"""The Rust sidebar reads a project's cron section like `agent_session.cron` does (BOARD-027).

The crontab section of a project and the rule for its next run belong to `agent_session.cron` (docs/project-team/spec.md,
cron). The sidebar follows them in `rust/src/cron.rs` and `rust/src/data/crontab.rs`, so the rules exist twice. Like
`test_rust_equivalence.py` this gives both sides the same input and requires the same answer, and the expected values
come from the Python code: for each crontab text and project, the number of jobs and the nearest next run
(`cron.listing(..., summary=True)`), or that the section is broken (`cron_invalid`).

The hand-written next runs and invalid schedules of `agent-session/tests/fixtures/cron_next_run.json` are checked by
the Rust unit tests (`rust/src/cron.rs`), which read that file in place; the time-to-next-run texts of
`fixtures/cron_remaining.json` are checked by the Rust unit tests and by `test_model.py`.
"""
import datetime as dt
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import board_testing  # noqa: F401  (adds the Board tool to sys.path)
import rust_binary
from project_board import model  # noqa: F401  (puts agent_session on sys.path)
from agent_session import cron
from agent_session.errors import SessionError


@pytest.fixture(scope="session")
def sidebar_bin():
    try:
        return rust_binary.sidebar_binary()
    except rust_binary.RustBinaryError as error:
        pytest.fail(f"the Rust sidebar binary is not available: {error}", pytrace=False)


def section(name, *jobs, end=True):
    lines = [f"# >>> project-agent: {name} >>>"]
    for job_id, schedule, command in jobs:
        lines += [f"# job {job_id}: about {job_id}", f"{schedule} {command}"]
    if end:
        lines.append(f"# <<< project-agent: {name} <<<")
    return "\n".join(lines) + "\n"


CHECK = ("check", "13,43 * * * *", "/x/agent-session check --project a >/dev/null 2>&1")
NIGHTLY = ("nightly", "0 3 * * *", "run \\% x")
NEVER = ("never", "0 0 30 2 *", "true")
WEEKLY = ("weekly", "30 8 * * 1-5", "report")
USER = "MAILTO=me\n0 1 * * * backup.sh\n\n"

CRONTABS = {
    "two projects among the user's own lines": USER + section("a", CHECK, NIGHTLY) + "\n" + section("b", WEEKLY) + "5 5 * * * after\n",
    "no crontab": "",
    "only the user's lines": USER,
    "an empty section": section("a"),
    "a section of another project only": section("b", CHECK),
    "no trailing newline": (USER + section("a", CHECK)).rstrip("\n"),
    "blank lines inside a section": "# >>> project-agent: a >>>\n\n# job check: x\n\n13 * * * * c\n\n# <<< project-agent: a <<<\n",
    "a job that never runs again": section("a", NEVER, NIGHTLY),
    "only a job that never runs again": section("a", NEVER),
    "tabs and runs of spaces in a job line": "# >>> project-agent: a >>>\n# job t: x\n0\t3   *  * *\tcmd  with  spaces\n# <<< project-agent: a <<<\n",
    "a day of month and a day of week": section("a", ("both", "0 12 13 * 5", "c"), ("star", "*/20 * * * 0", "c")),
    "no end line": section("a", CHECK, end=False),
    "a repeated section": section("a", CHECK) + section("a", NIGHTLY),
    "the end before the begin": "# <<< project-agent: a <<<\n# >>> project-agent: a >>>\n",
    "a begin only": "# >>> project-agent: a >>>\n",
    "an end only": "# <<< project-agent: a <<<\n",
    "a job comment without its schedule line": "# >>> project-agent: a >>>\n# job c: x\n# <<< project-agent: a <<<\n",
    "two job comments in a row": "# >>> project-agent: a >>>\n# job c: x\n# job d: y\n0 1 * * * z\n# <<< project-agent: a <<<\n",
    "a schedule line without a job comment": "# >>> project-agent: a >>>\n0 1 * * * z\n# <<< project-agent: a <<<\n",
    "a comment inside a section": "# >>> project-agent: a >>>\n# remark\n# <<< project-agent: a <<<\n",
    "a job comment with a bad id": "# >>> project-agent: a >>>\n# job Bad: x\n0 1 * * * z\n# <<< project-agent: a <<<\n",
    "a schedule that is not valid": section("a", ("c", "61 * * * *", "z")),
    "a schedule with a name": section("a", ("c", "0 3 * jan *", "z")),
    "a macro": section("a", ("c", "@daily", "z")),
    "a job line with no command": "# >>> project-agent: a >>>\n# job c: x\n0 1 * * *\n# <<< project-agent: a <<<\n",
    "a broken section beside a good one": section("a", CHECK) + "# >>> project-agent: b >>>\n# job c: x\n",
    "a good section beside a broken one": "# >>> project-agent: b >>>\n# job c: x\n" + section("a", CHECK),
    "a carriage return at the end of the end line": "# >>> project-agent: a >>>\r\n# job c: x\r\n0 1 * * * z\r\n# <<< project-agent: a <<<\r\n",
    "names that differ in case": section("A", CHECK) + section("a", NIGHTLY),
    "a name with a dot": section("a.b", CHECK) + section("a", NIGHTLY),
}
PROJECTS = ["a", "b", "A", "a.b", "none"]
NOWS = ["2026-11-12T10:00:30", "2026-11-12T23:59:00", "2026-12-31T23:59:59", "2028-02-28T03:00:00", "2026-11-13T08:30:00"]


