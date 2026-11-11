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


TMUX_INTEGRATION = Path(__file__).resolve().parents[3] / "integrations/tmux"


def _drag_border(master, column, target, row=5):
    """Press the border at 0-based `column`, move it to `target`, release (what the terminal sends tmux)."""
    def send(sequence):
        os.write(master, sequence.encode())
        time.sleep(0.15)
    send(f"\x1b[<0;{column + 1};{row}M")
    step = 1 if target > column else -1
    for x in range(column + step, target + step, step):
        send(f"\x1b[<32;{x + 1};{row}M")
    send(f"\x1b[<0;{target + 1};{row}m")


def _resize_client(name, client, window, columns):
    process, master, _tty = client
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 24, columns, 0, 0))
    os.killpg(process.pid, signal.SIGWINCH)
    for _ in range(100):
        if _tmux(name, "display-message", "-p", "-t", window, "#{window_width}") == str(columns):
            return
        time.sleep(0.05)
    pytest.fail("tmux did not take the new client size")


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_a_width_dragged_with_the_mouse_is_saved_after_the_terminal_was_resized(monkeypatch):
    """BOARD-019: after-resize-pane runs once when a drag starts, so the drag's own width was lost."""
    name = tmux_test_server.claim("board-test")
    clients = []
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-s", "one", "sleep", "60")
        _tmux(name, "new-session", "-d", "-s", "two", "sleep", "60")
        first = _tmux(name, "display-message", "-p", "-t", "one", "#{window_id}")
        second = _tmux(name, "display-message", "-p", "-t", "two", "#{window_id}")
        clients.append(_attached(name, "two"))
        socket_path = _tmux(name, "display-message", "-p", "#{socket_path}")
        _tmux(name, "set-option", "-g", "mouse", "on")
        _tmux(name, "set-option", "-g", "@project_agent_tmux_dir", str(TMUX_INTEGRATION))
        _tmux(name, "run-shell", f"{TMUX_INTEGRATION}/project_agent_bind.sh --socket {socket_path}")
        monkeypatch.setattr(tmux_control, "_sidebar_command", lambda _config: ["sleep", "60"])
        assert tmux_control.toggle_sidebar(socket=socket_path)["ok"] is True
        board = _tmux(name, "show-options", "-wqv", "-t", second, "@project_board_pane")
        # The Board pane keeps its marks the way tmux_control makes them; the hook reads the mark.
        saved = lambda: _tmux(name, "show-options", "-gqv", "@project_board_width")  # noqa: E731
        width = lambda window, pane: _pane_geometry(name, window)[pane][0]  # noqa: E731

        # (a) a drag of the Board's border
        start = width(second, board)
        assert saved() == str(start)
        _drag_border(clients[0][1], start, start + 12)
        assert width(second, board) == start + 12
        assert saved() == str(start + 12)

        # (b) the terminal gets narrower and wider again, then the border is dragged again
        _resize_client(name, clients[0], second, 50)
        _resize_client(name, clients[0], second, 80)
        assert saved() == str(start + 12), "a terminal resize is not a width the user chose"
        current = width(second, board)
        _drag_border(clients[0][1], current, 33)
        assert width(second, board) == 33
        assert saved() == "33"

        # (c) the saved width is the width of the Board in another window
        _tmux(name, "switch-client", "-c", clients[0][2], "-t", "one")
        assert tmux_control.reconcile(socket=socket_path)["ok"] is True
        other = _tmux(name, "show-options", "-wqv", "-t", first, "@project_board_pane")
        assert width(first, other) == 33
        assert saved() == "33"
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


