"""Board snapshot: read current project facts from their source files.

The TUI plan (docs/project-board-tui-plan.md) owns the display contract. The registry,
state.json and run liveness come from agent_session; CR and decision files are read with
project_item. A CR or decision file is parsed again only when its size or modification time
changed (`_cached`). The registry and each directory listing are read again only when the
modification time of the registry file or of a directory of the tree changed (`_unchanged`, BOARD-013);
every state file and run liveness is read on each call.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2]
for _name in ("agent-session", "project-item"):
    _path = str(TOOLS / _name)
    if _path not in sys.path:
        sys.path.insert(0, _path)

from agent_session import api  # noqa: E402
from agent_session.api import RemoteSeat, SessionError, load_registry, registry_path  # noqa: E402
from project_item.api import (CR, DECIDE, cr_states, decision_stage, file_id,  # noqa: E402
                              item_files, review_waiting, submitted_hash, text_sections)

CR_STATES = ("open", "todo", "in-progress")           # the sidebar's states; done and deferred are not counted
READABLE_STATES = CR_STATES + ("done",)               # the CR popup also reads done (BOARD-021)
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


def review_wait(state: str, headers: dict, parts: dict) -> bool:
    """A submission the Leader has not answered yet. The rule is owned by
    tools/project-board/README.md ("Review wait"); `project_item.api.review_waiting` implements it."""
    return state == "in-progress" and review_waiting(headers.get("Mode"), parts.get("Result", ""),
                                                      parts.get("Disposition", ""))


def _last_entry(result: str) -> str:
    """The newest `###` entry of a Result section, or the whole section without entries."""
    lines = result.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("### ")]
    return "\n".join(lines[starts[-1]:]) if starts else result


_cache: dict[tuple, dict[str, tuple]] = {}


def _cached(scope: tuple, paths: list[Path], build):
    """`build(path)` for each path, reusing the last result of a file whose size and modification
    time are unchanged. A source file costs one `stat` per call and is read only after a change.

    `scope` names one directory tree of one kind (the cache key); a path that is no longer listed
    leaves the cache. A file that cannot be stat-ed is built again each call, so its error reaches
    the caller instead of an old result.
    """
    old = _cache.get(scope, {})
    kept: dict[str, tuple] = {}
    out = []
    for path in paths:
        key = str(path)
        try:
            info = os.stat(path)
            signature = (info.st_mtime_ns, info.st_size, info.st_ino)
        except OSError:
            out.append(build(path))
            continue
        hit = old.get(key)
        if hit is not None and hit[0] == signature:
            kept[key] = hit
            out.append(hit[1])
            continue
        value = build(path)
        kept[key] = (signature, value)
        out.append(value)
    _cache[scope] = kept
    return out


# A file system stamps a change with a clock that ticks coarsely, so a second change in the same tick would leave
# the stamp as it was. A stamp this recent is not trusted: that read is not kept, and the next call reads again.
SETTLE_NS = 2_000_000_000
_unchanged_cache: dict[tuple, tuple] = {}


def _tree_stamps(base: Path) -> list[tuple[str, int]] | None:
    """The modification time of `base` and of every directory below it; None if `base` is not a directory."""
    try:
        stamps = [(str(base), os.stat(base).st_mtime_ns)]
        for top, names, _ in os.walk(base):
            for name in names:
                path = os.path.join(top, name)
                stamps.append((path, os.stat(path).st_mtime_ns))
    except OSError:
        return None
    return stamps


def _unchanged(scope: tuple, bases: list[Path], read):
    """`read()`, reused while no directory under `bases` has a new modification time.

    A file added, removed or renamed changes the time of the directory it is in, and a new directory
    changes its parent's, so the directories of the last read stand for every listing in the tree.
    The stamps are taken before `read()`: a change during it shows as different stamps on the next call.
    """
    old = _unchanged_cache.get(scope)
    if old is not None and all(_tree_stamps_same(stamps) for stamps in old[0]):
        return old[1]
    now = time.time_ns()
    trees = [_tree_stamps(base) for base in bases]
    value = read()
    if all(tree is not None and all(now - stamp >= SETTLE_NS for _, stamp in tree) for tree in trees):
        _unchanged_cache[scope] = (trees, value)
    else:
        _unchanged_cache.pop(scope, None)
    return value


def _tree_stamps_same(stamps: list[tuple[str, int]]) -> bool:
    """Whether every directory of an earlier read has the time it had. A directory added since changed its parent's."""
    try:
        return all(os.stat(path).st_mtime_ns == stamp for path, stamp in stamps)
    except OSError:
        return False


def _cr_item(state: str):
    def build(path: Path) -> dict:
        text = path.read_text(encoding="utf-8")
        parsed = CR.fmt.parse_text(text, path, state)
        item = {"id": parsed.cr_id or path.stem, "title": parsed.title or path.stem,
                "state": state, "path": str(path)}
        if state == "in-progress":
            parts = dict(text_sections(text))
            base = parsed.headers.get("Base")
            mode = parsed.headers.get("Mode", "write")
            result = parts.get("Result", "")
            item.update({
                "mode": mode, "base": base.split()[0] if base else None,
                "branch": f"cr/{item['id']}" if mode == "write" else None,
                "submitted": submitted_hash(result) if mode == "write" else None,
                "review_wait": review_wait(state, parsed.headers, parts),
                "result_markdown": _last_entry(result) if result.strip() else "",
                "contract_markdown": parts.get("Contract", ""),
            })
        return item
    return build


