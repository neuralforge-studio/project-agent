"""Exercise lifecycle commands with real temporary Git and tmux resources."""

import json
from pathlib import Path
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from agent_session_fixture import git, session_env
from agent_session.errors import SessionError
from agent_session.state import locked


def test_worker_automatic_seat_baseline_registration_and_release(session_env):
    env = session_env
    leader = env.manager().start("leader")
    job = env.job()
    worker = env.manager().start(str(job))
    assert leader["cwd"] == str(env.base)
    assert worker["seat"] == 0 and worker["cwd"] == str(env.seats[0])
    assert uuid.UUID(worker["session"]["session_id"])
    state = env.store.read()
    assert state["leader"] == leader["session"]
    assert state["0"]["job_id"] == "J-20261103-01"
    assert state["0"]["git_hash"] == env.initial_hash
    assert state["0"]["session"] == worker["session"]
    assert state["1"] == {"job_id": None, "git_hash": None, "session": None}
    baseline = env.read_job(job)["baseline"]
    assert baseline["base_hash"] == env.initial_hash
    assert baseline["base_commit_time"] == git(env.seats[0], "show", "-s", "--format=%cI", "HEAD")
    assert git(env.seats[0], "branch", "--show-current") == "job/J-20261103-01"
    (env.seats[0] / "server.py").write_text("VALUE = 2\n")
    git(env.seats[0], "add", "server.py")
    git(env.seats[0], "commit", "-m", "Refactor temporary server")
    submitted = env.publish_and_integrate(env.seats[0], "J-20261103-01")
    stopped = env.manager().control("stop", job="J-20261103-01")
    assert stopped["stopped"] is True and stopped["released"] is True
    assert env.store.read()["0"] == {"job_id": None, "git_hash": None, "session": None}
    assert env.domain()["releases"]["J-20261103-01"]["head"] == submitted
    assert env.tmux.pane_info(worker["pane_id"])["pane_dead"]
    assert env.manager().control("stop", job="leader")["released"] is True
    assert env.store.read()["leader"] is None


def test_automatic_allocation_preserves_dirty_seat_and_uses_next_seat(session_env):
    env = session_env
    original = env.seats[0] / "server.py"
    original.write_text("VALUE = 'existing user work'\n")
    job = env.job()
    worker = env.manager().start(str(job))
    assert worker["seat"] == 1
    assert original.read_text() == "VALUE = 'existing user work'\n"
    assert env.store.read()["0"] == {"job_id": None, "git_hash": None, "session": None}


def test_automatic_allocation_skips_a_controlled_unassigned_seat(session_env):
    env = session_env
    job = env.job()
    with locked(env.base / "agent/control/seat-0.lock"):
        worker = env.manager().start(str(job))
    assert worker["seat"] == 1
    assert env.store.read()["0"]["job_id"] is None


