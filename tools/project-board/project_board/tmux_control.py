"""tmux placement and client-directed actions for the Project Board TUI.

The server owns one global toggle. A Board pane is created in a window when an attached
client first watches it, and stays until the toggle is turned off, the window's managed pane
dies, or the window closes. Multiple clients watching the same window share that pane; a
mouse binding sends each click's client and pane-relative coordinates over a local
socket so actions still target the client that clicked.

A CR or decision window is a floating pane of the clicking client's window (BOARD-020), not a
popup: a popup is modal, a floating pane lets the sidebar and the work pane behind it be used.
Each window holds at most one; opening another item reuses it, keeping where it was moved to and
how large it was made.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import socket as unix_socket
import stat
import subprocess
import time
import uuid

from . import model, window_link
from agent_session import api
from agent_session.api import PANE_ID_OPTION, SessionError, Tmux


ENABLED = "@project_board_enabled"
CONFIG = "@project_board_config"
WIDTH = "@project_board_width"
EXPANDED = "@project_board_expanded"
WINDOW_PANE = "@project_board_pane"
WINDOW_RESTORE = "@project_board_restore"
PANE_MARK = "@project_board_managed"
PANE_SOCKET = "@project_board_click_socket"
PANE_READY = "@project_board_ready"
PANE_WINDOW = "@project_board_window"
PANE_WINDOW_KIND = "@project_board_window_kind"        # `cr` or `decision`: what the pane's process was started as
PANE_WINDOW_LINK = "@project_board_window_link"        # the socket it listens on, set by the process once it does
WINDOW_SEEN = "@project_board_seen"
SIDEBAR_WIDTH = 25
# The most Board panes kept at once. One Board process holds about 50 MB (RSS, measured) and reads
# the project files only while its window is shown, so the bound is memory, not CPU: 8 panes are
# about 400 MB at most. The windows a user moves among in a working session (a project's Leader and
# Workers) fit; a pane over the bound is removed from the window that no client showed for longest.
MAX_KEPT = 8
CLICK_TIMEOUT = 2
# How long opening a Board window waits for its pane to mark itself; a failed start is reported by its job.
WINDOW_START = 3
# How long a click waits for a Board window of the same kind that is still starting, before it starts the window again.
WINDOW_REUSE_WAIT = 20
STARTING = "Board 창을 시작하는 중…"
LAUNCHER = Path(__file__).resolve().parents[1] / "bin" / "project-board"


def _ok(data=None) -> dict:
    return {"ok": True, "data": data, "error": None}


def _fail(code: str, message: str, details=None) -> dict:
    return {"ok": False, "data": None,
            "error": {"code": code, "message": message, "details": details or {}}}


def _session_error(error: SessionError) -> dict:
    return _fail(error.code, error.message, getattr(error, "details", None))


def _control(socket=None) -> Tmux:
    path = socket or os.environ.get("PROJECT_BOARD_SOCKET")
    return Tmux(socket_path=str(path)) if path else Tmux()


RUNTIME_ROOT = Path("/tmp")
_RUNTIME_NAME = re.compile(r"project-board-(\d+)-(\d+)")
_RUNTIME_FILES = re.compile(r"control\.lock|[0-9a-f]{16}\.sock")
# A server's directory is made after the server started, and nothing writes it after the server
# ends. `ps` reports a process age in whole seconds, so a process that started less than this long
# after the directory's last change is still treated as its creator (a live server is never judged
# dead by rounding; a recycled pid that is that young is left for the next sweep).
_START_SLACK = 2.0


def _elapsed_seconds(text: str) -> float | None:
    """Parse `ps -o etime=` (`[[dd-]hh:]mm:ss`)."""
    days, _, clock = text.rpartition("-")
    try:
        parts = [int(part) for part in clock.split(":")]
        if not 2 <= len(parts) <= 3 or (days and len(parts) != 3):
            return None
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + part
        return seconds + (int(days) * 86400 if days else 0)
    except ValueError:
        return None


def _is_tmux_server_of(pid: int, created: float) -> bool:
    """Whether `pid` is a live tmux process old enough to have created a directory last changed at `created`.

    A directory name carries only a pid, and the OS reuses pids. A live pid therefore proves
    nothing by itself, so two things must both hold: the process is tmux (`ps` command name, which
    is `tmux: server` on Linux and the executable path on macOS), and it started no later than the
    directory's last change. The directory is made by the server's own Board commands, so a process
    that started after that is a different one that inherited the pid.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False  # a process of another user is never this user's tmux server
    except OSError:
        return True  # cannot tell: leave the directory
    try:
        result = subprocess.run(["ps", "-o", "etime=,comm=", "-p", str(pid)],
                                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return True
    fields = result.stdout.split(None, 1)
    if result.returncode != 0 or len(fields) != 2:
        return result.returncode != 1  # 1: ps found no such process
    elapsed = _elapsed_seconds(fields[0])
    if elapsed is None:
        return True
    if not os.path.basename(fields[1].strip()).startswith("tmux"):
        return False
    return time.time() - elapsed <= created + _START_SLACK


def _remove_runtime_directory(directory: Path) -> bool:
    """Remove a Board runtime directory only if it holds nothing but what the Board makes."""
    with os.scandir(directory) as entries:
        found = list(entries)
    for entry in found:
        if not _RUNTIME_FILES.fullmatch(entry.name):
            return False
        mode = entry.stat(follow_symlinks=False).st_mode
        if not (stat.S_ISSOCK(mode) if entry.name.endswith(".sock") else stat.S_ISREG(mode)):
            return False
    for entry in found:
        try:
            os.unlink(entry.path)
        except FileNotFoundError:
            pass
    os.rmdir(directory)
    return True


def reap_runtime_directories(root: Path | None = None) -> list[Path]:
    """Remove this user's Board runtime directories whose tmux server has ended.

    `/tmp/project-board-<uid>-<server pid>` is owned by that server's lifetime, but `kill-server`
    and a crash give the server no chance to remove it, so the next Board command in any server
    does. Only a plain directory (no symlink) of this user with mode 0700, named exactly so, and
    holding only `control.lock` and `<16 hex>.sock`, is removed. Two sweeps may race: a directory
    another sweep already removed is skipped. Failures never reach the caller.
    """
    root = RUNTIME_ROOT if root is None else root
    uid = os.getuid()
    removed = []
    try:
        names = [entry.name for entry in os.scandir(root) if entry.name.startswith(f"project-board-{uid}-")]
    except OSError:
        return removed
    for name in names:
        match = _RUNTIME_NAME.fullmatch(name)
        if match is None or int(match.group(1)) != uid:
            continue
        directory = root / name
        try:
            info = directory.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid
                    or stat.S_IMODE(info.st_mode) != 0o700):
                continue
            if _is_tmux_server_of(int(match.group(2)), info.st_mtime):
                continue
            if _remove_runtime_directory(directory):
                removed.append(directory)
        except OSError:
            continue  # already removed by a concurrent sweep, or not removable: leave it
    return removed


