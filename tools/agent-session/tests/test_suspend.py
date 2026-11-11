"""Shutdown and resume of Claude sessions, with real tmux and Git and a Claude-shaped fake CLI."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from agent_session_fixture import command_timeout, git, session_env  # noqa: F401  (pytest fixture)
from agent_session import lifecycle, process, suspend
from agent_session.config import resolve_project
from agent_session.state import StateStore, control_lock
from agent_session.errors import SessionError
from agent_session.suspend import Fleet, SuspendMixin, SuspendStore
from agent_session.tmux import Tmux
import tmux_test_server  # noqa: E402


def claude_project(env, monkeypatch, others=()):
    """Make the fixture project (and the named other projects) Claude projects with the fake Claude CLI."""
    import agent_session.lifecycle as lifecycle
    import agent_session.providers as providers
    from agent_session_fake_provider import FakeClaudeProvider

    config = json.loads(env.config.read_text())
    for entry in config.values():
        if entry["project"] == "fixture" or entry["project"] in others:
            entry["provider"] = "claude"
    env.config.write_text(json.dumps(config))
    env.project = resolve_project(env.base, env.config)       # the fixture's own project and store read the new provider
    env.store = StateStore(env.project)
    monkeypatch.setattr(lifecycle, "get_provider", lambda name: FakeClaudeProvider())
    monkeypatch.setattr(providers, "get_provider", lambda name: FakeClaudeProvider())
    return env.base / "agent" / "fixture-cli.jsonl"


def fleet(env, timeout=None):
    return Fleet(lifecycle.Manager, config_path=env.config, socket_name=env.socket_name, timeout=timeout or command_timeout())


def signals(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def messages(env):
    path = env.base / "agent" / "fixture-messages.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def records(env):
    return SuspendStore(env.project).read()


def kill_server(env):
    """Lose the server mid-test; the next command starts a new one, which the watchdog must cover again."""
    tmux_test_server.release(env.socket_name)
    tmux_test_server.watch(env.socket_name)


def busy(env, slot, base=None):
    """Mark the slot's fake CLI as mid-turn until the marker is removed."""
    marker = (base or env.base) / "agent" / f"fixture-busy-{slot}"
    marker.write_text("busy\n")
    return marker


def started(env):
    """A Claude project with a Leader and one Worker; return (leader result, worker result, cr id)."""
    leader = env.manager().start("leader")
    cr = env.cr()
    worker = env.manager().start(cr)
    return leader, worker, cr


@pytest.fixture
def trace(monkeypatch):
    """The begin and end of every target shutdown, in order, across threads."""
    events = []
    original = SuspendMixin.suspend_target

    def wrapped(self, slot, deadline, force, progress):
        events.append(("begin", self.project.project_id, slot, time.monotonic()))
        try:
            return original(self, slot, deadline, force, progress)
        finally:
            events.append(("end", self.project.project_id, slot, time.monotonic()))

    monkeypatch.setattr(SuspendMixin, "suspend_target", wrapped)
    return events


def when(events, kind, project, slot):
    return next(at for what, name, target, at in events if (what, name, target) == (kind, project, slot))


# shutdown

def test_shutdown_records_only_what_ended_and_leaves_state_cr_and_seat_alone(session_env, monkeypatch, trace):
    env = session_env
    cli = claude_project(env, monkeypatch)
    leader, worker, cr = started(env)
    before = env.store.read()
    seat_files = sorted(path.name for path in env.seats[0].iterdir())
    result = fleet(env).shutdown(everything=True)
    row = result["projects"][0]
    assert {item["slot"] for item in row["recorded"]} == {"seat-0", "leader"}
    assert not row["busy"] and not row["unknown"]
    saved = records(env)
    assert saved["seat-0"]["job_id"] == cr and saved["seat-0"]["run_id"] == worker["run_id"]
    assert saved["seat-0"]["session_id"] == worker["session"]["session_id"] and saved["seat-0"]["forced"] is False
    assert saved["leader"]["job_id"] is None and saved["leader"]["session_id"] == leader["session"]["session_id"]
    assert env.store.read() == before
    assert env.cr_state(cr)[0] == "in-progress"
    assert sorted(path.name for path in env.seats[0].iterdir()) == seat_files
    assert git(env.seats[0], "status", "--porcelain") == ""
    assert env.tmux.pane_info(worker["pane_id"])["pane_dead"] and env.tmux.pane_info(leader["pane_id"])["pane_dead"]
    assert signals(cli) == [{"signal": "SIGTERM"}] * 2      # a signal each, and nothing typed in a pane
    assert "/exit" not in env.tmux.capture_pane(worker["pane_id"])
    # The Worker rested before the Leader was asked.
    assert when(trace, "end", "fixture", "seat-0") <= when(trace, "begin", "fixture", "leader")


