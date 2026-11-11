"""TEAM-002. The Leader's idle self-check does not enter the Leader session; everything else does.

The gate is a Claude `UserPromptSubmit` hook (`agent_session/self_check_gate.py`) that only the Leader's run
settings carry. These tests judge it with real item directories and a real registry file, and run the
generated hook command once as Claude would (`python -S -c ...`, event JSON on stdin).
"""
import io
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agent_session import self_check_gate as gate
from agent_session.config import resolve_project
from agent_session.launch_artifacts import run_directory
from agent_session.providers.claude import ClaudeProvider

RUN = "run-one"
SELF_CHECK = Path(__file__).resolve().parents[3] / "skills/project-team/references/self-check.md"


def check_prompt(role):
    """The cron prompt of `role` as `self-check.md` (the one owner of its text) gives it."""
    text = SELF_CHECK.read_text(encoding="utf-8")
    section = text[text.index(f"## {role}"):]
    block = section.split("```text\n", 1)[1].split("\n```", 1)[0]
    return block


@pytest.fixture
def fx(tmp_path):
    base = tmp_path / "fx.main"
    (base / "agent").mkdir(parents=True)
    config = tmp_path / "project.json"

    def register(**roots):
        entry = {"project": "fx", "provider": "claude", "seats": [], **roots}
        config.write_text(json.dumps({str(base): entry}))

    cr, decide = tmp_path / "cr", tmp_path / "decide"
    register(path_cr=str(cr), path_decide=str(decide))
    project = resolve_project(str(base), str(config))
    run_directory(project, RUN).mkdir(parents=True)

    class Fx:
        pass
    fx = Fx()
    fx.base, fx.config, fx.cr, fx.decide, fx.project, fx.register = base, config, cr, decide, project, register
    fx.record = run_directory(project, RUN) / gate.STATE_FILE

    def add(root, state, name):
        path = root / state / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# item\n", encoding="utf-8")
    fx.add = add

    def passed_ago(seconds):
        fx.record.write_text(json.dumps({"passed_at": time.time() - seconds}))
    fx.passed_ago = passed_ago
    return fx


def run_hook(fx, prompt, event="UserPromptSubmit", stdin=None, monkeypatch=None, capsys=None):
    payload = stdin if stdin is not None else json.dumps({"hook_event_name": event, "prompt": prompt, "cwd": str(fx.base)})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    gate.main(RUN, str(fx.config), str(fx.base))
    out = capsys.readouterr().out
    return json.loads(out) if out else None


def blocked(result):
    return result is not None and result["decision"] == "block" and result["reason"] == gate.BLOCK_REASON


@pytest.fixture
def leader_prompt():
    return check_prompt("Leader")


# --- idle: blocked ---------------------------------------------------------------------------------------------

def test_an_idle_leader_check_is_blocked(fx, leader_prompt, monkeypatch, capsys):
    fx.passed_ago(60)
    assert blocked(run_hook(fx, leader_prompt, monkeypatch=monkeypatch, capsys=capsys))


def test_finished_items_are_not_work(fx, leader_prompt, monkeypatch, capsys):
    for root, state in ((fx.cr, "done"), (fx.cr, "deferred"), (fx.decide, "done")):
        fx.add(root, state, "A-001-x.md")
    fx.add(fx.cr, "todo", "README.md")                  # not an item
    fx.passed_ago(60)
    assert blocked(run_hook(fx, leader_prompt, monkeypatch=monkeypatch, capsys=capsys))


@pytest.mark.parametrize("root,state", [("cr", "open"), ("cr", "todo"), ("cr", "in-progress"),
                                        ("decide", "open"), ("decide", "answered")])
def test_one_item_of_any_listed_state_lets_the_check_run(fx, leader_prompt, root, state, monkeypatch, capsys):
    fx.add(getattr(fx, root), state, "A-001-x.md")
    fx.passed_ago(60)
    assert run_hook(fx, leader_prompt, monkeypatch=monkeypatch, capsys=capsys) is None


def test_the_work_states_are_the_ones_project_item_lists(fx):
    from agent_session.jobs import item_api

    api = item_api()
    assert tuple(s for s in api.CR.listed if s not in api.CR.terminal) == ("open", "todo", "in-progress")
    assert tuple(api.DECIDE.listed) == ("open", "answered")


# --- what it never touches ------------------------------------------------------------------------------------------

