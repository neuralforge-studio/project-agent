"""Who may move an item of a team project, and the Leader review a fixed CR needs before done.

Both rules apply only to a project with seats. The caller rule is agent-session's
(`agent_session.api.caller`); this module adds no second copy of it.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import registry, store
from .cr import accepted, section_text, submitted_hash
from .kinds import CR, Kind
from .errors import ItemError

COMMIT_RE = re.compile(r"[0-9a-f]{40}")


def require_leader(project) -> None:
    """Only this project's current Leader (checked against its live run) passes."""
    actor, _ = registry.caller(project)
    if actor != "leader":
        raise ItemError("role_denied", f"Only the current Leader of '{project.project_id}' may do this; "
                        f"the caller is {actor}.")


def _is_leader_name(by: str | None) -> bool:
    return bool(by) and by.strip().casefold() == "leader"


def _origin_main_has(base: Path, commit: str) -> str | None:
    """None when origin/main of the base holds the commit, else why not."""
    fetched = subprocess.run(["git", "-C", str(base), "fetch", "--quiet", "origin", "main"],
                             capture_output=True, text=True)
    if fetched.returncode:
        return f"origin/main could not be fetched: {fetched.stderr.strip()}"
    found = subprocess.run(["git", "-C", str(base), "merge-base", "--is-ancestor", commit,
                            "refs/remotes/origin/main"], capture_output=True, text=True)
    return None if found.returncode == 0 else f"the submitted commit {commit} is not on origin/main"


def _review_missing(project, text: str) -> list[str]:
    commit = submitted_hash(section_text(text, "Result"))
    if commit is None:
        return ["## Result has no top-level '- 제출 commit: <40-hex>' row"]
    missing = []
    if not accepted(section_text(text, "Disposition"), commit):
        missing.append(f"## Disposition has no Leader acceptance of {commit}; "
                       f"run `project-item accept <CR-ID> --commit {commit}`")
    reason = _origin_main_has(project.base, commit)
    if reason:
        missing.append(reason)
    return missing


def check_move(project, kind: Kind, root: Path, item_id: str, state: str, outcome: str | None,
               by: str | None) -> None:
    """Refuse a move the caller may not make or a fixed CR that was not reviewed.

    The caller holds root_lock(root). Nothing is written here.
    """
    source_state, path = store.find(kind, root, item_id)
    if source_state == "in-progress" or _is_leader_name(by):
        actor, _ = registry.caller(project)
        if actor not in ("leader", "operator"):
            raise ItemError("role_denied", f"Only the current Leader or an operator may move {item_id} "
                            f"out of {source_state}/; the caller is {actor}.")
        if _is_leader_name(by) and actor != "leader":
            raise ItemError("role_denied", "--by Leader is accepted only from the current Leader.")
    if kind is CR and source_state == "in-progress" and state == "done" and (outcome or "").split()[:1] == ["fixed"]:
        text = path.read_text(encoding="utf-8")
        if CR.fmt.parse_text(text, path, source_state).headers.get("Mode", "write") != "read-only":
            missing = _review_missing(project, text)
            if missing:
                raise ItemError("review_missing", f"{item_id} was not reviewed: " + "; ".join(missing))