def test_shutdown_again_is_safe_and_records_the_same_runs(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    started(env)
    fleet(env).shutdown(project="fixture")
    first = records(env)
    fleet(env).shutdown(project="fixture")
    assert {slot: entry["run_id"] for slot, entry in records(env).items()} == {
        slot: entry["run_id"] for slot, entry in first.items()}


def test_shutdown_also_records_a_worker_whose_return_was_held(session_env, monkeypatch):
    env = session_env
    cli = claude_project(env, monkeypatch)
    leader, worker, cr = started(env)
    held = env.manager().control("stop", job=cr)
    assert held["stopped"] is True and held["released"] is False
    assert signals(cli) == [{"signal": "SIGTERM"}]
    result = fleet(env).shutdown(project="fixture")
    assert records(env)["seat-0"]["run_id"] == worker["run_id"]
    assert env.store.read()["0"]["job_id"] == cr
    assert signals(cli) == [{"signal": "SIGTERM"}] * 2      # only the Leader was signalled by the shutdown
    assert {item["slot"] for item in result["projects"][0]["recorded"]} == {"seat-0", "leader"}


def test_all_targets_wait_under_one_deadline(session_env, monkeypatch, trace):
    env = session_env
    other = env.add_project("other")
    claude_project(env, monkeypatch, others=("other",))
    env.manager().start("leader")
    env.manager_at(other).start("leader")
    cr = env.cr()
    env.manager().start(cr)
    marks = [busy(env, "seat-0"), busy(env, "leader", base=other)]
    with pytest.raises(SessionError) as error:
        fleet(env, timeout=3).shutdown(everything=True)
    assert (error.value.code, error.value.exit_code) == ("shutdown_incomplete", 4)
    # The two busy targets of different projects were waited on at the same time, not one after the other.
    first = (when(trace, "begin", "fixture", "seat-0"), when(trace, "end", "fixture", "seat-0"))
    second = (when(trace, "begin", "other", "leader"), when(trace, "end", "other", "leader"))
    assert second[0] < first[1] and first[0] < second[1]
    for mark in marks:
        mark.unlink()


def test_without_force_a_working_target_keeps_running_and_nothing_is_recorded_for_it(session_env, monkeypatch):
    env = session_env
    cli = claude_project(env, monkeypatch)
    leader, worker, cr = started(env)
    busy(env, "seat-0")
    with pytest.raises(SessionError) as error:
        fleet(env, timeout=2).shutdown(project="fixture")
    assert (error.value.code, error.value.exit_code) == ("shutdown_incomplete", 4)
    row = error.value.details["projects"][0]
    assert [item["slot"] for item in row["busy"]] == ["seat-0"]
    assert row["busy"][0]["error"]["details"]["stopping_restored"] is True
    assert "--force" in error.value.details["rerun"]
    assert [item["slot"] for item in row["recorded"]] == ["leader"]
    assert set(records(env)) == {"leader"}
    assert env.tmux.pane_info(worker["pane_id"])["pane_dead"] is False       # still running
    assert env.tmux.get_current("fixture", "seat-0")["stopping"] is False    # input is allowed again
    assert signals(cli) == [{"signal": "SIGTERM"}]                           # the Leader's only
    assert env.manager().send(job=cr, message="still here")["disposition"] == "accepted"


def test_force_signals_only_the_cli_whose_birth_matches_and_records_forced(session_env, monkeypatch):
    env = session_env
    cli = claude_project(env, monkeypatch)
    leader, worker, cr = started(env)
    busy(env, "seat-0")
    result = fleet(env, timeout=2).shutdown(project="fixture", force=True)
    saved = records(env)
    assert saved["seat-0"]["forced"] is True and saved["leader"]["forced"] is False
    assert env.tmux.pane_info(worker["pane_id"])["pane_dead"] is True
    assert signals(cli) == [{"signal": "SIGTERM"}] * 2
    assert not result["projects"][0]["busy"]


def test_an_idle_cli_with_a_background_task_has_not_rested_until_it_is_forced(session_env, monkeypatch):
    env = session_env
    cli = claude_project(env, monkeypatch)
    leader, worker, cr = started(env)
    marker = env.base / "agent" / "fixture-background-seat-0"
    marker.write_text("task\n")
    with pytest.raises(SessionError) as error:
        fleet(env, timeout=2).shutdown(project="fixture")
    assert [item["slot"] for item in error.value.details["projects"][0]["busy"]] == ["seat-0"]
    assert signals(cli) == [{"signal": "SIGTERM"}]                           # the Leader's only; the Worker was not asked
    assert env.tmux.pane_info(worker["pane_id"])["pane_dead"] is False
    # The provider still reports the task after the CLI dies; a forced end is confirmed from the processes.
    result = fleet(env, timeout=2).shutdown(project="fixture", force=True)
    assert records(env)["seat-0"]["forced"] is True and not result["projects"][0]["busy"]
    assert env.tmux.pane_info(worker["pane_id"])["pane_dead"] is True
    marker.unlink()


def test_an_idle_cli_with_only_a_session_cron_rests_and_ends_without_force(session_env, monkeypatch):
    env = session_env
    cli = claude_project(env, monkeypatch)
    leader, worker, cr = started(env)
    marker = env.base / "agent" / "fixture-cron-seat-0"
    marker.write_text("")
    result = fleet(env, timeout=5).shutdown(project="fixture")
    saved = records(env)
    assert saved["seat-0"]["forced"] is False and not result["projects"][0]["busy"]
    assert env.tmux.pane_info(worker["pane_id"])["pane_dead"] is True
    assert signals(cli) == [{"signal": "SIGTERM"}] * 2
    marker.unlink()


def test_force_does_not_signal_a_process_with_a_different_birth(session_env, monkeypatch):
    env = session_env
    cli = claude_project(env, monkeypatch)
    leader, worker, cr = started(env)
    busy(env, "seat-0")
    env.tmux.write_meta(worker["window_id"], {"cli_birth": "linux:another-boot:1"})
    with pytest.raises(SessionError) as error:
        fleet(env, timeout=2).shutdown(project="fixture", force=True)
    row = error.value.details["projects"][0]
    assert [(item["slot"], item["error"]["code"]) for item in row["unknown"]] == [("seat-0", "target_changed")]
    assert "seat-0" not in records(env)
    assert signals(cli) == [{"signal": "SIGTERM"}]                           # the Leader's only
    assert env.tmux.pane_info(worker["pane_id"])["pane_dead"] is False


def test_a_codex_project_is_skipped_and_untouched(session_env):
    env = session_env
    env.manager().start("leader")
    result = fleet(env).shutdown(everything=True)
    row = result["projects"][0]
    assert row["recorded"] == [] and row["skipped"][0]["reason"] == "provider_not_supported"
    assert env.tmux.pane_info(env.tmux.get_current("fixture", "leader")["pane_id"])["pane_dead"] is False
    assert fleet(env).resume(everything=True)["projects"][0]["skipped"][0]["reason"] == "provider_not_supported"


def test_project_option_selects_one_registered_project(session_env, monkeypatch):
    env = session_env
    other = env.add_project("other")
    claude_project(env, monkeypatch, others=("other",))
    env.manager().start("leader")
    env.manager_at(other).start("leader")
    result = fleet(env).shutdown(project="other")
    assert [row["project"] for row in result["projects"]] == ["other"]
    assert [item["slot"] for item in result["projects"][0]["recorded"]] == ["leader"]
    assert set(SuspendStore(env.manager_at(other).project).read()) == {"leader"}
    assert SuspendStore(env.project).read() == {}
    assert env.tmux.pane_info(env.tmux.get_current("fixture", "leader")["pane_id"])["pane_dead"] is False
    with pytest.raises(SessionError) as error:
        fleet(env).shutdown(project="nowhere")
    assert (error.value.code, error.value.exit_code) == ("project_not_found", 2)


@pytest.mark.parametrize("who", ["leader", "seat-0", "stranger"])
def test_only_the_operator_may_shut_down_or_resume(session_env, monkeypatch, who):
    env = session_env
    cli = claude_project(env, monkeypatch)
    leader, worker, cr = started(env)
    identity = {"leader": leader, "seat-0": worker}.get(who)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", identity["session"]["session_id"] if identity else str(uuid.uuid4()))
    code = "caller_unbound" if who == "stranger" else "role_denied"
    for call in (lambda: fleet(env).shutdown(everything=True), lambda: fleet(env).resume(everything=True),
                 lambda: fleet(env).resume(everything=True, lost=True)):
        with pytest.raises(SessionError) as error:
            call()
        assert error.value.code == code
    assert signals(cli) == [] and records(env) == {}


# alarms

@pytest.mark.parametrize("event", ["warn", "deadline"])
@pytest.mark.parametrize("status", ["busy", "unknown"])
def test_alarms_keep_unrecorded_targets_after_their_threads_finish(monkeypatch, event, status):
    notices, bells = [], []
    monkeypatch.setattr(Tmux, "notify", lambda self, text, duration: notices.append(text) or 2)
    monkeypatch.setattr(Tmux, "ring_bell", lambda self, pane: bells.append(pane))
    targets = [
        {"project": "fixture", "slot": "seat-0", "done": True,
         "outcome": {"status": status}, "pane_id": "%1"},
        {"project": "fixture", "slot": "leader", "done": False,
         "outcome": None, "pane_id": "%0"},
        {"project": "fixture", "slot": "seat-1", "done": True,
         "outcome": {"status": "recorded"}, "pane_id": "%2"},
    ]
    alarm = suspend.Alarm(Tmux(), "agent-session shutdown --all", False, "12:00:00")

    alarm.fire(event, targets, len(targets), "12:00:00")

    assert len(notices) == 1
    assert "남은 대상 2: fixture:seat-0, fixture:leader." in notices[0]
    assert bells == ["%1", "%0"]
    assert alarm.log[0]["clients"] == 2 and alarm.log[0]["bells"] == 2
    assert alarm.log[0]["errors"] == []


class ControlClient:
    """An attached tmux client in control mode: its `%message` lines are what a person would see."""

    def __init__(self, env):
        self.path = env.root / "client.out"
        self.process = subprocess.Popen(["tmux", "-L", env.socket_name, "-C", "attach", "-t", "harness"],
                                        stdin=subprocess.PIPE, stdout=self.path.open("w"), stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if Tmux(socket_name=env.socket_name).notify("hello", 1):
                return
            time.sleep(0.1)
        raise AssertionError("The control client did not attach.")

    def lines(self):
        return [line for line in self.path.read_text().splitlines() if line.startswith("%message agent shutdown")]

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=10)


def test_alarms_message_every_client_and_flag_the_working_windows(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    leader, worker, cr = started(env)
    monkeypatch.setattr(suspend, "WARN_LEAD", 1)
    busy(env, "seat-0")
    client = ControlClient(env)
    try:
        with pytest.raises(SessionError) as error:
            fleet(env, timeout=4).shutdown(project="fixture")
        deadline = time.monotonic() + 5
        while len(client.lines()) < 3 and time.monotonic() < deadline:
            time.sleep(0.1)
        lines = client.lines()
    finally:
        client.close()
    log = error.value.details["alarms"]
    assert [entry["event"] for entry in log] == ["start", "warn", "deadline"]
    assert all(entry["clients"] == 1 and not entry["errors"] for entry in log)
    assert len(lines) == 3
    assert "대상 2" in lines[0] and "대기 마감 시각" in lines[0]
    assert "fixture:seat-0" in lines[1] and "--force" in lines[1]
    assert "fixture:seat-0" in lines[2]
    # Only the targets that had not rested were flagged; the bell is output to the pane, not input.
    flagged = env.tmux.command("list-windows", "-t", "fixture", "-F", "#{window_id} #{window_bell_flag}")
    assert f"{worker['window_id']} 1" in flagged.splitlines()
    assert log[1]["bells"] >= 1 and log[2]["bells"] >= 1


def test_the_force_alarm_names_the_kill_time(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    started(env)
    busy(env, "seat-0")
    monkeypatch.setattr(suspend, "WARN_LEAD", 1)
    log = fleet(env, timeout=4).shutdown(project="fixture", force=True)["alarms"]
    assert "강제 종료 시각" in log[0]["text"]
    assert "강제 종료합니다" in log[1]["text"] + log[2]["text"]


def test_without_any_client_the_alarm_says_so_and_the_verdict_is_unchanged(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    started(env)
    result = fleet(env).shutdown(project="fixture")
    assert [(entry["event"], entry["clients"]) for entry in result["alarms"]] == [("start", 0)]
    assert len(result["projects"][0]["recorded"]) == 2


def test_failing_alarms_do_not_change_the_verdict(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    started(env)
    busy(env, "seat-0")
    monkeypatch.setattr(suspend, "WARN_LEAD", 1)

    def fail(self, *arguments):
        raise SessionError("alarm_failed", "The fixture injected an alarm failure.", 5)

    monkeypatch.setattr(Tmux, "notify", fail)
    monkeypatch.setattr(Tmux, "ring_bell", fail)
    result = fleet(env, timeout=3).shutdown(project="fixture", force=True)
    assert {item["slot"] for item in result["projects"][0]["recorded"]} == {"seat-0", "leader"}
    assert len(result["alarms"]) >= 2 and all(entry["errors"] for entry in result["alarms"])


# resume

@pytest.mark.parametrize("restart", [True, False], ids=["server-restarted", "server-kept"])
def test_resume_reopens_the_same_conversations_leader_first(session_env, monkeypatch, restart):
    env = session_env
    claude_project(env, monkeypatch)
    leader, worker, cr = started(env)
    env.manager().review(job=cr)
    before = env.store.read()
    assert before["leader"]["reviewing"] == cr
    user = env.tmux.command("split-window", "-d", "-P", "-F", "#{pane_id}", "-t", leader["window_id"], "sleep", "86400")
    fleet(env).shutdown(project="fixture")
    first_runs = {slot: entry["run_id"] for slot, entry in records(env).items()}
    if restart:
        kill_server(env)
    order = []
    original = SuspendMixin.relaunch
    notified = []
    monkeypatch.setattr(SuspendMixin, "relaunch", lambda self, slot, record: order.append(slot) or original(self, slot, record))
    notify = SuspendMixin.notify_resumed
    monkeypatch.setattr(SuspendMixin, "notify_resumed", lambda self, slot, text: notified.append(slot) or notify(self, slot, text))
    result = fleet(env).resume(everything=True)
    assert order == ["leader", "seat-0"] and notified == ["seat-0", "leader"]
    assert {item["slot"] for item in result["projects"][0]["resumed"]} == {"leader", "seat-0"}
    # The same conversations: the state is exactly what it was, including connected_at and the review mark.
    assert env.store.read() == before
    for slot, session_id in (("leader", leader["session"]["session_id"]), ("seat-0", worker["session"]["session_id"])):
        current = env.tmux.get_current("fixture", slot)
        assert current["session_id"] == session_id and current["registered"] and current["ready"]
        assert current["resume"] is True and current["run_id"] != first_runs[slot]
        launch = (env.base / "agent/runs" / current["run_id"] / "launch.sh").read_text()
        assert f"--session {session_id}" in launch
    assert records(env) == {}
    assert env.cr_state(cr)[0] == "in-progress"
    sent = messages(env)
    assert [item["target"] for item in sent] == ["seat-0", "leader"]       # one message each, Worker first
    assert all("재개" in item["text"] and "background" in item["text"] for item in sent)
    assert f"seat-0({cr})" in sent[1]["text"] and "강제 종료" not in sent[0]["text"]
    assert "로컬 operator 입력" in sent[0]["text"]
    # The periodic check is the project's crontab job: no resume message asks a conversation to register one.
    assert all("CronCreate" not in item["text"] and "self-check" not in item["text"] for item in sent)
    names = env.tmux.command("list-windows", "-t", "fixture", "-F", "#{window_name}").splitlines()
    assert not [name for name in names if "-exited-" in name]
    windows_now = {slot: env.tmux.get_current("fixture", slot)["window_id"] for slot in ("leader", "seat-0")}
    if not restart:                                 # after a server restart there is no ended window to hand over
        # The ended windows are handed to the resumed runs, with the pane a person added beside the Leader.
        assert windows_now == {"leader": leader["window_id"], "seat-0": worker["window_id"]}
        assert env.tmux.command("list-panes", "-t", leader["window_id"], "-F", "#{pane_id}").splitlines() == [
            leader["pane_id"], user]
        assert sorted(names) == ["fixture-leader", f"fixture-seat0-{cr}"]


def test_a_forced_shutdown_is_told_to_the_resumed_conversation(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    started(env)
    busy(env, "seat-0")
    fleet(env, timeout=2).shutdown(project="fixture", force=True)
    (env.base / "agent/fixture-busy-seat-0").unlink()
    kill_server(env)
    fleet(env).resume(project="fixture")
    sent = {item["target"]: item["text"] for item in messages(env)}
    assert "강제 종료" in sent["seat-0"] and "강제 종료" not in sent["leader"]


def test_resume_keeps_the_record_of_a_target_the_state_no_longer_names(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    leader, worker, cr = started(env)
    fleet(env).shutdown(project="fixture")
    env.store.update(lambda value: value["0"]["session"].update(session_id=str(uuid.uuid4())))
    with pytest.raises(SessionError) as error:
        fleet(env).resume(project="fixture")
    row = error.value.details["projects"][0]
    assert [item["slot"] for item in row["resumed"]] == ["leader"]
    assert [(item["slot"], item["error"]["code"]) for item in row["failed"]] == [("seat-0", "target_changed")]
    assert set(records(env)) == {"seat-0"}
    assert "agent-session start --job " + cr in row["failed"][0]["fallback"]


def test_resume_needs_the_worker_cr_to_stay_in_progress(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    leader, worker, cr = started(env)
    fleet(env).shutdown(project="fixture")
    env.finish(cr, state="todo", outcome=None)
    with pytest.raises(SessionError) as error:
        fleet(env).resume(project="fixture")
    assert [(item["slot"], item["error"]["code"]) for item in error.value.details["projects"][0]["failed"]] == [
        ("seat-0", "target_changed")]
    assert set(records(env)) == {"seat-0"}


def test_resume_with_nothing_recorded_does_nothing(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    started(env)
    result = fleet(env).resume(everything=True)
    assert result["projects"][0]["resumed"] == [] and messages(env) == []


# resume --lost: a server that went down without shutdown

def lost_server(env, monkeypatch, tmp_path, transcript_age=3600, boot_age=60):
    """A Leader and a Worker whose server went down without shutdown, as `resume --lost` finds them.

    The tmux server is gone (no pointers). The fixture's boot time is `boot_age` seconds ago, so the
    conversation records, written `transcript_age` seconds ago, predate it. The run scripts of the fake
    CLI do not name the conversation as Claude's `--session-id`/`--resume` argv does, so that is added."""
    claude_project(env, monkeypatch)
    leader, worker, cr = started(env)
    config = tmp_path / "claude-config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    now = time.time()
    for run, cwd in ((leader, env.base), (worker, env.seats[0])):
        session_id = run["session"]["session_id"]
        with (env.base / "agent/runs" / run["run_id"] / "launch.sh").open("a") as script:
            script.write(f"# claude --session-id {session_id}\n")
        folder = config / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd.resolve()))
        folder.mkdir(parents=True, exist_ok=True)
        record = folder / f"{session_id}.jsonl"
        record.write_text("{}\n")
        os.utime(record, (now - transcript_age, now - transcript_age))
    monkeypatch.setattr(process, "boot_time", lambda: now - boot_age)
    monkeypatch.setattr(process, "session_holders", lambda session_id: [])
    kill_server(env)
    return leader, worker, cr, config


def rejected(error):
    return {item["slot"]: {reason["code"] for reason in item["error"]["details"]["reasons"]}
            for item in error.value.details["projects"][0]["rejected"]}


def test_resume_lost_reopens_the_slots_that_have_no_record_in_the_same_conversations(session_env, monkeypatch, tmp_path):
    env = session_env
    leader, worker, cr, _ = lost_server(env, monkeypatch, tmp_path)
    before = env.store.read()
    assert records(env) == {}
    result = fleet(env).resume(project="fixture", lost=True)
    row = result["projects"][0]
    assert {item["slot"] for item in row["resumed"]} == {"leader", "seat-0"} and row["rejected"] == []
    assert env.store.read() == before                        # the same conversations, same assignment
    for slot, run in (("leader", leader), ("seat-0", worker)):
        current = env.tmux.get_current("fixture", slot)
        assert current["session_id"] == run["session"]["session_id"] and current["resume"] is True
        assert current["registered"] and current["run_id"] != run["run_id"]
    assert records(env) == {} and env.cr_state(cr)[0] == "in-progress"
    # The judgement's evidence stays in the result.
    item = {entry["slot"]: entry for entry in row["resumed"]}["seat-0"]
    assert item["forced"] is True and item["job_id"] == cr
    evidence = item["lost"]
    assert evidence["processes"] == [] and evidence["execution_pointer"] is None
    assert evidence["transcript"].endswith(worker["session"]["session_id"] + ".jsonl")
    assert evidence["transcript_updated"] < evidence["boot_time"] <= evidence["checked_at"]
    sent = {entry["target"]: entry["text"] for entry in messages(env)}
    assert set(sent) == {"leader", "seat-0"} and all("shutdown 없이" in text for text in sent.values())
    assert "강제 종료" not in sent["leader"] and "중간에 끊겨" in sent["seat-0"]


@pytest.mark.parametrize("case, expected", [
    ("after_boot", {"updated_after_boot"}),
    ("process_alive", {"cli_alive"}),
    ("process_unknown", {"process_unknown"}),
    ("boot_unknown", {"process_unknown"}),
    ("no_transcript", {"transcript_missing"}),
    ("no_run", {"run_unknown"}),
])
def test_resume_lost_rejects_a_slot_it_cannot_confirm_and_keeps_the_assignment(session_env, monkeypatch, tmp_path,
                                                                             case, expected):
    env = session_env
    leader, worker, cr, config = lost_server(env, monkeypatch, tmp_path)
    before = env.store.read()
    if case == "after_boot":
        monkeypatch.setattr(process, "boot_time", lambda: time.time() - 7200)      # the records were written after it
    elif case == "process_alive":
        monkeypatch.setattr(process, "session_holders", lambda session_id: [4242])
    elif case == "process_unknown":
        def unknown(session_id):
            raise SessionError("process_unknown", "Cannot inspect the process directory.", 4)
        monkeypatch.setattr(process, "session_holders", unknown)
    elif case == "boot_unknown":
        def unknown():
            raise SessionError("process_unknown", "Cannot read the system boot time.", 4)
        monkeypatch.setattr(process, "boot_time", unknown)
    elif case == "no_transcript":
        shutil.rmtree(config)
    else:
        for script in (env.base / "agent/runs").glob("*/launch.sh"):
            script.write_text(script.read_text().replace(leader["session"]["session_id"], "x")
                              .replace(worker["session"]["session_id"], "y"))
    with pytest.raises(SessionError) as error:
        fleet(env).resume(project="fixture", lost=True)
    assert error.value.code == "resume_incomplete" and error.value.exit_code == 4
    assert rejected(error) == {"leader": expected, "seat-0": expected}
    assert error.value.details["projects"][0]["resumed"] == []
    assert env.store.read() == before and records(env) == {} and messages(env) == []
    assert env.tmux.get_current("fixture", "seat-0") is None and env.cr_state(cr)[0] == "in-progress"


def test_resume_lost_rejects_a_slot_whose_execution_pointer_remains(session_env, monkeypatch, tmp_path):
    env = session_env
    claude_project(env, monkeypatch)
    leader, worker, cr = started(env)             # the server and the CLIs are running
    monkeypatch.setattr(process, "boot_time", lambda: time.time() - 60)
    monkeypatch.setattr(process, "session_holders", lambda session_id: [])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    before = env.store.read()
    with pytest.raises(SessionError) as error:
        fleet(env).resume(project="fixture", lost=True)
    assert {slot: "execution_present" in codes for slot, codes in rejected(error).items()} == {
        "leader": True, "seat-0": True}
    assert env.store.read() == before and records(env) == {}
    assert env.tmux.get_current("fixture", "seat-0")["run_id"] == worker["run_id"]      # nothing was started
    assert not env.tmux.pane_info(worker["pane_id"])["pane_dead"]


def test_resume_lost_judges_each_slot_on_its_own_evidence(session_env, monkeypatch, tmp_path):
    env = session_env
    leader, worker, cr, config = lost_server(env, monkeypatch, tmp_path)
    leader_record = next((config / "projects").glob("*/" + leader["session"]["session_id"] + ".jsonl"))
    os.utime(leader_record, (time.time(), time.time()))             # the Leader's record is newer than the boot
    with pytest.raises(SessionError) as error:
        fleet(env).resume(project="fixture", lost=True)
    row = error.value.details["projects"][0]
    assert [item["slot"] for item in row["resumed"]] == ["seat-0"]
    assert rejected(error) == {"leader": {"updated_after_boot"}}
    assert env.tmux.get_current("fixture", "leader") is None
    assert "재개하지 못한 대상" not in messages(env)[0]["text"]       # only the Worker was resumed


def test_resume_lost_does_not_take_a_slot_whose_state_names_another_conversation(session_env, monkeypatch, tmp_path):
    env = session_env
    leader, worker, cr, _ = lost_server(env, monkeypatch, tmp_path)
    env.store.update(lambda value: value["0"]["session"].update(session_id=str(uuid.uuid4())))
    with pytest.raises(SessionError) as error:
        fleet(env).resume(project="fixture", lost=True)
    assert rejected(error) == {"seat-0": {"transcript_missing", "run_unknown"}}     # no record or run names it


def test_resume_lost_skips_a_reserved_seat_without_a_conversation(session_env, monkeypatch, tmp_path):
    env = session_env
    claude_project(env, monkeypatch)
    env.store.update(lambda value: value["1"].update(job_id="TOOL-009"))
    result = fleet(env).resume(project="fixture", lost=True)
    row = result["projects"][0]
    assert [item["slot"] for item in row["skipped"]] == ["seat-1"] and row["skipped"][0]["reason"] == "no_conversation"
    assert row["resumed"] == [] and row["rejected"] == []


def test_resume_without_lost_leaves_a_slot_that_has_no_record(session_env, monkeypatch, tmp_path):
    env = session_env
    lost_server(env, monkeypatch, tmp_path)
    result = fleet(env).resume(project="fixture")
    row = result["projects"][0]
    assert row["resumed"] == [] and "rejected" not in row and records(env) == {} and messages(env) == []
    with pytest.raises(SessionError) as error:
        env.manager().start(env.store.read()["0"]["job_id"])
    assert error.value.code == "execution_unknown"


def test_a_failed_lost_resume_keeps_its_evidence_and_start_takes_over(session_env, monkeypatch, tmp_path):
    from agent_session_fake_provider import FakeClaudeProvider

    env = session_env
    leader, worker, cr, _ = lost_server(env, monkeypatch, tmp_path)
    launch_spec = FakeClaudeProvider.launch_spec

    def exits(self, context, prepared):
        spec = launch_spec(self, context, prepared)
        return {**spec, "argv": ["/bin/false"]} if context.get("resume") else spec

    monkeypatch.setattr(FakeClaudeProvider, "launch_spec", exits)
    with pytest.raises(SessionError) as error:
        fleet(env, timeout=20).resume(project="fixture", lost=True)
    assert {item["slot"] for item in error.value.details["projects"][0]["failed"]} == {"leader", "seat-0"}
    saved = records(env)["seat-0"]
    assert saved["forced"] is True and saved["session_id"] == worker["session"]["session_id"]
    assert saved["lost"]["processes"] == [] and "boot_time" in saved["lost"]
    monkeypatch.setattr(FakeClaudeProvider, "launch_spec", launch_spec)
    result = env.manager().start(cr)
    assert result["session"]["session_id"] != worker["session"]["session_id"]
    assert set(records(env)) == {"leader"}


# a new conversation when the old one cannot be resumed

def test_a_recorded_worker_starts_a_new_conversation_without_tmux_evidence(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    leader, worker, cr = started(env)
    git_hash = env.store.read()["0"]["git_hash"]
    fleet(env).shutdown(project="fixture")
    kill_server(env)
    result = env.manager().start(cr)
    assert result["seat"] == 0 and result["ready"] is True
    assert result["session"]["session_id"] != worker["session"]["session_id"]
    assert env.store.read()["0"]["session"]["session_id"] == result["session"]["session_id"]
    assert env.store.read()["0"]["git_hash"] == git_hash                    # the Git baseline is kept
    assert "seat-0" not in records(env) and "leader" in records(env)
    assert env.cr_state(cr)[0] == "in-progress"
    prompt = (env.base / "agent/runs" / result["run_id"] / "prompt.md").read_text()
    assert "새 대화로 시작" in prompt and "배정 CR: " + cr in prompt


def test_without_a_record_the_worker_still_needs_manual_recovery(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    leader, worker, cr = started(env)
    kill_server(env)
    with pytest.raises(SessionError) as error:
        env.manager().start(cr)
    assert error.value.code == "execution_unknown"


def test_a_record_that_the_state_contradicts_does_not_open_the_slot(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    leader, worker, cr = started(env)
    fleet(env).shutdown(project="fixture")
    kill_server(env)
    env.store.update(lambda value: value["0"]["session"].update(session_id=str(uuid.uuid4())))
    with pytest.raises(SessionError) as error:
        env.manager().start(cr)
    assert error.value.code == "execution_unknown"


def test_a_failed_resume_leaves_the_record_and_start_can_take_over(session_env, monkeypatch):
    from agent_session_fake_provider import FakeClaudeProvider

    env = session_env
    claude_project(env, monkeypatch)
    leader, worker, cr = started(env)
    fleet(env).shutdown(project="fixture")
    kill_server(env)
    launch_spec = FakeClaudeProvider.launch_spec

    def exits(self, context, prepared):
        spec = launch_spec(self, context, prepared)
        return {**spec, "argv": ["/bin/false"]} if context.get("resume") else spec

    monkeypatch.setattr(FakeClaudeProvider, "launch_spec", exits)
    locked_while_dropped = []
    clear_current = Tmux.clear_current

    def spy(self, project_id, target, run_id):
        try:
            with control_lock(env.project, target, 0, blocking=False):
                locked_while_dropped.append(False)
        except SessionError as error:
            locked_while_dropped.append(error.code == "control_busy")
        return clear_current(self, project_id, target, run_id)

    monkeypatch.setattr(Tmux, "clear_current", spy)
    with pytest.raises(SessionError) as error:
        fleet(env, timeout=20).resume(project="fixture")
    assert locked_while_dropped and all(locked_while_dropped), "a failed launch was dropped without the lock"
    failed = {item["slot"]: item["error"]["code"] for item in error.value.details["projects"][0]["failed"]}
    assert failed == {"leader": "provider_exited", "seat-0": "provider_exited"}
    assert set(records(env)) == {"leader", "seat-0"}
    assert env.tmux.get_current("fixture", "seat-0") is None               # the dead launch left no evidence
    monkeypatch.setattr(FakeClaudeProvider, "launch_spec", launch_spec)
    result = env.manager().start(cr)
    assert result["session"]["session_id"] != worker["session"]["session_id"]
    assert set(records(env)) == {"leader"}


def test_starting_a_new_leader_drops_the_leaders_record(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    leader, worker, cr = started(env)
    fleet(env).shutdown(project="fixture")
    kill_server(env)
    result = env.manager().start("leader")
    assert result["session"]["session_id"] != leader["session"]["session_id"]
    assert set(records(env)) == {"seat-0"}


# record file

def test_the_record_rejects_an_invalid_entry_and_keeps_the_file(session_env):
    env = session_env
    path = env.base / "agent" / "suspend.json"
    path.write_text(json.dumps({"seat-0": {"job_id": "TOOL-001"}}))
    with pytest.raises(SessionError) as error:
        SuspendStore(env.project).read()
    assert error.value.code == "suspend_invalid"
    assert json.loads(path.read_text()) == {"seat-0": {"job_id": "TOOL-001"}}


def test_concurrent_records_do_not_lose_each_other(session_env):
    env = session_env
    store = SuspendStore(env.project)
    threads = [threading.Thread(target=store.record, args=(slot, None if slot == "leader" else "TOOL-00" + slot[-1],
                                                           "run-" + slot, "session-" + slot, False))
               for slot in ("leader", "seat-0", "seat-1", "seat-2", "seat-3")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert set(store.read()) == {"leader", "seat-0", "seat-1", "seat-2", "seat-3"}


def test_no_resume_message_asks_for_a_session_cron():
    for lost in (False, True):
        worker = suspend.resume_text("seat-0", False, lost=lost)
        leader = suspend.resume_text("leader", True, resumed=["seat-0(TOOL-001)"], failed=[], lost=lost)
        for text in (worker, leader):
            assert "CronCreate" not in text and "CronList" not in text and "self-check" not in text
