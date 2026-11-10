"""The benchmark tool's own checks (PERF-001): statistics and report format without a server, and one small A/A run."""
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import perf_bench  # noqa: E402
import bench_env  # noqa: E402

REPOSITORY = Path(__file__).resolve().parents[3]


def test_percentile_interpolates_between_ranks():
    assert perf_bench.percentile([1.0], 0.9) == 1.0
    assert perf_bench.percentile([1.0, 2.0, 3.0], 0.5) == 2.0
    assert perf_bench.percentile([0.0, 10.0], 0.9) == pytest.approx(9.0)
    assert perf_bench.percentile([5.0, 1.0, 3.0, 2.0, 4.0], 0.9) == pytest.approx(4.6)


def row(exe, op, wall, tmux=0, git=0, rc=0, mode="warm", scale="2x2", load=10.0, pane_tmux=0, cpu=None):
    return {"exe": exe, "scale": scale, "mode": mode, "rep": 1, "op": op, "wall": wall, "cpu": cpu, "rc": rc, "load": load,
            "spawns": {k: v for k, v in (("tmux", tmux), ("git", git)) if v},
            "pane_spawns": {"tmux": pane_tmux} if pane_tmux else {}}


def test_summary_and_markdown_give_median_interval_counts_ratios_and_verdicts():
    old = [1.0, 1.1, 0.9, 1.05, 0.95, 1.0, 1.02, 0.98, 1.0]
    new = [0.5, 0.55, 0.45, 0.52, 0.48, 0.5, 0.51, 0.49, 0.5]
    rows = [row("old", "ls", w, cpu=w / 2) for w in old] + [row("new", "ls", w, cpu=w * 2) for w in new]
    rows += [row("old", "ls", 99.0, rc=1)]                                    # a failed command is not a timing
    rows += [row("old", "ls", 5.0, tmux=32, mode="count"), row("new", "ls", 5.0, tmux=8, mode="count")]   # the counting pass
    summary = perf_bench.summarize(rows, ["old", "new"])
    (entry,) = summary["operations"]                                           # a count row is not a timing row
    old_stats, new_stats = entry["exe"]["old"], entry["exe"]["new"]
    assert old_stats["median"] == 1.0 and old_stats["failed"] == 1 and old_stats["n"] == 9
    assert old_stats["ci"][0] <= 1.0 <= old_stats["ci"][1] and new_stats["tmux"] == 8
    assert entry["ratio"]["median"] == pytest.approx(0.5) and entry["ratio"]["tmux"] == pytest.approx(0.25)
    assert entry["ratio"]["verdict"] == "improved" and entry["ratio"]["ci"][1] < 1      # the whole interval is below 1
    assert entry["ratio"]["cpu"] == pytest.approx(2.0) and entry["ratio"]["cpu_verdict"] == "worse"   # the cpu doubled
    text = perf_bench.markdown(summary, {"executables": {"old": "/a", "new": "/b"}, "reps": 9})
    assert "## 2x2 warm" in text and "| ls | 9/9 | 1.000 [" in text and "| improved |" in text and "32 -> 8" in text


def test_the_same_values_on_both_sides_are_not_called_an_improvement():
    values = [1.0, 1.4, 0.8, 1.2, 0.9, 1.1, 1.3, 0.7, 1.0]
    rows = [row(name, "ls", w) for name in ("a", "b") for w in values]
    (entry,) = perf_bench.summarize(rows, ["a", "b"])["operations"]
    assert entry["ratio"]["verdict"] == "same" and entry["ratio"]["ci"][0] < 1 < entry["ratio"]["ci"][1]


def test_few_repetitions_give_no_interval_and_no_verdict():
    rows = [row(name, "ls", w) for name in ("a", "b") for w in (1.0, 2.0)]
    (entry,) = perf_bench.summarize(rows, ["a", "b"])["operations"]
    assert entry["exe"]["a"]["ci"] is None and entry["ratio"]["verdict"] == "-"


def test_server_side_processes_count_toward_the_command():
    rows = [row("old", "start", 1.0), row("new", "start", 1.0)]
    rows += [row("old", "start", 1.0, tmux=10, pane_tmux=5, mode="count"), row("new", "start", 1.0, tmux=10, mode="count")]
    (entry,) = perf_bench.summarize(rows, ["old", "new"])["operations"]
    assert entry["exe"]["old"]["tmux"] == 15 and entry["exe"]["new"]["tmux"] == 10


