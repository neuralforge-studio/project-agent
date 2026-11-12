"""The Rust sidebar's data layer gives the Python model's answers (BOARD-018).

The sidebar reads the project files itself (`tools/project-board/rust/src/data`), so the rules of the registry,
state.json, the CR and decision files and run liveness exist twice: in Python (`project_board.model`,
`agent_session`, `project_item`) and in Rust. These tests build the same files on disk, ask Python
(`model.snapshot`, `model.liveness`) and the Rust binary (`dump`, the same three reads in the same order:
snapshot, liveness, snapshot) and require the same facts. The expected values come from the Python
implementation; nothing here computes them a second time.

What is compared is what the sidebar shows (`rust/src/model.rs`): CR counts, decision stages, per seat the
status, host, path, session, elapsed time and CR title, the Leader's elapsed time, each project's error rows
(source and message) and the registry error message, and per slot the liveness verdict.

Known differences, stated where the test normalizes them:
- A project whose liveness fails for a reason other than a missing state is `{"error": ...}` in Python and `{}`
  in Rust (the sidebar never shows it). A registry that cannot be read makes `model.liveness` raise; Rust gives `{}`.
- The verdicts of remote seats come from SSH and so from Python: Rust runs `project-board liveness --project`
  (here a fake launcher) and the Python side of the test replaces the SSH call.
"""
import datetime as dt
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from board_testing import BASE_HASH, LEADER_ID, WORKER_IDS, Board, cr_text, decide_text, leader, session
import rust_binary
from wait_limit import command_timeout
from project_board import model
from agent_session.errors import SessionError

NOW = dt.datetime(2026, 11, 5, 10, 30, tzinfo=dt.timezone.utc)
NOW_TEXT = "2026-11-05T10:30:00Z"
STAGES = ("결정 대기", "답변 접수", "반영 중", "완료")
SUBMIT = "a" * 40
OTHER = "c" * 40
NO_SESSION = {"job_id": None, "git_hash": None, "session": None}


@pytest.fixture(scope="session")
def sidebar_bin():
    try:
        return rust_binary.sidebar_binary()
    except rust_binary.RustBinaryError as error:
        pytest.fail(f"the Rust sidebar binary is not available: {error}", pytrace=False)


@pytest.fixture
def board(tmp_path):
    return Board(tmp_path)


@pytest.fixture(autouse=True)
def fresh_python_model(tmp_path, monkeypatch):
    """The model keeps module-level caches and release holds; each test starts without them and, unless it builds a
    tmux server, reads a socket nobody listens on instead of the user's server."""
    for cache in (model._cache, model._unchanged_cache, model._registry_cache, model._releases):
        cache.clear()
    monkeypatch.setenv("AGENT_SESSION_SOCKET", str(tmp_path / "no-tmux-server.sock"))


# ------------------------------------------------------------------ the two sides
def slim(view):
    """`model.snapshot()` reduced to what the sidebar uses (`rust/src/model.rs`)."""
    if view["error"]:
        return {"error": view["error"]["message"], "projects": []}
    projects = []
    for project in view["projects"]:
        crs, decide, leader_view = project["crs"], project["decide"], project["leader"]
        projects.append({
            "id": project["id"],
            "cr": None if crs is None else {state: len(crs[state]) for state in ("open", "todo", "in-progress")},
            "decide": None if decide is None else {
                "open": sum(item["state"] == "open" for item in decide),
                "stages": [sum(item["display_state"] == stage for item in decide) for stage in STAGES]},
            "errors": [{"source": e["source"], "message": e["message"]} for e in project["errors"]],
            "leader": None if leader_view is None else {"elapsed": leader_view["elapsed"]},
            "seats": [{key: seat[key] for key in ("index", "job_id", "status", "session", "host", "path",
                                                  "session_id", "elapsed", "title")} for seat in project["seats"]],
        })
    return {"error": None, "projects": projects}


def python_reads(config):
    """snapshot, liveness, snapshot of the Python model (the liveness sets the release holds the second shows)."""
    before = slim(model.snapshot(config, now=NOW))
    try:
        verdicts = model.liveness(config)
    except SessionError:                                    # a registry that cannot be read: Rust gives {}
        verdicts = {}
    liveness = {project: {} if "error" in slots else slots for project, slots in verdicts.items()}
    after = slim(model.snapshot(config, now=NOW))
    return {"before": before, "liveness": liveness, "after": after}


def rust_reads(binary, config, env=None):
    result = subprocess.run([str(binary), "dump", "--config", str(config), "--now", NOW_TEXT],
                            capture_output=True, text=True, timeout=command_timeout(), env={**os.environ, **(env or {})})
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def same(binary, board_or_config, env=None):
    """Both sides read the same files and give the same facts; returns the Python facts for further checks."""
    config = getattr(board_or_config, "config", board_or_config)
    expected = python_reads(config)
    assert rust_reads(binary, config, env) == expected
    return expected


def project_of(reads, name, which="before"):
    return next(project for project in reads[which]["projects"] if project["id"] == name)


def statuses(project):
    return [seat["status"] for seat in project["seats"]]


def workers(count):
    return [{"session_id": f"00000000-0000-4000-8000-{n:012d}", "endpoint": "unix:///tmp/x.sock",
             "connected_at": "2026-11-05T08:00:00Z"} for n in range(count)]


def put_state(base, count, rows, leader_session=None):
    """A state with `rows` ({seat number: (job, session or None)}) and no job on the other seats."""
    state = {"leader": leader() if leader_session is None else leader_session}
    for number in range(count):
        job, bound = rows.get(number, (None, None))
        state[str(number)] = {"job_id": job, "git_hash": None, "session": bound}
    Board.state(base, state)


