"""Board snapshot: what the page shows, read fresh from the source files on every request.

The plan (docs/project-board-plan.md) owns the rules: sources in section 3, screen states in
section 4.3, the review-wait rule in section 7.1. The registry, state.json and run liveness
come from agent_session; CR and decision files are read with project_item. Nothing is cached.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2]
for _name in ("agent-session", "project-item"):
    _path = str(TOOLS / _name)
    if _path not in sys.path:
        sys.path.insert(0, _path)

from agent_session import api  # noqa: E402
from agent_session.config import load_registry  # noqa: E402
from agent_session.errors import SessionError  # noqa: E402
from project_item.cr import submitted_hash  # noqa: E402  (the CR format owns the submission row)
from project_item.kinds import CR, DECIDE  # noqa: E402
from project_item.render import markdown, sections  # noqa: E402
from project_item.store import item_files  # noqa: E402

CR_STATES = ("open", "todo", "in-progress")           # done and deferred are not shown (plan 2)
HASH_TOKEN = re.compile(r"\b[0-9a-f]{7,40}\b")
DECIDE_HIDDEN = ("Evidence", "Disposition", "Result")   # the Board shows the question body; the rest is for the decide page


def _error(error: Exception) -> dict:
    if isinstance(error, SessionError):
        return {"code": error.code, "message": error.message}
    return {"code": type(error).__name__, "message": str(error)}


def _elapsed(connected_at: str | None, now: dt.datetime) -> int | None:
    if not connected_at:
        return None
    start = dt.datetime.strptime(connected_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    return max(0, int((now - start).total_seconds()))


def cited(disposition: str, commit: str) -> bool:
    """Whether the Disposition names the commit by at least its first 7 characters."""
    return any(commit.startswith(token) for token in HASH_TOKEN.findall(disposition))


def review_wait(state: str, headers: dict, parts: dict) -> bool:
    """Plan 7.1: a submission the Leader has not answered yet."""
    if state != "in-progress":
        return False
    result = parts.get("Result", "")
    if headers.get("Mode") == "read-only":
        return bool(result.strip())
    commit = submitted_hash(result)
    return commit is not None and not cited(parts.get("Disposition", ""), commit)


def _last_entry(result: str) -> str:
    """The newest `###` entry of a Result section, or the whole section without entries."""
    lines = result.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("### ")]
    return "\n".join(lines[starts[-1]:]) if starts else result


def cr_items(root: Path) -> dict:
    """open, todo and in-progress CRs. In-progress items carry what the seat drawer shows."""
    out = {}
    for state in CR_STATES:
        rows = []
        for path in item_files(CR, root, state):
            parsed = CR.fmt.parse(path, state)
            item = {"id": parsed.cr_id or path.stem, "title": parsed.title or path.stem, "state": state}
            if state == "in-progress":
                parts = dict(sections(path))
                base = parsed.headers.get("Base")
                mode = parsed.headers.get("Mode", "write")
                result = parts.get("Result", "")
                item.update({
                    "mode": mode, "base": base.split()[0] if base else None,
                    "branch": f"cr/{item['id']}" if mode == "write" else None,
                    "submitted": submitted_hash(result) if mode == "write" else None,
                    "review_wait": review_wait(state, parsed.headers, parts),
                    "result_html": markdown(_last_entry(result)) if result.strip() else "",
                    "contract_html": markdown(parts.get("Contract", "")),
                })
            rows.append(item)
        out[state] = rows
    return out


def decide_items(root: Path) -> list[dict]:
    items = []
    for path in item_files(DECIDE, root, "open"):
        parsed = DECIDE.fmt.parse(path, "open")
        items.append({
            "id": parsed.item_id or path.stem, "title": parsed.title or path.stem,
            "urgency": parsed.headers.get("Urgency", "normal"), "blocks": parsed.headers.get("Blocks"),
            "related": parsed.headers.get("Related"), "opened": parsed.headers.get("Opened"),
            "sections": [{"name": name, "html": markdown(body)} for name, body in sections(path)
                         if body and name not in DECIDE_HIDDEN],
        })
    return items


def _display(path: Path) -> str:
    home = Path.home()
    return "~/" + str(path.relative_to(home)) if path.is_relative_to(home) else str(path)


def _read_state(project):
    try:
        return api.read_state(project.base, config_path=project.config_path)
    except SessionError as error:
        if error.code == "state_not_found":             # no team has started in this project yet
            return None
        raise


def project_view(project, now: dt.datetime) -> dict:
    view = {"id": project.project_id, "base": str(project.base), "base_display": _display(project.base),
            "provider": project.provider,
            "seat_count": len(project.seats), "leader": None, "seats": [], "crs": None, "decide": None,
            "errors": []}
    try:
        state = _read_state(project)
    except Exception as error:                          # one broken project must not hide the others
        view["errors"].append({"source": "state", **_error(error)})
        state = None
    if project.path_cr is not None:
        try:
            view["crs"] = cr_items(project.path_cr)
        except Exception as error:
            view["errors"].append({"source": "cr", **_error(error)})
    if project.path_decide is not None:
        try:
            view["decide"] = decide_items(project.path_decide)
        except Exception as error:
            view["errors"].append({"source": "decide", **_error(error)})
    in_progress = {item["id"]: item for item in (view["crs"] or {}).get("in-progress", [])}
    leader = state["leader"] if state else None
    reviewing = leader.get("reviewing") if leader else None
    for index in range(len(project.seats)):
        entry = state[str(index)] if state else {"job_id": None, "git_hash": None, "session": None}
        session = entry["session"]
        job = entry["job_id"]
        cr = in_progress.get(job) if job else None
        if job is None:
            status = "empty"
        elif session is None:
            status = "pending"
        elif reviewing == job:
            status = "reviewing"
        elif cr and cr["review_wait"]:
            status = "review_wait"
        else:
            status = "working"
        view["seats"].append({
            "index": index, "job_id": job, "status": status, "session": session is not None,
            "session_id": session["session_id"] if session else None,
            "elapsed": _elapsed(session.get("connected_at"), now) if session else None,
            "title": cr["title"] if cr else None, "cr": cr,
        })
    if leader:
        seat = next((s["index"] for s in view["seats"] if reviewing and s["job_id"] == reviewing), None)
        view["leader"] = {"session_id": leader["session_id"], "elapsed": _elapsed(leader.get("connected_at"), now),
                          "reviewing": reviewing, "reviewing_seat": seat}
    return view


def snapshot(config=None, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        projects = load_registry(config)
    except SessionError as error:
        return {"now": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "projects": [], "error": _error(error)}
    return {"now": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "projects": [project_view(project, now) for project in projects], "error": None}


def liveness(config=None) -> dict:
    """Plan 7.2: per project, `alive`, `stopped` or `unknown` for each bound slot."""
    out = {}
    for project in load_registry(config):
        try:
            out[project.project_id] = api.liveness(project.base, config_path=project.config_path)
        except SessionError as error:
            out[project.project_id] = {} if error.code == "state_not_found" else {"error": _error(error)}
    return out


def find_project(config, project_id: str):
    for project in load_registry(config):
        if project.project_id == project_id:
            return project
    return None


def open_decision(project, decide_id: str) -> dict | None:
    if project.path_decide is None:
        return None
    return next((item for item in decide_items(project.path_decide) if item["id"] == decide_id), None)