def _listing(kind, root: Path, state: str) -> list[Path]:
    return _unchanged(("files", kind.name, str(root), state), [root / state], lambda: item_files(kind, root, state))


def cr_items(root: Path) -> dict:
    """open, todo and in-progress CRs. In-progress items carry what the seat drawer shows."""
    return {state: [dict(item) for item in
                    _cached(("cr", str(root), state), _listing(CR, root, state), _cr_item(state))]
            for state in CR_STATES}


def done_items(root: Path) -> list[dict]:
    """done CRs, for the CR popup only. The sidebar snapshot does not carry them.

    A project keeps hundreds of done CRs and opening a file costs a round trip on a shared disk, so the list
    does not open them: the title is first the file name without the ID, and `done_title` reads the real one."""
    items = []
    for path in _listing(CR, root, "done"):
        cr_id = file_id(CR, path) or path.stem
        title = path.stem.removeprefix(cr_id).strip("-_ ").replace("-", " ").replace("_", " ")
        items.append({"id": cr_id, "title": title or cr_id, "state": "done", "path": str(path)})
    return items


def done_title(item: dict) -> str | None:
    """The title of a listed done CR, from the first line of its file."""
    path = Path(item["path"])
    with path.open(encoding="utf-8") as handle:
        return CR.fmt.parse_text(handle.readline(), path, "done").title


def read_cr_markdown(project: dict, item: dict, state: str) -> str:
    """Read a listed CR only from its registered root and state directory."""
    root = project.get("cr_root")
    if state not in READABLE_STATES or not root or item.get("state") != state or not item.get("path"):
        raise ValueError("CR 목록 경로가 유효하지 않습니다.")
    path = Path(item["path"]).resolve(strict=True)
    if not path.is_relative_to(Path(root).resolve() / state) or file_id(CR, path) != item.get("id"):
        raise ValueError("CR 목록 밖의 파일은 읽을 수 없습니다.")
    return path.read_text(encoding="utf-8")


def _decision(state: str):
    def build(path: Path) -> dict:
        text = path.read_text(encoding="utf-8")
        parsed = DECIDE.fmt.parse_text(text, path, state)
        return {"id": parsed.item_id or path.stem, "title": parsed.title or path.stem,
                "path": str(path.resolve()), "state": state, "headers": parsed.headers,
                "sections": [{"name": name, "body": body} for name, body in text_sections(text)
                             if body and name not in DECIDE_HIDDEN]}
    return build


def decide_items(root: Path, cr_root: Path | None = None) -> list[dict]:
    items = []
    states = (_unchanged(("cr_states", str(cr_root)), [cr_root / state for state in CR.states],
                         lambda: cr_states(cr_root)) if cr_root is not None else {})
    for state in DECIDE.states:
        for read in _cached(("decide", str(root), state), _listing(DECIDE, root, state), _decision(state)):
            headers = read["headers"]
            items.append({
                "id": read["id"], "title": read["title"], "path": read["path"], "state": state,
                "display_state": decision_stage({"state": state, "headers": headers}, states),
                "urgency": headers.get("Urgency", "normal"), "blocks": headers.get("Blocks"),
                "related": headers.get("Related"), "opened": headers.get("Opened"),
                "sections": read["sections"],
            })
    return items


def _display(path: Path) -> str:
    home = Path.home()
    return "~/" + str(path.relative_to(home)) if path.is_relative_to(home) else str(path)


def _read_state(project):
    try:
        return api.project_state(project)
    except SessionError as error:
        if error.code == "state_not_found":             # no team has started in this project yet
            return None
        raise


def project_view(project, now: dt.datetime, only: frozenset | None = None) -> dict:
    """One project's facts. `only` (a subset of `state`, `crs`, `decide`) reads just those: a window that shows
    CRs or decisions has no use for the others, and every file read is a round trip on a shared disk. A part that
    is not read is as if the project had none (`crs`, `decide` None; no seats, no Leader without `state`)."""
    view = {"id": project.project_id, "base": str(project.base), "base_display": _display(project.base),
            "cr_root": str(project.path_cr.resolve()) if project.path_cr is not None else None,
            "provider": project.provider,
            "seat_count": len(project.seats), "leader": None, "seats": [], "crs": None, "decide": None,
            "errors": []}
    state = None
    if only is None or "state" in only:
        try:
            state = _read_state(project)
        except Exception as error:                      # one broken project must not hide the others
            view["errors"].append({"source": "state", **_error(error)})
    if project.path_cr is not None and (only is None or "crs" in only):
        try:
            view["crs"] = cr_items(project.path_cr)
        except Exception as error:
            view["errors"].append({"source": "cr", **_error(error)})
    if project.path_decide is not None and (only is None or "decide" in only):
        try:
            view["decide"] = decide_items(project.path_decide, project.path_cr)
        except Exception as error:
            view["errors"].append({"source": "decide", **_error(error)})
    if only is not None and "state" not in only:
        return view
    waiting = _releases.get(project.project_id, {}) if state else {}
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
        elif job in waiting:
            status = "release_pending"
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
            "release_pending": waiting.get(job) if job else None,
        })
    if leader:
        seat = next((s["index"] for s in view["seats"] if reviewing and s["job_id"] == reviewing), None)
        view["leader"] = {"session_id": leader["session_id"], "elapsed": _elapsed(leader.get("connected_at"), now),
                          "reviewing": reviewing, "reviewing_seat": seat}
    return view


