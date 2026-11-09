"""Interactive Codex TUI launch and exact-thread app-server control."""

import fnmatch
import json
import os
from pathlib import Path
import re
import time
import tomllib

from ..errors import SessionError
from .. import remote
from .common import (clean_env, context_timeout, deadline, executable, json_result, last_record_time, run,
                     session_id, text_file)
from .websocket import WebSocketRPC


TERMINAL_TURNS = {"completed", "interrupted", "failed"}
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LAUNCH_CONFIG_KEYS = ("sandbox_mode", "shell_environment_policy")
TRUST_LOCK_SECONDS = 5


def _trust_text(original, path):
    """Add one trust value without rewriting other TOML settings or comments."""
    try:
        data = tomllib.loads(original)
    except tomllib.TOMLDecodeError:
        return None
    projects = data.get("projects", {})
    if not isinstance(projects, dict):
        return None
    entry = projects.get(path)
    if entry is not None and not isinstance(entry, dict):
        return None
    if entry is not None and "trust_level" in entry:
        return original if entry["trust_level"] == "trusted" else None
    if entry is None:
        revised = original + ("\n" if original and not original.endswith("\n") else "")
        revised += f'\n[projects.{json.dumps(path)}]\ntrust_level = "trusted"\n'
    else:
        revised = None
        offset = 0
        for line in original.splitlines(keepends=True):
            header = re.fullmatch(r"\s*\[(?!\[)(.*)\]\s*(?:#.*)?", line.rstrip("\r\n"))
            if header:
                try:
                    section = tomllib.loads(f"[{header.group(1)}]\n")
                except tomllib.TOMLDecodeError:
                    section = {}
                if section.get("projects", {}).get(path) == {}:
                    end = offset + len(line)
                    revised = (original[:end] + ("" if line.endswith("\n") else "\n")
                               + 'trust_level = "trusted"\n' + original[end:])
                    break
            offset += len(line)
        if revised is None:
            return None
    try:
        if tomllib.loads(revised)["projects"][path]["trust_level"] == "trusted":
            return revised
    except (KeyError, TypeError, tomllib.TOMLDecodeError):
        pass
    return None


def trust_workspace(path, wait=TRUST_LOCK_SECONDS):
    """Record trust for an approved Codex workspace in the user's config."""
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    config = (home / "config.toml").resolve()
    try:
        config.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    lock = config.with_name(config.name + ".agent-session.lock")
    end = time.monotonic() + wait
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= end:
                return False
            time.sleep(0.05)
        except OSError:
            return False
    temporary = config.with_name(f".{config.name}.agent-session-{os.getpid()}-{time.time_ns()}")
    try:
        original = config.read_text(encoding="utf-8") if config.exists() else ""
        previous = config.stat() if config.exists() else None
        revised = _trust_text(original, str(Path(path).resolve()))
        if revised is None:
            return False
        if revised == original:
            return True
        mode = previous.st_mode & 0o777 if previous else 0o600
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(revised)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        current = config.stat() if config.exists() else None
        if (previous is None) != (current is None) or (previous and current and
                (previous.st_ino, previous.st_mtime_ns, previous.st_size) !=
                (current.st_ino, current.st_mtime_ns, current.st_size)):
            return False
        os.replace(temporary, config)
        return True
    except (OSError, UnicodeError):
        return False
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass
        try:
            lock.rmdir()
        except OSError:
            pass


