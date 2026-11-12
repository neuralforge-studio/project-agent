"""The two clients of the window protocol do the same thing in the same situation (BOARD-027).

A click on the sidebar tells a Board window that is already open (the CR list, the decisions, the cron jobs) what to show
(docs/project-board-tui-plan.md section 5, BOARD-025). The Python sidebar did that in `tmux_control._reuse`; the Rust
sidebar does it in `rust/src/window.rs` (`window::tell`). They are two clients of one protocol, so they must answer
the same situation the same way, and a change on the Python side must show here as a failure.

Each scenario is built twice on one tmux server with one pane of the window and one fake window process on a
socket: once for the Python client, once for the Rust one (`project-board-sidebar tell`). What is compared is what a
person or the window can tell apart:

- what the window received (the request, with the client's name),
- the outcome: `done` (the window took it), `busy` (the user is told why), or `fallback` (a window has to be started
  or restarted: the Rust sidebar runs `project-board open-...`, the Python client returns None to `_popup`),
- the title of the pane afterwards (set only when the window took the item).

The expected values are the Python client's. A window that is still starting is the one place where the clients differ
on purpose: Python waits for the window's socket for a while and Rust leaves the wait to `project-board`; with a window
that never comes up both end in `fallback`, which is what is compared.
"""
import json
import os
import socket as unix_socket
import subprocess
import threading
import time
import uuid
from pathlib import Path

import pytest

import board_testing  # noqa: F401  (adds the Board tool to sys.path)
from wait_limit import command_timeout
import tmux_test_server
from board_testing import attached, release_clients, tmux
from project_board import tmux_control
from rust_binary import RustBinaryError, sidebar_binary

TITLE_BEFORE = "before"
TITLE = "Window · Falcon2"
REQUESTS = {
    "cr": {"kind": "cr", "project": "Falcon2", "state": "todo"},
    "decision": {"kind": "decision", "project": "Falcon2", "decision": None},
    "cron": {"kind": "cron", "project": "Falcon2"},
}
OK = b'{"ok": true}\n'


class FakeWindow:
    """The process of a Board window: it listens on a socket, records each request line and answers as told.
    `reply` None keeps the connection open without an answer; b"" closes it at once."""

    def __init__(self, reply):
        self.path = f"/tmp/pb-notify-{os.getpid()}-{uuid.uuid4().hex[:8]}.win"
        self.reply = reply
        self.requests = []
        self.server = unix_socket.socket(unix_socket.AF_UNIX, unix_socket.SOCK_STREAM)
        self.server.bind(self.path)
        os.chmod(self.path, 0o600)
        self.server.listen(4)
        self.held = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                connection, _ = self.server.accept()
            except OSError:
                return
            line = b""
            while b"\n" not in line:
                block = connection.recv(4096)
                if not block:
                    break
                line += block
            try:
                self.requests.append(json.loads(line))
            except ValueError:
                self.requests.append(None)
            if self.reply is None:
                self.held.append(connection)             # never answered
                continue
            if self.reply:
                connection.sendall(self.reply)
            connection.close()

    def close(self):
        self.server.close()
        for connection in self.held:
            connection.close()
        Path(self.path).unlink(missing_ok=True)


# name -> how the window is: its kind and what listens (`reply`, or a `link` that is not a listener)
SCENARIOS = {
    "the window takes it": {"reply": OK},
    "the reply has more fields": {"reply": b'{"ok": true, "note": "x"}\n'},
    "ok is not true": {"reply": b'{"ok": 1}\n'},
    "ok is false without a code": {"reply": b'{"ok": false}\n'},
    "busy with a message": {"reply": b'{"ok": false, "code": "busy", "message": "An answer is being sent."}\n'},
    "busy without a message": {"reply": b'{"ok": false, "code": "busy"}\n'},
    "busy with an empty message": {"reply": b'{"ok": false, "code": "busy", "message": ""}\n'},
    "invalid": {"reply": b'{"ok": false, "code": "invalid", "message": "no"}\n'},
    "closing": {"reply": b'{"ok": false, "code": "closing"}\n'},
    "another code": {"reply": b'{"ok": false, "code": "other", "message": "x"}\n'},
    "not json": {"reply": b"hello\n"},
    "a list": {"reply": b"[]\n"},
    "null": {"reply": b"null\n"},
    "a string": {"reply": b'"ok"\n'},
    "an empty reply": {"reply": b""},
    "another kind of window": {"reply": OK, "kind": "other"},
    "the window is still starting": {"reply": OK, "link": "none"},
    "nothing listens": {"reply": OK, "link": "gone"},
    "a file that is not a socket": {"reply": OK, "link": "file"},
    "there is no window": {"reply": OK, "window": False},
    "no answer": {"reply": None, "slow": True},
}
SLOW = {name for name, scenario in SCENARIOS.items() if scenario.get("slow")}


@pytest.fixture(scope="module")
def binary():
    try:
        return sidebar_binary()
    except RustBinaryError as error:
        pytest.fail(f"the Rust sidebar binary is not available: {error}", pytrace=False)


