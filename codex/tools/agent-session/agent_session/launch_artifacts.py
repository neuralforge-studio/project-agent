"""The files that start a run: prompt document, provider input, `launch.sh`, and `controller.sh`.

Dependency direction: `lifecycle` imports this module; this module never imports `lifecycle`. It decides
what the generated files contain from the project, the provider, and the run context it is given. It
keeps no state and starts nothing: the order of preparation, the tmux window, and failure handling stay
with the caller. The generated command lines call `agent_session.internal` by name, so a run that is
already up keeps working (docs/project-team/README.md, "실행 경로 계약").
"""

import os
import shlex
import sys
from pathlib import Path

from .errors import SessionError
from .util import write_json

PROMPT_LIMIT = 65536                               # UTF-8 bytes of the initial prompt


def library_path():
    """The directory that holds the `agent_session` package, which every generated command puts on `sys.path`."""
    return Path(__file__).resolve().parents[1]


def run_directory(project, run_id):
    return project.runtime_path / "runs" / run_id


def _registration_command(context):
    code = ("import sys; sys.path.insert(0,sys.argv[1]); "
            "from agent_session.internal import register_current; "
            "register_current(run_id=sys.argv[2],config_path=sys.argv[3],"
            "socket_path=sys.argv[4],endpoint=sys.argv[5])")
    return shlex.join([context["python"], "-c", code, context["library_path"],
                       context["run_id"], context["config_path"], context["socket_path"],
                       context.get("endpoint") or ""])


def prompt_text(project, context, request=None):
    """The initial prompt of a run. A resumed conversation has one already, so it gets only `request`."""
    if context.get("resume"):
        return request                 # the conversation exists; the resume message is sent after registration
    role = "Leader" if context["seat"] is None else "Worker"
    text = "$project-team을 사용하십시오. 현재 프로젝트의 " + role + " 역할입니다.\n"
    if project.provider == "codex":
        text += ("첫 도구 호출에서 다음 내부 등록을 실행하십시오. 작업 디렉토리는 " + context["cwd"]
                 + "입니다. 등록 성공 전에는 일반 작업을 시작하지 마십시오.\n\n" + _registration_command(context) + "\n\n")
    else:
        text += "SessionStart 내부 등록이 실패하면 작업을 시작하지 마십시오.\n\n"
    if context.get("handoff_file"):
        path = Path(context["handoff_file"])
        text += "이전 대화는 보존됐습니다. 다음 인계로 같은 작업을 이어받으십시오.\n" + path.read_text(encoding="utf-8") + "\n"
    job = context.get("job")
    if job:
        base = (job.get("base") or {}).get("base_hash") or "준비 중"
        text += ("배정 CR: " + job["job_id"] + " (" + job["title"] + ")\n"
                 + "CR 파일: " + job["path"] + "\n"
                 + "Seat: " + context["seat_root"] + "\n"
                 + "작업 디렉토리: " + context["cwd"] + "\n"
                 + "Mode: " + job["mode"] + "\n"
                 + "Branch: " + (job.get("branch") or "없음(read-only)") + "\n"
                 + "Base: " + base + "\n\n"
                 + "작업 전에 위 CR 파일을 읽고, 그 본문이 link한 지침 문서도 읽으십시오. "
                 + "범위·구현·검증 기준의 원본은 CR 파일입니다.\n\n")
    text += request or (
        "인계 문서와 프로젝트 지침을 읽고 승인된 미완료 작업을 계속하십시오." if context.get("handoff_file") else
        "프로젝트 지침과 `project-item ls`의 결정 대기·CR을 확인하고 사용자 작업 지시를 기다리십시오. "
        "사용자에게 묻는 결정은 결정 항목으로 남기고, 위임 범위의 판정은 근거와 함께 CR에 기록하십시오(project-team skill)."
        if job is None else
        "CR의 범위에서 작업하고 검증하십시오. 제출 commit과 검증 결과를 CR 파일의 `## Result`에 쓰고 "
        "`agent-session send --job leader`로 보고하십시오.")
    if len(text.encode("utf-8")) > PROMPT_LIMIT:
        raise SessionError("prompt_too_large", "Initial JOB and handoff exceed 65536 UTF-8 bytes.", 2)
    return text


