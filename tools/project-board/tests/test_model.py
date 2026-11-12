"""Project facts and review state from files in a temporary registry."""
import datetime as dt
import json
import os
from pathlib import Path

import pytest

from board_testing import (BASE_HASH, LEADER_ID, WORKER_IDS, Board, cron_run, cron_section, isolate_crontab, leader,
                           session)
from project_board import model

NOW = dt.datetime(2026, 11, 5, 10, 30, tzinfo=dt.timezone.utc)
SUBMIT = "a" * 40
OTHER = "c" * 40


@pytest.fixture
def board(tmp_path):
    return Board(tmp_path)


@pytest.fixture(autouse=True)
def no_tmux_server(tmp_path, monkeypatch):
    """`model.liveness` reads the tmux server once; point it at a socket nobody listens on, not the user's server."""
    monkeypatch.setenv("AGENT_SESSION_SOCKET", str(tmp_path / "no-tmux-server.sock"))


# ------------------------------------------------------------ review wait (project-board README)
@pytest.mark.parametrize("result, expected", [
    ("", None),
    (f"- 제출 commit: `{SUBMIT}` (`cr/TOOL-001`).", SUBMIT),
    (f"- 제출 commit: {SUBMIT}", SUBMIT),
    # Codex review B1: hashes of the verification record that follow the submission line are not submissions.
    (f"- 제출 commit: `{SUBMIT}`\n- 검증: `git diff {OTHER}..{SUBMIT}`\n- 비교 기준: `{OTHER}`", SUBMIT),
    (f"- 제출 commit: `{OTHER}`\n\n### 두 번째 제출\n\n- 제출 commit: `{SUBMIT}`", SUBMIT),
    (f"- 시작 기준: `{BASE_HASH}`\n- 검증 범위 {OTHER}", None),
    (f"```\n- 제출 commit: {SUBMIT}\n```", None),
    ("- 제출 commit: `abc1234`", None),
    # Codex implementation review B1: examples in indented fences or nested lists are not submissions.
    (f"- 제출 commit: `{SUBMIT}`\n- 검증 입력:\n  ```md\n  - 제출 commit: {OTHER}\n  ```", SUBMIT),
    (f"- 제출 commit: `{SUBMIT}`\n~~~\n- 제출 commit: {OTHER}\n~~~", SUBMIT),
    (f"- 제출 commit: `{SUBMIT}`\n```\n~~~\n- 제출 commit: {OTHER}\n```", SUBMIT),
    (f"- 제출 commit: `{SUBMIT}`\n- 예시:\n  - 제출 commit: {OTHER}", SUBMIT),
    # Codex re-review: a shorter run or a line with an info string does not close the fence.
    (f"- 제출 commit: {SUBMIT}\n````md\n```text\n- 제출 commit: {OTHER}\n```\n````\n", SUBMIT),
    (f"- 제출 commit: {SUBMIT}\n```md\n```python\n- 제출 commit: {OTHER}\n```\n", SUBMIT),
    (f"- 제출 commit: {OTHER}\n```md\nexample\n````  \n- 제출 commit: {SUBMIT}\n", SUBMIT),
])
def test_the_submission_is_the_last_submission_line(result, expected):
    assert model.submitted_hash(result) == expected


@pytest.mark.parametrize("disposition, waiting", [
    ("- 2026-11-05 leader: 판정합니다.", True),
    (f"- 2026-11-05 leader: `{SUBMIT[:12]}` 검토, 수정 요청.", False),
    (f"- 2026-11-05 leader: {SUBMIT[:7]} 인수.", False),
    (f"- 2026-11-05 Leader: 제출 {SUBMIT}를 인수합니다.", False),   # the entry `project-item accept` writes: a particle follows the hash
    (f"- 2026-11-05 leader: {SUBMIT[:6]} 인수.", True),           # fewer than 7 characters is no citation
    (f"- 2026-11-05 leader: {OTHER} 검토.", True),                # another (older) submission
])
def test_a_write_cr_waits_until_the_disposition_cites_its_submission(disposition, waiting):
    parts = {"Result": f"- 제출 commit: `{SUBMIT}`\n- 비교 기준: `{OTHER}`", "Disposition": disposition}
    assert model.review_wait("in-progress", {"Base": BASE_HASH}, parts) is waiting
    assert model.review_wait("done", {"Base": BASE_HASH}, parts) is False