def test_feedback_restart_and_incomplete_stop_preserve_same_job_work(session_env, monkeypatch):
    env = session_env
    leader = env.manager().start("leader")
    job = env.job()
    original = env.manager().start(str(job))
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", original["session"]["session_id"])
        assert env.manager().send(job="leader", message="Review this result.")["disposition"] == "accepted"
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", leader["session"]["session_id"])
        assert env.manager().send(job="J-20261103-01", message="Keep the same JOB and correct the result.")["disposition"] == "accepted"
    messages = [json.loads(line) for line in (env.base / "agent/fixture-messages.jsonl").read_text().splitlines()]
    assert [item["session"]["session_id"] for item in messages] == [leader["session"]["session_id"], original["session"]["session_id"]]
    assert "동료 메시지" in messages[0]["text"] and "사용자 승인" in messages[0]["text"]
    assert "회신은 agent-session send --job J-20261103-01로" in messages[0]["text"]
    assert "회신은 agent-session send --job leader로" in messages[1]["text"]
    tracked = env.seats[0] / "server.py"
    untracked = env.seats[0] / "worker-notes.txt"
    tracked.write_text("VALUE = 3\n")
    untracked.write_text("preserve this unfinished work\n")
    restarted = env.manager().control("restart", job="J-20261103-01")
    assert restarted["restarted"] is True
    assert restarted["session"]["session_id"] != original["session"]["session_id"]
    assert restarted["run_id"] != original["run_id"]
    assert restarted["seat"] == original["seat"]
    assert env.store.read()["0"]["git_hash"] == env.initial_hash
    assert git(env.seats[0], "branch", "--show-current") == "job/J-20261103-01"
    assert tracked.read_text() == "VALUE = 3\n" and untracked.read_text() == "preserve this unfinished work\n"
    assert env.tmux.pane_info(original["pane_id"])["pane_dead"]
    stopped = env.manager().control("stop", job="J-20261103-01")
    assert stopped["stopped"] is True and stopped["released"] is False
    before = env.store.read()["0"].copy()
    continued = env.manager().start(str(job))
    assert continued["session"]["session_id"] != before["session"]["session_id"]
    assert env.store.read()["0"]["job_id"] == before["job_id"]
    assert env.store.read()["0"]["git_hash"] == before["git_hash"]
    assert tracked.read_text() == "VALUE = 3\n" and untracked.exists()


@pytest.mark.parametrize("failure", ["assignment_once", "git_prepare_once"])
def test_pre_provider_failure_reuses_its_reservation_without_handoff(session_env, failure):
    env = session_env
    job = env.job()
    env.fail_once(failure)
    with pytest.raises(SessionError) as error:
        env.manager().start(str(job))
    assert error.value.code == "fixture_" + failure
    pending = env.tmux.get_current("fixture", "seat-0")
    assert pending["provider_launch_attempted"] is False
    assert env.store.read()["0"]["job_id"] == "J-20261103-01"
    assert not (env.base / "handoff").exists()
    result = env.manager().start(str(job))
    assert result["run_id"] == pending["run_id"]
    assert result["window_id"] == pending["window_id"]
    assert result["ready"] is True
    assert env.domain()["assignments"]["J-20261103-01"]["prepared"] is True


def test_saved_baseline_is_reused_if_its_writer_fails_before_branch_creation(session_env):
    env = session_env
    job = env.job()
    env.fail_once("baseline_after_save_once")
    with pytest.raises(SessionError) as error:
        env.manager().start(str(job))
    assert error.value.code == "fixture_baseline_after_save_once"
    assert env.read_job(job)["baseline"]["base_hash"] == env.initial_hash
    assert env.store.read()["0"]["git_hash"] is None
    newer = env.advance_remote()
    assert newer != env.initial_hash
    result = env.manager().start(str(job))
    assert result["ready"] is True
    assert env.store.read()["0"]["git_hash"] == env.initial_hash
    assert git(env.seats[0], "rev-parse", "HEAD") == env.initial_hash
    assert env.read_job(job)["baseline"]["base_hash"] == env.initial_hash


@pytest.mark.parametrize("target", ["worker", "leader"])
def test_ready_writer_retry_keeps_the_existing_native_conversation(session_env, target):
    env = session_env
    job = env.job() if target == "worker" else "leader"
    env.fail_once("ready_once")
    with pytest.raises(SessionError) as error:
        env.manager().start(str(job))
    assert error.value.code == "fixture_ready_once"
    slot = "seat-0" if target == "worker" else "leader"
    bound = env.tmux.get_current("fixture", slot)
    assert bound["registered"] is True and bound["ready"] is False
    connection = env.store.read()["0"]["session"] if target == "worker" else env.store.read()["leader"]
    assert connection["session_id"] == bound["session_id"]
    retried = env.manager().start(str(job))
    assert retried["run_id"] == bound["run_id"]
    assert retried["session"] == connection
    assert retried["ready"] is True
    assert env.domain()["ready"][bound["job_id"] or "leader"] == [connection["session_id"]]