# ------------------------------------------------------------------ seat states, counts, times
def test_the_seat_states_cr_counts_and_times_are_the_same(board, sidebar_bin):
    base = board.project("alpha", seats=5)
    board.cr(base, "in-progress", "TOOL-001", "Working")
    board.cr(base, "in-progress", "TOOL-002", "Submitted", result=f"- 제출 commit: `{SUBMIT}`")
    board.cr(base, "in-progress", "TOOL-003", "Reviewed", result=f"- 제출 commit: `{SUBMIT}`")
    board.cr(base, "in-progress", "TOOL-004", "Pending")
    board.cr(base, "open", "TOOL-010")
    board.cr(base, "open", "TOOL-012")
    board.cr(base, "todo", "TOOL-011")
    board.cr(base, "done", "TOOL-099", with_base=False)
    board.state(base, {
        "leader": leader(reviewing="TOOL-003"),
        "0": {"job_id": "TOOL-001", "git_hash": None, "session": session(0)},
        "1": {"job_id": "TOOL-002", "git_hash": None, "session": session(1, connected_at=None)},
        "2": {"job_id": "TOOL-003", "git_hash": None, "session": session(2)},
        "3": {"job_id": "TOOL-004", "git_hash": None, "session": None},
        "4": NO_SESSION,
    })
    reads = same(sidebar_bin, board)
    alpha = project_of(reads, "alpha")
    assert statuses(alpha) == ["working", "review_wait", "reviewing", "pending", "empty"]
    assert alpha["cr"] == {"open": 2, "todo": 1, "in-progress": 4}
    assert [seat["elapsed"] for seat in alpha["seats"]] == [9000, None, 9000, None, None]
    assert alpha["leader"] == {"elapsed": 91800}
    assert [seat["title"] for seat in alpha["seats"]] == ["Working", "Submitted", "Reviewed", "Pending", None]


def test_a_seat_without_a_published_session_or_cr_and_the_clock_before_the_connection(board, sidebar_bin):
    base = board.project("alpha", seats=3)
    board.cr(base, "in-progress", "TOOL-001", "Has a CR")
    board.state(base, {
        "leader": leader(connected_at="2026-11-05T11:00:00Z"),       # connected after `now`: elapsed is 0
        "0": {"job_id": "TOOL-001", "git_hash": None, "session": session(0, connected_at="2026-11-05T10:30:00Z")},
        "1": {"job_id": "TOOL-404", "git_hash": None, "session": session(1)},     # no CR of that JOB
        "2": {"job_id": "TOOL-005", "git_hash": None, "session": None},
    })
    reads = same(sidebar_bin, board)
    alpha = project_of(reads, "alpha")
    assert statuses(alpha) == ["working", "working", "pending"]
    assert [seat["elapsed"] for seat in alpha["seats"]] == [0, 9000, None]
    assert alpha["leader"] == {"elapsed": 0} and alpha["seats"][1]["title"] is None


def test_a_leader_without_a_connection_time_has_no_elapsed_time(board, sidebar_bin):
    base = board.project("alpha", seats=1)
    board.state(base, {"leader": leader(connected_at=None), "0": NO_SESSION})
    reads = same(sidebar_bin, board)
    assert project_of(reads, "alpha")["leader"] == {"elapsed": None}


def test_a_project_without_a_state_shows_an_empty_team_and_no_error(board, sidebar_bin):
    board.project("alpha", seats=2)
    reads = same(sidebar_bin, board)
    alpha = project_of(reads, "alpha")
    assert alpha["leader"] is None and alpha["errors"] == [] and statuses(alpha) == ["empty", "empty"]
    assert reads["liveness"] == {"alpha": {}}


def test_a_state_with_fewer_seat_rows_than_the_registry_is_fitted(board, sidebar_bin):
    base = board.project("alpha", seats=3)
    board.state(base, {"leader": leader(), "0": {"job_id": "TOOL-001", "git_hash": None, "session": session(0)}})
    reads = same(sidebar_bin, board)
    assert statuses(project_of(reads, "alpha")) == ["working", "empty", "empty"]


# ------------------------------------------------------------------ review wait and the format of CR files
def test_review_wait_for_write_and_read_only_crs(board, sidebar_bin):
    base = board.project("alpha", seats=6)
    board.cr(base, "in-progress", "TOOL-001", "ro empty", mode="read-only", result="  ")
    board.cr(base, "in-progress", "TOOL-002", "ro result", mode="read-only", result="조사 결과입니다.")
    board.cr(base, "in-progress", "TOOL-003", "cited", result=f"- 제출 commit: `{SUBMIT}`",
             disposition=f"- 2026-11-05 leader: `{SUBMIT[:12]}` 수정 요청.")
    board.cr(base, "in-progress", "TOOL-004", "short hash", result=f"- 제출 commit: `{SUBMIT}`",
             disposition=f"- 2026-11-05 leader: {SUBMIT[:6]} 인수.")
    board.cr(base, "in-progress", "TOOL-005", "older hash", result=f"- 제출 commit: `{SUBMIT}`",
             disposition=f"- 2026-11-05 leader: {OTHER} 검토.")
    board.cr(base, "in-progress", "TOOL-006", "inside a word", result=f"- 제출 commit: `{SUBMIT}`",
             disposition=f"- 2026-11-05 leader: zz{SUBMIT[:12]} 검토.")
    put_state(base, 6, {n: (f"TOOL-00{n + 1}", workers(6)[n]) for n in range(6)})
    reads = same(sidebar_bin, board)
    assert statuses(project_of(reads, "alpha")) == [
        "working", "review_wait", "working", "review_wait", "review_wait", "review_wait"]


