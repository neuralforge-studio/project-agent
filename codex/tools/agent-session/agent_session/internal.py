"""Internal launch and hook functions. These are not user CLI commands."""

import datetime as dt
import json
import os
import time
from pathlib import Path

from .api import _project, _tmux
from .errors import SessionError
from .state import StateStore


_HOOK_FIELDS = ("session_id", "hook_event_name", "cwd", "source", "reason", "background_tasks", "session_crons")


def _run(run_id, config_path, socket_path, cwd=None):
    project = _project(cwd, config_path)
    control = _tmux(socket_path)
    matches = []
    for slot in ("leader", *(f"seat-{n}" for n in range(len(project.seats)))):
        try:
            meta = control.get_current(project.project_id, slot)
        except SessionError as error:
            if error.code != "execution_evidence_missing":
                raise
            continue
        if meta and meta.get("run_id") == run_id:
            matches.append(meta)
    if len(matches) != 1:
        raise SessionError("target_changed", "This run is not the current execution.")
    meta = matches[0]
    if Path(meta["base"]).resolve() != project.base:
        raise SessionError("owner_mismatch", "This execution belongs to another project.")
    seat = None if meta["target"] == "leader" else int(meta["target"].split("-", 1)[1])
    context = {
        **meta, "base": str(project.base), "provider": project.provider,
        "project_id": project.project_id, "config_path": str(project.config_path),
        "seat": seat, "seat_root": str(project.base if seat is None else project.seats[seat]),
    }
    if seat is not None and StateStore(project).read()[str(seat)]["job_id"] != meta.get("job_id"):
        raise SessionError("target_changed", "This JOB no longer owns the seat.")
    return project, control, context


def mark_process(run_id, config_path, socket_path, pid):
    """Record the pane process before it execs the interactive provider."""
    from . import process

    _, control, context = _run(run_id, config_path, socket_path)
    pane = control.pane_info(context["pane_id"])
    pid = int(pid)
    if pane["pane_pid"] != pid:
        raise SessionError("owner_mismatch", "The launch process is not the managed pane.")
    fingerprint = process.birth(pid)
    if not fingerprint:
        raise SessionError("execution_unknown", "The launch process has exited.", 4)
    control.write_meta(context["window_id"], {
        "cli_pid": pid, "cli_birth": fingerprint, "process_group": os.getpgid(pid),
        "provider_launch_attempted": True,
    })


def _register(run_id, config_path, socket_path, session_id, endpoint=None, cwd=None):
    from . import process
    from .providers import get_provider

    project, control, context = _run(run_id, config_path, socket_path, cwd)
    if not isinstance(session_id, str) or not session_id:
        raise SessionError("session_unbound", "The actual provider conversation ID is missing.")
    actual_cwd = Path(cwd or Path.cwd()).resolve()
    if actual_cwd != Path(context["cwd"]).resolve():
        raise SessionError("owner_mismatch", "The provider started in another directory.")
    if not process.alive(int(context["cli_pid"]), context["cli_birth"]):
        raise SessionError("execution_unknown", "The managed CLI is not alive.", 4)
    if context.get("expected_session_id") and context["expected_session_id"] != session_id:
        raise SessionError("owner_mismatch", "The hook conversation UUID is unexpected.")
    session = {"session_id": session_id}
    if project.provider == "codex":
        if endpoint != context.get("endpoint"):
            raise SessionError("owner_mismatch", "The app-server endpoint has changed.")
        session["endpoint"] = endpoint
    provider = get_provider(project.provider)
    context["session_id"] = session_id
    session = provider.verify_binding(session, context, context, timeout=20) or session
    if project.provider == "claude" and not session.get("message_to"):
        raise SessionError("session_unbound", "The native Claude recipient is unverified.", 4)
    current = control.get_current(project.project_id, context["target"])
    if not current or current.get("run_id") != run_id:
        raise SessionError("target_changed", "A newer run replaced this registration.")

    # Only the controller that holds the target lock publishes canonical state.
    # A late hook can update its old window, but cannot replace a newer owner.
    control.write_meta(context["window_id"], {
        "session_id": session_id, "registered": True,
        **({"message_to": session["message_to"]} if project.provider == "claude" else {}),
    })
    return project, control, context, session


def register_current(run_id, config_path, socket_path, endpoint):
    """Bind the actual Codex tool context, then wait for the launch controller."""
    session_id = os.environ.get("CODEX_THREAD_ID")
    _, control, context, session = _register(
        run_id, config_path, socket_path, session_id, endpoint,
    )
    return _wait_ready(control, context, session, output=True)


