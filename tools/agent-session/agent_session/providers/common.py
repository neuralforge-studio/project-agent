"""Small process and deadline helpers shared by the provider transports."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from ..errors import SessionError


class Deadline:
    def __init__(self, seconds):
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds <= 0:
            raise SessionError("invalid_timeout", "Timeout must be positive.", 2)
        self.end = time.monotonic() + seconds

    def remaining(self):
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise SessionError("provider_timeout", "The provider did not respond before the deadline.", 4)
        return remaining


def deadline(value):
    return value if isinstance(value, Deadline) else Deadline(value)


def executable(name, context=None):
    value = (context or {}).get("provider_executable") or shutil.which(name)
    if not value or not Path(value).is_file():
        raise SessionError("provider_not_found", f"The {name} CLI is not installed.", 5)
    return str(Path(value).resolve())


def clean_env(source=None):
    values = dict(os.environ if source is None else source)
    names = {
        "CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_CHILD_SESSION",
        "CLAUDE_CODE_SESSION_ATTENDED", "CODEX_THREAD_ID",
    }
    for name in list(values):
        if name in names or name.startswith("CLAUDE_CODE_MESSAGING_"):
            values.pop(name, None)
    return values


def run(argv, timeout, *, cwd=None, env=None):
    limit = deadline(timeout)
    try:
        result = subprocess.run(
            [str(value) for value in argv], cwd=cwd, env=env, capture_output=True,
            text=True, encoding="utf-8", timeout=limit.remaining(), check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise SessionError("provider_timeout", "The provider command timed out.", 4) from error
    except ValueError as error:
        raise SessionError("invalid_provider_input", "A provider argument or environment value is invalid.", 2) from error
    except OSError as error:
        raise SessionError("provider_command_failed", "The provider command could not start.", 5) from error
    if result.returncode:
        raise SessionError(
            "provider_command_failed", "The provider command failed.", 5,
            {"command": Path(str(argv[0])).name, "exit_code": result.returncode},
        )
    return result.stdout


def json_result(value, method):
    try:
        result = json.loads(value)
    except (ValueError, TypeError) as error:
        raise SessionError("provider_protocol_error", f"Invalid JSON from {method}.", 4) from error
    if not isinstance(result, dict):
        raise SessionError("provider_protocol_error", f"Invalid object from {method}.", 4)
    return result


def session_id(session):
    value = session.get("session_id") if isinstance(session, dict) else None
    if not isinstance(value, str) or not value:
        raise SessionError("session_not_bound", "The provider session is not registered.", 3)
    return value


def context_timeout(context, default=30):
    return context.get("timeout", default)


def text_file(path, field):
    try:
        value = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError, TypeError) as error:
        raise SessionError("invalid_provider_input", f"Cannot read {field}.", 2) from error
    if not value.strip():
        raise SessionError("invalid_provider_input", f"{field} is empty.", 2)
    return value
