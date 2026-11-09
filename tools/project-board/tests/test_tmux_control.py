"""Observable tmux placement and client-directed Board clicks."""
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import shlex
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
import tmux_test_server
from project_board import tmux_control
from board_testing import Board, session
from agent_session.tmux import Tmux


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


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_ending_a_test_server_removes_the_runtime_directory_the_board_made_for_it():
    """tmux_test_server removes `/tmp/project-board-<uid>-<server pid>`; the product owns that name."""
    name = tmux_test_server.claim("board-test")
    directory = None
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-s", "home", "sleep", "60")
        directory = tmux_control._private_dir(Tmux(socket_name=name))
        assert directory.is_dir()
    finally:
        tmux_test_server.release(name)
    assert directory is not None and not directory.exists()
    assert not tmux_test_server.socket_path(name).exists()


SOCK = "0123456789abcdef.sock"


def _runtime_directory(root, pid, uid=None, mode=0o700, files=("control.lock",)):
    """A Board runtime directory as `_private_dir` leaves it; `.sock` names are real sockets."""
    directory = root / f"project-board-{os.getuid() if uid is None else uid}-{pid}"
    directory.mkdir(mode=0o700)
    for name in files:
        if name.endswith(".sock"):
            # A unix socket path is limited to ~100 bytes; bind by a relative name from inside.
            here = os.getcwd()
            os.chdir(directory)
            try:
                with socket.socket(socket.AF_UNIX) as bound:
                    bound.bind(name)
            finally:
                os.chdir(here)
        else:
            (directory / name).write_text("")
    directory.chmod(mode)
    return directory


def _dead_pid():
    process = subprocess.Popen(["true"])
    process.wait()
    return process.pid


def _server_pid(name):
    _tmux(name, "-f", "/dev/null", "new-session", "-d", "-s", "home", "sleep", "60")
    return int(_tmux(name, "display-message", "-p", "#{pid}"))


@pytest.fixture
def runtime_root(tmp_path, monkeypatch):
    """A private stand-in for `/tmp`, so a sweep never sees the user's real directories."""
    root = tmp_path / "t"
    root.mkdir()
    monkeypatch.setattr(tmux_control, "RUNTIME_ROOT", root)
    return root


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_next_board_start_removes_the_directory_of_a_server_that_was_killed(runtime_root):
    ended = tmux_test_server.claim("board-test")
    running = tmux_test_server.claim("board-test")
    try:
        _server_pid(ended)
        _server_pid(running)
        gone = tmux_control._private_dir(Tmux(socket_name=ended))
        kept = tmux_control._private_dir(Tmux(socket_name=running))
        assert gone.is_dir() and kept.is_dir()
        tmux_test_server.release(ended)
        assert gone.is_dir(), "kill-server leaves the directory; only the next Board start removes it"

        assert tmux_control._private_dir(Tmux(socket_name=running)) == kept
        assert not gone.exists()
        assert kept.is_dir(), "a live server's directory stays"
    finally:
        tmux_test_server.release(ended)
        tmux_test_server.release(running)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_sweep_removes_directories_of_ended_servers_and_of_pids_tmux_no_longer_holds(runtime_root):
    live, recycled = tmux_test_server.claim("board-test"), tmux_test_server.claim("board-test")
    stranger = subprocess.Popen(["sleep", "60"])
    try:
        live_pid, recycled_pid = _server_pid(live), _server_pid(recycled)
        kept = _runtime_directory(runtime_root, live_pid, files=("control.lock", SOCK))
        gone = [
            _runtime_directory(runtime_root, _dead_pid(), files=("control.lock", SOCK)),
            _runtime_directory(runtime_root, _dead_pid(), files=()),
            _runtime_directory(runtime_root, stranger.pid),  # the pid is alive but is not tmux
            _runtime_directory(runtime_root, recycled_pid),  # tmux, but newer than the directory
        ]
        old = time.time() - 3600
        os.utime(gone[-1], (old, old))

        assert sorted(tmux_control.reap_runtime_directories(runtime_root)) == sorted(gone)
        assert [path.exists() for path in gone] == [False] * 4
        assert kept.is_dir() and (kept / SOCK).exists()
    finally:
        stranger.kill()
        stranger.wait()
        tmux_test_server.release(live)
        tmux_test_server.release(recycled)