def _private_dir(control: Tmux) -> Path:
    pid = control.command("display-message", "-p", "#{pid}")
    if not pid.isdigit():
        raise ValueError("tmux did not identify its server process")
    reap_runtime_directories()
    directory = RUNTIME_ROOT / f"project-board-{os.getuid()}-{pid}"
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("Project Board's tmux runtime directory is not private")
    return directory


@contextmanager
def _locked(control: Tmux):
    path = _private_dir(control) / "control.lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("Project Board's tmux lock is not private")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _lines(control: Tmux, *args) -> list[str]:
    return [line for line in control.command(*args).splitlines() if line]


def _clients(control: Tmux) -> tuple[str, ...]:
    return tuple(_lines(control, "list-clients", "-F", "#{client_name}"))


def _client(control: Tmux, selected: str | None) -> str:
    attached = _clients(control)
    if selected is None:
        if len(attached) != 1:
            raise ValueError("Select a tmux client when none or several are attached")
        return attached[0]
    if selected not in attached:
        raise ValueError("The selected tmux client is not attached")
    return selected


def _client_window(control: Tmux, client: str) -> str | None:
    for row in _lines(control, "list-clients", "-F", "#{client_name}\t#{window_id}"):
        name, separator, window = row.partition("\t")
        if separator and name == client:
            return window
    return None


def _options(control: Tmux, *args) -> str:
    return control.command("show-options", "-qv", *args)


def _expanded(control: Tmux) -> set[str]:
    raw = _options(control, "-s", EXPANDED)
    if not raw:
        return set()
    values = json.loads(raw)
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError("Project Board's expanded project option is invalid")
    return set(values)


def expanded_projects(socket=None) -> set[str]:
    """Read the project folds shared by every Board pane in this tmux server.

    One `show-options` reads the whole value, so no lock is taken: the lock only orders the
    read-modify-write of `toggle_expanded_project`. Every Board pane reads this on each refresh
    (BOARD-013), and the lock would start a `display-message` and a `ps` per other tmux server each time.
    """
    return _expanded(_control(socket))


