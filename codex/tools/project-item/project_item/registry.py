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

from agent_session import api  # noqa: E402
from agent_session.config import load_registry, resolve_project  # noqa: E402
from agent_session.errors import SessionError  # noqa: E402

KEYS = {"cr": "path_cr", "decide": "path_decide"}


class ItemError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


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
        if name is None:
            return resolve_project(cwd, config)
        for project in load_registry(config):
            if project.project_id == name:
                return project
    except SessionError as error:
        raise _registry_error(error) from error
    raise ItemError("project_not_found", f"No registered project is named '{name}'.")


def project_of_cwd(config=None, cwd=None):
    """The project of the working directory, or None outside every project."""
    try:
        return resolve_project(cwd, config)
    except SessionError:
        return None


def caller(project) -> tuple[str, str | None]:
    """The caller by agent-session's rule: "leader" or "seat-N" (checked against its live run),
    "operator" or "unmanaged-agent", with the conversation ID."""
    try:
        actor, identity = api.caller(project)
        if actor == "leader" or actor.startswith("seat-"):
            api.require_live(project, actor, identity)
    except SessionError as error:
        raise _registry_error(error) from error
    return actor, identity


def item_root(project, kind: str) -> Path:
    root = getattr(project, KEYS[kind])
    if root is None:
        raise ItemError("item_path_unset",
                        f"Project '{project.project_id}' has no {KEYS[kind]} in {project.config_path}.")
    return root


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