def test_sweep_leaves_everything_that_is_not_an_ended_boards_own_directory(runtime_root, tmp_path):
    pid = _dead_pid()
    uid = os.getuid()
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "control.lock").write_text("")
    stray = _runtime_directory(runtime_root, pid + 1, files=("control.lock", "notes.txt"))
    odd_socket = _runtime_directory(runtime_root, pid + 2, files=("control.lock",))
    (odd_socket / SOCK).write_text("not a socket")
    nested = _runtime_directory(runtime_root, pid + 3, files=("control.lock",))
    (nested / "sub").mkdir()
    (runtime_root / f"project-board-{uid}-{pid + 4}").symlink_to(target)
    kept = [
        stray, odd_socket, nested, target,
        _runtime_directory(runtime_root, pid + 5, mode=0o755),
        _runtime_directory(runtime_root, pid + 6, uid=uid + 1),
        runtime_root / f"project-board-{uid}-{pid + 4}",
    ]
    for name in (f"project-board-{uid}-abc", f"project-board-{uid}-{pid}-x", f"project-board-{uid}",
                 f"x-project-board-{uid}-{pid}", f"project-board-ui-{pid}"):
        (runtime_root / name).mkdir()
        kept.append(runtime_root / name)

    assert tmux_control.reap_runtime_directories(runtime_root) == []
    assert all(path.exists() for path in kept)
    assert (target / "control.lock").exists()


