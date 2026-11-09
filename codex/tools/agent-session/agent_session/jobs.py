"""CR files as JOBs. The CR root comes from the project registry (path_cr); the format and the
in-progress move belong to the sibling project-item tool, used only through project_item.api.
No project code runs here."""

import sys
from pathlib import Path

from .errors import SessionError

_PROJECT_ITEM = str(Path(__file__).resolve().parents[2] / "project-item")


def item_api():
    """The public interface of project-item, imported from the sibling tool directory."""
    if _PROJECT_ITEM not in sys.path:
        sys.path.insert(0, _PROJECT_ITEM)
    from project_item import api
    return api


def _session_error(error):
    exit_code = 2 if error.code in ("item_path_unset", "item_not_found", "project_not_found") else 3
    return SessionError(error.code, error.message, exit_code)


def _call(function, *args):
    try:
        return function(*args)
    except item_api().ItemError as error:
        raise _session_error(error) from error


def cr_root(project):
    return _call(item_api().item_root, project, "cr")


def check_id(job_id):
    if not isinstance(job_id, str) or not item_api().JOB_ID.fullmatch(job_id):
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
    item = _job(_call(item_api().lookup, cr_root(project), check_id(job_id)))
    if item["state"] not in states:
        raise SessionError("cr_not_assignable", f"{job_id} is in {item['state']}/; expected "
                           + " or ".join(states) + ".")
    return item


def claim(project, job_id):
    return _job(_call(item_api().claim, cr_root(project), check_id(job_id)))


def unclaim(project, job_id):
    _call(item_api().unclaim, cr_root(project), check_id(job_id))


def set_base(project, job_id, base):
    _call(item_api().set_base, cr_root(project), check_id(job_id), base)


def state_of(project, job_id):
    """Current directory of the CR and its Outcome kind (for the release check)."""
    api = item_api()
    item = _call(api.lookup, cr_root(project), check_id(job_id))
    parsed = api.CR.fmt.parse_text(item["text"], Path(item["path"]), item["state"])
    return item["state"], api.outcome_kind(parsed.headers.get("Outcome")) or None