def test_cr_files_in_unusual_formats(board, sidebar_bin):
    """Titles, ids, headers, fences, repeated sections and line ends, each read as `project_item.cr` reads them."""
    base = board.project("alpha", seats=11)
    root = base / "agent/cr/in-progress"
    head = "- Opened: 2026-11-05\n- Scope: s\n- Severity: S3\n"
    files = {
        "A-001-plain.md": ("# Plain title\n\n" + head + "\n## Result\n\n- 제출 commit: " + SUBMIT + "\n", "A-001-plain"),
        "B-001-notitle.md": ("no title line\n\n## Result\n\n- 제출 commit: " + SUBMIT + "\n", "B-001-notitle"),
        "C-001-crlf.md": (f"# C-001: Windows ends\r\n\r\n{head}\r\n## Result\r\n\r\n- 제출 commit: {SUBMIT}\r\n", "C-001"),
        "D-001-formfeed.md": (f"# D-001: Form feed\n\n{head}\n## Result\n\nintro\x0c- 제출 commit: {SUBMIT}\n", "D-001"),
        "E-001-status.md": (f"# E-001: Status lines\n\n- Status: x\n{head}- Mode: read-only\n\n## Result\n\ndone\n", "E-001"),
        "F-001-fence.md": (f"# F-001: Fenced heading\n\n{head}\n```\n## Result\n- 제출 commit: {SUBMIT}\n```\n\n## Result\n\n"
                           "nothing\n", "F-001"),
        "G-001-twice.md": (f"# G-001: Result twice\n\n{head}\n## Result\n\n- 제출 commit: {SUBMIT}\n\n## Result\n\n\n", "G-001"),
        "H-001-mode.md": (f"# H-001: Mode after text\n\n{head}\ntext\n- Mode: read-only\n\n## Result\n\n"
                          f"- 제출 commit: {SUBMIT}\n", "H-001"),
        "I-001-other.md": (f"# I-009: Id in the title\n\n{head}\n## Result\n\n- 제출 commit: {SUBMIT}\n", "I-009"),
        "J-001-unicode.md": (f"# J-001:   Title with spaces　 \n\n{head}\n", "J-001"),
        "K-001-hash.md": (f"# K-001: Hash\n\n{head}\n## Disposition\n\n{SUBMIT[:7]}\n\n## Result\n\n- 제출 commit: {SUBMIT}\n"
                          f"- 제출 commit: {OTHER}\n", "K-001"),
    }
    rows = {}
    for number, (name, (text, job)) in enumerate(files.items()):
        (root / name).write_bytes(text.encode("utf-8"))
        rows[number] = (job, workers(11)[number])
    put_state(base, 11, rows)
    reads = same(sidebar_bin, board)
    alpha = project_of(reads, "alpha")
    assert alpha["errors"] == []
    assert [seat["title"] for seat in alpha["seats"]] == [
        "Plain title", "B-001-notitle", "Windows ends", "Form feed", "Status lines", "Fenced heading",
        "Result twice", "Mode after text", "Id in the title", "Title with spaces", "Hash"]
    assert statuses(alpha) == ["review_wait", "review_wait", "review_wait", "review_wait", "review_wait", "working",
                               "working", "review_wait", "review_wait", "working", "review_wait"]


def test_the_cr_title_names_the_job_not_the_file_name(board, sidebar_bin):
    base = board.project("alpha", seats=2)
    path = board.cr(base, "in-progress", "TOOL-001", "Renamed file")
    path.rename(path.with_name("TOOL-777-renamed.md"))
    put_state(base, 2, {0: ("TOOL-001", workers(2)[0]), 1: ("TOOL-777", workers(2)[1])})
    reads = same(sidebar_bin, board)
    assert [seat["title"] for seat in project_of(reads, "alpha")["seats"]] == ["Renamed file", None]


# ------------------------------------------------------------------ decisions
@pytest.mark.parametrize("cr_state", ["open", "todo", "in-progress", "done", "deferred", None])
def test_a_confirmed_decision_follows_the_state_of_its_related_cr(board, sidebar_bin, cr_state):
    base = board.project("alpha")
    board.decide(base, "done", "D-20261105-01", related="SESSION-020")
    if cr_state:
        board.cr(base, cr_state, "SESSION-020")
    reads = same(sidebar_bin, board)
    stages = project_of(reads, "alpha")["decide"]["stages"]
    assert stages == ([0, 0, 0, 1] if cr_state in ("done", "deferred") else [0, 0, 1, 0])


def test_every_decision_stage_with_related_variants(board, sidebar_bin):
    base = board.project("alpha")
    board.decide(base, "open", "D-20261105-01", "open")
    board.decide(base, "open", "D-20261105-02", "open too", related="TOOL-001")
    board.decide(base, "answered", "D-20261104-01", "answered")
    board.decide(base, "done", "D-20261103-01", "no related")
    board.decide(base, "done", "D-20261103-02", "one pending", related="TOOL-001")
    board.decide(base, "done", "D-20261103-03", "all done", related="TOOL-002, TOOL-003")
    board.decide(base, "done", "D-20261103-04", "one of two pending", related="TOOL-002 TOOL-001")
    board.decide(base, "done", "D-20261103-05", "inside words only", related="xTOOL-001 TOOL-001x X-1")
    board.decide(base, "done", "D-20261103-06", "unknown id", related="NOPE-999")
    withdrawn = board.decide(base, "done", "D-20261103-07", "withdrawn", related="TOOL-001")
    withdrawn.write_text(withdrawn.read_text(encoding="utf-8").replace("decided A", "withdrawn"), encoding="utf-8")
    board.cr(base, "todo", "TOOL-001")
    board.cr(base, "done", "TOOL-002")
    group = base / "agent/cr/done/2026-11"                       # done/ keeps CRs in group directories
    group.mkdir()
    (group / "TOOL-003-item.md").write_text(cr_text("TOOL-003", "In a group"), encoding="utf-8")
    reads = same(sidebar_bin, board)
    decide = project_of(reads, "alpha")["decide"]
    assert decide == {"open": 2, "stages": [2, 1, 3, 4]}


