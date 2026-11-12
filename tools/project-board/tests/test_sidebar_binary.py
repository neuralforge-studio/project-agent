"""The sidebar binary (`project-board-sidebar`) in a tmux pane: what it shows, and what its clicks, keys and signals do.

BOARD-018 replaced the Textual sidebar with this binary; these tests hold the behaviour of the Textual sidebar
(tests of 0.7.1) at the process boundary. The screen itself is checked by the golden screens of the Rust unit
tests (`rust/src/golden.rs`), which were drawn by the Textual sidebar.
"""
import json
import os
import shutil
import signal
import socket as unix_socket
import threading
import stat
import subprocess
import time
from pathlib import Path

import pytest

import board_testing  # noqa: F401  (adds the Board tool to sys.path)
import tmux_test_server
from wait_limit import command_timeout
from board_testing import Board, attached, click_socket, leader, release_clients, session, tmux
from rust_binary import sidebar_binary

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
LAUNCHER = Path(board_testing.TOOL) / "bin" / "project-board"


def _wait(condition, what="the screen"):
    deadline = time.monotonic() + command_timeout()
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


class Pane:
    """The sidebar running as the only pane of the window a client shows."""

    def __init__(self, tmp_path, request, board, size=(25, 30), launcher=None, attach=True, env=None, path=None, binary=None):
        self.name = tmux_test_server.claim("sidebar-test")
        request.addfinalizer(self.close)
        self.clients = []
        self.click = click_socket(request)
        self.log = tmp_path / "helper.log"
        self.launcher = launcher
        if launcher == "fake":
            self.launcher = tmp_path / "project-board"
            self.launcher.write_text(f'#!/bin/sh\necho "$@" >> {self.log}\n')
            self.launcher.chmod(0o755)
        self.board = board
        self.crontab = CrontabShim(tmp_path)
        path = self.crontab.directory + os.pathsep + (path or os.environ["PATH"])
        self.size = size
        self.socket_path = socket_path = str(tmux_test_server.socket_path(self.name))
        variables = {"PROJECT_BOARD_SOCKET": socket_path, "AGENT_SESSION_SOCKET": socket_path,
                    "PROJECT_BOARD_CLICK_SOCKET": self.click, "COLORTERM": "truecolor", **(env or {})}
        if self.launcher:
            variables["PROJECT_BOARD_LAUNCHER"] = str(self.launcher)
        command = ["-f", "/dev/null", "new-session", "-d", "-x", str(size[0]), "-y", str(size[1]), "-s", "main"]
        for key, value in variables.items():
            command += ["-e", f"{key}={value}"]
        # tmux ignores `-e PATH=`; a program that needs another PATH is run through env
        command += ["env", f"PATH={path}"] + [str(binary or sidebar_binary()), "--config", str(board.config)]
        tmux(self.name, *command)
        tmux(self.name, "set-option", "-g", "window-size", "manual")
        if attach:
            self.clients.append(attached(self.name, "main"))
            tmux(self.name, "resize-window", "-t", "main", "-x", str(size[0]), "-y", str(size[1]))
        self.pane = tmux(self.name, "display-message", "-p", "-t", "main", "#{pane_id}")
        if attach:
            # the sidebar may ask tmux before the client is attached; project_board_visibility.sh signals it when a
            # client shows its window, so the test does the same
            _wait(lambda: tmux(self.name, "show-options", "-pqv", "-t", self.pane, "@project_board_ready") == "1", what="mark_ready")
            os.kill(int(tmux(self.name, "display-message", "-p", "-t", self.pane, "#{pane_pid}")), signal.SIGUSR1)

    def close(self):
        release_clients(self.clients)
        self.clients = []
        tmux_test_server.release(self.name)

    def _capture(self, *flags):
        # `board_testing.tmux` strips the output, and the first row of the sidebar is empty
        return subprocess.run(["tmux", "-L", self.name, "capture-pane", "-p", *flags, "-t", self.pane],
                              capture_output=True, text=True, check=True, timeout=command_timeout()).stdout

    def screen(self):
        return self._capture()

    def lines(self):
        return [line.rstrip() for line in self.screen().splitlines()]

    def ansi(self):
        return self._capture("-e")

    def wait_text(self, text):
        _wait(lambda: text in self.screen(), f"{text!r} on the screen:\n{self.screen()}")

    def wait_gone(self, text):
        _wait(lambda: text not in self.screen(), f"{text!r} gone from the screen:\n{self.screen()}")

    def send_click(self, x, y, client="/dev/ttys-test"):
        with unix_socket.socket(unix_socket.AF_UNIX, unix_socket.SOCK_STREAM) as connection:
            connection.settimeout(command_timeout())
            connection.connect(self.click)
            connection.sendall(json.dumps({"client": client, "x": x, "y": y}).encode() + b"\n")
            reply = b""
            while b"\n" not in reply:
                block = connection.recv(4096)
                if not block:
                    break
                reply += block
        return json.loads(reply)

    def send_raw(self, payload: bytes):
        with unix_socket.socket(unix_socket.AF_UNIX, unix_socket.SOCK_STREAM) as connection:
            connection.settimeout(command_timeout())
            connection.connect(self.click)
            connection.sendall(payload)
            reply = b""
            while b"\n" not in reply:
                block = connection.recv(4096)
                if not block:
                    break
                reply += block
        return json.loads(reply)

    def keys(self, *keys):
        tmux(self.name, "send-keys", "-t", self.pane, *keys)

    def mouse(self, kind, x, y):
        """An SGR mouse report typed into the pane: 35 is motion, 0 a left button (M down, m up). x and y count from 1."""
        code, final = {"move": (35, "M"), "down": (0, "M"), "up": (0, "m")}[kind]
        tmux(self.name, "send-keys", "-t", self.pane, "-l", f"\x1b[<{code};{x + 1};{y + 1}{final}")

    def helper_calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def folds(self):
        raw = tmux(self.name, "show-options", "-sqv", "@project_board_expanded")
        return set(json.loads(raw)) if raw else set()


