"""HTTP behavior of docs/project-board-plan.md sections 6.2 and 6.3 against a real local server."""
import http.client
import json
import re
import stat
import threading

import pytest

from board_testing import Board, leader
from project_board import server as board_server

DECIDE = "D-20261105-01"


@pytest.fixture
def running(tmp_path):
    board = Board(tmp_path)
    base = board.project("alpha", seats=1)
    board.state(base, {"leader": leader(), "0": {"job_id": None, "git_hash": None, "session": None}})
    board.decide(base, "open", DECIDE, "질문 하나")
    httpd = board_server.BoardServer(0, str(board.config))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield {"server": httpd, "port": httpd.server_address[1], "board": board, "base": base}
    httpd.shutdown()
    httpd.server_close()


def call(port, method, path, body=None, headers=None, host=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    sent = {"Host": host or f"127.0.0.1:{port}", **(headers or {})}
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))
    connection.putrequest(method, path, skip_host=True)
    for key, value in sent.items():
        connection.putheader(key, value)
    if data is not None:
        connection.putheader("Content-Length", str(len(data)))
    connection.endheaders(data)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    return response.status, dict(response.getheaders()), raw


def answer(running, payload=None, **headers):
    sent = {"Content-Type": "application/json", "X-Board-Token": running["server"].token}
    sent.update(headers)
    sent = {key: value for key, value in sent.items() if value is not None}
    return call(running["port"], "POST", "/api/answer",
                payload or {"project": "alpha", "decide_id": DECIDE, "answer": "A로 진행합니다."}, sent)


def test_the_page_carries_this_runs_token_and_refuses_framing(running):
    status, headers, raw = call(running["port"], "GET", "/")
    assert status == 200 and headers["X-Frame-Options"] == "DENY"
    page = raw.decode("utf-8")
    assert re.search(r'name="board-token" content="([^"]+)"', page).group(1) == running["server"].token
    assert "__BOARD_TOKEN__" not in page
    status, _, raw = call(running["port"], "GET", "/api/board")
    assert status == 200 and json.loads(raw)["projects"][0]["decide"][0]["id"] == DECIDE


@pytest.mark.parametrize("host", ["evil.example:80", "127.0.0.1:1", "rebind.example"])
def test_other_host_names_are_refused(running, host):
    port = running["port"]
    assert call(port, "GET", "/api/board", host=host)[0] == 403
    assert call(port, "GET", "/", host=host)[0] == 403
    assert call(port, "GET", "/", host=f"localhost:{port}")[0] == 200


@pytest.mark.parametrize("headers, code, status", [
    ({"X-Board-Token": None}, "token_denied", 403),
    ({"X-Board-Token": "guess"}, "token_denied", 403),
    ({"Origin": "http://evil.example"}, "origin_denied", 403),
    ({"Content-Type": "text/plain"}, "json_required", 415),
    ({"Content-Type": "application/x-www-form-urlencoded"}, "json_required", 415),
])
def test_requests_that_a_foreign_page_could_send_are_refused(running, monkeypatch, headers, code, status):
    sent = []
    monkeypatch.setattr(board_server, "send_answer", lambda project, text: sent.append(text))
    got, _, raw = answer(running, **headers)
    assert (got, json.loads(raw)["error"]["code"]) == (status, code)
    assert sent == []


@pytest.mark.parametrize("payload, code, status", [
    ({"project": "alpha", "decide_id": DECIDE, "answer": "  "}, "answer_empty", 400),
    ({"project": "alpha", "decide_id": DECIDE}, "invalid_request", 400),
    ({"project": "alpha", "decide_id": DECIDE, "answer": "x" * 16385}, "answer_too_large", 400),
    ({"project": "nobody", "decide_id": DECIDE, "answer": "A"}, "project_not_found", 404),
    ({"project": "alpha", "decide_id": "D-20261105-09", "answer": "A"}, "decide_not_open", 409),
])
def test_an_answer_must_name_an_open_decision(running, monkeypatch, payload, code, status):
    monkeypatch.setattr(board_server, "send_answer", lambda project, text: pytest.fail("must not send"))
    got, _, raw = answer(running, payload)
    assert (got, json.loads(raw)["error"]["code"]) == (status, code)