def test_a_read_only_cr_waits_once_it_has_a_result():
    headers = {"Mode": "read-only"}
    assert model.review_wait("in-progress", headers, {"Result": "  \n"}) is False
    assert model.review_wait("in-progress", headers, {"Result": "조사 결과입니다."}) is True


# ------------------------------------------------------------ plan 4.3 seat and leader states
def test_snapshot_derives_each_seat_state_and_the_leader_position(board):
    base = board.project("alpha", seats=5)
    board.cr(base, "in-progress", "TOOL-001", "Working")
    board.cr(base, "in-progress", "TOOL-002", "Submitted", result=f"- 제출 commit: `{SUBMIT}`")
    board.cr(base, "in-progress", "TOOL-003", "Reviewed", result=f"- 제출 commit: `{SUBMIT}`")
    board.cr(base, "in-progress", "TOOL-004", "Pending")
    board.cr(base, "open", "TOOL-010")
    board.cr(base, "todo", "TOOL-011")
    board.cr(base, "done", "TOOL-099", with_base=False)
    board.state(base, {
        "leader": leader(reviewing="TOOL-003"),
        "0": {"job_id": "TOOL-001", "git_hash": None, "session": session(0)},
        "1": {"job_id": "TOOL-002", "git_hash": None, "session": session(1, connected_at=None)},
        "2": {"job_id": "TOOL-003", "git_hash": None, "session": session(2)},
        "3": {"job_id": "TOOL-004", "git_hash": None, "session": None},
        "4": {"job_id": None, "git_hash": None, "session": None},
    })
    view = model.snapshot(board.config, now=NOW)
    assert view["error"] is None and view["now"] == "2026-11-05T10:30:00Z"
    (alpha,) = view["projects"]
    assert alpha["errors"] == [] and alpha["seat_count"] == 5 and alpha["provider"] == "codex"
    assert [(s["job_id"], s["status"]) for s in alpha["seats"]] == [
        ("TOOL-001", "working"), ("TOOL-002", "review_wait"), ("TOOL-003", "reviewing"),
        ("TOOL-004", "pending"), (None, "empty")]
    # 2h 30m since 08:00; a legacy session without connected_at has no time (shown as "?").
    assert [s["elapsed"] for s in alpha["seats"]] == [9000, None, 9000, None, None]
    assert [s["session_id"] for s in alpha["seats"][:3]] == list(WORKER_IDS)
    assert alpha["leader"] == {"session_id": LEADER_ID, "elapsed": 91800,
                               "reviewing": "TOOL-003", "reviewing_seat": 2}
    seat1 = alpha["seats"][1]["cr"]
    assert seat1["branch"] == "cr/TOOL-002" and seat1["base"] == BASE_HASH and seat1["submitted"] == SUBMIT
    assert "**contract**" in seat1["contract_markdown"]
    crs = alpha["crs"]
    assert [i["id"] for i in crs["open"]] == ["TOOL-010"] and [i["id"] for i in crs["todo"]] == ["TOOL-011"]
    assert [i["id"] for i in crs["in-progress"]] == ["TOOL-001", "TOOL-002", "TOOL-003", "TOOL-004"]
    assert "done" not in crs                                    # plan 2: done CRs are not shown


def test_feedback_returns_a_seat_to_working_until_a_new_submission(board):
    base = board.project("alpha", seats=1)
    path = board.cr(base, "in-progress", "TOOL-001", result=f"- 제출 commit: `{SUBMIT}`",
                    disposition=f"- 2026-11-05 leader: `{SUBMIT[:12]}` 수정 요청.")
    board.state(base, {"leader": leader(), "0": {"job_id": "TOOL-001", "git_hash": None, "session": session(0)}})
    assert model.snapshot(board.config, now=NOW)["projects"][0]["seats"][0]["status"] == "working"
    path.write_text(path.read_text(encoding="utf-8") + f"\n### 재제출\n\n- 제출 commit: `{OTHER}`\n", encoding="utf-8")
    seat = model.snapshot(board.config, now=NOW)["projects"][0]["seats"][0]
    assert seat["status"] == "review_wait" and seat["cr"]["submitted"] == OTHER
    assert "재제출" in seat["cr"]["result_markdown"] and SUBMIT not in seat["cr"]["result_markdown"]