class CrontabShim:
    """A `crontab` first on the sidebar's PATH, so that no test reads the real crontab: `crontab -l` prints `text` (no
    crontab for the user while it is None), or fails with `failure`. One line of `calls` is one `crontab` process."""

    def __init__(self, tmp_path):
        self.directory = str(tmp_path / "crontab-shim")
        self.dir = Path(self.directory)
        self.dir.mkdir(exist_ok=True)
        self.calls_path = tmp_path / "crontab-calls.log"
        script = self.dir / "crontab"
        script.write_text(
            "#!/bin/sh\n"
            f'printf "%s\\n" "$*" >> {self.calls_path}\n'
            f'if [ -f {self.dir}/failure ]; then cat {self.dir}/failure >&2; exit 1; fi\n'
            f'if [ -f {self.dir}/text ]; then cat {self.dir}/text; exit 0; fi\n'
            'echo "no crontab for $USER" >&2; exit 1\n')
        script.chmod(0o755)

    def set(self, text=None, failure=None):
        for name, value in (("text", text), ("failure", failure)):
            if value is None:
                (self.dir / name).unlink(missing_ok=True)
            else:
                (self.dir / name).write_text(value, encoding="utf-8")

    def calls(self):
        return self.calls_path.read_text().splitlines() if self.calls_path.exists() else []


def cron_section(project, *jobs):
    """The crontab lines of a project's section: `jobs` are (id, schedule) pairs."""
    lines = [f"# >>> project-agent: {project} >>>"]
    for job_id, schedule in jobs:
        lines += [f"# job {job_id}: {job_id} job", f"{schedule} /bin/true"]
    return "\n".join(lines + [f"# <<< project-agent: {project} <<<", ""])


def _tmux_shim(tmp_path):
    """A `tmux` first on PATH that logs its arguments and runs the real one: one line is one tmux process."""
    directory = tmp_path / "shim"
    directory.mkdir()
    log = tmp_path / "tmux-calls.log"
    shim = directory / "tmux"
    shim.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> {log}\nexec {shutil.which("tmux")} "$@"\n')
    shim.chmod(0o755)
    return str(directory), log


