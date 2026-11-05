import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from agent_session import cli
from agent_session.errors import SessionError


class FakeManager:
    def __init__(self, **options):
        self.options = options

    def start(self, job, prompt_file=None):
        return {"command": "start", "options": self.options, "job": job, "prompt_file": prompt_file}

    def send(self, **arguments):
        return {"command": "send", "options": self.options, **arguments}

    def control(self, operation, **arguments):
        return {"command": operation, "options": self.options, **arguments}

    def review(self, **arguments):
        return {"command": "review", "options": self.options, **arguments}


@pytest.mark.parametrize("argv, expected", [
    (["start", "--job", "leader"], {"command": "start", "job": "leader", "prompt_file": None}),
    (["start", "--job", "J-20261103-07.md"], {"command": "start", "job": "J-20261103-07.md", "prompt_file": None}),
    (["start", "--job", "leader", "--prompt-file", "REQUEST.md"],
     {"command": "start", "job": "leader", "prompt_file": "REQUEST.md"}),
    (["send", "--job", "leader", "작업 결과입니다."],
     {"command": "send", "job": "leader", "seat": None, "message": "작업 결과입니다.", "file": None, "project": None}),
    (["send", "--seat", "0", "--file", "FEEDBACK.md"],
     {"command": "send", "job": None, "seat": 0, "message": None, "file": "FEEDBACK.md", "project": None}),
    (["send", "--job", "J-20261103-07", "--", "--literal-message"],
     {"command": "send", "job": "J-20261103-07", "seat": None, "message": "--literal-message", "file": None, "project": None}),
    (["send", "--project", "other", "--job", "leader", "협업 요청입니다."],
     {"command": "send", "job": "leader", "seat": None, "message": "협업 요청입니다.", "file": None, "project": "other"}),
    (["stop", "--seat", "9"], {"command": "stop", "job": None, "seat": 9}),
    (["restart", "--job", "leader"], {"command": "restart", "job": "leader", "seat": None}),
    (["review", "--job", "TOOL-013"], {"command": "review", "job": "TOOL-013", "clear": False}),
    (["review", "--clear"], {"command": "review", "job": None, "clear": True}),
])
def test_dispatch_keeps_input_meaning_and_emits_one_result(argv, expected, capsys):
    assert cli.main(argv, manager_factory=FakeManager) == 0
    output = capsys.readouterr()
    assert not output.err
    assert len(output.out.splitlines()) == 1
    result = json.loads(output.out)
    assert result["ok"] is True and result["error"] is None
    options = result["data"].pop("options")
    assert result["data"] == expected
    assert options == {"cwd": None, "config_path": None, "socket_name": None, "socket_path": None,
                       "timeout": 30 if expected["command"] in ("send", "review") else 600}


def test_global_source_and_socket_precede_the_command(capsys):
    args = ["--config", "/tmp/project.json", "--socket-path", "/tmp/test.sock",
            "send", "--job", "leader", "--file", "MESSAGE.md", "--timeout", "12"]
    assert cli.main(args, manager_factory=FakeManager) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["data"]["options"] == {"cwd": None, "config_path": "/tmp/project.json",
                                        "socket_name": None, "socket_path": "/tmp/test.sock", "timeout": 12}


@pytest.mark.parametrize("argv", [
    [], ["status"], ["projects"], ["bind"], ["event"],
    ["start"], ["start", "--job", ""],
    ["start", "--job", "JOB.md", "--prompt-file", "OTHER.md"],
    ["start", "--leader"], ["start", "--job-file", "JOB.md"],
    ["send", "--job", "leader"], ["send", "message"],
    ["send", "--job", "leader", "--seat", "1", "message"],
    ["send", "--job", "leader", "message", "--file", "MESSAGE.md"],
    ["send", "--job", "leader", ""], ["send", "--job", "leader", "   "],
    ["send", "--project", "", "--job", "leader", "message"],
    ["stop", "--project", "other", "--job", "leader"], ["restart", "--project", "other", "--job", "leader"],
    ["review", "--project", "other", "--clear"], ["start", "--project", "other", "--job", "leader"],
    ["stop", "--seat", "-1"], ["stop", "--seat", "10"],
    ["restart", "--job", "leader", "--seat", "0"],
    ["review"], ["review", "--job", "TOOL-013", "--clear"], ["review", "--seat", "0"], ["review", "--job", ""],
    ["view"], ["view", "--help"], ["view", "--job", "leader"],
    ["view", "--seat", "0"], ["view", "--job", "leader", "--into", "my-session"],
    ["start", "--job", "leader", "--timeout", "0"],
    ["start", "--job", "leader", "--timeout", "1.5"],
    ["--socket-name", "test", "--socket-path", "/tmp/test.sock", "start", "--job", "leader"],
    ["start", "--job", "leader", "--config", "/tmp/project.json"],
])
def test_input_error_has_no_manager_side_effect(argv, capsys):
    calls = []
    def factory(**options):
        calls.append(options)
        return FakeManager(**options)
    assert cli.main(argv, manager_factory=factory) == 2
    output = capsys.readouterr()
    assert not output.err
    assert len(output.out.splitlines()) == 1
    result = json.loads(output.out)
    assert result["ok"] is False and result["data"] is None
    assert result["error"]["code"] == "invalid_arguments"
    assert calls == []


def test_help_lists_only_current_commands(capsys):
    assert cli.main(["--help"]) == 0
    output = capsys.readouterr()
    assert not output.err
    assert "{start,send,stop,restart,review}" in output.out
    assert re.search(r"\bview\b", output.out) is None