_registry_cache: dict[str, tuple] = {}


def _registry(config) -> list:
    """`load_registry(config)`, reused while the registry file is the same file with the same size and
    modification time. The projects are only read, so one list serves every caller."""
    path = registry_path(config)
    try:
        info = os.stat(path)
    except OSError:
        return load_registry(config)                   # it reports what is wrong with the file
    stamp = (info.st_mtime_ns, info.st_size, info.st_ino)
    hit = _registry_cache.get(str(path))
    if hit is not None and hit[0] == stamp:
        return hit[1]
    projects = load_registry(config)
    if time.time_ns() - info.st_mtime_ns >= SETTLE_NS:
        _registry_cache[str(path)] = (stamp, projects)
    else:
        _registry_cache.pop(str(path), None)
    return projects


def snapshot(config=None, now: dt.datetime | None = None, project_id: str | None = None,
             only: frozenset | None = None) -> dict:
    """Every registered project, or only `project_id` (a popup shows one project); `only`: see `project_view`."""
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        projects = _registry(config)
    except SessionError as error:
        return {"now": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "projects": [], "error": _error(error)}
    if project_id is not None:
        projects = [project for project in projects if project.project_id == project_id]
    return {"now": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "projects": [project_view(project, now, only) for project in projects], "error": None}


ONLY_CRS = frozenset({"crs"})                       # what the CR window reads of a project
ONLY_DECISIONS = frozenset({"decide"})              # what the decision window reads of a project


def decision_snapshot(config=None) -> dict:
    """The decisions of every registered project and nothing else: what ◀▶ of the decision window needs to know
    (which projects have a decision to show). It shares the cache of `decide_items`, so the window's own read of
    a project reuses it."""
    return snapshot(config, only=ONLY_DECISIONS)


def popup_snapshot(config=None, project_id: str | None = None, done: bool = False,
                   only: frozenset | None = None) -> dict:
    """What a popup shows: `project_id` only (as `snapshot` reads it) and `order`, the registered project IDs
    in registration order, for ◀▶. With `done`, the project's done CRs are under `crs["done"]`.

    A done list that cannot be read is reported as an `errors` entry (source `cr`), like the other lists.
    """
    data = snapshot(config, project_id=project_id, only=only)
    try:
        data["order"] = [project.project_id for project in _registry(config)]
    except SessionError:
        data["order"] = []
    for project in data["projects"]:
        if done and project["cr_root"] is not None and project["crs"] is not None:
            try:
                project["crs"]["done"] = done_items(Path(project["cr_root"]))
            except Exception as error:
                project["errors"].append({"source": "cr", **_error(error)})
    return data


# JOB ID -> release hold of each project, as the last `liveness()` read it. Both facts come from
# tmux (`api.server_view`: two `tmux` processes for all projects), so they are read on the 10-second run-fact
# refresh and not on the 2-second file refresh that `snapshot` is (BOARD-002). A hold that ended is
# shown until the next run-fact refresh.
_releases: dict[str, dict] = {}


def _project_liveness(project, view) -> dict:
    try:
        return api.project_liveness(project, view=view)
    except SessionError as error:
        return {} if error.code == "state_not_found" else {"error": _error(error)}


def liveness_of(project) -> dict:
    """The `liveness` entry of one project, read from the tmux server for that project alone."""
    try:
        view = api.server_view([project])
    except SessionError:
        view = None
    return _project_liveness(project, view)


def liveness(config=None) -> dict:
    """Per project, `alive`, `stopped` or `unknown` for each bound slot.

    The rule is owned by docs/project-team/spec.md section 5 (`agent_session.api.liveness`).
    It also refreshes the release holds that `snapshot` shows.
    """
    out = {}
    projects = _registry(config)
    try:
        view = api.server_view(projects)                # one read of the tmux server for every project
    except SessionError:
        view = None                                     # each project then reads (and fails) for itself
    for project in projects:
        out[project.project_id] = _project_liveness(project, view)
        try:
            _releases[project.project_id] = api.project_pending_releases(project, view=view)
        except SessionError:
            _releases[project.project_id] = {}          # an unreadable tmux is not a pending release
    return out


def find_project(config, project_id: str):
    for project in _registry(config):
        if project.project_id == project_id:
            return project
    return None


def open_decision(project, decide_id: str) -> dict | None:
    if project.path_decide is None:
        return None
    return next((item for item in decide_items(project.path_decide)
                 if item["id"] == decide_id and item["state"] == "open"), None)
