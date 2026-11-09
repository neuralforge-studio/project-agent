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


def row(exe, op, wall, tmux=0, git=0, rc=0, mode="warm", scale="2x2", load=10.0):
    return {"exe": exe, "scale": scale, "mode": mode, "rep": 1, "op": op, "wall": wall, "rc": rc, "load": load,
            "spawns": {k: v for k, v in (("tmux", tmux), ("git", git)) if v}, "sleep": 0.5, "pane_spawns": {}}


def test_summary_and_markdown_give_median_p90_counts_and_ratios():
    rows = [row("old", "ls", w, tmux=32) for w in (1.0, 2.0, 3.0)] + [row("new", "ls", w, tmux=8) for w in (0.5, 1.0, 1.5)]
    rows += [row("old", "ls", 99.0, rc=1)]                                    # a failed command is not a timing
    summary = perf_bench.summarize(rows, ["old", "new"])
    (entry,) = summary["operations"]
    assert entry["exe"]["old"]["median"] == 2.0 and entry["exe"]["old"]["failed"] == 1
    assert entry["exe"]["old"]["p90"] == pytest.approx(2.8) and entry["exe"]["new"]["tmux"] == 8
    assert entry["ratio"]["median"] == pytest.approx(0.5) and entry["ratio"]["tmux"] == pytest.approx(0.25)
    text = perf_bench.markdown(summary, {"executables": {"old": "/a", "new": "/b"}, "reps": 3})
    assert "## 2x2 warm" in text and "| ls | 2.000 | 2.800 | 1.000 | 1.400 | 0.50 | 0.50 | 32 -> 8 |" in text


def test_ratio_is_empty_without_a_baseline_value():
    rows = [row("old", "x", 1.0), row("new", "x", 1.0, git=2)]
    (entry,) = perf_bench.summarize(rows, ["old", "new"])["operations"]
    assert entry["ratio"]["other"] is None


def test_executable_needs_a_full_tree(tmp_path):
    with pytest.raises(SystemExit):
        bench_env.parse_executable(f"x={tmp_path}")
    with pytest.raises(SystemExit):
        bench_env.parse_executable("no-separator")


@pytest.mark.skipif(not shutil.which("tmux") or not shutil.which("git"), reason="tmux and git are required")
def test_small_a_a_run_writes_rows_summary_and_leaves_no_server(tmp_path):
    sockets = Path(f"/tmp/tmux-{os.getuid()}")
    before = set(p.name for p in sockets.glob("perf-2x2-*")) if sockets.exists() else set()
    out = tmp_path / "out"
    perf_bench.main(["run", "--exe", f"a={REPOSITORY}", "--exe", f"b={REPOSITORY}", "--workdir", str(tmp_path / "work"),
                     "--out", str(out), "--scales", "2x2", "--reps", "1", "--cold-reps", "0",
                     "--groups", "readonly,lifecycle,steady", "--steady-seconds", "2"])
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()]
    assert {r["exe"] for r in rows} == {"a", "b"}
    assert all(r["rc"] == 0 for r in rows)
    ops = {r["op"] for r in rows}
    assert {"agent_start_worker", "agent_send_to_worker", "agent_finish_ended", "project_item_ls", "board_liveness",
            "status_cache_valid", "steady_board_1"} <= ops
    start = next(r for r in rows if r["op"] == "agent_start_worker")
    assert start["spawns"]["tmux"] > 0 and start["pane_spawns"]["tmux"] > 0          # the Worker's registration is counted too
    liveness = next(r for r in rows if r["op"] == "board_liveness")
    assert liveness["spawns"]["tmux"] > 0
    summary = json.loads((out / "summary.json").read_text())
    assert summary["baseline"] == "a" and summary["candidate"] == "b" and summary["steady"]
    text = (out / "summary.md").read_text()
    assert "## 2x2 warm" in text and "| agent_start_worker |" in text and "## steady cost" in text
    leftover = (set(p.name for p in sockets.glob("perf-2x2-*")) if sockets.exists() else set()) - before
    assert not leftover and not (tmp_path / "work" / "2x2").exists()
