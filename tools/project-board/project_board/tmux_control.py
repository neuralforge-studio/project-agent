"""tmux placement and client-directed actions for the Project Board TUI.

The server owns one global toggle. A Board pane is created in a window when an attached
client first watches it, and stays until the toggle is turned off, the window's managed pane
dies, or the window closes. Multiple clients watching the same window share that pane; a
mouse binding sends each click's client and pane-relative coordinates over a local
socket so actions still target the client that clicked.
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

from . import model
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
SIDEBAR_WIDTH = 25
CLICK_TIMEOUT = 2
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
    """Read the project folds shared by every Board pane in this tmux server."""
    control = _control(socket)
    with _locked(control):
        return _expanded(control)


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


def _managed_pane_dead(control: Tmux, window: str, panes: dict[str, bool]) -> bool:
    raw = _options(control, "-w", "-t", window, PANE_ID_OPTION)
    if not raw:
        return False
    try:
        pane = json.loads(raw)
    except ValueError:
        return False
    return isinstance(pane, str) and panes.get(pane, False)


def _board_pane(control: Tmux, window: str, panes: dict[str, bool]) -> str | None:
    pane = _options(control, "-w", "-t", window, WINDOW_PANE)
    if not pane:
        return None
    if pane in panes and _options(control, "-p", "-t", pane, PANE_MARK) == "1":
        return pane
    try:
        if pane not in panes:
            _restore(control, window)
    finally:
        control.command("set-option", "-wu", "-t", window, WINDOW_PANE)
        control.command("set-option", "-wu", "-t", window, WINDOW_RESTORE)
    return None


def _restore(control: Tmux, window: str) -> None:
    raw = _options(control, "-w", "-t", window, WINDOW_RESTORE)
    if not raw:
        return
    saved = json.loads(raw)
    control.command("select-layout", "-t", window, saved["layout"])
    if saved["focus"] in _panes(control, window):
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


def _reconcile(control: Tmux) -> dict:
    enabled = _options(control, "-g", ENABLED) == "1"
    config = _options(control, "-g", CONFIG) or None
    visible = set(_lines(control, "list-clients", "-F", "#{window_id}")) if enabled else set()
    windows = dict.fromkeys(_lines(control, "list-windows", "-a", "-F", "#{window_id}"))
    created, removed, failures = [], [], []
    to_remove, to_create, to_keep = [], [], []
    for window in windows:
        try:
            panes = _panes(control, window)
            board = _board_pane(control, window, panes)
            usable = enabled and not _managed_pane_dead(control, window, panes)
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

    saved_width = _options(control, "-g", WIDTH)
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
    if to_remove or to_keep or to_create:
        control.command("set-option", "-g", WIDTH, str(width))
    return {"enabled": enabled, "visible_windows": sorted(visible),
            "created": created, "removed": removed, "failures": failures}


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


def _popup(control: Tmux, client: str, args: list[str], title: str, size: str) -> dict:
    # display-popup -E waits until the popup closes. Run it as a tmux background
    # job so the click socket and the sidebar remain responsive while it is open.
    command = ["tmux", "-S", control.effective_socket(), "display-popup", "-E", "-c", client,
               "-w", size, "-h", size, "-T", title, "-e", f"PROJECT_BOARD_CLIENT={client}", *args]
    control.command("run-shell", "-b", shlex.join(command))
    return _ok({"client": client})


def open_popup(config, project_id: str, decide_id: str | None = None, client: str | None = None, socket=None) -> dict:
    """Open one decision in a large popup on the specified tmux client."""
    try:
        control = _control(socket)
        selected = _client(control, client)
        command = [str(LAUNCHER)]
        if config:
            command.extend(("--config", str(config)))
        command.extend(("popup", "--project", project_id))
        if decide_id:
            command.extend(("--decision", decide_id))
        return _popup(control, selected, command, f"Decision · {project_id}", "90%")
    except SessionError as error:
        return _session_error(error)
    except (OSError, ValueError) as error:
        return _fail("popup_unavailable", str(error))


def open_cr_popup(config, project_id: str, state: str, client: str | None = None, socket=None) -> dict:
    """Open a project's CR list without changing the shared sidebar screen."""
    if state not in model.CR_STATES:
        return _fail("cr_state_invalid", "Choose open, todo or in-progress.")
    try:
        control = _control(socket)
        selected = _client(control, client)
        command = [str(LAUNCHER)]
        if config:
            command.extend(("--config", str(config)))
        command.extend(("cr", "--project", project_id, "--state", state))
        return _popup(control, selected, command, f"CR · {project_id}", "80%")
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
