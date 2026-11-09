"""The tmux windows of a slot's runs: naming, reuse of a retired window, opening, renaming, and cleanup.

Dependency direction: `lifecycle` imports this module; this module never imports `lifecycle`. Every
function takes the `Tmux` client and the project it works on. Judging whether a run has ended is the
caller's: `observe` is a callable that returns the run's observation for its window meta (`stopped` says
the end is confirmed). The slot's control lock, the order of start and release, and what a failure
leaves behind stay with the caller; a function here that depends on the lock says so.
"""

import json
import os
import time
from pathlib import Path

from . import process
from .errors import SessionError
from .launch_artifacts import run_directory

SWEEP_SECONDS = 30                                 # after this, a cleanup leaves later windows to the next sweep
REUSE_REFUSED = ("target_changed", "tmux_owner_mismatch", "target_running", "window_unreusable")


def _completed(result_file):
    try:
        return json.loads(Path(result_file).read_text(encoding="utf-8"))["data"]["completed"] is True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def window_name(project_id, meta):
    if meta["seat"] is None:
        return f"{project_id}-leader"
    return f"{project_id}-seat{meta['seat']}-{meta['job_id']}"


def retire_name(tmux, project_id, meta):
    tmux.command("rename-window", "-t", meta["window_id"],
                 window_name(project_id, meta) + "-exited-" + meta["run_id"][:8])


def open_window(tmux, project, context, retired):
    """The run's window, made current for its slot; `context["window_name"]` names it.

    The slot's retired window (from `reusable`) is handed to the run when tmux accepts it, so the panes
    that a person added stay beside the new CLI. A refusal that only says the window cannot be reused
    opens a new window; any other error is the caller's to read, because the window may have changed.
    """
    name = context["window_name"]
    # The waiting pane starts in the seat root; the launch script enters the CR's Cwd after Git preparation.
    cwd = context["cwd"]
    physical_root = str(project.base) if context.get("remote_seat") else context["seat_root"]
    reused = None
    if retired is not None:
        try:
            reused = tmux.reuse_window(project.project_id, name, physical_root, context, retired)
        except SessionError as error:
            if error.code not in REUSE_REFUSED:
                raise
    context = reused or tmux.create_window(project.project_id, name, physical_root, context)
    if context["cwd"] != cwd:
        context = tmux.write_meta(context["window_id"], {"cwd": cwd})
    tmux.set_current(project.project_id, context["target"], context)
    if context["seat"] is None:
        tmux.command("select-window", "-t", project.project_id + ":" + context["window_id"])
    return context


def reusable(tmux, project, target, observe, ending=None):
    """The retired window that the slot's next run takes over, or None to open a new window.

    With a current pointer, only its window counts. Without one (after a release), the window of the
    slot's most recent run counts; recency is the time of the run's launch script. The window must
    be one `sweep` would accept as ended, except that a person's panes in it do not matter.
    `ending` is the run that this restart's own controller just ended; it is the one run whose
    pending control does not keep its window from the new run.
    """
    try:
        meta = tmux.get_current(project.project_id, target)
        if meta is None:
            found = []
            for window_id in tmux.managed_windows(project.project_id, target):
                candidate = tmux.read_meta(window_id)
                script = run_directory(project, str(candidate.get("run_id"))) / "launch.sh"
                found.append((script.stat().st_mtime if script.is_file() else 0.0, candidate))
            if not found:
                return None
            meta = max(found, key=lambda item: item[0])[1]
        own = ending is not None and meta.get("run_id") == ending.get("run_id")
        return meta if retained(project, meta, observe, controller=own) is None else None
    except SessionError:
        return None


def retained(project, meta, observe, owner=None, controller=False):
    """Why a retired window must stay, or None when its run ended without pending control.

    With `controller`, this process may be the controller that is restarting the run: then the run's
    own pending control and controller record do not count. Any other pending control does.
    """
    if not meta.get("base") or Path(meta["base"]).resolve() != project.base or not meta.get("pane_id"):
        return "foreign_window"
    pid, birth = meta.get("controller_pid"), meta.get("controller_birth")
    mine = bool(controller and meta.get("control_pending") and meta.get("control_operation") == "restart"
                and pid == os.getpid() and birth == process.birth(os.getpid()))
    if not mine:
        if meta.get("control_pending"):
            return "control_pending"
        if pid and process.alive(int(pid), birth):
            # The finishing self-controller may close its own run after it saved the completed result.
            own = (owner is not None and owner["run_id"] == meta.get("run_id")
                   and owner["pid"] == int(pid) and owner["birth"] == birth
                   and _completed(owner["result_file"]))
            if not own:
                return "controller_running"
    if not observe(meta)["stopped"]:
        return "termination_unconfirmed"
    return None


def _pointer_run(tmux, project, target):
    try:
        current = tmux.get_current(project.project_id, target)
    except SessionError as error:
        if error.code == "execution_evidence_missing":
            return error.details.get("run_id")
        raise
    return current.get("run_id") if current else None


def sweep(tmux, project, target, observe, owner=None):
    """Close the slot's retired windows; the current pointer's run and unsure windows stay.

    A retired window that holds a person's panes loses only its managed pane and is listed in `pane_closed`.

    The caller holds the slot's control lock, so the current pointer cannot change meanwhile.
    """
    closed, kept, pane_closed = [], [], []
    deadline = time.monotonic() + SWEEP_SECONDS
    try:
        current = _pointer_run(tmux, project, target)
        handles = tmux.managed_windows(project.project_id, target)
    except SessionError as error:
        return {"closed": closed, "kept": [{"window_id": None, "reason": error.code}]}
    for window_id in handles:
        try:
            meta = tmux.read_meta(window_id)
            if meta.get("run_id") == current:
                continue
            if time.monotonic() >= deadline:
                reason = "cleanup_budget"
            else:
                reason = retained(project, meta, observe, owner)
                if reason is None:
                    (closed if tmux.close_window(window_id, meta) == "window" else pane_closed).append(window_id)
                    continue
        except SessionError as error:
            reason = error.code
        kept.append({"window_id": window_id, "reason": reason})
    return {"closed": closed, "kept": kept, **({"pane_closed": pane_closed} if pane_closed else {})}


def discard_placeholder(tmux, project, meta, observe, remaining):
    """End the unlaunched waiting pane of a start that failed before its reservation held.

    `remaining` returns the seconds left of the command, and raises when none are left."""
    try:
        tmux.request_placeholder_stop(meta["window_id"])
        current = tmux.get_current(project.project_id, meta["target"])
        while not observe(current)["stopped"]:
            time.sleep(min(0.1, remaining()))
        retire_name(tmux, project.project_id, current)
    except SessionError:
        pass                                   # the original failure is the result
