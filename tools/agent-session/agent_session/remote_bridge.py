"""Private reverse-SSH uplink for one Worker's Result and existing CLI reports."""

import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import socketserver
import subprocess
import sys
import time

from .errors import SessionError
from .util import write_json


def _parts(text):
    import re
    matches = list(re.finditer(r"^## Result[ \t]*$", text, re.MULTILINE))
    if len(matches) != 1:
        raise SessionError("remote_result_invalid", "The CR must have one Result section.", 2)
    start = matches[0].end()
    following = re.search(r"^## ", text[start:], re.MULTILINE)
    end = start + following.start() if following else len(text)
    return text[:start], text[start:end], text[end:]


def sync_result(project, settings, original, updated):
    """Copy only Result into the authoritative CR under its existing item-root lock."""
    from . import jobs
    api = jobs.item_api()
    before, result, after = _parts(updated)
    old_before, old_result, old_after = _parts(original)
    if (before, after) != (old_before, old_after):
        raise SessionError("remote_result_invalid", "A Worker may return only the CR Result section.", 2)
    with api.root_lock(jobs.cr_root(project)):
        item = api.lookup_locked(jobs.cr_root(project), settings["job_id"])
        if item["state"] != "in-progress":
            raise SessionError("target_changed", "The CR left in-progress before the remote report.")
        path = Path(item["path"])
        current_before, current_result, current_after = _parts(item["text"])
        previous = settings.get("last_result", old_result)
        if current_result not in (previous, result):
            raise SessionError("remote_result_conflict", "The authoritative Result changed; preserve both reports.", 4)
        path.write_text(current_before + result + current_after, encoding="utf-8")
        settings["last_result"] = result


def prepare(manager, context):
    """Start one private bridge before creating its SSH display connection."""
    from . import process
    path = manager.project.runtime_path / "runs" / context["run_id"] / "bridge.json"
    if path.exists():
        settings = json.loads(path.read_text())
        if process.alive(settings.get("pid", 0), settings.get("birth")):
            return settings
        Path(settings["listen"]).unlink(missing_ok=True)
    else:
        settings = {"base": str(manager.project.base), "config_path": str(manager.project.config_path),
                    "socket_path": context["socket_path"], "run_id": context["run_id"],
                    "target": context["target"], "job_id": context["job_id"], "token": secrets.token_hex(32),
                    "listen": "/tmp/as-u-" + str(os.getuid()) + "-" + context["run_id"][:24] + ".sock",
                    "remote_listen": "/tmp/as-u-" + context["run_id"][:24] + ".sock"}
    write_json(path, settings)
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    for name in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "TMUX", "TMUX_PANE", "AGENT_SESSION_UPLINK"):
        env.pop(name, None)
    log = path.with_suffix(".log").open("ab")
    child = subprocess.Popen([sys.executable, "-m", "agent_session.remote_bridge", str(path)],
                             env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    log.close()
    settings.update(pid=child.pid, birth=process.birth(child.pid))
    write_json(path, settings)
    deadline = time.monotonic() + 5
    while not Path(settings["listen"]).exists():
        if child.poll() is not None or time.monotonic() > deadline:
            raise SessionError("remote_unknown", "The Worker report bridge did not start.", 4)
        time.sleep(0.05)
    return settings


def forward(arguments):
    """Use the existing send/stop/restart syntax inside a remote Worker."""
    settings = json.loads(Path(os.environ["AGENT_SESSION_UPLINK"]).read_text())
    if (arguments.command not in ("send", "stop", "restart") or getattr(arguments, "project", None)
            or getattr(arguments, "seat", None) is not None
            or arguments.job != ("leader" if arguments.command == "send" else settings["job_id"])):
        raise SessionError("role_denied", "A remote Worker may report to its Leader or control its own run.", 2)
    message = getattr(arguments, "message", None)
    if getattr(arguments, "file", None):
        message = Path(arguments.file).read_text(encoding="utf-8")
    request = {"token": settings["token"], "run_id": settings["run_id"],
               "session_id": os.environ.get("CODEX_THREAD_ID"), "operation": arguments.command,
               "message": message, "original": settings["original_cr"],
               "updated": Path(settings["cr_path"]).read_text(encoding="utf-8")}
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(arguments.timeout)
            connection.connect(settings["listen"])
            connection.sendall(json.dumps(request).encode() + b"\n")
            response = json.loads(connection.makefile("rb").readline(1024 * 1024))
    except (OSError, ValueError) as error:
        raise SessionError("remote_unknown", "The Leader report connection is unavailable; delivery is unconfirmed.", 4) from error
    if not response["ok"]:
        error = response["error"]
        raise SessionError(error["code"], error["message"], 4, error.get("details"))
    return response["data"]


class Bridge(socketserver.ForkingMixIn, socketserver.UnixStreamServer):
    block_on_close = False


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        from .lifecycle import Manager
        try:
            request = json.loads(self.rfile.readline(1024 * 1024))
            settings = json.loads(self.server.settings_path.read_text())
            if (not hmac.compare_digest(request.get("token", ""), settings["token"])
                    or request.get("run_id") != settings["run_id"]):
                raise SessionError("owner_mismatch", "The remote report credential does not match this run.")
            manager = Manager(settings["base"], settings["config_path"], socket_path=settings["socket_path"])
            meta = manager.tmux.get_current(manager.project.project_id, settings["target"])
            if (not meta or meta["run_id"] != settings["run_id"] or not meta.get("ready")
                    or not request.get("session_id") or meta.get("session_id") != request["session_id"]):
                raise SessionError("target_changed", "The remote report belongs to a replaced Worker.")
            os.environ["CODEX_THREAD_ID"] = request["session_id"]
            with manager._lock(settings["target"]):
                manager._same(meta)
                manager._authorize("send", "leader")
                sync_result(manager.project, settings, request["original"], request["updated"])
                write_json(self.server.settings_path, settings)
            if request["operation"] == "send":
                result = manager.send(job="leader", message=request["message"])
            elif request["operation"] in ("stop", "restart"):
                result = manager.control(request["operation"], job=settings["job_id"])
            else:
                raise SessionError("role_denied", "Unsupported Worker uplink command.")
            response = {"ok": True, "data": result}
        except SessionError as error:
            response = {"ok": False, "error": error.as_dict()}
        except Exception:
            response = {"ok": False, "error": {"code": "remote_unknown", "message": "The remote report was not confirmed."}}
        self.wfile.write(json.dumps(response).encode() + b"\n")


def serve(path):
    path = Path(path)
    settings = json.loads(path.read_text())
    os.umask(0o077)
    with Bridge(settings["listen"], Handler) as server:
        server.settings_path = path
        server.serve_forever(poll_interval=0.2)


if __name__ == "__main__":
    serve(sys.argv[1])