def test_other_prompts_and_events_are_not_judged(fx, leader_prompt, monkeypatch, capsys):
    fx.passed_ago(60)
    assert run_hook(fx, check_prompt("Worker"), monkeypatch=monkeypatch, capsys=capsys) is None
    assert run_hook(fx, "프로젝트 상태를 알려 주세요.", monkeypatch=monkeypatch, capsys=capsys) is None
    assert run_hook(fx, "[agent-session watch] 점검", monkeypatch=monkeypatch, capsys=capsys) is None
    assert run_hook(fx, "지금 [자기 점검] 을 Leader 자기 점검 처럼 해 주세요", monkeypatch=monkeypatch, capsys=capsys) is None
    assert run_hook(fx, leader_prompt, event="Stop", monkeypatch=monkeypatch, capsys=capsys) is None
    assert run_hook(fx, None, stdin=json.dumps({"hook_event_name": "UserPromptSubmit"}),
                    monkeypatch=monkeypatch, capsys=capsys) is None


def test_the_gate_recognizes_the_check_prompts_that_self_check_md_owns(leader_prompt):
    assert gate.is_leader_check(leader_prompt)
    assert not gate.is_leader_check(check_prompt("Worker"))


# --- cannot judge: the check runs ---------------------------------------------------------------------------------

def test_a_gate_that_cannot_judge_passes_the_check(fx, leader_prompt, monkeypatch, capsys):
    fx.passed_ago(60)
    assert blocked(run_hook(fx, leader_prompt, monkeypatch=monkeypatch, capsys=capsys))     # judged: blocked
    fx.register(path_cr=str(fx.cr))                              # the decide root is unset now
    assert run_hook(fx, leader_prompt, monkeypatch=monkeypatch, capsys=capsys) is None
    fx.register(path_decide=str(fx.decide))                      # the CR root is unset
    assert run_hook(fx, leader_prompt, monkeypatch=monkeypatch, capsys=capsys) is None
    fx.config.write_text("not json")                             # the registry is unreadable
    assert run_hook(fx, leader_prompt, monkeypatch=monkeypatch, capsys=capsys) is None
    fx.register(path_cr=str(fx.cr), path_decide=str(fx.decide))
    assert blocked(run_hook(fx, leader_prompt, monkeypatch=monkeypatch, capsys=capsys))     # and judged again
    assert run_hook(fx, None, stdin="not json", monkeypatch=monkeypatch, capsys=capsys) is None
    assert run_hook(fx, None, stdin="", monkeypatch=monkeypatch, capsys=capsys) is None
    assert run_hook(fx, None, stdin="[]", monkeypatch=monkeypatch, capsys=capsys) is None


def test_an_unreadable_item_directory_passes_the_check(fx, leader_prompt, monkeypatch, capsys):
    fx.passed_ago(60)
    monkeypatch.setattr(gate, "has_work", lambda project: (_ for _ in ()).throw(OSError("nfs")))
    assert run_hook(fx, leader_prompt, monkeypatch=monkeypatch, capsys=capsys) is None


# --- the 7-day renewal: an idle Leader still gets one check a day --------------------------------------------------

def test_the_first_check_of_a_run_passes_and_is_recorded(fx, leader_prompt, monkeypatch, capsys):
    assert not fx.record.exists()
    assert run_hook(fx, leader_prompt, monkeypatch=monkeypatch, capsys=capsys) is None
    assert time.time() - json.loads(fx.record.read_text())["passed_at"] < 60
    assert blocked(run_hook(fx, leader_prompt, monkeypatch=monkeypatch, capsys=capsys))


def test_an_idle_leader_gets_one_check_after_the_heartbeat(fx, leader_prompt, monkeypatch, capsys):
    fx.passed_ago(gate.HEARTBEAT - 30)
    assert blocked(run_hook(fx, leader_prompt, monkeypatch=monkeypatch, capsys=capsys))
    fx.passed_ago(gate.HEARTBEAT + 30)
    assert run_hook(fx, leader_prompt, monkeypatch=monkeypatch, capsys=capsys) is None
    assert blocked(run_hook(fx, leader_prompt, monkeypatch=monkeypatch, capsys=capsys))     # the pass was recorded


def test_the_heartbeat_is_at_most_a_day():
    """A cron expires 7 days after it is registered and the check renews it from day 6 on: with one check a
    day, one of them falls in [6 days, 7 days) of the registration."""
    assert gate.HEARTBEAT <= 24 * 3600