def _wait_ready(control, context, session, output=False):
    end = time.monotonic() + 120
    while time.monotonic() < end:
        latest = control.get_current(context["project_id"], context["target"])
        if not latest or latest.get("run_id") != context["run_id"]:
            raise SessionError("target_changed", "Registration was replaced by another run.")
        if latest.get("ready"):
            if output:
                print(json.dumps({"ok": True, "session": session, "ready": True}))
            return session
        if latest.get("start_error"):
            raise SessionError("start_failed", str(latest["start_error"]), 4)
        time.sleep(0.1)
    raise SessionError("registration_timeout", "The controller did not finish startup.", 4)


def register_from_hook(run_id, config_path, socket_path, expected_session_id=None, endpoint=None):
    """Read one native Claude event and reject a stale execution callback."""
    import sys

    payload = json.load(sys.stdin)
    session_id = payload.get("session_id")
    if not session_id or session_id != expected_session_id:
        raise SessionError("owner_mismatch", "The hook has an unexpected native session ID.")
    cwd = payload.get("cwd")
    project, control, context = _run(run_id, config_path, socket_path, cwd)
    event = payload.get("hook_event_name")
    if event not in ("SessionStart", "Stop", "StopFailure", "SessionEnd"):
        raise SessionError("hook_invalid", "This hook event is not used by agent-session.", 2)
    if event == "SessionStart":
        # Only a resume run (tmux option `resume`) binds a resumed conversation; other runs need a new one.
        wanted = "resume" if context.get("resume") else "startup"
        if payload.get("source") != wanted:
            raise SessionError("hook_invalid", "This run binds only a " + ("resumed" if wanted == "resume" else "new")
                               + " conversation.")
        project, control, context, _ = _register(
            run_id, config_path, socket_path, session_id, endpoint, cwd,
        )
    elif context.get("session_id") != session_id:
        raise SessionError("owner_mismatch", "This event belongs to an old conversation.")
    observations = control.read_meta(context["window_id"]).get("hook_observations", {})
    # Keep what the provider check reads; reply text such as last_assistant_message is not evidence.
    observed = {key: payload[key] for key in _HOOK_FIELDS if key in payload}
    observations[event] = {**observed, "observed_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    control.write_meta(context["window_id"], {"hook_observations": observations})
    if event == "SessionStart":
        _wait_ready(control, context, {"session_id": session_id}, output=False)


def run_controller(request_file):
    """Finish a self-control request from the tmux server process."""
    from . import process
    from .lifecycle import Manager
    from .util import write_json

    request = json.loads(Path(request_file).read_text(encoding="utf-8"))
    result_file = Path(request["result_file"])
    end = time.monotonic() + request["timeout"]
    control = _tmux(request["socket_path"])
    own_window = request["window_id"]
    cleanup = None
    try:
        metadata = control.read_meta(own_window)
        if metadata.get("run_id") != request["run_id"]:
            raise SessionError("target_changed", "The deferred controller no longer owns this window.")
        control.write_meta(own_window, {"controller_pid": os.getpid(), "controller_birth": process.birth(os.getpid())})
        while process.alive(request["requester_pid"], request["requester_birth"]):
            if time.monotonic() >= end:
                raise SessionError("timeout", "The self-control caller did not return before the wait limit.", 4)
            time.sleep(0.05)
        manager = Manager(request["base"], request["config_path"],
                          socket_path=request["socket_path"], timeout=max(0.001, end - time.monotonic()))
        result = manager.control(request["operation"], job=request.get("job"),
                                 seat=request.get("seat"), expected_run=request["run_id"],
                                 allow_self=False, defer_cleanup=True)
        cleanup = result.pop("deferred_cleanup", None)
        output = {"ok": True, "data": {**result, "completed": True}, "error": None}
    except SessionError as exc:
        output = {"ok": False, "data": {"completed": True}, "error": exc.as_dict()}
    except Exception as exc:
        output = {"ok": False, "data": {"completed": True}, "error": {
            "code": "controller_failed", "message": str(exc), "details": {},
        }}
    write_json(result_file, output)
    try:
        if control.read_meta(own_window).get("run_id") == request["run_id"]:
            control.write_meta(own_window, {"control_pending": False})
    except SessionError:
        # A removed window does not invalidate the persisted controller result.
        pass
    if cleanup is not None:
        # Close windows only now: closing the server's last window also ends this tmux job.
        owner = {"run_id": request["run_id"], "pid": os.getpid(), "birth": process.birth(os.getpid()),
                 "result_file": str(result_file)}
        try:
            manager.sweep_after_result(cleanup, owner)
        except Exception:
            pass                                   # retained windows are closed by a later sweep
