"""Watch wakes a resting Worker once and tells the Leader; a Worker that works or waits for the Leader is left alone."""

import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from agent_session_fixture import command_timeout, session_env  # noqa: F401,E402
from agent_session import cli, process
from agent_session.errors import SessionError
from agent_session.lifecycle import Manager
from agent_session.watch import Watch

THRESHOLD = 1800
SLOT = "seat-0"


def iso(seconds):
    return dt.datetime.fromtimestamp(seconds, dt.timezone.utc).isoformat()


def started(env):
    """Leader and one Worker on a CR in progress; the Worker's last turn ended an hour ago."""
    leader = env.manager().start("leader")
    cr = env.cr()
    worker = env.manager().start(cr)
    now = time.time()
    meta = env.tmux.get_current("fixture", SLOT)
    env.tmux.write_meta(meta["window_id"], {"run_id": meta["run_id"], "hook_observations": {
        "Stop": {"session_id": meta["session_id"], "hook_event_name": "Stop", "observed_at": iso(now - 3600)}}})
    return leader, cr, worker, now


def messages(env, target=None):
    path = env.base / "agent" / "fixture-messages.jsonl"
    found = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [item for item in found if "[agent-session watch]" in item["text"]
            and (target is None or item["target"] == target)]


def look(env, now, minutes=THRESHOLD // 60):
    return env.manager().watch_target(SLOT, minutes * 60, now=now)


def no_children(monkeypatch):
    monkeypatch.setattr(process, "tree", lambda pid: [])


def test_resting_worker_is_woken_once_with_evidence_and_the_leader_is_told(session_env, monkeypatch):
    env = session_env
    no_children(monkeypatch)
    _, cr, _, now = started(env)
    first = look(env, now)
    assert first["status"] == "resting"
    worker, leader = messages(env, SLOT), messages(env, "leader")
    assert len(worker) == 1 and len(leader) == 1
    assert cr in worker[0]["text"] and "마지막 turn 종료" in worker[0]["text"] and "자식 process가 없습니다" in worker[0]["text"]
    assert "마지막 보고(Leader에게 send) 기록 없음" in worker[0]["text"]
    assert "seat 0" in leader[0]["text"] and "강제로 끊지 않았습니다" in leader[0]["text"]
    # The same state a minute later: the nudge made a new input, so the clock restarts and nothing is sent.
    assert look(env, now + 60)["status"] == "idle"
    # The Worker rests again without reporting: the Worker is not told twice, the Leader is reminded.
    again = look(env, now + THRESHOLD + 60)
    assert again["status"] == "resting"
    assert len(messages(env, SLOT)) == 1 and len(messages(env, "leader")) == 2
    assert [item for item in again["actions"] if item["send"] == cr] == []
    # Both windows record the deliveries for the next look.
    assert env.tmux.get_current("fixture", SLOT)["last_received"]["from"] == "operator"


def test_a_report_after_the_nudge_starts_a_new_episode(session_env, monkeypatch):
    env = session_env
    no_children(monkeypatch)
    leader, _, worker, now = started(env)
    look(env, now)
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", worker["session"]["session_id"])
        env.manager().send(job="leader", message="제출합니다.")
    assert env.tmux.get_current("fixture", SLOT)["last_sent"]["to"] == "leader"
    # Reported and not answered: waiting for the Leader, not resting, however long.
    waiting = look(env, now + 3 * THRESHOLD)
    assert waiting["status"] == "awaiting_leader" and waiting["reason"] == "reported"
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", leader["session"]["session_id"])
        env.manager().send(job="TOOL-001", message="수정하십시오.")
    # The Leader answered, the Worker went idle again: a new episode wakes the Worker again.
    later = look(env, time.time() + THRESHOLD + 60)
    assert later["status"] == "resting"
    assert len(messages(env, SLOT)) == 2


def test_reviewing_leader_is_not_waited_for_in_a_nudge(session_env, monkeypatch):
    env = session_env
    no_children(monkeypatch)
    leader, cr, _, now = started(env)
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", leader["session"]["session_id"])
        env.manager().review(job=cr)
    result = look(env, now)
    assert result["status"] == "awaiting_leader" and result["reason"] == "reviewing"
    assert messages(env) == []


def test_a_turn_in_progress_is_left_alone_and_bounds_the_rest(session_env, monkeypatch):
    from agent_session_fake_provider import FakeProvider
    env = session_env
    no_children(monkeypatch)
    _, _, _, now = started(env)
    with monkeypatch.context() as busy:
        busy.setattr(FakeProvider, "observe", lambda self, *a, **k: {"idle": False, "active_turn": True, "runtime_status": "busy"})
        assert look(env, now)["status"] == "busy"
    # It ended without a Stop hook (an interrupt): the rest counts from the last time it was seen busy.
    assert look(env, now + 10)["status"] == "idle"
    assert messages(env) == []


def test_a_cr_that_left_in_progress_is_not_watched(session_env, monkeypatch):
    env = session_env
    no_children(monkeypatch)
    _, cr, _, now = started(env)
    env.finish(cr)
    result = look(env, now)
    assert result["status"] == "skipped" and result["reason"] == "cr_not_in_progress"
    assert messages(env) == []


def test_only_a_background_shell_is_a_rest_and_its_command_is_in_the_message(session_env, monkeypatch):
    from agent_session_fake_provider import FakeProvider
    env = session_env
    no_children(monkeypatch)
    _, _, _, now = started(env)
    shell = {"idle": False, "active_turn": True, "runtime_status": "shell",
             "background": [{"id": "bz1", "type": "shell", "command": "until ! pgrep -f x; do sleep 3; done"}]}
    monkeypatch.setattr(FakeProvider, "observe", lambda self, *a, **k: shell)
    assert look(env, now)["status"] == "resting"
    assert "until ! pgrep -f x; do sleep 3; done" in messages(env, SLOT)[0]["text"]


def child(pid, cpu, started=1000.0):
    return {"pid": pid, "birth": f"b{pid}", "started": started, "cpu": cpu, "args": "make -j8 test"}


def test_children_that_use_cpu_are_working_and_idle_ones_are_named(session_env, monkeypatch):
    env = session_env
    _, _, _, now = started(env)
    monkeypatch.setattr(process, "started", lambda pid: 0.0)
    cpu = [10.0]
    monkeypatch.setattr(process, "tree", lambda pid: [child(4242, cpu[0])])
    assert look(env, now)["status"] == "observing"          # nothing to compare with yet
    cpu[0] = 10.0 + 0.2 * 600                               # 20 % of a core over ten minutes
    assert look(env, now + 600)["reason"] == "children_use_cpu"
    cpu[0] += 0.5                                           # then almost nothing
    result = look(env, now + 1200)
    assert result["status"] == "resting"
    text = messages(env, SLOT)[0]["text"]
    assert "pid 4242" in text and "make -j8 test" in text and "직전 점검 뒤 CPU 0.5초" in text
    assert len(messages(env, SLOT)) == 1


def spawn(*command):
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.mark.skipif(not sys.platform.startswith("linux") or not shutil.which("pgrep"), reason="needs /proc and pgrep")
def test_a_pgrep_loop_that_matches_itself_is_woken_and_a_busy_child_is_not(session_env, monkeypatch):
    env = session_env
    _, _, _, now = started(env)
    real = process.tree
    real_started, cli = process.started, int(env.tmux.get_current("fixture", SLOT)["cli_pid"])
    monkeypatch.setattr(process, "tree", lambda pid: real(os.getpid()))   # the test process stands for the CLI
    monkeypatch.setattr(process, "started", lambda pid: 0.0 if pid == cli else real_started(pid))
    busy = spawn(sys.executable, "-c", "while True: pass")
    try:
        assert look(env, now)["status"] == "observing"
        time.sleep(2)
        assert look(env, time.time())["reason"] == "children_use_cpu"
        assert messages(env) == []
    finally:
        busy.kill()
        busy.wait()
    # `pgrep -f` matches the bash that runs it, so this loop never ends and uses no CPU.
    loop = spawn("/bin/bash", "-c", "while pgrep -f zz_watch_marker >/dev/null; do sleep 30; done")
    try:
        time.sleep(1)
        look(env, time.time())                               # a look that records the loop
        time.sleep(2)
        result = look(env, time.time())
        assert result["status"] == "resting"
        assert "pgrep -f zz_watch_marker" in messages(env, SLOT)[0]["text"]
    finally:
        loop.kill()
        loop.wait()


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


def test_watch_command_is_the_operators_and_reports_each_target(session_env, monkeypatch, capsys):
    env = session_env
    no_children(monkeypatch)
    leader, cr, worker, _ = started(env)
    capsys.readouterr()
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", worker["session"]["session_id"])
        assert run_command(env, "--all") != 0
        assert json.loads(capsys.readouterr().out)["error"]["code"] == "role_denied"
    assert messages(env) == []
    assert run_command(env, "--project", "fixture") == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["threshold_minutes"] == 30
    [target] = data["projects"][0]["targets"]
    assert (target["slot"], target["job_id"], target["status"]) == (SLOT, cr, "resting")
    # A second run at once sends nothing more.
    assert run_command(env, "--project", "fixture") == 0
    assert len(messages(env, SLOT)) == 1 and len(messages(env, "leader")) == 1
    assert run_command(env, "--project", "unknown") == 2


def test_a_second_watch_of_the_project_does_not_run_at_once(session_env, monkeypatch):
    from agent_session.state import locked
    env = session_env
    no_children(monkeypatch)
    started(env)
    watch = Watch(Manager, config_path=env.config, socket_name=env.socket_name, timeout=command_timeout())
    with locked(env.project.runtime_path / "watch.lock"):
        result = watch.run(project="fixture")
    assert result["projects"][0]["error"]["code"] == "control_busy"
    assert messages(env) == []


def test_a_failed_target_does_not_hide_the_others(session_env, monkeypatch):
    env = session_env
    no_children(monkeypatch)
    started(env)
    monkeypatch.setattr(Manager, "watch_target", lambda self, *a, **k: (_ for _ in ()).throw(SessionError("x", "boom")))
    watch = Watch(Manager, config_path=env.config, socket_name=env.socket_name, timeout=command_timeout())
    [target] = watch.run(project="fixture")["projects"][0]["targets"]
    assert target["status"] == "error" and target["error"]["code"] == "x"


def test_the_leader_watches_its_own_project_and_gets_the_evidence_instead_of_a_message(session_env, monkeypatch, capsys):
    env = session_env
    no_children(monkeypatch)
    leader, cr, worker, _ = started(env)
    capsys.readouterr()
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", leader["session"]["session_id"])
        assert run_command(env, "--project", "fixture") == 0
        [target] = json.loads(capsys.readouterr().out)["data"]["projects"][0]["targets"]
        assert target["status"] == "resting" and cr in target["evidence"] and "자식 process가 없습니다" in target["evidence"]
        # The Worker is woken as in the operator's run; the Leader is not messaged by its own command.
        assert len(messages(env, SLOT)) == 1 and messages(env, "leader") == []
        # The same state again: the Worker is not woken twice and the Leader is still not messaged.
        assert run_command(env, "--project", "fixture") == 0
        assert len(messages(env, SLOT)) == 1 and messages(env, "leader") == []
    # The Leader's own looks leave no notification record (`notified_at`) for the operator's run to skip.
    assert "notified_at" not in (env.tmux.get_current("fixture", SLOT)["watch"].get("resting") or {})


def test_only_this_projects_leader_may_watch_it_and_never_several_projects(session_env, monkeypatch, capsys):
    env = session_env
    no_children(monkeypatch)
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
