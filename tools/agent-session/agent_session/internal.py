"""Internal launch and hook functions. These are not user CLI commands."""

import datetime as dt
import json
import os
import time
from pathlib import Path

from .config import current_project
from .errors import SessionError
from .state import StateStore, control_lock, publish_session
from .tmux import control as tmux_control


_HOOK_BUDGET = 25          # seconds from the hook's start to its deadline; the SessionStart hook limit is 30
_PUBLISH_RESERVE = 6       # seconds of that budget kept for the control lock, the state lock and the writes
_BINDING_TIMEOUT = 20      # seconds at most for the binding check, which ends before the reserve
_BINDING_INTERVAL = 1.0
_FINISH_BUDGET = 120       # seconds for the wrap-up of a run that ended itself, lock wait and window cleanup included
_HOST_TIMEOUT = 8          # seconds for the provider's background listing inside the hook
_HOOK_FIELDS = ("session_id", "hook_event_name", "cwd", "source", "reason", "background_tasks", "session_crons")


def _run(run_id, config_path, socket_path, cwd=None):
    project = current_project(cwd, config_path)
    control = tmux_control(socket_path)
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
        "run_id": run_id, "cli_pid": pid, "cli_birth": fingerprint, "process_group": os.getpgid(pid),
        "provider_launch_attempted": True,
    })


def _register(run_id, config_path, socket_path, session_id, endpoint=None, cwd=None, deadline=None):
    """Bind the conversation and publish it, within one deadline (`_HOOK_BUDGET` from the start)."""
    deadline = deadline or time.monotonic() + _HOOK_BUDGET
    project, control, context = _run(run_id, config_path, socket_path, cwd)
    try:
        session = _bind(project, control, context, session_id, endpoint, cwd, deadline)
    except SessionError as error:
        _record_failure(control, context, error)
        raise

    # Registration and publication are one step (state.publish_session). The lock makes the publication wait
    # for a command that holds the slot, and the run is checked again inside it: a late hook cannot replace a
    # newer owner. A registration that succeeds clears a failure an earlier attempt of this run recorded.
    claude = project.provider == "claude"
    binding = {"session_id": session_id,
               **({"message_to": session["message_to"]} if claude else {"endpoint": session["endpoint"]})}
    try:
        with control_lock(project, context["target"], max(0, deadline - time.monotonic())):
            publish_session(project, control, StateStore(project, timeout=max(0, deadline - time.monotonic())),
                            context, binding)
    except SessionError as error:
        _record_failure(control, context, error)
        raise
    return project, control, context, session


def _bind(project, control, context, session_id, endpoint, cwd, deadline):
    """Check that the actual provider conversation is this run's; return its session binding."""
    from . import process
    from .providers import get_provider

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
    ends = min(time.monotonic() + _BINDING_TIMEOUT, deadline - _PUBLISH_RESERVE)
    session = _verify_binding(provider, session, context, max(ends, time.monotonic() + 0.1)) or session
    if project.provider == "claude" and not session.get("message_to"):
        raise SessionError("session_unbound", "The native Claude recipient is unverified.", 4)
    current = control.get_current(project.project_id, context["target"])
    if not current or current.get("run_id") != context["run_id"]:
        raise SessionError("target_changed", "A newer run replaced this registration.")
    return session


def _verify_binding(provider, session, context, end):
    """Check the native binding; look again while the provider's listing has not shown this pane yet.

    Starting several conversations at once can leave a listing without the pane for a moment.
    Only a failure the provider marks retryable is repeated, and only until the hook's time is spent;
    every other failure (several rows, another name or UUID, no locator) stands at once."""
    while True:
        try:
            return provider.verify_binding(session, context, context, timeout=max(0.1, end - time.monotonic()))
        except SessionError as error:
            if not error.details.get("retryable") or time.monotonic() + _BINDING_INTERVAL >= end:
                raise
        time.sleep(_BINDING_INTERVAL)


def _record_failure(control, context, error):
    """Leave the registration failure on this run's window so the waiting start can report it.

    A newer run that replaced this one is that run's concern, not this window's; write_meta also
    refuses a window that was handed to another run."""
    if error.code == "target_changed":
        return
    try:
        control.write_meta(context["window_id"], {
            "run_id": context["run_id"], "start_error": {"code": error.code, "message": error.message},
        })
    except SessionError:
        pass                                # the original error is the one to report


def register_current(run_id, config_path, socket_path, endpoint):
    """Bind the actual Codex tool context and publish it."""
    session_id = os.environ.get("CODEX_THREAD_ID")
    _, _, _, session = _register(run_id, config_path, socket_path, session_id, endpoint)
    print(json.dumps({"ok": True, "session": session, "ready": True}))
    return session


def _foreign_session(run_id, config_path, socket_path, payload, expected_session_id):
    """Reject a hook that carries another conversation's ID.

    When the run's own transcript says the conversation moved to this ID's background session, the run's
    window records the move and the error says so; otherwise it is an `owner_mismatch`."""
    from . import background
    from .providers import get_provider

    session_id = payload.get("session_id")
    if session_id and expected_session_id:
        try:
            project, control, context = _run(run_id, config_path, socket_path, payload.get("cwd"))
            record = background.record_of(get_provider(project.provider), expected_session_id, session_id,
                                          context["cwd"], _HOST_TIMEOUT)
            if record:
                control.write_meta(context["window_id"], {"run_id": run_id, "moved_to_background": record})
                raise SessionError("conversation_backgrounded", "The conversation moved to a background session.",
                                   4, background.details(context, record))
        except SessionError as error:
            if error.code == "conversation_backgrounded":
                raise
    raise SessionError("owner_mismatch", "The hook has an unexpected native session ID.")


def register_from_hook(run_id, config_path, socket_path, expected_session_id=None, endpoint=None):
    """Read one native Claude event and reject a stale execution callback."""
    import sys

    deadline = time.monotonic() + _HOOK_BUDGET
    payload = json.load(sys.stdin)
    session_id = payload.get("session_id")
    if not session_id or session_id != expected_session_id:
        _foreign_session(run_id, config_path, socket_path, payload, expected_session_id)
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
            run_id, config_path, socket_path, session_id, endpoint, cwd, deadline,
        )
    elif context.get("session_id") != session_id:
        raise SessionError("owner_mismatch", "This event belongs to an old conversation.")
    observations = control.read_meta(context["window_id"]).get("hook_observations", {})
    # Keep what the provider check reads; reply text such as last_assistant_message is not evidence.
    observed = {key: payload[key] for key in _HOOK_FIELDS if key in payload}
    observations[event] = {**observed, "observed_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    control.write_meta(context["window_id"], {"run_id": run_id, "hook_observations": observations})


def run_controller(request_file):
    """Finish a self-control request from the tmux server process."""
    from . import process
    from .lifecycle import Manager
    from .util import write_json

    request = json.loads(Path(request_file).read_text(encoding="utf-8"))
    result_file = Path(request["result_file"])
    end = time.monotonic() + request["timeout"]
    control = tmux_control(request["socket_path"])
    own_window = request["window_id"]
    cleanup = None
    try:
        metadata = control.read_meta(own_window)
        if metadata.get("run_id") != request["run_id"]:
            raise SessionError("target_changed", "The deferred controller no longer owns this window.")
        control.write_meta(own_window, {"run_id": request["run_id"], "controller_pid": os.getpid(),
                                        "controller_birth": process.birth(os.getpid())})
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
            control.write_meta(own_window, {"run_id": request["run_id"], "control_pending": False})
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


def finish_ended(socket_path, window_id, pane_id):
    """Wrap up the managed run whose pane just died; the tmux server's `pane-died` hook runs this.

    Everything comes from the window's own metadata. Whatever the wrap-up finds (done, left to a command,
    not confirmed) is saved in the run's directory as `finish-result.json`; nothing is printed, because the
    hook has no one to read it. A window or run that is no longer the pane's is not this call's concern."""
    from .launch_artifacts import run_directory
    from .lifecycle import Manager
    from .util import write_json

    control = tmux_control(socket_path)
    meta = control.read_meta(window_id)
    if meta.get("pane_id") != pane_id or not all(meta.get(key) for key in ("base", "config_path", "run_id", "target")):
        return None
    manager = Manager(meta["base"], meta["config_path"], socket_path=socket_path, timeout=_FINISH_BUDGET)
    try:
        output = {"ok": True, "data": manager.finish_ended(meta["run_id"], meta["target"], pane_id), "error": None}
    except SessionError as exc:
        output = {"ok": False, "data": None, "error": exc.as_dict()}
    except Exception as exc:
        output = {"ok": False, "data": None, "error": {"code": "finish_failed", "message": str(exc), "details": {}}}
    try:
        write_json(run_directory(manager.project, meta["run_id"]) / "finish-result.json", output)
    except OSError:
        pass                                    # a closed window leaves nothing to inform
    return output


def _main(arguments):
    if len(arguments) == 4 and arguments[0] == "finish-ended":
        try:
            finish_ended(*arguments[1:])
        except SessionError:
            pass                                # a window that is gone is already finished
        return 0
    return 2


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
