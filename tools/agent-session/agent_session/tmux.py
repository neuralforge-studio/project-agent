"""Control only windows with an exact project, run, and process identity."""

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
from . import process


_PREFIX = "@agent_session_"
PANE_ID_OPTION = _PREFIX + "pane_id"    # window option naming the managed pane; project-agent.conf repeats it
EXIT_HOOK = "pane-died[agent-session]"  # the server-wide hook element that starts the wrap-up of a run that ended itself
_HOOK_WORD = re.compile(r"[A-Za-z0-9_./:@%+=,-]+")  # what a hook command may carry as a path: no quote, space, or `$`
COMPANY_TMUX = "/primehome/tools/Inhouse/tmux/latest/bin"   # install contract 3.2: put this directory first in PATH
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
_VALUES_MARK = "agent-session-values"
_SEAT_TARGET = re.compile(r"seat-(0|[1-9][0-9]*)")


def _meta_keys(lines):
    keys = [line.split(" ", 1)[0][len(_PREFIX):] for line in lines if line.startswith(_PREFIX)]
    if any(re.fullmatch(r"[a-z][a-z0-9_]*", key) is None for key in keys):
        raise SessionError("tmux_metadata_invalid", "The managed window has invalid runtime metadata.")
    return keys


def _absent(stderr):
    return any(text in stderr for text in ("no server running", "No such file or directory", "can't find session"))


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
        prefix = ["tmux"]
        if self.socket_path is not None:
            prefix.extend(["-S", self.socket_path])
        elif self.socket_name is not None:
            prefix.extend(["-L", self.socket_name])
        return prefix + list(map(str, arguments))

    def _run(self, *arguments, allow_missing=False):
        try:
            result = subprocess.run(self._argv(arguments), capture_output=True, text=True, timeout=10)
        except FileNotFoundError as exc:
            raise SessionError("tmux_unavailable", "The tmux executable is unavailable.", 5) from exc
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
        raw = self._run("display-message", "-p", "#{pid}\t#{start_time}\t#{socket_path}")
        parts = raw.split("\t")
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

    def has_session(self, project_id):
        name = _session(project_id)
        return self._session_target(name, missing_ok=True) is not None

    def _session_target(self, project_id, missing_ok=False):
        raw = self._run("list-sessions", "-F", "#{session_name}\t#{session_id}", allow_missing=True)
        for line in (raw or "").splitlines():
            name, separator, handle = line.partition("\t")
            if separator and name == project_id:
                return handle
        if missing_ok:
            return None
        raise SessionError("tmux_session_not_found", "The exact tmux session is unavailable.", 3,
                           {"project": project_id})

    def _session_owner(self, project_id):
        raw = self._run("show-options", "-qv", "-t", self._session_target(project_id), _PREFIX + "owner")
        if not raw:
            raise SessionError("tmux_owner_mismatch", "The named tmux session is not managed by agent-session.")
        try:
            owner = json.loads(raw)
        except ValueError as exc:
            raise SessionError("tmux_owner_mismatch", "The managed tmux session has an invalid owner marker.") from exc
        if not isinstance(owner, dict) or owner.get("project_id") != project_id:
            raise SessionError("tmux_owner_mismatch", "The managed tmux session belongs to another project.")
        actual = self.server_identity()
        if any(owner.get(key) != value for key, value in actual.items()):
            raise SessionError("tmux_owner_mismatch", "The tmux session was restored or its server identity changed.")
        return owner

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
        pane = self.pane_info(pane_id)
        try:
            if pane["pane_pid"] is None:
                raise ProcessLookupError(pane_id)
            placeholder_group = os.getpgid(pane["pane_pid"])
        except OSError as exc:
            raise SessionError("execution_unknown", "The waiting process group is unavailable.", 4) from exc
        return {**values, "base": base, "project_id": name, "window_id": window_id, "pane_id": pane_id,
                "cwd": str(cwd), **self.server_identity(), "provider_launch_attempted": False,
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
        if self.has_session(name):
            owner = self._session_owner(name)
            if owner.get("base") != base:
                raise SessionError("tmux_owner_mismatch", "The tmux session belongs to another project base.")
            raw = self._run("new-window", "-d", "-P", "-F", "#{window_id}\t#{pane_id}",
                            "-t", self._session_target(name) + ":", "-n", window_name, "-c", cwd, "sleep", "86400")
        else:
            raw = self._run("new-session", "-d", "-P", "-F", "#{window_id}\t#{pane_id}",
                            "-s", name, "-n", window_name, "-c", cwd, "sleep", "86400")
            owner = {"base": base, "project_id": name, **self.server_identity()}
            self._run("set-option", "-t", self._session_target(name), _PREFIX + "owner", json.dumps(owner))
        identifiers = raw.split("\t")
        if len(identifiers) != 2 or not identifiers[0].startswith("@") or not identifiers[1].startswith("%"):
            raise SessionError("tmux_unknown", "Tmux did not return exact window and pane handles.", 4)
        window_id, pane_id = identifiers
        self._run("set-option", "-w", "-t", window_id, "remain-on-exit", "on")
        self.write_meta(window_id, self._waiting_values(values, base, name, window_id, pane_id, cwd))
        return self.read_meta(window_id)

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
        owner = self._session_owner(name)
        if owner.get("base") != base:
            raise SessionError("tmux_owner_mismatch", "The tmux session belongs to another project base.")
        meta = self.read_meta(window_id)
        keys = ("base", "target", "run_id", "project_id", "window_id", "pane_id")
        if (not meta.get("run_id") or any(meta.get(key) != expected.get(key) for key in keys)
                or meta["project_id"] != name or meta["target"] != values["target"]):
            raise SessionError("target_changed", "The window no longer holds the expected run.")
        server = self.server_identity()
        if any(meta.get(key) != value for key, value in server.items()):
            raise SessionError("tmux_owner_mismatch", "The window was restored or belongs to another server.")
        handles = self._run("list-windows", "-t", self._session_target(name), "-F", "#{window_id}").splitlines()
        panes = self._run("list-panes", "-t", window_id, "-F", "#{pane_id}").splitlines()
        if window_id not in handles or meta["pane_id"] not in panes:
            raise SessionError("target_changed", "The window or its managed pane is not in the project session.")
        if not self.pane_info(meta["pane_id"])["pane_dead"]:
            raise SessionError("target_running", "The managed pane is still running.")
        leftover = sorted(set(meta) - set(values) - set(_RUN_VALUES) - set(_IDENTITY)
                          - {"cwd", "provider_launch_attempted", "registered", "ready", "publishing", "stopping",
                             "placeholder_pid", "placeholder_birth", "placeholder_process_group"})
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
            arguments += [";", "set-option", "-t", self._session_target(name), self._current_option(values["target"]),
                          json.dumps(pointer, ensure_ascii=False, separators=(",", ":")),
                          ";", "set-option", "-w", "-t", window_id, "remain-on-exit", "on",
                          ";", "rename-window", "-t", window_id, window_name]
            self._run(*arguments[1:])
        except BaseException:
            # The waiting process is this call's own; ending it returns the window to the retired run's evidence.
            if pid is not None:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            raise
        return self.read_meta(window_id)

    def read_meta(self, window_id):
        """Read values with -v, because the quoted listing escapes $ in a way shlex cannot undo.

        One tmux command sequence lists the options and prints the requested values, so the
        result is one snapshot. A key that write_meta added after the request is read again;
        managed options are never unset, so the key list only grows.
        """
        window_id = _safe_text(window_id, "window handle")
        keys = None
        while True:
            arguments = ["show-options", "-w", "-t", window_id,
                         ";", "display-message", "-p", "-t", window_id, _VALUES_MARK]
            for key in keys or ():
                arguments += [";", "show-options", "-wv", "-t", window_id, _PREFIX + key]
            # JSON escapes control characters, so only tmux adds "\n"; splitlines would also cut U+2028.
            lines = self._run(*arguments).split("\n")
            if lines.count(_VALUES_MARK) != 1:
                raise SessionError("tmux_metadata_invalid", "The managed window has invalid runtime metadata.")
            mark = lines.index(_VALUES_MARK)
            listed = _meta_keys(lines[:mark])
            if not listed or listed == keys:
                break
            keys = listed
        values = lines[mark + 1:]
        try:
            if len(values) != len(listed):
                raise ValueError("Incomplete tmux option values")
            return {key: json.loads(value) for key, value in zip(listed, values)}
        except ValueError as exc:
            raise SessionError("tmux_metadata_invalid", "The managed window has invalid runtime metadata.") from exc

    def write_meta(self, window_id, updates):
        """Keep mutable fields in separate options so concurrent updates merge.

        One tmux command sequence sets all options of one update, so a reader sees all or none of them.
        """
        current = self.read_meta(window_id)
        updates = _json_value(dict(updates))
        for key, value in updates.items():
            if key in _IDENTITY and key in current and current[key] != value:
                raise SessionError("target_changed", "An immutable runtime identity cannot be replaced in place.",
                                   details={"field": key})
            if key == "provider_launch_attempted" and current.get(key) is True and value is not True:
                raise SessionError("target_changed", "A provider launch attempt cannot be cleared in the same run.")
        arguments = self._option_arguments(window_id, updates)
        if arguments:
            self._run(*arguments[1:])
        return self.read_meta(window_id)

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
        owner = self._session_owner(_session(project_id))
        actual = self.read_meta(metadata["window_id"])
        if (actual.get("project_id") != project_id or actual.get("target") != target
                or actual.get("base") != owner.get("base") or actual.get("run_id") != metadata.get("run_id")):
            raise SessionError("target_changed", "The current pointer does not match this managed window.")
        pointer = {key: actual.get(key) for key in _IDENTITY}
        self._run("set-option", "-t", self._session_target(project_id), self._current_option(target),
                  json.dumps(pointer, ensure_ascii=False, separators=(",", ":")))
        return actual

    def get_current(self, project_id, target):
        name = _session(project_id)
        if not self.has_session(name):
            return None
        self._session_owner(name)
        raw = self._run("show-options", "-qv", "-t", self._session_target(name), self._current_option(target))
        if not raw:
            return None
        try:
            pointer = json.loads(raw)
        except ValueError as exc:
            raise SessionError("tmux_metadata_invalid", "The current execution pointer is invalid.") from exc
        if not isinstance(pointer, dict) or not pointer.get("window_id"):
            raise SessionError("tmux_metadata_invalid", "The current execution pointer is incomplete.")
        try:
            actual = self.read_meta(pointer["window_id"])
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

    def clear_current(self, project_id, target, run_id):
        """Remove the slot pointer only while it still names this run."""
        name = _session(project_id)
        if not self.has_session(name):
            return False
        self._session_owner(name)
        option = self._current_option(target)
        handle = self._session_target(name)
        raw = self._run("show-options", "-qv", "-t", handle, option)
        if not raw:
            return False
        try:
            pointer = json.loads(raw)
        except ValueError as exc:
            raise SessionError("tmux_metadata_invalid", "The current execution pointer is invalid.") from exc
        if not isinstance(pointer, dict) or pointer.get("run_id") != run_id:
            return False
        self._run("set-option", "-u", "-t", handle, option)
        return True

    def managed_windows(self, project_id, target):
        """Window handles of one slot's managed runs in the project session, current or retired."""
        name = _session(project_id)
        if not self.has_session(name):
            return []
        self._session_owner(name)
        raw = self._run("list-windows", "-t", self._session_target(name), "-F", "#{window_id}")
        handles = []
        for window_id in (raw or "").splitlines():
            try:
                meta = self.read_meta(window_id)
            except SessionError:
                continue
            if meta.get("project_id") == name and meta.get("target") == target:
                handles.append(window_id)
        return handles

    def close_window(self, window_id, expected):
        """Close a retired window's dead managed pane: "window" when it was the only pane, else "pane".

        A window that holds panes a person added keeps them. The managed pane goes and the window stops
        being a managed one (its options are unset, `remain-on-exit` too) in one tmux command sequence."""
        meta = self.read_meta(_safe_text(window_id, "window handle"))
        keys = ("base", "target", "run_id", "project_id", "window_id", "pane_id")
        if not meta.get("run_id") or any(meta.get(key) != expected.get(key) for key in keys):
            raise SessionError("target_changed", "The window no longer holds the expected run.")
        server = self.server_identity()
        if any(meta.get(key) != value for key, value in server.items()):
            raise SessionError("tmux_owner_mismatch", "The window was restored or belongs to another server.")
        panes = self._run("list-panes", "-t", window_id, "-F", "#{pane_id}").splitlines()
        if meta["pane_id"] not in panes:
            raise SessionError("target_changed", "The window no longer holds the managed pane.",
                               details={"panes": panes})
        if not self.pane_info(meta["pane_id"])["pane_dead"]:
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

        The running server's version counts; with no server yet, the first `tmux` in PATH. A tree without
        the integration file has no minimum, and nothing is checked."""
        wanted = minimum_version()
        if wanted is None:
            return
        version = self._run("display-message", "-p", "#{version}", allow_missing=True)
        if not version:
            try:
                parts = subprocess.run(["tmux", "-V"], capture_output=True, text=True, timeout=10).stdout.split()
            except (OSError, subprocess.SubprocessError) as exc:
                raise SessionError("tmux_unavailable", "The tmux executable is unavailable.", 5) from exc
            version = parts[-1] if parts else ""
        if _version_number(version) < _version_number(wanted):
            raise SessionError(
                "tmux_too_old", f"agent-session needs tmux {wanted} or newer; this tmux is {version or 'of an unknown version'}. "
                f"Put {COMPANY_TMUX} first in PATH and restart the tmux server.", 5,
                {"version": version, "minimum": wanted, "company_tmux": COMPANY_TMUX})

    def install_exit_hook(self, python, library):
        """Make the tmux server run the wrap-up of a managed run whose pane died (`internal.finish_ended`).

        One server-wide `pane-died` hook element serves every project and run: it fires only for a pane that
        a managed window names as its own (`PANE_ID_OPTION`), and the wrap-up reads everything else from that
        window. It is an element of its own, so the hooks of a person's configuration still run (a window-scope
        hook would replace them). The command is written again at every launch with that launch's interpreter
        and library. Returns False, without a hook, when a path has a character the command cannot carry."""
        words = (str(python), str(library))
        if any(_HOOK_WORD.fullmatch(word) is None for word in words):
            return False
        shell = (f"exec env PYTHONPATH={words[1]} {words[0]} -m agent_session.internal finish-ended "
                 "#{socket_path} #{window_id} #{pane_id} >/dev/null 2>&1")
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

    def pane_info(self, pane_id):
        """The pane's fields. A dead pane may have no pane_pid (tmux 3.8 clears it); it is None then.

        Only fields that can never hold a tab are read: pane_current_path and pane_current_command
        are printed as is, so a tab in a directory name would shift every field after it."""
        fields = ("window_id", "pane_id", "pane_pid", "pane_dead", "pane_dead_status", "pane_dead_signal")
        raw = self._run("display-message", "-p", "-t", _safe_text(pane_id, "pane handle"),
                        "\t".join("#{" + field + "}" for field in fields))
        parts = raw.split("\t")
        if (len(parts) != len(fields) or parts[3] not in ("0", "1")
                or not (parts[2].isdigit() or (parts[2] == "" and parts[3] == "1"))):
            raise SessionError("tmux_unknown", "The managed pane observation is incomplete.", 4,
                               {"pane": pane_id, "raw": raw, "field_count": len(parts)})
        row = dict(zip(fields, parts))
        row["pane_pid"] = int(row["pane_pid"]) if row["pane_pid"] else None
        row["pane_dead"] = row["pane_dead"] == "1"
        row["pane_dead_status"] = int(row["pane_dead_status"]) if row["pane_dead_status"].isdigit() else None
        row["pane_dead_signal"] = row["pane_dead_signal"] or None
        return row

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

    def run_controller(self, script_path, cwd):
        """Ask the selected tmux server to run a fixed controller script."""
        script = Path(script_path).expanduser().resolve()
        cwd = Path(cwd).expanduser().resolve()
        if not script.is_file() or not cwd.is_dir():
            raise SessionError("tmux_input", "The controller script or working directory is unavailable.", 2)
        command = "cd " + shlex.quote(str(cwd)) + " && exec " + shlex.join(["/bin/bash", str(script)])
        self._run("run-shell", "-b", command)
        return {"submitted": True, "script": str(script), "cwd": str(cwd),
                "socket_path": self.effective_socket()}

    def find_by_session(self, project, session_id):
        if not self.has_session(project.project_id):
            return None
        owner = self._session_owner(project.project_id)
        if owner.get("base") != str(project.base):
            raise SessionError("tmux_owner_mismatch", "The tmux session belongs to another project base.")
        windows = self._run("list-windows", "-t", self._session_target(project.project_id), "-F", "#{window_id}").splitlines()
        found = []
        for window_id in dict.fromkeys(windows):
            meta = self.read_meta(window_id)
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