def test_snapshot_keeps_remote_host_and_path_distinct_from_local_paths(board):
    base = board.project("alpha", seats=2)
    board.registry[str(base)]["seats"][1] = {
        "host": "macbook-worker", "path": "/Users/swain/Agent/remote-seat"}
    board.config.write_text(json.dumps(board.registry), encoding="utf-8")
    board.state(base, {
        "leader": leader(),
        "0": {"job_id": None, "git_hash": None, "session": None},
        "1": {"job_id": "TOOL-001", "git_hash": None, "session": session(0)},
    })
    snapshot = model.snapshot(board.config, now=NOW)
    assert snapshot["error"] is None
    local, remote = snapshot["projects"][0]["seats"]
    assert local["host"] is None and local["path"] == str((base / "../seat0").resolve())
    assert remote["host"] == "macbook-worker"
    assert remote["path"] == "/Users/swain/Agent/remote-seat"
    assert remote["job_id"] == "TOOL-001" and remote["session_id"] == session(0)["session_id"]


def test_decisions_include_each_stage_with_markdown_source(board):
    base = board.project("alpha")
    path = board.decide(base, "open", "D-20261105-01", "질문 하나")
    board.decide(base, "answered", "D-20261104-01", "접수된 질문")
    board.decide(base, "done", "D-20261103-01", "진행 중인 질문", related="TOOL-002")
    board.decide(base, "done", "D-20261102-01", "끝난 질문")
    board.cr(base, "in-progress", "TOOL-002")
    (alpha,) = model.snapshot(board.config, now=NOW)["projects"]
    items = {item["id"]: item for item in alpha["decide"]}
    item = items["D-20261105-01"]
    assert (item["id"], item["title"], item["urgency"], item["blocks"]) == ("D-20261105-01", "질문 하나", "high", "TOOL-002")
    assert item["path"] == str(path.resolve())
    assert [s["name"] for s in item["sections"]] == ["Background", "Options", "Recommendation", "Evidence"]
    assert "<b>" in item["sections"][0]["body"] and "| 선택지 | 내용 |" in item["sections"][1]["body"]
    assert "`b.py:2`" in item["sections"][3]["body"]
    assert {key: value["display_state"] for key, value in items.items()} == {
        "D-20261105-01": "결정 대기", "D-20261104-01": "답변 접수",
        "D-20261103-01": "반영 중", "D-20261102-01": "완료",
    }
    (base / "agent/cr/in-progress/TOOL-002-item.md").rename(base / "agent/cr/done/TOOL-002-item.md")
    items = {item["id"]: item for item in model.snapshot(board.config, now=NOW)["projects"][0]["decide"]}
    assert items["D-20261103-01"]["display_state"] == "완료"
    assert items["D-20261102-01"]["display_state"] == "완료"
    assert model.open_decision(model.find_project(board.config, "alpha"), "D-20261104-01") is None


@pytest.mark.parametrize("cr_state, expected", [
    ("open", "반영 중"), ("todo", "반영 중"), ("in-progress", "반영 중"),
    ("done", "완료"), ("deferred", "완료"),
])
def test_confirmed_decision_tracks_related_cr_state(board, cr_state, expected):
    base = board.project("alpha")
    board.decide(base, "done", "D-20261105-01", related="SESSION-020")
    board.cr(base, cr_state, "SESSION-020")
    (item,) = model.snapshot(board.config, now=NOW)["projects"][0]["decide"]
    assert item["display_state"] == expected


