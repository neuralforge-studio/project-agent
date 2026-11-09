#!/usr/bin/env python3
"""A/B benchmark of project-agent commands, Board and status line at N projects x S seats (PERF-001).

usage:
  python perf_bench.py run --exe BASE=PATH --exe CANDIDATE=PATH --workdir DIR --out DIR
                           [--scales 4x4,8x8,16x16] [--reps 3] [--groups startup,readonly,board_cli,lifecycle,steady]
                           [--cold-reps 3] [--cold-seconds 61] [--cold-units agent_review_clear,...]
                           [--steady-seconds 60] [--steady-reps 1]
  python perf_bench.py report --out DIR

PATH is a product tree: a checkout, `git archive vX.Y.Z | tar -x -C DIR`, or an installed release directory
(it needs tools/, integrations/tmux and tools/agent-session/tests/fixtures). The first --exe is the baseline,
the second the candidate; the same tree twice is an A/A run that shows the noise floor.

For each scale the benchmark builds an isolated environment (own tmux server, registry, git repositories,
cache directory; `bench_env.py`), then measures every unit with the two executables interleaved (A B A B ...),
so that the host load of one moment is not charged to one side only. `warm` rows run back to back. `cold` rows
run after an idle gap of --cold-seconds (default 61 s): the workstation's /primehome mount has acregmin=60, so
a command that follows another by more than a minute finds every file attribute expired.

Outputs in --out: results.jsonl (one row per command), meta.json, summary.json and summary.md (median, p90,
tmux and other process counts, the candidate/baseline ratios and the host load, per scale x mode x operation).
The environment lives in --workdir and is removed at the end. Choose a --workdir on the file system whose cost
is being measured (the workstation's NFS home), never a path inside a seat or the user's own tmux state.
"""
import argparse
import json
import platform
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

import bench_env
import bench_ops
from bench_env import Environment, load_average, parse_executable

READONLY_UNITS = ("project_item_ls", "project_item_check", "agent_review_clear", "agent_watch", "status_script", "board_model")
COLD_UNITS = ("agent_review_clear", "project_item_ls", "status_script", "board_model")


# ---------------------------------------------------------------------- statistics
def percentile(values, fraction):
    """Linear interpolation between the closest ranks (the `inclusive` method)."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _count(row, which):
    spawns = row.get("spawns", {})
    if which == "tmux":
        return spawns.get("tmux", 0)
    return sum(v for k, v in spawns.items() if k != "tmux")


def aggregate(rows):
    """{(scale, mode, op): {exe: stats}} from result rows; a failed row only counts in `failed`."""
    groups = {}
    for row in rows:
        if row["op"].startswith("steady_board"):
            continue
        groups.setdefault((row["scale"], row["mode"], row["op"]), {}).setdefault(row["exe"], []).append(row)
    out = {}
    for key, per_exe in groups.items():
        out[key] = {}
        for exe, items in per_exe.items():
            good = [r for r in items if r["rc"] == 0]
            if not good:
                out[key][exe] = {"n": 0, "failed": len(items)}
                continue
            walls = [r["wall"] for r in good]
            out[key][exe] = {
                "n": len(good), "failed": len(items) - len(good), "median": statistics.median(walls),
                "p90": percentile(walls, 0.9), "min": min(walls), "max": max(walls),
                "tmux": statistics.median(_count(r, "tmux") for r in good),
                "other": statistics.median(_count(r, "other") for r in good),
                "other_by_name": {name: statistics.median(r["spawns"].get(name, 0) for r in good)
                                  for name in sorted({k for r in good for k in r["spawns"] if k != "tmux"})},
                "sleep": statistics.median(r.get("sleep", 0) for r in good),
                "pane_tmux": statistics.median(r.get("pane_spawns", {}).get("tmux", 0) for r in good),
                "load": statistics.median(r["load"] for r in good)}
    return out


def ratio(candidate, baseline):
    return None if not baseline else candidate / baseline


def summarize(rows, names):
    """The JSON summary: every operation's stats per executable and the candidate/baseline ratios."""
    base, candidate = names[0], names[-1]
    summary = []
    for (scale, mode, op), per_exe in sorted(aggregate(rows).items()):
        entry = {"scale": scale, "mode": mode, "op": op, "exe": per_exe}
        if base in per_exe and candidate in per_exe and per_exe[base].get("n") and per_exe[candidate].get("n"):
            a, b = per_exe[base], per_exe[candidate]
            entry["ratio"] = {"median": ratio(b["median"], a["median"]), "p90": ratio(b["p90"], a["p90"]),
                              "tmux": ratio(b["tmux"], a["tmux"]), "other": ratio(b["other"], a["other"])}
        summary.append(entry)
    steady = [r for r in rows if r["op"].startswith("steady_board")]
    return {"baseline": base, "candidate": candidate, "operations": summary, "steady": steady}


