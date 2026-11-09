"""TUI decision answers through the Board's transport-independent service."""
import json
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from board_testing import LEADER_ID, Board, leader
from project_board import answer
from project_item import store

DECIDE = "D-20261105-01"


@pytest.fixture(autouse=True)
def operator(monkeypatch):
    monkeypatch.setattr(answer.model.api, "caller", lambda project: ("operator", None))
    monkeypatch.setattr(answer.model.api, "liveness", lambda cwd, config_path=None:
                        {"leader": {"session_id": LEADER_ID, "state": "alive"}})


@pytest.fixture
def board(tmp_path):
    data = Board(tmp_path)
    base = data.project("alpha", seats=1)
    data.state(base, {"leader": leader(), "0": {"job_id": None, "git_hash": None, "session": None}})
    data.decide(base, "open", DECIDE, "질문 하나")
    return data, base


@pytest.mark.parametrize("project, decide, response, code", [
    ("alpha", DECIDE, "  ", "answer_empty"),
    ("alpha", DECIDE, "A\x00B", "answer_empty"),
    ("alpha", DECIDE, "가" * 5462, "answer_too_large"),
    ("alpha", DECIDE, None, "invalid_request"),
    ("nobody", DECIDE, "A", "project_not_found"),
    ("alpha", "D-20261105-09", "A", "decide_not_open"),
])
def test_answer_validation_stops_before_sending(board, monkeypatch, project, decide, response, code):
    data, _ = board
    monkeypatch.setattr(answer, "send_answer", lambda *_: pytest.fail("must not send"))
    result = answer.submit_answer(data.config, project, decide, response)
    assert result["ok"] is False and result["error"]["code"] == code


def test_answer_is_checked_against_the_current_open_items(board, monkeypatch):
    data, base = board
    original = base / "agent/decide/open" / f"{DECIDE}.md"
    original.rename(base / "agent/decide/done" / original.name)
    monkeypatch.setattr(answer, "send_answer", lambda *_: pytest.fail("must not send"))
    assert answer.submit_answer(data.config, "alpha", DECIDE, "A")["error"]["code"] == "decide_not_open"


def test_missing_registry_is_reported_without_sending(tmp_path):
    result = answer.submit_answer(tmp_path / "missing.json", "alpha", DECIDE, "A")
    assert result["ok"] is False and result["error"]["code"] == "registry_not_found"


def test_no_leader_is_recorded_without_sending(board, monkeypatch):
    data, base = board
    data.state(base, {"leader": None, "0": {"job_id": None, "git_hash": None, "session": None}})
    monkeypatch.setattr(answer, "send_answer", lambda *_: pytest.fail("must not send"))
    result = answer.submit_answer(data.config, "alpha", DECIDE, "A")
    assert result["ok"] is True
    assert result["data"]["notification"]["error"]["code"] == "leader_unavailable"
    assert (base / "agent/decide/answered" / f"{DECIDE}.md").exists()


@pytest.mark.parametrize("actor, code", [("seat-0", "role_denied"), ("leader", "role_denied"),
                                        ("unmanaged-agent", "caller_unbound")])
def test_only_the_operator_can_approve(board, monkeypatch, actor, code):
    data, _ = board
    monkeypatch.setattr(answer.model.api, "caller", lambda project: (actor, "a-session"))
    monkeypatch.setattr(answer, "send_answer", lambda *_: pytest.fail("must not send"))
    assert answer.submit_answer(data.config, "alpha", DECIDE, "A")["error"]["code"] == code


def test_stopped_current_leader_is_recorded_without_sending(board, monkeypatch):
    data, base = board
    monkeypatch.setattr(answer.model.api, "liveness", lambda cwd, config_path=None:
                        {"leader": {"session_id": LEADER_ID, "state": "stopped"}})
    monkeypatch.setattr(answer, "send_answer", lambda *_: pytest.fail("must not send"))
    result = answer.submit_answer(data.config, "alpha", DECIDE, "A")
    assert result["ok"] is True
    assert result["data"]["notification"]["error"]["code"] == "leader_stopped"
    assert (base / "agent/decide/answered" / f"{DECIDE}.md").exists()


def test_old_stopped_verdict_cannot_block_a_new_leader(board, monkeypatch):
    data, _ = board
    monkeypatch.setattr(answer.model.api, "liveness", lambda cwd, config_path=None:
                        {"leader": {"session_id": "old-session", "state": "stopped"}})
    monkeypatch.setattr(answer, "send_answer", lambda *_: {"ok": True, "data": {}, "error": None})
    assert answer.submit_answer(data.config, "alpha", DECIDE, "A")["ok"] is True


