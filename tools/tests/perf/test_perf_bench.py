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


def row(exe, op, wall, tmux=0, git=0, rc=0, mode="warm", scale="2x2", load=10.0, pane_tmux=0):
    return {"exe": exe, "scale": scale, "mode": mode, "rep": 1, "op": op, "wall": wall, "rc": rc, "load": load,
            "spawns": {k: v for k, v in (("tmux", tmux), ("git", git)) if v},
            "pane_spawns": {"tmux": pane_tmux} if pane_tmux else {}}


def test_summary_and_markdown_give_median_p90_counts_and_ratios():
    rows = [row("old", "ls", w) for w in (1.0, 2.0, 3.0)] + [row("new", "ls", w) for w in (0.5, 1.0, 1.5)]
    rows += [row("old", "ls", 99.0, rc=1)]                                    # a failed command is not a timing
    rows += [row("old", "ls", 5.0, tmux=32, mode="count"), row("new", "ls", 5.0, tmux=8, mode="count")]   # the counting pass
    summary = perf_bench.summarize(rows, ["old", "new"])
    (entry,) = summary["operations"]                                           # a count row is not a timing row
    assert entry["exe"]["old"]["median"] == 2.0 and entry["exe"]["old"]["failed"] == 1
    assert entry["exe"]["old"]["p90"] == pytest.approx(2.8) and entry["exe"]["new"]["tmux"] == 8
    assert entry["ratio"]["median"] == pytest.approx(0.5) and entry["ratio"]["tmux"] == pytest.approx(0.25)
    text = perf_bench.markdown(summary, {"executables": {"old": "/a", "new": "/b"}, "reps": 3})
    assert "## 2x2 warm" in text and "| ls | 2.000 | 2.800 | 1.000 | 1.400 | 0.50 | 0.50 | 32 -> 8 |" in text


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
