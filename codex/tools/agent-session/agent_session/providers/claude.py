"""Interactive Claude launch and the public cross-session MCP transport."""

import json
import os
from pathlib import Path
import re
import shlex
import time
import uuid

from ..errors import SessionError
from .common import context_timeout, deadline, executable, json_result, run, session_id, text_file
from .mcp import MCPClient


def _load_settings(path, required=False):
    path = Path(path)
    if not path.exists() and not required:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as error:
        raise SessionError("invalid_provider_input", "Cannot read Claude settings.", 2) from error
    if not isinstance(value, dict):
        raise SessionError("invalid_provider_input", "Claude settings must be an object.", 2)
    return value


def _merge(base, update):
    result = dict(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        elif isinstance(value, list) and isinstance(result.get(key), list):
            result[key] = result[key] + value
        else:
            result[key] = value
    return result


def _validate_args(values):
    flags = {"--model", "--effort", "--permission-mode", "--setting-sources"}
    switches = {"--dangerously-skip-permissions", "--allow-dangerously-skip-permissions", "--no-chrome", "--verbose"}
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise SessionError("invalid_provider_args", "Provider arguments must be strings.", 2)
    index = 0
    sources = {"user", "project", "local"}
    while index < len(values):
        key, separator, value = values[index].partition("=")
        if key in switches and not separator:
            index += 1
            continue
        if key not in flags:
            raise SessionError("invalid_provider_args", "Unsupported or structural Claude argument.", 2, {"argument": key})
        if not separator:
            index += 1
            if index >= len(values):
                raise SessionError("invalid_provider_args", "A Claude argument has no value.", 2, {"argument": key})
            value = values[index]
        if not value:
            raise SessionError("invalid_provider_args", "A Claude argument is empty.", 2, {"argument": key})
        if key == "--setting-sources":
            sources = set(value.split(","))
            if not sources <= {"user", "project", "local"}:
                raise SessionError("invalid_provider_args", "Unknown Claude settings source.", 2)
        index += 1
    return sources


def parse_peers(result):
    """Read the 2.1.317 listing's tmux locator, never a UUID-derived ref."""
    listing = result.get("listing")
    sections = result.get("sections")
    if not isinstance(listing, str) or not isinstance(sections, list):
        raise SessionError("provider_protocol_unsupported", "Claude returned an unsupported ListAgents format.", 4)
    output = []
    for section in sections:
        if not isinstance(section, dict) or section.get("kind") != "sessions":
            continue
        rows = section.get("rows")
        if not isinstance(rows, list):
            raise SessionError("provider_protocol_error", "Claude returned invalid session rows.", 4)
        for row in rows:
            if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key] for key in ("name", "ref", "status")):
                raise SessionError("provider_protocol_error", "Claude returned an invalid peer row.", 4)
            prefix = row["name"] + " [" + row["ref"] + "]"
            lines = [line.strip() for line in listing.splitlines() if line.strip().startswith(prefix + " ")]
            if len(lines) != 1:
                raise SessionError("provider_protocol_error", "Claude peer rows and listing do not agree.", 4)
            matches = re.findall(r"\btmux\s+(.+?):(@\d+)\.(%\d+)(?=\s*(?:·|$))", lines[0])
            if len(matches) != 1:
                # Non-tmux peers cannot be adopted by this manager.
                continue
            tmux_session, window_id, pane_id = matches[0]
            output.append({**row, "message_to": prefix, "tmux_session": tmux_session.strip(),
                           "window_id": window_id, "pane_id": pane_id})
    return output


