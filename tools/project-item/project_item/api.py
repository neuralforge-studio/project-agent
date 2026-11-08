"""Public item operations used by Session, Board, and tmux integrations.

Paths are registered item roots. Item formats, locks, transitions, and page writes
remain owned by their existing modules. This boundary does not load a registry,
identify a caller, control a session, or send a notification.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import assign, render, store
from . import decide
from .cr import submitted_hash
from .errors import ItemError
from .kinds import CR, DECIDE

MAX_DECISION_ANSWER_BYTES = store.MAX_DECISION_ANSWER_BYTES
_ROOT_KEYS = {"cr": "path_cr", "decide": "path_decide"}
__all__ = ["ItemError", "MAX_DECISION_ANSWER_BYTES", "CR", "DECIDE", "submitted_hash",
           "item_root", "cr_items", "read_cr_markdown", "decision_items", "answer_decision",
           "open_decisions", "lookup_cr", "claim_cr", "unclaim_cr", "set_cr_base", "sync_cr_result"]


def item_root(project, kind: str) -> Path:
    """Read the configured item root without creating a default path."""
    key = _ROOT_KEYS[kind]
    root = getattr(project, key)
    if root is None:
        raise ItemError("item_path_unset",
                        f"Project '{project.project_id}' has no {key} in {project.config_path}.")
    return root


def cr_items(root: Path, states=("open", "todo", "in-progress")) -> dict[str, list[dict]]:
    """Read CR identities and source facts grouped by their state directories."""
    result = {}
    for state in states:
        rows = []
        for path in store.item_files(CR, root, state):
            parsed = CR.fmt.parse(path, state)
            rows.append({"id": parsed.cr_id or path.stem, "title": parsed.title or path.stem,
                         "state": state, "path": str(path), "headers": parsed.headers,
                         "sections": dict(render.sections(path)) if state == "in-progress" else {}})
        result[state] = rows
    return result


def read_cr_markdown(root: Path, item: dict, state: str) -> str:
    """Read a listed CR only from the given root, state, and CR identity."""
    if state not in CR.states or item.get("state") != state or not item.get("path"):
        raise ValueError("CR 목록 경로가 유효하지 않습니다.")
    path = Path(item["path"]).resolve(strict=True)
    if not path.is_relative_to(Path(root).resolve() / state) or store.file_id(CR, path) != item.get("id"):
        raise ValueError("CR 목록 밖의 파일은 읽을 수 없습니다.")
    return path.read_text(encoding="utf-8")


def decision_items(root: Path, cr_root: Path | None = None, states=None) -> list[dict]:
    """Read decision facts and derived progress. Errors stay local to the requested root.

    ``states=("open",)`` reads only waiting decisions, so a status consumer need not
    read closed history. Omit states to include all decision states.
    """
    items = []
    cr_states = render.cr_states(cr_root)
    for state in DECIDE.states if states is None else states:
        for path in store.item_files(DECIDE, root, state):
            parsed = DECIDE.fmt.parse(path, state)
            item = {"id": parsed.item_id or path.stem, "title": parsed.title or path.stem,
                    "path": str(path.resolve()), "state": state, "headers": parsed.headers,
                    "sections": render.sections(path)}
            item["display_state"] = render.decision_stage(item, cr_states)
            items.append(item)
    return items


def open_decisions(root: Path) -> dict[str, str]:
    """Read waiting IDs for a status consumer, retaining IDs whose title cannot be read.

    A root/listing failure propagates to the caller. A single title read or parse
    failure yields an empty title, so status counts preserve the observed file ID.
    """
    result = {}
    for path in store.item_files(DECIDE, root, "open"):
        item_id = store.file_id(DECIDE, path) or path.stem
        try:
            title = decide.parse(path, "open").title or ""
        except (OSError, ValueError):
            title = ""
        result[item_id] = title
    return result


def answer_decision(project, decide_id: str, answer: str) -> dict:
    """Save one answer, then refresh its page. A page failure does not undo receipt.

    The integration must authorize its caller before this domain operation. ItemError
    reports a rejected answer; ``page_error`` reports an advisory refresh failure.
    """
    root = item_root(project, "decide")
    path = store.answer_decide(root, decide_id, answer)
    page_error = None
    try:
        render.render(project.project_id, root, cr_root=project.path_cr)
    except Exception as error:
        page_error = {"code": getattr(error, "code", type(error).__name__),
                      "message": getattr(error, "message", str(error))}
    return {"path": str(path), "page_error": page_error}


def lookup_cr(root: Path, cr_id: str) -> dict:
    """Read the locked CR assignment model, including its authoritative text."""
    return assign.lookup(root, cr_id)


def claim_cr(root: Path, cr_id: str) -> dict:
    """Claim todo into in-progress under the item-root lock."""
    return assign.claim(root, cr_id)


def unclaim_cr(root: Path, cr_id: str) -> None:
    """Undo a failed assignment without changing a CR that has already moved."""
    assign.unclaim(root, cr_id)


def set_cr_base(root: Path, cr_id: str, base: dict | None) -> None:
    """Write the assignment baseline using the existing CR validation and lock."""
    assign.set_base(root, cr_id, base)


def _result_parts(text: str) -> tuple[str, str, str]:
    matches = list(re.finditer(r"^## Result[ \t]*$", text, re.MULTILINE))
    if len(matches) != 1:
        raise ItemError("remote_result_invalid", "The CR must have one Result section.")
    start = matches[0].end()
    following = re.search(r"^## ", text[start:], re.MULTILINE)
    end = start + following.start() if following else len(text)
    return text[:start], text[start:end], text[end:]


def sync_cr_result(root: Path, cr_id: str, original: str, updated: str,
                   previous: str | None = None) -> str:
    """Replace only Result while preserving concurrent changes outside that section.

    Return the saved Result body for the caller's next conflict check. A changed
    authoritative Result or a CR that left in-progress is refused under the root lock.
    """
    before, result, after = _result_parts(updated)
    old_before, old_result, old_after = _result_parts(original)
    if (before, after) != (old_before, old_after):
        raise ItemError("remote_result_invalid", "A Worker may return only the CR Result section.")
    with store.root_lock(root):
        item = assign._lookup(root, cr_id)
        if item["state"] != "in-progress":
            raise ItemError("target_changed", "The CR left in-progress before the remote report.")
        current_before, current_result, current_after = _result_parts(item["text"])
        if current_result not in (old_result if previous is None else previous, result):
            raise ItemError("remote_result_conflict", "The authoritative Result changed; preserve both reports.")
        Path(item["path"]).write_text(current_before + result + current_after, encoding="utf-8")
    return result