def _managed(name, window, project, target):
    """What agent-session writes on a managed window: JSON values in `@agent_session_*` options."""
    _tmux(name, "set-option", "-w", "-t", window, "@agent_session_project_id", json.dumps(project))
    _tmux(name, "set-option", "-w", "-t", window, "@agent_session_target", json.dumps(target))


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_active_context_reads_the_managed_project_and_slot_of_the_pane_window(monkeypatch):
    name = tmux_test_server.claim("board-test")
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-s", "Falcon2", "sleep", "60")
        socket_path = _tmux(name, "display-message", "-p", "#{socket_path}")
        cases = {"leader": ("Falcon2", "leader"), "seat": ("Falcon2", "seat-2"), "other": ("ProjectB", "seat-10"),
                 "odd": ("Falcon2", "worker"), "nobody": None}
        panes = {}
        for label, managed in cases.items():
            _tmux(name, "new-window", "-d", "-t", "Falcon2", "-n", label, "sleep", "60")
            panes[label] = _tmux(name, "display-message", "-p", "-t", f"Falcon2:{label}", "#{pane_id}")
            if managed:
                _managed(name, f"Falcon2:{label}", *managed)
        expected = {"leader": {"project_id": "Falcon2", "slot": "leader"},
                    "seat": {"project_id": "Falcon2", "slot": "seat-2"},
                    "other": {"project_id": "ProjectB", "slot": "seat-10"},
                    "odd": {"project_id": "Falcon2", "slot": None},
                    "nobody": None}
        for label, want in expected.items():
            monkeypatch.setenv("TMUX_PANE", panes[label])
            assert tmux_control.active_context(socket_path) == want, label
        monkeypatch.delenv("TMUX_PANE")
        assert tmux_control.active_context(socket_path) is None          # outside tmux
        # A value that is not JSON is not a managed window.
        _tmux(name, "set-option", "-w", "-t", "Falcon2:nobody", "@agent_session_project_id", "Falcon2")
        monkeypatch.setenv("TMUX_PANE", panes["nobody"])
        assert tmux_control.active_context(socket_path) is None
    finally:
        tmux_test_server.release(name)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_the_sidebar_highlight_follows_a_client_between_managed_and_plain_windows(tmp_path, monkeypatch):
    """The sidebar of each window marks its own window; the client sees the pane of the window it shows."""
    import asyncio
    from board_testing import leader, wait_until
    from project_board import model
    from project_board.tui import SidebarApp

    board = Board(tmp_path)
    base = board.project("Falcon2", seats=3)
    board.state(base, {"leader": leader(),
                       **{str(n): {"job_id": None, "git_hash": None, "session": None} for n in range(3)}})
    other = board.project("ProjectB", seats=1)
    board.state(other, {"leader": None, "0": {"job_id": None, "git_hash": None, "session": None}})
    name = tmux_test_server.claim("board-test")
    clients = []
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-s", "Falcon2", "-n", "leader", "sleep", "60")
        socket_path = _tmux(name, "display-message", "-p", "#{socket_path}")
        for label in ("seat", "plain"):
            _tmux(name, "new-window", "-d", "-t", "Falcon2", "-n", label, "sleep", "60")
        panes = {n: _tmux(name, "display-message", "-p", "-t", f"Falcon2:{n}", "#{pane_id}")
                 for n in ("leader", "seat", "plain")}
        _managed(name, "Falcon2:leader", "Falcon2", "leader")
        _managed(name, "Falcon2:seat", "Falcon2", "seat-1")
        clients.append(_attached(name, "Falcon2"))

        def marks(pane):
            monkeypatch.setenv("TMUX_PANE", pane)
            app = SidebarApp(str(board.config), poll=False,
                             context_reader=lambda: tmux_control.active_context(socket_path))
            found = {}

            async def check():
                async with app.run_test(size=(40, 25)) as pilot:
                    await app.apply_snapshot(model.snapshot(board.config))
                    await app.refresh_context()
                    await wait_until(pilot, lambda: app.query("#project-0-seats"))
                    await pilot.pause()
                    await pilot.click("#project-0-seats")
                    await wait_until(pilot, lambda: app.query("#project-0-seat-1"))
                    found["names"] = [str(b.label) for b in app.query(".project-name")]
                    found["slots"] = [w.has_class("slot-active") for w in app.query(".leader")] + \
                                     [b.has_class("slot-active") for b in app.query("#project-0-seat-0, #project-0-seat-1")]

            asyncio.run(check())
            return found

        want = {"leader": (["▶ Falcon2", "ProjectB"], [True, False, False]),
                "seat": (["▶ Falcon2", "ProjectB"], [False, False, True]),
                "plain": (["Falcon2", "ProjectB"], [False, False, False])}
        for window in ("leader", "seat", "plain", "leader"):
            _tmux(name, "select-window", "-t", f"Falcon2:{window}")
            # The Board pane the client sees is the one of the window it shows (the BOARD-002 check).
            shown = []
            for label, pane in panes.items():
                monkeypatch.setenv("TMUX_PANE", pane)
                if tmux_control.board_visible(socket_path):
                    shown.append(label)
            assert shown == [window]
            names, slots = want[window]
            result = marks(panes[window])
            assert (result["names"], result["slots"]) == (names, slots), window
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
def test_a_failing_board_window_never_covers_the_work_pane_and_the_client_is_told(bare):
    """BOARD-011, BOARD-020: `new-pane -W` ends with the exit status of its command, as `display-popup -E` did.
    As a bare `run-shell` job a failure opened view mode in the active pane (`bare`, the check that the test
    can see it); the Board's own window records the failure and shows it on the client that opened it."""
    name = tmux_test_server.claim("board-popup")
    process = master = None
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-s", "work", "sleep", "60")
        process, master, client = _attached(name, "work")
        control = Tmux(socket_name=name)
        command = ["sh", "-c", "echo noisy; echo noisy >&2; exit 3"]
        if bare:
            socket_path = _tmux(name, "display-message", "-p", "#{socket_path}")
            job = ["tmux", "-S", socket_path, "new-pane", "-W", "-t", "work", *command]
            control.command("run-shell", "-b", " ".join(map(shlex.quote, job)))
        else:
            result = tmux_control._popup(control, client, command, "fake", "50%")
            assert result["ok"] is True and result["data"]["client"] == client
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