def toggle_expanded_project(project_id: str, socket=None) -> set[str]:
    """Atomically toggle one project in the server-wide Board fold state."""
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("project ID is required")
    control = _control(socket)
    with _locked(control):
        expanded = _expanded(control)
        if project_id in expanded:
            expanded.remove(project_id)
        else:
            expanded.add(project_id)
        control.command("set-option", "-s", EXPANDED,
                        json.dumps(sorted(expanded), ensure_ascii=False))
        return expanded


def _panes(control: Tmux, window: str) -> dict[str, bool]:
    rows = _lines(control, "list-panes", "-t", window, "-F", "#{pane_id}\t#{pane_dead}")
    out = {}
    for row in rows:
        pane, separator, dead = row.partition("\t")
        if separator:
            out[pane] = dead == "1"
    return out


class _Window:
    """What one window tells `_snapshot`: its panes (id -> dead), the Board and managed-pane options of the
    window, the time a client last showed it, and the Board mark of each of its panes."""

    def __init__(self):
        self.panes: dict[str, bool] = {}
        self.board = ""
        self.managed = ""
        self.seen = ""
        self.marks: dict[str, str] = {}


class _Snapshot:
    """The server state `_reconcile` and `_evict` judge, read by one tmux process.

    A format reads an option through the pane, the window, the session and the global levels, where
    `show-options -w` reads the window alone. The Board and agent-session write `@project_board_pane`,
    `@project_board_seen` and the managed-pane option only on windows, and `@project_board_managed` only
    on panes, never above, so the values are the ones the per-window reads gave.
    """

    def __init__(self, enabled: str, width: str, config: str, visible: list[str], windows: dict[str, _Window]):
        self.enabled = enabled == "1"
        self.width = width
        self.config = config or None
        self.visible = visible
        self.windows = windows


def _snapshot(control: Tmux) -> _Snapshot:
    """Read the global Board options, the windows the clients show, and every window and pane at once."""
    rows = _lines(
        control,
        "display-message", "-p", f"G\t#{{{ENABLED}}}\t#{{{WIDTH}}}\t#{{{CONFIG}}}",
        ";", "list-clients", "-F", "C\t#{window_id}",
        ";", "list-panes", "-a", "-F",
        f"P\t#{{window_id}}\t#{{pane_id}}\t#{{pane_dead}}\t#{{{WINDOW_PANE}}}\t#{{{PANE_ID_OPTION}}}"
        f"\t#{{{WINDOW_SEEN}}}\t#{{{PANE_MARK}}}")
    enabled = width = config = ""
    visible, windows = [], {}
    for row in rows:
        kind, _, rest = row.partition("\t")
        if kind == "G":
            enabled, width, config = rest.split("\t", 2)
        elif kind == "C":
            visible.append(rest)
        elif kind == "P":
            window, pane, dead, board, managed, seen, mark = rest.split("\t", 6)
            record = windows.setdefault(window, _Window())
            if not record.panes:
                record.board, record.managed, record.seen = board, managed, seen
            record.panes[pane] = dead == "1"
            record.marks[pane] = mark
    return _Snapshot(enabled, width, config, visible, windows)


def _managed_pane_dead(window: _Window) -> bool:
    if not window.managed:
        return False
    try:
        pane = json.loads(window.managed)
    except ValueError:
        return False
    return isinstance(pane, str) and window.panes.get(pane, False)


def _board_pane(control: Tmux, window: str, record: _Window) -> str | None:
    pane = record.board
    if not pane:
        return None
    if pane in record.panes and record.marks.get(pane) == "1":
        return pane
    try:
        if pane not in record.panes:
            _restore(control, window)
    finally:
        control.command("set-option", "-wu", "-t", window, WINDOW_PANE)
        control.command("set-option", "-wu", "-t", window, WINDOW_RESTORE)
    return None


def _floating(node: dict) -> list[dict]:
    """The floating panes of a tmux layout tree (`#{window_layout}`, tmux 3.8): the leaves with a `z`."""
    if node["t"] == "p":
        return [node] if "z" in node else []
    return [leaf for child in node["c"] for leaf in _floating(child)]


def _tiled(node: dict, active: bool) -> dict | None:
    """The layout tree without its floating panes. A container left with one child is that child.

    `active` is true when a floating pane is the active one: a layout names one active pane only, so
    the tiled panes then keep none."""
    if node["t"] == "p":
        if "z" in node:
            return None
        return {key: value for key, value in node.items() if key != "a"} if active else node
    children = [child for child in (_tiled(child, active) for child in node["c"]) if child is not None]
    if len(children) == 1:
        return {**children[0], **{key: node[key] for key in "whxy"}}
    return {**node, "c": children}