def test_a_same_origin_answer_is_sent_through_agent_session(running, tmp_path, monkeypatch):
    record = tmp_path / "record.json"
    stub = tmp_path / "agent-session"
    stub.write_text("#!/usr/bin/env python3\n"
                    "import json, os, sys\n"
                    "args = sys.argv[1:]\n"
                    "body = open(args[args.index('--file') + 1], encoding='utf-8').read()\n"
                    f"json.dump({{'args': args, 'cwd': os.getcwd(), 'body': body}}, open({str(record)!r}, 'w'))\n"
                    "print('progress goes to stderr', file=sys.stderr)\n"
                    "print(json.dumps({'ok': True, 'data': {'disposition': 'accepted'}, 'error': None}))\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(board_server, "AGENT_SESSION", stub)
    origin = f"http://127.0.0.1:{running['port']}"
    status, _, raw = answer(running, {"project": "alpha", "decide_id": DECIDE, "answer": "A로 진행합니다.\n둘째 줄"},
                            Origin=origin)
    assert status == 200 and json.loads(raw) == {"ok": True, "data": {"disposition": "accepted"}, "error": None}
    seen = json.loads(record.read_text(encoding="utf-8"))
    assert seen["cwd"] == str(running["base"])
    args = seen["args"]
    assert args[:2] == ["--config", str(running["board"].config)]
    assert args[2:5] == ["send", "--job", "leader"] and args[args.index("--timeout") + 1] == "30"
    lines = seen["body"].splitlines()
    assert lines[0] == f"결정 답변: {DECIDE}" and lines[1] == "Project: alpha" and lines[2] == "질문: 질문 하나"
    assert seen["body"].endswith("\n답변:\nA로 진행합니다.\n둘째 줄")


def test_a_refused_send_is_reported_with_its_error(running, tmp_path, monkeypatch):
    stub = tmp_path / "agent-session"
    stub.write_text("#!/bin/sh\necho '{\"ok\": false, \"data\": null, \"error\": {\"code\": \"caller_unbound\", "
                    "\"message\": \"This agent is not a registered member of this project.\", \"details\": {}}}'\nexit 3\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(board_server, "AGENT_SESSION", stub)
    status, _, raw = answer(running)
    assert status == 502 and json.loads(raw)["error"]["code"] == "caller_unbound"
    stub.write_text("#!/bin/sh\necho broken >&2\nexit 5\n")
    status, _, raw = answer(running)
    assert status == 502 and json.loads(raw)["error"]["code"] == "send_unconfirmed"


def test_a_send_that_does_not_finish_is_unconfirmed_not_failed(running, tmp_path, monkeypatch):
    def hang(*args, **kwargs):
        raise board_server.subprocess.TimeoutExpired(args[0], kwargs.get("timeout"))
    monkeypatch.setattr(board_server.subprocess, "run", hang)
    status, _, raw = answer(running)
    assert status == 502 and json.loads(raw)["error"]["code"] == "send_unconfirmed"
    monkeypatch.undo()                               # the real subprocess.run again; agent-session cannot start
    monkeypatch.setattr(board_server, "AGENT_SESSION", tmp_path / "missing" / "agent-session")
    status, _, raw = answer(running)
    assert status == 502 and json.loads(raw)["error"]["code"] == "send_unavailable"


def test_the_server_listens_on_loopback_only(running):
    assert running["server"].server_address[0] == "127.0.0.1"


def test_main_warns_inside_an_agent_session(monkeypatch, capsys, tmp_path):
    started = {}

    class Fake:
        server_address = ("127.0.0.1", 9999)

        def __init__(self, port, config, verbose):
            started.update(port=port, config=config)

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            started["closed"] = True
    monkeypatch.setattr(board_server, "BoardServer", Fake)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "an-agent")
    assert board_server.main(["--port", "9999", "--config", str(tmp_path / "p.json")]) == 0
    out = capsys.readouterr()
    assert "http://127.0.0.1:9999/" in out.out and "CLAUDE_CODE_SESSION_ID" in out.err
    assert started == {"port": 9999, "config": str(tmp_path / "p.json"), "closed": True}
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    board_server.main([])
    assert capsys.readouterr().err == ""
