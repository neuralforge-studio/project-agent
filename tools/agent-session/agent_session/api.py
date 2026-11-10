"""The one module other tools import from agent-session: state reads, the caller rule, and liveness."""

import os
from pathlib import Path

from . import config, process, providers, remote, tmux as tmux_module
from .config import RemoteSeat, load_registry, resolve_project
from .errors import SessionError
from .state import StateStore, binding_identity, select_target
from .tmux import PANE_ID_OPTION, Tmux

# The public names. spec 5 (docs/project-team/spec.md) records each one's input and result.
__all__ = (
    "PANE_ID_OPTION", "RemoteSeat", "SessionError", "Tmux",
    "caller", "check_binding", "finish_release", "liveness", "load_registry", "pane_slot", "pending_releases",
    "project_liveness", "project_pending_releases", "project_state",
    "read_state", "require_live", "resolve_project",
)


def pane_slot(pane, tmux=None):
    """`(project_id, slot)` of the managed window that holds this tmux pane, or None for another window.

    `slot` is `leader` or `seat-N` (the vocabulary of `caller`), or None when the window's target is not
    a slot. It reads the window's tmux options only, so it never fails on stale state.
    """
    return (tmux or tmux_module.control()).pane_slot(pane)


def caller(project, tmux=None, store=None):
    """Who runs this command: (slot, session id) of this project's Leader ("leader") or Worker
    ("seat-N"), ("operator", None) for a CLI outside every managed run, or ("unmanaged-agent", id)
    for an agent session that is not a member of this project.

    A conversation ID in the environment is matched with the state's bindings; without one, the
    tmux pane of the managed run names the slot. This is the one caller rule of the project tools.
    """
    tmux = tmux or tmux_module.control()
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
    own = (tmux or tmux_module.control()).get_current(project.project_id, slot)
    if not own or own.get("session_id") != identity or not own.get("ready"):
        raise SessionError("caller_not_running", "The sender no longer owns a live managed CLI.")
    if own.get("remote_seat"):
        tmux_module.check_owner(project, slot, {"session_id": identity}, own)
        alive = remote.liveness(own) == "alive"
    else:
        alive = bool(own.get("cli_pid") and process.alive(int(own["cli_pid"]), own.get("cli_birth")))
    if not alive:
        raise SessionError("caller_not_running", "The sender no longer owns a live managed CLI.")


def read_state(cwd=None, config_path=None):
    """Read an existing atomic snapshot without acquiring a control lock."""
    return project_state(config.current_project(cwd, config_path))


def project_state(project):
    """`read_state` of a project the caller already holds (from `load_registry`). A consumer that
    visits every project reads the registry once instead of once per project."""
    return StateStore(config.require_base(project)).read()


def liveness(cwd=None, config_path=None, socket=None):
    """Classify each bound slot's current run from tmux and process facts, without a provider call.

    Keys are "leader" and seat numbers that have a session. Each value names the session it
    judged and its state. "alive": the current run is this session and its pane and CLI run.
    "stopped": that run's pane or CLI ended. "unknown": no current run, a run of another
    session, or a failed lookup. A caller drops a verdict whose session is no longer current.
    """
    return project_liveness(config.current_project(cwd, config_path), socket)


def project_liveness(project, socket=None):
    """`liveness` of a project the caller already holds (from `load_registry`)."""
    state = StateStore(config.require_base(project)).read()
    control = tmux_module.control(socket)
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
                    tmux_module.check_owner(project, slot, session, meta)
                    verdict = remote.liveness(meta)
                else:
                    pane = control.pane_info(meta["pane_id"])
                    verdict = "alive" if process.cli_alive(meta, pane) and not pane["pane_dead"] else "stopped"
        except SessionError:
            pass
        result[key] = {"session_id": session["session_id"], "state": verdict}
    return result


def check_binding(cwd, target, expected_session_id=None, config_path=None, socket=None):
    """Observe a binding, then reject concurrent changes to its identity."""
    project = config.current_project(cwd, config_path)
    store = StateStore(project)
    before = store.read()
    seat, session = select_target(before, target)
    if expected_session_id and (not session or session["session_id"] != expected_session_id):
        raise SessionError("owner_mismatch", "The conversation is not the current owner.")
    control = tmux_module.control(socket)
    slot = "leader" if seat is None else f"seat-{seat}"
    pointer = control.get_current(project.project_id, slot)
    if not pointer:
        raise SessionError("execution_unknown", "The current tmux execution is unavailable.", 4)
    meta = control.read_meta(pointer["window_id"])
    for field in ("run_id", "window_id", "pane_id"):
        if pointer.get(field) != meta.get(field):
            raise SessionError("owner_mismatch", "The tmux execution has changed.")
    tmux_module.check_owner(project, slot, session, meta)
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
        cli_alive = process.cli_alive(meta, info)
        meta = {**meta, "pane_dead": info["pane_dead"]}
        if session:
            provider = providers.get_provider(project.provider)
            if not info["pane_dead"]:
                provider.verify_binding(session, context, meta, timeout=15)
            elif not meta.get("registered"):
                raise SessionError("execution_unknown", "The dead pane never established its conversation.", 4)
            observation = provider.observe(session, context, meta, timeout=15)
        else:
            observation = process.unlaunched_observation(meta, info)
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
        after_seat, after_session = select_target(after, target)
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


def _socket_kwargs(socket):
    socket = socket or os.environ.get("AGENT_SESSION_SOCKET")
    if isinstance(socket, dict):
        return socket
    return {"socket_path": str(socket)} if socket else {}


def _manager(cwd, config_path, socket, timeout, project=None):
    from .lifecycle import Manager          # lifecycle imports this module
    return Manager(cwd, config_path, timeout=timeout, project=project, **_socket_kwargs(socket))


def release_waits(project, store, tmux):
    """JOB ID -> {seat, since, reasons} for each assigned seat whose stopped run waits for release.

    Reads the state and the run's tmux record only. It lives here, not in `lifecycle`, so that a command
    that only lists these (`project-item ls`, the Board) does not import the whole lifecycle."""
    state = store.read(missing_ok=True)
    found = {}
    for key, entry in state.items():
        if key == "leader" or not entry["job_id"]:
            continue
        try:
            meta = tmux.get_current(project.project_id, f"seat-{key}")
        except SessionError:
            continue                           # unknown evidence is not a pending release
        pending = meta and meta.get("job_id") == entry["job_id"] and meta.get("release_pending")
        if pending:
            found[entry["job_id"]] = {"seat": int(key), **pending}
    return found


def _release_waits_of(project, socket):
    return release_waits(project, StateStore(project, timeout=60), Tmux(**_socket_kwargs(socket)))


def pending_releases(cwd=None, config_path=None, socket=None):
    """JOB ID -> {seat, since, reasons} for each seat whose Worker stopped but whose release waits
    because the CR was still in-progress. Read-only; an unreadable run is not listed.
    """
    return _release_waits_of(config.current_project(cwd, config_path), socket)


def project_pending_releases(project, socket=None):
    """`pending_releases` of a project the caller already holds (from `load_registry`)."""
    return _release_waits_of(config.require_base(project), socket)


def finish_release(cwd, job_id, config_path=None, socket=None):
    """Finish the release that `stop` left pending for the JOB, after its CR left in-progress.

    None when the JOB has no pending release. Otherwise {job_id, seat, released, reasons}: the release
    check of stop decides, and a refusal keeps the assignment and names why.
    """
    return _manager(cwd, config_path, socket, 120).finish_release(job_id)