def test_withdrawn_decision_is_complete_on_board_while_related_cr_is_todo(board):
    base = board.project("alpha")
    path = board.decide(base, "done", "D-20261105-01", related="TOOL-001")
    path.write_text(path.read_text(encoding="utf-8").replace("Outcome: decided A", "Outcome: withdrawn"),
                    encoding="utf-8")
    board.cr(base, "todo", "TOOL-001")
    (item,) = model.snapshot(board.config, now=NOW)["projects"][0]["decide"]
    assert item["display_state"] == "완료"


def test_decision_shows_project_sections_in_file_order_including_evidence(board):
    base = board.project("alpha")
    path = board.decide(base, "open", "D-20261106-01", "초안 승인")
    path.write_text(path.read_text(encoding="utf-8") + "\n## Draft\n\n게시 <i>초안</i> 전문.\n\n## Empty\n\n## Disposition\n\n- 판정.\n"
                    "\n## Result\n\n- 결과.\n", encoding="utf-8")
    (item,) = model.snapshot(board.config, now=NOW)["projects"][0]["decide"]
    assert [s["name"] for s in item["sections"]] == ["Background", "Options", "Recommendation", "Evidence", "Draft"]
    assert "<i>초안</i>" in item["sections"][4]["body"]


# ------------------------------------------------------------ plan 3 and 6.1 sources
def test_a_project_without_item_paths_or_state_shows_an_empty_team(board):
    board.project("plain", seats=2, items=False)
    (plain,) = model.snapshot(board.config, now=NOW)["projects"]
    assert plain["crs"] is None and plain["decide"] is None and plain["leader"] is None
    assert [s["status"] for s in plain["seats"]] == ["empty", "empty"] and plain["errors"] == []


def test_one_broken_project_does_not_hide_the_others(board):
    broken = board.project("broken")
    (broken / "agent/state.json").write_text("{", encoding="utf-8")
    good = board.project("good", seats=1)
    board.state(good, {"leader": leader(), "0": {"job_id": None, "git_hash": None, "session": None}})
    by_id = {p["id"]: p for p in model.snapshot(board.config, now=NOW)["projects"]}
    assert [(e["source"], e["code"]) for e in by_id["broken"]["errors"]] == [("state", "state_invalid")]
    assert by_id["good"]["errors"] == [] and by_id["good"]["leader"]["session_id"] == LEADER_ID


def test_a_missing_registry_is_reported_not_raised(tmp_path):
    view = model.snapshot(tmp_path / "missing.json", now=NOW)
    assert view["projects"] == [] and view["error"]["code"] == "registry_not_found"


def test_liveness_is_collected_per_project_and_a_missing_state_has_none(board, monkeypatch):
    first = board.project("alpha", seats=1)
    board.project("beta", seats=1)
    board.state(first, {"leader": leader(), "0": {"job_id": None, "git_hash": None, "session": None}})
    calls = []

    def liveness(project, socket=None, view=None):
        calls.append(project.base)
        if project.base != first:
            raise model.SessionError("state_not_found", "The project state has not been initialized.")
        return {"leader": {"session_id": LEADER_ID, "state": "stopped"}}
    monkeypatch.setattr(model.api, "project_liveness", liveness)
    assert model.liveness(board.config) == {"alpha": {"leader": {"session_id": LEADER_ID, "state": "stopped"}}, "beta": {}}
    assert len(calls) == 2


# ------------------------------------------------------------ cost of a refresh (BOARD-002)
def _count_reads(monkeypatch):
    """Names of the Markdown files that are read from now on."""
    reads = []
    original = Path.read_text

    def read_text(self, *args, **kwargs):
        if self.suffix == ".md":
            reads.append(self.name)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read_text)
    return reads


