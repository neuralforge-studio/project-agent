"""MacBook execution capsule. It has native run evidence, never a second project authority."""

import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys

from .errors import SessionError
from .util import write_json


def _directory(run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise SessionError("remote_input", "Invalid remote run ID.", 2)
    return Path.home() / ".cache/agent-session/runs" / run_id


def _manager(directory):
    from .lifecycle import Manager
    config = directory / "project.json"
    saved = json.loads((directory / "execution.json").read_text())
    manager = Manager(directory / "control", config, socket_path=saved["socket_path"], timeout=600)
    return manager, saved


def _current(seat, payload):
    manager, saved = _manager(_directory(payload["run_id"]))
    if saved["seat"] != str(seat):
        raise SessionError("owner_mismatch", "The remote execution belongs to another seat.")
    meta = manager.tmux.get_current(manager.project.project_id, "seat-0")
    if not meta or meta.get("run_id") != payload["run_id"] or meta.get("job_id") != saved["job_id"]:
        raise SessionError("execution_unknown", "The remote run evidence is unavailable.", 4)
    expected = payload.get("native")
    if expected:
        for key in ("run_id", "project_id", "window_id", "pane_id", "server_pid", "server_started", "server_birth", "socket_path"):
            if meta.get(key) != expected.get(key):
                raise SessionError("owner_mismatch", "The remote native execution changed.", 4)
        if expected.get("session_id") and meta.get("session_id") != expected["session_id"]:
            raise SessionError("owner_mismatch", "The remote conversation changed.", 4)
        if expected.get("endpoint") and meta.get("endpoint") != expected["endpoint"]:
            raise SessionError("owner_mismatch", "The remote provider endpoint changed.", 4)
    return manager, meta


def _launch(seat, payload, source):
    directory = _directory(payload["run_id"])
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    from .state import locked
    with locked(directory / "launch.lock"):
        record = directory / "execution.json"
        if record.exists():
            old = json.loads(record.read_text())
            if old["seat"] != str(seat) or old["job_id"] != payload["job"]["job_id"]:
                raise SessionError("owner_mismatch", "The remote run ID was already used.")
            return old
        base = directory / "control"
        base.mkdir()
        skills = Path.home() / ".codex/skills"
        skills.mkdir(parents=True, exist_ok=True)
        for name in ("project-team", "project-item"):
            target = source / "guidance/codex/skills" / name
            link = skills / name
            if target.is_dir() and not link.exists() and not link.is_symlink():
                link.symlink_to(target, target_is_directory=True)
        config = {str(base): {"project": "remote-" + payload["run_id"][:12], "provider": "codex",
                              "seats": [str(seat)], "launch": {"worker_args": payload["args"]}}}
        write_json(directory / "project.json", config)
        job = dict(payload["job"])
        job["path"] = str(directory / "cr.md")
        Path(job["path"]).write_text(payload["cr_text"], encoding="utf-8")
        uplink = {**payload["uplink"], "cr_path": job["path"], "original_cr": payload["cr_text"]}
        write_json(directory / "uplink.json", uplink)
        (directory / "bin").mkdir()
        wrapper = directory / "bin/agent-session"
        wrapper.write_text("#!/bin/sh\nexec " + shlex.join([sys.executable, "-m", "agent_session"]) + ' "$@"\n')
        wrapper.chmod(0o700)
        saved = {"seat": str(seat), "run_id": payload["run_id"], "job_id": job["job_id"],
                 "socket_path": "/tmp/as-" + str(os.getuid()) + "-" + payload["run_id"][:24] + ".sock"}
        write_json(record, saved)
        write_json(directory / "request.json", {**payload, "job": job, "source": str(source)})
        log = (directory / "controller.log").open("ab")
        env = dict(os.environ)
        for key in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "TMUX", "TMUX_PANE", "AGENT_SESSION_UPLINK"):
            env.pop(key, None)
        env["PYTHONPATH"] = str(source / "agent-session")
        try:
            child = subprocess.Popen([sys.executable, "-m", "agent_session.remote_runtime", str(directory)],
                                     cwd=base, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     start_new_session=True)
            from . import process
            saved.update(controller_pid=child.pid, controller_birth=process.birth(child.pid))
            write_json(record, saved)
        except OSError as error:
            write_json(directory / "start-error.json", {"code": "remote_start_failed", "message": str(error), "details": {}})
            raise
        log.close()
        return saved