def _layout_with_floating(control: Tmux, window: str, layout: str) -> tuple[str, bool]:
    """`layout` (saved before the sidebar was added) with the window's floating panes of now, and whether
    one of them is the active pane.

    `select-layout` needs a layout that names every pane of the window. A saved layout names the panes
    of its time, so a floating pane (the Board's CR or decision window) opened or closed since would
    make it fail.
    """
    try:
        current = _floating(json.loads(control.command("display-message", "-p", "-t", window,
                                                       "#{window_layout}"))["L"])
        saved = json.loads(layout)
        active = any(leaf.get("a") for leaf in current)
        root = _tiled(saved["L"], active)
    except (ValueError, KeyError, TypeError):
        return layout, False
    if root is None:
        return layout, False
    if current:
        if root["t"] == "p":
            root = {"t": "v", **{key: root[key] for key in "whxy"}, "c": [root]}
        root = {**root, "c": [*root["c"], *current]}
    return json.dumps({**saved, "L": root}, separators=(",", ":")), active


def _restore(control: Tmux, window: str) -> None:
    raw = _options(control, "-w", "-t", window, WINDOW_RESTORE)
    if not raw:
        return
    saved = json.loads(raw)
    layout, floating_active = _layout_with_floating(control, window, saved["layout"])
    control.command("select-layout", "-t", window, layout)
    if not floating_active and saved["focus"] in _panes(control, window):
        control.command("select-pane", "-t", saved["focus"])


def _remove(control: Tmux, window: str, pane: str) -> None:
    control.command("kill-pane", "-t", pane)
    try:
        _restore(control, window)
    except SessionError:
        # Killing a sole remaining pane can close its window as well.
        if window in _lines(control, "list-windows", "-a", "-F", "#{window_id}"):
            raise
    finally:
        try:
            control.command("set-option", "-wu", "-t", window, WINDOW_PANE)
            control.command("set-option", "-wu", "-t", window, WINDOW_RESTORE)
        except SessionError:
            if window in _lines(control, "list-windows", "-a", "-F", "#{window_id}"):
                raise


def _sidebar_command(config: str | None) -> list[str]:
    command = [str(LAUNCHER)]
    if config:
        command.extend(("--config", config))
    command.append("sidebar")
    return command


def _create(control: Tmux, window: str, config: str | None, width: int) -> str:
    click_path = _private_dir(control) / (uuid.uuid4().hex[:16] + ".sock")
    layout = control.command("display-message", "-p", "-t", window, "#{window_layout}")
    focus = control.command("display-message", "-p", "-t", window, "#{pane_id}")
    command = ["split-window", "-d", "-f", "-h", "-b", "-l", str(width),
               "-P", "-F", "#{pane_id}", "-t", window,
               "-e", f"PROJECT_BOARD_CLICK_SOCKET={click_path}", *_sidebar_command(config)]
    pane = control.command(*command).strip()
    if not pane.startswith("%"):
        raise ValueError("tmux did not return the Board pane handle")
    try:
        control.command("set-option", "-w", "-t", window, WINDOW_RESTORE,
                        json.dumps({"layout": layout, "focus": focus}))
        control.command("set-option", "-p", "-t", pane, PANE_MARK, "1")
        control.command("set-option", "-p", "-t", pane, PANE_SOCKET, str(click_path))
        control.command("set-option", "-w", "-t", window, WINDOW_PANE, pane)
    except Exception:
        try:
            control.command("kill-pane", "-t", pane)
        except SessionError:
            pass
        try:
            control.command("select-layout", "-t", window, layout)
            control.command("select-pane", "-t", focus)
        except SessionError:
            pass
        for option in (WINDOW_PANE, WINDOW_RESTORE):
            try:
                control.command("set-option", "-wu", "-t", window, option)
            except SessionError:
                pass
        raise
    return pane


def _can_fit_width(control: Tmux, window: str, width: int) -> bool:
    window_width = int(control.command("display-message", "-p", "-t", window,
                                       "#{window_width}"))
    return window_width > width + 1