def test_a_refresh_reads_only_the_files_that_changed(board, monkeypatch):
    base = board.project("alpha", seats=1)
    cr = board.cr(base, "in-progress", "TOOL-001", "First")
    board.cr(base, "open", "TOOL-010", "Open one")
    decision = board.decide(base, "open", "D-20261105-01", "Question")
    board.decide(base, "done", "D-20261105-02", "Old question")
    board.state(base, {"leader": leader(), "0": {"job_id": "TOOL-001", "git_hash": None, "session": session(0)}})
    reads = _count_reads(monkeypatch)

    first = model.snapshot(board.config, now=NOW)
    assert sorted(reads) == sorted(["TOOL-001-item.md", "TOOL-010-item.md", "D-20261105-01.md", "D-20261105-02.md"])
    reads.clear()

    assert model.snapshot(board.config, now=NOW) == first         # nothing changed: nothing is read
    assert reads == []

    cr.write_text(cr.read_text(encoding="utf-8").replace("First", "Renamed title"), encoding="utf-8")
    reads.clear()
    again = model.snapshot(board.config, now=NOW)["projects"][0]
    assert reads == ["TOOL-001-item.md"]
    assert again["seats"][0]["title"] == "Renamed title" and again["crs"]["in-progress"][0]["title"] == "Renamed title"
    reads.clear()

    decision.unlink()                                             # a removed file leaves the list
    after = model.snapshot(board.config, now=NOW)["projects"][0]
    assert [item["id"] for item in after["decide"]] == ["D-20261105-02"] and reads == []


def test_a_cached_file_still_follows_the_directory_it_is_listed_in(board):
    base = board.project("alpha", seats=1)
    path = board.decide(base, "open", "D-20261105-01", "Question")
    assert model.snapshot(board.config, now=NOW)["projects"][0]["decide"][0]["state"] == "open"
    path.rename(base / "agent/decide/answered" / path.name)       # a move keeps the file, not its state
    (item,) = model.snapshot(board.config, now=NOW)["projects"][0]["decide"]
    assert item["state"] == "answered" and item["display_state"] == "답변 접수"


def test_a_refresh_reads_the_registry_once_however_many_projects_it_shows(board, monkeypatch):
    for name in ("alpha", "beta", "gamma"):
        board.project(name, seats=1)
    from agent_session import config as session_config
    calls = []
    original = session_config.load_registry

    def counted(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)
    monkeypatch.setattr(session_config, "load_registry", counted)
    monkeypatch.setattr(model, "load_registry", counted)
    assert len(model.snapshot(board.config, now=NOW)["projects"]) == 3
    assert len(calls) == 1
    calls.clear()
    assert set(model.liveness(board.config)) == {"alpha", "beta", "gamma"}
    assert len(calls) == 1


def test_a_popup_snapshot_holds_only_its_project(board):
    board.project("alpha", seats=1)
    board.project("beta", seats=1)
    assert [p["id"] for p in model.snapshot(board.config, now=NOW)["projects"]] == ["alpha", "beta"]
    assert [p["id"] for p in model.snapshot(board.config, now=NOW, project_id="beta")["projects"]] == ["beta"]
    assert model.snapshot(board.config, now=NOW, project_id="missing")["projects"] == []


def test_a_seat_whose_stopped_worker_waits_for_release_shows_release_pending(board, monkeypatch):
    base = board.project("alpha", seats=2)
    board.cr(base, "in-progress", "TOOL-001", "Finished")
    board.cr(base, "in-progress", "TOOL-002", "Running")
    board.state(base, {"leader": leader(),
                       "0": {"job_id": "TOOL-001", "git_hash": None, "session": session(0)},
                       "1": {"job_id": "TOOL-002", "git_hash": None, "session": session(1)}})
    hold = {"seat": 0, "since": "2026-11-05T10:00:00Z", "reasons": ["the CR is still in-progress"]}
    monkeypatch.setattr(model.api, "project_pending_releases", lambda project, socket=None, view=None: {"TOOL-001": hold})
    monkeypatch.setattr(model.api, "project_liveness", lambda project, socket=None, view=None: {"0": {}})
    assert model.snapshot(board.config, now=NOW)["projects"][0]["seats"][0]["status"] == "working"   # not read on the file refresh
    model.liveness(board.config)                                   # the run-fact refresh reads it
    seats = model.snapshot(board.config, now=NOW)["projects"][0]["seats"]
    assert [(s["job_id"], s["status"]) for s in seats] == [("TOOL-001", "release_pending"), ("TOOL-002", "working")]
    assert seats[0]["release_pending"] == hold and seats[1]["release_pending"] is None