def test_read_only_preparation_syncs_main_without_a_job_branch(session_env):
    env = session_env
    newer = env.advance_remote()
    job = env.job(mode="read-only")
    result = env.manager().start(str(job))
    assert env.store.read()["0"]["git_hash"] == newer
    assert env.read_job(job)["baseline"]["branch"] is None
    assert git(env.seats[0], "branch", "--show-current") == "main"
    assert git(env.seats[0], "branch", "--list", "job/*") == ""
    env.accept("J-20261103-01", newer)
    assert env.manager().control("stop", job=result["job_id"])["released"] is True


def test_release_writer_failure_preserves_assignment_until_retry(session_env):
    env = session_env
    job = env.job()
    result = env.manager().start(str(job))
    env.publish_and_integrate(env.seats[0], result["job_id"])
    before = env.store.read()["0"].copy()
    env.fail_once("release_once")
    with pytest.raises(SessionError) as error:
        env.manager().control("stop", job=result["job_id"])
    assert error.value.code == "fixture_release_once"
    assert env.tmux.pane_info(result["pane_id"])["pane_dead"]
    assert env.store.read()["0"] == before
    assert env.manager().control("stop", job=result["job_id"])["released"] is True
    assert env.store.read()["0"] == {"job_id": None, "git_hash": None, "session": None}


def test_leader_prelaunch_retry_preserves_request_and_required_git_sync(session_env, monkeypatch):
    import agent_session.lifecycle as lifecycle

    env = session_env
    newer = env.advance_remote()
    request = env.root / "REQUEST.md"
    task = "Refactor the server only after checking the approved server requirements."
    request.write_text(task)
    original_sync = lifecycle.git_ops.sync_main
    attempts = []

    def sync_with_transient_failure(root):
        attempts.append(str(root))
        if len(attempts) == 1:
            raise SessionError("fixture_transient_fetch", "The fixture temporarily cannot fetch main.")
        return original_sync(root)

    monkeypatch.setattr(lifecycle.git_ops, "sync_main", sync_with_transient_failure)
    first = env.manager()
    first.adapter.prepare_workspace = lambda context, phase: {"sync_main": True}
    with pytest.raises(SessionError) as error:
        first.start("leader", prompt_file=str(request))
    assert error.value.code == "fixture_transient_fetch"
    pending = env.tmux.get_current("fixture", "leader")
    assert pending["provider_launch_attempted"] is False
    assert env.store.read()["leader"] is None

    second = env.manager()
    second.adapter.prepare_workspace = lambda context, phase: {"sync_main": True}
    result = second.start("leader", prompt_file=str(request))
    prompt = (env.base / "agent/runs" / result["run_id"] / "prompt.md").read_text()
    assert result["run_id"] == pending["run_id"]
    assert {
        "ready": result["ready"],
        "head": git(env.base, "rev-parse", "HEAD"),
        "request_preserved": task in prompt,
    } == {"ready": True, "head": newer, "request_preserved": True}


def test_allocation_skips_missing_window_without_erasing_its_evidence(session_env):
    env = session_env
    env.manager().start("leader")
    missing = env.tmux.create_window("fixture", "closed-worker", env.seats[0], {
        "base": str(env.base), "run_id": "closed-worker-run", "target": "seat-0", "job_id": "J-20261103-99",
    })
    env.tmux.set_current("fixture", "seat-0", missing)
    pointer = env.tmux.command("show-options", "-qv", "-t", "fixture", "@agent_session_current_seat_0")
    env.tmux.command("kill-window", "-t", missing["window_id"])
    worker = env.manager().start(str(env.job()))
    assert worker["seat"] == 1
    assert env.store.read()["0"] == {"job_id": None, "git_hash": None, "session": None}
    assert git(env.seats[0], "branch", "--show-current") == "main"
    assert env.tmux.command("show-options", "-qv", "-t", "fixture", "@agent_session_current_seat_0") == pointer