def _ratio(value):
    return "-" if value is None else f"{value:.2f}"


def markdown(summary, meta):
    base, candidate = summary["baseline"], summary["candidate"]
    lines = [f"# project-agent benchmark: {candidate} against {base}", ""]
    for key in ("started", "host", "python", "tmux", "workdir_mount"):
        if key in meta:
            lines.append(f"- {key}: {meta[key]}")
    lines += [f"- executables: " + ", ".join(f"{k} = {v}" for k, v in meta.get("executables", {}).items()),
              f"- reps {meta.get('reps')}, cold reps {meta.get('cold_reps')} after {meta.get('cold_seconds')} s idle", ""]
    modes = sorted({(e["scale"], e["mode"]) for e in summary["operations"]},
                   key=lambda item: (int(item[0].split("x")[0]) * int(item[0].split("x")[1]), item[1] != "warm"))
    for scale, mode in modes:
        lines += [f"## {scale} {mode}", "",
                  f"| operation | {base} median s | p90 | {candidate} median s | p90 | ratio median | ratio p90 | "
                  f"tmux {base} -> {candidate} | other {base} -> {candidate} | sleep s | load |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for entry in summary["operations"]:
            if (entry["scale"], entry["mode"]) != (scale, mode):
                continue
            a, b = entry["exe"].get(base, {}), entry["exe"].get(candidate, {})
            if not a.get("n") or not b.get("n"):
                continue
            ratios = entry.get("ratio", {})
            lines.append(f"| {entry['op']} | {a['median']:.3f} | {a['p90']:.3f} | {b['median']:.3f} | {b['p90']:.3f} | "
                         f"{_ratio(ratios.get('median'))} | {_ratio(ratios.get('p90'))} | {a['tmux']:g} -> {b['tmux']:g} | "
                         f"{a['other']:g} -> {b['other']:g} | {a['sleep']:g} -> {b['sleep']:g} | "
                         f"{a['load']:.0f}/{b['load']:.0f} |")
        lines.append("")
    if summary["steady"]:
        lines += ["## steady cost (Board panes, one client, status-interval 1)", "",
                  "| scale | exe | board panes | seconds | board CPU s | status runs | status CPU s | tmux spawns | other spawns | load |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for r in sorted(summary["steady"], key=lambda r: (r["scale"], r["op"], r["exe"])):
            other = sum(v for k, v in r["spawns"].items() if k != "tmux")
            lines.append(f"| {r['scale']} | {r['exe']} | {r['board_panes']} ({r['op'][-1]}) | {r['wall']:.0f} | "
                         f"{r['board_cpu']} | {r['status_runs']} | {r['status_cpu']} | {r['spawns'].get('tmux', 0)} | "
                         f"{other} | {r['load']:.0f} |")
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------- run
def make_units(bench):
    units = {"startup": bench.startup, "board_cli": bench.board_cli, "lifecycle": bench.lifecycle}
    for name in READONLY_UNITS:
        units[name] = lambda exe, name=name: bench.readonly(exe, {name})
    return units


def _meta(args, exes):
    mount = subprocess.run(["findmnt", "-T", str(args.workdir), "-no", "FSTYPE,OPTIONS"], capture_output=True, text=True).stdout.strip()
    tmux = subprocess.run(["tmux", "-V"], capture_output=True, text=True).stdout.strip()
    return {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "host": platform.node(), "python": sys.version.split()[0],
            "tmux": tmux, "workdir_mount": mount[:200], "executables": {e.name: str(e.root) for e in exes},
            "scales": args.scales, "reps": args.reps, "cold_reps": args.cold_reps, "cold_seconds": args.cold_seconds,
            "groups": args.groups, "load_at_start": load_average()}


def run(args):
    exes = [parse_executable(text) for text in args.exe]
    if len(exes) != 2:
        raise SystemExit("give --exe twice: the baseline first, then the candidate")
    if exes[0].name == exes[1].name:
        raise SystemExit("the two executables need different names")
    out, workdir = Path(args.out), Path(args.workdir)
    out.mkdir(parents=True, exist_ok=True)
    workdir.mkdir(parents=True, exist_ok=True)
    results = out / "results.jsonl"
    results.unlink(missing_ok=True)
    meta = _meta(args, exes)
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    recorder = bench_ops.Recorder(results)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))      # end through the finally below, which releases the server
    for scale in args.scales:
        projects, seats = map(int, scale.split("x"))
        env = Environment(workdir, projects, seats)
        print(f"== {scale}: building (load {load_average():.0f})", flush=True)
        built = env.build()
        print(f"== {scale}: built in {built:.0f} s", flush=True)
        bench = bench_ops.Bench(env, recorder)
        units = make_units(bench)
        try:
            warm = [u for u in ("startup", *READONLY_UNITS, "board_cli", "lifecycle") if u in args.warm_units]
            bench.mode = "warm"
            for rep in range(1, args.reps + 1):
                bench.rep = rep
                for unit in warm:
                    for exe in exes:                              # A B A B: one unit, both executables, then the next unit
                        units[unit](exe)
            cold = [u for u in args.cold_units if u in units]
            bench.mode = "cold"
            for rep in range(1, args.cold_reps + 1):
                bench.rep = rep
                for unit in cold:
                    for exe in exes:
                        time.sleep(args.cold_seconds)
                        units[unit](exe)
            if "steady" in args.groups:
                bench.mode, bench.rep = "warm", 1
                for rep in range(1, args.steady_reps + 1):
                    bench.rep = rep
                    for panes in (1, 4):
                        for exe in exes:
                            bench.steady(exe, panes, args.steady_seconds)
        finally:
            bench.detach()
            env.teardown()
    report(out)


