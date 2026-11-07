"""Observable tmux placement and client-directed Board clicks."""
import fcntl
import json
import os
from pathlib import Path
import pty
import shutil
import socket
import stat
import struct
import subprocess
import tempfile
import termios
import threading
import time
import uuid

import pytest

import board_testing  # noqa: F401  (adds the Board tool to sys.path)
from project_board import tmux_control


def _tmux(name, *args):
    return subprocess.run(["tmux", "-L", name, *args], capture_output=True, text=True,
                          check=True, timeout=5).stdout.strip()


def _attached(name, session):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    client = os.ttyname(slave)
    process = subprocess.Popen(["tmux", "-L", name, "attach-session", "-t", session],
                               stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
                               env={**os.environ, "TERM": "xterm-256color"})
    os.close(slave)
    for _ in range(50):
        if client in _tmux(name, "list-clients", "-F", "#{client_name}").splitlines():
            return process, master, client
        time.sleep(0.05)
    process.terminate()
    os.close(master)
    pytest.fail("tmux client did not attach")


@pytest.mark.skipif(shutil.which("tmux") is None,
                    reason="tmux is unavailable")
def test_global_sidebar_tracks_attached_windows_and_preserves_existing_panes(monkeypatch):
    name = "board-test-" + uuid.uuid4().hex[:12]
    clients = []
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-s", "one", "sleep", "60")
        _tmux(name, "new-session", "-d", "-s", "two", "sleep", "60")
        first_window = _tmux(name, "display-message", "-p", "-t", "one", "#{window_id}")
        second_window = _tmux(name, "display-message", "-p", "-t", "two", "#{window_id}")
        original = set(_tmux(name, "list-panes", "-a", "-F", "#{pane_id}").splitlines())
        clients.append(_attached(name, "one"))
        clients.append(_attached(name, "two"))
        socket_path = _tmux(name, "display-message", "-p", "#{socket_path}")
        monkeypatch.setattr(tmux_control, "_sidebar_command", lambda _config: ["sleep", "60"])

        result = tmux_control.toggle_sidebar(socket=socket_path)
        assert result["ok"] is True
        assert set(result["data"]["created"]) == {first_window, second_window}
        assert len(_tmux(name, "list-panes", "-a", "-F", "#{pane_id}").splitlines()) == 4

        _tmux(name, "switch-client", "-c", clients[0][2], "-t", "two")
        result = tmux_control.reconcile(socket=socket_path)
        assert result["ok"] is True
        assert result["data"]["removed"] == [first_window]
        assert _tmux(name, "show-options", "-wqv", "-t", first_window,
                     "@project_board_pane") == ""

        result = tmux_control.toggle_sidebar(socket=socket_path)
        assert result["ok"] is True
        assert result["data"]["enabled"] is False
        assert set(_tmux(name, "list-panes", "-a", "-F", "#{pane_id}").splitlines()) == original
    finally:
        for process, master, _client in clients:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            os.close(master)
        subprocess.run(["tmux", "-L", name, "kill-server"], capture_output=True, timeout=5)


def test_click_socket_receives_the_exact_client_and_rejects_stale_window(monkeypatch):
    short_dir = tempfile.TemporaryDirectory(prefix="board-click-", dir="/tmp")
    click_path = Path(short_dir.name) / "click.sock"
    received = []
    ready = threading.Event()

    def serve():
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(click_path))
            os.chmod(click_path, 0o600)
            server.listen(1)
            ready.set()
            connection, _ = server.accept()
            with connection:
                received.append(json.loads(connection.makefile("r").readline()))
                connection.sendall(b'{"ok":true,"data":{"widget":"decision"},"error":null}\n')

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert ready.wait(2)
    assert stat.S_ISSOCK(click_path.stat().st_mode)

    class FakeControl:
        current = "@1"

        def command(self, *args):
            if args[:2] == ("list-clients", "-F"):
                return "/dev/ttys1\t" + self.current if "\t" in args[2] else "/dev/ttys1"
            if args[0] == "display-message":
                return "@1"
            if args[0] == "show-options":
                return {"@project_board_enabled": "1", "@project_board_pane": "%4",
                        "@project_board_managed": "1",
                        "@project_board_click_socket": str(click_path)}[args[-1]]
            raise AssertionError(args)

    control = FakeControl()
    monkeypatch.setattr(tmux_control, "_control", lambda _socket: control)
    assert tmux_control.route_click("/dev/ttys1", "%4", 2, 3)["ok"] is True
    thread.join(timeout=2)
    assert received == [{"client": "/dev/ttys1", "x": 2, "y": 3}]
    control.current = "@2"
    stale = tmux_control.route_click("/dev/ttys1", "%4", 2, 3)
    assert stale["error"]["code"] == "click_stale"
    short_dir.cleanup()


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_project_click_switches_only_selected_client_to_session_current_window(tmp_path):
    board = board_testing.Board(tmp_path)
    board.project("one")
    board.project("two")
    board.project("two-extra")
    board.project("missing")
    name = "board-test-" + uuid.uuid4().hex[:12]
    clients = []
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-s", "one", "sleep", "60")
        _tmux(name, "new-session", "-d", "-s", "two-extra", "sleep", "60")
        _tmux(name, "new-session", "-d", "-s", "two", "sleep", "60")
        _tmux(name, "new-window", "-d", "-t", "two", "sleep", "60")
        _tmux(name, "select-window", "-t", "two:1")
        current = _tmux(name, "display-message", "-p", "-t", "two", "#{window_id}")
        clients.append(_attached(name, "one"))
        clients.append(_attached(name, "one"))
        selected, other = clients[0][2], clients[1][2]
        socket_path = _tmux(name, "display-message", "-p", "#{socket_path}")

        result = tmux_control.switch_project(str(board.config), "two", selected, socket_path)
        assert result["ok"] is True
        rows = dict(row.split("\t", 1) for row in _tmux(name, "list-clients", "-F", "#{client_name}\t#{session_name}\t#{window_id}").splitlines())
        assert rows[selected] == f"two\t{current}"
        assert rows[other].startswith("one\t")

        missing = tmux_control.switch_project(str(board.config), "missing", selected, socket_path)
        assert missing["error"]["code"] == "project_session_missing"
        unknown = tmux_control.switch_project(str(board.config), "unregistered", selected, socket_path)
        assert unknown["error"]["code"] == "project_not_found"
        after = dict(row.split("\t", 1) for row in _tmux(name, "list-clients", "-F", "#{client_name}\t#{session_name}\t#{window_id}").splitlines())
        assert after == rows
    finally:
        for process, master, _client in clients:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            os.close(master)
        subprocess.run(["tmux", "-L", name, "kill-server"], capture_output=True, timeout=5)