def test_missing_other_window_does_not_hide_a_live_pane_caller(session_env, monkeypatch):
    env = session_env
    worker = env.manager().start(str(env.job()))
    missing = env.tmux.create_window("fixture", "closed-leader", env.base, {
        "base": str(env.base), "run_id": "closed-leader-run", "target": "leader", "job_id": None,
    })
    env.tmux.set_current("fixture", "leader", missing)
    env.tmux.command("kill-window", "-t", missing["window_id"])
    monkeypatch.setenv("TMUX_PANE", worker["pane_id"])
    current = env.tmux.get_current("fixture", "seat-0")
    monkeypatch.setenv("TMUX", current["socket_path"] + "," + str(current["server_pid"]) + ",0")
    with pytest.raises(SessionError) as error:
        env.manager().start(str(env.job(number=2)))
    assert error.value.code == "role_denied"
    assert env.store.read()["0"]["job_id"] == worker["job_id"]
    assert env.store.read()["1"]["job_id"] is None


def test_stop_can_end_an_unlaunched_placeholder_without_releasing_unfinished_job(session_env):
    from agent_session.api import check_binding

    env = session_env
    job = env.job()
    env.fail_once("assignment_once")
    with pytest.raises(SessionError):
        env.manager().start(str(job))
    pending = env.tmux.get_current("fixture", "seat-0")
    assert pending["provider_launch_attempted"] is False
    assert pending["registered"] is False
    before = env.store.read()["0"].copy()
    snapshot = env.project.state_path.read_bytes()
    binding = check_binding(env.base, "J-20261103-01", config_path=env.config,
                            socket=env.tmux.effective_socket())
    assert binding["session"] is None
    assert binding["ready"] is False and binding["alive"] is False
    assert binding["termination_confirmed"] is False
    assert env.project.state_path.read_bytes() == snapshot
    result = env.manager().control("stop", job="J-20261103-01")
    assert result["stopped"] is True
    assert result["released"] is False
    assert env.tmux.pane_info(pending["pane_id"])["pane_dead"] is True
    assert env.store.read()["0"] == before
    assert env.store.read()["0"]["session"] is None
    binding = check_binding(env.base, "J-20261103-01", config_path=env.config,
                            socket=env.tmux.effective_socket())
    assert binding["session"] is None
    assert binding["termination_confirmed"] is True
    assert env.project.state_path.read_bytes() == snapshot


def test_rejected_stop_request_does_not_mark_a_ready_session_stopping(session_env, monkeypatch):
    env = session_env
    worker = env.manager().start(str(env.job()))
    manager = env.manager()

    def reject_request(*args, **kwargs):
        raise SessionError("session_unbound", "The native conversation could not be verified.", 4)

    monkeypatch.setattr(manager.provider, "request_stop", reject_request)
    with pytest.raises(SessionError) as error:
        manager.control("stop", job=worker["job_id"])
    assert error.value.code == "session_unbound"
    current = env.tmux.get_current("fixture", "seat-0")
    assert current["stopping"] is False
    assert current["ready"] is True
    assert env.tmux.pane_info(worker["pane_id"])["pane_dead"] is False
    assert env.store.read()["0"]["session"] == worker["session"]


@pytest.mark.parametrize("attempted", [True, None])
def test_unbound_attempted_or_unknown_launch_cannot_be_stopped_as_a_placeholder(session_env, attempted):
    env = session_env
    env.fail_once("assignment_once")
    with pytest.raises(SessionError):
        env.manager().start(str(env.job()))
    pending = env.tmux.get_current("fixture", "seat-0")
    env.tmux.write_meta(pending["window_id"], {"provider_launch_attempted": attempted})
    before = env.store.read()["0"].copy()
    with pytest.raises(SessionError) as error:
        env.manager().control("stop", job="J-20261103-01")
    assert error.value.code == "session_unbound"
    current = env.tmux.get_current("fixture", "seat-0")
    assert current["stopping"] is False
    assert env.tmux.pane_info(pending["pane_id"])["pane_dead"] is False
    assert env.store.read()["0"] == before