def report(out):
    out = Path(out)
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines() if line]
    meta = json.loads((out / "meta.json").read_text())
    names = list(meta["executables"])
    summary = summarize(rows, names)
    (out / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    text = markdown(summary, meta)
    (out / "summary.md").write_text(text)
    print(text)


def parse(argv=None):
    parser = argparse.ArgumentParser(description="A/B benchmark of project-agent (see the module docstring).")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--exe", action="append", required=True, metavar="NAME=PATH")
    run_parser.add_argument("--workdir", required=True)
    run_parser.add_argument("--out", required=True)
    run_parser.add_argument("--scales", default="4x4,8x8,16x16", type=lambda s: [x for x in s.split(",") if x])
    run_parser.add_argument("--reps", type=int, default=3)
    run_parser.add_argument("--groups", default="startup,readonly,board_cli,lifecycle,steady",
                            type=lambda s: [x for x in s.split(",") if x])
    run_parser.add_argument("--cold-reps", type=int, default=3)
    run_parser.add_argument("--cold-seconds", type=float, default=61)
    run_parser.add_argument("--cold-units", default=",".join(COLD_UNITS), type=lambda s: [x for x in s.split(",") if x])
    run_parser.add_argument("--steady-seconds", type=float, default=60)
    run_parser.add_argument("--steady-reps", type=int, default=1)
    report_parser = sub.add_parser("report")
    report_parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.command == "run":
        unknown = set(args.groups) - set(bench_ops.GROUPS)
        if unknown:
            raise SystemExit(f"unknown groups {sorted(unknown)}; choose from {bench_ops.GROUPS}")
        args.warm_units = []
        if "startup" in args.groups:
            args.warm_units.append("startup")
        if "readonly" in args.groups:
            args.warm_units += READONLY_UNITS
        args.warm_units += [g for g in ("board_cli", "lifecycle") if g in args.groups]
        for scale in args.scales:
            if not (scale.count("x") == 1 and all(p.isdigit() and int(p) >= 1 for p in scale.split("x"))):
                raise SystemExit(f"a scale is PROJECTSxSEATS, for example 16x16, not {scale!r}")
    return args


def main(argv=None):
    args = parse(argv)
    if args.command == "run":
        run(args)
    else:
        report(args.out)


if __name__ == "__main__":
    main()
