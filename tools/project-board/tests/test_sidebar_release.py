"""BOARD-028: a sidebar follows the installed release. The binaries here sit in a release layout
(`<lib>/releases/<name>/tools/project-board/bin/` with a symlink `<lib>/current`, install contract "release의 식별")
inside the tmux pane, so the sidebar reads its own release from where it is, as an installed one does."""
import os
import shutil
import signal
import stat
import time
from pathlib import Path

import pytest

import board_testing  # noqa: F401  (adds the Board tool to sys.path)
from board_testing import tmux
from rust_binary import sidebar_binary
from test_sidebar_binary import FakeBoardWindow, Pane, _board, _tmux_shim, _wait

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
OLD, NEW = "0.11.0-aaaaaaaaaaaa", "0.12.0-bbbbbbbbbbbb"
RESTART = "재시작 필요"


class Lib:
    """An installed layout of copies of the sidebar binary: one release per name, `current` pointing at one."""

    def __init__(self, tmp_path, *names, current):
        self.root = (tmp_path / "lib").resolve()
        for name in names:
            self.release(name)
        self.point(current)

    def release(self, name, binary=True):
        bin_dir = self.root / "releases" / name / "tools" / "project-board" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        if binary:
            shutil.copy2(sidebar_binary(), bin_dir / "project-board-sidebar")
        else:
            (bin_dir / "project-board-sidebar").unlink(missing_ok=True)
        return bin_dir / "project-board-sidebar"

    def binary(self, name):
        return self.root / "releases" / name / "tools" / "project-board" / "bin" / "project-board-sidebar"

    def point(self, name):
        """`current` -> `releases/<name>`, replaced atomically as the installer does."""
        staging = self.root / "current.new"
        staging.unlink(missing_ok=True)
        staging.symlink_to("releases/" + name)
        os.replace(staging, self.root / "current")


def _process(pane):
    return int(tmux(pane.name, "display-message", "-p", "-t", pane.pane, "#{pane_pid}"))


def _executable(pid):
    try:
        return Path(os.readlink(f"/proc/{pid}/exe"))
    except OSError:
        return None


def _facts(pane):
    """What must not change when the sidebar replaces itself: the pane, its size and place, the process, its options."""
    return {
        "pane": pane.pane,
        "geometry": tmux(pane.name, "display-message", "-p", "-t", pane.pane,
                         "#{pane_width}x#{pane_height}@#{pane_left},#{pane_top}"),
        "process": _process(pane),
        "folds": pane.folds(),
        "ready": tmux(pane.name, "show-options", "-pqv", "-t", pane.pane, "@project_board_ready"),
    }


def _sidebar_in(tmp_path, request, current=OLD, names=(OLD, NEW), **options):
    lib = Lib(tmp_path, *names, current=current)
    board = _board(tmp_path)
    pane = Pane(tmp_path, request, board, binary=lib.binary(OLD), **options)
    pane.wait_text("Falcon2")
    _wait(lambda: pane.folds() == set() and tmux(pane.name, "show-options", "-pqv", "-t", pane.pane, "@project_board_ready") == "1",
          what="mark_ready")
    return lib, pane


def test_a_new_release_replaces_the_sidebar_in_the_same_pane_with_the_state_it_had(tmp_path, request):
    lib, pane = _sidebar_in(tmp_path, request)
    tmux(pane.name, "set-option", "-s", "@project_board_expanded", '["Falcon2"]')       # a state that lives in tmux
    pane.wait_text("CPU-012")
    process = _process(pane)
    assert _executable(process) == lib.binary(OLD)
    facts = _facts(pane)
    clicked = pane.send_click(0, 0)                                                     # the click socket answers
    assert clicked["error"]["code"] in ("no_widget", "not_clickable")

    lib.point(NEW)
    _wait(lambda: _executable(process) == lib.binary(NEW), timeout=10, what="the new release's binary in the same process")
    pane.wait_text("CPU-012")                                                           # drawn again, seats still open
    assert _facts(pane) == facts
    assert RESTART not in pane.screen()
    assert pane.send_click(0, 0) == clicked                                             # the same socket, the new process
    os.kill(process, signal.SIGUSR1)                                                    # its handler is installed
    time.sleep(0.5)
    assert _executable(process) == lib.binary(NEW) and "Falcon2" in pane.screen()
    time.sleep(5)                                                                       # and it does not switch again
    assert _executable(process) == lib.binary(NEW) and _facts(pane) == facts


def test_the_same_release_shows_nothing_and_changes_nothing(tmp_path, request):
    lib, pane = _sidebar_in(tmp_path, request)
    process, facts = _process(pane), _facts(pane)
    time.sleep(5)                                                                       # more than two reads
    assert _executable(process) == lib.binary(OLD) and _facts(pane) == facts
    assert RESTART not in pane.screen()
    lib.point(OLD)                                                                      # `current` written again: still this release
    time.sleep(3)
    assert _executable(process) == lib.binary(OLD) and RESTART not in pane.screen()