def python_side(text, now):
    """Per project: `{"count", "next_run"}` from `cron.listing(summary=True)`, or `{"error": True}`."""
    crontab = SimpleNamespace(read=lambda: text)
    result = {}
    for project_id in PROJECTS:
        project = SimpleNamespace(project_id=project_id, runtime_path=Path("/nonexistent"))
        try:
            summary = cron.listing(project, crontab, now=now, summary=True)
            result[project_id] = {"count": summary["count"], "next_run": summary["next_run"]}
        except SessionError as error:
            assert error.code == "cron_invalid", error
            result[project_id] = {"error": True}
    return result


def rust_side(binary, tmp_path, text, now):
    path = tmp_path / "crontab.txt"
    path.write_bytes(text.encode("utf-8"))
    command = [str(binary), "dump", "cron", "--crontab", str(path), "--now", now.strftime("%Y-%m-%dT%H:%M")]
    for project_id in PROJECTS:
        command += ["--project", project_id]
    out = json.loads(subprocess.run(command, capture_output=True, text=True, check=True, timeout=30).stdout)
    return {project_id: ({"error": True} if "error" in value else value) for project_id, value in out.items()}


@pytest.mark.parametrize("name", list(CRONTABS))
def test_a_crontab_gives_the_same_jobs_and_next_run_per_project(sidebar_bin, tmp_path, name):
    text = CRONTABS[name]
    for now_text in NOWS:
        now = dt.datetime.fromisoformat(now_text)
        assert rust_side(sidebar_bin, tmp_path, text, now) == python_side(text, now), (name, now_text)


def test_the_cases_cover_counts_next_runs_and_broken_sections():
    """The comparison is not vacuous: Python gives jobs, none and an error for these crontabs."""
    now = dt.datetime(2026, 11, 12, 10, 0, 30)
    views = [python_side(text, now) for text in CRONTABS.values()]
    assert any(view["a"].get("count", 0) >= 2 for view in views)
    assert any(view["a"] == {"count": 0, "next_run": None} for view in views)
    assert any(view["a"] == {"count": 1, "next_run": None} for view in views)          # a job that never runs again
    assert sum("error" in view["a"] for view in views) >= 10
    assert any(view["a"].get("next_run") == "2026-11-12T10:13" for view in views)
