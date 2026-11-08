"""Board snapshot: read current project facts from their source files.

The TUI plan (docs/project-board-tui-plan.md) owns the display contract. The registry,
state.json and run liveness come from agent_session; CR and decision files are read with
project_item. Nothing is cached.
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
from agent_session.registry import RemoteSeat, SessionError, load_registry, find_project as registered_project  # noqa: E402
from project_item import api as items  # noqa: E402
from project_item.api import submitted_hash, DECIDE  # noqa: E402  (legacy exports of the format owner)

CR_STATES = ("open", "todo", "in-progress")           # done and deferred are not shown
HASH_TOKEN = re.compile(r"\b[0-9a-f]{7,40}\b")
DECIDE_HIDDEN = ("Disposition", "Result")


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
    """Adapt public Item facts to the Board's CR and seat presentation."""
    out = items.cr_items(root, CR_STATES)
    for state, rows in out.items():
        for item in rows:
            headers = item.pop("headers")
            parts = item.pop("sections")
            if state == "in-progress":
                base = headers.get("Base")
                mode = headers.get("Mode", "write")
                result = parts.get("Result", "")
                item.update({
                    "mode": mode, "base": base.split()[0] if base else None,
                    "branch": f"cr/{item['id']}" if mode == "write" else None,
                    "submitted": submitted_hash(result) if mode == "write" else None,
                    "review_wait": review_wait(state, headers, parts),
                    "result_markdown": _last_entry(result) if result.strip() else "",
                    "contract_markdown": parts.get("Contract", ""),
                })
    return out


def read_cr_markdown(project: dict, item: dict, state: str) -> str:
    """Read a listed CR through Item's root and identity validation."""
    root = project.get("cr_root")
    if state not in CR_STATES or not root:
        raise ValueError("CR 목록 경로가 유효하지 않습니다.")
    return items.read_cr_markdown(Path(root), item, state)


def decide_items(root: Path, cr_root: Path | None = None) -> list[dict]:
    return [{
        "id": item["id"], "title": item["title"], "path": item["path"],
        "state": item["state"], "display_state": item["display_state"],
        "urgency": item["headers"].get("Urgency", "normal"), "blocks": item["headers"].get("Blocks"),
        "related": item["headers"].get("Related"), "opened": item["headers"].get("Opened"),
        "sections": [{"name": name, "body": body} for name, body in item["sections"]
                     if body and name not in DECIDE_HIDDEN],
    } for item in items.decision_items(root, cr_root)]


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
            "cr_root": str(project.path_cr.resolve()) if project.path_cr is not None else None,
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
            view["decide"] = decide_items(project.path_decide, project.path_cr)
        except Exception as error:
            view["errors"].append({"source": "decide", **_error(error)})
    in_progress = {item["id"]: item for item in (view["crs"] or {}).get("in-progress", [])}
    leader = state["leader"] if state else None
    reviewing = leader.get("reviewing") if leader else None
    for index, root in enumerate(project.seats):
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
            "host": root.host if isinstance(root, RemoteSeat) else None,
            "path": str(root.path if isinstance(root, RemoteSeat) else root),
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
    return registered_project(config, project_id)


def open_decision(project, decide_id: str) -> dict | None:
    if project.path_decide is None:
        return None
    return next((item for item in decide_items(project.path_decide)
                 if item["id"] == decide_id and item["state"] == "open"), None)
