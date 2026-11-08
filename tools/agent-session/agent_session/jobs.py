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
    from project_item import api
    return api


def _session_error(error):
    exit_code = 2 if error.code in ("item_path_unset", "item_not_found", "project_not_found") else 3
    return SessionError(error.code, error.message, exit_code)


def _call(function, *args):
    items = _modules()
    try:
        return function(*args)
    except items.ItemError as error:
        raise _session_error(error) from error


def cr_root(project):
    items = _modules()
    return _call(items.item_root, project, "cr")


def check_id(job_id):
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        raise SessionError("job_invalid", "Use leader or a CR ID such as TOOL-012.", 2)
    return job_id


def _job(item):
    # A JOB only points to its CR: the CR file is the one copy of the text, which can outgrow a tmux option.
    item = {key: value for key, value in item.items() if key != "text"}
    if item["mode"] not in ("write", "read-only"):
        raise SessionError("job_invalid", "The CR Mode must be write or read-only.", 2)
    item["branch"] = f"cr/{item['job_id']}" if item["mode"] == "write" else None
    return item


def lookup(project, job_id, states=("todo", "in-progress")):
    items = _modules()
    item = _job(_call(items.lookup_cr, cr_root(project), check_id(job_id)))
    if item["state"] not in states:
        raise SessionError("cr_not_assignable", f"{job_id} is in {item['state']}/; expected "
                           + " or ".join(states) + ".")
    return item


def claim(project, job_id):
    items = _modules()
    return _job(_call(items.claim_cr, cr_root(project), check_id(job_id)))


def unclaim(project, job_id):
    items = _modules()
    _call(items.unclaim_cr, cr_root(project), check_id(job_id))


def set_base(project, job_id, base):
    items = _modules()
    _call(items.set_cr_base, cr_root(project), check_id(job_id), base)


def state_of(project, job_id):
    """Current directory of the CR and its Outcome kind (for the release check)."""
    items = _modules()
    item = _call(items.lookup_cr, cr_root(project), check_id(job_id))
    outcome = None
    for line in item["text"].splitlines():
        if line.startswith("- Outcome:"):
            outcome = line.split(":", 1)[1].strip().split(" ")[0] or None
            break
        if line.startswith("## "):
            break
    return item["state"], outcome