def test_a_sidebar_that_is_not_in_a_release_never_switches(tmp_path, request):
    board = _board(tmp_path)
    pane = Pane(tmp_path, request, board)                                               # the binary the tests build, in a checkout
    pane.wait_text("Falcon2")
    process = _process(pane)
    before = _executable(process)
    time.sleep(5)
    assert _executable(process) == before and RESTART not in pane.screen()


@pytest.mark.parametrize("situation", ["no binary", "not executable", "not a program", "current is gone", "current outside releases"])
def test_a_sidebar_that_cannot_switch_keeps_its_code_and_says_a_restart_is_needed_and_why(tmp_path, request, situation):
    lib, pane = _sidebar_in(tmp_path, request)
    process = _process(pane)
    if situation == "no binary":
        lib.release(NEW, binary=False)
        lib.point(NEW)
        reason = NEW
    elif situation == "not executable":
        lib.binary(NEW).chmod(stat.S_IMODE(lib.binary(NEW).stat().st_mode) & ~0o111)
        lib.point(NEW)
        reason = NEW
    elif situation == "not a program":
        lib.binary(NEW).write_bytes(b"\x7fELF not a program")
        lib.point(NEW)
        reason = "실행하지 못했습니다"
    elif situation == "current is gone":
        lib.point("nothing-here")
        reason = "current를 읽을 수 없습니다"
    else:
        (lib.root / "elsewhere").mkdir()
        lib.point("../elsewhere")
        reason = "releases 밖"
    pane.wait_text(RESTART, timeout=10)
    screen = pane.screen()
    assert reason in screen.replace("\n", "") or reason in " ".join(screen.split()), screen
    assert "prefix B" in " ".join(screen.split()), screen                               # how to start it again
    assert _executable(process) == lib.binary(OLD) and _process(pane) == process        # the old code carries on
    assert any("Falcon2" in line for line in pane.lines())                              # and keeps drawing
    # `current` is this release again: the notice goes
    lib.point(OLD)
    pane.wait_gone(RESTART, timeout=10)
    assert _executable(process) == lib.binary(OLD)


def test_a_notice_stays_with_a_registry_error_that_the_old_code_may_have_made(tmp_path, request):
    lib, pane = _sidebar_in(tmp_path, request)
    lib.release(NEW, binary=False)
    lib.point(NEW)
    pane.board.config.write_text("{not json", encoding="utf-8")                         # the registry no longer reads
    pane.wait_text("project registry", timeout=10)
    pane.wait_text(RESTART, timeout=10)                                                 # both are shown


def test_looking_for_the_installed_release_starts_no_process(tmp_path, request):
    """The period of the reads is the sidebar's own (BOARD-022): a sidebar that finds `current` elsewhere, and
    one that does not, make the same tmux and crontab calls."""
    directory, log = _tmux_shim(tmp_path)
    lib, pane = _sidebar_in(tmp_path, request, path=directory + os.pathsep + os.environ["PATH"])
    lib.release(NEW, binary=False)
    lib.point(NEW)                                                                      # the check now fails every 2 seconds
    pane.wait_text(RESTART, timeout=10)
    log.write_text("")
    pane.crontab.calls_path.write_text("")
    time.sleep(20.5)
    calls = log.read_text().splitlines()
    folds = [c for c in calls if "@project_board_expanded" in c and "display-message" not in c]
    others = [c for c in calls if c not in folds]
    assert 9 <= len(folds) <= 11, calls
    assert len(others) <= 2 * 3, calls
    assert set(pane.crontab.calls()) == {"-l"} and len(pane.crontab.calls()) <= 3


def test_a_window_the_sidebars_own_release_started_is_told_and_one_another_release_started_is_not(tmp_path, request):
    lib = Lib(tmp_path, OLD, NEW, current=OLD)
    pane = Pane(tmp_path, request, _board(tmp_path), launcher="fake", binary=lib.binary(OLD))
    pane.wait_text("Falcon2")
    client = pane.clients[0][2]
    mine = FakeBoardWindow(pane, tmp_path, release=OLD)
    request.addfinalizer(mine.close)
    assert pane.send_click(2, 3, client)["data"] == {"widget": "project-0-O"}
    _wait(lambda: len(mine.requests) == 1, what="the request to a window of this release")
    assert pane.helper_calls() == []
    tmux(pane.name, "set-option", "-p", "-t", mine.window_pane, "@project_board_window_release", NEW)
    pane.send_click(8, 3, client)
    _wait(lambda: len(pane.helper_calls()) == 1, what="the window of another release started again")
    assert len(mine.requests) == 1
    assert pane.helper_calls()[0].endswith(f"open-cr --project Falcon2 --state todo --client {client}")