def test_an_unreadable_release_record_does_not_hide_the_seats(board, monkeypatch):
    base = board.project("alpha", seats=1)
    board.cr(base, "in-progress", "TOOL-001")
    board.state(base, {"leader": leader(), "0": {"job_id": "TOOL-001", "git_hash": None, "session": session(0)}})

    def unreadable(project, socket=None, view=None):
        raise model.SessionError("tmux_unknown", "tmux is unreadable")

    monkeypatch.setattr(model.api, "project_pending_releases", unreadable)
    monkeypatch.setattr(model.api, "project_liveness", lambda project, socket=None, view=None: {"0": {}})
    model.liveness(board.config)
    project = model.snapshot(board.config, now=NOW)["projects"][0]
    assert project["errors"] == [] and project["seats"][0]["status"] == "working"


# ------------------------------------------------------------ an idle refresh reads no listing (BOARD-013)
@pytest.fixture
def settled(monkeypatch):
    """Trust a directory's modification time at once, so the tests need not wait out `SETTLE_NS`. The margin
    is negative because a file server's clock may be ahead of this host's (a stamp then lies in the future)."""
    monkeypatch.setattr(model, "SETTLE_NS", -10_000_000_000)


_bumps = iter(range(10 ** 12, 10 ** 15, 10 ** 10))


def _bump(*directories):
    """Give directories a modification time no earlier read had: a test changes files faster than the clock ticks."""
    for directory in directories:
        stamp = 1_800_000_000_000_000_000 + next(_bumps)
        os.utime(directory, ns=(stamp, stamp))