def test_decision_files_in_unusual_formats(board, sidebar_bin):
    base = board.project("alpha")
    root = base / "agent/decide/done"
    text = decide_text("D-20261105-01", "q", state="done", related="TOOL-001")
    (root / "D-20261105-01.md").write_bytes(text.replace("\n", "\r\n").encode("utf-8"))               # CRLF
    (root / "D-20261105-02.md").write_text("no title\n\n- Outcome: withdrawn\n", encoding="utf-8")      # not a header block
    (root / "D-20261105-03.md").write_text("# plain\n\n- Status: x\n- Related: TOOL-001\n- Outcome: decided A\n",
                                           encoding="utf-8")
    (root / "D-20261105-04.md").write_text("# D-20261105-04: q\n\n```\n- Outcome: withdrawn\n```\n"
                                           "- Related: TOOL-001\n", encoding="utf-8")                   # fence lines are skipped: the block goes on and the fenced Outcome is no header
    (root / "D-20261105-05.md").write_text("# D-20261105-05: q\n\n- Outcome: withdrawn x\n- Outcome: decided\n"
                                           "- Related: TOOL-001\n", encoding="utf-8")                   # the first value counts
    (root / "README.md").write_text("not an item\n", encoding="utf-8")
    (root / "ORDER-1.md").write_text("not an item\n", encoding="utf-8")
    board.cr(base, "in-progress", "TOOL-001")
    reads = same(sidebar_bin, board)
    assert project_of(reads, "alpha")["decide"] == {"open": 0, "stages": [0, 0, 3, 2]}


def test_projects_with_only_one_item_root_or_none(board, sidebar_bin):
    only_cr = board.project("only-cr", seats=1)
    only_decide = board.project("only-decide", seats=1)
    board.project("none", seats=1, items=False)
    board.cr(only_cr, "open", "TOOL-001")
    board.decide(only_decide, "done", "D-20261105-01", related="TOOL-001")
    del board.registry[str(only_cr)]["path_decide"]
    del board.registry[str(only_decide)]["path_cr"]
    board.config.write_text(json.dumps(board.registry), encoding="utf-8")
    reads = same(sidebar_bin, board)
    assert project_of(reads, "only-cr")["decide"] is None and project_of(reads, "only-cr")["cr"]["open"] == 1
    assert project_of(reads, "only-decide")["cr"] is None
    assert project_of(reads, "only-decide")["decide"]["stages"] == [0, 0, 1, 0]      # no CR tree: the related CR is unknown
    assert project_of(reads, "none")["cr"] is None and project_of(reads, "none")["decide"] is None


def test_item_roots_that_are_missing_have_no_items_and_no_error(board, sidebar_bin):
    base = board.project("alpha", seats=1)
    for path in sorted((base / "agent").rglob("*"), reverse=True):
        if path.is_dir():
            path.rmdir()
    reads = same(sidebar_bin, board)
    alpha = project_of(reads, "alpha")
    assert alpha["errors"] == [] and alpha["cr"] == {"open": 0, "todo": 0, "in-progress": 0}
    assert alpha["decide"] == {"open": 0, "stages": [0, 0, 0, 0]}


# ------------------------------------------------------------------ remote seats
def test_a_remote_seat_shows_its_host_and_path(board, sidebar_bin):
    base = board.project("alpha", seats=3)
    board.registry[str(base)]["seats"][1] = {"host": "macbook-worker", "path": "/Users/swain//Agent/./remote-seat"}
    board.registry[str(base)]["seats"][2] = {"host": "other", "path": "/r", "python": "/opt/py"}
    board.config.write_text(json.dumps(board.registry), encoding="utf-8")
    put_state(base, 3, {1: ("TOOL-001", workers(3)[1])})
    reads = same(sidebar_bin, board)
    seats = project_of(reads, "alpha")["seats"]
    assert [(seat["host"], seat["path"]) for seat in seats] == [
        (None, str((base / "../seat0").resolve())), ("macbook-worker", "/Users/swain/Agent/remote-seat"), ("other", "/r")]


# ------------------------------------------------------------------ registry
GOOD = {"project": "x", "provider": "codex", "seats": []}


@pytest.mark.parametrize("registry", [
    "{",
    '{"/a": {"project": "x", "project": "y"}}',
    "[]",
    '{"relative/base": {}}',
    '{"/a": {"project": "x"}}',
    '{"/a": {"project": "x", "provider": "codex", "seats": [], "extra": 1}}',
    '{"/a": {"project": " ", "provider": "codex", "seats": []}}',
    '{"/a": {"project": "x", "provider": "gemini", "seats": []}}',
    '{"/a": {"project": "x", "provider": "codex", "seats": "s"}}',
    '{"/a": {"project": "x", "provider": "claude", "seats": [{"host": "h", "path": "/p"}]}}',
    '{"/a": {"project": "x", "provider": "codex", "seats": [{"host": "h", "path": "rel"}]}}',
    '{"/a": {"project": "x", "provider": "codex", "seats": [{"host": "-h", "path": "/p"}]}}',
    '{"/a": {"project": "x", "provider": "codex", "seats": [{"host": "h", "path": "/p/../q"}]}}',
    '{"/a": {"project": "x", "provider": "codex", "seats": [{"host": "h", "path": "/p", "python": "-c"}]}}',
    '{"/a": {"project": "x", "provider": "codex", "seats": [7]}}',
    '{"/a": {"project": "x", "provider": "codex", "seats": ["/a"]}}',
    '{"/a": {"project": "x", "provider": "codex", "seats": []}, "/b": {"project": "x", "provider": "codex", "seats": []}}',
    '{"/a": {"project": "x", "provider": "codex", "seats": ["/s"]}, "/b": {"project": "y", "provider": "codex", "seats": ["/s"]}}',
    '{"/a": {"project": "x", "provider": "codex", "seats": [], "path_cr": "/c", "path_decide": "/c/d"}}',
    '{"/a": {"project": "x", "provider": "codex", "seats": [], "path_cr": ""}}',
    '{"/a": {"project": "x", "provider": "codex", "seats": [], "launch": {}}}',
    '{"/a": {"project": "x", "provider": "codex", "seats": [], "launch": {"args": "x"}}}',
    '{"/a": {"project": "x", "provider": "codex", "seats": [], "launch": {"worker_args": ["--resume=1"]}}}',
    '{"/a": {"project": "x", "provider": "codex", "seats": [], "launch": {"other": []}}}',
], ids=lambda text: text[:60])
def test_a_registry_that_is_not_valid_gives_the_same_message(board, sidebar_bin, registry):
    board.config.write_text(registry, encoding="utf-8")
    reads = same(sidebar_bin, board)
    assert reads["before"]["error"] and reads["before"]["projects"] == [] and reads["liveness"] == {}