def _evict(control: Tmux, shown_kept: list[str], created: list[str], failures: list) -> list[str]:
    """Remove Board panes beyond MAX_KEPT, from the windows that were shown longest ago.

    A window a client shows now is never removed. `@project_board_seen` is the time a client last
    showed the window (project_board_visibility.sh writes it; a new pane starts at now).
    """
    now = str(int(time.time()))
    for window in created:
        control.command("set-option", "-w", "-t", window, WINDOW_SEEN, now)
    shown = set(shown_kept) | set(created)
    boards = []
    for window, record in _snapshot(control).windows.items():
        if record.board:
            boards.append((window, record.board, int(record.seen) if record.seen.isdecimal() else 0))
    evicted = []
    excess = len(boards) - MAX_KEPT
    for window, pane, _seen in sorted((b for b in boards if b[0] not in shown), key=lambda b: b[2]):
        if excess <= 0:
            break
        try:
            _remove(control, window, pane)
            evicted.append(window)
            excess -= 1
        except (SessionError, OSError, ValueError) as error:
            failures.append({"window": window, "reason": str(error)})
    return evicted


def _reconcile(control: Tmux) -> dict:
    snapshot = _snapshot(control)
    enabled, config = snapshot.enabled, snapshot.config
    visible = set(snapshot.visible) if enabled else set()
    windows = snapshot.windows
    created, removed, failures = [], [], []
    to_remove, to_create, to_keep = [], [], []
    for window, record in windows.items():
        try:
            panes = record.panes
            board = _board_pane(control, window, record)
            usable = enabled and not _managed_pane_dead(record)
            # A Board pane stays in a window nobody watches: it is the process that costs seconds
            # to start, and the next client to arrive finds it already showing.
            if board and (not usable or panes[board]):
                to_remove.append((window, board))
                board = None
            show = usable and window in visible
            if show and board is None and panes:
                to_create.append(window)
            elif show and board:
                to_keep.append((window, board))
        except (SessionError, OSError, ValueError) as error:
            failures.append({"window": window, "reason": str(error)})

    saved_width = snapshot.width
    saved_width_valid = saved_width.isdecimal() and int(saved_width) > 0
    width = int(saved_width) if saved_width_valid else SIDEBAR_WIDTH
    if not saved_width_valid and (to_remove or to_create or to_keep):
        control.command("set-option", "-g", WIDTH, str(width))
    board_count = len(to_remove) + len(to_keep)
    for window, board in to_remove:
        try:
            pane_width = int(control.command("display-message", "-p", "-t", board, "#{pane_width}"))
            capture_width = False
            if board_count == 1 and pane_width != width and _can_fit_width(control, window, width):
                control.command("resize-pane", "-t", board, "-x", str(width))
                fitted_width = int(control.command("display-message", "-p", "-t", board,
                                                   "#{pane_width}"))
                capture_width = fitted_width == width
                control.command("set-option", "-g", WIDTH, str(width))
            _remove(control, window, board)
            removed.append(window)
            if capture_width:
                width = pane_width
                control.command("set-option", "-g", WIDTH, str(width))
        except (SessionError, OSError, ValueError) as error:
            failures.append({"window": window, "reason": str(error)})
    for window, board in to_keep:
        try:
            pane_width = int(control.command("display-message", "-p", "-t", board, "#{pane_width}"))
            if pane_width != width and _can_fit_width(control, window, width):
                control.command("resize-pane", "-t", board, "-x", str(width))
        except (SessionError, OSError, ValueError) as error:
            failures.append({"window": window, "reason": str(error)})
    for window in to_create:
        try:
            _create(control, window, config, width)
            created.append(window)
        except (SessionError, OSError, ValueError) as error:
            failures.append({"window": window, "reason": str(error)})
    for window in _evict(control, [w for w, _ in to_keep], created, failures):
        removed.append(window)
    if to_remove or to_keep or to_create:
        control.command("set-option", "-g", WIDTH, str(width))
    return {"enabled": enabled, "visible_windows": sorted(visible),
            "created": created, "removed": removed, "failures": failures}


def board_visible(socket=None) -> bool:
    """Whether a client shows the window of this Board pane (read from the pane itself).

    The answer comes from tmux's clients, not from `@project_board_visible`, which is only the
    change record of project_board_visibility.sh.
    """
    control = _control(socket)
    pane = os.environ.get("TMUX_PANE")
    if not pane:
        return True
    window = control.command("display-message", "-p", "-t", pane, "#{window_id}")
    return window in _lines(control, "list-clients", "-F", "#{window_id}")


def mark_ready(socket=None) -> bool:
    """Tell project_board_visibility.sh that this pane handles SIGUSR1, then return whether it is shown.

    The mark comes first so that a change after the read is signalled; the read comes after so
    that a change before the mark is not lost.
    """
    control = _control(socket)
    pane = os.environ.get("TMUX_PANE")
    if pane:
        control.command("set-option", "-p", "-t", pane, PANE_READY, "1")
    return board_visible(socket)


