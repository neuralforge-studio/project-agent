"""Watch wakes an instance whose screen has not changed for the threshold, once per stall, and tells the Leader.

The screens are Claude's: the layout was captured from a live Claude Code 2.1 pane (conversation, spinner line,
prompt box between two border lines, status line and permission-mode line below it), with the conversation text
replaced."""

import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from agent_session_fixture import command_timeout, session_env  # noqa: F401,E402
from agent_session import cli, process
from agent_session.errors import SessionError
from agent_session.lifecycle import Manager
from agent_session.providers.claude import screen_body
from agent_session.tmux import Tmux
from agent_session.watch import Watch

THRESHOLD = 1800
SLOT = "seat-0"
BORDER = "─" * 100


def screen(activity, usage="5h 14% ↻03:20", agents="↓ 10 agents", typed=""):
    """A Claude pane: the conversation, the spinner or result line, the prompt box and the two footer lines."""
    return "\n".join([
        "● 구현을 마쳤습니다.", "  Read 3 files, ran 5 shell commands", activity, BORDER + " seat0", "❯ " + typed, BORDER,
        f"  user@example.com · Sonnet 5.5 high · ctx 8% · {usage} · week 12% ↻Mon 16:00",
        f"  ⏵⏵ bypass permissions on (shift+tab to cycle) · {agents}"])


RUNNING = screen("✻ Improvising… (39s · ↓ 1.9k tokens · thought for 2s)")
RUNNING_LATER = screen("✻ Improvising… (2m 24s · ↓ 8.2k tokens · thought for 5s)")
RESTING = screen("✻ Brewed for 2m 3s")
FOOTER_ONLY = screen("✻ Brewed for 2m 3s", usage="5h 15% ↻04:20", agents="← 11 agents")


def test_only_the_footer_below_the_prompt_box_is_left_out_of_a_claude_screen():
    assert screen_body(RESTING) == screen_body(FOOTER_ONLY)
    assert screen_body(RUNNING) != screen_body(RUNNING_LATER)       # the spinner time runs while a turn runs
    assert screen_body(RUNNING) != screen_body(RESTING)
    assert screen_body(RESTING) != screen_body(screen("✻ Brewed for 2m 3s", typed="다음 입력"))
    assert "5h" not in screen_body(RESTING) and "bypass" not in screen_body(RESTING)
    assert screen_body("한 줄\n\n  \n") == "한 줄"                    # no border line: the whole screen, trailing blanks aside


def iso(seconds):
    return dt.datetime.fromtimestamp(seconds, dt.timezone.utc).isoformat()


def started(env):
    """Leader and one Worker on a CR in progress."""
    leader = env.manager().start("leader")
    cr = env.cr()
    worker = env.manager().start(cr)
    return leader, cr, worker, time.time()


def messages(env, target=None):
    path = env.base / "agent" / "fixture-messages.jsonl"
    found = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [item for item in found if "[agent-session watch]" in item["text"]
            and (target is None or item["target"] == target)]