def _count_listings(monkeypatch):
    calls = []
    for name in ("item_files", "cr_states", "load_registry"):
        original = getattr(model, name)

        def counted(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(model, name, counted)
    return calls


def test_a_refresh_of_an_unchanged_tree_lists_no_directory_and_reads_no_registry(board, monkeypatch, settled):
    base = board.project("alpha", seats=1)
    board.cr(base, "open", "TOOL-010", "Open one")
    board.cr(base, "in-progress", "TOOL-001", "First")
    board.decide(base, "done", "D-20261105-02", "Old question", related="TOOL-001")
    board.state(base, {"leader": leader(), "0": {"job_id": "TOOL-001", "git_hash": None, "session": session(0)}})
    calls = _count_listings(monkeypatch)

    first = model.snapshot(board.config, now=NOW)
    assert set(calls) == {"item_files", "cr_states", "load_registry"}
    calls.clear()

    assert model.snapshot(board.config, now=NOW) == first
    assert calls == []


def test_a_refresh_just_after_a_change_lists_again_because_the_stamp_may_not_have_ticked(board, monkeypatch):
    base = board.project("alpha", seats=1)
    board.cr(base, "open", "TOOL-010", "Open one")
    calls = _count_listings(monkeypatch)                         # SETTLE_NS is the product's: a change this recent
    model.snapshot(board.config, now=NOW)                        # is not trusted
    calls.clear()
    model.snapshot(board.config, now=NOW)
    assert "item_files" in calls and "load_registry" in calls


def test_changes_to_the_tree_show_on_the_next_refresh_though_listings_are_kept(board, settled):
    base = board.project("alpha", seats=1)
    waiting = board.cr(base, "open", "TOOL-010", "Open one")
    board.cr(base, "in-progress", "TOOL-001", "First")
    board.decide(base, "done", "D-20261105-02", "Waits for TOOL-002", related="TOOL-002")
    board.state(base, {"leader": leader(), "0": {"job_id": "TOOL-001", "git_hash": None, "session": session(0)}})
    root = base / "agent"

    def view():
        project = model.snapshot(board.config, now=NOW)["projects"][0]
        return project

    first = view()
    assert [len(first["crs"][state]) for state in ("open", "todo", "in-progress")] == [1, 0, 1]
    assert first["decide"][0]["display_state"] == "반영 중"
    assert first["seats"][0]["status"] == "working"

    waiting.rename(root / "cr/todo" / waiting.name)              # a CR moves
    _bump(root / "cr/open", root / "cr/todo")
    moved = view()
    assert [len(moved["crs"][state]) for state in ("open", "todo", "in-progress")] == [0, 1, 1]

    board.decide(base, "open", "D-20261105-03", "New question")  # a decision is added
    _bump(root / "decide/open")
    assert [item["id"] for item in view()["decide"]] == ["D-20261105-03", "D-20261105-02"]

    group = root / "cr/done/2026-11"                             # done/ keeps CRs in group directories
    group.mkdir()
    _bump(root / "cr/done", group)
    assert view()["decide"][1]["display_state"] == "반영 중"
    (group / "TOOL-002-item.md").write_text(cr_text_of("TOOL-002"), encoding="utf-8")
    _bump(group)                                                 # only the group directory changed
    assert [item["display_state"] for item in view()["decide"]] == ["결정 대기", "완료"]

    board.state(base, {"leader": leader(), "0": {"job_id": None, "git_hash": None, "session": None}})
    assert view()["seats"][0]["status"] == "empty"               # a run that ended (the state file is read each time)


def cr_text_of(cr_id):
    from board_testing import cr_text
    return cr_text(cr_id, "Done in a group")


def test_the_registry_is_read_again_only_when_its_file_changes(board, monkeypatch, settled):
    board.project("alpha", seats=1)
    calls = _count_listings(monkeypatch)
    assert [p["id"] for p in model.snapshot(board.config, now=NOW)["projects"]] == ["alpha"]
    assert [p["id"] for p in model.snapshot(board.config, now=NOW)["projects"]] == ["alpha"]
    assert calls.count("load_registry") == 1
    model.liveness(board.config)                                  # the run-fact refresh shares the read
    assert calls.count("load_registry") == 1

    board.project("beta", seats=1)                                # the registry file is rewritten
    _bump(board.config)
    assert [p["id"] for p in model.snapshot(board.config, now=NOW)["projects"]] == ["alpha", "beta"]
    assert calls.count("load_registry") == 2


def test_a_registry_that_cannot_be_read_is_reported_each_time_and_not_kept(board, settled):
    board.project("alpha", seats=1)
    board.config.write_text("{", encoding="utf-8")
    _bump(board.config)
    assert model.snapshot(board.config, now=NOW)["error"]["code"] == "registry_invalid"
    board.config.write_text(json.dumps({}), encoding="utf-8")
    _bump(board.config)
    assert model.snapshot(board.config, now=NOW) == {"now": "2026-11-05T10:30:00Z", "projects": [], "error": None}


def test_a_window_reads_only_the_part_of_a_project_it_shows(board, monkeypatch):
    """BOARD-025: the CR window does not read decisions or run state, the decision window does not read CRs; every
    file read is a round trip on a shared disk."""
    base = board.project("Alpha", seats=1)
    board.state(base, {"leader": None, "0": {"job_id": None, "git_hash": None, "session": None}})
    board.cr(base, "open", "AAA-001", "alpha open")
    board.cr(base, "done", "AAA-000", "alpha done")
    board.decide(base, "open", "D-20261107-01", "alpha question")

    def refuse(name):
        def read(*args, **kwargs):
            raise AssertionError(f"{name} was read")
        return read
    with monkeypatch.context() as patch:
        patch.setattr(model, "decide_items", refuse("decisions"))
        patch.setattr(model, "_read_state", refuse("state"))
        data = model.popup_snapshot(board.config, "Alpha", True, model.ONLY_CRS)
    (project,) = data["projects"]
    assert [item["id"] for item in project["crs"]["open"]] == ["AAA-001"]
    assert [item["id"] for item in project["crs"]["done"]] == ["AAA-000"]
    assert project["decide"] is None and project["seats"] == [] and project["leader"] is None and project["errors"] == []
    assert data["order"] == ["Alpha"]

    with monkeypatch.context() as patch:
        patch.setattr(model, "cr_items", refuse("CRs"))
        patch.setattr(model, "_read_state", refuse("state"))
        data = model.popup_snapshot(board.config, "Alpha", False, model.ONLY_DECISIONS)
    (project,) = data["projects"]
    assert [item["id"] for item in project["decide"]] == ["D-20261107-01"] and project["crs"] is None

    full = model.snapshot(board.config)["projects"][0]                        # without `only` nothing changes
    assert full["crs"] is not None and full["decide"] is not None and len(full["seats"]) == 1


def test_the_decision_snapshot_has_every_projects_decisions_and_nothing_else(board):
    first, second = board.project("Alpha", seats=0), board.project("Beta", seats=0)
    board.decide(first, "open", "D-20261107-01", "alpha question")
    board.cr(second, "open", "BBB-001", "beta open")
    data = model.decision_snapshot(board.config)
    assert [(item["id"], [d["id"] for d in item["decide"]], item["crs"]) for item in data["projects"]] == [
        ("Alpha", ["D-20261107-01"], None), ("Beta", [], None)]


# ------------------------------------------------------------ the cron window (BOARD-027)
REMAINING = json.loads((Path(__file__).parent / "fixtures" / "cron_remaining.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", REMAINING["cases"], ids=lambda case: f"{case['now']}->{case['next']}")
def test_the_time_left_to_a_run_is_the_largest_unit_rounded_down(case):
    """The expected texts are written by hand in the fixture the Rust sidebar reads too."""
    assert model.remaining_text(case["next"], dt.datetime.fromisoformat(case["now"])) == case["text"]
    assert model.remaining_text(dt.datetime.fromisoformat(case["next"]), dt.datetime.fromisoformat(case["now"])) == case["text"]


def test_the_cron_view_lists_the_jobs_of_one_project_and_every_registered_project_for_the_arrows(board, tmp_path, monkeypatch):
    crontab = isolate_crontab(tmp_path, monkeypatch)
    alpha, _beta = board.project("Alpha", seats=0), board.project("Beta", seats=0)
    crontab.write_text("0 23 * * * /home/user/nightly.sh\n"
                       + cron_section("Alpha", ("check", "점검", "13,43 * * * *", "/bin/check 100\\%"),
                                      ("report", "보고", "0 9 * * 1-5", "/bin/report")))
    cron_run(alpha, "check", "2026-11-12T01:13:20Z", True, "ok")
    now = dt.datetime(2026, 11, 12, 10, 20, 30)
    view = model.cron_view(board.config, "Alpha", now)
    assert view["order"] == ["Alpha", "Beta"] and view["error"] is None and view["project"] == "Alpha"
    check, report = view["jobs"]
    assert (check["id"], check["description"], check["schedule"]) == ("check", "점검", "13,43 * * * *")
    assert check["command"] == "/bin/check 100%"                                  # `\%` is `%` as in `cron ls`
    assert check["last_run"] == {"at": "2026-11-12T01:13:20Z", "ok": True, "result": "ok"}
    assert report["last_run"] is None
    assert check["remaining"] == model.remaining_text(check["next_run"], now)
    assert model.cron_view(board.config, "Beta")["jobs"] == []                    # no section: no jobs, no error


def test_the_cron_view_says_why_the_jobs_cannot_be_read_and_still_lists_the_projects(board, tmp_path, monkeypatch):
    crontab = isolate_crontab(tmp_path, monkeypatch)
    board.project("Alpha", seats=0), board.project("Beta", seats=0)
    monkeypatch.setenv("FAKE_CRONTAB_FAIL", "read")
    view = model.cron_view(board.config, "Alpha")
    assert view["jobs"] == [] and view["order"] == ["Alpha", "Beta"]
    assert "crontab" in view["error"] and "simulated failure" in view["error"]
    monkeypatch.delenv("FAKE_CRONTAB_FAIL")
    crontab.write_text("# >>> project-agent: Alpha >>>\n" + cron_section("Beta", ("check", "점검", "13 * * * *", "/x")))
    broken, fine = model.cron_view(board.config, "Alpha"), model.cron_view(board.config, "Beta")
    assert broken["jobs"] == [] and "section" in broken["error"]
    assert fine["error"] is None and [job["id"] for job in fine["jobs"]] == ["check"]   # another project is not affected
    assert model.cron_view(board.config, "Nobody")["error"] == "Project를 찾을 수 없습니다."