def active_context(socket=None) -> dict | None:
    """The managed project and slot of this Board pane's window, or None (BOARD-009).

    The pane shares its window with every client that watches it, so that window is the active
    window of each client showing this sidebar. `slot` is `leader`, `seat-N`, or None when the window's
    target is not a slot. Returns None outside tmux and for a window that is not managed. Which options
    name the project and slot belongs to agent-session (`agent_session.api.pane_slot`).
    """
    pane = os.environ.get("TMUX_PANE")
    if not pane:
        return None
    found = api.pane_slot(pane, _control(socket))
    return None if found is None else {"project_id": found[0], "slot": found[1]}


def reconcile(config=None, socket=None) -> dict:
    """Match Board panes to windows currently watched by attached clients."""
    try:
        control = _control(socket)
        with _locked(control):
            if config is not None:
                control.command("set-option", "-g", CONFIG, str(Path(config).expanduser().resolve()))
            data = _reconcile(control)
        return _ok(data) if not data["failures"] else _fail("sidebar_partial", "Some tmux windows could not be updated.", data)
    except SessionError as error:
        return _session_error(error)
    except (OSError, ValueError) as error:
        return _fail("sidebar_unavailable", str(error))


def toggle_sidebar(config=None, client=None, socket=None) -> dict:
    """Toggle the server-wide Board, then update only visible windows."""
    try:
        control = _control(socket)
        with _locked(control):
            if client is not None:
                _client(control, client)
            enabled = _options(control, "-g", ENABLED) == "1"
            control.command("set-option", "-g", ENABLED, "0" if enabled else "1")
            if config is not None:
                control.command("set-option", "-g", CONFIG, str(Path(config).expanduser().resolve()))
            data = _reconcile(control)
        return _ok(data) if not data["failures"] else _fail("sidebar_partial", "Some tmux windows could not be updated.", data)
    except SessionError as error:
        return _session_error(error)
    except (OSError, ValueError) as error:
        return _fail("sidebar_unavailable", str(error))


def _window_pane(control: Tmux, window: str) -> str | None:
    """The window's Board window (a floating pane marked `@project_board_window`), or None."""
    for row in _lines(control, "list-panes", "-t", window, "-F", f"#{{pane_id}}\t#{{{PANE_WINDOW}}}"):
        pane, _, mark = row.partition("\t")
        if mark == "1":
            return pane
    return None


def _window_command(socket: str, args: list[str], kind: str) -> list[str]:
    """The command of a Board window: it marks its own pane, then becomes `args`.

    The mark is made by the pane itself because `new-pane -W` returns only when the pane ends, so
    nothing can mark it from outside after it starts. `remain-on-exit` of the pane is off: a managed
    window has it on (agent-session), which would leave a closed Board window behind as a dead pane.
    The pane says what it is starting (`STARTING`) at once: the Python process behind it needs seconds on a
    loaded host and the pane is empty until its screen is drawn (BOARD-025).
    """
    pane = '"$TMUX_PANE"'
    script = (f"tmux -S {shlex.quote(socket)} set-option -p -t {pane} remain-on-exit off \\; "
              f"set-option -p -t {pane} {PANE_WINDOW} 1 \\; "
              f"set-option -p -t {pane} {PANE_WINDOW_KIND} {kind} \\; "
              f"set-option -pu -t {pane} {PANE_WINDOW_LINK}; "
              f"printf '%s\\n' {shlex.quote(STARTING)}; exec \"$@\"")
    return ["sh", "-c", script, "sh", *args]


def _window_options(control: Tmux, pane: str) -> tuple[str, str]:
    """The kind of the pane's window process and the socket it listens on ('' while it is starting)."""
    row = control.command("display-message", "-p", "-t", pane,
                          f"#{{{PANE_WINDOW_KIND}}}\t#{{{PANE_WINDOW_LINK}}}")
    kind, _, link = row.partition("\t")
    return kind, link


def _reuse(control: Tmux, pane: str, kind: str, request: dict, title: str) -> dict | None:
    """Tell the process of the window in `pane` what to show; None when the pane must be started again.

    Only a window of the same `kind` is reused: its process is the one that can show that kind of item, and
    it keeps what it has read, so the new item appears without starting Python and Textual again. A process
    that is still starting is waited for (`WINDOW_REUSE_WAIT`); one that does not answer is replaced.
    """
    current, link = _window_options(control, pane)
    if current != kind:
        return None
    deadline = time.monotonic() + WINDOW_REUSE_WAIT
    while not link and time.monotonic() < deadline:
        time.sleep(0.05)
        current, link = _window_options(control, pane)
    if not link or current != kind:
        return None
    try:
        result = window_link.send(link, request)
    except OSError:
        return None
    if result.get("ok"):
        control.command("select-pane", "-t", pane, "-T", title)
        return _ok({"pane": pane, "reused": True})
    if result.get("code") == "busy":
        return _fail("window_busy", result.get("message") or "The Board window is busy.")
    return None