class ClaudeProvider:
    name = "claude"
    mcp_factory = MCPClient

    def prepare_context(self, context):
        result = dict(context)
        cli = executable("claude", context)
        version = run([cli, "--version"], context_timeout(context)).strip()
        identity = str(uuid.uuid4())
        result.update({"provider_executable": cli, "provider_version": version,
                       "session_id": identity, "expected_session_id": identity, "endpoint": None})
        return result

    def registration_hooks(self, context):
        required = ("python", "library_path", "run_id", "config_path", "socket_path")
        if any(not context.get(key) for key in required):
            raise SessionError("invalid_provider_input", "Missing Claude hook launch context.", 2)
        identity = context.get("expected_session_id") or context.get("session_id")
        if not identity:
            raise SessionError("invalid_provider_input", "Missing expected Claude session UUID.", 2)
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from agent_session.internal import register_from_hook; "
            "register_from_hook(run_id=sys.argv[2],config_path=sys.argv[3],"
            "socket_path=sys.argv[4],expected_session_id=sys.argv[5])"
        )
        command = shlex.join([str(context["python"]), "-c", code, str(context["library_path"]),
                              str(context["run_id"]), str(context["config_path"]),
                              str(context["socket_path"]), identity])
        hooks = {}
        for event in ("SessionStart", "Stop", "StopFailure", "SessionEnd"):
            entry = {"hooks": [{"type": "command", "command": command, "timeout": 30}]}
            if event == "SessionStart":
                entry["matcher"] = "startup"
            hooks[event] = [entry]
        return hooks

    def _configuration(self, context, prepared, sources):
        paths = []
        if "user" in sources:
            paths.append(Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "settings.json")
        project_root = Path(context.get("seat_root", context["cwd"]))
        if "project" in sources:
            paths.append(project_root / ".claude/settings.json")
        if "local" in sources:
            paths.append(project_root / ".claude/settings.local.json")
        final = _load_settings(prepared.get("settings_file"), required=True)
        layers = [_load_settings(path) for path in paths] + [final]
        managed = context.get("managed_settings_file")
        if managed:
            layers.append(_load_settings(managed, required=True))
        else:
            for path in (Path("/etc/claude-code/managed-settings.json"), Path("/Library/Application Support/ClaudeCode/managed-settings.json")):
                if path.exists():
                    layers.append(_load_settings(path, required=True))
        effective = {}
        for layer in layers:
            if layer.get("crossSessionInbound") == "refuse":
                raise SessionError("needs_user_action", "Existing Claude settings refuse peer messages.", 3)
            deny = layer.get("permissions", {}).get("deny", [])
            if any(value in {"SendMessage", "ListAgents", "*"} for value in deny if isinstance(value, str)):
                raise SessionError("needs_user_action", "Existing Claude policy denies cross-session tools.", 3)
            effective = _merge(effective, layer)
        if effective.get("sandbox", {}).get("enabled") is True:
            raise SessionError("unsupported_sandbox", "Agent session v1 requires an already approved non-sandbox Claude configuration.", 3)
        if final.get("crossSessionInbound") != "accept":
            raise SessionError("invalid_provider_input", "The final Claude --settings file must enable peer delivery.", 2)
        hooks = final.get("hooks", {})
        if any(not isinstance(hooks.get(event), list) or not hooks[event] for event in ("SessionStart", "Stop", "StopFailure", "SessionEnd")):
            raise SessionError("invalid_provider_input", "The final Claude settings lack lifecycle hooks.", 2)
        env = prepared.get("env", {})
        if not isinstance(env, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in env.items()):
            raise SessionError("invalid_provider_input", "Invalid Claude environment values.", 2)
        settings_env = effective.get("env", {})
        if not isinstance(settings_env, dict):
            raise SessionError("invalid_provider_input", "Claude settings env is not an object.", 2)
        conflict = [key for key, value in env.items() if key in settings_env and settings_env[key] != value]
        if conflict:
            raise SessionError("env_policy_conflict", "Claude settings override required project environment values.", 3, {"names": conflict})
        if "CLAUDE_CODE_TMPDIR" in env and final.get("env", {}).get("CLAUDE_CODE_TMPDIR") != env["CLAUDE_CODE_TMPDIR"]:
            raise SessionError("env_policy_conflict", "CLAUDE_CODE_TMPDIR must also be present in final Claude settings env.", 3)
        return final

    def launch_spec(self, context, prepared):
        args = prepared.get("provider_args", [])
        sources = _validate_args(args)
        self._configuration(context, prepared, sources)
        identity = context.get("expected_session_id") or context.get("session_id")
        try:
            uuid.UUID(identity)
        except (ValueError, TypeError, AttributeError) as error:
            raise SessionError("invalid_provider_input", "Claude requires a new session UUID.", 2) from error
        prompt = text_file(prepared.get("prompt_file"), "initial prompt")
        argv = [executable("claude", context), "--session-id", identity,
                "--settings", str(Path(prepared["settings_file"]).resolve()), *args]
        if prepared.get("system_prompt_file"):
            text_file(prepared["system_prompt_file"], "system prompt")
            argv.extend(["--append-system-prompt-file", str(Path(prepared["system_prompt_file"]).resolve())])
        if prepared.get("provider_name"):
            argv.extend(["-n", prepared["provider_name"]])
        argv.append(prompt)
        return {"argv": argv, "env": dict(prepared.get("env", {})),
                "unset_env": list(prepared.get("unset_env", [])),
                "session_id": identity, "endpoint": None}

    def _peer(self, client, session, context, meta):
        identity = session_id(session)
        expected = context.get("expected_session_id") or meta.get("expected_session_id")
        if expected and expected != identity:
            raise SessionError("session_mismatch", "Claude UUID does not match the launch.", 3)
        recorded = meta.get("session_id")
        if not expected and not recorded:
            raise SessionError("session_not_bound", "Claude has no recorded launch UUID.", 3)
        if recorded and recorded != identity:
            raise SessionError("session_mismatch", "Claude UUID does not match the managed run.", 3)
        pane = meta.get("pane_id") or context.get("pane_id")
        window = meta.get("window_id") or context.get("window_id")
        tmux_session = meta.get("session_name") or meta.get("tmux_session") or context.get("project_id")
        if not pane or not window or not tmux_session:
            raise SessionError("session_not_bound", "Claude has no verified tmux locator.", 3)
        peers = parse_peers(client.tool("ListAgents", {}))
        matches = [peer for peer in peers if peer["pane_id"] == pane and peer["window_id"] == window and peer["tmux_session"] == tmux_session]
        name = context.get("provider_name") or meta.get("provider_name")
        if name and not session.get("message_to"):
            matches = [peer for peer in matches if peer["name"] == name]
        if len(matches) != 1:
            raise SessionError("session_not_bound", "Claude ListAgents does not identify one managed pane.", 3)
        return matches[0]

    def verify_binding(self, session, context, meta, timeout=30):
        limit = deadline(timeout)
        with self.mcp_factory([executable("claude", context), "mcp", "serve"], limit) as client:
            peer = self._peer(client, session, context, meta)
        return {"session_id": session_id(session), "message_to": peer["message_to"]}

    def send(self, session, text, context, timeout=30):
        meta = context.get("meta", {})
        limit = deadline(timeout)
        with self.mcp_factory([executable("claude", context), "mcp", "serve"], limit) as client:
            peer = self._peer(client, session, context, meta)
            try:
                result = client.tool("SendMessage", {"to": peer["message_to"], "summary": "Project team message", "message": text})
            except SessionError as error:
                if error.code != "provider_tool_rejected":
                    raise
                return {"disposition": "rejected", "accepted": False, "read": False}
        delivery = result.get("delivery") or result.get("status")
        if delivery in {"held", "rejected", "unknown"}:
            disposition = delivery
        elif result.get("success") is False:
            disposition = "rejected"
        elif result.get("success") is True:
            disposition = "accepted"
        else:
            disposition = "unknown"
        return {"disposition": disposition, "accepted": disposition == "accepted", "read": False,
                "session": {"session_id": session_id(session), "message_to": peer["message_to"]}}

    def _latest_meta(self, context, meta):
        if context.get("socket_path") and context.get("window_id"):
            from ..tmux import Tmux
            current = Tmux(socket_path=context["socket_path"]).read_meta(context["window_id"])
            if current.get("run_id") != meta.get("run_id"):
                raise SessionError("target_changed", "The Claude run changed while observing it.", 3)
            return current
        return meta

    def observe(self, session, context, meta=None, timeout=30):
        meta = meta or context.get("meta", {})
        peer = None
        try:
            with self.mcp_factory([executable("claude", context), "mcp", "serve"], timeout) as client:
                peer = self._peer(client, session, context, meta)
        except SessionError as error:
            if error.code != "session_not_bound" or not meta.get("pane_dead"):
                raise
        current = self._latest_meta(context, meta)
        observations = current.get("hook_observations", {})
        if not isinstance(observations, dict):
            raise SessionError("provider_protocol_error", "Invalid Claude hook observations.", 4)
        valid = {name: payload for name, payload in observations.items()
                 if isinstance(payload, dict) and payload.get("session_id") == session_id(session)}
        stopped = valid.get("Stop")
        if not isinstance(stopped, dict):
            stopped = valid.get("StopFailure")
        observed = isinstance(stopped, dict) and isinstance(stopped.get("background_tasks"), list) and isinstance(stopped.get("session_crons"), list)
        background = stopped["background_tasks"] + stopped["session_crons"] if observed else None
        if peer is None:
            ended = "SessionEnd" in valid
            return {"known": bool(ended and observed), "active_turn": False if ended else None,
                    "active_turn_ids": [], "pending": None, "background": background,
                    "idle": bool(ended), "terminal": bool(ended and observed and not background),
                    "pending_disposition": "unknown"}
        status = peer["status"].casefold()
        idle = status == "idle"
        return {"known": bool(observed), "active_turn": not idle, "active_turn_ids": [],
                "pending": None, "background": background, "idle": idle,
                "terminal": bool(idle and observed and not background),
                "pending_disposition": "unknown", "runtime_status": status}

    def request_stop(self, session, context, meta=None, timeout=30):
        # The controller waits for idle and sends /exit to its owned pane.
        return self.observe(session, context, meta, timeout)
