"""Local HTTP server of the Project Board (docs/project-board-plan.md section 6).

GET /           the page, with this run's send token
GET /api/board  the snapshot of every project, read from the files now
GET /api/live   run liveness of every bound slot (tmux and process facts only)
POST /api/answer  send one decision answer to the project's Leader with `agent-session send`

The server keeps no state besides its token. It binds 127.0.0.1 only.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from . import model

STATIC = Path(__file__).resolve().parent / "static"
AGENT_SESSION = model.TOOLS / "agent-session" / "bin" / "agent-session"
HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_REQUEST = 65536
MAX_ANSWER = 16384                       # UTF-8 bytes; agent-session takes 32768 with the header lines
SEND_TIMEOUT = 30                        # agent-session send --timeout
AGENT_ENV = ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID")


def answer_message(project_id: str, decide_id: str, title: str, answer: str) -> str:
    """Plan 6.2: the first line names the decision; the answer is the rest after `답변:`."""
    return (f"결정 답변: {decide_id}\n"
            f"Project: {project_id}\n"
            f"질문: {title}\n"
            "사용자가 Project Board에서 입력한 답입니다. 결정 항목 절차에 따라 기록하고 항목을 옮기십시오. "
            "`답변:` 다음 줄부터 끝까지가 답변 원문입니다.\n"
            "답변:\n"
            f"{answer}")


def send_answer(project, text: str) -> dict:
    """Deliver through the public agent-session command, as the user (operator) who runs the board."""
    with tempfile.TemporaryDirectory(prefix="project-board-") as directory:
        body = Path(directory) / "answer.md"
        body.write_text(text, encoding="utf-8")
        command = [str(AGENT_SESSION), "--config", str(project.config_path), "send", "--job", "leader",
                   "--file", str(body), "--timeout", str(SEND_TIMEOUT)]
        try:
            run = subprocess.run(command, cwd=project.base, capture_output=True, text=True,
                                 timeout=SEND_TIMEOUT + 30)
        except OSError as error:                    # agent-session did not start; nothing was sent
            return {"ok": False, "data": None,
                    "error": {"code": "send_unavailable", "message": str(error), "details": {}}}
        except subprocess.TimeoutExpired:
            # It may have delivered before it stopped answering; the page must not suggest a blind resend.
            return {"ok": False, "data": None, "error": {"code": "send_unconfirmed",
                    "message": "agent-session did not finish; the Leader may have received the answer.",
                    "details": {}}}
    try:
        return json.loads(run.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return {"ok": False, "data": None, "error": {"code": "send_unconfirmed",
                "message": "agent-session did not return a JSON result; the Leader may have received the answer.",
                "details": {"exit": run.returncode, "stderr": run.stderr[-2000:]}}}


def _fail(code: str, message: str) -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": message, "details": {}}}


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "project-board"

    def log_message(self, format, *args):
        if self.server.verbose:
            super().log_message(format, *args)

    # ------------------------------------------------------------ helpers
    def _origins(self) -> tuple[str, ...]:
        port = self.server.server_address[1]
        return (f"127.0.0.1:{port}", f"localhost:{port}")

    def _host_allowed(self) -> bool:
        # A page on another site may resolve its own name to 127.0.0.1 (DNS rebinding).
        return self.headers.get("Host", "") in self._origins()

    def _reply(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value) -> None:
        self._reply(status, json.dumps(value, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")

    # ------------------------------------------------------------ routes
    def do_GET(self):
        if not self._host_allowed():
            return self._json(403, _fail("host_denied", "Open the board at 127.0.0.1 or localhost."))
        path = urlsplit(self.path).path
        if path == "/":
            page = (STATIC / "board.html").read_text(encoding="utf-8")
            return self._reply(200, page.replace("__BOARD_TOKEN__", self.server.token).encode("utf-8"),
                               "text/html; charset=utf-8")
        if path == "/api/board":
            return self._json(200, model.snapshot(self.server.config))
        if path == "/api/live":
            try:
                return self._json(200, {"ok": True, "data": model.liveness(self.server.config), "error": None})
            except model.SessionError as error:
                return self._json(200, {"ok": False, "data": None, "error": model._error(error)})
        return self._json(404, _fail("not_found", "No such page."))

    def do_POST(self):
        if urlsplit(self.path).path != "/api/answer":
            return self._json(404, _fail("not_found", "No such endpoint."))
        if not self._host_allowed():
            return self._json(403, _fail("host_denied", "Open the board at 127.0.0.1 or localhost."))
        origin = self.headers.get("Origin")
        if origin is not None and origin not in tuple("http://" + item for item in self._origins()):
            return self._json(403, _fail("origin_denied", "Answers are accepted from the board page only."))
        if not secrets.compare_digest(self.headers.get("X-Board-Token", ""), self.server.token):
            return self._json(403, _fail("token_denied", "Reload the board page and send again."))
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            return self._json(415, _fail("json_required", "Send the answer as JSON."))
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._json(411, _fail("length_required", "Content-Length is required."))
        if length < 0 or length > MAX_REQUEST:
            return self._json(413, _fail("request_too_large", "The request is too large."))
        try:
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            project_id, decide_id, answer = request["project"], request["decide_id"], request["answer"]
            if not all(isinstance(value, str) for value in (project_id, decide_id, answer)):
                raise TypeError
        except (UnicodeError, ValueError, KeyError, TypeError):
            return self._json(400, _fail("invalid_request", "Send project, decide_id and answer as strings."))
        if not answer.strip() or "\x00" in answer:
            return self._json(400, _fail("answer_empty", "Write an answer before sending."))
        if len(answer.encode("utf-8")) > MAX_ANSWER:
            return self._json(400, _fail("answer_too_large", f"Keep the answer within {MAX_ANSWER} bytes."))
        try:
            project = model.find_project(self.server.config, project_id)
            if project is None:
                return self._json(404, _fail("project_not_found", "The project is not registered."))
            decision = model.open_decision(project, decide_id)
        except Exception as error:
            return self._json(500, {"ok": False, "data": None, "error": model._error(error)})
        if decision is None:
            return self._json(409, _fail("decide_not_open", "The decision is no longer waiting for an answer."))
        result = send_answer(project, answer_message(project.project_id, decide_id, decision["title"], answer))
        return self._json(200 if result.get("ok") else 502, result)


class BoardServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, config=None, verbose=False):
        super().__init__((HOST, port), Handler)
        self.config = config
        self.token = secrets.token_urlsafe(32)
        self.verbose = verbose


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="project-board",
                                     description="Show every registered project team on a local page.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port on 127.0.0.1 (default {DEFAULT_PORT})")
    parser.add_argument("--config", metavar="PATH", help="project registry (default: agent-session's standard paths)")
    parser.add_argument("--verbose", action="store_true", help="log every request")
    args = parser.parse_args(argv)
    try:
        server = BoardServer(args.port, args.config, args.verbose)
    except OSError as error:
        print(f"project-board: cannot listen on {HOST}:{args.port}: {error}", file=sys.stderr)
        return 1
    agent = [name for name in AGENT_ENV if os.environ.get(name)]
    if agent:
        print("project-board: this process runs inside an agent session (" + ", ".join(agent) + "). "
              "agent-session rejects its answers; start the board from your own terminal.", file=sys.stderr)
    print(f"Project Board: http://{HOST}:{server.server_address[1]}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
