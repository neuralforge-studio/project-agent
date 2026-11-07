"""Join local assignment and display evidence to a remote native Codex run."""

import json
import os
from pathlib import Path
import shlex
import signal
import time

from . import process, remote, remote_bridge
from .errors import SessionError


def _native(meta):
    keys = ("run_id", "project_id", "window_id", "pane_id", "server_pid", "server_started",
            "server_birth", "socket_path", "session_id", "endpoint", "cwd", "cli_pid", "cli_birth")
    return {key: meta.get(key) for key in keys}


def poll(manager, meta, check_dialog=True):
    result = remote.run_call(meta, "poll", timeout=manager.remaining())
    native = result.get("native")
    if native:
        update = {"run_id": meta["run_id"], "remote_native": _native(native)}
        if result.get("ready"):
            update.update(registered=True, session_id=native["session_id"], endpoint=native["endpoint"])
        meta = manager.tmux.write_meta(meta["window_id"], update)
    if check_dialog and result.get("dialog"):
        raise SessionError("needs_user_action", "The remote Codex waits for a user dialog. Open its SSH window.", 3,
                           {**manager._result(meta), "dialog": result["dialog"]})
    return meta


def attach(manager, meta):
    """The local pane is a display and reverse report channel, never termination evidence."""
    bridge = remote_bridge.prepare(manager, meta)
    remote.run_call(meta, "prepare_display", timeout=manager.remaining())
    native = meta["remote_native"]
    script = manager.project.runtime_path / "runs" / meta["run_id"] / "launch.sh"
    command = ["ssh", "-tt", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
               "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2",
               "-o", "ExitOnForwardFailure=yes", "-o", "StreamLocalBindUnlink=yes",
               "-R", bridge["remote_listen"] + ":" + bridge["listen"], "--", meta["remote_seat"]["host"],
               "PATH=\"$HOME/.local/bin:/opt/homebrew/bin:$PATH\" "
               + shlex.join(["tmux", "-S", native["socket_path"], "attach-session", "-t", native["project_id"]])]
    script.write_text("#!/bin/bash\nexec " + shlex.join(command) + "\n", encoding="utf-8")
    meta = manager.tmux.write_meta(meta["window_id"], {"launch_file": str(script)})
    if manager.tmux.pane_info(meta["pane_id"])["pane_dead"]:
        meta = manager.tmux.reconnect_remote(meta, manager.project.base, script)
    else:
        meta = manager.tmux.launch(meta["window_id"], manager.project.base, script)
    deadline = time.monotonic() + min(10, manager.remaining())
    while True:
        if manager.tmux.pane_info(meta["pane_id"])["pane_dead"]:
            raise SessionError("remote_display_failed", "The SSH display exited; the native run is preserved.", 4,
                               manager._result(meta))
        if remote.run_call(meta, "display_clients", timeout=manager.remaining()):
            return meta
        if time.monotonic() > deadline:
            raise SessionError("remote_display_failed", "The remote tmux display connection is unconfirmed.", 4,
                               manager._result(meta))
        time.sleep(min(.1, manager.remaining()))


def launch(manager, context):
    bridge = remote_bridge.prepare(manager, context)
    job = context["job"]
    # An accepted SSH request can lose its response. Keep the uncertainty before sending it.
    manager.tmux.write_meta(context["window_id"], {"run_id": context["run_id"], "provider_launch_attempted": True})
    remote.run_call(context, "launch", {"job": job, "args": list(manager.project.args_for("worker")),
                    "cr_text": Path(job["path"]).read_text(encoding="utf-8"),
                    "source_base": str(manager.project.base), "source_cr": job["path"],
                    "handoff_text": Path(context["handoff_file"]).read_text(encoding="utf-8")
                    if context.get("handoff_file") else None,
                    "uplink": {"listen": bridge["remote_listen"], "token": bridge["token"],
                               "job_id": context["job_id"], "run_id": context["run_id"]}},
                    timeout=manager.remaining())
    while not context.get("remote_native"):
        context = poll(manager, context, check_dialog=False)
        if not context.get("remote_native"):
            time.sleep(min(0.2, manager.remaining()))
    context = attach(manager, context)
    return {**manager._wait_ready(context), "cleanup": manager._sweep(context["target"])}


def detach(manager, meta):
    """Called only after native termination. Close the SSH display and its private bridge."""
    remote.run_call(meta, "detach", timeout=manager.remaining())
    path = manager.project.runtime_path / "runs" / meta["run_id"] / "bridge.json"
    if path.exists():
        settings = json.loads(path.read_text())
        if settings.get("birth") and process.alive(settings["pid"], settings["birth"]):
            os.kill(settings["pid"], signal.SIGTERM)
        Path(settings["listen"]).unlink(missing_ok=True)
    # SSH exit is asynchronous; closing a still-live display is left to a later sweep.