def test_known_failure_keeps_partial_work_facts(capsys):
    class Failed(FakeManager):
        def start(self, *args, **kwargs):
            raise SessionError("needs_user_action", "Provider login is required.", 3,
                               {"job_id": "J-20261103-07", "run_id": "run-one", "window_id": "@3"})
    assert cli.main(["start", "--job", "JOB.md"], manager_factory=Failed) == 3
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["error"]["details"] == {"job_id": "J-20261103-07", "run_id": "run-one", "window_id": "@3"}
    assert not output.err


def failing_manager(runtime_path, error):
    class Failed(FakeManager):
        def __init__(self, **options):
            super().__init__(**options)
            self.project = SimpleNamespace(runtime_path=runtime_path)

        def start(self, *args, **kwargs):
            raise error

        def send(self, **kwargs):
            raise error
    return Failed


def test_unknown_failure_does_not_print_exception_data(tmp_path, capsys):
    error = RuntimeError("DO_NOT_PRINT_PRIVATE_EXCEPTION_DATA")
    assert cli.main(["send", "--job", "leader", "hello"],
                    manager_factory=failing_manager(tmp_path / "agent", error)) == 5
    output = capsys.readouterr()
    assert "DO_NOT_PRINT" not in output.out + output.err
    assert not output.err
    result = json.loads(output.out)
    assert result["error"]["code"] == "internal_error"
    diagnostic = result["error"]["details"]["diagnostic"]
    assert result["error"]["details"] == {"operation": "send", "effects_possible": True, "diagnostic": diagnostic}
    assert "DO_NOT_PRINT_PRIVATE_EXCEPTION_DATA" in Path(diagnostic).read_text(encoding="utf-8")


def test_unexpected_failure_keeps_its_traceback_in_a_private_project_file(tmp_path, capsys):
    # SESSION-003: a start failed with internal_error and left no trace of its KeyError.
    runtime = tmp_path / "agent"
    assert cli.main(["start", "--job", "leader"],
                    manager_factory=failing_manager(runtime, KeyError("message_to"))) == 5
    output = capsys.readouterr()
    assert not output.err
    assert "KeyError" not in output.out and "message_to" not in output.out
    error = json.loads(output.out)["error"]
    assert error["code"] == "internal_error"
    assert error["message"] == "The command failed. Check the retained project state."
    diagnostic = Path(error["details"].pop("diagnostic"))
    assert error["details"] == {"operation": "start", "effects_possible": True}
    assert diagnostic.parent == runtime / "diagnostics"
    assert diagnostic.name.endswith(f"-start-{os.getpid()}.log")
    assert stat.S_IMODE(diagnostic.stat().st_mode) == 0o600
    text = diagnostic.read_text(encoding="utf-8")
    assert "Traceback" in text and "KeyError: 'message_to'" in text


@pytest.mark.parametrize("unwritable", [False, True])
def test_unexpected_failure_without_a_diagnostic_place_keeps_the_result(tmp_path, capsys, unwritable):
    if unwritable:
        (tmp_path / "agent").write_text("not a directory")
        factory = failing_manager(tmp_path / "agent", KeyError("message_to"))
    else:
        def factory(**options):
            raise KeyError("message_to")
    assert cli.main(["start", "--job", "leader"], manager_factory=factory) == 5
    output = capsys.readouterr()
    assert not output.err
    error = json.loads(output.out)["error"]
    assert error["code"] == "internal_error"
    assert error["details"] == {"operation": "start", "effects_possible": True}


def test_interruption_does_not_report_a_completed_stop(capsys):
    class Interrupted(FakeManager):
        def control(self, *args, **kwargs):
            raise KeyboardInterrupt
    assert cli.main(["stop", "--job", "leader"], manager_factory=Interrupted) == 4
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert result["error"]["code"] == "interrupted"
    assert result["error"]["details"]["effects_possible"] is True


def test_command_logs_use_stderr_and_self_control_keeps_acceptance_semantics(capsys):
    class Deferred(FakeManager):
        def control(self, *args, **kwargs):
            print("controller submitted")
            return {"accepted": True, "completed": False, "result_file": Path("/tmp/control-result.json")}
    assert cli.main(["restart", "--job", "leader"], manager_factory=Deferred) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["data"] == {"accepted": True, "completed": False, "result_file": "/tmp/control-result.json"}
    assert output.err.strip() == "controller submitted"


def test_entry_points_work_outside_the_source_tree_without_pythonpath(tmp_path):
    env = dict(os.environ, PYTHONPATH="/not-the-source")
    entry = subprocess.run([sys.executable, str(TOOL / "agent_session.py"), "--help"],
                           cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10)
    assert entry.returncode == 0 and "usage:" in entry.stdout
    assert not entry.stderr
    link = tmp_path / "agent-session"
    link.symlink_to(TOOL / "bin/agent-session")
    launched = subprocess.run([str(link), "--help"], cwd=tmp_path, env=env,
                              capture_output=True, text=True, timeout=10)
    assert launched.returncode == 0 and "usage:" in launched.stdout
    assert not launched.stderr


def test_launcher_missing_wsl_interpreter_returns_structured_error(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path), WSL_DISTRO_NAME="test-wsl")
    result = subprocess.run([str(TOOL / "bin/agent-session"), "--help"],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 5
    assert json.loads(result.stdout)["error"]["code"] == "python_unavailable"
    assert not result.stderr