def look(env, now, minutes=THRESHOLD // 60, slot=SLOT):
    return env.manager().watch_target(slot, minutes * 60, now=now)


@pytest.fixture
def pane(monkeypatch):
    """The text every pane shows; set `pane.text` to change the screen."""
    class Pane:
        text = RESTING
    holder = Pane()
    monkeypatch.setattr(Tmux, "capture_pane", lambda self, pane_id: holder.text)
    monkeypatch.setattr(process, "tree", lambda pid: [])
    return holder


def stalled(env, pane, slot, minutes=THRESHOLD // 60 + 1):
    """Record that the slot's pane has shown its current text for `minutes` already."""
    meta = env.tmux.get_current("fixture", slot)
    digest = env.manager()._fingerprint(meta)
    env.tmux.write_meta(meta["window_id"], {"run_id": meta["run_id"], "watch": {
        "screen": {"hash": digest, "since": time.time() - minutes * 60}}})


def test_a_worker_that_waits_for_the_leader_is_woken_and_told_to_remind_the_leader(session_env, pane, monkeypatch):
    env = session_env
    leader, cr, worker, now = started(env)
    with monkeypatch.context() as actor:                  # it reported and the Leader has not answered
        actor.setenv("CODEX_THREAD_ID", worker["session"]["session_id"])
        env.manager().send(job="leader", message="제출합니다.")
    assert look(env, now)["status"] == "active"           # the first look only records the screen
    assert look(env, now + THRESHOLD - 60)["status"] == "active"
    assert messages(env) == []
    first = look(env, now + THRESHOLD)
    assert first["status"] == "resting"
    worker_text, leader_text = messages(env, SLOT), messages(env, "leader")
    assert len(worker_text) == 1 and len(leader_text) == 1
    text = worker_text[0]["text"]
    assert cr in text and "Leader에게 CR ID와 제출 commit을 짧게 다시 알리십시오" in text
    assert "자식 process가 없습니다" in text and "마지막 보고(Leader에게 send) 기록 없음" not in text
    assert "seat 0" in leader_text[0]["text"] and "Disposition에 없는 CR" in leader_text[0]["text"]
    # The same stall later: the Worker is not woken again, the Leader is reminded after each threshold.
    again = look(env, now + 2 * THRESHOLD + 60)
    assert again["status"] == "resting" and [item for item in again["actions"] if item["send"] == cr] == []
    assert len(messages(env, SLOT)) == 1 and len(messages(env, "leader")) == 2


def test_a_screen_that_changed_after_the_nudge_is_a_new_state_and_wakes_again_when_it_stalls(session_env, pane):
    env = session_env
    _, _, _, now = started(env)
    look(env, now)
    assert look(env, now + THRESHOLD)["status"] == "resting"
    pane.text = screen("✻ Brewed for 3m 1s")                # the Worker answered the nudge and rested again
    assert look(env, now + THRESHOLD + 60)["status"] == "active"
    assert look(env, now + 2 * THRESHOLD)["status"] == "active"
    assert look(env, now + 2 * THRESHOLD + 120)["status"] == "resting"
    assert len(messages(env, SLOT)) == 2


def test_a_footer_that_changes_alone_does_not_hide_a_stall(session_env, pane):
    env = session_env
    _, _, _, now = started(env)
    look(env, now)
    pane.text = FOOTER_ONLY
    assert look(env, now + THRESHOLD)["status"] == "resting"
    assert len(messages(env, SLOT)) == 1


def test_a_screen_that_keeps_changing_is_working_and_is_left_alone(session_env, pane):
    env = session_env
    _, _, _, now = started(env)
    for step, text in enumerate((RUNNING, RUNNING_LATER, screen("✻ Improvising… (5m 1s · ↓ 20k tokens)"),
                                 screen("✻ Improvising… (9m 1s · ↓ 31k tokens)"))):
        pane.text = text
        assert look(env, now + step * 20 * 60)["status"] == "active"
    assert messages(env) == []


def test_a_cr_that_left_in_progress_is_not_watched(session_env, pane):
    env = session_env
    _, cr, _, now = started(env)
    env.finish(cr)
    result = look(env, now)
    assert result["status"] == "skipped" and result["reason"] == "cr_not_in_progress"
    assert messages(env) == []


def test_a_stalled_worker_with_a_background_shell_names_it_in_the_message(session_env, pane, monkeypatch):
    from agent_session_fake_provider import FakeProvider
    env = session_env
    _, _, _, now = started(env)
    shell = {"idle": False, "active_turn": True, "runtime_status": "shell",
             "background": [{"id": "bz1", "type": "shell", "command": "until ! pgrep -f x; do sleep 3; done"}]}
    monkeypatch.setattr(FakeProvider, "observe", lambda self, *a, **k: shell)
    look(env, now)
    assert look(env, now + THRESHOLD)["status"] == "resting"
    assert "until ! pgrep -f x; do sleep 3; done" in messages(env, SLOT)[0]["text"]


def test_a_child_process_is_named_in_the_message_but_does_not_stop_the_nudge(session_env, pane, monkeypatch):
    env = session_env
    _, _, _, now = started(env)
    monkeypatch.setattr(process, "started", lambda pid: 0.0)
    monkeypatch.setattr(process, "tree", lambda pid: [
        {"pid": 4242, "birth": "b4242", "started": 1000.0, "cpu": 90.0, "args": "make -j8 test"}])
    look(env, now)
    assert look(env, now + THRESHOLD)["status"] == "resting"       # a silent screen is a stall whatever runs
    assert "pid 4242" in messages(env, SLOT)[0]["text"] and "make -j8 test" in messages(env, SLOT)[0]["text"]


def test_a_stalled_leader_with_a_cr_in_progress_is_woken_once_per_stall(session_env, pane):
    env = session_env
    _, cr, _, now = started(env)
    leader = lambda at: look(env, at, slot="leader")
    assert leader(now)["status"] == "active"
    assert leader(now + THRESHOLD)["status"] == "resting"
    [sent] = messages(env, "leader")
    assert cr in sent["text"] and "seat 0" in sent["text"] and "review 대기 CR" in sent["text"]
    assert leader(now + 2 * THRESHOLD)["status"] == "resting"
    assert len(messages(env, "leader")) == 1
    pane.text = screen("✻ Brewed for 4m 4s")                # the Leader worked, then rested again
    leader(now + 2 * THRESHOLD + 60)
    assert leader(now + 3 * THRESHOLD + 60)["status"] == "resting"
    assert len(messages(env, "leader")) == 2


def test_a_leader_with_no_cr_in_progress_has_nothing_to_have_forgotten(session_env, pane):
    env = session_env
    env.manager().start("leader")
    result = look(env, time.time(), slot="leader")
    assert result["status"] == "skipped" and result["reason"] == "no_cr_in_progress"
    assert messages(env) == []


def spawn(*command):
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_process_tree_reports_command_cpu_and_start_of_the_descendants():
    if not sys.platform.startswith("linux"):
        pytest.skip("needs /proc")
    loop = spawn(sys.executable, "-c", "import time\nwhile True: time.sleep(1)")
    try:
        time.sleep(0.5)
        found = [item for item in process.tree(os.getpid()) if item["pid"] == loop.pid]
        assert len(found) == 1
        item = found[0]
        assert "time.sleep" in item["args"] and item["cpu"] >= 0
        assert abs(item["started"] - time.time()) < 60 and item["birth"] == process.birth(loop.pid)
    finally:
        loop.kill()
        loop.wait()


def run_command(env, *arguments):
    return cli.main(["--config", str(env.config), "--socket-name", env.socket_name, "watch", *arguments])


def test_watch_command_is_the_operators_and_reports_each_target(session_env, pane, monkeypatch, capsys):
    env = session_env
    leader, cr, worker, _ = started(env)
    stalled(env, pane, SLOT)
    capsys.readouterr()
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", worker["session"]["session_id"])
        assert run_command(env, "--all") != 0
        assert json.loads(capsys.readouterr().out)["error"]["code"] == "role_denied"
    assert messages(env) == []
    assert run_command(env, "--project", "fixture") == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["threshold_minutes"] == 30
    leader_target, target = data["projects"][0]["targets"]          # the operator judges the Leader too
    assert (leader_target["slot"], leader_target["status"]) == ("leader", "active")
    assert (target["slot"], target["job_id"], target["status"]) == (SLOT, cr, "resting")
    # A second run at once sends nothing more.
    assert run_command(env, "--project", "fixture") == 0
    assert len(messages(env, SLOT)) == 1 and len(messages(env, "leader")) == 1
    assert run_command(env, "--project", "unknown") == 2


def test_a_second_watch_of_the_project_does_not_run_at_once(session_env, monkeypatch):
    from agent_session.state import locked
    env = session_env
    started(env)
    watch = Watch(Manager, config_path=env.config, socket_name=env.socket_name, timeout=command_timeout())
    with locked(env.project.runtime_path / "watch.lock"):
        result = watch.run(project="fixture")
    assert result["projects"][0]["error"]["code"] == "control_busy"
    assert messages(env) == []


def test_a_failed_target_does_not_hide_the_others(session_env, monkeypatch):
    env = session_env
    started(env)
    monkeypatch.setattr(Manager, "watch_target", lambda self, *a, **k: (_ for _ in ()).throw(SessionError("x", "boom")))
    watch = Watch(Manager, config_path=env.config, socket_name=env.socket_name, timeout=command_timeout())
    targets = watch.run(project="fixture")["projects"][0]["targets"]
    assert [item["slot"] for item in targets] == ["leader", SLOT]     # the first error does not stop the second look
    assert all(item["status"] == "error" and item["error"]["code"] == "x" for item in targets)


def test_the_leader_watches_its_own_project_and_gets_the_evidence_instead_of_a_message(session_env, pane, monkeypatch, capsys):
    env = session_env
    leader, cr, worker, _ = started(env)
    stalled(env, pane, SLOT)
    stalled(env, pane, "leader")
    capsys.readouterr()
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", leader["session"]["session_id"])
        assert run_command(env, "--project", "fixture") == 0
        [target] = json.loads(capsys.readouterr().out)["data"]["projects"][0]["targets"]    # not the Leader itself
        assert target["slot"] == SLOT and target["status"] == "resting" and cr in target["evidence"] and "자식 process가 없습니다" in target["evidence"]
        # The Worker is woken as in the operator's run; the Leader is not messaged by its own command.
        assert len(messages(env, SLOT)) == 1 and messages(env, "leader") == []
        # The same state again: the Worker is not woken twice and the Leader is still not messaged.
        assert run_command(env, "--project", "fixture") == 0
        assert len(messages(env, SLOT)) == 1 and messages(env, "leader") == []
    # The Leader's own looks leave no notification record (`notified_at`) for the operator's run to skip.
    assert "notified_at" not in (env.tmux.get_current("fixture", SLOT)["watch"].get("resting") or {})


def test_only_this_projects_leader_may_watch_it_and_never_several_projects(session_env, monkeypatch, capsys):
    env = session_env
    leader, _, worker, _ = started(env)
    other = env.add_project()
    other_leader = env.manager_at(other).start("leader")
    capsys.readouterr()

    def refused(identity, *arguments):
        with monkeypatch.context() as actor:
            actor.setenv("CODEX_THREAD_ID", identity)
            assert run_command(env, *arguments) != 0
            return json.loads(capsys.readouterr().out)["error"]["code"]
    assert refused(leader["session"]["session_id"], "--all") == "caller_unbound"       # two projects: not the Leader's
    assert refused(leader["session"]["session_id"], "--project", "other") == "caller_unbound"
    assert refused(other_leader["session"]["session_id"], "--project", "fixture") == "caller_unbound"
    assert refused(worker["session"]["session_id"], "--project", "fixture") == "role_denied"
    assert refused("someone-else", "--project", "fixture") == "caller_unbound"
    assert messages(env) == []


def test_self_check_prompts_carry_the_review_wait_items():
    text = (Path(__file__).resolve().parents[3] / "skills/project-team/references/self-check.md").read_text(encoding="utf-8")
    worker = text[text.index("## Worker"):text.index("## Leader")]
    leader = text[text.index("## Leader"):]
    assert "회신을 30분 넘게 기다렸으면" in worker and "CR ID와 제출 hash" in worker and "점검마다 한 번" in worker
    assert "아무것도 하지 않고 메시지도 보내지 않습니다" not in worker
    assert "review 대기 CR" in leader and "제출 행 hash가 Disposition에 없는 것" in leader