def test_a_registry_that_is_not_utf8_or_not_there(board, sidebar_bin, tmp_path):
    board.config.write_bytes(b'{"/a": \xff}')
    assert same(sidebar_bin, board)["before"]["error"] == "Cannot read a valid project registry."
    reads = same(sidebar_bin, tmp_path / "missing.json")
    assert reads["before"]["error"] == "The selected project registry is unavailable."


def test_a_valid_registry_with_launch_arguments_and_relative_paths(board, sidebar_bin):
    base = board.project("alpha", seats=1)
    board.registry[str(base)]["launch"] = {"args": ["--model", "x"], "leader_args": ["--a=b"], "worker_args": []}
    board.registry[str(base)]["path_cr"] = "../cr-elsewhere/"
    (base.parent / "cr-elsewhere/open").mkdir(parents=True)
    (base.parent / "cr-elsewhere/open/TOOL-001-x.md").write_text(cr_text("TOOL-001", "T"), encoding="utf-8")
    board.config.write_text(json.dumps(board.registry), encoding="utf-8")
    reads = same(sidebar_bin, board)
    assert reads["before"]["error"] is None and project_of(reads, "alpha")["cr"]["open"] == 1


def test_the_standard_registry_places_are_searched_without_a_config(tmp_path, sidebar_bin, monkeypatch):
    home = tmp_path / "home"
    (home / ".config/project-agent").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    expected = model.snapshot(None, now=NOW)
    assert expected["error"]["code"] == "registry_not_found"
    registry = {str(tmp_path / "p/main"): {**GOOD, "project": "std"}}
    (tmp_path / "p/main").mkdir(parents=True)
    (home / ".config/project-agent/project.json").write_text(json.dumps(registry), encoding="utf-8")
    (home / ".claude").mkdir()
    (home / ".claude/project.json").write_text(json.dumps(registry), encoding="utf-8")     # a second, separate file
    ambiguous = model.snapshot(None, now=NOW)["error"]
    assert ambiguous["code"] == "registry_ambiguous"
    (home / ".claude/project.json").unlink()
    (home / ".claude/project.json").symlink_to(home / ".config/project-agent/project.json")      # the same file
    found = slim(model.snapshot(None, now=NOW))
    assert [project["id"] for project in found["projects"]] == ["std"]

    def rust(env_home):
        result = subprocess.run([str(sidebar_bin), "dump", "--now", NOW_TEXT], capture_output=True, text=True,
                                env={**os.environ, "HOME": str(env_home)}, timeout=command_timeout())
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)["before"]
    assert rust(home) == found
    (home / ".claude/project.json").unlink()
    (home / ".claude/project.json").write_text(json.dumps(registry), encoding="utf-8")
    assert rust(home)["error"] == ambiguous["message"]
    for path in (home / ".claude/project.json", home / ".config/project-agent/project.json"):
        path.unlink()
    assert rust(home)["error"] == expected["error"]["message"]


# ------------------------------------------------------------------ state errors
@pytest.mark.parametrize("name, text", [
    ("broken json", "{"),
    ("repeated key", '{"leader": null, "leader": null}'),
    ("not an object", "[]"),
    ("no leader", "{}"),
    ("seat keys not consecutive", '{"leader": null, "1": null}'),
    ("assigned seat removed from the registry",
     '{"leader": null, "0": {"job_id": null, "git_hash": null, "session": null}, '
     '"1": {"job_id": "T-1", "git_hash": null, "session": null}}'),
    ("leader is a text", '{"leader": "x", "0": {"job_id": null, "git_hash": null, "session": null}}'),
    ("leader without a transport field", '{"leader": {"session_id": "L"}, "0": {"job_id": null, "git_hash": null, "session": null}}'),
    ("leader with an unknown field", '{"leader": {"session_id": "L", "endpoint": "e", "x": 1}, "0": {"job_id": null, "git_hash": null, "session": null}}'),
    ("bad connected_at", '{"leader": {"session_id": "L", "endpoint": "e", "connected_at": "2026-02-30T00:00:00Z"}, "0": {"job_id": null, "git_hash": null, "session": null}}'),
    ("leader reviewing leader", '{"leader": {"session_id": "L", "endpoint": "e", "reviewing": "leader"}, "0": {"job_id": null, "git_hash": null, "session": null}}'),
    ("seat row with a missing field", '{"leader": null, "0": {"job_id": null}}'),
    ("blank job", '{"leader": null, "0": {"job_id": " ", "git_hash": null, "session": null}}'),
    ("job named leader", '{"leader": null, "0": {"job_id": "leader", "git_hash": null, "session": null}}'),
    ("short git hash", '{"leader": null, "0": {"job_id": "T-1", "git_hash": "abc", "session": null}}'),
    ("session of a seat is invalid", '{"leader": null, "0": {"job_id": "T-1", "git_hash": null, "session": {"session_id": "W"}}}'),
    ("session on an unassigned seat", '{"leader": null, "0": {"job_id": null, "git_hash": null, "session": {"session_id": "W", "endpoint": "e"}}}'),
    ("a job on two seats", '{"leader": null, "0": {"job_id": "T-1", "git_hash": null, "session": null}, "1": {"job_id": "T-1", "git_hash": null, "session": null}}'),
    ("reviewing a job no seat holds", '{"leader": {"session_id": "L", "endpoint": "e", "reviewing": "T-9"}, "0": {"job_id": "T-1", "git_hash": null, "session": null}}'),
])
def test_a_state_that_is_not_valid_gives_the_same_error_row(board, sidebar_bin, name, text):
    base = board.project("alpha", seats=2 if "1" in text and "assigned seat" not in name and "two seats" not in name else 1)
    if name == "a job on two seats":
        base = board.project("beta", seats=2)
    (base / "agent/state.json").write_text(text, encoding="utf-8")
    good = board.project("good", seats=1)
    board.state(good, {"leader": leader(), "0": NO_SESSION})
    reads = same(sidebar_bin, board)
    broken = [project for project in reads["before"]["projects"] if project["id"] != "good"][-1]
    assert [error["source"] for error in broken["errors"]] == ["state"], name
    assert statuses(broken) and set(statuses(broken)) == {"empty"} and broken["leader"] is None
    assert project_of(reads, "good")["errors"] == [] and project_of(reads, "good")["leader"] is not None