def test_concurrent_sweeps_of_the_same_directory_both_finish(runtime_root):
    for _ in range(20):
        directory = _runtime_directory(runtime_root, _dead_pid(), files=("control.lock", SOCK))
        errors = []

        def sweep():
            try:
                tmux_control.reap_runtime_directories(runtime_root)
            except BaseException as error:  # noqa: BLE001 - any escape is the failure
                errors.append(error)

        threads = [threading.Thread(target=sweep) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == [] and not directory.exists()


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_remote_seat_switch_uses_its_local_display_window_for_only_clicking_client(tmp_path):
    board = Board(tmp_path)
    base = board.project("remote-project", seats=1)
    board.registry[str(base)]["seats"][0] = {
        "host": "macbook-worker", "path": "/Users/swain/Agent/remote-seat"}
    board.config.write_text(json.dumps(board.registry), encoding="utf-8")
    board.state(base, {"leader": None,
                       "0": {"job_id": "TOOL-001", "git_hash": None, "session": session(0)}})
    name = tmux_test_server.claim("board-test")
    clients = []
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-s", "home", "sleep", "60")
        control = Tmux(socket_name=name)
        display = control.create_window("remote-project", "remote-worker", base, {
            "base": str(base), "target": "seat-0", "run_id": uuid.uuid4().hex,
            "session_id": session(0)["session_id"], "host": "macbook-worker",
        })
        control.set_current("remote-project", "seat-0", display)
        clients.append(_attached(name, "home"))
        clients.append(_attached(name, "home"))
        selected, other = clients[0][2], clients[1][2]
        socket_path = _tmux(name, "display-message", "-p", "#{socket_path}")

        result = tmux_control.switch_seat(str(board.config), "remote-project", 0, selected, socket_path)
        assert result["ok"] is True
        assert result["data"]["pane"] == display["pane_id"]
        rows = dict(row.split("\t", 1) for row in _tmux(
            name, "list-clients", "-F", "#{client_name}\t#{session_name}\t#{pane_id}").splitlines())
        assert rows[selected] == f"remote-project\t{display['pane_id']}"
        assert rows[other].startswith("home\t")
    finally:
        for process, master, _client in clients:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            os.close(master)
        tmux_test_server.release(name)


@pytest.mark.skipif(shutil.which("tmux") is None,
                    reason="tmux is unavailable")
def test_global_sidebar_tracks_attached_windows_and_preserves_existing_panes(monkeypatch):
    name = tmux_test_server.claim("board-test")
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
        assert tmux_control.expanded_projects(socket_path) == set()
        assert tmux_control.toggle_expanded_project("one", socket_path) == {"one"}
        assert tmux_control.toggle_expanded_project("two", socket_path) == {"one", "two"}
        assert tmux_control.toggle_expanded_project("two", socket_path) == {"one"}
        assert json.loads(_tmux(name, "show-options", "-sqv", "@project_board_expanded")) == ["one"]
        barrier = threading.Barrier(3)
        failures = []

        def toggle_from_client(project_id):
            try:
                barrier.wait(timeout=5)
                tmux_control.toggle_expanded_project(project_id, socket_path)
            except Exception as error:
                failures.append(error)

        workers = [threading.Thread(target=toggle_from_client, args=(project_id,))
                   for project_id in ("two", "three")]
        for worker in workers:
            worker.start()
        barrier.wait(timeout=5)
        for worker in workers:
            worker.join(timeout=5)
        assert not failures
        assert not any(worker.is_alive() for worker in workers)
        assert tmux_control.expanded_projects(socket_path) == {"one", "two", "three"}
        tmux_control.toggle_expanded_project("two", socket_path)
        tmux_control.toggle_expanded_project("three", socket_path)
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

        # BOARD-002: a window the last client left keeps its Board pane, so returning to it starts nothing.
        _tmux(name, "switch-client", "-c", clients[0][2], "-t", "two")
        result = tmux_control.reconcile(socket=socket_path)
        assert result["ok"] is True
        assert result["data"]["removed"] == [] and result["data"]["created"] == []
        assert _tmux(name, "show-options", "-wqv", "-t", first_window,
                     "@project_board_pane") == first_board
        assert first_board in _pane_geometry(name, first_window)
        assert tmux_control.expanded_projects(socket_path) == {"one"}

        _tmux(name, "switch-client", "-c", clients[0][2], "-t", "one")
        result = tmux_control.reconcile(socket=socket_path)
        assert result["ok"] is True and result["data"]["created"] == []
        assert _tmux(name, "show-options", "-wqv", "-t", first_window,
                     "@project_board_pane") == first_board
        assert tmux_control.expanded_projects(socket_path) == {"one"}

        result = tmux_control.toggle_sidebar(socket=socket_path)
        assert result["ok"] is True
        assert result["data"]["enabled"] is False
        assert tmux_control.expanded_projects(socket_path) == {"one"}
        assert tmux_control.toggle_sidebar(socket=socket_path)["ok"] is True
        assert tmux_control.expanded_projects(socket_path) == {"one"}
        assert tmux_control.toggle_sidebar(socket=socket_path)["ok"] is True
        assert set(_tmux(name, "list-panes", "-a", "-F", "#{pane_id}").splitlines()) == original
        assert _pane_geometry(name, first_window) == first_geometry
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
        tmux_test_server.release(name)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_sidebar_restores_split_layout_and_focus_after_selecting_board(monkeypatch):
    name = tmux_test_server.claim("board-test")
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
        tmux_test_server.release(name)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_sidebar_keeps_resized_width_across_window_changes(monkeypatch):
    name = tmux_test_server.claim("board-test")
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
        # The after-resize-pane hook of project-agent-main.conf records this (test_resize_hook_...).
        _tmux(name, "set-option", "-g", "@project_board_width", "33")
        assert _pane_geometry(name, second)[board][0] == 33
        second_board = board

        _tmux(name, "switch-client", "-c", clients[0][2], "-t", "one")
        assert tmux_control.reconcile(socket=socket_path)["ok"] is True
        board = _tmux(name, "show-options", "-wqv", "-t", first, "@project_board_pane")
        assert _pane_geometry(name, first)[board][0] == 33
        # The window the client left keeps its Board pane (BOARD-002).
        assert set(_pane_geometry(name, second)) == original[second] | {second_board}

        _tmux(name, "switch-client", "-c", clients[0][2], "-t", "two")
        assert tmux_control.reconcile(socket=socket_path)["ok"] is True
        board = _tmux(name, "show-options", "-wqv", "-t", second, "@project_board_pane")
        assert board == second_board
        assert _pane_geometry(name, second)[board][0] == 33
        assert set(_pane_geometry(name, first)) == original[first] | {_tmux(
            name, "show-options", "-wqv", "-t", first, "@project_board_pane")}

        assert tmux_control.toggle_sidebar(socket=socket_path)["ok"] is True
        assert set(_pane_geometry(name, first)) == original[first]
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
        tmux_test_server.release(name)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_kept_board_panes_are_bounded_and_the_longest_unseen_window_goes_first(monkeypatch):
    name = tmux_test_server.claim("board-test")
    clients = []
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-s", "one", "sleep", "60")
        for session_name in ("two", "three", "four"):
            _tmux(name, "new-session", "-d", "-s", session_name, "sleep", "60")
        windows = {n: _tmux(name, "display-message", "-p", "-t", n, "#{window_id}")
                   for n in ("one", "two", "three", "four")}
        original = {n: _pane_geometry(name, w) for n, w in windows.items()}
        clients.append(_attached(name, "one"))
        socket_path = _tmux(name, "display-message", "-p", "#{socket_path}")
        monkeypatch.setattr(tmux_control, "_sidebar_command", lambda _config: ["sleep", "60"])
        monkeypatch.setattr(tmux_control, "MAX_KEPT", 3)

        def board(window):
            return _tmux(name, "show-options", "-wqv", "-t", window, "@project_board_pane")

        def visit(session_name, seen):
            _tmux(name, "switch-client", "-c", clients[0][2], "-t", session_name)
            result = tmux_control.reconcile(socket=socket_path)
            assert result["ok"] is True
            # project_board_visibility.sh stamps the window a client shows; the test stamps it directly.
            _tmux(name, "set-option", "-w", "-t", windows[session_name], "@project_board_seen", str(seen))
            return result["data"]

        assert tmux_control.toggle_sidebar(socket=socket_path)["ok"] is True
        _tmux(name, "set-option", "-w", "-t", windows["one"], "@project_board_seen", "100")
        assert visit("two", 200)["removed"] == []
        assert visit("three", 300)["removed"] == []                  # three kept panes: the bound
        assert all(board(windows[n]) for n in ("one", "two", "three"))
        # A fourth window evicts the one shown longest ago (one), never the window being shown.
        data = visit("four", 400)
        assert data["created"] == [windows["four"]] and data["removed"] == [windows["one"]]
        assert board(windows["one"]) == ""
        assert set(_pane_geometry(name, windows["one"])) == set(original["one"])   # only its own pane is left
        assert _tmux(name, "show-options", "-wqv", "-t", windows["one"], "@project_board_restore") == ""
        assert all(board(windows[n]) for n in ("two", "three", "four"))
        # Back to the evicted window: it gets a new pane and now two is the oldest.
        _tmux(name, "set-option", "-w", "-t", windows["two"], "@project_board_seen", "250")
        data = visit("one", 500)
        assert data["created"] == [windows["one"]] and data["removed"] == [windows["two"]]
    finally:
        for process, master, _client in clients:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            os.close(master)
        tmux_test_server.release(name)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_a_board_pane_asks_tmux_whether_a_client_shows_its_window(monkeypatch):
    name = tmux_test_server.claim("board-test")
    clients = []
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-s", "one", "sleep", "60")
        _tmux(name, "new-session", "-d", "-s", "two", "sleep", "60")
        panes = {n: _tmux(name, "display-message", "-p", "-t", n, "#{pane_id}") for n in ("one", "two")}
        socket_path = _tmux(name, "display-message", "-p", "#{socket_path}")
        clients.append(_attached(name, "one"))
        monkeypatch.setenv("TMUX_PANE", panes["one"])
        assert tmux_control.mark_ready(socket_path) is True
        assert _tmux(name, "show-options", "-pqv", "-t", panes["one"], "@project_board_ready") == "1"
        monkeypatch.setenv("TMUX_PANE", panes["two"])
        assert tmux_control.board_visible(socket_path) is False
        _tmux(name, "switch-client", "-c", clients[0][2], "-t", "two")
        assert tmux_control.board_visible(socket_path) is True
        monkeypatch.delenv("TMUX_PANE")
        assert tmux_control.board_visible(socket_path) is True      # outside tmux: keep reading
    finally:
        for process, master, _client in clients:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            os.close(master)
        tmux_test_server.release(name)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_sidebar_keeps_requested_width_after_a_narrow_window(monkeypatch):
    name = tmux_test_server.claim("board-test")
    clients = []
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-x", "80", "-y", "24",
              "-s", "wide", "sleep", "60")
        _tmux(name, "set-option", "-g", "window-size", "manual")
        _tmux(name, "new-session", "-d", "-x", "20", "-y", "24", "-s", "narrow",
              "sleep", "60")
        wide = _tmux(name, "display-message", "-p", "-t", "wide", "#{window_id}")
        narrow = _tmux(name, "display-message", "-p", "-t", "narrow", "#{window_id}")
        clients.append(_attached(name, "wide"))
        assert _tmux(name, "display-message", "-p", "-t", wide, "#{window_width}") == "80"
        assert _tmux(name, "display-message", "-p", "-t", narrow, "#{window_width}") == "20"
        socket_path = _tmux(name, "display-message", "-p", "#{socket_path}")
        monkeypatch.setattr(tmux_control, "_sidebar_command", lambda _config: ["sleep", "60"])

        assert tmux_control.toggle_sidebar(socket=socket_path)["ok"] is True
        board = _tmux(name, "show-options", "-wqv", "-t", wide, "@project_board_pane")
        _tmux(name, "resize-pane", "-t", board, "-x", "33")
        _tmux(name, "set-option", "-g", "@project_board_width", "33")   # what the resize hook records
        assert _pane_geometry(name, wide)[board][0] == 33

        _tmux(name, "switch-client", "-c", clients[0][2], "-t", "narrow")
        assert tmux_control.reconcile(socket=socket_path)["ok"] is True
        board = _tmux(name, "show-options", "-wqv", "-t", narrow, "@project_board_pane")
        assert _pane_geometry(name, narrow)[board][0] < 33

        _tmux(name, "switch-client", "-c", clients[0][2], "-t", "wide")
        assert tmux_control.reconcile(socket=socket_path)["ok"] is True
        board = _tmux(name, "show-options", "-wqv", "-t", wide, "@project_board_pane")
        actual = (_pane_geometry(name, wide)[board][0],
                  int(_tmux(name, "show-options", "-gqv", "@project_board_width")))
        assert actual == (33, 33)
    finally:
        for process, master, _client in clients:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            os.close(master)
        tmux_test_server.release(name)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_sidebar_keeps_requested_width_after_a_split_window(monkeypatch):
    name = tmux_test_server.claim("board-test")
    clients = []
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-x", "80", "-y", "24",
              "-s", "one", "sleep", "60")
        _tmux(name, "set-option", "-g", "window-size", "manual")
        _tmux(name, "new-session", "-d", "-x", "80", "-y", "24", "-s", "two",
              "sleep", "60")
        first = _tmux(name, "display-message", "-p", "-t", "one", "#{window_id}")
        second = _tmux(name, "display-message", "-p", "-t", "two", "#{window_id}")
        _tmux(name, "split-window", "-d", "-h", "-l", "20", "-t", second, "sleep", "60")
        assert len(_pane_geometry(name, first)) == 1
        assert len(_pane_geometry(name, second)) == 2
        clients.append(_attached(name, "one"))
        clients.append(_attached(name, "two"))
        socket_path = _tmux(name, "display-message", "-p", "#{socket_path}")
        monkeypatch.setattr(tmux_control, "_sidebar_command", lambda _config: ["sleep", "60"])

        assert tmux_control.toggle_sidebar(socket=socket_path)["ok"] is True
        board = _tmux(name, "show-options", "-wqv", "-t", first, "@project_board_pane")
        _tmux(name, "resize-pane", "-t", board, "-x", "77")
        assert _pane_geometry(name, first)[board][0] == 77
        _tmux(name, "set-option", "-g", "@project_board_width", "77")

        _tmux(name, "switch-client", "-c", clients[0][2], "-t", "two")
        assert tmux_control.reconcile(socket=socket_path)["ok"] is True
        board = _tmux(name, "show-options", "-wqv", "-t", second, "@project_board_pane")
        assert _pane_geometry(name, second)[board][0] == 76

        _tmux(name, "switch-client", "-c", clients[0][2], "-t", "one")
        _tmux(name, "switch-client", "-c", clients[1][2], "-t", "one")
        assert tmux_control.reconcile(socket=socket_path)["ok"] is True
        board = _tmux(name, "show-options", "-wqv", "-t", first, "@project_board_pane")
        actual = (_pane_geometry(name, first)[board][0],
                  int(_tmux(name, "show-options", "-gqv", "@project_board_width")))
        assert actual == (77, 77)
    finally:
        for process, master, _client in clients:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            os.close(master)
        tmux_test_server.release(name)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_resize_hook_records_only_board_pane_width():
    name = tmux_test_server.claim("board-test")
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-x", "100", "-y", "30",
              "sleep", "60")
        _tmux(name, "source-file", str(Path(__file__).resolve().parents[3] /
                                       "integrations/tmux/project-agent.conf"))
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
        tmux_test_server.release(name)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_managed_pane_death_removes_board_and_restore_state(monkeypatch):
    name = tmux_test_server.claim("board-test")
    clients = []
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-s", "one", "sleep", "60")
        _tmux(name, "set-option", "-g", "remain-on-exit", "on")
        clients.append(_attached(name, "one"))
        _tmux(name, "source-file", str(Path(__file__).resolve().parents[3] /
                                       "integrations/tmux/project-agent.conf"))
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
        tmux_test_server.release(name)