def session_input(project, context, hooks, prompt):
    """Provider input from the common prompt and the project's launch args for this role."""
    directory = run_directory(project, context["run_id"])
    path = directory / "prompt.md"
    path.write_text(prompt, encoding="utf-8")
    role = "leader" if context["target"] == "leader" else "worker"
    prepared = {"prompt_file": str(path), "provider_args": list(project.args_for(role)),
                "env": {}, "unset_env": [], "settings_file": None}
    if project.provider == "claude":
        settings = {"crossSessionInbound": "accept", "hooks": hooks}
        settings_path = directory / "settings.json"
        write_json(settings_path, settings)
        prepared.update(settings_file=str(settings_path), provider_name=context.get("window_name"))
    return prepared


def prepare(project, provider, context, request, remaining):
    """Write the run's prompt and provider settings; return the provider input and its launch spec.

    A remote seat's files are written on its own host, so it has none here. `remaining` returns the
    seconds left of the command, and is read after the Codex Leader's workspace trust is recorded."""
    if context.get("remote_seat"):
        return {}, {}
    if project.provider == "codex" and context["target"] == "leader":
        provider.trust_base(project.base)
    context["timeout"] = remaining()
    run_directory(project, context["run_id"]).mkdir(parents=True, exist_ok=True)
    hooks = provider.registration_hooks(context)
    prepared = session_input(project, context, hooks, prompt_text(project, context, request))
    prepared.setdefault("env", {}).update({
        "AGENT_SESSION_CONFIG": context["config_path"],
        "AGENT_SESSION_SOCKET": context["socket_path"],
        "AGENT_SESSION_BASE": context["base"],
    })
    if context.get("upstream"):
        prepared["env"].update(AGENT_SESSION_UPLINK=context["upstream"],
                               PYTHONPATH=context["library_path"],
                               PATH=context["upstream_bin"] + os.pathsep + os.environ.get("PATH", ""))
    return prepared, provider.launch_spec(context, prepared)


def launch_script(context, launch):
    """The text of `launch.sh`: clean the environment, enter the CR's Cwd, mark the process, and exec the CLI."""
    code = ("import sys;sys.path.insert(0,sys.argv[1]);from agent_session.internal import mark_process;"
            "mark_process(sys.argv[2],sys.argv[3],sys.argv[4],int(sys.argv[5]))")
    marker = shlex.join([context["python"], "-c", code, context["library_path"], context["run_id"],
                         context["config_path"], context["socket_path"]]) + ' "$$"'
    clean = [key for key in os.environ if key.startswith("CLAUDE_CODE_MESSAGING_") or key.startswith("AGENT_SESSION_")]
    clean += ["CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"] + launch.get("unset_env", [])
    lines = ["#!/bin/bash", "set -e",
             'for name in ${!CLAUDE_CODE_MESSAGING_@} ${!AGENT_SESSION_@}; do unset "$name"; done',
             "unset " + " ".join(shlex.quote(key) for key in sorted(set(clean))),
             "cd " + shlex.quote(context["cwd"]), marker]
    for name, value in launch.get("env", {}).items():
        lines.append("export " + name + "=" + shlex.quote(value))
    lines.append("exec " + shlex.join(launch["argv"]))
    return "\n".join(lines) + "\n"


def write_launch_script(project, context, launch):
    script = run_directory(project, context["run_id"]) / "launch.sh"
    script.write_text(launch_script(context, launch), encoding="utf-8")
    return script


def controller_script(request_file):
    """The text of `controller.sh`: run the deferred stop or restart that `request_file` describes."""
    code = "import sys;sys.path.insert(0,sys.argv[1]);from agent_session.internal import run_controller;run_controller(sys.argv[2])"
    command = shlex.join([sys.executable, "-c", code, str(library_path()), str(request_file)])
    return "#!/bin/bash\nset -e\nunset CODEX_THREAD_ID CLAUDE_CODE_SESSION_ID TMUX TMUX_PANE\nexec " + command + "\n"


def write_controller_script(directory, request_file):
    script = Path(directory) / "controller.sh"
    script.write_text(controller_script(request_file), encoding="utf-8")
    return script