FAKE_BOARD = """#!/bin/sh
# Stands for the Board TUI of a CR or decision window: records how it was started, ends when told to.
here=$(dirname "$0")
printf '%s\\n' "$PROJECT_BOARD_CLIENT" "$@" > "$here/started"
read answer
exit "${answer:-0}"
"""


class _Floating:
    """A test server with one attached client and a stand-in Board TUI for the CR and decision windows."""

    def __init__(self, tmp_path, monkeypatch, windows=1):
        self.tmp_path = tmp_path
        self.name = tmux_test_server.claim("board-float")
        self.clients = []
        launcher = tmp_path / "fake-board"
        launcher.write_text(FAKE_BOARD)
        launcher.chmod(0o755)
        monkeypatch.setattr(tmux_control, "LAUNCHER", launcher)
        monkeypatch.setattr(tmux_control, "_sidebar_command", lambda _config: ["sleep", "60"])
        _tmux(self.name, "-f", "/dev/null", "new-session", "-d", "-s", "work", "cat")
        for _ in range(windows - 1):
            _tmux(self.name, "new-window", "-d", "-t", "work", "cat")
        _tmux(self.name, "set-option", "-g", "mouse", "on")
        self.clients.append(_attached(self.name, "work"))
        self.master, self.client = self.clients[0][1], self.clients[0][2]
        self.socket = _tmux(self.name, "display-message", "-p", "#{socket_path}")
        self.window = _tmux(self.name, "display-message", "-p", "-t", "work", "#{window_id}")
        self.work = _tmux(self.name, "display-message", "-p", "-t", self.window, "#{pane_id}")

    def close(self):
        _release_clients(self.clients)
        tmux_test_server.release(self.name)

    def tmux(self, *args):
        return _tmux(self.name, *args)

    def floating(self, window=None):
        """The floating panes of a window: id -> (left, top, width, height)."""
        rows = self.tmux("list-panes", "-t", window or self.window, "-F",
                         "#{pane_id}\t#{pane_floating_flag}\t#{pane_left}\t#{pane_top}\t#{pane_width}\t#{pane_height}")
        found = {}
        for row in rows.splitlines():
            pane, flag, *geometry = row.split("\t")
            if flag == "1":
                found[pane] = tuple(map(int, geometry))
        return found

    def open(self, kind="cr", project="Falcon2"):
        if kind == "cr":
            return tmux_control.open_cr_popup(None, project, "open", self.client, self.socket)
        return tmux_control.open_popup(None, project, "D-1", self.client, self.socket)

    def started(self):
        deadline = time.monotonic() + 5
        path = self.tmp_path / "started"
        while time.monotonic() < deadline:
            if path.exists() and path.read_text().endswith("\n"):
                return path.read_text().split("\n")[:-1]
            time.sleep(0.05)
        pytest.fail("the Board window did not start")

    def mouse(self, button, x, y, up=False):
        """One SGR mouse event on the client, 1-based cell as tmux counts."""
        os.write(self.master, f"\033[<{button};{x};{y}{'m' if up else 'M'}".encode())
        time.sleep(0.15)

    def drag(self, start, end, button=0):
        (x0, y0), (x1, y1) = start, end
        self.mouse(button, x0, y0)
        self.mouse(button + 32, (x0 + x1) // 2, (y0 + y1) // 2)
        self.mouse(button + 32, x1, y1)
        self.mouse(button, x1, y1, up=True)

    def wait_gone(self, pane, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pane not in self.tmux("list-panes", "-a", "-F", "#{pane_id}").split():
                return True
            time.sleep(0.05)
        return False


@pytest.fixture
def floating(tmp_path, monkeypatch):
    made = []

    def make(windows=1):
        made.append(_Floating(tmp_path, monkeypatch, windows))
        return made[-1]
    yield make
    for server in made:
        server.close()


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_a_cr_or_decision_window_opens_as_a_floating_pane_of_the_clicking_clients_window(floating):
    """BOARD-020 contract 1: where, how large, what runs in it. Decision 90%, CR 80%, centred, as the popup was."""
    server = floating(windows=2)
    server.tmux("select-window", "-t", "work:1")
    shown = server.tmux("display-message", "-p", "-t", "work:1", "#{window_id}")
    other = server.tmux("display-message", "-p", "-t", "work:0", "#{window_id}")
    assert tmux_control.open_cr_popup(None, "Falcon2", "todo", server.client, server.socket)["ok"] is True
    client, *arguments = server.started()
    assert client == server.client and arguments == ["cr", "--project", "Falcon2", "--state", "todo"]
    assert server.floating(other) == {}
    ((pane, geometry),) = server.floating(shown).items()
    window_width, window_height = map(int, server.tmux("display-message", "-p", "-t", shown,
                                                       "#{window_width} #{window_height}").split())
    left, top, width, height = geometry
    # 80% of the window includes the border; the margin is the rest, halved
    assert (width + 2, height + 2) == (window_width * 80 // 100, window_height * 80 // 100)
    assert abs(left - 1 - (window_width - width - 2) // 2) <= 1 and abs(top - 1 - (window_height - height - 2) // 2) <= 1
    assert server.tmux("show-options", "-pqv", "-t", pane, tmux_control.PANE_WINDOW) == "1"
    assert server.tmux("display-message", "-p", "-t", pane, "#{pane_title}") == "CR · Falcon2"

    server.tmux("send-keys", "-t", pane, "Enter")
    assert server.wait_gone(pane)
    (server.tmp_path / "started").unlink()
    assert tmux_control.open_popup(None, "Falcon2", "D-1", server.client, server.socket)["ok"] is True
    client, *arguments = server.started()
    assert arguments == ["popup", "--project", "Falcon2", "--decision", "D-1"]
    ((pane, (_, _, width, height)),) = server.floating(shown).items()
    assert (width + 2, height + 2) == (window_width * 90 // 100, window_height * 90 // 100)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_the_board_window_is_moved_and_resized_with_the_mouse_by_tmux_defaults(floating):
    """BOARD-020 contract 2: dragging the top border moves it, dragging another border resizes it, Alt-drag moves
    it. These are tmux 3.8's own root bindings; the Board adds no binding, so no other pane's mouse changes."""
    server = floating()
    before_keys = server.tmux("list-keys", "-T", "root")
    assert server.open()["ok"] is True
    ((pane, (left, top, width, height)),) = server.floating().items()
    assert server.tmux("list-keys", "-T", "root") == before_keys

    server.drag((left + 5, top), (left + 11, top + 2))               # the top border: the cell above the pane
    assert server.floating()[pane] == (left + 6, top + 2, width, height)
    left, top = left + 6, top + 2
    server.drag((left + width + 1, top + height + 1), (left + width - 5, top + height - 2))   # the corner
    assert server.floating()[pane] == (left, top, width - 6, height - 3)
    width, height = width - 6, height - 3
    server.drag((left + 4, top + 3), (left + 6, top + 4), button=8)  # Alt held
    assert server.floating()[pane] == (left + 2, top + 1, width, height)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_while_the_board_window_is_open_the_pane_behind_it_takes_input_and_the_sidebar_stays(floating):
    """BOARD-020 contract 3: a popup took every key of its client. The window stays on top when the pane behind
    it is selected, the pane behind gets what the client types, and the sidebar is not disturbed."""
    server = floating()
    assert tmux_control.toggle_sidebar(socket=server.socket, client=server.client)["ok"] is True
    sidebar = server.tmux("show-options", "-wqv", "-t", server.window, tmux_control.WINDOW_PANE)
    width = server.tmux("show-options", "-gqv", tmux_control.WIDTH)
    assert server.open()["ok"] is True
    ((pane, _),) = server.floating().items()
    assert server.tmux("display-message", "-p", "-t", pane, "#{pane_active}") == "1"

    ((_, (left, _, window_width, _)),) = server.floating().items()
    column = left + window_width + 3                                        # right of the window: the pane behind, not the sidebar
    assert column <= 80
    server.mouse(0, column, 12)
    server.mouse(0, column, 12, up=True)
    assert server.tmux("display-message", "-p", "-t", server.work, "#{pane_active}") == "1"
    assert pane in server.floating() and server.tmux("display-message", "-p", "-t", pane, "#{pane_z}") == "0"
    os.write(server.master, b"typed behind\r")                       # what a person types to the pane behind
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and "typed behind" not in server.tmux("capture-pane", "-p", "-t", server.work):
        time.sleep(0.05)
    assert "typed behind" in server.tmux("capture-pane", "-p", "-t", server.work)
    assert "typed behind" not in server.tmux("capture-pane", "-p", "-t", pane)
    assert server.tmux("show-options", "-wqv", "-t", server.window, tmux_control.WINDOW_PANE) == sidebar
    assert server.tmux("show-options", "-pqv", "-t", sidebar, tmux_control.PANE_MARK) == "1"
    assert server.tmux("show-options", "-gqv", tmux_control.WIDTH) == width


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_a_click_on_the_sidebar_reaches_the_board_while_its_window_is_open(floating, request):
    """BOARD-020 contract 3: the click binding of the integration sends a click on the sidebar to the Board, with
    the clicking client and the cell, whatever floating pane is open; a click on the Board window is not one."""
    server = floating()
    server.tmux("source-file", str(Path(__file__).resolve().parents[3] / "integrations/tmux/project-agent.conf"))
    assert tmux_control.toggle_sidebar(socket=server.socket, client=server.client)["ok"] is True
    sidebar = server.tmux("show-options", "-wqv", "-t", server.window, tmux_control.WINDOW_PANE)
    click_path = Path(server.tmux("show-options", "-pqv", "-t", sidebar, tmux_control.PANE_SOCKET))
    received = []

    def serve():
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(str(click_path))
            os.chmod(click_path, 0o600)
            listener.settimeout(15)
            listener.listen(2)
            while True:
                try:
                    connection, _ = listener.accept()
                except OSError:
                    return
                with connection:
                    received.append(json.loads(connection.makefile("r").readline()))
                    connection.sendall(b'{"ok":true,"data":null,"error":null}\n')

    threading.Thread(target=serve, daemon=True).start()
    for _ in range(100):
        if click_path.exists():
            break
        time.sleep(0.05)
    assert server.open()["ok"] is True
    ((pane, (left, top, _, _)),) = server.floating().items()
    server.mouse(0, 3, 4)
    server.mouse(0, 3, 4, up=True)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not received:
        time.sleep(0.1)
    assert received == [{"client": server.client, "x": 2, "y": 3}]
    assert server.tmux("display-message", "-p", "-t", pane, "#{pane_active}") == "1"      # the click did not move focus
    server.mouse(0, left + 3, top + 3)                               # inside the Board window: no click for the sidebar
    server.mouse(0, left + 3, top + 3, up=True)
    time.sleep(1.0)
    assert len(received) == 1


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_another_item_reuses_the_window_with_its_place_and_size(floating):
    """BOARD-020 contract 4: one Board window per window; another click shows the new content in it."""
    server = floating()
    assert server.open("cr")["ok"] is True
    server.started()
    ((pane, (left, top, width, height)),) = server.floating().items()
    server.drag((left + 5, top), (left + 9, top + 3))
    server.drag((left + width + 1, top + height + 1), (left + width - 9, top + height - 3))
    placed = server.floating()[pane]
    (tmp := server.tmp_path / "started").unlink()

    result = server.open("decision")
    assert result["ok"] is True and result["data"]["pane"] == pane
    client, *arguments = server.started()
    assert arguments[:2] == ["popup", "--project"] and client == server.client
    assert server.floating() == {pane: placed}
    assert server.tmux("display-message", "-p", "-t", pane, "#{pane_title}") == "Decision · Falcon2"
    time.sleep(1.0)
    assert server.tmux("show-options", "-gqv", "@project_agent_last_error") == ""   # replacing it is not a failure
    server.tmux("send-keys", "-t", pane, "Enter")
    assert server.wait_gone(pane)
    assert server.tmux("show-options", "-gqv", "@project_agent_last_error") == ""


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_two_clicks_at_once_open_one_window(floating):
    """BOARD-020 contract 4: a window marks itself after it starts, so a second click must wait for the mark."""
    server = floating()
    results = []
    threads = [threading.Thread(target=lambda: results.append(server.open())) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert [result["ok"] for result in results] == [True] * 3
    assert len(server.floating()) == 1


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_closing_the_board_window_closes_only_that_pane_even_in_a_window_that_keeps_dead_panes(floating):
    """BOARD-020 contract 5: agent-session's windows have `remain-on-exit on`; the closed Board window must not stay
    as a dead pane. The sidebar, its width and the managed-pane option are what they were."""
    server = floating()
    server.tmux("source-file", str(Path(__file__).resolve().parents[3] / "integrations/tmux/project-agent.conf"))
    server.tmux("set-option", "-w", "-t", server.window, "remain-on-exit", "on")
    server.tmux("set-option", "-w", "-t", server.window, tmux_control.PANE_ID_OPTION, json.dumps(server.work))
    assert tmux_control.toggle_sidebar(socket=server.socket, client=server.client)["ok"] is True
    before = (server.tmux("show-options", "-wqv", "-t", server.window, tmux_control.WINDOW_PANE),
              server.tmux("show-options", "-gqv", tmux_control.WIDTH),
              server.tmux("show-options", "-wqv", "-t", server.window, tmux_control.PANE_ID_OPTION))
    panes = set(server.tmux("list-panes", "-t", server.window, "-F", "#{pane_id}").split())
    assert server.open()["ok"] is True
    ((pane, (_, _, width, height)),) = server.floating().items()
    server.tmux("resize-pane", "-t", pane, "-x", str(width - 7))     # resizing it is not resizing the sidebar
    time.sleep(0.5)
    assert server.tmux("show-options", "-gqv", tmux_control.WIDTH) == before[1]

    server.tmux("send-keys", "-t", pane, "Enter")
    assert server.wait_gone(pane)
    assert set(server.tmux("list-panes", "-t", server.window, "-F", "#{pane_id}").split()) == panes
    assert (server.tmux("show-options", "-wqv", "-t", server.window, tmux_control.WINDOW_PANE),
            server.tmux("show-options", "-gqv", tmux_control.WIDTH),
            server.tmux("show-options", "-wqv", "-t", server.window, tmux_control.PANE_ID_OPTION)) == before
    assert server.tmux("show-options", "-gqv", "@project_agent_last_error") == ""

    assert server.open()["ok"] is True                               # closing the window it is in
    server.tmux("new-window", "-d", "-t", "work", "cat")
    server.tmux("kill-window", "-t", server.window)
    time.sleep(0.5)
    assert server.tmux("show-options", "-gqv", tmux_control.WIDTH) == before[1]
    assert server.tmux("show-options", "-gqv", "@project_agent_last_error") == ""


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
@pytest.mark.parametrize("split", [False, True])
def test_removing_the_sidebar_restores_the_layout_around_an_open_board_window(floating, split):
    """BOARD-020: `select-layout` names every pane of the window, so a saved layout cannot be restored once a
    floating pane came or went. The tiled panes get their layout back and the Board window stays where it was."""
    server = floating()
    if split:
        server.tmux("split-window", "-d", "-h", "-t", server.window, "cat")
    window = server.window
    before = _pane_geometry(server.name, window)
    assert tmux_control.toggle_sidebar(socket=server.socket, client=server.client)["ok"] is True
    assert server.open()["ok"] is True
    ((pane, placed),) = server.floating().items()

    result = tmux_control.toggle_sidebar(socket=server.socket, client=server.client)
    assert result["ok"] is True, result["error"]["details"]["failures"]
    assert server.floating() == {pane: placed}
    after = _pane_geometry(server.name, window)
    # the Board window keeps the focus it had; where the tiled panes are is what is compared
    assert {key: value[:4] for key, value in after.items() if key != pane} == {key: value[:4] for key, value in before.items()}


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_a_board_window_that_cannot_be_opened_is_reported_to_the_caller(floating):
    server = floating()
    result = tmux_control.open_cr_popup(None, "Falcon2", "open", "/dev/pts/9999", server.socket)
    assert result["ok"] is False and result["error"]["code"] == "popup_unavailable"
    assert server.floating() == {}


def _release_clients(clients):
    for process, master, _client in clients:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        os.close(master)


def _counting(monkeypatch):
    """The argument vectors of the tmux processes the product starts from now on (the test's own are not counted)."""
    calls = []
    original = subprocess.run

    def counted(argv, *args, **kwargs):
        if argv and argv[0] == "tmux":
            calls.append(list(argv))
        return original(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", counted)
    return calls


def _tmux_processes_of_sync_and_toggle(monkeypatch, extra_windows):
    """The tmux processes `toggle` (on, off) and `sync` (a window to fill, nothing to change) start on a server
    with 2 + 2 * extra_windows windows, one client and no Board pane, with the Board panes they make."""
    name = tmux_test_server.claim("board-test")
    clients = []
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-s", "one", "sleep", "60")
        _tmux(name, "new-window", "-d", "-t", "one", "sleep", "60")
        for number in range(extra_windows):
            _tmux(name, "new-session", "-d", "-s", f"s{number}", "sleep", "60")
            _tmux(name, "new-window", "-d", "-t", f"s{number}", "sleep", "60")
        clients.append(_attached(name, "one"))
        socket_path = _tmux(name, "display-message", "-p", "#{socket_path}")
        monkeypatch.setattr(tmux_control, "_sidebar_command", lambda _config: ["sleep", "60"])
        calls = _counting(monkeypatch)
        counts, made = {}, {}

        def measure(label, action):
            del calls[:]
            result = action()
            assert result["ok"] is True, result
            counts[label] = len(calls)
            made[label] = (len(result["data"]["created"]), len(result["data"]["removed"]))

        measure("toggle_on", lambda: tmux_control.toggle_sidebar(socket=socket_path))
        _tmux(name, "switch-client", "-c", clients[0][2], "-t", "one:1")
        measure("sync_create", lambda: tmux_control.reconcile(socket=socket_path))
        measure("sync_nochange", lambda: tmux_control.reconcile(socket=socket_path))
        measure("toggle_off", lambda: tmux_control.toggle_sidebar(socket=socket_path))
        assert made == {"toggle_on": (1, 0), "sync_create": (1, 0), "sync_nochange": (0, 0), "toggle_off": (0, 2)}
        return counts
    finally:
        _release_clients(clients)
        tmux_test_server.release(name)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_sync_and_toggle_start_the_same_tmux_processes_for_any_number_of_windows(monkeypatch):
    """BOARD-012: the reads of `sync` and `toggle` do not grow with the windows of the server.

    The panes made or removed (one or two here, the clients' windows) account for the writes and for the
    layout reads that go with them; every other process is one read of the whole server."""
    small = _tmux_processes_of_sync_and_toggle(monkeypatch, 0)
    large = _tmux_processes_of_sync_and_toggle(monkeypatch, 24)
    assert large == small, (small, large)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_the_snapshot_reads_what_the_per_window_options_hold(monkeypatch):
    """BOARD-012: one format read gives the values `show-options` gave for each window and pane."""
    name = tmux_test_server.claim("board-test")
    clients = []
    try:
        _tmux(name, "-f", "/dev/null", "new-session", "-d", "-s", "one", "sleep", "60")
        _tmux(name, "new-session", "-d", "-s", "two", "sleep", "60")
        _tmux(name, "new-window", "-d", "-t", "two", "sleep", "60")
        clients.append(_attached(name, "one"))
        _tmux(name, "set-option", "-g", "remain-on-exit", "on")
        dead = _tmux(name, "split-window", "-d", "-P", "-F", "#{pane_id}", "-t", "two:0", "true")
        for _ in range(100):
            if _tmux(name, "display-message", "-p", "-t", dead, "#{pane_dead}") == "1":
                break
            time.sleep(0.05)
        socket_path = _tmux(name, "display-message", "-p", "#{socket_path}")
        monkeypatch.setattr(tmux_control, "_sidebar_command", lambda _config: ["sleep", "60"])
        assert tmux_control.toggle_sidebar(config=None, socket=socket_path)["ok"] is True
        windows = _tmux(name, "list-windows", "-a", "-F", "#{window_id}").splitlines()
        _tmux(name, "set-option", "-w", "-t", windows[-1], "@project_board_seen", "1234")
        _tmux(name, "set-option", "-w", "-t", "two:0", tmux_control.PANE_ID_OPTION, json.dumps(dead))
        _tmux(name, "set-option", "-g", "@project_board_config", "/tmp/a b/config.json")

        snapshot = tmux_control._snapshot(Tmux(socket_path=socket_path))

        assert snapshot.enabled is True and snapshot.config == "/tmp/a b/config.json"
        assert snapshot.width == _tmux(name, "show-options", "-gqv", "@project_board_width") != ""
        assert snapshot.visible == _tmux(name, "list-clients", "-F", "#{window_id}").splitlines()
        assert list(snapshot.windows) == windows            # tmux's order, the order the panes are judged in
        marked = 0
        for window, record in snapshot.windows.items():
            def option(*flags):
                return _tmux(name, "show-options", "-qv", *flags)
            assert record.board == option("-w", "-t", window, "@project_board_pane")
            assert record.seen == option("-w", "-t", window, "@project_board_seen")
            assert record.managed == option("-w", "-t", window, tmux_control.PANE_ID_OPTION)
            assert record.panes == {
                pane: dead_flag == "1" for pane, dead_flag in
                (row.split("\t") for row in _tmux(name, "list-panes", "-t", window, "-F",
                                                  "#{pane_id}\t#{pane_dead}").splitlines())}
            for pane, mark in record.marks.items():
                assert mark == option("-p", "-t", pane, "@project_board_managed")
                marked += mark == "1"
        assert marked == 1 and snapshot.windows[windows[0]].board
        assert tmux_control._managed_pane_dead(snapshot.windows[_tmux(name, "display-message", "-p", "-t", "two:0", "#{window_id}")])
    finally:
        _release_clients(clients)
        tmux_test_server.release(name)


def test_reading_the_folds_takes_no_lock_and_starts_one_tmux_command(monkeypatch):
    """Every Board pane reads the folds on each refresh (BOARD-013): one `show-options`, no lock (which would add a
    `display-message` and a `ps` per other tmux server)."""
    calls = []

    class Control:
        def command(self, *args):
            calls.append(args)
            return '["one", "two"]'

    def no_lock(control):
        raise AssertionError("reading the folds must not take the lock")
    monkeypatch.setattr(tmux_control, "_control", lambda socket=None: Control())
    monkeypatch.setattr(tmux_control, "_locked", no_lock)
    assert tmux_control.expanded_projects() == {"one", "two"}
    assert len(calls) == 1 and calls[0][0] == "show-options"