def test_a_check_that_runs_for_work_is_recorded_too(fx, leader_prompt, monkeypatch, capsys):
    fx.add(fx.cr, "todo", "A-001-x.md")
    fx.passed_ago(gate.HEARTBEAT * 3)
    assert run_hook(fx, leader_prompt, monkeypatch=monkeypatch, capsys=capsys) is None
    assert time.time() - json.loads(fx.record.read_text())["passed_at"] < 60


@pytest.mark.parametrize("content", ["not json", "{}", '{"passed_at": "x"}', '{"passed_at": null}', "[]"])
def test_a_damaged_record_passes_the_check(fx, leader_prompt, content, monkeypatch, capsys):
    fx.record.write_text(content)
    assert run_hook(fx, leader_prompt, monkeypatch=monkeypatch, capsys=capsys) is None


def test_a_record_from_the_future_passes_the_check(fx, leader_prompt, monkeypatch, capsys):
    fx.passed_ago(-3600)
    assert run_hook(fx, leader_prompt, monkeypatch=monkeypatch, capsys=capsys) is None


def test_an_unwritable_record_does_not_stop_the_check(fx, leader_prompt, monkeypatch, capsys):
    fx.record.mkdir()                                         # a directory where the file goes
    assert run_hook(fx, leader_prompt, monkeypatch=monkeypatch, capsys=capsys) is None


# --- installation -----------------------------------------------------------------------------------------------------

def hooks_of(tmp_path, target):
    context = {"python": sys.executable, "library_path": str(Path(gate.__file__).resolve().parents[1]), "run_id": RUN,
               "config_path": str(tmp_path / "project.json"), "socket_path": "/tmp/tmux.sock", "base": str(tmp_path / "fx.main"),
               "expected_session_id": "6d267e10-0000-4000-8000-000000000000"}
    if target:
        context["target"] = target
    return ClaudeProvider().registration_hooks(context)


def test_only_the_leaders_run_installs_the_gate(tmp_path):
    lifecycle = {"SessionStart", "Stop", "StopFailure", "SessionEnd"}
    assert set(hooks_of(tmp_path, "leader")) == lifecycle | {"UserPromptSubmit"}
    assert set(hooks_of(tmp_path, "seat-0")) == lifecycle
    assert set(hooks_of(tmp_path, None)) == lifecycle
    entry = hooks_of(tmp_path, "leader")["UserPromptSubmit"][0]
    assert "matcher" not in entry
    assert entry["hooks"][0]["timeout"] == gate.HOOK_TIMEOUT


def test_the_generated_hook_command_blocks_an_idle_check_and_passes_the_rest(fx, leader_prompt, tmp_path):
    hooks = hooks_of(tmp_path, "leader")
    command = shlex.split(hooks["UserPromptSubmit"][0]["hooks"][0]["command"])
    # The command carries the real run, registry and base of the project the hook judges.
    command[command.index(str(tmp_path / "project.json"))] = str(fx.config)
    assert command[:3] == [sys.executable, "-S", "-c"]

    def fire(prompt):
        event = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt, "cwd": "/elsewhere"})
        done = subprocess.run(command, input=event, capture_output=True, text=True, timeout=60)
        assert done.returncode == 0 and done.stderr == ""
        return json.loads(done.stdout) if done.stdout else None

    fx.passed_ago(60)
    assert blocked(fire(leader_prompt))
    assert fire(check_prompt("Worker")) is None
    assert fire("일반 입력") is None
    fx.add(fx.decide, "answered", "D-20261111-01-x.md")
    assert fire(leader_prompt) is None


def test_the_gate_stays_light_to_start(fx):
    """An ordinary prompt costs an interpreter start and a JSON read: the registry and project-item load only
    when a Leader check is judged."""
    program = ("import sys, json, io; sys.path.insert(0, %r); sys.stdin = io.StringIO(%r)\n"
               "from agent_session import self_check_gate as g\n"
               "g.main('r', '/none', '/none')\n"
               "print(json.dumps(sorted(m for m in sys.modules if m.startswith(('agent_session.config', 'project_item')))))"
               % (str(Path(gate.__file__).resolve().parents[1]), json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "hi"})))
    done = subprocess.run([sys.executable, "-I", "-S", "-c", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == []
