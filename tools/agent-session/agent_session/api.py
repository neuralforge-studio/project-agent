"""Integration for project task, verification, and CR code: state reads and the caller rule."""

import os
from pathlib import Path

from .config import RemoteSeat, resolve_project
from .errors import SessionError
from .state import StateStore, binding_identity


def _project(cwd=None, config_path=None):
    return resolve_project(cwd, config_path or os.environ.get("AGENT_SESSION_CONFIG"))


def _tmux(socket=None):
    from .tmux import Tmux

    socket = socket or os.environ.get("AGENT_SESSION_SOCKET")
    if isinstance(socket, dict):
        return Tmux(**socket)
    return Tmux(socket_path=str(socket)) if socket else Tmux()


def caller(project, tmux=None, store=None):
    """Who runs this command: (slot, session id) of this project's Leader ("leader") or Worker
    ("seat-N"), ("operator", None) for a CLI outside every managed run, or ("unmanaged-agent", id)
    for an agent session that is not a member of this project.

    A conversation ID in the environment is matched with the state's bindings; without one, the
    tmux pane of the managed run names the slot. This is the one caller rule of the project tools.
    """
    tmux = tmux or _tmux()
    store = store or StateStore(project)
    identity = os.environ.get("CODEX_THREAD_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID")
    state = store.read(missing_ok=True)
    if identity:
        if state["leader"] and state["leader"]["session_id"] == identity:
            return "leader", identity
        for key, item in state.items():
            if key != "leader" and item["session"] and item["session"]["session_id"] == identity:
                return f"seat-{key}", identity
        return "unmanaged-agent", identity
    pane = os.environ.get("TMUX_PANE")
    inherited_socket = os.environ.get("TMUX", "").split(",", 1)[0]
    if pane and inherited_socket and Path(inherited_socket).resolve() == Path(tmux.effective_socket()).resolve():
        for slot in ("leader", *(f"seat-{n}" for n in range(len(project.seats)))):
            try:
                meta = tmux.get_current(project.project_id, slot)
            except SessionError as error:
                if error.code != "execution_evidence_missing":
                    raise
                continue
            if meta and meta.get("pane_id") == pane:
                return slot, meta.get("session_id")
    return "operator", None


def require_live(project, slot, identity, tmux=None):
    """Reject a Leader or Worker caller whose slot no longer holds its live managed CLI."""
    from . import process

    own = (tmux or _tmux()).get_current(project.project_id, slot)
    if not own or own.get("session_id") != identity or not own.get("ready"):
        raise SessionError("caller_not_running", "The sender no longer owns a live managed CLI.")
    if own.get("remote_seat"):
        from . import remote
        _check_owner(project, slot, {"session_id": identity}, own)
        alive = remote.liveness(own) == "alive"
    else:
        alive = bool(own.get("cli_pid") and process.alive(int(own["cli_pid"]), own.get("cli_birth")))
    if not alive:
        raise SessionError("caller_not_running", "The sender no longer owns a live managed CLI.")


def read_state(cwd=None, config_path=None):
    """Read an existing atomic snapshot without acquiring a control lock."""
    return StateStore(_project(cwd, config_path)).read()


def _select(state, target):
    if target == "leader":
        return None, state["leader"]
    matches = [int(key) for key, item in state.items()
               if key != "leader" and item["job_id"] == target]
    if len(matches) != 1:
        raise SessionError("job_not_assigned", "JOB has no unique current seat.")
    seat = matches[0]
    return seat, state[str(seat)]["session"]


def _check_owner(project, slot, session, meta):
    """Accept a tmux run only as this base's run of the slot and as the conversation the state names.

    Session is the state's conversation for the slot; None leaves the conversation uncompared.
    """
    if Path(meta.get("base", "")).resolve() != project.base:
        raise SessionError("owner_mismatch", "The tmux window belongs to another project.")
    if meta.get("target") != slot or (session and meta.get("session_id") != session["session_id"]):
        raise SessionError("owner_mismatch", "The native conversation does not match this slot.")
    if slot.startswith("seat-"):
        seat = project.seats[int(slot[5:])]
        expected = {"host": seat.host, "path": str(seat.path), "python": seat.python} if isinstance(seat, RemoteSeat) else None
        if meta.get("remote_seat") != expected:
            raise SessionError("owner_mismatch", "The execution host differs from the registered seat.")
        if expected and session and "endpoint" in session and session["endpoint"] != meta.get("endpoint"):
            raise SessionError("owner_mismatch", "The remote provider endpoint differs from the published binding.")


def _unlaunched_observation(meta, pane):
    from . import process

    if meta.get("provider_launch_attempted") is not False or meta.get("registered") is not False:
        raise SessionError("session_unbound", "The target has no verified native conversation.", 4)
    pid, fingerprint = meta.get("placeholder_pid"), meta.get("placeholder_birth")
    group = meta.get("placeholder_process_group")
    if not pid or not fingerprint or not group:
        raise SessionError("execution_unknown", "The waiting pane process identity is incomplete.", 4)
    alive = process.alive(int(pid), fingerprint)
    stopped = bool(pane["pane_dead"] and not alive and not process.group_alive(int(group)))
    return {"known": True, "terminal": True, "active_turn": False, "pending": [],
            "background": [], "idle": True, "cli_alive": False, "stopped": stopped, "pane": pane}


def _cli_alive(meta, pane):
    """Whether the run's CLI process (or the pane process before it marked one) still runs."""
    from . import process

    pid = meta.get("cli_pid") or pane.get("pane_pid")     # a window handed to a new run holds cli_pid null
    return bool(pid and process.alive(int(pid), meta.get("cli_birth")))


def liveness(cwd=None, config_path=None, socket=None):
    """Classify each bound slot's current run from tmux and process facts, without a provider call.

    Keys are "leader" and seat numbers that have a session. Each value names the session it
    judged and its state. "alive": the current run is this session and its pane and CLI run.
    "stopped": that run's pane or CLI ended. "unknown": no current run, a run of another
    session, or a failed lookup. A caller drops a verdict whose session is no longer current.
    """
    project = _project(cwd, config_path)
    state = StateStore(project).read()
    control = _tmux(socket)
    result = {}
    for key, entry in state.items():
        session = entry if key == "leader" else entry["session"]
        if not session:
            continue
        slot = "leader" if key == "leader" else f"seat-{key}"
        verdict = "unknown"
        try:
            meta = control.get_current(project.project_id, slot)
            if meta and meta.get("session_id") == session["session_id"]:
                if meta.get("remote_seat"):
                    from . import remote
                    _check_owner(project, slot, session, meta)
                    verdict = remote.liveness(meta)
                else:
                    pane = control.pane_info(meta["pane_id"])
                    verdict = "alive" if _cli_alive(meta, pane) and not pane["pane_dead"] else "stopped"
        except SessionError:
            pass
        result[key] = {"session_id": session["session_id"], "state": verdict}
    return result


def check_binding(cwd, target, expected_session_id=None, config_path=None, socket=None):
    """Observe a binding, then reject concurrent changes to its identity."""
    from . import process
    from .providers import get_provider

    project = _project(cwd, config_path)
    store = StateStore(project)
    before = store.read()
    seat, session = _select(before, target)
    if expected_session_id and (not session or session["session_id"] != expected_session_id):
        raise SessionError("owner_mismatch", "The conversation is not the current owner.")
    control = _tmux(socket)
    slot = "leader" if seat is None else f"seat-{seat}"
    pointer = control.get_current(project.project_id, slot)
    if not pointer:
        raise SessionError("execution_unknown", "The current tmux execution is unavailable.", 4)
    meta = control.read_meta(pointer["window_id"])
    for field in ("run_id", "window_id", "pane_id"):
        if pointer.get(field) != meta.get(field):
            raise SessionError("owner_mismatch", "The tmux execution has changed.")
    _check_owner(project, slot, session, meta)
    context = {
        "base": str(project.base), "project_id": project.project_id,
        "provider": project.provider, "target": slot, "seat": seat,
        "seat_root": str(project.base if seat is None else project.seats[seat]),
        "cwd": meta.get("cwd", str(project.base if seat is None else project.seats[seat])),
        "job_id": None if seat is None else target, "run_id": meta["run_id"],
        "config_path": str(project.config_path), "socket_path": meta.get("socket_path"),
        "window_id": meta["window_id"], "pane_id": meta["pane_id"],
        "endpoint": (session or {}).get("endpoint", meta.get("endpoint")),
    }
    ready = bool(meta.get("ready"))
    if meta.get("remote_seat") and meta.get("provider_launch_attempted") is not False:
        from . import remote
        native = remote.run_call(meta, "check_binding", timeout=15)
        if (not isinstance(native, dict) or not isinstance(native.get("observation"), dict)
                or any(type(native.get(key)) is not bool for key in ("alive", "ready", "termination_confirmed"))):
            raise SessionError("remote_unknown", "The remote binding observation is incomplete.", 4)
        observation = native["observation"]
        alive = bool(native["alive"])
        terminated = bool(native["termination_confirmed"])
        ready = ready and bool(native["ready"])
        context.update(remote_seat=meta["remote_seat"], remote_native=meta.get("remote_native"))
    else:
        info = control.pane_info(meta["pane_id"])
        cli_alive = _cli_alive(meta, info)
        meta = {**meta, "pane_dead": info["pane_dead"]}
        if session:
            provider = get_provider(project.provider)
            if not info["pane_dead"]:
                provider.verify_binding(session, context, meta, timeout=15)
            elif not meta.get("registered"):
                raise SessionError("execution_unknown", "The dead pane never established its conversation.", 4)
            observation = provider.observe(session, context, meta, timeout=15)
        else:
            observation = _unlaunched_observation(meta, info)
            cli_alive = False
        group = meta.get("process_group")
        group_alive = bool(group and process.group_alive(int(group)))
        backgrounds = meta.get("background_pids", [])
        background_alive = any(process.alive(int(item["pid"]), item.get("birth"))
                               for item in backgrounds)
        terminated = observation.get("stopped") if session is None else bool(info["pane_dead"] and not cli_alive and not group_alive
                          and not background_alive and observation.get("known")
                          and observation.get("terminal")
                          and not observation.get("active_turn")
                          and not observation.get("pending")
                          and not observation.get("background"))
        alive = bool(cli_alive and not info["pane_dead"])
    after = store.read()
    after_pointer = control.get_current(project.project_id, slot)
    try:
        after_seat, after_session = _select(after, target)
        # Review marks and connection times may change during observation; the connection may not.
        same_assignment = (after_seat == seat and binding_identity(after_session, project.provider)
                           == binding_identity(session, project.provider))
    except SessionError:
        same_assignment = False
    identity = ("run_id", "window_id", "pane_id", "server_pid", "server_started", "session_id",
                "remote_seat", "remote_native")
    same_run = after_pointer and all(after_pointer.get(key) == pointer.get(key) for key in identity)
    if not same_assignment or not same_run:
        raise SessionError("target_changed", "The target changed during observation.")
    return {
        **context, "session": session, "ready": ready,
        "alive": alive,
        "termination_confirmed": terminated, "metadata": meta,
        "observation": observation,
    }