def _popup(control: Tmux, client: str, args: list[str], title: str, size: str, kind: str, request: dict) -> dict:
    """Show `args` in the Board window of the client's window: a floating pane `size` large, centred.

    A window has one Board window. When its process is of the same `kind` and listening it is told `request`
    (`_reuse`, over `window_link`) and nothing is started. Otherwise the pane keeps its position and size
    and runs `args` instead (`respawn-pane -k`). A new one is created by `new-pane -W`, which returns when the
    pane ends, so it runs as a tmux background job: the click socket and the sidebar stay responsive.
    A person opened it: a failure is recorded and shown on that client, never in a work pane (BOARD-011).
    """
    window = _client_window(control, client)
    if window is None:
        raise ValueError("The tmux client has no window")
    margin = f"{(100 - int(size.rstrip('%'))) // 2}%"
    with _locked(control):
        pane = _window_pane(control, window)
        if pane is not None:
            reused = _reuse(control, pane, kind, {**request, "client": client}, title)
            if reused is not None:
                return reused
        link = str(_private_dir(control) / (uuid.uuid4().hex[:16] + ".win"))
        environment = ["-e", f"PROJECT_BOARD_CLIENT={client}", "-e", f"{window_link.SOCKET_ENV}={link}"]
        command_line = _window_command(control.effective_socket(), args, kind)
        if pane is not None:
            old = _window_options(control, pane)[1]
            if old:                                     # the process that is replaced leaves its socket file behind
                window_link.stop(None, old)
            # the pane's options are the old process's until the new one's script writes its own
            control.command("set-option", "-pu", "-t", pane, PANE_WINDOW_LINK)
            control.command("set-option", "-p", "-t", pane, PANE_WINDOW_KIND, kind)
            control.command("respawn-pane", "-k", "-t", pane, *environment, *command_line)
            control.command("select-pane", "-t", pane, "-T", title)
            return _ok({"client": client, "pane": pane})
        command = ["tmux", "-S", control.effective_socket(), "new-pane", "-W", "-t", window,
                   "-x", size, "-y", size, "-X", margin, "-Y", margin, "-T", title, *environment, *command_line]
        # tmux ends a pane it closes (the border's close button, `kill-window`) with SIGHUP, and `-W` then
        # returns 129. That is a person closing the window, not a failure, so BOARD-011 records none.
        control.run_quiet(shlex.join(command) + '; status=$?; [ "$status" -ne 129 ] || status=0; exit "$status"',
                          "board-popup", client)
        # The next click must find this pane, so the lock is kept until the pane has marked itself.
        deadline = time.monotonic() + WINDOW_START
        while time.monotonic() < deadline:
            pane = _window_pane(control, window)
            if pane is not None:
                break
            time.sleep(0.02)
    return _ok({"client": client, "pane": pane})


def mark_window_ready(link: str, socket=None) -> bool:
    """Tell clicks that this Board window listens on `link` (the process is up and can be told what to show)."""
    pane = os.environ.get("TMUX_PANE")
    if not pane:
        return False
    _control(socket).command("set-option", "-p", "-t", pane, PANE_WINDOW_LINK, link)
    return True


def open_popup(config, project_id: str, decide_id: str | None = None, client: str | None = None, socket=None) -> dict:
    """Open one decision in the Board window of the specified tmux client's window."""
    try:
        control = _control(socket)
        selected = _client(control, client)
        command = [str(LAUNCHER)]
        if config:
            command.extend(("--config", str(config)))
        command.extend(("popup", "--project", project_id))
        if decide_id:
            command.extend(("--decision", decide_id))
        return _popup(control, selected, command, f"Decision · {project_id}", "90%", "decision",
                      {"kind": "decision", "project": project_id, "decision": decide_id})
    except SessionError as error:
        return _session_error(error)
    except (OSError, ValueError) as error:
        return _fail("popup_unavailable", str(error))