def test_a_state_file_that_is_not_utf8_or_is_a_link_or_whose_parent_is_a_file(board, sidebar_bin, tmp_path):
    first = board.project("bytes", seats=1)
    (first / "agent/state.json").write_bytes(b'{"leader": "\xff"}')
    second = board.project("linked", seats=1)
    board.state(second, {"leader": leader(), "0": NO_SESSION})
    (second / "agent/real.json").write_bytes((second / "agent/state.json").read_bytes())
    (second / "agent/state.json").unlink()
    (second / "agent/state.json").symlink_to(second / "agent/real.json")
    third = board.project("parent-file", seats=1)
    (third / "agent").rename(third / "agent-moved")
    (third / "agent").write_text("a file", encoding="utf-8")
    fourth = board.project("no-base", seats=1)
    for path in sorted(fourth.rglob("*"), reverse=True):
        path.rmdir() if path.is_dir() else path.unlink()
    fourth.rmdir()
    reads = same(sidebar_bin, board)
    by_id = {project["id"]: project for project in reads["before"]["projects"]}
    assert all(len(by_id[name]["errors"]) >= 1 and by_id[name]["errors"][0]["source"] == "state" for name in by_id), by_id
    assert by_id["no-base"]["errors"][0]["message"] == "The registered project base is unavailable."


# ------------------------------------------------------------------ errors in the CR and decision trees
def test_a_file_that_cannot_be_read_gives_the_error_row_of_its_tree(board, sidebar_bin):
    base = board.project("alpha", seats=1)
    board.project("beta", seats=1)
    board.cr(base, "open", "TOOL-001")
    (base / "agent/cr/todo/TOOL-002-bad.md").write_bytes(b"# TOOL-002: x\n\xff\xfe\n")
    (base / "agent/cr/in-progress/TOOL-003-bad.md").write_bytes(b"ab\xe3\x81")
    board.decide(base, "open", "D-20261105-01")
    (base / "agent/decide/answered/D-20261105-02.md").write_bytes(b"\x80")
    reads = same(sidebar_bin, board)
    alpha = project_of(reads, "alpha")
    assert [(e["source"], e["message"]) for e in alpha["errors"]] == [
        ("cr", "'utf-8' codec can't decode byte 0xff in position 14: invalid start byte"),
        ("decide", "'utf-8' codec can't decode byte 0x80 in position 0: invalid start byte")]
    assert alpha["cr"] is None and alpha["decide"] is None
    assert project_of(reads, "beta")["errors"] == [] and project_of(reads, "beta")["cr"] is not None


def test_the_first_unreadable_file_in_listing_order_names_the_error(board, sidebar_bin):
    base = board.project("alpha", seats=1)
    (base / "agent/cr/in-progress/TOOL-001-a.md").write_bytes(b"\xc3\x28")
    (base / "agent/cr/open/TOOL-002-b.md").write_bytes(b"\xe3\x81")
    (base / "agent/cr/open/sub").mkdir()
    (base / "agent/cr/open/sub/A-003-c.md").write_bytes(b"\xff")                # `sub/A-003-c.md` sorts before `TOOL-002-b.md`
    reads = same(sidebar_bin, board)
    assert [e["source"] for e in project_of(reads, "alpha")["errors"]] == ["cr"]


def test_listed_names_that_are_not_regular_files(board, sidebar_bin):
    base = board.project("alpha", seats=1)
    board.project("beta", seats=1)
    board.project("gamma", seats=1)
    (base / "agent/cr/open/dir.md").mkdir()                                       # a directory named like an item
    (base / "agent/cr/open/dir.md/TOOL-001-in-dir.md").write_text(cr_text("TOOL-001", "x"), encoding="utf-8")
    other = Path(str(base).replace("alpha", "beta"))
    (other / "agent/cr/open/broken.md").symlink_to(other / "agent/cr/open/nothing-here")
    third = Path(str(base).replace("alpha", "gamma"))
    (third / "agent/cr/todo/real").mkdir()
    (third / "agent/cr/todo/real/TOOL-001-x.md").write_text(cr_text("TOOL-001", "x"), encoding="utf-8")
    (third / "agent/cr/todo/link").symlink_to(third / "agent/cr/todo/real")        # not followed, as in rglob
    (third / "agent/cr/todo/file-link.md").symlink_to(third / "agent/cr/todo/real/TOOL-001-x.md")
    reads = same(sidebar_bin, board)
    assert [e["message"].split(":")[0] for e in project_of(reads, "alpha")["errors"]] == ["[Errno 21] Is a directory"]
    assert [e["message"].split(":")[0] for e in project_of(reads, "beta")["errors"]] == ["[Errno 2] No such file or directory"]
    assert project_of(reads, "gamma")["errors"] == [] and project_of(reads, "gamma")["cr"]["todo"] == 2


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_a_permission_error_is_reported_like_python(board, sidebar_bin):
    base = board.project("alpha", seats=1)
    path = board.cr(base, "open", "TOOL-001")
    path.chmod(0)
    try:
        reads = same(sidebar_bin, board)
    finally:
        path.chmod(0o644)
    (error,) = project_of(reads, "alpha")["errors"]
    assert error["message"].startswith("[Errno 13] Permission denied: ")