def test_click_socket_receives_the_exact_client_and_rejects_stale_window(monkeypatch, request):
    short_dir = tempfile.TemporaryDirectory(prefix="board-click-", dir="/tmp")
    request.addfinalizer(short_dir.cleanup)
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


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_project_click_switches_only_selected_client_to_session_current_window(tmp_path):
    board = board_testing.Board(tmp_path)
    board.project("one")
    board.project("two")
    board.project("two-extra")
    board.project("missing")
    name = tmux_test_server.claim("board-test")
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
        tmux_test_server.release(name)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
@pytest.mark.parametrize("bare", [True, False])
def test_a_failing_popup_never_covers_the_work_pane_and_the_client_is_told(bare):
    """BOARD-011: `display-popup -E` ends with the exit status of its command. As a bare `run-shell` job a
    failure opened view mode in the active pane (`bare`, the check that the test can see it); the Board's own
    popup records the failure and shows it on the client that opened the popup."""
    name = tmux_test_server.claim("board-popup")
    process = master = None
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-s", "work", "sleep", "60")
        process, master, client = _attached(name, "work")
        control = Tmux(socket_name=name)
        command = ["sh", "-c", "echo noisy; echo noisy >&2; exit 3"]
        if bare:
            socket_path = _tmux(name, "display-message", "-p", "#{socket_path}")
            popup = ["tmux", "-S", socket_path, "display-popup", "-E", "-c", client, "-w", "50%", "-h", "50%", *command]
            control.command("run-shell", "-b", " ".join(map(shlex.quote, popup)))
        else:
            assert tmux_control._popup(control, client, command, "fake", "50%") == {"ok": True, "data": {"client": client}, "error": None}
        deadline = time.monotonic() + 10
        mode = ""
        while time.monotonic() < deadline:
            mode = _tmux(name, "display-message", "-p", "-t", "work", "#{pane_mode}")
            recorded = _tmux(name, "show-options", "-gqv", "@project_agent_last_error")
            if mode or recorded:
                break
            time.sleep(0.1)
        time.sleep(1.0)                              # tmux reports a job when it ends
        mode = _tmux(name, "display-message", "-p", "-t", "work", "#{pane_mode}")
        recorded = _tmux(name, "show-options", "-gqv", "@project_agent_last_error")
        if bare:
            assert mode == "view-mode" and recorded == ""
        else:
            assert mode == ""
            assert _tmux(name, "capture-pane", "-M", "-p", "-t", "work") == ""
            assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d board-popup failed \(exit 3\)", recorded), recorded
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            os.close(master)
        tmux_test_server.release(name)