def _board(tmp_path):
    board = Board(tmp_path)
    falcon = board.project("Falcon2", seats=3)
    board.cr(falcon, "open", "CPU-001")
    board.cr(falcon, "open", "CPU-002")
    board.cr(falcon, "todo", "CPU-003")
    board.cr(falcon, "in-progress", "CPU-012")
    board.decide(falcon, "open", "D-20261107-01")
    board.decide(falcon, "open", "D-20261107-02")
    board.state(falcon, {
        "leader": leader(reviewing="CPU-012"),
        "0": {"job_id": "CPU-012", "git_hash": None, "session": session(0)},
        "1": {"job_id": None, "git_hash": None, "session": None},
        "2": {"job_id": None, "git_hash": None, "session": None},
    })
    other = board.project("ProjectB", seats=2)
    board.cr(other, "todo", "GPU-001")
    board.decide(other, "open", "D-20261107-03")
    board.state(other, {"leader": None, "0": {"job_id": None, "git_hash": None, "session": None},
                        "1": {"job_id": None, "git_hash": None, "session": None}})
    return board


def test_it_shows_every_project_with_its_counts_and_folds_seats_until_expanded(tmp_path, request):
    pane = Pane(tmp_path, request, _board(tmp_path))
    pane.wait_text("ProjectB")
    pane.wait_text("C:0")                # the crontab is read after the first drawing (no crontab: no jobs)
    lines = pane.lines()
    assert lines[1].startswith("Falcon2 ") and lines[1].endswith("m")           # the Leader's time (BOARD-023)
    assert lines[:1] + lines[2:9] == ["", " D:2   C:0", " O:2   T:1   I:1   ▸", "", "ProjectB", " D:1   C:0", " O:0   T:1   I:0   ▸", ""]
    tmux(pane.name, "set-option", "-s", "@project_board_expanded", json.dumps(["Falcon2"]))
    pane.wait_text("R 0 CPU-012")      # the next 2-second read shows the fold the tmux option holds
    lines = pane.lines()
    assert lines[3] == " O:2   T:1   I:1   ▾"
    assert lines[1].startswith("Falcon2 ") and lines[5] == "   1 -" and lines[6] == "   2 -"      # BOARD-023: the time is on the name row
    assert lines[4].startswith(" R 0 CPU-012 ") and "Leader" not in pane.screen()


def test_an_empty_registry_says_there_is_no_project_only_after_the_first_read(tmp_path, request):
    board = Board(tmp_path)
    board.config.write_text("{}", encoding="utf-8")
    pane = Pane(tmp_path, request, board)
    pane.wait_text("등록된 project가")
    assert "없습니다." in pane.screen()


def test_a_registry_error_is_shown_on_the_first_row(tmp_path, request):
    board = Board(tmp_path)
    board.config.write_text("{not json", encoding="utf-8")
    pane = Pane(tmp_path, request, board)
    pane.wait_text("project registry")
    assert pane.lines()[0].startswith("Cannot read a valid")


def test_the_click_socket_answers_with_the_widget_and_runs_the_action_for_the_clicking_client(tmp_path, request):
    pane = Pane(tmp_path, request, _board(tmp_path), launcher="fake")
    tmux(pane.name, "set-option", "-s", "@project_board_expanded", json.dumps(["Falcon2"]))
    pane.wait_text("R 0 CPU-012")
    # rows: 0 error, 1 name, 2 D, 3 counts, 4 seat 0, 5 seat 1 (empty), 6 seat 2 (empty)
    assert pane.send_click(2, 1) == {"ok": True, "data": {"widget": "project-0-name"}, "error": None}
    assert pane.send_click(2, 2)["data"] == {"widget": "project-0-D"}
    assert pane.send_click(2, 3)["data"] == {"widget": "project-0-O"}
    assert pane.send_click(8, 3)["data"] == {"widget": "project-0-T"}
    assert pane.send_click(14, 3)["data"] == {"widget": "project-0-I"}
    assert pane.send_click(5, 4)["data"] == {"widget": "project-0-seat-0"}
    # the CR and decision windows are opened by `project-board` (here a fake) for the clicking client; the switches are
    # done by the sidebar itself (rust/src/switch.rs, compared with tmux_control by test_rust_switch.py): no helper run
    _wait(lambda: len(pane.helper_calls()) == 4, what="the four helper runs")
    time.sleep(0.5)
    client = "/dev/ttys-test"
    assert sorted(pane.helper_calls()) == sorted([
        f"--config {pane.board.config} open-decision --project Falcon2 --client {client}",
        f"--config {pane.board.config} open-cr --project Falcon2 --state open --client {client}",
        f"--config {pane.board.config} open-cr --project Falcon2 --state todo --client {client}",
        f"--config {pane.board.config} open-cr --project Falcon2 --state in-progress --client {client}",
    ])
    # a client that is not attached: the switch fails and the sidebar says why
    pane.wait_text("not attached")


