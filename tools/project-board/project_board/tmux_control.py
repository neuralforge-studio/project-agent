"""tmux placement and client-directed actions for the Project Board.

The server owns one global toggle. A Board pane is created in a window when an attached
client first watches it, and stays until the toggle is turned off, the window's managed pane
dies, or the window closes. Multiple clients watching the same window share that pane; a
mouse binding sends each click's client and pane-relative coordinates over a local
socket so actions still target the client that clicked. The sidebar is the `project-board-sidebar` binary
(tools/project-board/rust); it runs the actions below through `project-board` subcommands.

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

from . import model, release, window_link
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
PANE_WINDOW = "@project_board_window"
PANE_WINDOW_KIND = "@project_board_window_kind"        # `cr`, `decision` or `cron`: what the pane's process was started as
PANE_WINDOW_LINK = "@project_board_window_link"        # the socket it listens on, set by the process once it does
PANE_WINDOW_RELEASE = "@project_board_window_release"  # the release (`release.name_of`) of the code that started it
WINDOW_SEEN = "@project_board_seen"
SIDEBAR_WIDTH = 25
# The most Board panes kept at once. One Board process holds about 13 MB (RSS of the Rust sidebar with 10 projects; the Textual one held 50 MB) and reads
# the project files only while its window is shown, so the bound is memory, not CPU: 8 panes are
# about 100 MB at most. The windows a user moves among in a working session (a project's Leader and
# Workers) fit; a pane over the bound is removed from the window that no client showed for longest.
MAX_KEPT = 8
CLICK_TIMEOUT = 2
# How long opening a Board window waits for its pane to mark itself; a failed start is reported by its job.
WINDOW_START = 3
TOOL = Path(__file__).resolve().parents[1]
LAUNCHER = TOOL / "bin" / "project-board"
RELEASE = release.name_of(TOOL)                         # '' in a development checkout
SIDEBAR_NAME = "project-board-sidebar"
# How long a click waits for a Board window of the same kind that is still starting, before it starts the window again.
WINDOW_REUSE_WAIT = 20
STARTING = "Board 창을 시작하는 중…"


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


def _signalable(pid: int) -> bool:
    """Whether `pid` is a live process this user could signal (the ones `ps` is asked about)."""
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False
    return True


def _process_rows(pids) -> dict[int, tuple[str, str]] | None:
    """`ps` of every pid in one process: pid -> (`etime`, command name). None when ps cannot tell."""
    try:
        result = subprocess.run(["ps", "-o", "pid=,etime=,comm=", "-p", ",".join(map(str, pids))],
                                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode not in (0, 1):  # 1: ps found none of the processes
        return None
    rows = {}
    for line in result.stdout.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[0].isdigit():
            rows[int(fields[0])] = (fields[1], fields[2])
    return rows


_ASK = object()


def _is_tmux_server_of(pid: int, created: float, rows=_ASK) -> bool:
    """Whether `pid` is a live tmux process old enough to have created a directory last changed at `created`.

    A directory name carries only a pid, and the OS reuses pids. A live pid therefore proves
    nothing by itself, so two things must both hold: the process is tmux (`ps` command name, which
    is `tmux: server` on Linux and the executable path on macOS), and it started no later than the
    directory's last change. The directory is made by the server's own Board commands, so a process
    that started after that is a different one that inherited the pid.

    `rows` is `_process_rows` of the pids of one sweep (None when ps could not tell), so that a sweep
    starts one `ps` for all its directories; without it this pid is asked for alone.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False  # a process of another user is never this user's tmux server
    except OSError:
        return True  # cannot tell: leave the directory
    if rows is _ASK:
        rows = _process_rows([pid])
    if rows is None:
        return True
    row = rows.get(pid)
    if row is None:
        return False  # ps does not know the process (it ended after the check above)
    elapsed = _elapsed_seconds(row[0])
    if elapsed is None:
        return True
    if not os.path.basename(row[1].strip()).startswith("tmux"):
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
    candidates = []
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
        except OSError:
            continue  # already removed by a concurrent sweep: leave it
        candidates.append((directory, int(match.group(2)), info.st_mtime))
    alive = [pid for _, pid, _ in candidates if _signalable(pid)]
    rows = _process_rows(alive) if alive else {}  # None: ps could not tell, every live pid is left
    for directory, pid, created in candidates:
        try:
            if _is_tmux_server_of(pid, created, rows):
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
    """Hold the Board lock of this tmux server; yields the server's private runtime directory."""
    directory = _private_dir(control)
    path = directory / "control.lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("Project Board's tmux lock is not private")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield directory
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
    window, the time a client last showed it, the Board mark and width of each of its panes, the window's
    width, layout and active pane, and the layout saved before its Board pane was added."""

    def __init__(self):
        self.panes: dict[str, bool] = {}
        self.board = ""
        self.managed = ""
        self.seen = ""
        self.marks: dict[str, str] = {}
        self.widths: dict[str, int] = {}
        self.width = 0
        self.layout = ""
        self.restore = ""
        self.active = ""


class _Snapshot:
    """The server state `_reconcile` and `_evict` judge, read by one tmux process.

    A format reads an option through the pane, the window, the session and the global levels, where
    `show-options -w` reads the window alone. The Board and agent-session write `@project_board_pane`,
    `@project_board_seen`, `@project_board_restore` and the managed-pane option only on windows, and
    `@project_board_managed` only on panes, never above, so the values are the ones the per-window reads gave.
    The widths, layout and active pane are what `display-message -t` gave for each window and pane: the
    changes of `_reconcile` need none of them read again (BOARD-022).
    """

    def __init__(self, enabled: str, width: str, config: str, visible: list[str], windows: dict[str, _Window],
                 clients: list[str]):
        self.enabled = enabled == "1"
        self.width = width
        self.config = config or None
        self.visible = visible
        self.windows = windows
        self.clients = clients


def _snapshot(control: Tmux) -> _Snapshot:
    """Read the global Board options, the windows the clients show, and every window and pane at once."""
    rows = _lines(
        control,
        "display-message", "-p", f"G\t#{{{ENABLED}}}\t#{{{WIDTH}}}\t#{{{CONFIG}}}",
        ";", "list-clients", "-F", "C\t#{window_id}\t#{client_name}",
        ";", "list-panes", "-a", "-F",
        f"P\t#{{window_id}}\t#{{pane_id}}\t#{{pane_dead}}\t#{{{WINDOW_PANE}}}\t#{{{PANE_ID_OPTION}}}"
        f"\t#{{{WINDOW_SEEN}}}\t#{{{PANE_MARK}}}\t#{{window_width}}\t#{{pane_width}}\t#{{pane_active}}"
        f"\t#{{{WINDOW_RESTORE}}}\t#{{window_layout}}")
    enabled = width = config = ""
    visible, windows, clients = [], {}, []
    for row in rows:
        kind, _, rest = row.partition("\t")
        if kind == "G":
            enabled, width, config = rest.split("\t", 2)
        elif kind == "C":
            window, _, client = rest.partition("\t")
            visible.append(window)
            clients.append(client)
        elif kind == "P":
            window, pane, dead, board, managed, seen, mark, window_width, pane_width, active, restore, layout = \
                rest.split("\t", 11)
            record = windows.setdefault(window, _Window())
            if not record.panes:
                record.board, record.managed, record.seen = board, managed, seen
                record.width = int(window_width) if window_width.isdecimal() else 0
                record.restore, record.layout = restore, layout
            record.panes[pane] = dead == "1"
            record.marks[pane] = mark
            record.widths[pane] = int(pane_width) if pane_width.isdecimal() else 0
            if active == "1":
                record.active = pane
    return _Snapshot(enabled, width, config, visible, windows, clients)


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


def _layout_with_floating(current: str, layout: str) -> tuple[str, bool]:
    """`layout` (saved before the sidebar was added) with the floating panes of `current` (the window's
    `#{window_layout}` of now), and whether one of them is the active pane.

    `select-layout` needs a layout that names every pane of the window. A saved layout names the panes
    of its time, so a floating pane (the Board's CR or decision window) opened or closed since would
    make it fail.
    """
    try:
        current = _floating(json.loads(current)["L"])
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


def _restore_commands(window: str, saved: str, current_layout: str, panes) -> list[tuple]:
    """The tmux commands that put `window` back as it was before its Board pane (saved in `saved`).

    `panes` are the panes the window has once the Board pane is gone."""
    if not saved:
        return []
    saved = json.loads(saved)
    layout, floating_active = _layout_with_floating(current_layout, saved["layout"])
    commands = [("select-layout", "-t", window, layout)]
    if not floating_active and saved["focus"] in panes:
        commands.append(("select-pane", "-t", saved["focus"]))
    return commands


def _chain(commands) -> list[str]:
    """One tmux argument vector for `commands`: the server runs them in order, in one process."""
    arguments: list[str] = []
    for command in commands:
        if arguments:
            arguments.append(";")
        arguments.extend(command)
    return arguments


def _restore(control: Tmux, window: str) -> None:
    raw = _options(control, "-w", "-t", window, WINDOW_RESTORE)
    commands = _restore_commands(window, raw, control.command("display-message", "-p", "-t", window,
                                                                "#{window_layout}") if raw else "",
                                 _panes(control, window) if raw else ())
    if commands:
        control.command(*_chain(commands))


def _remove(control: Tmux, window: str, pane: str, record: _Window, before=(), after=()) -> None:
    """Kill a Board pane and put its window back as it was, in one tmux process.

    `record` is what a snapshot said of the window while the pane was in it. The options are cleared
    before the layout is restored, so a restore that fails still leaves the window without a Board pane.
    `before` and `after` are further commands for the same process (a progress message).
    """
    commands = [*before, ("kill-pane", "-t", pane),
                ("set-option", "-wu", "-t", window, WINDOW_PANE),
                ("set-option", "-wu", "-t", window, WINDOW_RESTORE),
                *_restore_commands(window, record.restore, record.layout,
                                   [other for other in record.panes if other != pane]),
                *after]
    try:
        control.command(*_chain(commands))
    except SessionError:
        # Killing a sole remaining pane can close its window as well.
        if window in _lines(control, "list-windows", "-a", "-F", "#{window_id}"):
            raise


def sidebar_binary() -> Path:
    """The sidebar binary: `PROJECT_BOARD_SIDEBAR_BIN`, the one the installer put next to the launcher, or the
    one `cargo build --release` made in a checkout."""
    candidates = []
    if os.environ.get("PROJECT_BOARD_SIDEBAR_BIN"):
        candidates.append(Path(os.environ["PROJECT_BOARD_SIDEBAR_BIN"]))
    candidates += [TOOL / "bin" / SIDEBAR_NAME, TOOL / "rust" / "target" / "release" / SIDEBAR_NAME]
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    raise ValueError(f"{SIDEBAR_NAME} is not built (run cargo build --release in tools/project-board/rust)")


def _sidebar_command(config: str | None) -> list[str]:
    command = [str(sidebar_binary())]
    if config:
        command.extend(("--config", config))
    return command


def _create(control: Tmux, window: str, config: str | None, width: int, directory: Path, record: _Window,
            messages=()) -> str:
    click_path = directory / (uuid.uuid4().hex[:16] + ".sock")
    layout, focus = record.layout, record.active
    command = ["split-window", "-d", "-f", "-h", "-b", "-l", str(width),
               "-P", "-F", "#{pane_id}", "-t", window,
               "-e", f"PROJECT_BOARD_CLICK_SOCKET={click_path}", *_sidebar_command(config)]
    pane = control.command(*command).strip()
    if not pane.startswith("%"):
        raise ValueError("tmux did not return the Board pane handle")
    try:
        control.command(*_chain([
            ("set-option", "-w", "-t", window, WINDOW_RESTORE, json.dumps({"layout": layout, "focus": focus})),
            ("set-option", "-p", "-t", pane, PANE_MARK, "1"),
            ("set-option", "-p", "-t", pane, PANE_SOCKET, str(click_path)),
            ("set-option", "-w", "-t", window, WINDOW_PANE, pane),
            ("set-option", "-w", "-t", window, WINDOW_SEEN, str(int(time.time()))), *messages]))
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


def _evict(control: Tmux, shown_kept: list[str], created: list[str], failures: list) -> list[str]:
    """Remove Board panes beyond MAX_KEPT, from the windows that were shown longest ago.

    A window a client shows now is never removed. `@project_board_seen` is the time a client last
    showed the window (project_board_visibility.sh writes it; `_create` starts a new pane at now).
    """
    shown = set(shown_kept) | set(created)
    boards = []
    for window, record in _snapshot(control).windows.items():
        if record.board:
            boards.append((window, record.board, int(record.seen) if record.seen.isdecimal() else 0, record))
    evicted = []
    excess = len(boards) - MAX_KEPT
    for window, pane, _seen, record in sorted((b for b in boards if b[0] not in shown), key=lambda b: b[2]):
        if excess <= 0:
            break
        try:
            _remove(control, window, pane, record)
            evicted.append(window)
            excess -= 1
        except (SessionError, OSError, ValueError) as error:
            failures.append({"window": window, "reason": str(error)})
    return evicted


# A person waits for the key to take effect: past this many seconds the Board says how far it is (BOARD-022).
PROGRESS_AFTER = 0.5
PROGRESS_SHOWN_MS = 3000


class _Progress:
    """The progress message of a toggle, once it has taken longer than PROGRESS_AFTER.

    It is `display-message -c`, which covers no pane and leaves the user's status settings alone. The key
    does not name its client, so every attached client is told, as a failed key is (project_agent_run.sh).
    The message goes into the tmux process of the step it reports, so showing progress starts none.
    """

    def __init__(self, clients: list[str], verb: str, total: int, started: float):
        self._clients, self._verb, self._total, self._started = clients, verb, total, started
        self._done = 0

    def _messages(self, text: str, milliseconds: int) -> list[tuple]:
        return [("display-message", "-c", client, "-d", str(milliseconds), text) for client in self._clients]

    def step(self) -> tuple[list[tuple], list[tuple]]:
        """(commands before, commands after) of the next step: where it is now, or that all is done."""
        self._done += 1
        if time.monotonic() - self._started < PROGRESS_AFTER:
            return [], []
        if self._done == self._total:
            return [], self._messages(f"Board {self._verb} 중 {self._done}/{self._total} 완료", 1000)
        return self._messages(f"Board {self._verb} 중 {self._done}/{self._total}", PROGRESS_SHOWN_MS), []


def _reconcile(control: Tmux, directory: Path, snapshot: _Snapshot | None = None,
               started: float | None = None) -> dict:
    """Match the Board panes to the windows the clients show, from one read of the server.

    `snapshot` is a read made earlier under the same lock, with the Board option already changed in it;
    `started` (a `time.monotonic()`) is when the person's key began, which turns on the progress message.
    """
    if snapshot is None:
        snapshot = _snapshot(control)
    enabled, config = snapshot.enabled, snapshot.config
    visible = set(snapshot.visible) if enabled else set()
    windows = snapshot.windows
    created, removed, failures = [], [], []
    to_remove, to_create, to_keep = [], [], []
    held = set()
    for window, record in windows.items():
        try:
            panes = record.panes
            board = _board_pane(control, window, record)
            usable = enabled and not _managed_pane_dead(record)
            if board:
                held.add(window)
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
        saved_width = str(width)
    progress = None
    if started is not None and (to_remove or to_create):
        progress = _Progress(snapshot.clients, "켜는" if enabled else "끄는", len(to_remove) + len(to_create), started)
    # `after-resize-pane` writes the global width from the pane it resized: only a resize-pane here
    # can leave the option other than what was read.
    resized = False
    board_count = len(to_remove) + len(to_keep)
    for window, board in to_remove:
        record = windows[window]
        before, after = progress.step() if progress else ((), ())
        try:
            pane_width = record.widths[board]
            capture_width = False
            if board_count == 1 and pane_width != width and record.width > width + 1:
                control.command("resize-pane", "-t", board, "-x", str(width))
                resized = True
                fitted_width = int(control.command("display-message", "-p", "-t", board,
                                                   "#{pane_width}"))
                capture_width = fitted_width == width
                control.command("set-option", "-g", WIDTH, str(width))
            _remove(control, window, board, record, before, after)
            removed.append(window)
            held.discard(window)
            if capture_width:
                width = pane_width
                control.command("set-option", "-g", WIDTH, str(width))
        except (SessionError, OSError, ValueError) as error:
            failures.append({"window": window, "reason": str(error)})
    for window, board in to_keep:
        record = windows[window]
        try:
            if record.widths[board] != width and record.width > width + 1:
                control.command("resize-pane", "-t", board, "-x", str(width))
                resized = True
        except (SessionError, OSError, ValueError) as error:
            failures.append({"window": window, "reason": str(error)})
    for window in to_create:
        before, after = progress.step() if progress else ((), ())
        try:
            _create(control, window, config, width, directory, windows[window], [*before, *after])
            created.append(window)
        except (SessionError, OSError, ValueError) as error:
            failures.append({"window": window, "reason": str(error)})
    # Only a window kept beyond the bound has to be found out, which takes a second read of the server.
    if len(held) + len(created) > MAX_KEPT:
        for window in _evict(control, [w for w, _ in to_keep], created, failures):
            removed.append(window)
    if (to_remove or to_keep or to_create) and (resized or saved_width != str(width)):
        control.command("set-option", "-g", WIDTH, str(width))
    return {"enabled": enabled, "visible_windows": sorted(visible),
            "created": created, "removed": removed, "failures": failures}


def reconcile(config=None, socket=None) -> dict:
    """Match Board panes to windows currently watched by attached clients."""
    try:
        control = _control(socket)
        with _locked(control) as directory:
            if config is not None:
                control.command("set-option", "-g", CONFIG, str(Path(config).expanduser().resolve()))
            data = _reconcile(control, directory)
        return _ok(data) if not data["failures"] else _fail("sidebar_partial", "Some tmux windows could not be updated.", data)
    except SessionError as error:
        return _session_error(error)
    except (OSError, ValueError) as error:
        return _fail("sidebar_unavailable", str(error))


def toggle_sidebar(config=None, client=None, socket=None) -> dict:
    """Toggle the server-wide Board, then update only visible windows.

    The state is read once, with the server, and the changed options are written in one tmux process; the
    reconcile then works from that read (BOARD-022).
    """
    started = time.monotonic()
    try:
        control = _control(socket)
        with _locked(control) as directory:
            if client is not None:
                _client(control, client)
            snapshot = _snapshot(control)
            snapshot.enabled = not snapshot.enabled
            writes = [("set-option", "-g", ENABLED, "1" if snapshot.enabled else "0")]
            if config is not None:
                snapshot.config = str(Path(config).expanduser().resolve())
                writes.append(("set-option", "-g", CONFIG, snapshot.config))
            control.command(*_chain(writes))
            data = _reconcile(control, directory, snapshot, started)
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


def _window_command(tmux: str, socket: str, args: list[str], kind: str) -> list[str]:
    """The command of a Board window: it marks its own pane, then becomes `args`.

    The mark is made by the pane itself because `new-pane -W` returns only when the pane ends, so
    nothing can mark it from outside after it starts. `remain-on-exit` of the pane is off: a managed
    window has it on (agent-session), which would leave a closed Board window behind as a dead pane.
    The pane says what it is starting (`STARTING`) at once: the Python process behind it needs seconds on a
    loaded host and the pane is empty until its screen is drawn (BOARD-025).
    """
    pane = '"$TMUX_PANE"'
    script = (f"{shlex.quote(tmux)} -S {shlex.quote(socket)} set-option -p -t {pane} remain-on-exit off \\; "
              f"set-option -p -t {pane} {PANE_WINDOW} 1 \\; "
              f"set-option -p -t {pane} {PANE_WINDOW_KIND} {kind} \\; "
              f"set-option -p -t {pane} {PANE_WINDOW_RELEASE} {shlex.quote(RELEASE)} \\; "
              f"set-option -pu -t {pane} {PANE_WINDOW_LINK}; "
              f"printf '%s\\n' {shlex.quote(STARTING)}; exec \"$@\"")
    return ["sh", "-c", script, "sh", *args]


def _window_options(control: Tmux, pane: str) -> tuple[str, str, str]:
    """The kind of the pane's window process, the release that started it and the socket it listens on ('' while
    it is starting)."""
    row = control.command("display-message", "-p", "-t", pane,
                          f"#{{{PANE_WINDOW_KIND}}}\t#{{{PANE_WINDOW_RELEASE}}}\t#{{{PANE_WINDOW_LINK}}}")
    kind, _, rest = row.partition("\t")
    started_by, _, link = rest.partition("\t")
    return kind, started_by, link


def _reuse(control: Tmux, pane: str, kind: str, request: dict, title: str) -> dict | None:
    """Tell the process of the window in `pane` what to show; None when the pane must be started again.

    Only a window of the same `kind` is reused: its process is the one that can show that kind of item, and
    it keeps what it has read, so the new item appears without starting Python and Textual again. A window
    that another release started (`RELEASE`: the release of this code, which is the one that starts the
    replacement) is not reused: its process still runs the code it imported. A process that is still starting
    is waited for (`WINDOW_REUSE_WAIT`); one that does not answer is replaced.
    """
    current, started_by, link = _window_options(control, pane)
    if current != kind or started_by != RELEASE:
        return None
    deadline = time.monotonic() + WINDOW_REUSE_WAIT
    while not link and time.monotonic() < deadline:
        time.sleep(0.05)
        current, started_by, link = _window_options(control, pane)
    if not link or current != kind or started_by != RELEASE:
        return None
    try:
        result = window_link.send(link, request)
    except OSError:
        return None
    if result.get("ok") is True:                      # the protocol says `{"ok": true}`; the Rust client reads it the same way
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
        command_line = _window_command(control.program(), control.effective_socket(), args, kind)
        if pane is not None:
            old = _window_options(control, pane)[2]
            if old:                                     # the process that is replaced leaves its socket file behind
                window_link.stop(None, old)
            # the pane's options are the old process's until the new one's script writes its own
            control.command("set-option", "-pu", "-t", pane, PANE_WINDOW_LINK)
            control.command("set-option", "-p", "-t", pane, PANE_WINDOW_KIND, kind)
            control.command("set-option", "-p", "-t", pane, PANE_WINDOW_RELEASE, RELEASE)
            control.command("respawn-pane", "-k", "-t", pane, *environment, *command_line)
            control.command("select-pane", "-t", pane, "-T", title)
            return _ok({"client": client, "pane": pane})
        command = [control.program(), "-S", control.effective_socket(), "new-pane", "-W", "-t", window,
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


def open_cron_popup(config, project_id: str, client: str | None = None, socket=None) -> dict:
    """Open a project's cron jobs in the Board window of the specified client's window (BOARD-027)."""
    try:
        control = _control(socket)
        selected = _client(control, client)
        command = [str(LAUNCHER)]
        if config:
            command.extend(("--config", str(config)))
        command.extend(("cron", "--project", project_id))
        return _popup(control, selected, command, f"Cron · {project_id}", "80%", "cron",
                      {"kind": "cron", "project": project_id})
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