@pytest.fixture(scope="module")
def server():
    name = tmux_test_server.claim("window-notify")
    tmux(name, "-f", "/dev/null", "new-session", "-d", "-x", "80", "-y", "24", "-s", "main", "sleep", "600")
    client = attached(name, "main")
    yield name, client[2]
    release_clients([client])
    tmux_test_server.release(name)


def outcome_of_python(control, client, kind, request, title):
    """What `tmux_control._popup` does before it starts anything: find the window pane, then `_reuse` it."""
    window = tmux_control._client_window(control, client)
    pane = tmux_control._window_pane(control, window)
    if pane is None:
        return {"outcome": "fallback", "message": None}
    result = tmux_control._reuse(control, pane, kind, {**request, "client": client}, title)
    if result is None:
        return {"outcome": "fallback", "message": None}
    if result["ok"]:
        return {"outcome": "done", "message": None}
    assert result["error"]["code"] == "window_busy", result
    return {"outcome": "busy", "message": result["error"]["message"]}


def outcome_of_rust(binary, name, client, kind, request, title):
    environment = {**os.environ, "PROJECT_BOARD_SOCKET": str(tmux_test_server.socket_path(name))}
    done = subprocess.run([str(binary), "tell", "--kind", kind, "--client", client, "--title", title,
                           "--request", json.dumps(request)], capture_output=True, text=True, env=environment, timeout=command_timeout())
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def run_scenario(side, name, server_info, binary, scenario, kind, tmp_path):
    """Build the window of `scenario` on the test server, let one client act, and report what can be told apart."""
    tmux_name, client = server_info
    window = tmux(tmux_name, "new-window", "-d", "-P", "-F", "#{window_id}", "-t", "main", "sleep", "600")
    tmux(tmux_name, "select-window", "-t", window)
    fake = None
    try:
        if scenario.get("window", True):
            pane = tmux(tmux_name, "split-window", "-d", "-P", "-F", "#{pane_id}", "-t", window, "sleep", "600")
            tmux(tmux_name, "select-pane", "-t", pane, "-T", TITLE_BEFORE)
            tmux(tmux_name, "set-option", "-p", "-t", pane, "@project_board_window", "1")
            tmux(tmux_name, "set-option", "-p", "-t", pane, "@project_board_window_kind",
                 scenario.get("kind", kind) if scenario.get("kind") != "other" else ("decision" if kind != "decision" else "cr"))
            mode = scenario.get("link", "listening")
            fake = FakeWindow(scenario["reply"])
            link = {"listening": fake.path, "none": "", "gone": str(tmp_path / "gone.win")}.get(mode)
            if mode == "file":
                link = str(tmp_path / "plain.win")
                Path(link).write_text("x")
            if link:
                tmux(tmux_name, "set-option", "-p", "-t", pane, "@project_board_window_link", link)
        request = REQUESTS[kind]
        if side == "python":
            result = outcome_of_python(tmux_control._control(str(tmux_test_server.socket_path(tmux_name))), client, kind, request, TITLE)
        else:
            result = outcome_of_rust(binary, tmux_name, client, kind, request, TITLE)
        title = tmux(tmux_name, "display-message", "-p", "-t", pane, "#{pane_title}") if scenario.get("window", True) else None
        received = list(fake.requests) if fake else []
        return {**result, "title": title, "received": received}
    finally:
        if fake:
            fake.close()
        tmux(tmux_name, "kill-window", "-t", window)


CASES = [(name, kind) for name in SCENARIOS for kind in REQUESTS if name not in SLOW or kind == "cron"]


@pytest.mark.parametrize("name,kind", CASES, ids=[f"{kind}-{name}" for name, kind in CASES])
def test_both_clients_do_the_same_with_a_window(server, binary, tmp_path, monkeypatch, name, kind):
    monkeypatch.setattr(tmux_control, "WINDOW_REUSE_WAIT", 0.2)      # a window that is still starting never comes up here
    scenario = SCENARIOS[name]
    python = run_scenario("python", name, server, binary, scenario, kind, tmp_path)
    rust = run_scenario("rust", name, server, binary, scenario, kind, tmp_path)
    assert rust == python, (name, kind)


def test_the_scenarios_are_not_vacuous(server, binary, tmp_path, monkeypatch):
    """Python's answers cover every outcome, a request that arrived, and a title that was set."""
    monkeypatch.setattr(tmux_control, "WINDOW_REUSE_WAIT", 0.2)
    seen = {}
    for name in ("the window takes it", "busy with a message", "invalid", "another kind of window"):
        seen[name] = run_scenario("python", name, server, binary, SCENARIOS[name], "cron", tmp_path)
    assert seen["the window takes it"] == {"outcome": "done", "message": None, "title": TITLE,
                                           "received": [{**REQUESTS["cron"], "client": server[1]}]}
    assert seen["busy with a message"]["outcome"] == "busy" and seen["busy with a message"]["message"] == "An answer is being sent."
    assert seen["busy with a message"]["title"] == TITLE_BEFORE
    assert seen["invalid"]["outcome"] == "fallback" and seen["invalid"]["received"] == [{**REQUESTS["cron"], "client": server[1]}]
    assert seen["another kind of window"] == {"outcome": "fallback", "message": None, "title": TITLE_BEFORE, "received": []}
