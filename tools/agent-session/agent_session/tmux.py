"""Control only windows with an exact project, run, and process identity."""

from collections import namedtuple
import json
import os
from pathlib import Path
import re
import shlex
import signal
import stat
import subprocess
import time

from .config import RemoteSeat
from .errors import SessionError
from . import process, tmux_program
from .tmux_program import COMPANY_TMUX


_PREFIX = "@agent_session_"
PANE_ID_OPTION = _PREFIX + "pane_id"    # window option naming the managed pane; project-agent.conf repeats it
EXIT_HOOK = "pane-died[agent-session]"  # the server-wide hook element that starts the wrap-up of a run that ended itself
LAST_ERROR_OPTION = "@project_agent_last_error"   # the one record of a failed tmux job (install contract 5.3, project_agent_run.sh)
_HOOK_WORD = re.compile(r"[A-Za-z0-9_./:@%+=,-]+")  # what a hook command may carry as a path: no quote, space, or `$`
# The minimum tmux version has one definition: `@project_agent_tmux_min` in the integration file (install
# contract 3.2). The product tree keeps that file at `integrations/tmux/` beside `tools/`; a tree without it
# (the remote runtime's bundle) has no minimum to check.
_INTEGRATION_FILE = Path(__file__).resolve().parents[3] / "integrations" / "tmux" / "project-agent.conf"
_MINIMUM = re.compile(r"^set-option -g @project_agent_tmux_min '([^']+)'$", re.MULTILINE)
_VERSION = re.compile(r"(?:next-)?(\d+)\.(\d+)")      # `3.8`, `3.6a`, `next-3.9`; anything else counts as too old


def minimum_version():
    """The minimum tmux version the product requires, or None when the integration file is not in this tree."""
    try:
        found = _MINIMUM.search(_INTEGRATION_FILE.read_text(encoding="utf-8"))
    except OSError:
        return None
    return found.group(1) if found else None


def quiet_shell(job, name, socket, quote='"', notify_client=None):
    """Shell text for one `run-shell` job that leaves nothing in the pane the user is working in (BOARD-011).

    tmux shows the output and a nonzero exit status of a `run-shell` job in the then active pane, which is the
    user's work pane. The text runs `job` with its output discarded and always exits 0. A failure is written
    to the server option `LAST_ERROR_OPTION` as one line, `<date> <time> <name> failed (exit N)`, replaced by
    the next failure; with `notify_client` (an action of a person) that client also gets a message for 5
    seconds, which covers no pane. This is the rule of `integrations/tmux/project_agent_run.sh` (`hook` and
    `key` modes) for the jobs of the tools, which cannot call that script: the remote runtime's bundle does
    not carry it. `socket` and `notify_client` are shell words. `quote` is the double quote of the text the
    message is in; a hook that nests this text in tmux's own quotes passes `\\"`. The text has no `'`."""
    message = f"{quote}$(date +%F) $(date +%T) {name} failed (exit $*){quote}"
    tmux = tmux_program.program()
    if _HOOK_WORD.fullmatch(tmux) is None:      # a hook is only written when it can carry the word (`install_exit_hook`)
        tmux = shlex.quote(tmux)
    record = f"set -- $?; {tmux} -S {socket} set-option -g {LAST_ERROR_OPTION} {message} >/dev/null 2>&1"
    if notify_client is not None:
        notice = f"{quote}project-agent: {name} failed (tmux show-options -gv {LAST_ERROR_OPTION}){quote}"
        record += f"; {tmux} -S {socket} display-message -c {notify_client} -d 5000 {notice} >/dev/null 2>&1"
    return f"( {job} ) >/dev/null 2>&1 || {{ {record}; }}; exit 0"


def _version_number(text):
    found = _VERSION.match(text or "")
    return int(found.group(1)) * 1000 + int(found.group(2)) if found else 0


_IDENTITY = ("base", "target", "job_id", "run_id", "project_id", "window_id", "pane_id",
             "server_pid", "server_started", "server_birth", "socket_path")


def _safe_text(value, what):
    if not isinstance(value, str) or not value or any(char in value for char in "\x00\n\r\t"):
        raise SessionError("tmux_input", f"A nonempty {what} without control characters is required.", 2)
    return value


def _session(value):
    value = _safe_text(value, "tmux session name")
    if any(char in value for char in ":."):
        raise SessionError("tmux_input", "Tmux session names must not contain ':' or '.'.", 2)
    return value