def test_a_click_on_something_that_cannot_act_is_refused_or_ignored_as_before(tmp_path, request):
    pane = Pane(tmp_path, request, _board(tmp_path), launcher="fake")
    tmux(pane.name, "set-option", "-s", "@project_board_expanded", json.dumps(["Falcon2"]))
    pane.wait_text("R 0 CPU-012")
    # ProjectB's O has no CR (disabled): ignored with ok; the blank margin row and the first row are not buttons
    other = [n for n, line in enumerate(pane.lines()) if line == "ProjectB"][0]
    assert pane.send_click(2, other + 2)["data"] == {"widget": "project-1-O"}
    assert pane.send_click(2, 7)["error"]["code"] == "not_clickable"      # the margin row
    assert pane.send_click(2, 0)["error"]["code"] == "not_clickable"      # the error row
    assert pane.send_click(5, 5)["data"] == {"widget": "project-0-seat-1"}   # an empty seat: ignored
    assert pane.send_click(40, 2)["error"]["code"] == "no_widget"
    assert pane.send_click(2, 99)["error"]["code"] == "no_widget"
    time.sleep(0.3)
    assert pane.helper_calls() == []


def test_a_malformed_click_message_is_rejected_and_the_sidebar_keeps_running(tmp_path, request):
    pane = Pane(tmp_path, request, _board(tmp_path), launcher="fake")
    pane.wait_text("Falcon2")
    for payload in (b"not json\n", b'{"x": 1, "y": 1}\n', b'{"client": "c", "x": -1, "y": 0}\n',
                    b'{"client": "c", "x": 1.5, "y": 0}\n', b'{"client": "c", "x": "1", "y": 0}\n',
                    b'{"client": "", "x": 1, "y": 0}\n', b'{"client": "c", "x": true, "y": 0}\n', b"[]\n"):
        reply = pane.send_raw(payload)
        assert reply["ok"] is False and reply["error"]["code"] == "invalid_click", payload
    assert pane.send_raw(b'{"client": "c", "x": 2, "y": 1}\n')["data"] == {"widget": "project-0-name"}
    big = b'{"client": "' + b"c" * 5000 + b'", "x": 1, "y": 1}\n'
    assert pane.send_raw(big)["error"]["message"] == "click message too large"