def controller(directory):
    """Run the native launch controller independently of an SSH connection."""
    directory = Path(directory)
    request = json.loads((directory / "request.json").read_text())
    try:
        manager, saved = _manager(directory)
        job = request["job"]
        manager.store.update(lambda state: state["0"].update(job_id=job["job_id"], git_hash=job["base"]["base_hash"]))
        context = manager._context("seat-0", job, run_id=request["run_id"])
        context["upstream"] = str(directory / "uplink.json")
        context["upstream_bin"] = str(directory / "bin")
        if request.get("handoff_text"):
            handoff = directory / "handoff.md"
            handoff.write_text(request["handoff_text"], encoding="utf-8")
            context["handoff_file"] = str(handoff)
        context = manager._new_window(context)
        manager._launch(context, request=(
            "CR의 범위에서 작업·검증·commit·push하십시오. 이 CR 파일은 Mac mini 원본의 전송 snapshot입니다. "
            "Result 절만 수정하십시오. `agent-session send --job leader`는 Result를 원본에 충돌 검사 후 반영하고 "
            "현재 Leader에게 보고합니다. 이 명령은 PATH에 준비되어 있습니다. "
            "추가 CR·배정·state는 이 실행 capsule에서 만들거나 변경하지 마십시오. "
            "원문의 경로는 " + request.get("source_base", "") + "를 " + saved["seat"]
            + "로 대응하십시오. 상대 link는 원문 CR " + request.get("source_cr", "") + "의 부모 기준입니다. "
            "restart 인계는 " + str(manager._handoff_path(context)) + "에 쓰십시오."))
    except BaseException as error:
        if isinstance(error, SessionError) and error.code == "needs_user_action":
            return
        write_json(directory / "start-error.json", {"code": getattr(error, "code", "remote_start_failed"),
                   "message": str(error), "details": getattr(error, "details", {})})
        raise


def dispatch(seat, operation, payload, source):
    from .git_ops import git, is_git
    root = Path(seat)
    if not root.is_absolute():
        raise SessionError("remote_input", "A remote seat must be absolute.", 2)
    if operation == "git":
        return git(root, *payload["args"], timeout=600)
    if operation == "is_git":
        return is_git(root)
    if operation == "ensure_seat":
        if root.exists():
            return False
        root.parent.mkdir(parents=True, exist_ok=True)
        # mkdir claims only this new seat. A failed clone is retained for diagnosis.
        root.mkdir()
        git(root.parent, "clone", "--no-recurse-submodules", "--", payload["origin"], str(root), timeout=600)
        from .providers.codex import trust_workspace
        trust_workspace(root)
        return True
    if operation == "launch":
        return _launch(root, payload, source)
    if operation == "poll":
        directory = _directory(payload["run_id"])
        if (directory / "start-error.json").exists():
            error = json.loads((directory / "start-error.json").read_text())
            raise SessionError(error["code"], error["message"], 4, error["details"])
        manager, saved = _manager(directory)
        meta = manager.tmux.get_current(manager.project.project_id, "seat-0")
        if not meta:
            return {"ready": False}
        manager, meta = _current(root, payload)
        if meta.get("registered") and not meta.get("ready"):
            with manager._lock("seat-0"):
                manager._wait_ready(meta)
                meta = manager.tmux.get_current(manager.project.project_id, "seat-0")
        return {"ready": bool(meta.get("ready")), "native": meta,
                "dialog": manager.provider.startup_dialog(manager.tmux.capture_pane(meta["pane_id"]))}
    manager, meta = _current(root, payload)
    if operation == "liveness":
        from .api import _cli_alive
        pane = manager.tmux.pane_info(meta["pane_id"])
        return "alive" if _cli_alive(meta, pane) and not pane["pane_dead"] else "stopped"
    if operation == "observe":
        return manager._observe(meta)
    if operation == "check_binding":
        from .api import check_binding
        return check_binding(manager.project.base, meta["job_id"], config_path=manager.project.config_path,
                             socket=manager.socket)
    if operation == "handoff":
        path = manager._fresh_handoff(meta)
        return {"fresh": path is not None, "text": Path(path).read_text(encoding="utf-8") if path else None}
    if operation == "send":
        return manager.provider.send(manager._session(meta), payload["message"], {**meta, "meta": meta}, timeout=30)
    if operation == "request_stop":
        return manager.provider.request_stop(manager._session(meta), meta, meta, timeout=30)
    if operation == "request_exit":
        manager.provider.request_exit(meta, manager.tmux)
        return {}
    if operation == "detach":
        clients = manager.tmux.command("list-clients", "-F", "#{session_name}").splitlines()
        if manager.project.project_id in clients:
            manager.tmux.command("detach-client", "-s", manager.project.project_id)
        return {}
    if operation == "prepare_display":
        path = Path("/tmp/as-u-" + payload["run_id"][:24] + ".sock")
        try:
            info = path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise SessionError("owner_mismatch", "The remote report socket has another owner.")
            path.unlink()
        except FileNotFoundError:
            pass
        return {}
    if operation == "display_clients":
        clients = manager.tmux.command("list-clients", "-F", "#{session_name}").splitlines()
        return clients.count(manager.project.project_id)
    raise SessionError("remote_input", "Unsupported remote operation.", 2)


def respond(request, source):
    try:
        data = dispatch(request["seat"], request["operation"], request["payload"], source)
        response = {"ok": True, "data": data}
    except SessionError as error:
        response = {"ok": False, "error": {**error.as_dict(), "exit_code": error.exit_code}}
    except Exception as error:
        response = {"ok": False, "error": {"code": "remote_unknown", "message": str(error), "exit_code": 4}}
    print(json.dumps(response), flush=True)


if __name__ == "__main__":
    controller(sys.argv[1])