def test_path_cr_that_is_a_file_has_no_items(board, sidebar_bin):
    base = board.project("alpha", seats=1)
    for path in sorted((base / "agent").rglob("*"), reverse=True):
        path.rmdir() if path.is_dir() else path.unlink()
    (base / "agent/cr").write_text("a file", encoding="utf-8")
    reads = same(sidebar_bin, board)
    assert project_of(reads, "alpha")["cr"] == {"open": 0, "todo": 0, "in-progress": 0}


# ------------------------------------------------------------------ liveness against a real tmux server
@pytest.fixture
def fleet_env(tmp_path, monkeypatch):
    """A private tmux server with live runs (agent-session's `fleet`), and the model pointed at it."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent-session" / "tests"))
    import fleet
    import tmux_test_server
    from agent_session import tmux as tmux_module
    name = tmux_test_server.claim("board-rust-eq")
    try:
        socket = fleet.start_server(name)
        monkeypatch.setenv("AGENT_SESSION_SOCKET", socket)
        (tmp_path / "fleet").mkdir()
        registry = fleet.build_fleet(tmp_path / "fleet", socket, 3, 4)
        yield {"socket": socket, "registry": registry, "control": tmux_module.Tmux(socket_path=socket), "root": tmp_path / "fleet"}
    finally:
        tmux_test_server.release(name)


def verdicts(reads, project="p0"):
    return {slot: entry["state"] for slot, entry in reads["liveness"][project].items()}


def test_every_run_of_a_live_server_is_alive_and_a_release_hold_shows_after_the_liveness_read(fleet_env, sidebar_bin):
    reads = same(sidebar_bin, fleet_env["registry"])
    assert verdicts(reads) == {"leader": "alive", "0": "alive", "1": "alive", "2": "alive", "3": "alive"}
    assert statuses(project_of(reads, "p0", "before")) == ["working"] * 4        # no liveness read yet: no hold
    assert statuses(project_of(reads, "p0", "after")) == ["release_pending", "working", "working", "working"]


def test_stopped_unknown_and_changed_runs(fleet_env, sidebar_bin):
    control, root = fleet_env["control"], fleet_env["root"]
    prefix = "@agent_session_"

    def meta(project, slot):
        return control.get_current(project, slot)

    def option(window, key, value):
        control.command("set-option", "-w", "-t", window, prefix + key, json.dumps(value))
    option(meta("p0", "seat-0")["window_id"], "cli_pid", 2 ** 22 + 12345)       # the CLI process is gone: stopped
    control.command("kill-window", "-t", meta("p0", "seat-1")["window_id"])      # the window is gone: unknown
    option(meta("p0", "seat-2")["window_id"], "run_id", "another-run")            # another run than the pointer names
    control.command("set-option", "-t", "p0", prefix + "current_seat_3", "not json")
    control.command("set-option", "-t", "p1", prefix + "current_leader", json.dumps({"window_id": "@1' ; kill-server"}))
    owner = json.loads(control.command("show-options", "-qv", "-t", "p2", prefix + "owner"))
    owner["server_pid"] += 1                                                       # a session of another server
    control.command("set-option", "-t", "p2", prefix + "owner", json.dumps(owner))
    state = json.loads((root / "p1.main/agent/state.json").read_text(encoding="utf-8"))
    state["0"]["session"]["session_id"] = "11111111-aaaa-4bbb-8ccc-222222222222"  # state binds another conversation
    (root / "p1.main/agent/state.json").write_text(json.dumps(state), encoding="utf-8")
    reads = same(sidebar_bin, fleet_env["registry"])
    assert verdicts(reads, "p0") == {"leader": "alive", "0": "stopped", "1": "unknown", "2": "unknown", "3": "unknown"}
    assert verdicts(reads, "p1") == {"leader": "unknown", "0": "unknown", "1": "alive", "2": "alive", "3": "alive"}
    assert set(verdicts(reads, "p2").values()) == {"unknown"}


def test_a_dead_pane_is_stopped(fleet_env, sidebar_bin):
    control = fleet_env["control"]
    window = control.get_current("p0", "seat-1")["window_id"]
    control.command("set-option", "-w", "-t", window, "remain-on-exit", "on")
    pid = control.pane_info(control.get_current("p0", "seat-1")["pane_id"])["pane_pid"]
    os.kill(pid, 15)
    import time
    deadline = time.monotonic() + command_timeout()
    while not control.pane_info(control.get_current("p0", "seat-1")["pane_id"])["pane_dead"]:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    reads = same(sidebar_bin, fleet_env["registry"])
    assert verdicts(reads)["1"] == "stopped" and verdicts(reads)["2"] == "alive"


def test_an_option_the_read_did_not_expect_is_learned(fleet_env, sidebar_bin):
    control = fleet_env["control"]
    window = control.get_current("p0", "seat-0")["window_id"]
    control.command("set-option", "-w", "-t", window, "@agent_session_a_new_option", json.dumps({"x": 1}))
    reads = same(sidebar_bin, fleet_env["registry"])
    assert verdicts(reads)["0"] == "alive"


def test_a_window_option_that_is_not_json_is_unknown(fleet_env, sidebar_bin):
    control = fleet_env["control"]
    window = control.get_current("p0", "seat-0")["window_id"]
    control.command("set-option", "-w", "-t", window, "@agent_session_cwd", "{not json")
    reads = same(sidebar_bin, fleet_env["registry"])
    assert verdicts(reads)["0"] == "unknown" and verdicts(reads)["1"] == "alive"


@pytest.mark.parametrize("socket", ["nobody.sock", "relative.sock"])
def test_a_server_that_cannot_be_read_leaves_every_verdict_unknown(fleet_env, sidebar_bin, tmp_path, monkeypatch, socket):
    """No server at the socket, or a socket path that is not absolute: Python and Rust both read nothing."""
    value = str(tmp_path / socket) if socket == "nobody.sock" else socket
    monkeypatch.setenv("AGENT_SESSION_SOCKET", value)
    reads = same(sidebar_bin, fleet_env["registry"])
    assert set(verdicts(reads, "p0").values()) == {"unknown"} and len(verdicts(reads, "p0")) == 5
    assert statuses(project_of(reads, "p0", "after")) == ["working"] * 4


class FakeLauncher:
    """Stands in for `project-board liveness --project ID`: prints `answer` (JSON text) and records its arguments."""

    def __init__(self, directory, answer, status=0):
        self.script = directory / "fake-project-board"
        self.record = directory / "launcher-arguments.json"
        self.script.write_text(textwrap.dedent(f"""\
            #!{sys.executable}
            import json, sys
            open({str(self.record)!r}, "w").write(json.dumps(sys.argv[1:]))
            sys.stdout.write({answer!r})
            sys.exit({status})
            """), encoding="utf-8")
        self.script.chmod(0o755)

    def env(self):
        return {"PROJECT_BOARD_LAUNCHER": str(self.script)}

    def arguments(self):
        return json.loads(self.record.read_text(encoding="utf-8"))


def make_remote(fleet_env, monkeypatch):
    """Seat 1 of p0 is a remote seat whose run is registered with the remote seat record."""
    control, root = fleet_env["control"], fleet_env["root"]
    registry = json.loads(fleet_env["registry"].read_text(encoding="utf-8"))
    base = str(root / "p0.main")
    seat = {"host": "remote-host", "path": "/remote/seat", "python": "python3"}
    registry[base]["seats"][1] = seat
    fleet_env["registry"].write_text(json.dumps(registry), encoding="utf-8")
    window = control.get_current("p0", "seat-1")["window_id"]
    control.command("set-option", "-w", "-t", window, "@agent_session_remote_seat", json.dumps(seat))
    control.command("set-option", "-w", "-t", window, "@agent_session_endpoint", json.dumps("unix:///tmp/fleet.sock"))
    state = json.loads((root / "p0.main/agent/state.json").read_text(encoding="utf-8"))
    return state["1"]["session"]["session_id"]


@pytest.mark.parametrize("answer", ["alive", "stopped"])
def test_the_verdict_of_a_remote_seat_comes_from_the_python_launcher(fleet_env, sidebar_bin, monkeypatch, answer):
    session_id = make_remote(fleet_env, monkeypatch)
    from agent_session import remote
    monkeypatch.setattr(remote, "liveness", lambda meta: answer)             # Python judges by SSH; the test answers
    launcher = FakeLauncher(fleet_env["root"], json.dumps({"1": {"session_id": session_id, "state": answer}}))
    reads = same(sidebar_bin, fleet_env["registry"], launcher.env())
    assert verdicts(reads)["1"] == answer and verdicts(reads)["0"] == "alive"
    assert launcher.arguments() == ["--config", str(fleet_env["registry"]), "liveness", "--project", "p0"]


@pytest.mark.parametrize("answer, status", [("not json", 0), ("[]", 0), ('{"1": {"session_id": "x", "state": "alive"}}', 0),
                                            ('{"1": {"state": "bogus"}}', 0), ("{}", 1)])
def test_a_launcher_that_fails_or_answers_badly_leaves_the_remote_seat_unknown(fleet_env, sidebar_bin, monkeypatch, answer, status):
    make_remote(fleet_env, monkeypatch)
    from agent_session import remote
    from agent_session.errors import SessionError as Error

    def unreachable(meta):
        raise Error("remote_unknown", "SSH did not confirm the remote operation.", 4)
    monkeypatch.setattr(remote, "liveness", unreachable)                      # Python: an SSH failure is unknown
    launcher = FakeLauncher(fleet_env["root"], answer, status)
    reads = same(sidebar_bin, fleet_env["registry"], launcher.env())
    assert verdicts(reads)["1"] == "unknown" and verdicts(reads)["2"] == "alive"


def test_a_remote_run_that_the_owner_check_rejects_is_unknown_without_asking_python(fleet_env, sidebar_bin, monkeypatch):
    session_id = make_remote(fleet_env, monkeypatch)
    control = fleet_env["control"]
    window = control.get_current("p0", "seat-1")["window_id"]
    control.command("set-option", "-w", "-t", window, "@agent_session_remote_seat",
                    json.dumps({"host": "elsewhere", "path": "/remote/seat", "python": "python3"}))
    from agent_session import remote
    monkeypatch.setattr(remote, "liveness", lambda meta: "alive")
    launcher = FakeLauncher(fleet_env["root"], json.dumps({"1": {"session_id": session_id, "state": "alive"}}))
    reads = same(sidebar_bin, fleet_env["registry"], launcher.env())
    assert verdicts(reads)["1"] == "unknown" and verdicts(reads)["2"] == "alive"
    assert not launcher.record.exists()                                      # the owner check comes before the call
