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

from agent_session.config import load_registry, resolve_project  # noqa: E402
from agent_session.errors import SessionError  # noqa: E402

LEGACY_PROGRAMS = TOOLS / "cr" / "programs.json"
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


def _overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def legacy_roots() -> dict[str, Path]:
    """CR roots of the legacy `cr` registry (programs not yet moved to the project registry)."""
    try:
        table = json.loads(LEGACY_PROGRAMS.read_text(encoding="utf-8"))["programs"]
    except FileNotFoundError:
        return {}
    return {name: (Path(entry["repo"]) / entry["cr_dir"]).resolve() for name, entry in table.items()}


def item_root(project, kind: str) -> Path:
    root = getattr(project, KEYS[kind])
    if root is None:
        raise ItemError("item_path_unset",
                        f"Project '{project.project_id}' has no {KEYS[kind]} in {project.config_path}.")
    for program, legacy in legacy_roots().items():
        if _overlap(root, legacy):
            raise ItemError("item_path_duplicate",
                            f"{KEYS[kind]} {root} overlaps the CR directory of program '{program}' "
                            f"in {LEGACY_PROGRAMS}. Remove the program there first.")
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