def test_ratio_is_empty_without_a_baseline_value():
    rows = [row("old", "x", 1.0), row("new", "x", 1.0), row("old", "x", 1.0, mode="count"),
            row("new", "x", 1.0, git=2, mode="count")]
    (entry,) = perf_bench.summarize(rows, ["old", "new"])["operations"]
    assert entry["ratio"]["other"] is None


def test_executable_needs_a_full_tree(tmp_path):
    with pytest.raises(SystemExit):
        bench_env.parse_executable(f"x={tmp_path}")
    with pytest.raises(SystemExit):
        bench_env.parse_executable("no-separator")


def isolated_copy(tmp_path):
    """A copy of the product whose launchers start Python with `-I -S`, as PERF-002's candidate may: no PYTHONPATH,
    no site, so nothing of the benchmark can be injected through the interpreter."""
    root = tmp_path / "isolated"
    ignore = shutil.ignore_patterns("__pycache__", "docs", "install", "skills", ".git")
    shutil.copytree(REPOSITORY / "tools", root / "tools", ignore=ignore, symlinks=True)
    shutil.copytree(REPOSITORY / "integrations", root / "integrations", ignore=ignore)
    agent = root / "tools" / "agent-session" / "bin" / "agent-session"
    text = agent.read_text()
    assert 'exec "$agent_session_python" -c' in text
    agent.write_text(text.replace('exec "$agent_session_python" -c', 'exec "$agent_session_python" -I -S -c'))
    item = root / "tools" / "project-item" / "bin" / "project-item"
    text = item.read_text()
    assert 'exec "$PY" -m project_item "$@"' in text
    item.write_text(text.replace('exec "$PY" -m project_item "$@"', 'exec "$PY" -I -S -c \'import sys; sys.path.insert(0, sys.argv.pop(1)); '
                                 'from project_item.cli import main; sys.argv[0] = "project-item"; sys.exit(main())\' "$ROOT" "$@"'))
    return root


@pytest.mark.skipif(not shutil.which("tmux") or not shutil.which("git"), reason="tmux and git are required")
def test_small_run_with_an_isolated_candidate_counts_the_same_and_leaves_no_server(tmp_path):
    sockets = Path(f"/tmp/tmux-{os.getuid()}")
    before = set(p.name for p in sockets.glob("perf-2x2-*")) if sockets.exists() else set()
    out = tmp_path / "out"
    candidate = isolated_copy(tmp_path)
    perf_bench.main(["run", "--exe", f"a={REPOSITORY}", "--exe", f"b={candidate}", "--workdir", str(tmp_path / "work"),
                     "--out", str(out), "--scales", "2x2", "--reps", "1", "--cold-reps", "0",
                     "--groups", "readonly,lifecycle,steady", "--steady-seconds", "2"])
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()]
    assert {r["exe"] for r in rows} == {"a", "b"} and all(r["rc"] == 0 for r in rows)
    assert {"agent_start_worker", "agent_send_to_worker", "agent_finish_ended", "project_item_ls", "board_liveness",
            "status_cache_valid", "steady_board_1"} <= {r["op"] for r in rows}
    assert {r["mode"] for r in rows} == {"count", "warm"}
    assert any(r["cpu"] and r["cpu"] > 0 for r in rows if r["op"] == "project_item_ls")      # the command's own CPU is recorded
    assert not any(r["spawns"] or r["pane_spawns"] for r in rows if r["mode"] == "warm")        # no shim in a timing pass
    summary = json.loads((out / "summary.json").read_text())
    by = {(e["op"]): e["exe"] for e in summary["operations"] if e["mode"] == "warm"}
    # `-I -S` must not change what is counted: a counter inside the interpreter would read 0 for b. (A tmux read that
    # sees a window change is repeated, so a count may differ by a few between two runs of the same command.)
    for op in ("project_item_ls", "agent_review_clear", "agent_watch", "agent_review", "agent_send_to_worker",
               "project_item_accept", "board_liveness"):
        a, b = by[op]["a"]["tmux"], by[op]["b"]["tmux"]
        assert a > 0 and b > 0 and abs(a - b) <= max(2, 0.2 * a), (op, a, b)
    start = by["agent_start_worker"]["a"]
    assert start["tmux"] > 0 and any(r["pane_spawns"].get("tmux") for r in rows if r["op"] == "agent_start_worker")
    assert summary["baseline"] == "a" and summary["candidate"] == "b" and summary["steady"]
    text = (out / "summary.md").read_text()
    assert "## 2x2 warm" in text and "| agent_start_worker |" in text and "## steady cost" in text
    leftover = (set(p.name for p in sockets.glob("perf-2x2-*")) if sockets.exists() else set()) - before
    assert not leftover and not (tmp_path / "work" / "2x2").exists()
