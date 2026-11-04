"""Snapshot rules of docs/project-board-plan.md sections 3, 4.3 and 7.1 on files in a temporary registry."""
import datetime as dt

import pytest

from board_testing import BASE_HASH, LEADER_ID, WORKER_IDS, Board, leader, session
from project_board import model

NOW = dt.datetime(2026, 11, 5, 10, 30, tzinfo=dt.timezone.utc)
SUBMIT = "a" * 40
OTHER = "c" * 40


@pytest.fixture
def board(tmp_path):
    return Board(tmp_path)


# ------------------------------------------------------------ plan 7.1 review wait
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
    assert "<strong>contract</strong>" in seat1["contract_html"]
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
    assert "재제출" in seat["cr"]["result_html"] and SUBMIT not in seat["cr"]["result_html"]


def test_decisions_are_read_from_open_only_and_rendered_escaped(board):
    base = board.project("alpha")
    board.decide(base, "open", "D-20261105-01", "질문 하나")
    board.decide(base, "done", "D-20261104-01", "끝난 질문")
    (alpha,) = model.snapshot(board.config, now=NOW)["projects"]
    (item,) = alpha["decide"]
    assert (item["id"], item["title"], item["urgency"], item["blocks"]) == ("D-20261105-01", "질문 하나", "high", "TOOL-002")
    assert [s["name"] for s in item["sections"]] == ["Background", "Options", "Recommendation"]
    assert "&lt;b&gt;" in item["sections"][0]["html"] and "<table>" in item["sections"][1]["html"]
    assert model.open_decision(model.find_project(board.config, "alpha"), "D-20261104-01") is None


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

    def liveness(cwd, config_path=None):
        calls.append(cwd)
        if cwd != first:
            raise model.SessionError("state_not_found", "The project state has not been initialized.")
        return {"leader": {"session_id": LEADER_ID, "state": "stopped"}}
    monkeypatch.setattr(model.api, "liveness", liveness)
    assert model.liveness(board.config) == {"alpha": {"leader": {"session_id": LEADER_ID, "state": "stopped"}}, "beta": {}}
    assert len(calls) == 2