def test_the_click_socket_is_private_and_removed_when_the_sidebar_ends(tmp_path, request):
    pane = Pane(tmp_path, request, _board(tmp_path))
    pane.wait_text("Falcon2")
    info = os.lstat(pane.click)
    assert stat.S_ISSOCK(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
    process_id = int(tmux(pane.name, "display-message", "-p", "-t", pane.pane, "#{pane_pid}"))
    os.kill(process_id, signal.SIGTERM)
    _wait(lambda: not os.path.lexists(pane.click), what="the socket removed")


def test_a_click_socket_path_that_is_in_use_is_reported_on_the_first_row(tmp_path, request):
    board = _board(tmp_path)
    path = click_socket(request)
    Path(path).write_text("taken")
    name = tmux_test_server.claim("sidebar-test")
    request.addfinalizer(lambda: tmux_test_server.release(name))
    tmux(name, "-f", "/dev/null", "new-session", "-d", "-x", "40", "-y", "10", "-s", "main",
         "-e", f"PROJECT_BOARD_CLICK_SOCKET={path}", str(sidebar_binary()), "--config", str(board.config))
    _wait(lambda: "클릭 socket" in tmux(name, "capture-pane", "-p", "-t", "main"), what="the error row")
    assert Path(path).read_text() == "taken"


def test_folding_shows_at_once_and_is_kept_in_the_shared_tmux_option(tmp_path, request):
    pane = Pane(tmp_path, request, _board(tmp_path), launcher=LAUNCHER)
    pane.wait_text("ProjectB")
    assert pane.send_click(19, 3)["data"] == {"widget": "project-0-seats"}
    pane.wait_text("R 0 CPU-012")
    _wait(lambda: pane.folds() == {"Falcon2"}, what="the shared option")  # a Python process starts under the load of the host
    assert pane.send_click(19, 3)["data"] == {"widget": "project-0-seats"}
    pane.wait_gone("R 0 CPU-012")
    _wait(lambda: pane.folds() == set(), what="the shared option cleared")


def test_a_fold_another_pane_wrote_reaches_this_one_at_the_next_read(tmp_path, request):
    pane = Pane(tmp_path, request, _board(tmp_path))
    pane.wait_text("ProjectB")
    tmux(pane.name, "set-option", "-s", "@project_board_expanded", json.dumps(["ProjectB"]))
    pane.wait_text("   0 -")
    assert "R 0 CPU-012" not in pane.screen()


def test_tab_enter_and_the_arrows_work_from_the_keyboard(tmp_path, request):
    pane = Pane(tmp_path, request, _board(tmp_path), size=(25, 7), launcher="fake")
    tmux(pane.name, "set-option", "-s", "@project_board_expanded", json.dumps(["Falcon2"]))
    pane.wait_text("R 0 CPU-012")
    assert pane.lines()[0] == "" and "ProjectB" not in pane.screen()       # 7 rows hold the first project only
    pane.keys("Tab")                    # name of Falcon2 (not visibly marked), Tab again: D
    pane.keys("Tab", "Enter")
    _wait(lambda: pane.helper_calls(), what="the helper run")
    assert pane.helper_calls() == [f"--config {pane.board.config} open-decision --project Falcon2"]
    pane.keys("Down", "Down", "Down")
    pane.wait_text("ProjectB") if "ProjectB" in pane.screen() else None
    pane.keys("PageDown")
    _wait(lambda: "ProjectB" in pane.screen(), what="the second project after scrolling")
    pane.keys("Home")
    _wait(lambda: pane.lines()[1].startswith("Falcon2"), what="the top again")


def test_the_pointer_shows_the_hover_background_and_a_tooltip_that_goes_away(tmp_path, request):
    pane = Pane(tmp_path, request, _board(tmp_path))
    pane.wait_text("Falcon2")
    pane.mouse("move", 3, 2)            # the D row of Falcon2
    _wait(lambda: "48;2;52;80;109" in pane.ansi().splitlines()[2].replace(":", ";"), what="the hover background")
    _wait(lambda: "결정 대기 2" in pane.screen(), what="the tooltip")
    pane.mouse("move", 3, 8)            # another widget: the tooltip goes at once
    pane.wait_gone("결정 대기 2")


def test_a_sidebar_nobody_watches_reads_nothing_until_it_is_shown_again(tmp_path, request):
    board = _board(tmp_path)
    pane = Pane(tmp_path, request, board)
    pane.wait_text("Falcon2")
    _wait(lambda: tmux(pane.name, "show-options", "-pqv", "-t", pane.pane, "@project_board_ready") == "1", what="mark_ready")
    # a second window that the client moves to hides the sidebar's window
    tmux(pane.name, "new-window", "-d", "-n", "other", "sleep", "300")
    tmux(pane.name, "select-window", "-t", "main:other")
    process_id = int(tmux(pane.name, "display-message", "-p", "-t", pane.pane, "#{pane_pid}"))
    os.kill(process_id, signal.SIGUSR1)           # what project_board_visibility.sh does
    time.sleep(0.5)
    board.cr(Path(board.registry and next(iter(board.registry))), "todo", "CPU-099")
    time.sleep(3.0)                               # more than one read interval
    assert " T:1 " in pane.screen() and " T:2 " not in pane.screen()
    hidden = len(pane.crontab.calls())
    time.sleep(11.0)                              # more than one 10-second read interval: the crontab is not read either
    assert len(pane.crontab.calls()) == hidden
    tmux(pane.name, "select-window", "-t", "main:0")
    os.kill(process_id, signal.SIGUSR1)
    pane.wait_text("T:2")              # SIGUSR1 makes the pane read the crontab; the wait asserts the result, not a time


def test_the_window_of_the_pane_is_marked_with_its_project_and_slot(tmp_path, request):
    board = _board(tmp_path)
    pane = Pane(tmp_path, request, board)
    pane.wait_text("Falcon2")
    assert "▶" not in pane.screen()
    before = [line for line in pane.ansi().splitlines() if "Falcon2" in line][0]
    assert "48;2;47;109;179" not in before.replace(":", ";")
    tmux(pane.name, "set-option", "-w", "-t", "main:0", "@agent_session_project_id", json.dumps("Falcon2"))
    tmux(pane.name, "set-option", "-w", "-t", "main:0", "@agent_session_target", json.dumps("leader"))
    tmux(pane.name, "set-option", "-s", "@project_board_expanded", json.dumps(["Falcon2"]))
    _wait(lambda: "48;2;47;109;179" in [line for line in pane.ansi().splitlines() if "Falcon2" in line][0].replace(":", ";"),
          what="the highlight")   # the managed window is read every 10 seconds
    assert "Leader" not in pane.screen() and "▶" not in pane.screen()
    ansi = pane.ansi().splitlines()
    name_row = [line for line in ansi if "Falcon2" in line][0]
    assert "48;2;47;109;179" in name_row.replace(":", ";")      # #2f6db3: a Leader window shows on the name row (BOARD-023)


def test_every_periodic_read_and_the_visibility_check_start_one_tmux_process(tmp_path, request):
    """BOARD-022: under load one tmux process costs 70-100 ms. The folds are read by one process every 2 seconds;
    the liveness read starts two (the server, then the options of the runs: spec section 5) and the managed window
    one, every 10 seconds; the visibility check one, however many commands it holds."""
    directory, log = _tmux_shim(tmp_path)
    pane = Pane(tmp_path, request, _board(tmp_path), path=directory + os.pathsep + os.environ["PATH"])
    pane.wait_text("Falcon2")
    time.sleep(1.0)
    started = len(log.read_text().splitlines())
    assert started <= 1 + 1 + 1 + 3, log.read_text()      # mark_ready, the visibility check after the signal the test sends, the first fold read, the first 10-second reads
    log.write_text("")
    time.sleep(20.5)
    calls = log.read_text().splitlines()
    folds = [c for c in calls if "@project_board_expanded" in c and "display-message" not in c]
    others = [c for c in calls if c not in folds]
    assert 9 <= len(folds) <= 11, calls                   # one per 2 seconds
    assert len(others) <= 2 * 3, calls                    # two 10-second cycles, three processes each at most
    # BOARD-027: the crontab is one `crontab -l` for every project, every 10 seconds, and none at the 2-second reads
    cron_calls = pane.crontab.calls()
    assert set(cron_calls) == {"-l"} and 3 <= len(cron_calls) <= 4, cron_calls     # the first read, then two 10-second cycles
    log.write_text("")
    process_id = int(tmux(pane.name, "display-message", "-p", "-t", pane.pane, "#{pane_pid}"))
    os.kill(process_id, signal.SIGUSR1)
    time.sleep(0.8)
    visibility = [c for c in log.read_text().splitlines() if "list-clients" in c]
    assert len(visibility) == 1 and "display-message" in visibility[0], log.read_text()


class FakeBoardWindow:
    """What a Board window is to a click (docs/project-board-tui-plan.md, BOARD-025): a pane marked as a window, whose process
    listens on a socket and answers one JSON line with one JSON line."""

    def __init__(self, pane, tmp_path, kind="cr", reply=None, link=True, release=""):
        self.requests = []
        self.reply = reply if reply is not None else b'{"ok": true}\n'
        self.path = f"/tmp/pb-win-{os.getpid()}-{id(self) % 100000}.win"
        Path(self.path).unlink(missing_ok=True)
        self.server = unix_socket.socket(unix_socket.AF_UNIX, unix_socket.SOCK_STREAM)
        self.server.bind(self.path)
        os.chmod(self.path, 0o600)
        self.server.listen(4)
        threading.Thread(target=self._serve, daemon=True).start()
        self.window_pane = tmux(pane.name, "split-window", "-d", "-P", "-F", "#{pane_id}", "-t", "main", "sleep", "300")
        tmux(pane.name, "set-option", "-p", "-t", self.window_pane, "@project_board_window", "1")
        tmux(pane.name, "set-option", "-p", "-t", self.window_pane, "@project_board_window_kind", kind)
        tmux(pane.name, "set-option", "-p", "-t", self.window_pane, "@project_board_window_release", release)
        if link:
            tmux(pane.name, "set-option", "-p", "-t", self.window_pane, "@project_board_window_link", self.path)

    def _serve(self):
        while True:
            try:
                connection, _ = self.server.accept()
            except OSError:
                return
            with connection:
                line = b""
                while b"\n" not in line:
                    block = connection.recv(4096)
                    if not block:
                        break
                    line += block
                self.requests.append(json.loads(line))
                connection.sendall(self.reply)

    def close(self):
        self.server.close()
        Path(self.path).unlink(missing_ok=True)


def _window_pane_setup(tmp_path, request, **window):
    pane = Pane(tmp_path, request, _board(tmp_path), launcher="fake")
    pane.wait_text("Falcon2")
    fake = FakeBoardWindow(pane, tmp_path, **window)
    request.addfinalizer(fake.close)
    return pane, fake, pane.clients[0][2]


def test_a_click_on_an_open_window_of_the_same_kind_tells_it_and_starts_nothing(tmp_path, request):
    pane, window, client = _window_pane_setup(tmp_path, request)
    assert pane.send_click(2, 3, client)["data"] == {"widget": "project-0-O"}            # O: a CR window
    _wait(lambda: len(window.requests) == 1, what="the request")
    assert window.requests[0] == {"kind": "cr", "project": "Falcon2", "state": "open", "client": client}
    _wait(lambda: tmux(pane.name, "display-message", "-p", "-t", window.window_pane, "#{pane_title}") == "CR · Falcon2", what="the title")
    assert pane.send_click(14, 3, client)["data"] == {"widget": "project-0-I"}
    _wait(lambda: len(window.requests) == 2, what="the second request")
    assert window.requests[1]["state"] == "in-progress"
    time.sleep(0.5)
    assert pane.helper_calls() == []                                                    # nothing was started


def test_a_decision_click_sends_a_decision_request_with_a_null_decision(tmp_path, request):
    pane, window, client = _window_pane_setup(tmp_path, request, kind="decision")
    assert pane.send_click(2, 2, client)["data"] == {"widget": "project-0-D"}
    _wait(lambda: len(window.requests) == 1, what="the request")
    assert window.requests[0] == {"kind": "decision", "project": "Falcon2", "decision": None, "client": client}
    _wait(lambda: tmux(pane.name, "display-message", "-p", "-t", window.window_pane, "#{pane_title}") == "Decision · Falcon2", what="the title")
    assert pane.helper_calls() == []


def test_a_busy_window_is_not_replaced_and_the_user_is_told(tmp_path, request):
    pane, window, client = _window_pane_setup(
        tmp_path, request, reply=b'{"ok": false, "code": "busy", "message": "An answer is being sent."}\n')
    pane.send_click(2, 3, client)
    pane.wait_text("An answer is being")            # the message wraps in a 25 column pane
    time.sleep(0.5)
    assert pane.helper_calls() == []


@pytest.mark.parametrize("situation", ["other kind", "still starting", "invalid", "closing", "not json", "other release"])
def test_a_window_that_cannot_take_the_item_is_started_the_ordinary_way(tmp_path, request, situation):
    options = {"other kind": {"kind": "decision"}, "still starting": {"link": False},
               "invalid": {"reply": b'{"ok": false, "code": "invalid", "message": "no"}\n'},
               "closing": {"reply": b'{"ok": false, "code": "closing"}\n'}, "not json": {"reply": b"hello\n"},
               "other release": {"release": "0.1.0-aaaaaaaaaaaa"}}[situation]
    pane, window, client = _window_pane_setup(tmp_path, request, **options)
    pane.send_click(2, 3, client)
    _wait(lambda: len(pane.helper_calls()) == 1, what="the helper run")
    assert pane.helper_calls() == [f"--config {pane.board.config} open-cr --project Falcon2 --state open --client {client}"]


def test_a_window_whose_process_is_gone_or_a_missing_window_is_started_the_ordinary_way(tmp_path, request):
    pane, window, client = _window_pane_setup(tmp_path, request)
    window.close()                                           # the socket file is gone: nothing listens
    pane.send_click(2, 3, client)
    _wait(lambda: len(pane.helper_calls()) == 1, what="the helper run after a dead window")
    tmux(pane.name, "kill-pane", "-t", window.window_pane)  # no window at all
    pane.send_click(8, 3, client)
    _wait(lambda: len(pane.helper_calls()) == 2, what="the helper run without a window")
    assert pane.helper_calls()[1].endswith(f"open-cr --project Falcon2 --state todo --client {client}")


# ------------------------------------------------------------------ the cron count (BOARD-027)
CRON_TEXT = "MAILTO=me\n0 1 * * * backup\n\n" + cron_section("Falcon2", ("check", "13,43 * * * *"), ("nightly", "0 3 * * *"))


def test_the_cron_count_shows_each_projects_jobs_and_marks_a_broken_section_or_an_unreadable_crontab(tmp_path, request):
    board = _board(tmp_path)
    shim = CrontabShim(tmp_path)
    shim.set(CRON_TEXT + "# >>> project-agent: ProjectB >>>\n# job x: y\n")           # ProjectB's section has no end
    pane = Pane(tmp_path, request, board)
    pane.wait_text("C:2")
    assert pane.lines()[2] == " D:2   C:2" and pane.lines()[6] == " D:1   C:!"
    shim.set(failure="crontab: no permission")
    _wait(lambda: pane.lines()[2] == " D:2   C:!", what="C:! on every project")   # the next 10-second read
    assert pane.lines()[2] == " D:2   C:!" and pane.lines()[6] == " D:1   C:!"
    shim.set(CRON_TEXT)
    _wait(lambda: pane.lines()[2] == " D:2   C:2", what="C:2 again")
    assert pane.lines()[6] == " D:1   C:0"


def test_the_cron_count_has_a_tooltip_with_the_time_to_the_next_run(tmp_path, request):
    board = _board(tmp_path)
    CrontabShim(tmp_path).set(CRON_TEXT)
    pane = Pane(tmp_path, request, board)
    pane.wait_text("C:2")
    pane.mouse("move", 8, 2)
    _wait(lambda: "cron 2개, 다음 실행" in pane.screen().replace("\n", " "), what="the tooltip")
    assert " 뒤" in pane.screen().replace("\n", " ")
    pane.mouse("move", 8, 6)                    # ProjectB's C:0
    _wait(lambda: "cron 작업 없음" in pane.screen(), what="the tooltip of C:0")


def test_pressing_the_cron_count_opens_the_cron_window_and_c0_does_nothing(tmp_path, request):
    board = _board(tmp_path)
    pane = Pane(tmp_path, request, board, launcher="fake")
    pane.crontab.set(CRON_TEXT)
    pane.wait_text("C:2")                      # the crontab is read before the first press
    client = pane.clients[0][2]
    assert pane.send_click(8, 2, client)["data"] == {"widget": "project-0-C"}
    _wait(lambda: len(pane.helper_calls()) == 1, what="the helper run")
    assert pane.helper_calls() == [f"--config {pane.board.config} open-cron --project Falcon2 --client {client}"]
    assert pane.send_click(8, 6, client)["data"] == {"widget": "project-1-C"}        # C:0: acknowledged, nothing opened
    time.sleep(0.5)
    assert len(pane.helper_calls()) == 1


def test_a_cron_click_tells_an_open_cron_window_and_starts_nothing(tmp_path, request):
    pane, window, client = _window_pane_setup(tmp_path, request, kind="cron")
    pane.crontab.set(CRON_TEXT)
    pane.wait_text("C:2")
    assert pane.send_click(8, 2, client)["data"] == {"widget": "project-0-C"}
    _wait(lambda: len(window.requests) == 1, what="the request")
    assert window.requests[0] == {"kind": "cron", "project": "Falcon2", "client": client}
    _wait(lambda: tmux(pane.name, "display-message", "-p", "-t", window.window_pane, "#{pane_title}") == "Cron · Falcon2", what="the title")
    time.sleep(0.5)
    assert pane.helper_calls() == []


def test_a_cron_click_on_a_window_of_another_kind_starts_the_cron_window_the_ordinary_way(tmp_path, request):
    pane, window, client = _window_pane_setup(tmp_path, request, kind="cr")
    pane.crontab.set(CRON_TEXT)
    pane.wait_text("C:2")
    pane.send_click(8, 2, client)
    _wait(lambda: len(pane.helper_calls()) == 1, what="the helper run")
    assert pane.helper_calls() == [f"--config {pane.board.config} open-cron --project Falcon2 --client {client}"]
    assert window.requests == []