def test_answer_reaches_agent_session_with_the_user_text(board, tmp_path, monkeypatch):
    data, base = board
    record = tmp_path / "sent.json"
    stub = tmp_path / "agent-session"
    stub.write_text("#!/usr/bin/env python3\n"
                    "import json, os, sys\n"
                    "args = sys.argv[1:]\n"
                    "body = open(args[args.index('--file') + 1], encoding='utf-8').read()\n"
                    f"json.dump({{'args': args, 'cwd': os.getcwd(), 'body': body}}, open({str(record)!r}, 'w'))\n"
                    "print(json.dumps({'ok': True, 'data': {'disposition': 'accepted'}, 'error': None}))\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(answer, "AGENT_SESSION", stub)

    result = answer.submit_answer(data.config, "alpha", DECIDE, "A로 진행합니다.\n둘째 줄")
    assert result == {"ok": True, "data": {"accepted": True, "notification": {"status": "sent"}}, "error": None}
    seen = json.loads(record.read_text(encoding="utf-8"))
    assert seen["cwd"] == str(base)
    args = seen["args"]
    assert args[:2] == ["--config", str(data.config)]
    assert args[2:5] == ["send", "--job", "leader"] and args[args.index("--timeout") + 1] == "30"
    assert seen["body"].splitlines()[:3] == [f"결정 답변: {DECIDE}", "Project: alpha", "질문: 질문 하나"]
    assert seen["body"].endswith("\n답변:\nA로 진행합니다.\n둘째 줄")


def test_answer_is_recorded_once_before_notifying(board, monkeypatch):
    data, base = board
    sent = []
    monkeypatch.setattr(answer, "send_answer", lambda _project, body:
                        sent.append(body) or {"ok": True, "data": {}, "error": None})
    first = answer.submit_answer(data.config, "alpha", DECIDE, "A\n둘째 줄")
    second = answer.submit_answer(data.config, "alpha", DECIDE, "B")
    assert first["ok"] is True and first["data"]["accepted"] is True
    assert second["error"]["code"] == "decide_not_open"
    assert len(sent) == 1
    path = base / "agent/decide/answered" / f"{DECIDE}.md"
    assert path.exists()
    assert 'Answer: "A\\n둘째 줄"' in path.read_text(encoding="utf-8")
    assert "답변 접수" in (base / "agent/decide/decide.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("separator", ["\u2028", "\u2029"])
def test_board_receipt_and_leader_confirmation_keep_unicode_separator(board, monkeypatch, separator):
    data, base = board
    words = f"A{separator}B"
    monkeypatch.setattr(answer, "send_answer", lambda *_: {"ok": True, "data": {}, "error": None})
    result = answer.submit_answer(data.config, "alpha", DECIDE, words)
    assert result["ok"] is True and result["data"]["accepted"] is True
    root = base / "agent/decide"
    answered = root / "answered" / f"{DECIDE}.md"
    assert answer.model.DECIDE.fmt.answer_text(answer.model.DECIDE.fmt.parse(answered, "answered")) == words
    done = store.move(answer.model.DECIDE, root, DECIDE, "done", outcome="decided A", by="Leader")
    assert f'사용자 답변 원문: "A\\u{ord(separator):04x}B"' in done.read_text(encoding="utf-8")


def test_concurrent_answers_accept_only_one(board, monkeypatch):
    data, base = board
    sent = []
    monkeypatch.setattr(answer, "send_answer", lambda _project, body:
                        sent.append(body) or {"ok": True, "data": {}, "error": None})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda text: answer.submit_answer(data.config, "alpha", DECIDE, text),
                                ("A", "B")))
    assert sum(item["ok"] for item in results) == 1
    assert len(sent) == 1
    path = base / "agent/decide/answered" / f"{DECIDE}.md"
    assert path.exists()
    assert path.read_text(encoding="utf-8").count("- Answer:") == 1


def test_page_write_failure_does_not_lose_an_accepted_answer(board, monkeypatch):
    data, base = board

    def fail_page(*_args, **_kwargs):
        raise OSError("page is read-only")

    monkeypatch.setattr(answer.item_api, "render_decision_page", fail_page)
    monkeypatch.setattr(answer, "send_answer", lambda *_: {"ok": True, "data": {}, "error": None})
    result = answer.submit_answer(data.config, "alpha", DECIDE, "A")
    assert result["ok"] is True and result["data"]["page_error"]["code"] == "OSError"
    assert (base / "agent/decide/answered" / f"{DECIDE}.md").exists()


def test_agent_session_refusal_preserves_its_error(board, tmp_path, monkeypatch):
    data, base = board
    stub = tmp_path / "agent-session"
    stub.write_text("#!/bin/sh\necho '{\"ok\": false, \"data\": null, \"error\": {\"code\": \"caller_unbound\", "
                    "\"message\": \"This agent is not the operator.\", \"details\": {}}}'\nexit 3\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(answer, "AGENT_SESSION", stub)
    result = answer.submit_answer(data.config, "alpha", DECIDE, "A")
    assert result["ok"] is True
    assert result["data"]["notification"]["error"]["code"] == "caller_unbound"
    assert (base / "agent/decide/answered" / f"{DECIDE}.md").exists()


def test_unknown_send_result_is_not_reported_as_a_failure(board, monkeypatch):
    data, base = board
    monkeypatch.setattr(answer.subprocess, "run", lambda *_args, **_kwargs:
                        subprocess.CompletedProcess([], 5, stdout="", stderr="broken"))
    result = answer.submit_answer(data.config, "alpha", DECIDE, "A")
    assert result["ok"] is True
    assert result["data"]["notification"]["status"] == "unconfirmed"
    assert result["data"]["notification"]["error"]["details"]["exit"] == 5
    assert (base / "agent/decide/answered" / f"{DECIDE}.md").exists()
    assert answer.submit_answer(data.config, "alpha", DECIDE, "A")["error"]["code"] == "decide_not_open"


@pytest.mark.parametrize("failure, code", [
    (subprocess.TimeoutExpired(["agent-session"], 60), "send_unconfirmed"),
    (OSError("missing executable"), "send_unavailable"),
])
def test_send_timeout_and_start_failure_are_distinct(board, monkeypatch, failure, code):
    data, base = board

    def fail(*_args, **_kwargs):
        raise failure

    project = answer.model.find_project(data.config, "alpha")
    with monkeypatch.context() as patcher:
        patcher.setattr(answer.subprocess, "run", fail)
        delivery = answer.send_answer(project, "saved answer")
    monkeypatch.setattr(answer, "send_answer", lambda *_: delivery)
    result = answer.submit_answer(data.config, "alpha", DECIDE, "A")
    assert result["ok"] is True
    assert result["data"]["notification"]["error"]["code"] == code
    assert (base / "agent/decide/answered" / f"{DECIDE}.md").exists()
