"""Observable tmux placement and client-directed Board clicks."""
import fcntl
import json
import os
from pathlib import Path
import pty
import shutil
import signal
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


def _pane_geometry(name, window):
    rows = _tmux(name, "list-panes", "-t", window,
                 "-F", "#{pane_id}\t#{pane_width}\t#{pane_height}\t#{pane_left}\t#{pane_top}\t#{pane_active}")
    geometry = {}
    for row in rows.splitlines():
        parts = row.split("\t")
        geometry[parts[0]] = tuple(map(int, parts[1:]))
    return geometry


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
        first_geometry = _pane_geometry(name, first_window)
        second_geometry = _pane_geometry(name, second_window)
        socket_path = _tmux(name, "display-message", "-p", "#{socket_path}")
        monkeypatch.setattr(tmux_control, "_sidebar_command", lambda _config: ["sleep", "60"])

        result = tmux_control.toggle_sidebar(socket=socket_path)
        assert result["ok"] is True
        assert set(result["data"]["created"]) == {first_window, second_window}
        assert len(_tmux(name, "list-panes", "-a", "-F", "#{pane_id}").splitlines()) == 4
        for window, before in ((first_window, first_geometry), (second_window, second_geometry)):
            after = _pane_geometry(name, window)
            board = _tmux(name, "show-options", "-wqv", "-t", window, "@project_board_pane")
            board_width, board_height, board_left, board_top, _ = after[board]
            assert (board_left, board_top, board_height) == (0, 0, next(iter(before.values()))[1])
            assert board_width == 25
            for pane, (width, height, left, top, active) in before.items():
                assert after[pane] == (width - board_width - 1, height, left + board_width + 1, top, active)

        first_board = _tmux(name, "show-options", "-wqv", "-t", first_window,
                            "@project_board_pane")
        _tmux(name, "resize-pane", "-t", first_board, "-x", "33")
        _tmux(name, "set-option", "-g", "@project_board_width", "33")
        assert tmux_control.reconcile(socket=socket_path)["ok"] is True
        second_board = _tmux(name, "show-options", "-wqv", "-t", second_window,
                             "@project_board_pane")
        assert _pane_geometry(name, second_window)[second_board][0] == 33

        _tmux(name, "switch-client", "-c", clients[0][2], "-t", "two")
        result = tmux_control.reconcile(socket=socket_path)
        assert result["ok"] is True
        assert result["data"]["removed"] == [first_window]
        assert _tmux(name, "show-options", "-wqv", "-t", first_window,
                     "@project_board_pane") == ""
        assert _tmux(name, "show-options", "-wqv", "-t", first_window,
                     "@project_board_restore") == ""
        assert _pane_geometry(name, first_window) == first_geometry

        result = tmux_control.toggle_sidebar(socket=socket_path)
        assert result["ok"] is True
        assert result["data"]["enabled"] is False
        assert set(_tmux(name, "list-panes", "-a", "-F", "#{pane_id}").splitlines()) == original
        assert _pane_geometry(name, second_window) == second_geometry
        assert _tmux(name, "show-options", "-wqv", "-t", second_window,
                     "@project_board_restore") == ""
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


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_sidebar_restores_split_layout_and_focus_after_selecting_board(monkeypatch):
    name = "board-test-" + uuid.uuid4().hex[:12]
    clients = []
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-x", "101", "-y", "31",
              "-s", "one", "sleep", "60")
        first = _tmux(name, "display-message", "-p", "-t", "one", "#{pane_id}")
        right = _tmux(name, "split-window", "-d", "-h", "-l", "24", "-P", "-F", "#{pane_id}",
                      "-t", first, "sleep", "60")
        _tmux(name, "split-window", "-d", "-v", "-l", "10", "-t", first, "sleep", "60")
        _tmux(name, "select-pane", "-t", right)
        clients.append(_attached(name, "one"))
        window = _tmux(name, "display-message", "-p", "-t", "one", "#{window_id}")
        before = _pane_geometry(name, window)
        socket_path = _tmux(name, "display-message", "-p", "#{socket_path}")
        monkeypatch.setattr(tmux_control, "_sidebar_command", lambda _config: ["sleep", "60"])

        assert tmux_control.toggle_sidebar(socket=socket_path)["ok"] is True
        after = _pane_geometry(name, window)
        board = _tmux(name, "show-options", "-wqv", "-t", window, "@project_board_pane")
        board_width, board_height, board_left, board_top, _ = after[board]
        original_height = max(row[1] + row[3] for row in before.values())
        assert (board_left, board_top, board_height) == (0, 0, original_height)
        assert board_width > 0
        assert all(after[pane][2] >= board_width + 1 for pane in before)
        assert after[right][4] == 1

        _tmux(name, "select-pane", "-t", board)
        assert tmux_control.toggle_sidebar(socket=socket_path)["ok"] is True
        assert _pane_geometry(name, window) == before
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


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_sidebar_keeps_resized_width_across_window_changes(monkeypatch):
    name = "board-test-" + uuid.uuid4().hex[:12]
    clients = []
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-s", "one", "sleep", "60")
        _tmux(name, "new-session", "-d", "-s", "two", "sleep", "60")
        first = _tmux(name, "display-message", "-p", "-t", "one", "#{window_id}")
        second = _tmux(name, "display-message", "-p", "-t", "two", "#{window_id}")
        clients.append(_attached(name, "two"))
        original = {window: set(_pane_geometry(name, window)) for window in (first, second)}
        socket_path = _tmux(name, "display-message", "-p", "#{socket_path}")
        monkeypatch.setattr(tmux_control, "_sidebar_command", lambda _config: ["sleep", "60"])

        assert tmux_control.toggle_sidebar(socket=socket_path)["ok"] is True
        board = _tmux(name, "show-options", "-wqv", "-t", second, "@project_board_pane")
        _tmux(name, "resize-pane", "-t", board, "-x", "33")
        assert _pane_geometry(name, second)[board][0] == 33

        _tmux(name, "switch-client", "-c", clients[0][2], "-t", "one")
        assert tmux_control.reconcile(socket=socket_path)["ok"] is True
        board = _tmux(name, "show-options", "-wqv", "-t", first, "@project_board_pane")
        assert _pane_geometry(name, first)[board][0] == 33
        assert set(_pane_geometry(name, second)) == original[second]

        _tmux(name, "switch-client", "-c", clients[0][2], "-t", "two")
        assert tmux_control.reconcile(socket=socket_path)["ok"] is True
        board = _tmux(name, "show-options", "-wqv", "-t", second, "@project_board_pane")
        assert _pane_geometry(name, second)[board][0] == 33
        assert set(_pane_geometry(name, first)) == original[first]

        assert tmux_control.toggle_sidebar(socket=socket_path)["ok"] is True
        assert set(_pane_geometry(name, second)) == original[second]
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


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_resize_hook_records_only_board_pane_width():
    name = "board-test-" + uuid.uuid4().hex[:12]
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-x", "100", "-y", "30",
              "sleep", "60")
        _tmux(name, "source-file", str(Path(__file__).resolve().parents[4] /
                                       "tmux/scripts/project_board.conf"))
        board = _tmux(name, "split-window", "-h", "-b", "-l", "25", "-P", "-F", "#{pane_id}",
                      "sleep", "60")
        window = _tmux(name, "display-message", "-p", "#{window_id}")
        other = next(pane for pane in _pane_geometry(name, window) if pane != board)
        _tmux(name, "set-option", "-p", "-t", board, "@project_board_managed", "1")

        _tmux(name, "resize-pane", "-t", board, "-x", "33")
        assert _tmux(name, "show-options", "-gqv", "@project_board_width") == "33"
        _tmux(name, "resize-pane", "-t", other, "-x", "60")
        assert _tmux(name, "show-options", "-gqv", "@project_board_width") == "33"
    finally:
        subprocess.run(["tmux", "-L", name, "kill-server"], capture_output=True, timeout=5)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_managed_pane_death_removes_board_and_restore_state(monkeypatch):
    name = "board-test-" + uuid.uuid4().hex[:12]
    clients = []
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-s", "one", "sleep", "60")
        _tmux(name, "set-option", "-g", "remain-on-exit", "on")
        clients.append(_attached(name, "one"))
        _tmux(name, "source-file", str(Path(__file__).resolve().parents[4] /
                                       "tmux/scripts/project_board.conf"))
        window = _tmux(name, "display-message", "-p", "-t", "one", "#{window_id}")
        managed = _tmux(name, "display-message", "-p", "-t", "one", "#{pane_id}")
        _tmux(name, "set-option", "-w", "-t", window, "@agent_session_pane_id",
              json.dumps(managed))
        socket_path = _tmux(name, "display-message", "-p", "#{socket_path}")
        monkeypatch.setattr(tmux_control, "_sidebar_command", lambda _config: ["sleep", "60"])

        assert tmux_control.toggle_sidebar(socket=socket_path)["ok"] is True
        board = _tmux(name, "show-options", "-wqv", "-t", window, "@project_board_pane")
        assert board in _pane_geometry(name, window)
        pid = int(_tmux(name, "display-message", "-p", "-t", managed, "#{pane_pid}"))
        os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            if board not in _pane_geometry(name, window):
                break
            time.sleep(0.05)
        assert board not in _pane_geometry(name, window)
        assert _tmux(name, "show-options", "-wqv", "-t", window, "@project_board_pane") == ""
        assert _tmux(name, "show-options", "-wqv", "-t", window, "@project_board_restore") == ""
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