def _merge(base, update):
    result = dict(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _merge_configuration(base, update):
    """Keep Codex's filter format replacement and case-insensitive map merge."""
    policy_update = update.get("shell_environment_policy")
    if not isinstance(policy_update, dict):
        return _merge(base, update)
    legacy_keys = ("include_only", "exclude")
    has_filters = policy_update.get("filters") is not None
    has_legacy = any(policy_update.get(key) is not None for key in legacy_keys)
    if has_filters and has_legacy:
        raise SessionError("env_policy_conflict", "Do not mix legacy environment arrays and filters in one config layer.", 3)
    result = _merge(base, update)
    policy = dict(result["shell_environment_policy"])
    if has_filters:
        for key in legacy_keys:
            policy.pop(key, None)
        previous = base.get("shell_environment_policy")
        old_filters = previous.get("filters") if isinstance(previous, dict) else None
        new_filters = policy_update["filters"]
        if isinstance(old_filters, dict) and isinstance(new_filters, dict):
            policy["filters"] = {key.casefold(): value for key, value in old_filters.items()}
            policy["filters"].update({key.casefold(): value for key, value in new_filters.items()})
    elif has_legacy:
        policy.pop("filters", None)
    result["shell_environment_policy"] = policy
    return result


def _profile_configuration(config, layers, profile):
    """Resolve launch checks with a replacement profile and the native layer order."""
    if layers is None:
        raise SessionError("provider_protocol_unsupported", "Codex profile validation requires config layers.", 3)
    if not isinstance(layers, list):
        raise SessionError("provider_protocol_error", "Codex config layers must be an array.", 4)
    resolved = {}
    user_seen = False
    # config/read returns layers from highest to lowest precedence.
    for layer in reversed(layers):
        if not isinstance(layer, dict):
            raise SessionError("provider_protocol_error", "A Codex config layer is invalid.", 4)
        if layer.get("disabledReason") is not None:
            continue
        source, values = layer.get("name"), layer.get("config")
        if (not isinstance(source, dict) or not isinstance(source.get("type"), str)
                or not source["type"] or not isinstance(values, dict)):
            raise SessionError("provider_protocol_error", "A Codex config layer has invalid source or values.", 4)
        kind = source["type"]
        if kind == "user" and source.get("profile") is not None:
            continue
        if kind in {"project", "sessionFlags"} and not user_seen:
            raise SessionError("provider_protocol_unsupported", "Codex config layers do not locate the user profile.", 3)
        if kind == "user" and user_seen:
            raise SessionError("provider_protocol_error", "Codex returned multiple base user config layers.", 4)
        resolved = _merge_configuration(resolved, {key: values[key] for key in _LAUNCH_CONFIG_KEYS if key in values})
        if kind == "user":
            user_seen = True
            resolved = _merge_configuration(resolved, {key: profile[key] for key in _LAUNCH_CONFIG_KEYS if key in profile})
    if not user_seen:
        raise SessionError("provider_protocol_unsupported", "Codex did not return an active base user config layer.", 3)
    # A key absent after replay must not retain the daemon's previous profile value.
    result = {key: value for key, value in config.items() if key not in _LAUNCH_CONFIG_KEYS}
    result.update(resolved)
    return result


def _toml_value(text):
    try:
        import tomllib
        return tomllib.loads("value = " + text)["value"]
    except ImportError:
        try:
            return json.loads(text)
        except ValueError:
            return text
    except (ValueError, KeyError):
        return text


def _put(config, key, value):
    # Config override paths use TOML-style quoted keys for exact filter names.
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"|([^.]+)', key)
    names = []
    for quoted, plain in parts:
        names.append(json.loads('"' + quoted + '"') if quoted else plain)
    if not names or any(not name for name in names):
        raise SessionError("invalid_provider_args", "Invalid Codex config override key.", 2)
    current = config
    for name in names[:-1]:
        current = current.setdefault(name, {})
        if not isinstance(current, dict):
            raise SessionError("invalid_provider_args", "Conflicting Codex config override keys.", 2)
    current[names[-1]] = value


def _arguments(values):
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise SessionError("invalid_provider_args", "Provider arguments must be strings.", 2)
    flags = {
        "--model", "-m", "--profile", "-p", "--sandbox", "-s",
        "--ask-for-approval", "-a", "--config", "-c", "--enable", "--disable",
    }
    switches = {"--dangerously-bypass-approvals-and-sandbox", "--strict-config", "--no-alt-screen"}
    parsed = {"overrides": {}, "profile": None, "sandbox": None, "bypass": False}
    index = 0
    while index < len(values):
        token = values[index]
        key, separator, inline = token.partition("=")
        if key in switches and not separator:
            if key == "--dangerously-bypass-approvals-and-sandbox":
                parsed["bypass"] = True
            index += 1
            continue
        if key not in flags:
            raise SessionError("invalid_provider_args", "Unsupported or structural Codex argument.", 2, {"argument": key})
        if separator:
            value = inline
        else:
            index += 1
            if index >= len(values):
                raise SessionError("invalid_provider_args", "A Codex argument has no value.", 2, {"argument": key})
            value = values[index]
        if not value:
            raise SessionError("invalid_provider_args", "A Codex argument is empty.", 2, {"argument": key})
        if key in {"--config", "-c"}:
            name, equal, literal = value.partition("=")
            if not equal:
                raise SessionError("invalid_provider_args", "Codex config override requires key=value.", 2)
            _put(parsed["overrides"], name, _toml_value(literal))
        elif key in {"--profile", "-p"}:
            if parsed["profile"] is not None:
                raise SessionError("invalid_provider_args", "Specify one Codex profile.", 2)
            parsed["profile"] = value
        elif key in {"--sandbox", "-s"}:
            parsed["sandbox"] = value
        index += 1
    if parsed["bypass"] and parsed["sandbox"] not in {None, "danger-full-access"}:
        raise SessionError("invalid_provider_args", "Conflicting Codex sandbox arguments.", 2)
    return parsed


class CodexProvider:
    name = "codex"
    rpc_factory = WebSocketRPC

    def prepare_context(self, context):
        result = dict(context)
        cli = executable("codex", context)
        limit = deadline(context_timeout(context))
        info = json_result(run([cli, "app-server", "daemon", "version"], limit), "daemon version")
        if info.get("status") != "running":
            if not context.get("allow_daemon_start", False):
                raise SessionError("provider_not_running", "Start the user's Codex daemon before launching a TUI.", 3)
            run([cli, "app-server", "daemon", "start"], limit)
            while True:
                info = json_result(run([cli, "app-server", "daemon", "version"], limit), "daemon version")
                if info.get("status") == "running":
                    break
                time.sleep(min(0.1, limit.remaining()))
        socket_path = info.get("socketPath")
        if not isinstance(socket_path, str) or not Path(socket_path).is_absolute():
            raise SessionError("provider_protocol_error", "Codex did not report its app-server socket.", 4)
        result.update({
            "provider_executable": cli, "endpoint": "unix://" + str(Path(socket_path).resolve()),
            "session_id": None, "provider_version": info.get("appServerVersion"),
        })
        return result

    def trust_new_seat(self, root):
        return trust_workspace(root)

    def trust_base(self, root):
        return trust_workspace(root)

    def moved_to(self, session_id):
        """Codex has no background-session handoff."""
        return None

    def startup_dialog(self, screen):
        if re.search(r"\bFolder access\b", screen) and re.search(r"\bTrust this folder\?", screen):
            return "workspace_trust"
        return None

    def last_record(self, session_id):
        """When this thread's session file last got a record: `{"at": epoch seconds or None, "reason": ...}`.

        Codex keeps `$CODEX_HOME/sessions/<year>/<month>/<day>/rollout-<start time>-<thread id>.jsonl`, whose
        lines carry a `timestamp`. No Codex session file was available when this was written, so this layout
        is the documented behavior of Codex, not an observed one."""
        if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9-]+", session_id):
            return {"at": None, "reason": "transcript_not_found"}
        root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser() / "sessions"
        try:
            files = list(root.glob(f"*/*/*/rollout-*-{session_id}.jsonl"))
            if not files:
                return {"at": None, "reason": "transcript_not_found"}
            at = last_record_time(max(files, key=lambda path: path.stat().st_mtime))
        except OSError:
            return {"at": None, "reason": "transcript_unreadable"}
        return {"at": at, "reason": None if at is not None else "no_record_with_time"}

    def registration_hooks(self, context):
        # SessionStart alone does not prove which tmux run created a thread.
        return {}

    def _configuration(self, context, parsed, limit):
        profile = parsed["profile"]
        with self.rpc_factory(context["endpoint"], limit) as rpc:
            response = rpc.call("config/read", {"cwd": str(context["cwd"]), "includeLayers": bool(profile)})
        config = response.get("config")
        if not isinstance(config, dict):
            raise SessionError("provider_protocol_error", "Codex did not return effective configuration.", 4)
        if profile:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", profile):
                raise SessionError("invalid_provider_args", "Invalid Codex profile name.", 2)
            codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
            path = codex_home / (profile + ".config.toml")
            try:
                import tomllib
                with path.open("rb") as handle:
                    layer = tomllib.load(handle)
            except ImportError as error:
                raise SessionError("provider_protocol_unsupported", "Codex profile validation needs Python 3.11 or newer.", 3) from error
            except (OSError, ValueError) as error:
                raise SessionError("invalid_provider_args", "Cannot read the selected Codex profile v2 file.", 2) from error
            config = _profile_configuration(config, response.get("layers"), layer)
        return _merge_configuration(config, parsed["overrides"])

    def _environment_arguments(self, prepared, config, parsed):
        values = prepared.get("env", {})
        remove = prepared.get("unset_env", [])
        if not isinstance(values, dict) or any(not isinstance(key, str) or not _ENV_NAME.fullmatch(key) or not isinstance(value, str) or "\0" in value for key, value in values.items()):
            raise SessionError("invalid_provider_input", "Invalid provider environment values.", 2)
        if not isinstance(remove, list) or any(not isinstance(key, str) or not _ENV_NAME.fullmatch(key) for key in remove):
            raise SessionError("invalid_provider_input", "Environment removal requires exact variable names.", 2)
        if set(values) & set(remove):
            raise SessionError("env_policy_conflict", "A provider variable is both set and removed.", 3)
        policy = config.get("shell_environment_policy") or {}
        if not isinstance(policy, dict):
            raise SessionError("env_policy_conflict", "Invalid shell environment policy.", 3)
        existing_set = policy.get("set") or {}
        if not isinstance(existing_set, dict):
            raise SessionError("env_policy_conflict", "Invalid configured shell environment values.", 3)
        removed = {key.casefold() for key in remove}
        if removed & {key.casefold() for key in existing_set}:
            raise SessionError("env_policy_conflict", "Configured environment values would restore a removed variable.", 3)
        command_policy = parsed["overrides"].get("shell_environment_policy", {})
        if remove and isinstance(command_policy, dict) and any(key in command_policy for key in ("exclude", "include_only")):
            raise SessionError("env_policy_conflict", "Do not mix legacy environment arrays and filters in one CLI layer.", 3)
        if remove and any(policy.get(key) is not None for key in ("exclude", "include_only")):
            raise SessionError("env_policy_conflict", "Required environment removals would replace configured legacy filters.", 3)
        filters = policy.get("filters") or {}
        if not isinstance(filters, dict):
            raise SessionError("env_policy_conflict", "Invalid environment filters.", 3)
        includes = [key for key, mode in filters.items() if mode == "include"]
        legacy_includes = policy.get("include_only")
        if legacy_includes is not None:
            if not isinstance(legacy_includes, list) or any(not isinstance(value, str) for value in legacy_includes):
                raise SessionError("env_policy_conflict", "Invalid environment allowlist.", 3)
            includes.extend(legacy_includes)
        if includes:
            missing = [key for key in values if not any(fnmatch.fnmatchcase(key.casefold(), pattern.casefold()) for pattern in includes)]
            if missing:
                raise SessionError("env_policy_conflict", "The environment allowlist blocks required project variables.", 3, {"names": missing})
        output = []
        for key, value in values.items():
            output.extend(["-c", "shell_environment_policy.set." + key + "=" + json.dumps(value, ensure_ascii=False)])
        for key in remove:
            output.extend(["-c", "shell_environment_policy.filters." + json.dumps(key) + '="exclude"'])
        return output

    def launch_spec(self, context, prepared):
        if prepared.get("settings_file") is not None:
            raise SessionError("invalid_provider_input", "Codex does not have a --settings file.", 2)
        args = prepared.get("provider_args", [])
        parsed = _arguments(args)
        limit = deadline(context_timeout(context))
        config = self._configuration(context, parsed, limit)
        sandbox = "danger-full-access" if parsed["bypass"] else parsed["sandbox"] or config.get("sandbox_mode")
        if sandbox != "danger-full-access":
            raise SessionError("unsupported_sandbox", "Agent session v1 requires an already approved non-sandbox Codex configuration.", 3)
        env_args = self._environment_arguments(prepared, config, parsed)
        prompt = text_file(prepared.get("prompt_file"), "initial prompt")
        argv = [executable("codex", context), "--remote", context["endpoint"],
                "--cd", str(Path(context["cwd"]).resolve()), *args, *env_args, prompt]
        return {"argv": argv, "env": dict(prepared.get("env", {})),
                "unset_env": list(prepared.get("unset_env", [])), "session_id": None,
                "endpoint": context["endpoint"]}

    def _thread(self, rpc, session, context):
        identity = session_id(session)
        result = rpc.call("thread/read", {"threadId": identity, "includeTurns": False})
        thread = result.get("thread")
        if not isinstance(thread, dict) or thread.get("id") != identity:
            raise SessionError("session_mismatch", "Codex returned a different thread.", 3)
        cwd = thread.get("cwd")
        if not isinstance(cwd, str) or Path(cwd).resolve() != Path(context["cwd"]).resolve():
            raise SessionError("session_mismatch", "The Codex thread has a different working directory.", 3)
        status = thread.get("status")
        if not isinstance(status, dict) or status.get("type") not in {"active", "idle", "notLoaded", "systemError"}:
            raise SessionError("provider_protocol_error", "Codex did not report a known runtime status.", 4)
        return thread

    def _endpoint(self, session, context):
        value = session.get("endpoint")
        if not isinstance(value, str) or value != context.get("endpoint", value):
            raise SessionError("session_mismatch", "The Codex endpoint does not match the managed TUI.", 3)
        return value

    def verify_binding(self, session, context, meta, timeout=30):
        endpoint = self._endpoint(session, context)
        recorded = meta.get("session_id")
        if recorded and recorded != session_id(session):
            raise SessionError("session_mismatch", "The Codex thread differs from the recorded run.", 3)
        if meta.get("remote_seat") or context.get("remote_seat"):
            remote.run_call({**context, **meta}, "check_binding", timeout=timeout)
            return dict(session)
        with self.rpc_factory(endpoint, timeout) as rpc:
            self._thread(rpc, session, context)
        return {"session_id": session_id(session), "endpoint": endpoint}

    def send(self, session, text, context, timeout=30):
        limit = deadline(timeout)
        endpoint = self._endpoint(session, context)
        if context.get("remote_seat"):
            result = remote.run_call(context, "send", {"message": text}, timeout=timeout)
            return {**result, "session": dict(session)}
        with self.rpc_factory(endpoint, limit) as rpc:
            thread = self._thread(rpc, session, context)
            if thread["status"]["type"] == "notLoaded":
                raise SessionError("session_not_running", "The Codex thread is not loaded.", 3)
        run([executable("codex", context), "queue", "--remote", endpoint,
                      "--thread", session_id(session), "--message", text], limit,
                     cwd=context["cwd"], env=clean_env())
        # Queue's successful exit acknowledges intake, not processing or consent.
        return {"disposition": "accepted", "accepted": True, "read": False,
                "session": dict(session)}

    def _observe(self, rpc, session, context, meta=None):
        thread = self._thread(rpc, session, context)
        identity = session_id(session)
        turns = rpc.pages("thread/turns/list", {"threadId": identity, "itemsView": "summary", "sortDirection": "desc"})
        active = []
        for turn in turns:
            if not isinstance(turn, dict) or turn.get("status") not in TERMINAL_TURNS | {"inProgress"} or not isinstance(turn.get("id"), str):
                raise SessionError("provider_protocol_error", "Invalid Codex turn observation.", 4)
            if turn["status"] == "inProgress":
                active.append(turn["id"])
        latest_turn_id = turns[0]["id"] if turns else None
        pending = rpc.pages("thread/queue/list", {"threadId": identity})
        if any(not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in pending):
            raise SessionError("provider_protocol_error", "Invalid Codex pending input observation.", 4)
        background = None
        background_known = False
        background_source = "unavailable"
        if thread["status"]["type"] != "notLoaded":
            try:
                background = rpc.pages("thread/backgroundTerminals/list", {"threadId": identity})
            except SessionError as error:
                if error.code != "provider_rpc_error" or error.details.get("rpc_code") != -32600:
                    raise
                # A loaded TUI can exit after thread/read and before this query.
                if self._thread(rpc, session, context)["status"]["type"] != "notLoaded":
                    raise
            else:
                if any(not isinstance(item, dict) or not isinstance(item.get("processId"), str) for item in background):
                    raise SessionError("provider_protocol_error", "Invalid Codex background observation.", 4)
                background_known = True
                background_source = "loaded"
        thread = self._thread(rpc, session, context)
        busy = bool(active) or thread["status"]["type"] == "active"
        evidence = (meta or {}).get("last_background_clear")
        run_id = context.get("run_id")
        matching_clear = (
            isinstance(evidence, dict) and isinstance(run_id, str) and bool(run_id)
            and (meta or {}).get("run_id") == run_id
            and evidence.get("run_id") == run_id and evidence.get("session_id") == identity
            and "latest_turn_id" in evidence and evidence["latest_turn_id"] == latest_turn_id
        )
        if (not background_known and thread["status"]["type"] == "notLoaded"
                and not busy and not pending and matching_clear):
            background = []
            background_known = True
            background_source = "last_loaded_clear"
        return {"known": background_known, "active_turn": busy, "active_turn_ids": active,
                "latest_turn_id": latest_turn_id,
                "pending": pending, "background": background,
                "background_known": background_known, "background_source": background_source,
                "idle": not busy and not pending,
                "terminal": background_known and not busy and not pending and not background,
                "runtime_status": thread["status"]["type"]}

    def observe(self, session, context, meta=None, timeout=30):
        if context.get("remote_seat") or (meta or {}).get("remote_seat"):
            self._endpoint(session, context)
            return remote.run_call({**context, **(meta or {})}, "observe", timeout=timeout)
        with self.rpc_factory(self._endpoint(session, context), timeout) as rpc:
            return self._observe(rpc, session, context, meta)

    def request_stop(self, session, context, meta=None, timeout=30):
        limit = deadline(timeout)
        identity = session_id(session)
        if context.get("remote_seat") or (meta or {}).get("remote_seat"):
            self._endpoint(session, context)
            return remote.run_call({**context, **(meta or {})}, "request_stop", timeout=timeout)
        with self.rpc_factory(self._endpoint(session, context), limit) as rpc:
            observed = self._observe(rpc, session, context, meta)
            for item in observed["pending"]:
                try:
                    rpc.call("thread/queue/delete", {"threadId": identity, "queuedSubmissionId": item["id"]})
                except SessionError:
                    # Intake may have moved this item into an active turn.
                    remaining = rpc.pages("thread/queue/list", {"threadId": identity})
                    if any(value.get("id") == item["id"] for value in remaining):
                        raise
            for turn_id in observed["active_turn_ids"]:
                try:
                    rpc.call("turn/interrupt", {"threadId": identity, "turnId": turn_id})
                except SessionError:
                    current = self._observe(rpc, session, context, meta)
                    if turn_id in current["active_turn_ids"]:
                        raise
            return self._observe(rpc, session, context, meta)

    def request_exit(self, meta, tmux):
        if meta.get("remote_seat"):
            return remote.run_call(meta, "request_exit")
        # The idle TUI gets /exit and Enter in its owned pane until its SIGTERM exit is verified.
        tmux.send_exit(meta["pane_id"])
