"""CR files as JOBs. The CR root comes from the project registry (path_cr); the format and the
in-progress move belong to the sibling project-item tool. No project code runs here."""

import re
import sys
from pathlib import Path

from .errors import SessionError

_PROJECT_ITEM = str(Path(__file__).resolve().parents[2] / "project-item")
JOB_ID = re.compile(r"[A-Z][A-Z0-9]*-\d{2,}")


def _modules():
    if _PROJECT_ITEM not in sys.path:
        sys.path.insert(0, _PROJECT_ITEM)
    from project_item import assign, registry
    return assign, registry


def _session_error(error):
    exit_code = 2 if error.code in ("item_path_unset", "item_path_duplicate", "item_not_found",
                                    "project_not_found") else 3
    return SessionError(error.code, error.message, exit_code)


def _call(function, *args):
    _, registry = _modules()
    try:
        return function(*args)
    except registry.ItemError as error:
        raise _session_error(error) from error


def cr_root(project):
    _, registry = _modules()
    return _call(registry.item_root, project, "cr")


def check_id(job_id):
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        raise SessionError("job_invalid", "Use leader or a CR ID such as TOOL-012.", 2)
    return job_id


def _job(item):
    item = dict(item)
    if item["mode"] not in ("write", "read-only"):
        raise SessionError("job_invalid", "The CR Mode must be write or read-only.", 2)
    item["branch"] = f"cr/{item['job_id']}" if item["mode"] == "write" else None
    return item


def lookup(project, job_id, states=("todo", "in-progress")):
    assign, _ = _modules()
    item = _job(_call(assign.lookup, cr_root(project), check_id(job_id)))
    if item["state"] not in states:
        raise SessionError("cr_not_assignable", f"{job_id} is in {item['state']}/; expected "
                           + " or ".join(states) + ".")
    return item


def claim(project, job_id):
    assign, _ = _modules()
    return _job(_call(assign.claim, cr_root(project), check_id(job_id)))


def unclaim(project, job_id):
    assign, _ = _modules()
    _call(assign.unclaim, cr_root(project), check_id(job_id))


def set_base(project, job_id, base):
    assign, _ = _modules()
    _call(assign.set_base, cr_root(project), check_id(job_id), base)


def state_of(project, job_id):
    """Current directory of the CR and its Outcome kind (for the release check)."""
    assign, _ = _modules()
    item = _call(assign.lookup, cr_root(project), check_id(job_id))
    outcome = None
    for line in item["text"].splitlines():
        if line.startswith("- Outcome:"):
            outcome = line.split(":", 1)[1].strip().split(" ")[0] or None
            break
        if line.startswith("## "):
            break
    return item["state"], outcome
