"""CR assignment calls for agent-session: look up a CR, claim it into in-progress, and keep
its Base header. Each call holds the item root lock once and never calls a function that takes
the lock again (the lock is not reentrant)."""
from __future__ import annotations

from pathlib import Path

from . import store
from .kinds import CR
from .errors import ItemError


def lookup(root: Path, cr_id: str) -> dict:
    """The CR as a JOB: id, state, path, title, mode, cwd, base and text."""
    with store.root_lock(root):
        return _lookup(root, cr_id)


def _lookup(root: Path, cr_id: str) -> dict:
    state, path = store.find(CR, root, cr_id)
    text = path.read_text(encoding="utf-8")
    item = CR.fmt.parse_text(text, path, state)
    if item.cr_id != cr_id:
        raise ItemError("item_invalid", f"{path} does not have the title '# {cr_id}: ...'.")
    headers = item.headers
    base = None
    if headers.get("Base"):
        commit, _, when = headers["Base"].partition(" ")
        base = {"base_hash": commit, "base_commit_time": when}
    return {"job_id": cr_id, "state": state, "path": str(path), "title": item.title,
            "mode": headers.get("Mode", "write"), "cwd": headers.get("Cwd", "."),
            "base": base, "text": text}


def claim(root: Path, cr_id: str) -> dict:
    """Move a todo CR to in-progress (an in-progress CR stays). Return the JOB after the move."""
    with store.root_lock(root):
        job = _lookup(root, cr_id)
        if job["state"] == "todo":
            path = Path(job["path"])
            store._relocate(CR, root, cr_id, "todo", path, "in-progress", path.read_text(encoding="utf-8"))
            job = _lookup(root, cr_id)
        elif job["state"] != "in-progress":
            raise ItemError("cr_not_assignable", f"{cr_id} is in {job['state']}/; assign a CR in todo/.")
        return job


def unclaim(root: Path, cr_id: str) -> None:
    """Undo claim(): move an in-progress CR back to todo without a Disposition entry."""
    with store.root_lock(root):
        state, path = store.find(CR, root, cr_id)
        if state == "in-progress":
            store._relocate(CR, root, cr_id, "in-progress", path, "todo", path.read_text(encoding="utf-8"))


def set_base(root: Path, cr_id: str, base: dict | None) -> None:
    """Write (or remove with None) the '- Base: <commit> <ISO time>' header of the CR."""
    with store.root_lock(root):
        state, path = store.find(CR, root, cr_id)
        value = None if base is None else f"{base['base_hash']} {base['base_commit_time']}"
        text = store.set_header(path.read_text(encoding="utf-8"), "Base", value)
        bad = CR.fmt.check(CR.fmt.parse_text(text, path, state))
        if bad:
            raise ItemError("format_invalid", f"{cr_id}: " + "; ".join(bad))
        path.write_text(text, encoding="utf-8")