def open_cr_popup(config, project_id: str, state: str, client: str | None = None, socket=None) -> dict:
    """Open a project's CR list in the Board window of the specified client's window, leaving the sidebar screen as it is."""
    if state not in model.CR_STATES:
        return _fail("cr_state_invalid", "Choose open, todo or in-progress.")
    try:
        control = _control(socket)
        selected = _client(control, client)
        command = [str(LAUNCHER)]
        if config:
            command.extend(("--config", str(config)))
        command.extend(("cr", "--project", project_id, "--state", state))
        return _popup(control, selected, command, f"CR · {project_id}", "80%", "cr",
                      {"kind": "cr", "project": project_id, "state": state})
    except SessionError as error:
        return _session_error(error)
    except (OSError, ValueError) as error:
        return _fail("popup_unavailable", str(error))


def switch_project(config, project_id: str, client: str | None = None, socket=None) -> dict:
    """Switch only the clicking client to a registered project's current window."""
    try:
        control = _control(socket)
        selected = _client(control, client)
        if model.find_project(config, project_id) is None:
            return _fail("project_not_found", "The project is not registered.")
        session_id = None
        for row in _lines(control, "list-sessions", "-F", "#{session_name}\t#{session_id}"):
            name, separator, value = row.partition("\t")
            if separator and name == project_id:
                session_id = value
                break
        if session_id is None:
            return _fail("project_session_missing", "The project tmux session is unavailable.")
        control.command("switch-client", "-c", selected, "-t", session_id)
        return _ok({"client": selected, "session": project_id})
    except SessionError as error:
        return _session_error(error)
    except (OSError, ValueError) as error:
        return _fail("project_switch_failed", str(error))


def switch_seat(config, project_id: str, seat_index: int, client: str | None = None, socket=None) -> dict:
    """Switch only the clicking client to a verified Worker pane."""
    try:
        control = _control(socket)
        selected = _client(control, client)
        project = model.find_project(config, project_id)
        if project is None:
            return _fail("project_not_found", "The project is not registered.")
        if not isinstance(seat_index, int) or isinstance(seat_index, bool) or not 0 <= seat_index < len(project.seats):
            return _fail("seat_invalid", "The seat does not exist in this project.")
        state = api.project_state(project)
        session = state[str(seat_index)]["session"]
        if session is None:
            return _fail("seat_not_running", "The seat has no Worker session.")
        meta = control.find_by_session(project, session["session_id"])
        if meta is None:
            return _fail("seat_window_missing", "The Worker window is unavailable.")
        pane = meta["pane_id"]
        control.command("switch-client", "-c", selected, "-t", pane)
        return _ok({"client": selected, "pane": pane, "window": meta["window_id"]})
    except SessionError as error:
        return _session_error(error)
    except (OSError, ValueError, KeyError) as error:
        return _fail("seat_switch_failed", str(error))


def route_click(client: str, pane: str, x: int, y: int, socket=None) -> dict:
    """Relay a tmux mouse event to its Board pane without changing focus."""
    try:
        control = _control(socket)
        _client(control, client)
        if type(x) is not int or type(y) is not int or x < 0 or y < 0:
            return _fail("click_invalid", "Mouse coordinates must be nonnegative integers.")
        if _options(control, "-g", ENABLED) != "1":
            return _fail("click_stale", "The Board sidebar is no longer enabled.")
        client_window = _client_window(control, client)
        pane_window = control.command("display-message", "-p", "-t", pane, "#{window_id}")
        if client_window != pane_window or _options(control, "-w", "-t", pane_window, WINDOW_PANE) != pane:
            return _fail("click_stale", "The client no longer sees this Board pane.")
        if _options(control, "-p", "-t", pane, PANE_MARK) != "1":
            return _fail("click_not_board", "The mouse target is not a Board pane.")
        click_path = _options(control, "-p", "-t", pane, PANE_SOCKET)
        if not click_path:
            return _fail("click_unavailable", "The Board click socket is not ready.")
        path = Path(click_path)
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            return _fail("click_unavailable", "The Board click socket is not private.")
        payload = json.dumps({"client": client, "x": x, "y": y}, ensure_ascii=False).encode("utf-8") + b"\n"
        with unix_socket.socket(unix_socket.AF_UNIX, unix_socket.SOCK_STREAM) as connection:
            connection.settimeout(CLICK_TIMEOUT)
            connection.connect(str(path))
            connection.sendall(payload)
            response = b""
            while b"\n" not in response and len(response) < 65536:
                block = connection.recv(4096)
                if not block:
                    break
                response += block
        return json.loads(response.split(b"\n", 1)[0])
    except SessionError as error:
        return _session_error(error)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return _fail("click_unavailable", str(error))
