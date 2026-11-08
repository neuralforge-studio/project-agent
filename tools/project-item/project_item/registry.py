"""Project selection and item roots.

The project registry (~/.codex/project.json) and its parser belong to agent-session
(docs/project-team/spec.md section 2). This module imports that parser from the sibling
tool directory, so that the registry has one parser.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2]
_AGENT_SESSION = str(TOOLS / "agent-session")
if _AGENT_SESSION not in sys.path:
    sys.path.insert(0, _AGENT_SESSION)

from agent_session.registry import load_registry, resolve_project, select_project, SessionError  # noqa: E402
from .api import item_root, _ROOT_KEYS as KEYS  # noqa: E402  (legacy root-key export)
from .errors import ItemError  # noqa: E402  (legacy import retains the same error type)


def _registry_error(error: SessionError) -> ItemError:
    return ItemError(error.code, error.message)


def projects(config=None) -> tuple:
    try:
        return load_registry(config)
    except SessionError as error:
        raise _registry_error(error) from error


def select(config=None, name=None, cwd=None):
    """The named project, or the project of the working directory (agent-session rule)."""
    try:
        return select_project(config, name, cwd)
    except SessionError as error:
        raise _registry_error(error) from error


def project_of_cwd(config=None, cwd=None):
    """The project of the working directory, or None outside every project."""
    try:
        return resolve_project(cwd, config)
    except SessionError:
        return None


def caller(project) -> tuple[str, str | None]:
    """The caller by agent-session's rule: "leader" or "seat-N" (checked against its live run),
    "operator" or "unmanaged-agent", with the conversation ID."""
    from agent_session import api

    try:
        actor, identity = api.caller(project)
        if actor == "leader" or actor.startswith("seat-"):
            api.require_live(project, actor, identity)
    except SessionError as error:
        raise _registry_error(error) from error
    return actor, identity


def sessions_dir() -> Path:
    return Path.home() / ".claude" / "sessions"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def owner_sessions(project) -> list[dict]:
    """Live interactive Claude Code sessions whose cwd is under the base or a seat, newest first."""
    roots = (project.base,) + tuple(project.seats)
    rows = []
    for path in sessions_dir().glob("*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if row.get("kind") != "interactive" or row.get("entrypoint") != "cli":
            continue
        if not isinstance(row.get("pid"), int) or not _alive(row["pid"]):
            continue
        try:
            cwd = Path(row.get("cwd", "")).resolve()
        except (OSError, RuntimeError):
            continue
        if any(cwd == root or root in cwd.parents for root in roots):
            rows.append(row)
    return sorted(rows, key=lambda r: r.get("startedAt", 0), reverse=True)
