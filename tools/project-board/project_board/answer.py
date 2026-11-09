"""Record a user's decision answer, then notify the project's Leader."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from . import model
from project_item import api as item_api
from project_item.api import ItemError

AGENT_SESSION = model.TOOLS / "agent-session" / "bin" / "agent-session"
MAX_ANSWER = item_api.MAX_ANSWER_BYTES
SEND_TIMEOUT = 30                        # agent-session send --timeout


def _fail(code: str, message: str, details: dict | None = None) -> dict:
    return {"ok": False, "data": None,
            "error": {"code": code, "message": message, "details": details or {}}}


def answer_message(project_id: str, decide_id: str, title: str, answer: str) -> str:
    """Format the exact user answer for the project's Leader."""
    return (f"결정 답변: {decide_id}\n"
            f"Project: {project_id}\n"
            f"질문: {title}\n"
            "사용자가 Project Board에서 입력한 답을 Decision에 접수했습니다. 결정 항목 절차에 따라 확인하고 항목을 옮기십시오. "
            "`답변:` 다음 줄부터 끝까지가 답변 원문입니다.\n"
            "답변:\n"
            f"{answer}")


def send_answer(project, text: str) -> dict:
    """Use the public agent-session command as the operator running the Board."""
    with tempfile.TemporaryDirectory(prefix="project-board-") as directory:
        body = Path(directory) / "answer.md"
        body.write_text(text, encoding="utf-8")
        command = [str(AGENT_SESSION), "--config", str(project.config_path), "send", "--job", "leader",
                   "--file", str(body), "--timeout", str(SEND_TIMEOUT)]
        try:
            run = subprocess.run(command, cwd=project.base, capture_output=True, text=True,
                                 timeout=SEND_TIMEOUT + 30)
        except OSError as error:
            return _fail("send_unavailable", str(error))
        except subprocess.TimeoutExpired:
            return _fail("send_unconfirmed", "agent-session did not finish; the Leader may have received the answer.")
    try:
        result = json.loads(run.stdout.strip().splitlines()[-1])
        if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
            raise ValueError("agent-session did not return an operation result")
        return result
    except (IndexError, ValueError):
        return _fail("send_unconfirmed", "agent-session did not return a JSON result; the Leader may have received the answer.",
                     {"exit": run.returncode, "stderr": run.stderr[-2000:]})


def _notification(project, text: str) -> dict:
    """Delivery is advisory: the saved answer remains accepted if delivery fails."""
    try:
        state = model._read_state(project)
        if not state or not state.get("leader"):
            result = _fail("leader_unavailable", "The project Leader is not running.")
        else:
            live = model.api.project_liveness(project).get("leader", {})
            if live.get("session_id") == state["leader"]["session_id"] and live.get("state") == "stopped":
                result = _fail("leader_stopped", "The project Leader has stopped.")
            else:
                result = send_answer(project, text)
    except Exception as error:
        issue = model._error(error)
        result = _fail(issue["code"], issue["message"])
    if result.get("ok"):
        return {"status": "sent"}
    error = result.get("error") or {}
    return {"status": "unconfirmed" if error.get("code") == "send_unconfirmed" else "failed",
            "error": error}


def submit_answer(config, project_id: str, decide_id: str, answer: str) -> dict:
    """Accept one answer under the decision root lock before attempting delivery."""
    if not all(isinstance(value, str) for value in (project_id, decide_id, answer)):
        return _fail("invalid_request", "Project, decision ID and answer must be text.")
    if not answer.strip() or "\x00" in answer:
        return _fail("answer_empty", "Write an answer before sending.")
    if len(answer.encode("utf-8")) > MAX_ANSWER:
        return _fail("answer_too_large", f"Keep the answer within {MAX_ANSWER} bytes.")
    try:
        project = model.find_project(config, project_id)
        if project is None:
            return _fail("project_not_found", "The project is not registered.")
        decision = model.open_decision(project, decide_id)
    except Exception as error:
        issue = model._error(error)
        return _fail(issue["code"], issue["message"])
    if decision is None:
        return _fail("decide_not_open", "The decision is no longer waiting for an answer.")
    try:
        actor, _ = model.api.caller(project)
        if actor == "unmanaged-agent":
            return _fail("caller_unbound", "This agent is not a registered member of this project.")
        if actor != "operator":
            return _fail("role_denied", "Only the operator may answer a decision.")
    except Exception as error:
        issue = model._error(error)
        return _fail(issue["code"], issue["message"])
    try:
        item_api.answer_decide(project.path_decide, decide_id, answer)
    except ItemError as error:
        return _fail(error.code, error.message)
    except Exception as error:
        issue = model._error(error)
        return _fail(issue["code"], issue["message"])
    page_error = None
    try:
        item_api.render_decision_page(project.project_id, project.path_decide, cr_root=project.path_cr)
    except Exception as error:
        page_error = model._error(error)
    delivery = _notification(project, answer_message(project.project_id, decide_id, decision["title"], answer))
    data = {"accepted": True, "notification": delivery}
    if page_error:
        data["page_error"] = page_error
    return {"ok": True, "data": data, "error": None}