def _json_value(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


# What a run adds to its window after the window is created, with the value that reads like a window
# that never had it. Metadata is never unset (read_meta), so a window handed to a new run gets these.
_RUN_VALUES = {
    "cli_pid": None, "cli_birth": None, "process_group": None, "background_pids": [],
    "last_background_clear": None, "hook_observations": {}, "controller_pid": None,
    "controller_birth": None, "control_pending": False, "control_operation": None,
    "session_id": None, "message_to": None, "start_error": None, "launch_file": None, "provider_name": None,
    "resume": False, "expected_session_id": None, "handoff_file": None, "leader_request": None,
    "remote_seat": None, "remote_native": None, "upstream": None, "upstream_bin": None,
    "moved_to_background": None, "last_sent": None, "last_received": None, "watch": None,
    "release_pending": None,
}
# What a run's waiting pane adds to the metadata the caller gives (`_waiting_values`).
_WAITING_KEYS = frozenset({"cwd", "provider_launch_attempted", "registered", "ready", "publishing", "stopping",
                           "placeholder_pid", "placeholder_birth", "placeholder_process_group"})
_VALUES_MARK = "agent-session-values"
_SEAT_TARGET = re.compile(r"seat-(0|[1-9][0-9]*)")
# The names of the window options of a managed run that a read asks for in the same tmux sequence that lists
# them. Only a guess that the listing checks: a name the listing shows and the guess lacks is read again and
# remembered, so a read is one tmux process once the names are known, and never misses an option.
_META_KEYS = frozenset(_IDENTITY) | frozenset(_RUN_VALUES) | _WAITING_KEYS
_ARGV_LIMIT = 12000      # tmux refuses a command line of 16 KB ("command too long"); a longer batch goes in by stdin
_WINDOW_ID = re.compile(r"@[0-9]+")
_WINDOW_GONE = re.compile(r"(?:no such window|can't find window): (@[0-9]+)$")


def _meta_keys(lines):
    keys = [line.split(" ", 1)[0][len(_PREFIX):] for line in lines if line.startswith(_PREFIX)]
    if any(re.fullmatch(r"[a-z][a-z0-9_]*", key) is None for key in keys):
        raise SessionError("tmux_metadata_invalid", "The managed window has invalid runtime metadata.")
    return keys


def _absent(stderr):
    return any(text in stderr for text in ("no server running", "No such file or directory", "can't find session"))


_PANE_FIELDS = ("window_id", "pane_id", "pane_pid", "pane_dead", "pane_dead_status", "pane_dead_signal")
_ID_MARK, _SESSION_MARK, _WINDOW_MARK, _PANE_MARK = ("agent-session-" + word for word in ("server", "session", "window", "pane"))
_Session = namedtuple("_Session", "handle owner pointers")      # a session's handle, owner marker text, pointer texts


def _identity_from(raw):
    """The server identity from `pid<TAB>start_time<TAB>socket_path`; the one owner of its checks."""
    parts = (raw or "").split("\t")
    if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit() or not parts[2]:
        raise SessionError("tmux_unknown", "Tmux did not return a complete server identity.", 4)
    pid = int(parts[0])
    fingerprint = process.birth(pid)
    if fingerprint is None:
        raise SessionError("tmux_unknown", "The tmux server process identity is unavailable.", 4)
    socket_path = Path(parts[2]).resolve()
    try:
        info = socket_path.stat()
    except OSError as exc:
        raise SessionError("tmux_unknown", "The selected tmux socket is unavailable.", 4) from exc
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise SessionError("tmux_owner_mismatch", "The selected tmux socket is not owned by the current user.")
    return {"server_pid": pid, "server_started": parts[1], "server_birth": fingerprint,
            "socket_path": str(socket_path)}


def _pane_row(raw, pane_id):
    """The pane's fields from `_PANE_FIELDS` joined by tabs; the one owner of their checks."""
    parts = raw.split("\t")
    if (len(parts) != len(_PANE_FIELDS) or parts[3] not in ("0", "1")
            or not (parts[2].isdigit() or (parts[2] == "" and parts[3] == "1"))):
        raise SessionError("tmux_unknown", "The managed pane observation is incomplete.", 4,
                           {"pane": pane_id, "raw": raw, "field_count": len(parts)})
    row = dict(zip(_PANE_FIELDS, parts))
    row["pane_pid"] = int(row["pane_pid"]) if row["pane_pid"] else None
    row["pane_dead"] = row["pane_dead"] == "1"
    row["pane_dead_status"] = int(row["pane_dead_status"]) if row["pane_dead_status"].isdigit() else None
    row["pane_dead_signal"] = row["pane_dead_signal"] or None
    return row


def _pointer_field(raw, key):
    """A text field of a current pointer text, or None when the text is not a pointer or lacks the field."""
    try:
        pointer = json.loads(raw)
    except ValueError:
        return None
    value = pointer.get(key) if isinstance(pointer, dict) else None
    return value if isinstance(value, str) and value else None


def _pointer_window(raw):
    """The window a current pointer text names, or None when the text is not a pointer."""
    return _pointer_field(raw, "window_id")


class ServerView:
    """One read of a tmux server: what a single tmux process (two for the window options) told about it.

    It holds the server identity, every session with its handle, owner marker and the current pointers that
    were asked for, and, when asked, every window and pane. The checks of the product (owner, identity,
    pointer against window) run on it with the same functions as on a live server: `Tmux.get_current` is
    `ServerView.current` of a view of one project. A consumer that asks about many slots takes one view and
    asks it each time, so the tmux processes do not grow with the slots.

    A view is a snapshot. It reads nothing again and never writes; make a new one to see a change."""

    def __init__(self, control, identity, sessions, windows, panes, targets):
        self._control = control
        self._identity_raw = identity
        self.sessions = sessions        # session name -> _Session
        self.windows = windows          # window id -> session handle, or None when windows were not read
        self.panes = panes              # pane id -> its `_PANE_FIELDS` text, or None when panes were not read
        self.targets = targets
        self._identity = None
        self._metas = {}                # window id -> its options, or the SessionError that reading them gave

    def identity(self):
        if self._identity is None:
            self._identity = _identity_from(self._identity_raw)
        return self._identity

    def handle(self, project_id, missing_ok=False):
        entry = self.sessions.get(project_id)
        if entry is None:
            if missing_ok:
                return None
            raise SessionError("tmux_session_not_found", "The exact tmux session is unavailable.", 3,
                               {"project": project_id})
        return entry.handle

    def owner(self, project_id):
        """The owner marker of the project's session when it is this server's and this project's."""
        self.handle(project_id)                      # the session must exist
        raw = self.sessions[project_id].owner
        if not raw:
            raise SessionError("tmux_owner_mismatch", "The named tmux session is not managed by agent-session.")
        try:
            owner = json.loads(raw)
        except ValueError as exc:
            raise SessionError("tmux_owner_mismatch", "The managed tmux session has an invalid owner marker.") from exc
        if not isinstance(owner, dict) or owner.get("project_id") != project_id:
            raise SessionError("tmux_owner_mismatch", "The managed tmux session belongs to another project.")
        actual = self.identity()
        if any(owner.get(key) != value for key, value in actual.items()):
            raise SessionError("tmux_owner_mismatch", "The tmux session was restored or its server identity changed.")
        return owner

    def pointer(self, project_id, target):
        """The text of the slot's current pointer option; empty when the slot has none."""
        entry = self.sessions[project_id]
        if target in entry.pointers:
            return entry.pointers[target]
        return self._control._run("show-options", "-qv", "-t", entry.handle, self._control._current_option(target))

    def load(self, project_ids=None):
        """Read the options of every current run of these projects (all by default) in one batch."""
        wanted = []
        for name, entry in self.sessions.items():
            if project_ids is None or name in project_ids:
                wanted += [window for window in map(_pointer_window, entry.pointers.values())
                           if window and _WINDOW_ID.fullmatch(window) and window not in self._metas
                           and (self.windows is None or window in self.windows)]   # another text is read alone, when asked for
        if wanted:
            self._metas.update(self._control._read_metas(wanted))
        return self

    def meta(self, window_id):
        """The window's options; the error that reading them gave is raised again, as a live read would."""
        found = self._metas.get(window_id)
        if found is None:
            if self.windows is not None and window_id not in self.windows:
                found = SessionError("tmux_command_failed", "Tmux rejected the operation.", 5,
                                     {"command": "show-options", "reason": f"can't find window: {window_id}"})
            else:
                found = self._control._read_metas([window_id])[window_id]
            self._metas[window_id] = found
        if isinstance(found, SessionError):
            raise found
        return dict(found)

    def current(self, project_id, target):
        """The slot's current run: its window options, or None. The rule of `Tmux.get_current`."""
        name = _session(project_id)
        if name not in self.sessions:
            return None
        self.owner(name)
        raw = self.pointer(name, target)
        if not raw:
            return None
        try:
            pointer = json.loads(raw)
        except ValueError as exc:
            raise SessionError("tmux_metadata_invalid", "The current execution pointer is invalid.") from exc
        if not isinstance(pointer, dict) or not pointer.get("window_id"):
            raise SessionError("tmux_metadata_invalid", "The current execution pointer is incomplete.")
        try:
            actual = self.meta(pointer["window_id"])
        except SessionError as error:
            reason = error.details.get("reason", "")
            if (error.code == "tmux_command_failed" and isinstance(reason, str)
                    and re.fullmatch(r"(?:no such window|can't find window): .+", reason)):
                raise SessionError("execution_evidence_missing", "The current execution window is unavailable.", 4,
                                   {"target": target, "window_id": pointer["window_id"],
                                    "run_id": pointer.get("run_id")}) from error
            raise
        if any(actual.get(key) != pointer.get(key) for key in _IDENTITY):
            raise SessionError("target_changed", "The runtime identity no longer matches the current pointer.")
        if actual.get("target") != target or actual.get("project_id") != name:
            raise SessionError("target_changed", "The current execution points to another target.")
        return actual

    def pane_info(self, pane_id):
        """The pane's fields (`Tmux.pane_info`), from this view when it read the panes."""
        if self.panes is None:
            return self._control.pane_info(pane_id)
        raw = self.panes.get(_safe_text(pane_id, "pane handle"))
        if raw is None:
            raise SessionError("tmux_command_failed", "Tmux rejected the operation.", 5,
                               {"command": "display-message", "reason": f"can't find pane: {pane_id}"})
        return _pane_row(raw, pane_id)

    def windows_of(self, project_id):
        """Window handles of the project's session, in tmux's order."""
        handle = self.handle(project_id)
        return [window for window, session in self.windows.items() if session == handle]

    def panes_of(self, window_id):
        return [pane for pane, raw in self.panes.items() if raw.split("\t")[0] == window_id]


class Tmux:
    def __init__(self, socket_name=None, socket_path=None):
        if socket_name is not None and socket_path is not None:
            raise SessionError("tmux_input", "Choose a socket name or a socket path, not both.", 2)
        self.socket_name = None if socket_name is None else _safe_text(str(socket_name), "socket name")
        if self.socket_name is not None and ("/" in self.socket_name or self.socket_name in (".", "..")):
            raise SessionError("tmux_input", "A socket name must be one path component.", 2)
        self.socket_path = None
        if socket_path is not None:
            path = Path(_safe_text(str(socket_path), "socket path")).expanduser()
            if not path.is_absolute():
                raise SessionError("tmux_input", "A tmux socket path must be absolute.", 2)
            self.socket_path = str(path.resolve())

    def _argv(self, arguments):
        prefix = [tmux_program.program()]
        if self.socket_path is not None:
            prefix.extend(["-S", self.socket_path])
        elif self.socket_name is not None:
            prefix.extend(["-L", self.socket_name])
        return prefix + list(map(str, arguments))

    def program(self):
        """The tmux executable every command of this control runs (the installer's record, `tmux_program`)."""
        return tmux_program.program()

    def _run(self, *arguments, allow_missing=False):
        try:
            result = subprocess.run(self._argv(arguments), capture_output=True, text=True, timeout=10,
                                    env=tmux_program.environment())
        except FileNotFoundError as exc:
            raise SessionError("tmux_unavailable", "The tmux executable is unavailable.", 5,
                               {"program": tmux_program.program()}) from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SessionError("tmux_unknown", "Cannot confirm the tmux operation.", 4) from exc
        if result.returncode:
            if allow_missing and _absent(result.stderr):
                return None
            raise SessionError("tmux_command_failed", "Tmux rejected the operation.", 5,
                               {"command": str(arguments[0]) if arguments else "", "reason": result.stderr.strip()})
        return result.stdout.rstrip("\n")

    def command(self, *arguments):
        return self._run(*arguments)

    def effective_socket(self):
        value = self._run("display-message", "-p", "#{socket_path}", allow_missing=True)
        if value:
            return str(Path(value).resolve())
        if self.socket_path is not None:
            return self.socket_path
        if self.socket_name is None and os.environ.get("TMUX"):
            return str(Path(os.environ["TMUX"].split(",", 1)[0]).resolve())
        directory = Path(os.environ.get("TMUX_TMPDIR", "/tmp")) / f"tmux-{os.getuid()}"
        return str((directory / (self.socket_name or "default")).resolve())

    def server_identity(self):
        return _identity_from(self._run("display-message", "-p", "#{pid}\t#{start_time}\t#{socket_path}"))

    def _observe(self, targets=(), windows=False, panes=False):
        """Read the server in one tmux process: its identity, every session with its owner marker and the
        current pointers of `targets`, and, when asked, every window and pane. Returns a `ServerView`."""
        targets = tuple(target for target in dict.fromkeys(targets) if self._is_target(target))
        columns = "".join("\t#{" + self._current_option(target) + "}" for target in targets)
        arguments = ["display-message", "-p", _ID_MARK + "\t#{pid}\t#{start_time}\t#{socket_path}",
                     ";", "list-sessions", "-F",
                     _SESSION_MARK + "\t#{session_id}\t#{" + _PREFIX + "owner}" + columns + "\t#{session_name}"]
        if windows:
            arguments += [";", "list-windows", "-a", "-F", _WINDOW_MARK + "\t#{window_id}\t#{session_id}"]
        if panes:
            arguments += [";", "list-panes", "-a", "-F", _PANE_MARK + "\t" + "\t".join("#{" + name + "}" for name in _PANE_FIELDS)]
        raw = self._run(*arguments, allow_missing=True)
        identity, sessions = None, {}
        found_windows = {} if windows else None
        found_panes = {} if panes else None
        for line in (raw or "").split("\n"):
            mark, _, rest = line.partition("\t")
            if mark == _ID_MARK:
                identity = rest
            elif mark == _SESSION_MARK:
                parts = rest.split("\t", len(targets) + 2)         # handle, owner, the pointers, the name
                sessions[parts[-1]] = _Session(parts[0], parts[1], dict(zip(targets, parts[2:-1])))
            elif mark == _WINDOW_MARK and windows:
                window, _, session = rest.partition("\t")
                found_windows[window] = session
            elif mark == _PANE_MARK and panes:
                found_panes[rest.split("\t", 2)[1]] = rest
        return ServerView(self, identity, sessions, found_windows, found_panes, targets)

    def server_view(self, project_ids, targets):
        """A `ServerView` of every session, window and pane, with the options of the current runs of the
        slots `targets` (`leader`, `seat-N`) of these projects already read: two tmux processes in all."""
        return self._observe(targets, windows=True, panes=True).load(set(project_ids))

    @staticmethod
    def _is_target(target):
        return target == "leader" or _SEAT_TARGET.fullmatch(target or "") is not None

    def has_session(self, project_id):
        return _session(project_id) in self._observe().sessions

    def _session_target(self, project_id, missing_ok=False):
        return self._observe().handle(_session(project_id), missing_ok)

    def _session_owner(self, project_id):
        return self._observe().owner(project_id)

    @staticmethod
    def _run_values(metadata):
        """The checked values of a new run and its normalized base."""
        values = _json_value(dict(metadata))
        for key in ("base", "run_id", "target"):
            _safe_text(values.get(key), "managed " + key)
        if values["target"] != "leader" and _SEAT_TARGET.fullmatch(values["target"]) is None:
            raise SessionError("tmux_input", "The managed target must be leader or seat-N.", 2)
        return values, str(Path(values["base"]).resolve())

    def _waiting_values(self, values, base, name, window_id, pane_id, cwd):
        """The run's values once its waiting pane exists: the pane, the server, and the waiting process."""
        view = self._observe(panes=True)
        pane = view.pane_info(pane_id)
        try:
            if pane["pane_pid"] is None:
                raise ProcessLookupError(pane_id)
            placeholder_group = os.getpgid(pane["pane_pid"])
        except OSError as exc:
            raise SessionError("execution_unknown", "The waiting process group is unavailable.", 4) from exc
        return {**values, "base": base, "project_id": name, "window_id": window_id, "pane_id": pane_id,
                "cwd": str(cwd), **view.identity(), "provider_launch_attempted": False,
                "registered": False, "ready": False, "publishing": None, "stopping": False,
                "placeholder_pid": pane["pane_pid"], "placeholder_birth": process.birth(pane["pane_pid"]),
                "placeholder_process_group": placeholder_group}

    def create_window(self, project_id, window_name, cwd, metadata):
        """Create a waiting pane. The caller records its current pointer next."""
        name = _session(project_id)
        window_name = _safe_text(window_name, "window name")
        cwd = Path(cwd).expanduser().resolve()
        if not cwd.is_dir():
            raise SessionError("cwd_unavailable", "The tmux working directory is unavailable.", 3)
        values, base = self._run_values(metadata)
        view = self._observe()
        if name in view.sessions:
            owner = view.owner(name)
            if owner.get("base") != base:
                raise SessionError("tmux_owner_mismatch", "The tmux session belongs to another project base.")
            raw = self._run("new-window", "-d", "-P", "-F", "#{window_id}\t#{pane_id}",
                            "-t", view.handle(name) + ":", "-n", window_name, "-c", cwd, "sleep", "86400")
        else:
            raw = self._run("new-session", "-d", "-P", "-F", "#{window_id}\t#{pane_id}",
                            "-s", name, "-n", window_name, "-c", cwd, "sleep", "86400")
            made = self._observe()               # the session this call made: its handle, and the server it is on
            owner = {"base": base, "project_id": name, **made.identity()}
            self._run("set-option", "-t", made.handle(name), _PREFIX + "owner", json.dumps(owner))
        identifiers = raw.split("\t")
        if len(identifiers) != 2 or not identifiers[0].startswith("@") or not identifiers[1].startswith("%"):
            raise SessionError("tmux_unknown", "Tmux did not return exact window and pane handles.", 4)
        window_id, pane_id = identifiers
        self._run("set-option", "-w", "-t", window_id, "remain-on-exit", "on")
        return self.write_meta(window_id, self._waiting_values(values, base, name, window_id, pane_id, cwd))

    def reuse_window(self, project_id, window_name, cwd, metadata, expected):
        """Give a retired window to a new run: its dead managed pane restarts as the new run's waiting pane.

        `expected` is the metadata of the retired run. Every check comes before the first change, and a
        refusal changes nothing. Then the pane respawns without -k, so tmux itself refuses a pane that
        lives again. One tmux command sequence replaces the window's metadata with the new run's values,
        points the slot at the new run, and renames the window; the window is the retired run's evidence
        until that sequence runs and the new run's waiting pane after it. Other panes stay as they are.
        """
        name = _session(project_id)
        window_name = _safe_text(window_name, "window name")
        if window_name.endswith(";"):
            raise SessionError("tmux_input", "A window name must not end with ';'.", 2)
        cwd = Path(cwd).expanduser().resolve()
        if not cwd.is_dir():
            raise SessionError("cwd_unavailable", "The tmux working directory is unavailable.", 3)
        values, base = self._run_values(metadata)
        window_id = _safe_text(expected.get("window_id"), "window handle")
        view = self._observe(windows=True, panes=True)
        owner = view.owner(name)
        if owner.get("base") != base:
            raise SessionError("tmux_owner_mismatch", "The tmux session belongs to another project base.")
        meta = self.read_meta(window_id)
        keys = ("base", "target", "run_id", "project_id", "window_id", "pane_id")
        if (not meta.get("run_id") or any(meta.get(key) != expected.get(key) for key in keys)
                or meta["project_id"] != name or meta["target"] != values["target"]):
            raise SessionError("target_changed", "The window no longer holds the expected run.")
        server = view.identity()
        if any(meta.get(key) != value for key, value in server.items()):
            raise SessionError("tmux_owner_mismatch", "The window was restored or belongs to another server.")
        if window_id not in view.windows_of(name) or meta["pane_id"] not in view.panes_of(window_id):
            raise SessionError("target_changed", "The window or its managed pane is not in the project session.")
        if not view.pane_info(meta["pane_id"])["pane_dead"]:
            raise SessionError("target_running", "The managed pane is still running.")
        leftover = sorted(set(meta) - set(values) - set(_RUN_VALUES) - set(_IDENTITY) - _WAITING_KEYS)
        if leftover:
            raise SessionError("window_unreusable", "The window has metadata that a new run cannot replace.",
                               details={"keys": leftover})
        pane_id = meta["pane_id"]
        self._run("respawn-pane", "-t", pane_id, "-c", cwd, "sleep", "86400")
        pid = None
        try:
            fresh = self._waiting_values(values, base, name, window_id, pane_id, cwd)
            pid = fresh["placeholder_pid"]
            updates = {**_RUN_VALUES, **fresh}
            pointer = {key: updates.get(key) for key in _IDENTITY}
            arguments = self._option_arguments(window_id, updates)
            arguments += [";", "set-option", "-t", view.handle(name), self._current_option(values["target"]),
                          json.dumps(pointer, ensure_ascii=False, separators=(",", ":")),
                          ";", "set-option", "-w", "-t", window_id, "remain-on-exit", "on",
                          ";", "rename-window", "-t", window_id, window_name]
            reused = self._read_metas([window_id], before=arguments[1:])[window_id]
            if isinstance(reused, SessionError):
                raise reused
        except BaseException:
            # The waiting process is this call's own; ending it returns the window to the retired run's evidence.
            if pid is not None:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            raise
        return reused

    def read_meta(self, window_id):
        """The window's run options, read as one snapshot.

        One tmux command sequence lists the option names and prints the values of the names asked for, so
        the result is one snapshot. A name the listing shows and the request lacked is read again; managed
        options are never unset, so the names only grow (`_META_KEYS`)."""
        window_id = _safe_text(window_id, "window handle")
        found = self._read_metas([window_id])[window_id]
        if isinstance(found, SessionError):
            raise found
        return found

    def _read_metas(self, window_ids, before=None):
        """{window id: its run options, or the SessionError of reading that window}, for several windows in
        one tmux process (the sequence of `read_meta` once per window). `before` is a tmux command list
        for one window that runs first in the same sequence (`write_meta` reads its result back with it)."""
        global _META_KEYS
        pending = list(dict.fromkeys(_safe_text(window, "window handle") for window in window_ids))
        results = {}
        while pending:
            keys = sorted(_META_KEYS)
            mark = _VALUES_MARK + "\t#{window_id}" + "".join("\t#{" + _PREFIX + key + "}" for key in keys)
            commands = [command for window in pending
                        for command in (["show-options", "-w", "-t", window], ["display-message", "-p", "-t", window, mark])]
            output, gone = self._meta_sequence(commands, before)
            before = None
            for window in gone:
                results[window] = SessionError("tmux_command_failed", "Tmux rejected the operation.", 5,
                                               {"command": "show-options", "reason": f"no such window: {window}"})
            if output is None:                          # the sequence stopped at the window that is gone
                pending = [window for window in pending if window not in results]
                continue
            blocks, listing = {}, []
            for line in output.split("\n"):
                if line.startswith(_VALUES_MARK + "\t"):
                    fields = line.split("\t")
                    blocks[fields[1]] = (listing, fields[2:])
                    listing = []
                else:
                    listing.append(line)
            again = []
            for window in pending:
                if window in results:
                    continue
                block = blocks.get(window) or (next(iter(blocks.values())) if len(pending) == 1 and len(blocks) == 1 else None)
                if block is None:
                    results[window] = SessionError("tmux_metadata_invalid", "The managed window has invalid runtime metadata.")
                    continue
                lines, fields = block
                try:
                    listed = _meta_keys(lines)
                    if not listed:
                        results[window] = {}
                        continue
                    asked = dict(zip(keys, fields))
                    if len(fields) != len(keys):
                        raise ValueError("Incomplete tmux option values")
                    if any(key not in asked for key in listed):
                        again.append(window)
                        _META_KEYS = _META_KEYS | frozenset(listed)
                        continue
                    results[window] = {key: json.loads(asked[key]) for key in listed}
                except SessionError as error:
                    results[window] = error
                except ValueError:
                    results[window] = SessionError("tmux_metadata_invalid", "The managed window has invalid runtime metadata.")
            pending = again
        return results

    def _meta_sequence(self, commands, before):
        """Run tmux command lists in one process. Returns (their output, the windows that no longer exist).

        A short sequence is one command line; when a window is gone it stops there and the output is None.
        A long one goes in by stdin to `source-file`, because tmux refuses a command line of 16 KB; there a
        failing line does not stop the lines after it."""
        if before is not None or sum(len(word) + 1 for command in commands for word in command) <= _ARGV_LIMIT:
            words = list(before or ())
            for command in commands:
                words += ([";"] if words else []) + command
            try:
                return self._run(*words), []
            except SessionError as error:
                reason = error.details.get("reason", "")
                found = _WINDOW_GONE.search(reason) if error.code == "tmux_command_failed" and isinstance(reason, str) else None
                if before is not None or found is None:
                    raise
                return None, [found.group(1)]
        script = ""
        for index in range(0, len(commands), 2):
            lines = [" ".join(self._quoted(word) for word in command) for command in commands[index:index + 2]]
            script += " ; ".join(lines) + "\n"
        try:
            result = subprocess.run(self._argv(["source-file", "-"]), input=script, capture_output=True, text=True,
                                    timeout=10, env=tmux_program.environment())
        except FileNotFoundError as exc:
            raise SessionError("tmux_unavailable", "The tmux executable is unavailable.", 5,
                               {"program": tmux_program.program()}) from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SessionError("tmux_unknown", "Cannot confirm the tmux operation.", 4) from exc
        gone = []
        for line in result.stderr.splitlines():
            found = _WINDOW_GONE.search(line)
            if found is None:
                raise SessionError("tmux_command_failed", "Tmux rejected the operation.", 5,
                                   {"command": "source-file", "reason": line.strip()})
            gone.append(found.group(1))
        return result.stdout.rstrip("\n"), gone

    @staticmethod
    def _quoted(word):
        if "'" in word or "\n" in word:
            raise SessionError("tmux_input", "A tmux word must have no quote or newline.", 2)
        return "'" + word + "'"

    def write_meta(self, window_id, updates):
        """Keep mutable fields in separate options so concurrent updates merge.

        One tmux command sequence sets all options of one update, so a reader sees all or none of them.
        The same sequence reads the options back, so the result is what the window holds after the update.
        """
        updates = _json_value(dict(updates))
        guarded = [key for key in updates if key in _IDENTITY or key == "provider_launch_attempted"]
        if guarded or not updates:                 # only these updates are checked against what the window holds now
            current = self.read_meta(window_id)
            for key, value in updates.items():
                if key in _IDENTITY and key in current and current[key] != value:
                    raise SessionError("target_changed", "An immutable runtime identity cannot be replaced in place.",
                                       details={"field": key})
                if key == "provider_launch_attempted" and current.get(key) is True and value is not True:
                    raise SessionError("target_changed", "A provider launch attempt cannot be cleared in the same run.")
        arguments = self._option_arguments(window_id, updates)
        if not arguments:
            return current
        found = self._read_metas([window_id], before=arguments[1:])[window_id]
        if isinstance(found, SessionError):
            raise found
        return found

    @staticmethod
    def _option_arguments(window_id, updates):
        arguments = []
        for key, value in updates.items():
            if re.fullmatch(r"[a-z][a-z0-9_]*", key) is None:
                raise SessionError("tmux_metadata_invalid", "A runtime metadata key is invalid.", 2)
            # Tmux ends a command at an argument that ends with ";". A JSON value never ends with ";".
            arguments += [";", "set-option", "-w", "-t", window_id, _PREFIX + key,
                          json.dumps(value, ensure_ascii=False, separators=(",", ":"))]
        return arguments

    def _current_option(self, target):
        if target != "leader" and _SEAT_TARGET.fullmatch(target or "") is None:
            raise SessionError("tmux_input", "The managed target must be leader or seat-N.", 2)
        return _PREFIX + "current_" + target.replace("-", "_")

    def set_current(self, project_id, target, metadata):
        view = self._observe()
        owner = view.owner(_session(project_id))
        actual = self.read_meta(metadata["window_id"])
        if (actual.get("project_id") != project_id or actual.get("target") != target
                or actual.get("base") != owner.get("base") or actual.get("run_id") != metadata.get("run_id")):
            raise SessionError("target_changed", "The current pointer does not match this managed window.")
        pointer = {key: actual.get(key) for key in _IDENTITY}
        self._run("set-option", "-t", view.handle(project_id), self._current_option(target),
                  json.dumps(pointer, ensure_ascii=False, separators=(",", ":")))
        return actual

    def get_current(self, project_id, target):
        return self._observe((target,)).current(project_id, target)

    def current_with_run(self, project_id, run_id, targets):
        """The window options of the slots among `targets` whose current run is `run_id`: normally one, else none.

        The pointers of all `targets` come in the one tmux process that reads the server, and only the windows
        the pointers name this run for are read, so the tmux processes do not grow with the slots (a
        `get_current` per slot did). A pointer that is unreadable or names another run is not this run's
        concern; a slot whose window is gone is not a match."""
        name = _session(project_id)
        view = self._observe(targets)
        if name not in view.sessions:
            return []
        found = []
        for target in view.targets:
            if _pointer_field(view.pointer(name, target), "run_id") != run_id:
                continue
            try:
                meta = view.current(project_id, target)
            except SessionError as error:
                if error.code != "execution_evidence_missing":
                    raise
                continue
            if meta and meta.get("run_id") == run_id:
                found.append(meta)
        return found

    def clear_current(self, project_id, target, run_id):
        """Remove the slot pointer only while it still names this run."""
        name = _session(project_id)
        view = self._observe((target,))
        if name not in view.sessions:
            return False
        view.owner(name)
        option = self._current_option(target)
        raw = view.pointer(name, target)
        if not raw:
            return False
        try:
            pointer = json.loads(raw)
        except ValueError as exc:
            raise SessionError("tmux_metadata_invalid", "The current execution pointer is invalid.") from exc
        if not isinstance(pointer, dict) or pointer.get("run_id") != run_id:
            return False
        self._run("set-option", "-u", "-t", view.handle(name), option)
        return True

    def managed_windows(self, project_id, target):
        """Window handles of one slot's managed runs in the project session, current or retired."""
        name = _session(project_id)
        view = self._observe(windows=True)
        if name not in view.sessions:
            return []
        view.owner(name)
        found = self._read_metas(view.windows_of(name))
        return [window for window, meta in found.items()
                if not isinstance(meta, SessionError) and meta.get("project_id") == name and meta.get("target") == target]

    def close_window(self, window_id, expected):
        """Close a retired window's dead managed pane: "window" when it was the only pane, else "pane".

        A window that holds panes a person added keeps them. The managed pane goes and the window stops
        being a managed one (its options are unset, `remain-on-exit` too) in one tmux command sequence."""
        meta = self.read_meta(_safe_text(window_id, "window handle"))
        keys = ("base", "target", "run_id", "project_id", "window_id", "pane_id")
        if not meta.get("run_id") or any(meta.get(key) != expected.get(key) for key in keys):
            raise SessionError("target_changed", "The window no longer holds the expected run.")
        view = self._observe(panes=True)
        server = view.identity()
        if any(meta.get(key) != value for key, value in server.items()):
            raise SessionError("tmux_owner_mismatch", "The window was restored or belongs to another server.")
        panes = view.panes_of(window_id)
        if meta["pane_id"] not in panes:
            raise SessionError("target_changed", "The window no longer holds the managed pane.",
                               details={"panes": panes})
        if not view.pane_info(meta["pane_id"])["pane_dead"]:
            raise SessionError("target_running", "The managed pane is still running.")
        if panes == [meta["pane_id"]]:
            self._run("kill-window", "-t", window_id)
            return "window"
        arguments = ["kill-pane", "-t", meta["pane_id"], ";", "set-option", "-wu", "-t", window_id, "remain-on-exit"]
        for key in meta:
            arguments += [";", "set-option", "-wu", "-t", window_id, _PREFIX + key]
        self._run(*arguments)
        return "pane"

    def require_version(self):
        """Refuse a tmux older than the minimum, before a run is started: the named hook index of
        `install_exit_hook` needs the same tmux the integration file does (install contract 3.2).

        The running server's version counts; with no server yet, the version of the tmux this tree runs
        (`tmux_program`, the installer's record). A tree without the integration file has no minimum, and
        nothing is checked."""
        wanted = minimum_version()
        if wanted is None:
            return
        version = self._run("display-message", "-p", "#{version}", allow_missing=True)
        program = tmux_program.program()
        if not version:
            try:
                parts = subprocess.run([program, "-V"], capture_output=True, text=True, timeout=10,
                                       env=tmux_program.environment()).stdout.split()
            except (OSError, subprocess.SubprocessError) as exc:
                raise SessionError("tmux_unavailable", "The tmux executable is unavailable.", 5,
                                   {"program": program}) from exc
            version = parts[-1] if parts else ""
        if _version_number(version) < _version_number(wanted):
            raise SessionError(
                "tmux_too_old", f"agent-session needs tmux {wanted} or newer; the tmux {program} runs is "
                f"{version or 'of an unknown version'}. Install a newer tmux (the company tmux is in {COMPANY_TMUX}), "
                "run the installer again, and restart the tmux server (install contract 6.2).", 5,
                {"version": version, "minimum": wanted, "program": program, "company_tmux": COMPANY_TMUX})

    def install_exit_hook(self, python, library):
        """Make the tmux server run the wrap-up of a managed run whose pane died (`internal.finish_ended`).

        One server-wide `pane-died` hook element serves every project and run: it fires only for a pane that
        a managed window names as its own (`PANE_ID_OPTION`), and the wrap-up reads everything else from that
        window. It is an element of its own, so the hooks of a person's configuration still run (a window-scope
        hook would replace them). The command is written again at every launch with that launch's interpreter
        and library. It leaves nothing in the user's pane whatever the wrap-up does (`quiet_shell`). Returns False, without a hook, when a path has a character the command cannot carry."""
        words = (str(python), str(library), tmux_program.program())
        if any(_HOOK_WORD.fullmatch(word) is None for word in words):
            return False
        job = (f"env PYTHONPATH={words[1]} {words[0]} -m agent_session.internal finish-ended "
               "#{socket_path} #{window_id} #{pane_id}")
        shell = quiet_shell(job, "finish-ended", "#{socket_path}", quote='\\"')
        command = ("if-shell -F '#{==:#{" + PANE_ID_OPTION + "},\"#{pane_id}\"}' 'run-shell -b \"" + shell + "\"'")
        self._run("set-hook", "-g", EXIT_HOOK, command)
        return True

    def notify(self, text, milliseconds):
        """Show a message on every attached client for the given time. Return how many clients got it.

        Nothing is typed into a pane; a server with no attached client has nobody to tell."""
        clients = [name for name in (self._run("list-clients", "-F", "#{client_name}", allow_missing=True)
                                     or "").splitlines() if name]
        for client in clients:
            # display-message expands formats, so a literal "#" is doubled.
            self._run("display-message", "-d", int(milliseconds), "-c", client, text.replace("#", "##"))
        return len(clients)

    def ring_bell(self, pane_id):
        """Write one BEL to the pane's tty, which makes tmux flag the window's bell.

        This is output toward the terminal, not input to the program, so it cannot join what a person
        types in the pane."""
        tty = self._run("display-message", "-p", "-t", _safe_text(pane_id, "pane handle"), "#{pane_tty}")
        if not tty.startswith("/dev/"):
            raise SessionError("tmux_unknown", "Tmux did not return the pane's tty.", 4, {"pane": pane_id})
        try:
            descriptor = os.open(tty, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError as exc:
            raise SessionError("bell_failed", "Cannot open the pane's tty.", 5, {"pane": pane_id}) from exc
        try:
            os.write(descriptor, b"\a")
        except OSError as exc:
            raise SessionError("bell_failed", "Cannot write to the pane's tty.", 5, {"pane": pane_id}) from exc
        finally:
            os.close(descriptor)

    def capture_pane(self, pane_id):
        """The visible text of a pane; read only to find a provider's startup dialog."""
        return self._run("capture-pane", "-p", "-t", _safe_text(pane_id, "pane handle"))

    def pane_slot(self, pane_id):
        """`(project_id, target)` of the managed window that holds the pane, or None for another window.

        `target` is `leader`, `seat-N`, or None when the window's target is not a slot. The values are
        the JSON of the window's `project_id` and `target` options; a missing or malformed project_id
        means the window is not managed. One tmux call, so Board panes can ask on every window change."""
        keys = ("project_id", "target")
        raw = self._run("display-message", "-p", "-t", _safe_text(pane_id, "pane handle"),
                        "\t".join("#{" + _PREFIX + key + "}" for key in keys))
        values = []
        for part in raw.split("\t"):
            try:
                values.append(json.loads(part))
            except ValueError:
                values.append(None)
        if len(values) != len(keys) or not isinstance(values[0], str) or not values[0]:
            return None
        target = values[1]
        valid = isinstance(target, str) and (target == "leader" or _SEAT_TARGET.fullmatch(target) is not None)
        return values[0], target if valid else None

    def pane_info(self, pane_id):
        """The pane's fields. A dead pane may have no pane_pid (tmux 3.8 clears it); it is None then.

        Only fields that can never hold a tab are read: pane_current_path and pane_current_command
        are printed as is, so a tab in a directory name would shift every field after it."""
        raw = self._run("display-message", "-p", "-t", _safe_text(pane_id, "pane handle"),
                        "\t".join("#{" + field + "}" for field in _PANE_FIELDS))
        return _pane_row(raw, pane_id)

    def launch(self, window_id, cwd, script_path):
        """Replace only this run's still-owned waiting process."""
        meta = self.read_meta(window_id)
        if not meta.get("project_id") or not meta.get("target"):
            raise SessionError("tmux_owner_mismatch", "The window has no managed runtime identity.")
        current = self.get_current(meta["project_id"], meta["target"])
        if current is None or current.get("run_id") != meta.get("run_id") or current.get("window_id") != window_id:
            raise SessionError("target_changed", "This window is no longer the current execution.")
        if (meta.get("provider_launch_attempted") is not False
                and not (meta.get("remote_seat") and not meta.get("cli_pid"))):
            raise SessionError("launch_already_attempted", "The provider launch was already attempted or is unknown.")
        pane = self.pane_info(meta["pane_id"])
        if (pane["pane_dead"] or pane["pane_pid"] != meta.get("placeholder_pid")
                or not process.alive(pane["pane_pid"], meta.get("placeholder_birth"))):
            raise SessionError("target_changed", "The waiting pane process no longer matches this run.")
        cwd = Path(cwd).expanduser().resolve()
        script = Path(script_path).expanduser().resolve()
        expected_cwd = meta.get("base") if meta.get("remote_seat") else meta.get("cwd")
        if str(cwd) != expected_cwd or not script.is_file():
            raise SessionError("tmux_input", "The launch script or working directory does not match this run.", 2)
        self.write_meta(window_id, {"provider_launch_attempted": True})
        self._run("respawn-pane", "-k", "-t", meta["pane_id"], "-c", cwd, "/bin/bash", script)
        pane = self.pane_info(meta["pane_id"])
        pid = pane["pane_pid"]
        if pid is None:                    # the CLI already exited; keep what its launch recorded
            return self.read_meta(window_id)
        try:
            group = os.getpgid(pid)
        except ProcessLookupError:
            group = None
        return self.write_meta(window_id, {"cli_pid": pid, "cli_birth": process.birth(pid), "process_group": group})

    def reconnect_remote(self, meta, cwd, script):
        """Reconnect only a dead SSH display of the exact current remote run."""
        current = self.get_current(meta["project_id"], meta["target"])
        if (not current or not current.get("remote_seat") or current["run_id"] != meta["run_id"]
                or current["pane_id"] != meta["pane_id"] or not self.pane_info(meta["pane_id"])["pane_dead"]):
            raise SessionError("target_changed", "The remote display changed before reconnecting.")
        self._run("respawn-pane", "-t", meta["pane_id"], "-c", cwd, "/bin/bash", script)
        pane = self.pane_info(meta["pane_id"])
        pid = pane["pane_pid"]
        return self.write_meta(meta["window_id"], {"run_id": meta["run_id"], "cli_pid": pid,
                               "cli_birth": process.birth(pid) if pid else None,
                               "process_group": os.getpgid(pid) if pid else None})

    def send_exit(self, pane_id):
        pane = self.pane_info(pane_id)
        meta = self.read_meta(pane["window_id"])
        current = self.get_current(meta.get("project_id", ""), meta.get("target"))
        if current is None or current.get("run_id") != meta.get("run_id") or current.get("pane_id") != pane_id:
            raise SessionError("target_changed", "The pane is no longer the current execution.")
        if pane["pane_dead"]:
            return
        if (not meta.get("cli_birth") or not process.alive(pane["pane_pid"], meta["cli_birth"])
                or pane["pane_pid"] != meta.get("cli_pid")):
            raise SessionError("target_changed", "The provider pane process identity changed.")
        stage, literal_confirmed = "literal", False
        try:
            self._exit_input_ready(pane_id)
            self._run("send-keys", "-t", pane_id, "-l", "/exit")
            literal_confirmed = True
            # Codex 0.166 treats Enter within its 120 ms paste window as input text.
            time.sleep(0.25)
            stage = "enter"
            self._exit_input_ready(pane_id)
            self._run("send-keys", "-t", pane_id, "Enter")
        except SessionError as error:
            error.details = {**error.details, "exit_delivery": {"stage": stage,
                                                               "literal_confirmed": literal_confirmed}}
            raise

    def _exit_input_ready(self, pane_id):
        """A native idle report does not mean tmux will route keys to the CLI."""
        raw = self._run("display-message", "-p", "-t", pane_id, "#{pane_in_mode}\t#{pane_mode}")
        fields = raw.split("\t")
        if (len(fields) != 2 or fields[0] not in ("0", "1")
                or bool(fields[1]) != (fields[0] == "1")):
            raise SessionError("tmux_unknown", "Cannot confirm the pane input mode.", 4, {"pane": pane_id})
        if fields[0] == "1":
            raise SessionError("pane_input_blocked", "A tmux mode blocks the provider's exit input.", 4,
                               {"pane": pane_id, "pane_mode": fields[1]})

    def request_placeholder_stop(self, window_id):
        """Request TERM only for the current run's unlaunched waiting process."""
        meta = self.read_meta(window_id)
        current = self.get_current(meta.get("project_id", ""), meta.get("target"))
        if (current is None or current.get("run_id") != meta.get("run_id")
                or current.get("window_id") != window_id):
            raise SessionError("target_changed", "The waiting pane is no longer the current execution.")
        if meta.get("provider_launch_attempted") is not False or meta.get("registered") is not False:
            raise SessionError("launch_already_attempted", "This pane is not a confirmed unlaunched process.")
        pane = self.pane_info(meta["pane_id"])
        if pane["pane_dead"]:
            return {"requested": False, "pane_dead": True}
        pid = pane["pane_pid"]
        if (pid != meta.get("placeholder_pid") or not meta.get("placeholder_birth")
                or not process.alive(pid, meta["placeholder_birth"])):
            raise SessionError("target_changed", "The waiting pane process identity changed.")
        try:
            if os.getpgid(pid) != meta.get("placeholder_process_group"):
                raise SessionError("target_changed", "The waiting process group changed.")
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return {"requested": False, "pane_dead": self.pane_info(meta["pane_id"])["pane_dead"]}
        except OSError as exc:
            raise SessionError("execution_unknown", "Cannot confirm the waiting process termination request.", 4) from exc
        return {"requested": True, "pane_dead": self.pane_info(meta["pane_id"])["pane_dead"]}

    def run_quiet(self, job, name, client=None):
        """Run a shell `job` as a background `run-shell` that leaves nothing in the user's pane (`quiet_shell`).

        `client` is the tmux client of a person who started the job; a failure is shown on it for a moment."""
        socket = shlex.quote(self.effective_socket())
        self._run("run-shell", "-b", quiet_shell(job, name, socket, notify_client=shlex.quote(client) if client else None))

    def run_controller(self, script_path, cwd):
        """Ask the selected tmux server to run a fixed controller script."""
        script = Path(script_path).expanduser().resolve()
        cwd = Path(cwd).expanduser().resolve()
        if not script.is_file() or not cwd.is_dir():
            raise SessionError("tmux_input", "The controller script or working directory is unavailable.", 2)
        self.run_quiet("cd " + shlex.quote(str(cwd)) + " && " + shlex.join(["/bin/bash", str(script)]), "controller")
        return {"submitted": True, "script": str(script), "cwd": str(cwd),
                "socket_path": self.effective_socket()}

    def find_by_session(self, project, session_id):
        view = self._observe(windows=True)
        if project.project_id not in view.sessions:
            return None
        owner = view.owner(project.project_id)
        if owner.get("base") != str(project.base):
            raise SessionError("tmux_owner_mismatch", "The tmux session belongs to another project base.")
        found = []
        for window_id, meta in self._read_metas(view.windows_of(project.project_id)).items():
            if isinstance(meta, SessionError):
                raise meta
            if meta.get("base") == str(project.base) and meta.get("session_id") == session_id:
                found.append(meta)
        if len(found) > 1:
            raise SessionError("tmux_owner_mismatch", "The provider session matches more than one managed window.")
        return found[0] if found else None


def control(socket=None):
    """The Tmux control for a socket path or Tmux keywords; AGENT_SESSION_SOCKET when none is given."""
    socket = socket or os.environ.get("AGENT_SESSION_SOCKET")
    if isinstance(socket, dict):
        return Tmux(**socket)
    return Tmux(socket_path=str(socket)) if socket else Tmux()


def check_owner(project, slot, session, meta):
    """Accept a tmux run only as this base's run of the slot and as the conversation the state names.

    Session is the state's conversation for the slot; None leaves the conversation uncompared.
    """
    if Path(meta.get("base", "")).resolve() != project.base:
        raise SessionError("owner_mismatch", "The tmux window belongs to another project.")
    if meta.get("target") != slot or (session and meta.get("session_id") != session["session_id"]):
        raise SessionError("owner_mismatch", "The native conversation does not match this slot.")
    if slot.startswith("seat-"):
        seat = project.seats[int(slot[5:])]
        expected = {"host": seat.host, "path": str(seat.path), "python": seat.python} if isinstance(seat, RemoteSeat) else None
        if meta.get("remote_seat") != expected:
            raise SessionError("owner_mismatch", "The execution host differs from the registered seat.")
        if expected and session and "endpoint" in session and session["endpoint"] != meta.get("endpoint"):
            raise SessionError("owner_mismatch", "The remote provider endpoint differs from the published binding.")
