"""Exercise lifecycle commands with real temporary Git and tmux resources and CR files as JOBs."""

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from agent_session_fixture import command_timeout, git, session_env, stop_test_server
from agent_session.errors import SessionError
from agent_session.state import locked


EMPTY = {"job_id": None, "git_hash": None, "session": None}
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_seat_outside_the_registry_is_invalid(session_env):
    env = session_env
    env.manager().start("leader")
    with pytest.raises(SessionError) as error:
        env.manager().control("stop", seat=len(env.seats))
    assert error.value.code == "seat_invalid"
    assert env.manager().control("stop", job="leader")["released"] is True


def ident(session):
    """The connection fields that a command result reports."""
    return {key: session[key] for key in ("session_id", "endpoint")}


def windows(env):
    if not env.tmux.has_session("fixture"):
        return []
    return env.tmux.command("list-windows", "-t", "fixture", "-F", "#{window_id}").splitlines()


def without_reuse(monkeypatch):
    """Make every run open its own window, as a window that cannot be reused would."""
    import agent_session.lifecycle as lifecycle
    monkeypatch.setattr(lifecycle.Manager, "_reusable", lambda self, target, ending=None: None)


def fail_once(monkeypatch, module, name, code="fixture_failure"):
    """Make module.name raise once, then behave as before."""
    original = getattr(module, name)
    calls = []

    def wrapper(*args, **kwargs):
        if not calls:
            calls.append(True)
            raise SessionError(code, "The fixture injected a failure.")
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, wrapper)


def test_worker_assignment_moves_the_cr_and_release_follows_integration(session_env):
    env = session_env
    leader = env.manager().start("leader")
    cr = env.cr()
    worker = env.manager().start(cr)
    assert leader["cwd"] == str(env.base)
    assert worker["seat"] == 0 and worker["cwd"] == str(env.seats[0])
    assert uuid.UUID(worker["session"]["session_id"])
    state = env.store.read()
    assert ident(state["leader"]) == leader["session"]
    assert state["0"]["job_id"] == cr and state["0"]["git_hash"] == env.initial_hash
    assert ident(state["0"]["session"]) == worker["session"]
    assert state["1"] == EMPTY
    assert env.cr_state(cr)[0] == "in-progress"
    commit_time = git(env.seats[0], "show", "-s", "--format=%cI", "HEAD")
    assert env.cr_header(cr, "Base") == f"{env.initial_hash} {commit_time}"
    assert git(env.seats[0], "branch", "--show-current") == "cr/TOOL-001"
    prompt = (env.base / "agent/runs" / worker["run_id"] / "prompt.md").read_text()
    assert "배정 CR: TOOL-001" in prompt and "## Result" in prompt
    (env.seats[0] / "server.py").write_text("VALUE = 2\n")
    git(env.seats[0], "add", "server.py")
    git(env.seats[0], "commit", "-m", "Refactor temporary server")
    env.publish_and_integrate(env.seats[0])
    refused = env.manager().control("stop", job=cr)
    assert refused["stopped"] is True and refused["released"] is False
    assert any("in-progress" in reason for reason in refused["reasons"])
    env.finish(cr)
    stopped = env.manager().control("stop", job=cr)
    assert stopped["released"] is True
    assert env.store.read()["0"] == EMPTY
    assert stopped["cleanup"]["closed"] == [worker["window_id"]]
    assert worker["window_id"] not in windows(env) and env.tmux.get_current("fixture", "seat-0") is None
    assert env.manager().control("stop", job="leader")["released"] is True
    assert env.store.read()["leader"] is None


def test_only_todo_crs_take_a_new_seat(session_env):
    env = session_env
    cr = env.cr()
    env.finish(cr, state="done", outcome="waived", note="not needed")
    with pytest.raises(SessionError) as error:
        env.manager().start(cr)
    assert error.value.code == "cr_not_assignable"
    with pytest.raises(SessionError) as error:
        env.manager().start("not-a-cr")
    assert error.value.code == "job_invalid"


def test_automatic_allocation_preserves_dirty_seat_and_uses_next_seat(session_env):
    env = session_env
    original = env.seats[0] / "server.py"
    original.write_text("VALUE = 'existing user work'\n")
    worker = env.manager().start(env.cr())
    assert worker["seat"] == 1
    assert original.read_text() == "VALUE = 'existing user work'\n"
    assert env.store.read()["0"] == EMPTY


def test_seat_with_unpublished_commit_is_skipped(session_env):
    env = session_env
    (env.seats[0] / "local.txt").write_text("local only\n")
    git(env.seats[0], "add", "local.txt")
    git(env.seats[0], "commit", "-m", "Unpublished local work")
    worker = env.manager().start(env.cr())
    assert worker["seat"] == 1


def test_missing_seat_is_cloned_from_the_base_origin(session_env):
    env = session_env
    import shutil
    shutil.rmtree(env.seats[0])
    worker = env.manager().start(env.cr())
    assert worker["seat"] == 0
    assert git(env.seats[0], "remote", "get-url", "origin") == git(env.base, "remote", "get-url", "origin")
    assert git(env.seats[0], "branch", "--show-current") == "cr/TOOL-001"
    assert not (env.seats[0] / ".git" / "objects" / "info" / "alternates").exists()


def test_only_a_seat_that_start_cloned_gets_workspace_trust(session_env, monkeypatch):
    from agent_session_fake_provider import FakeProvider
    import shutil

    env = session_env
    trusted = []
    monkeypatch.setattr(FakeProvider, "trust_new_seat", lambda self, root: trusted.append(Path(root)) or True)
    shutil.rmtree(env.seats[0])
    assert env.manager().start(env.cr())["seat"] == 0
    assert env.manager().start(env.cr(2))["seat"] == 1
    assert trusted == [env.seats[0]]


@pytest.mark.parametrize("target", ["leader", "worker"])
def test_start_held_at_a_startup_dialog_needs_the_user_and_resumes(session_env, monkeypatch, target):
    import agent_session.lifecycle as lifecycle
    from agent_session_fake_provider import FakeProvider

    env = session_env
    job, slot = ("leader", "leader") if target == "leader" else (env.cr(), "seat-0")
    monkeypatch.setattr(lifecycle, "get_provider", lambda name: FakeProvider(dialog=True))
    for _ in range(2):                     # a second start waits at the same dialog instead of refusing
        with pytest.raises(SessionError) as error:
            env.manager().start(job)
        assert (error.value.code, error.value.exit_code) == ("needs_user_action", 3)
        assert error.value.details["dialog"] == "workspace_trust"
    waiting = env.tmux.get_current("fixture", slot)
    assert error.value.details["run_id"] == waiting["run_id"]
    if target == "leader":
        assert env.store.read()["leader"] is None
    else:
        assert env.cr_state(job)[0] == "in-progress"
        assert env.store.read()["0"]["job_id"] == job and env.store.read()["0"]["session"] is None
    env.tmux.command("send-keys", "-t", waiting["pane_id"], "-l", "approve")
    env.tmux.command("send-keys", "-t", waiting["pane_id"], "Enter")
    wait_until(lambda: env.tmux.get_current("fixture", slot).get("registered"))
    result = env.manager().start(job)
    assert result["run_id"] == waiting["run_id"] and result["ready"] is True


def test_automatic_allocation_skips_a_controlled_unassigned_seat(session_env):
    env = session_env
    with locked(env.base / "agent/control/seat-0.lock"):
        worker = env.manager().start(env.cr())
    assert worker["seat"] == 1
    assert env.store.read()["0"]["job_id"] is None


def test_failed_reservation_returns_the_cr_to_todo(session_env, monkeypatch):
    env = session_env
    cr = env.cr()
    fail_once(monkeypatch, env.store.__class__, "update")
    with pytest.raises(SessionError):
        env.manager().start(cr)
    assert env.cr_state(cr)[0] == "todo"
    assert env.store.read(missing_ok=True)["0"] == EMPTY


def test_feedback_restart_needs_handoff_and_keeps_work(session_env, monkeypatch):
    env = session_env
    leader = env.manager().start("leader")
    cr = env.cr()
    original = env.manager().start(cr)
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", original["session"]["session_id"])
        assert env.manager().send(job="leader", message="Review this result.")["disposition"] == "accepted"
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", leader["session"]["session_id"])
        assert env.manager().send(job=cr, message="Keep the same CR and correct the result.")["disposition"] == "accepted"
    messages = [json.loads(line) for line in (env.base / "agent/fixture-messages.jsonl").read_text().splitlines()]
    assert [item["session"]["session_id"] for item in messages] == [leader["session"]["session_id"], original["session"]["session_id"]]
    assert "회신은 agent-session send --job TOOL-001로" in messages[0]["text"]
    tracked = env.seats[0] / "server.py"
    untracked = env.seats[0] / "worker-notes.txt"
    tracked.write_text("VALUE = 3\n")
    untracked.write_text("preserve this unfinished work\n")
    with pytest.raises(SessionError) as error:
        env.manager().control("restart", job=cr)
    assert error.value.code == "handoff_required"
    assert env.tmux.pane_info(original["pane_id"])["pane_dead"] is False
    env.handoff("seat-0", "Continue the server change; VALUE = 3 is not committed.")
    restarted = env.manager().control("restart", job=cr)
    assert restarted["restarted"] is True
    assert restarted["session"]["session_id"] != original["session"]["session_id"]
    assert restarted["seat"] == original["seat"]
    prompt = (env.base / "agent/runs" / restarted["run_id"] / "prompt.md").read_text()
    assert "VALUE = 3 is not committed" in prompt
    assert env.store.read()["0"]["git_hash"] == env.initial_hash
    assert git(env.seats[0], "branch", "--show-current") == "cr/TOOL-001"
    assert tracked.read_text() == "VALUE = 3\n" and untracked.read_text() == "preserve this unfinished work\n"
    stopped = env.manager().control("stop", job=cr)
    assert stopped["stopped"] is True and stopped["released"] is False
    before = env.store.read()["0"].copy()
    continued = env.manager().start(cr)
    assert continued["session"]["session_id"] != before["session"]["session_id"]
    assert env.store.read()["0"]["git_hash"] == before["git_hash"]
    assert tracked.read_text() == "VALUE = 3\n" and untracked.exists()


def test_pre_provider_failure_reuses_its_reservation_without_syncing_again(session_env, monkeypatch):
    import agent_session.lifecycle as lifecycle

    env = session_env
    cr = env.cr()
    fail_once(monkeypatch, lifecycle.Manager, "_launch")
    with pytest.raises(SessionError) as error:
        env.manager().start(cr)
    assert error.value.code == "fixture_failure"
    pending = env.tmux.get_current("fixture", "seat-0")
    assert pending["provider_launch_attempted"] is False
    assert env.store.read()["0"]["job_id"] == cr
    assert env.cr_state(cr)[0] == "in-progress"
    assert env.cr_header(cr, "Base").startswith(env.initial_hash)
    newer = env.advance_remote()
    result = env.manager().start(cr)
    assert result["run_id"] == pending["run_id"] and result["window_id"] == pending["window_id"]
    assert result["ready"] is True
    assert git(env.seats[0], "rev-parse", "HEAD") == env.initial_hash != newer
    assert git(env.seats[0], "branch", "--show-current") == "cr/TOOL-001"


def test_parked_reservation_that_never_launched_keeps_its_run_and_git_preparation(session_env, monkeypatch):
    import agent_session.lifecycle as lifecycle

    env = session_env
    cr = env.cr()
    fail_once(monkeypatch, lifecycle.Manager, "_launch")
    with pytest.raises(SessionError):
        env.manager().start(cr)
    pending = env.tmux.get_current("fixture", "seat-0")
    env.finish(cr, state="todo", outcome=None, note="park before the Worker started")
    newer = env.advance_remote()
    result = env.manager().start(cr)
    assert result["run_id"] == pending["run_id"] and result["ready"] is True
    assert env.cr_state(cr)[0] == "in-progress"
    assert git(env.seats[0], "rev-parse", "HEAD") == env.initial_hash != newer
    assert git(env.seats[0], "branch", "--show-current") == "cr/TOOL-001"


def test_saved_base_is_reused_after_a_failure_before_branch_creation(session_env, monkeypatch):
    import agent_session.git_ops as git_ops

    env = session_env
    cr = env.cr()
    original = git_ops.git

    def stop_before_branch(root, *args, **kwargs):
        if args and args[0] == "check-ref-format":
            raise SessionError("fixture_failure", "The fixture stops before the branch.")
        return original(root, *args, **kwargs)

    monkeypatch.setattr(git_ops, "git", stop_before_branch)
    with pytest.raises(SessionError):
        env.manager().start(cr)
    monkeypatch.setattr(git_ops, "git", original)
    assert env.cr_header(cr, "Base").startswith(env.initial_hash)
    newer = env.advance_remote()
    result = env.manager().start(cr)
    assert result["ready"] is True
    assert git(env.seats[0], "rev-parse", "HEAD") == env.initial_hash != newer
    assert git(env.seats[0], "branch", "--show-current") == "cr/TOOL-001"


def test_parked_cr_continues_its_published_branch_on_another_seat(session_env):
    env = session_env
    cr = env.cr()
    first = env.manager().start(cr)
    (env.seats[0] / "server.py").write_text("VALUE = 'parked'\n")
    git(env.seats[0], "add", "server.py")
    git(env.seats[0], "commit", "-m", "Partial work")
    parked = env.publish(env.seats[0])
    env.finish(cr, state="todo", outcome=None, note="park until the API decision")
    assert env.manager().control("stop", job=cr)["released"] is True
    base = env.cr_header(cr, "Base")
    (env.seats[0] / "busy.txt").write_text("seat 0 is busy\n")
    env.advance_remote()
    second = env.manager().start(cr)
    assert second["seat"] == 1 and first["seat"] == 0
    assert git(env.seats[1], "branch", "--show-current") == "cr/TOOL-001"
    assert git(env.seats[1], "rev-parse", "HEAD") == parked
    assert env.cr_header(cr, "Base") == base
    assert env.store.read()["1"]["git_hash"] == env.initial_hash


def test_parked_cr_that_kept_its_seat_resumes_there_after_its_run_stops(session_env):
    env = session_env
    cr = env.cr()
    first = env.manager().start(cr)
    kept = env.seats[0] / "worker-notes.txt"
    kept.write_text("unfinished work\n")
    env.finish(cr, state="todo", outcome=None, note="park on the user's stop")
    with pytest.raises(SessionError) as error:
        env.manager().start(cr)
    assert error.value.code == "assignment_mismatch"
    assert env.cr_state(cr)[0] == "todo"
    assert env.tmux.pane_info(first["pane_id"])["pane_dead"] is False
    stopped = env.manager().control("stop", job=cr)
    assert stopped["released"] is False
    assert stopped["reasons"] == ["seat has uncommitted or untracked files"]
    import agent_session.lifecycle as lifecycle
    with pytest.MonkeyPatch.context() as patch:
        fail_once(patch, lifecycle.Manager, "_launch")
        with pytest.raises(SessionError) as error:
            env.manager().start(cr)
    assert error.value.code == "fixture_failure"
    pending = env.tmux.get_current("fixture", "seat-0")
    assert pending["run_id"] != first["run_id"] and pending["provider_launch_attempted"] is False
    assert env.cr_state(cr)[0] == "in-progress" and env.store.read()["0"]["job_id"] == cr
    resumed = env.manager().start(cr)
    assert resumed["seat"] == 0 and resumed["run_id"] == pending["run_id"]
    assert resumed["session"]["session_id"] != first["session"]["session_id"]
    assert env.cr_state(cr)[0] == "in-progress"
    assert kept.read_text() == "unfinished work\n"
    assert git(env.seats[0], "branch", "--show-current") == "cr/TOOL-001"
    assert env.store.read()["0"]["git_hash"] == env.initial_hash
    assert env.store.read()["0"]["session"]["session_id"] == resumed["session"]["session_id"]


BODY_MARKER = "BODY-ONLY-MARKER-7f3c"


def grow(env, cr_id, size=20000):
    """Pad the CR's Evidence past tmux's command limit (about 16 KiB), as Results and Dispositions do."""
    _, path = env.cr_state(cr_id)
    padding = BODY_MARKER + "\n" + "- evidence line kept in the CR file\n" * (size // 36)
    path.write_text(path.read_text().replace("## Evidence\n", "## Evidence\n" + padding, 1))
    assert len(path.read_bytes()) > size


def assert_job_points_to_the_cr(env, cr, run_id):
    job = env.tmux.get_current("fixture", "seat-0")["job"]
    assert "text" not in job
    assert job["job_id"] == cr and job["path"] == str(env.cr_state(cr)[1])
    assert BODY_MARKER not in (env.base / "agent/runs" / run_id / "prompt.md").read_text()


def test_worker_start_with_a_cr_over_the_tmux_command_limit(session_env):
    env = session_env
    cr = env.cr()
    grow(env, cr)
    worker = env.manager().start(cr)
    assert worker["seat"] == 0 and worker["ready"] is True
    assert_job_points_to_the_cr(env, cr, worker["run_id"])


@pytest.mark.parametrize("previous", ["stopped", "unlaunched"])
def test_a_cr_that_grew_past_the_tmux_command_limit_resumes_on_its_seat(session_env, monkeypatch, previous):
    import agent_session.lifecycle as lifecycle

    env = session_env
    cr = env.cr()
    if previous == "stopped":
        first = env.manager().start(cr)
        (env.seats[0] / "worker-notes.txt").write_text("unfinished work\n")
        env.finish(cr, state="todo", outcome=None, note="park on the user's stop")
        assert env.manager().control("stop", job=cr)["released"] is False
    else:
        fail_once(monkeypatch, lifecycle.Manager, "_launch")
        with pytest.raises(SessionError):
            env.manager().start(cr)
        first = env.tmux.get_current("fixture", "seat-0")
    grow(env, cr)
    resumed = env.manager().start(cr)
    assert resumed["seat"] == 0 and resumed["ready"] is True
    assert (resumed["run_id"] == first["run_id"]) is (previous == "unlaunched")
    assert env.cr_state(cr)[0] == "in-progress"
    assert_job_points_to_the_cr(env, cr, resumed["run_id"])


def test_worker_prompt_points_to_the_cr_file_instead_of_its_text(session_env):
    env = session_env
    cr = env.cr()
    _, path = env.cr_state(cr)
    path.write_text(path.read_text().replace("Change server.py.", "Change server.py. " + BODY_MARKER))
    worker = env.manager().start(cr)
    prompt = (env.base / "agent/runs" / worker["run_id"] / "prompt.md").read_text()
    assert "CR 파일: " + str(env.cr_state(cr)[1]) + "\n" in prompt
    assert "위 CR 파일을 읽" in prompt
    assert BODY_MARKER not in prompt and "## Implementation" not in prompt


def test_read_only_preparation_syncs_main_without_a_branch(session_env):
    env = session_env
    newer = env.advance_remote()
    cr = env.cr(mode="read-only")
    result = env.manager().start(cr)
    assert env.store.read()["0"]["git_hash"] == newer
    assert git(env.seats[0], "branch", "--show-current") == "main"
    assert git(env.seats[0], "branch", "--list", "cr/*") == ""
    env.finish(cr, state="open", outcome=None, note="evidence recorded in the CR")
    assert env.manager().control("stop", job=result["job_id"])["released"] is True


def test_fixed_result_must_be_on_origin_main_before_release(session_env):
    env = session_env
    cr = env.cr()
    result = env.manager().start(cr)
    (env.seats[0] / "server.py").write_text("VALUE = 4\n")
    git(env.seats[0], "add", "server.py")
    git(env.seats[0], "commit", "-m", "Not integrated")
    env.publish(env.seats[0])
    env.finish(cr)
    refused = env.manager().control("stop", job=cr)
    assert refused["released"] is False
    assert "the fixed result is not on origin/main" in refused["reasons"]
    git(env.base, "fetch", "origin", "cr/TOOL-001")
    git(env.base, "merge", "--ff-only", "origin/cr/TOOL-001")
    git(env.base, "push", "origin", "main")
    assert env.manager().control("stop", job=result["job_id"])["released"] is True
    assert env.store.read()["0"] == EMPTY


def test_leader_default_prompt_routes_user_questions_to_decision_items(session_env):
    env = session_env
    result = env.manager().start("leader")
    prompt = (env.base / "agent/runs" / result["run_id"] / "prompt.md").read_text()
    assert "결정 항목으로 남기고" in prompt and "위임 범위의 판정" in prompt


def test_leader_prelaunch_retry_preserves_the_request(session_env, monkeypatch):
    import agent_session.lifecycle as lifecycle

    env = session_env
    request = env.root / "REQUEST.md"
    task = "Refactor the server only after checking the approved server requirements."
    request.write_text(task)
    fail_once(monkeypatch, lifecycle.Manager, "_session_input")
    with pytest.raises(SessionError) as error:
        env.manager().start("leader", prompt_file=str(request))
    assert error.value.code == "fixture_failure"
    pending = env.tmux.get_current("fixture", "leader")
    assert pending["provider_launch_attempted"] is False
    assert env.store.read()["leader"] is None
    result = env.manager().start("leader", prompt_file=str(request))
    prompt = (env.base / "agent/runs" / result["run_id"] / "prompt.md").read_text()
    assert result["run_id"] == pending["run_id"] and result["ready"] is True and task in prompt


def test_allocation_skips_missing_window_without_erasing_its_evidence(session_env):
    env = session_env
    env.manager().start("leader")
    missing = env.tmux.create_window("fixture", "closed-worker", env.seats[0], {
        "base": str(env.base), "run_id": "closed-worker-run", "target": "seat-0", "job_id": "TOOL-099",
    })
    env.tmux.set_current("fixture", "seat-0", missing)
    pointer = env.tmux.command("show-options", "-qv", "-t", "fixture", "@agent_session_current_seat_0")
    env.tmux.command("kill-window", "-t", missing["window_id"])
    worker = env.manager().start(env.cr())
    assert worker["seat"] == 1
    assert env.store.read()["0"] == EMPTY
    assert git(env.seats[0], "branch", "--show-current") == "main"
    assert env.tmux.command("show-options", "-qv", "-t", "fixture", "@agent_session_current_seat_0") == pointer


def test_missing_other_window_does_not_hide_a_live_pane_caller(session_env, monkeypatch):
    env = session_env
    worker = env.manager().start(env.cr())
    missing = env.tmux.create_window("fixture", "closed-leader", env.base, {
        "base": str(env.base), "run_id": "closed-leader-run", "target": "leader", "job_id": None,
    })
    env.tmux.set_current("fixture", "leader", missing)
    env.tmux.command("kill-window", "-t", missing["window_id"])
    monkeypatch.setenv("TMUX_PANE", worker["pane_id"])
    current = env.tmux.get_current("fixture", "seat-0")
    monkeypatch.setenv("TMUX", current["socket_path"] + "," + str(current["server_pid"]) + ",0")
    second = env.cr(number=2)
    with pytest.raises(SessionError) as error:
        env.manager().start(second)
    assert error.value.code == "role_denied"
    assert env.store.read()["0"]["job_id"] == worker["job_id"]
    assert env.store.read()["1"]["job_id"] is None
    assert env.cr_state(second)[0] == "todo"


def test_stop_can_end_an_unlaunched_placeholder_without_releasing_unfinished_job(session_env, monkeypatch):
    import agent_session.git_ops as git_ops
    from agent_session.api import check_binding

    env = session_env
    cr = env.cr()
    fail_once(monkeypatch, git_ops, "sync_main")
    with pytest.raises(SessionError):
        env.manager().start(cr)
    pending = env.tmux.get_current("fixture", "seat-0")
    assert pending["provider_launch_attempted"] is False and pending["registered"] is False
    before = env.store.read()["0"].copy()
    snapshot = env.project.state_path.read_bytes()
    binding = check_binding(env.base, cr, config_path=env.config, socket=env.tmux.effective_socket())
    assert binding["session"] is None
    assert binding["ready"] is False and binding["alive"] is False
    assert binding["termination_confirmed"] is False
    assert env.project.state_path.read_bytes() == snapshot
    result = env.manager().control("stop", job=cr)
    assert result["stopped"] is True and result["released"] is False
    assert env.tmux.pane_info(pending["pane_id"])["pane_dead"] is True
    assert env.store.read()["0"] == before and env.store.read()["0"]["session"] is None
    binding = check_binding(env.base, cr, config_path=env.config, socket=env.tmux.effective_socket())
    assert binding["session"] is None and binding["termination_confirmed"] is True
    assert env.project.state_path.read_bytes() == snapshot


def test_rejected_stop_request_does_not_mark_a_ready_session_stopping(session_env, monkeypatch):
    env = session_env
    worker = env.manager().start(env.cr())
    manager = env.manager()

    def reject_request(*args, **kwargs):
        raise SessionError("session_unbound", "The native conversation could not be verified.", 4)

    monkeypatch.setattr(manager.provider, "request_stop", reject_request)
    with pytest.raises(SessionError) as error:
        manager.control("stop", job=worker["job_id"])
    assert error.value.code == "session_unbound"
    current = env.tmux.get_current("fixture", "seat-0")
    assert current["stopping"] is False and current["ready"] is True
    assert env.tmux.pane_info(worker["pane_id"])["pane_dead"] is False
    assert ident(env.store.read()["0"]["session"]) == worker["session"]


def test_stop_that_times_out_on_a_live_cli_lets_it_take_messages_again(session_env, monkeypatch):
    env = session_env
    worker = env.manager().start(env.cr())
    manager = env.manager(timeout=3)
    busy = {"known": True, "terminal": False, "active_turn": True, "pending": [], "background": [], "idle": False}
    monkeypatch.setattr(manager.provider, "observe", lambda *args, **kwargs: busy)
    with pytest.raises(SessionError) as error:
        manager.control("stop", job=worker["job_id"])
    assert (error.value.code, error.value.exit_code) == ("timeout", 4)
    stopping = env.tmux.get_current("fixture", "seat-0")["stopping"]
    try:
        delivered = env.manager().send(job=worker["job_id"], message="the stop did not end you")["disposition"]
    except SessionError as failure:
        delivered = failure.code
    assert (stopping, delivered) == (False, "accepted")
    assert error.value.details == {"stopping_restored": True}
    assert env.tmux.pane_info(worker["pane_id"])["pane_dead"] is False


def claude_project(env, monkeypatch):
    """Make the fixture a Claude project; return the file where its CLI records input and signals."""
    import agent_session.lifecycle as lifecycle
    import agent_session.providers as providers
    from agent_session_fake_provider import FakeClaudeProvider

    config = json.loads(env.config.read_text())
    config[str(env.base)]["provider"] = "claude"
    env.config.write_text(json.dumps(config))
    monkeypatch.setattr(lifecycle, "get_provider", lambda name: FakeClaudeProvider())
    monkeypatch.setattr(providers, "get_provider", lambda name: FakeClaudeProvider())
    return env.base / "agent" / "fixture-cli.jsonl"


def recorded(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_claude_stop_signals_its_cli_and_types_nothing_in_the_pane(session_env, monkeypatch):
    env = session_env
    record = claude_project(env, monkeypatch)
    worker = env.manager().start(env.cr())
    result = env.manager().control("stop", job=worker["job_id"])
    assert result["stopped"] is True and result["released"] is False
    assert recorded(record) == [{"signal": "SIGTERM"}]
    assert "/exit" not in env.tmux.capture_pane(worker["pane_id"])


def listing_drops_the_run(manager, monkeypatch, after_exit):
    """Make ListAgents lose the run: from the SIGTERM on if after_exit, otherwise from the first look."""
    from agent_session.errors import SessionError

    provider = manager.provider
    observe, request_exit = provider.observe, provider.request_exit
    state = {"exited": False, "dropped": 0}

    def exit_then_drop(meta, tmux):
        state["exited"] = True
        return request_exit(meta, tmux)

    def observe_without_row(session, context, meta=None, timeout=30):
        if state["exited"] == after_exit and state["dropped"] < 3:
            state["dropped"] += 1
            raise SessionError("session_not_bound", "Claude ListAgents does not identify one managed pane.", 3)
        return observe(session, context, meta, timeout)

    monkeypatch.setattr(provider, "request_exit", exit_then_drop)
    monkeypatch.setattr(provider, "observe", observe_without_row)
    return state


def test_claude_stop_waits_for_the_cli_when_sigterm_drops_it_from_listagents(session_env, monkeypatch):
    env = session_env
    record = claude_project(env, monkeypatch)
    worker = env.manager().start(env.cr())
    manager = env.manager(timeout=30)
    state = listing_drops_the_run(manager, monkeypatch, after_exit=True)
    result = manager.control("stop", job=worker["job_id"])
    assert result["stopped"] is True and result["released"] is False
    assert state["dropped"] == 3
    assert recorded(record) == [{"signal": "SIGTERM"}]
    assert env.tmux.pane_info(worker["pane_id"])["pane_dead"] is True


def test_claude_stop_that_loses_the_listing_before_the_signal_is_still_an_error(session_env, monkeypatch):
    env = session_env
    record = claude_project(env, monkeypatch)
    worker = env.manager().start(env.cr())
    manager = env.manager(timeout=30)
    listing_drops_the_run(manager, monkeypatch, after_exit=False)
    with pytest.raises(SessionError) as error:
        manager.control("stop", job=worker["job_id"])
    assert error.value.code == "session_not_bound"
    assert recorded(record) == []
    assert env.tmux.pane_info(worker["pane_id"])["pane_dead"] is False


def test_claude_stop_does_not_signal_a_cli_whose_birth_differs(session_env, monkeypatch):
    env = session_env
    record = claude_project(env, monkeypatch)
    worker = env.manager().start(env.cr())
    env.tmux.write_meta(worker["window_id"], {"cli_birth": "linux:another-boot:1"})
    with pytest.raises(SessionError) as error:
        env.manager(timeout=5).control("stop", job=worker["job_id"])
    assert error.value.code == "target_changed"
    # The CLI that the run recorded is not confirmed alive, so stop leaves its block for the operator.
    assert error.value.details == {"stopping_restored": False, "stopping_kept": "cli_unconfirmed"}
    assert env.tmux.get_current("fixture", "seat-0")["stopping"] is True
    assert recorded(record) == []
    assert env.tmux.pane_info(worker["pane_id"])["pane_dead"] is False


@pytest.mark.parametrize("attempted", [True, None])
def test_unbound_attempted_or_unknown_launch_cannot_be_stopped_as_a_placeholder(session_env, monkeypatch, attempted):
    import agent_session.git_ops as git_ops

    env = session_env
    cr = env.cr()
    fail_once(monkeypatch, git_ops, "sync_main")
    with pytest.raises(SessionError):
        env.manager().start(cr)
    pending = env.tmux.get_current("fixture", "seat-0")
    env.tmux.write_meta(pending["window_id"], {"provider_launch_attempted": attempted})
    before = env.store.read()["0"].copy()
    with pytest.raises(SessionError) as error:
        env.manager().control("stop", job=cr)
    assert error.value.code == "session_unbound"
    current = env.tmux.get_current("fixture", "seat-0")
    assert current["stopping"] is False
    assert env.tmux.pane_info(pending["pane_id"])["pane_dead"] is False
    assert env.store.read()["0"] == before


def record_provider_input(monkeypatch):
    """Record each provider send, stop request, and pane exit request; return the record."""
    from agent_session_fake_provider import FakeProvider

    calls = []
    for name in ("send", "request_stop", "request_exit"):
        original = getattr(FakeProvider, name)
        monkeypatch.setattr(FakeProvider, name, lambda self, *args, _name=name, _original=original, **kwargs:
                            calls.append(_name) or _original(self, *args, **kwargs))
    return calls


def outcome(command):
    try:
        result = command()
    except SessionError as error:
        return error.code
    return result.get("disposition") or ("stopped" if result.get("stopped") else "returned")


def test_a_run_of_another_base_gets_no_input_through_its_socket(session_env, tmp_path, monkeypatch):
    """Two registries name the same project ID; the other base's socket holds no target for this base."""
    from agent_session.lifecycle import Manager
    from agent_session_fixture import Environment

    env = session_env
    (tmp_path / "other").mkdir()
    other = Environment(tmp_path / "other").setup()
    try:
        cr = env.cr()
        foreign = {"leader": env.manager().start("leader"), cr: env.manager().start(cr)}
        assert other.cr() == cr
        other.manager().start("leader")
        other.manager().start(cr)
        calls = record_provider_input(monkeypatch)
        crossed = lambda: Manager(other.base, other.config, socket_name=env.socket_name, timeout=command_timeout())
        snapshots = (env.project.state_path.read_bytes(), other.project.state_path.read_bytes())
        results = [outcome(lambda: crossed().send(job=job, message="for the other base")) for job in foreign]
        results += [outcome(lambda: crossed().control("stop", job=job)) for job in foreign]
        assert (results, calls) == (["owner_mismatch"] * 4, [])
        # The base alone decides even when the state names the foreign run's conversation.
        def adopt(value):
            value["leader"]["session_id"] = foreign["leader"]["session"]["session_id"]
            value["0"]["session"]["session_id"] = foreign[cr]["session"]["session_id"]
        other.store.update(adopt)
        results = [outcome(lambda: crossed().send(job=job, message="for the other base")) for job in foreign]
        assert (results, calls) == (["owner_mismatch"] * 2, [])
        assert not (env.base / "agent/fixture-messages.jsonl").exists()
        for job, run in foreign.items():
            current = env.tmux.get_current("fixture", "leader" if job == "leader" else "seat-0")
            assert current["run_id"] == run["run_id"] and current["stopping"] is False
            assert env.tmux.pane_info(run["pane_id"])["pane_dead"] is False
        assert env.project.state_path.read_bytes() == snapshots[0]
    finally:
        stop_test_server(other.socket_name)


@pytest.mark.parametrize("scenario", ["stopped-worker", "waiting-worker", "waiting-leader", "live-leader", "unassigned-seat"])
def test_start_does_not_handle_the_run_of_another_base(session_env, tmp_path, monkeypatch, scenario):
    """Start's re-handling of an existing run applies the same base check as send and control."""
    import agent_session.git_ops as git_ops
    import agent_session.lifecycle as lifecycle
    from agent_session.lifecycle import Manager
    from agent_session_fake_provider import FakeProvider
    from agent_session_fixture import Environment

    env = session_env
    (tmp_path / "other").mkdir()
    other = Environment(tmp_path / "other").setup()
    try:
        cr = env.cr()
        assert other.cr() == cr
        other.manager().start("leader")
        if scenario != "unassigned-seat":
            other.manager().start(cr)
        slot = "leader" if scenario.endswith("leader") else "seat-0"
        job = "leader" if slot == "leader" else cr
        if scenario == "unassigned-seat":
            job = other.cr(2)                      # a new CR takes an empty seat, whose slot the foreign run holds
        if scenario in ("stopped-worker", "unassigned-seat"):
            env.manager().start(cr)
            assert env.manager().control("stop", job=cr)["released"] is False
        elif scenario == "waiting-worker":
            fail_once(monkeypatch, git_ops, "sync_main")
            with pytest.raises(SessionError):
                env.manager().start(cr)
        elif scenario == "waiting-leader":
            fail_once(monkeypatch, lifecycle.Manager, "_session_input")
            with pytest.raises(SessionError):
                env.manager().start("leader")
        else:
            env.manager().start("leader")
        foreign = env.tmux.get_current("fixture", slot)
        calls = []
        for name in ("observe", "launch_spec", "send", "request_stop", "request_exit"):
            original = getattr(FakeProvider, name)
            monkeypatch.setattr(FakeProvider, name, lambda self, *args, _name=name, _original=original, **kwargs:
                                calls.append(_name) or _original(self, *args, **kwargs))

        from agent_session.tmux import Tmux
        command = Tmux.command
        monkeypatch.setattr(Tmux, "command", lambda self, *args, **kwargs:
                            (calls.append(args[0]) if args[0] == "rename-window" else None) or command(self, *args, **kwargs))

        def names():
            return env.tmux.command("list-windows", "-t", "fixture", "-F", "#{window_id} #{window_name}")

        before = (names(), env.tmux.read_meta(foreign["window_id"]), env.project.state_path.read_bytes(),
                  other.project.state_path.read_bytes())
        crossed = Manager(other.base, other.config, socket_name=env.socket_name, timeout=command_timeout())
        assert outcome(lambda: crossed.start(job)) == "owner_mismatch"
        assert calls == []
        after = (names(), env.tmux.read_meta(foreign["window_id"]), env.project.state_path.read_bytes(),
                 other.project.state_path.read_bytes())
        assert after == before
        assert env.tmux.get_current("fixture", slot)["run_id"] == foreign["run_id"]
    finally:
        subprocess.run(["tmux", "-L", other.socket_name, "kill-server"], capture_output=True, timeout=10)


def test_a_run_that_the_state_does_not_name_gets_no_input(session_env, monkeypatch):
    env = session_env
    cr = env.cr()
    runs = {"leader": env.manager().start("leader"), cr: env.manager().start(cr)}
    env.handoff("leader")
    env.handoff("seat-0")
    published = env.store.read()

    def replace(value):
        value["leader"]["session_id"] = str(uuid.uuid4())
        value["0"]["session"]["session_id"] = str(uuid.uuid4())
    env.store.update(replace)
    calls = record_provider_input(monkeypatch)
    results = [outcome(lambda: env.manager().send(job=job, message="for the named conversation")) for job in runs]
    for operation in ("stop", "restart"):
        results += [outcome(lambda: env.manager().control(operation, job=job)) for job in runs]
    assert (results, calls) == (["owner_mismatch"] * 6, [])
    for job, run in runs.items():
        current = env.tmux.get_current("fixture", "leader" if job == "leader" else "seat-0")
        assert current["run_id"] == run["run_id"] and current["stopping"] is False
        assert env.tmux.pane_info(run["pane_id"])["pane_dead"] is False
    # The same runs take input again once the state names their conversations.
    env.store.update(lambda value: published)
    results = [outcome(lambda: env.manager().send(job=job, message="for the named conversation")) for job in runs]
    assert (results, calls) == (["accepted"] * 2, ["send"] * 2)


def test_launch_args_reach_the_provider_input(session_env, monkeypatch):
    env = session_env
    config = json.loads(env.config.read_text())
    config[str(env.base)]["launch"] = {"args": ["--dangerously-bypass-approvals-and-sandbox"]}
    env.config.write_text(json.dumps(config))
    captured = []
    import agent_session.lifecycle as lifecycle
    provider = lifecycle.get_provider("codex")
    original = provider.launch_spec
    monkeypatch.setattr(lifecycle, "get_provider", lambda name: provider)
    monkeypatch.setattr(provider, "launch_spec", lambda context, prepared: captured.append(prepared) or original(context, prepared))
    env.manager().start(env.cr())
    prepared = captured[-1]
    assert prepared["provider_args"] == ["--dangerously-bypass-approvals-and-sandbox"]
    assert set(prepared["env"]) == {"AGENT_SESSION_CONFIG", "AGENT_SESSION_SOCKET", "AGENT_SESSION_BASE"}
    assert prepared["unset_env"] == []


def test_role_launch_args_reach_only_their_role(session_env, monkeypatch):
    env = session_env
    config = json.loads(env.config.read_text())
    config[str(env.base)]["launch"] = {"args": ["--dangerously-bypass-approvals-and-sandbox"],
                                       "leader_args": ["--model", "leader-model"],
                                       "worker_args": ["--model", "worker-model"]}
    env.config.write_text(json.dumps(config))
    captured = {}
    import agent_session.lifecycle as lifecycle
    provider = lifecycle.get_provider("codex")
    original = provider.launch_spec
    monkeypatch.setattr(lifecycle, "get_provider", lambda name: provider)
    monkeypatch.setattr(provider, "launch_spec",
                        lambda context, prepared: captured.setdefault(context["target"], prepared)
                        and original(context, prepared))
    env.manager().start("leader")
    env.manager().start(env.cr())
    assert captured["leader"]["provider_args"] == ["--dangerously-bypass-approvals-and-sandbox",
                                                   "--model", "leader-model"]
    assert captured["seat-0"]["provider_args"] == ["--dangerously-bypass-approvals-and-sandbox",
                                                   "--model", "worker-model"]


# ---------------------------------------------------------------- V3 review regressions
def test_failed_reservation_frees_the_seat_for_the_next_start(session_env, monkeypatch):
    """B1: the placeholder of a failed reservation must not block the same seat."""
    env = session_env
    (env.seats[1] / "busy.txt").write_text("seat 1 is busy\n")
    cr = env.cr()
    env.store.update(lambda value: value)                  # the state exists before the failure
    fail_once(monkeypatch, env.store.__class__, "update")
    with pytest.raises(SessionError):
        env.manager().start(cr)
    assert env.cr_state(cr)[0] == "todo"
    worker = env.manager().start(cr)
    assert worker["seat"] == 0 and worker["ready"] is True


def test_cwd_that_appears_only_on_latest_main_is_accepted(session_env):
    """B3: the Cwd directory is checked after the main sync, not before."""
    env = session_env
    (env.seed / "newdir").mkdir()
    (env.seed / "newdir" / "x.txt").write_text("new\n")
    git(env.seed, "add", "newdir/x.txt")
    git(env.seed, "commit", "-m", "Add newdir")
    git(env.seed, "push", "origin", "main")
    worker = env.manager().start(env.cr(cwd="newdir"))
    assert worker["cwd"] == str(env.seats[0] / "newdir")


def test_missing_cwd_is_refused_before_the_provider_starts(session_env):
    env = session_env
    cr = env.cr(cwd="missing")
    with pytest.raises(SessionError) as error:
        env.manager().start(cr)
    assert error.value.code == "cwd_unavailable"
    pending = env.tmux.get_current("fixture", "seat-0")
    assert pending["provider_launch_attempted"] is False


def test_publication_counts_only_on_origin(session_env):
    """B4: a commit published only on another remote is not on origin."""
    env = session_env
    backup = env.root / "backup.git"
    git(env.root, "init", "--bare", "--initial-branch=main", str(backup))
    git(env.seats[0], "remote", "add", "backup", str(backup))
    (env.seats[0] / "local.txt").write_text("only on backup\n")
    git(env.seats[0], "add", "local.txt")
    git(env.seats[0], "commit", "-m", "Backup only")
    git(env.seats[0], "push", "backup", "HEAD:refs/heads/main")
    git(env.seats[0], "fetch", "backup")
    worker = env.manager().start(env.cr())
    assert worker["seat"] == 1


TIME = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"


def test_republished_connection_keeps_its_time_and_review(session_env, monkeypatch):
    from agent_session.tmux import Tmux

    env = session_env
    original = Tmux.write_meta

    def lose_ready(self, window_id, updates):
        if updates.get("ready") is True:
            raise SessionError("tmux_command_failed", "The fixture lost the ready flag.", 5)
        return original(self, window_id, updates)

    with monkeypatch.context() as broken:
        broken.setattr(Tmux, "write_meta", lose_ready)
        with pytest.raises(SessionError) as error:
            env.manager().start("leader")
        assert error.value.code == "tmux_command_failed"
    published = env.store.read()["leader"]
    assert re.fullmatch(TIME, published["connected_at"]) and published["reviewing"] is None
    cr = env.cr()
    env.manager().start(cr)
    assert re.fullmatch(TIME, env.store.read()["0"]["session"]["connected_at"])
    env.manager().review(job=cr)
    before = env.store.read()
    time.sleep(1.1)
    retried = env.manager().start("leader")
    assert retried["ready"] is True and retried["session"]["session_id"] == published["session_id"]
    assert env.store.read() == before


def test_review_mark_needs_the_leader_and_an_assigned_connected_job(session_env, monkeypatch):
    env = session_env
    with pytest.raises(SessionError) as error:
        env.manager().review(job="TOOL-001")
    assert error.value.code == "session_unbound"
    leader = env.manager().start("leader")
    first, second = env.cr(1), env.cr(2)
    worker = env.manager().start(first)
    env.manager().start(second)
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", worker["session"]["session_id"])
        with pytest.raises(SessionError) as error:
            env.manager().review(job=first)
        assert error.value.code == "role_denied"
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", leader["session"]["session_id"])
        assert env.manager().review(job=first) == {"project": "fixture", "reviewing": first}
        assert env.manager().review(job=second)["reviewing"] == second
        for job, code in (("TOOL-099", "job_not_assigned"), ("leader", "invalid_input")):
            with pytest.raises(SessionError) as error:
                env.manager().review(job=job)
            assert error.value.code == code
        for arguments in ({}, {"job": first, "clear": True}):
            with pytest.raises(SessionError) as error:
                env.manager().review(**arguments)
            assert error.value.code == "invalid_input"
        assert env.store.read()["leader"]["reviewing"] == second
        env.store.update(lambda state: state["0"].update(session=None))
        with pytest.raises(SessionError) as error:
            env.manager().review(job=first)
        assert error.value.code == "session_unbound"
        assert env.manager().review(clear=True)["reviewing"] is None


def test_review_mark_clears_on_leader_feedback_stop_and_a_new_leader(session_env, monkeypatch):
    env = session_env
    leader = env.manager().start("leader")
    cr = env.cr()
    env.manager().start(cr)

    def reviewing():
        current = env.store.read()["leader"]
        return current and current["reviewing"]

    env.manager().review(job=cr)
    assert env.manager().send(job=cr, message="An operator note.")["disposition"] == "accepted"
    assert reviewing() == cr
    env.manager()._clear_review(cr, leader_session_id="an-earlier-leader")
    assert reviewing() == cr
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", leader["session"]["session_id"])
        env.manager().send(job=cr, message="Correct the result.")
    assert reviewing() is None
    env.manager().review(job=cr)
    held = env.manager().control("stop", job=cr)
    assert held["released"] is False and reviewing() is None and env.store.read()["0"]["job_id"] == cr
    env.manager().review(job=cr)
    env.handoff("leader", "Continue the review.")
    restarted = env.manager().control("restart", job="leader")
    assert env.store.read()["leader"]["session_id"] == restarted["session"]["session_id"]
    assert reviewing() is None
    env.manager().review(job=cr)
    env.finish(cr, state="done", outcome="waived", note="no change needed")
    released = env.manager().control("stop", job=cr)
    assert released["released"] is True and env.store.read()["0"] == EMPTY and reviewing() is None


def test_restart_and_a_later_start_close_retired_windows(session_env, monkeypatch):
    from agent_session import internal

    env = session_env
    without_reuse(monkeypatch)
    cr = env.cr()
    original = env.manager().start(cr)
    env.handoff("seat-0", "Continue the fixture change.")
    restarted = env.manager().control("restart", job=cr)
    assert restarted["cleanup"] == {"closed": [original["window_id"]], "kept": []}
    assert windows(env) == [restarted["window_id"]]
    held = env.manager().control("stop", job=cr)
    assert held["released"] is False and held["cleanup"] == {"closed": [], "kept": []}
    assert windows(env) == [restarted["window_id"]]
    assert env.tmux.get_current("fixture", "seat-0")["run_id"] == restarted["run_id"]
    continued = env.manager().start(cr)
    assert continued["cleanup"] == {"closed": [restarted["window_id"]], "kept": []}
    assert windows(env) == [continued["window_id"]]
    with pytest.raises(SessionError) as error:
        internal._run(original["run_id"], str(env.config), env.tmux.effective_socket(), cwd=str(env.base))
    assert error.value.code == "target_changed"


def test_sweep_keeps_pending_controlled_shared_or_unconfirmed_windows(session_env, monkeypatch):
    import agent_session.lifecycle as lifecycle
    from agent_session.process import birth

    env = session_env
    without_reuse(monkeypatch)
    cr = env.cr()
    runs = [env.manager().start(cr)]
    with monkeypatch.context() as quiet:
        quiet.setattr(lifecycle.Manager, "_sweep", lambda self, target, owner=None: {"closed": [], "kept": []})
        for _ in range(5):
            env.handoff("seat-0", "Continue the fixture change.")
            runs.append(env.manager().control("restart", job=cr))
    assert windows(env) == [run["window_id"] for run in runs]
    pending, controlled, shared, unconfirmed, ended = runs[:5]
    env.tmux.write_meta(pending["window_id"], {"control_pending": True})
    me = {"pid": os.getpid(), "birth": birth(os.getpid())}
    env.tmux.write_meta(controlled["window_id"], {"controller_pid": me["pid"], "controller_birth": me["birth"]})
    env.tmux.command("split-window", "-d", "-t", shared["window_id"], "sleep", "86400")
    manager = env.manager()
    observe = manager.provider.observe

    def partly_unknown(session, context, meta=None, timeout=30):
        if session["session_id"] == unconfirmed["session"]["session_id"]:
            return {"known": False}
        return observe(session, context, meta, timeout)

    manager.provider.observe = partly_unknown
    swept = manager._sweep("seat-0")
    assert swept["closed"] == [ended["window_id"]]
    assert {item["window_id"]: item["reason"] for item in swept["kept"]} == {
        pending["window_id"]: "control_pending", controlled["window_id"]: "controller_running",
        shared["window_id"]: "window_shared", unconfirmed["window_id"]: "termination_unconfirmed"}
    result_file = env.base / "agent/runs" / controlled["run_id"] / "control-result.json"
    owner = {"run_id": controlled["run_id"], **me, "result_file": str(result_file)}
    for payload, other in (({"accepted": True, "completed": False}, {}), ({"completed": True}, {"pid": 1}),
                           ({"completed": True}, {"run_id": pending["run_id"]})):
        result_file.write_text(json.dumps({"ok": True, "data": payload, "error": None}))
        assert controlled["window_id"] not in manager._sweep("seat-0", owner={**owner, **other})["closed"]
    assert manager._sweep("seat-0", owner=owner)["closed"] == [controlled["window_id"]]
    assert windows(env) == [pending["window_id"], shared["window_id"], unconfirmed["window_id"], runs[5]["window_id"]]


SELF_CONTROL = r'''
import json, shlex, sys
library, fixtures, base, config, socket_name, operation, job = sys.argv[1:8]
sys.path[:0] = [library, fixtures]
from agent_session.lifecycle import Manager
from agent_session.tmux import Tmux

original = Tmux.run_controller


def run_fixture_controller(self, script, cwd):
    """Run the real deferred controller in tmux with the fixture provider."""
    code = ("import sys;sys.path[:0]=[sys.argv[1],sys.argv[2]];import agent_session_fake_provider as f;"
            "import agent_session.providers as p;import agent_session.lifecycle as l;"
            "p.get_provider=l.get_provider=lambda name:f.FakeProvider();"
            "from agent_session.internal import run_controller;run_controller(sys.argv[3])")
    command = shlex.join([sys.executable, "-c", code, library, fixtures,
                          str(script.with_name("control-request.json"))])
    script.write_text("#!/bin/bash\nset -e\nunset CODEX_THREAD_ID CLAUDE_CODE_SESSION_ID TMUX TMUX_PANE\nexec "
                      + command + "\n", encoding="utf-8")
    return original(self, script, cwd)


Tmux.run_controller = run_fixture_controller
print(json.dumps(Manager(base, config, socket_name=socket_name, timeout=60).control(operation, job=job)))
'''


def self_control(env, operation, job, session_id):
    """Request control from the managed conversation itself and wait for the controller result."""
    done = subprocess.run([sys.executable, "-c", SELF_CONTROL, str(Path(__file__).resolve().parents[1]),
                           str(FIXTURES), str(env.base), str(env.config), env.socket_name, operation, job],
                          env={**os.environ, "CODEX_THREAD_ID": session_id},
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    accepted = json.loads(done.stdout.splitlines()[-1])
    assert accepted["accepted"] is True and accepted["completed"] is False
    path = Path(accepted["result_file"])
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        result = json.loads(path.read_text(encoding="utf-8"))
        if result["data"].get("completed"):
            return result
        time.sleep(0.1)
    raise AssertionError("The controller did not finish: " + path.read_text(encoding="utf-8"))


def wait_until(predicate, limit=15):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    raise AssertionError("The expected condition was not reached.")


def test_self_stop_saves_its_result_before_closing_the_servers_last_window(session_env):
    env = session_env
    cr = env.cr()
    worker = env.manager().start(cr)
    env.finish(cr, state="done", outcome="waived", note="the fixture needs no change")
    env.tmux.command("kill-session", "-t", "harness")
    assert windows(env) == [worker["window_id"]]
    result = self_control(env, "stop", cr, worker["session"]["session_id"])
    assert result["ok"] is True and result["data"]["released"] is True
    assert "deferred_cleanup" not in result["data"]
    assert env.store.read()["0"] == EMPTY
    wait_until(lambda: not env.tmux.has_session("fixture"))
    saved = env.base / "agent/runs" / worker["run_id"] / "control-result.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == result


def test_self_restart_keeps_an_unreusable_window_until_its_result_is_saved(session_env):
    env = session_env
    cr = env.cr()
    worker = env.manager().start(cr)
    # A value that no run of this version writes keeps the window from the next run.
    env.tmux.command("set-option", "-w", "-t", worker["window_id"], "@agent_session_legacy_value", "1")
    env.handoff("seat-0", "Continue the fixture change.")
    result = self_control(env, "restart", cr, worker["session"]["session_id"])
    data = result["data"]
    assert result["ok"] is True and data["restarted"] is True and data["run_id"] != worker["run_id"]
    assert {"window_id": worker["window_id"], "reason": "control_pending"} in data["cleanup"]["kept"]
    wait_until(lambda: worker["window_id"] not in windows(env))
    assert windows(env) == [data["window_id"]]


def test_accepted_feedback_reports_a_failed_review_clear_without_failing(session_env, monkeypatch):
    import agent_session.lifecycle as lifecycle

    env = session_env
    leader = env.manager().start("leader")
    cr = env.cr()
    env.manager().start(cr)
    env.manager().review(job=cr)
    monkeypatch.setattr(lifecycle.Manager, "_clear_review", lambda self, job_id, leader_session_id=None: (
        _ for _ in ()).throw(SessionError("state_write_failed", "The fixture state write failed.", 5)))
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", leader["session"]["session_id"])
        sent = env.manager().send(job=cr, message="Correct the result.")
    assert sent["disposition"] == "accepted"
    assert sent["review_clear_error"]["code"] == "state_write_failed"
    assert env.store.read()["leader"]["reviewing"] == cr


def test_controller_cleanup_needs_the_slot_lock_and_keeps_the_current_run(session_env, monkeypatch):
    import agent_session.lifecycle as lifecycle

    env = session_env
    without_reuse(monkeypatch)
    cr = env.cr()
    first = env.manager().start(cr)
    with monkeypatch.context() as quiet:
        quiet.setattr(lifecycle.Manager, "_sweep", lambda self, target, owner=None: {"closed": [], "kept": []})
        env.handoff("seat-0", "Continue the fixture change.")
        current = env.manager().control("restart", job=cr)
        held = env.manager().control("stop", job=cr)
    assert held["released"] is False
    manager = env.manager()
    with locked(env.base / "agent/control/seat-0.lock"):
        busy = manager.sweep_after_result("seat-0", None)
    assert busy == {"closed": [], "kept": [{"window_id": None, "reason": "control_busy"}]}
    assert windows(env) == [first["window_id"], current["window_id"]]
    assert manager.sweep_after_result("seat-0", None) == {"closed": [first["window_id"]], "kept": []}
    assert windows(env) == [current["window_id"]]
    assert env.tmux.get_current("fixture", "seat-0")["run_id"] == current["run_id"]


def test_release_reports_a_pointer_it_could_not_clear(session_env, monkeypatch):
    from agent_session.tmux import Tmux

    env = session_env
    cr = env.cr()
    worker = env.manager().start(cr)
    env.finish(cr, state="done", outcome="waived", note="no change needed")

    def refuse(self, project_id, target, run_id):
        raise SessionError("tmux_command_failed", "The fixture refused the pointer change.", 5)

    monkeypatch.setattr(Tmux, "clear_current", refuse)
    stopped = env.manager().control("stop", job=cr)
    assert stopped["released"] is True and env.store.read()["0"] == EMPTY
    assert stopped["cleanup"] == {"closed": [], "kept": [{"window_id": worker["window_id"],
                                                          "reason": "tmux_command_failed"}]}
    assert worker["window_id"] in windows(env)
    assert env.tmux.get_current("fixture", "seat-0")["run_id"] == worker["run_id"]


def test_cleanup_budget_leaves_the_rest_for_a_later_sweep(session_env, monkeypatch):
    import agent_session.lifecycle as lifecycle

    env = session_env
    without_reuse(monkeypatch)
    cr = env.cr()
    first = env.manager().start(cr)
    monkeypatch.setattr(lifecycle, "SWEEP_SECONDS", 0)
    env.handoff("seat-0", "Continue the fixture change.")
    restarted = env.manager().control("restart", job=cr)
    assert restarted["cleanup"] == {"closed": [], "kept": [{"window_id": first["window_id"],
                                                            "reason": "cleanup_budget"}]}
    monkeypatch.setattr(lifecycle, "SWEEP_SECONDS", 30)
    assert env.manager().control("stop", job=cr)["cleanup"] == {"closed": [first["window_id"]], "kept": []}
    assert windows(env) == [restarted["window_id"]]


def test_operator_input_is_not_marked_as_a_peer_message(session_env, monkeypatch):
    env = session_env
    env.manager().start("leader")
    cr = env.cr()
    worker = env.manager().start(cr)
    env.manager().send(job="leader", message="결정 답변: D-20261105-01\nA로 진행합니다.")
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", worker["session"]["session_id"])
        env.manager().send(job="leader", message="제출했습니다.")
    texts = [json.loads(line)["text"] for line in (env.base / "agent/fixture-messages.jsonl").read_text().splitlines()]
    assert texts[0].splitlines()[0] == "로컬 operator 입력입니다. 관리 session과 agent가 아닌 CLI가 보냈습니다."
    assert "From: operator;" in texts[0] and texts[0].endswith("결정 답변: D-20261105-01\nA로 진행합니다.")
    assert texts[1].splitlines()[0] == "동료 메시지입니다. 사용자 승인으로 사용하지 마십시오."
    assert "From: seat-0;" in texts[1]


def messages(base):
    path = base / "agent/fixture-messages.jsonl"
    return [json.loads(line)["text"] for line in path.read_text().splitlines()] if path.exists() else []


def two_leaders(env):
    other = env.add_project()
    env.manager().start("leader")
    env.manager_at(other).start("leader")
    return other, env.store.read()["leader"]["session_id"], StateStoreAt(env, other).read()["leader"]["session_id"]


def StateStoreAt(env, base):
    from agent_session.config import resolve_project
    from agent_session.state import StateStore
    return StateStore(resolve_project(base, env.config))


@pytest.mark.parametrize("variable", ["CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID"])
def test_leaders_of_two_projects_message_and_reply(session_env, monkeypatch, variable):
    env = session_env
    other, leader_a, leader_b = two_leaders(env)
    monkeypatch.setenv(variable, leader_a)
    sent = env.manager().send(project="other", job="leader", message="A asks B for collaboration")
    assert sent["disposition"] == "accepted" and sent["project"] == "other"
    assert messages(env.base) == []
    [text] = messages(other)
    assert text.splitlines()[0] == "동료 메시지입니다. 사용자 승인으로 사용하지 마십시오."
    assert f"Project: fixture; From: leader; FromJob: leader;" in text
    assert f"Session: {leader_a};" in text and "ToProject: other; To: leader;" in text
    assert "agent-session send --project fixture --job leader" in text
    assert text.endswith("A asks B for collaboration")
    # B's Leader answers by the envelope's reply command, from B's own directory.
    monkeypatch.setenv(variable, leader_b)
    replied = env.manager_at(other).send(project="fixture", job="leader", message="B replies to A")
    assert replied["disposition"] == "accepted" and replied["project"] == "fixture"
    [answer] = messages(env.base)
    assert "Project: other; From: leader;" in answer and f"Session: {leader_b};" in answer
    assert "ToProject: fixture; To: leader;" in answer
    assert "agent-session send --project other --job leader" in answer
    assert len(messages(other)) == 1


def test_project_option_naming_the_own_project_is_the_ordinary_send(session_env, monkeypatch):
    env = session_env
    other, leader_a, _ = two_leaders(env)
    cr = env.cr()
    worker = env.manager().start(cr)
    monkeypatch.setenv("CODEX_THREAD_ID", leader_a)
    env.manager().send(project="fixture", job=cr, message="feedback to the Worker")
    assert "ToProject" not in messages(env.base)[-1] and messages(other) == []
    monkeypatch.setenv("CODEX_THREAD_ID", worker["session"]["session_id"])
    env.manager().send(project="fixture", job="leader", message="report to the Leader")
    assert "From: seat-0;" in messages(env.base)[-1] and "send --job TOOL-001" in messages(env.base)[-1]


def test_only_the_current_leader_with_a_leader_target_crosses_projects(session_env, monkeypatch):
    env = session_env
    other, leader_a, leader_b = two_leaders(env)
    cr = env.cr()
    worker = env.manager().start(cr)
    manager = env.manager()

    def denied(code, **kwargs):
        with pytest.raises(SessionError) as error:
            manager.send(project="other", message="cross", **kwargs)
        assert error.value.code == code
        assert messages(other) == []

    # A Worker of the sender's project may report only to its own Leader.
    monkeypatch.setenv("CODEX_THREAD_ID", worker["session"]["session_id"])
    denied("role_denied", job="leader")
    # An unregistered session and an operator are not Leaders.
    monkeypatch.setenv("CODEX_THREAD_ID", leader_b)       # the other project's Leader is not a member here
    denied("caller_unbound", job="leader")
    monkeypatch.setenv("CODEX_THREAD_ID", str(uuid.uuid4()))
    denied("caller_unbound", job="leader")
    monkeypatch.delenv("CODEX_THREAD_ID")
    denied("role_denied", job="leader")
    # The Leader may not address a JOB, a seat, or an unregistered project of another project.
    monkeypatch.setenv("CODEX_THREAD_ID", leader_a)
    denied("invalid_input", job="TOOL-001")
    denied("invalid_input", seat=0)
    with pytest.raises(SessionError) as error:
        manager.send(project="nowhere", job="leader", message="cross")
    assert error.value.code == "project_not_found"
    assert manager.send(project="other", job="leader", message="cross")["disposition"] == "accepted"


def test_a_replaced_leader_run_cannot_cross_projects(session_env, monkeypatch):
    env = session_env
    other, leader_a, _ = two_leaders(env)
    env.handoff("leader", "Continue the fixture Leader work.")
    env.manager().control("restart", job="leader")
    assert env.store.read()["leader"]["session_id"] != leader_a
    monkeypatch.setenv("CODEX_THREAD_ID", leader_a)
    with pytest.raises(SessionError) as error:
        env.manager().send(project="other", job="leader", message="from a previous run")
    assert error.value.code == "caller_unbound" and messages(other) == []


def test_sending_to_another_project_does_not_grant_its_control(session_env, monkeypatch):
    env = session_env
    other, leader_a, _ = two_leaders(env)
    monkeypatch.setenv("CODEX_THREAD_ID", leader_a)
    for command in ("stop", "restart"):
        with pytest.raises(SessionError) as error:
            env.manager_at(other).control(command, job="leader")
        assert error.value.code == "caller_unbound"
    with pytest.raises(SessionError) as error:
        env.manager_at(other).review(clear=True)
    assert error.value.code == "caller_unbound"


# --- Window reuse (SESSION-018): a new run takes over the retired window of its slot. ---

def add_pane(env, window_id):
    """A pane that a person added beside the managed pane."""
    return env.tmux.command("split-window", "-d", "-P", "-F", "#{pane_id}", "-t", window_id, "sleep", "86400")


def panes(env, window_id):
    return env.tmux.command("list-panes", "-t", window_id, "-F", "#{pane_id}").splitlines()


def window_names(env):
    return env.tmux.command("list-windows", "-t", "fixture", "-F", "#{window_id} #{window_name}").splitlines()


# What two runs of one slot may legitimately share; every other value must be the new run's own.
SHARED = {"base", "project_id", "provider", "config_path", "target", "seat", "seat_root", "cwd", "job_id", "role",
          "python", "library_path", "allow_daemon_start", "window_id", "pane_id", "window_name", "endpoint",
          "server_pid", "server_started", "server_birth", "socket_path", "registered", "ready", "stopping",
          "provider_launch_attempted", "job", "provider_name", "leader_request", "start_error"}


def test_leader_restart_reuses_the_window_with_the_panes_a_person_added(session_env):
    env = session_env
    first = env.manager().start("leader")
    first_meta = env.tmux.read_meta(first["window_id"])
    user = add_pane(env, first["window_id"])
    env.handoff("leader", "Continue the Leader work.")
    restarted = env.manager().control("restart", job="leader")
    assert restarted["window_id"] == first["window_id"] and restarted["pane_id"] == first["pane_id"]
    assert panes(env, first["window_id"]) == [first["pane_id"], user]
    assert windows(env) == [first["window_id"]]
    assert window_names(env) == [first["window_id"] + " fixture-leader"]
    assert restarted["run_id"] != first["run_id"]
    assert restarted["session"]["session_id"] != first["session"]["session_id"]
    assert restarted["cleanup"] == {"closed": [], "kept": []}
    assert env.store.read()["leader"]["session_id"] == restarted["session"]["session_id"]
    pointer = env.tmux.get_current("fixture", "leader")
    assert pointer["run_id"] == restarted["run_id"] and pointer["window_id"] == first["window_id"]
    meta = env.tmux.read_meta(first["window_id"])
    assert meta["run_id"] == restarted["run_id"] and meta["session_id"] == restarted["session"]["session_id"]
    # Nothing of the first run is left: a value equal to the first run's is one the slot's runs share.
    assert {key for key in first_meta if meta.get(key) == first_meta[key]} <= SHARED
    assert meta["control_pending"] is False and meta["controller_pid"] is None
    assert meta["launch_file"].endswith(restarted["run_id"] + "/launch.sh")
    # It reads as a window that was created for this run: the same keys and kinds of values, plus
    # neutral values for what only another run would have added.
    env.tmux.command("kill-pane", "-t", user)
    env.manager().control("stop", job="leader")        # no person's pane is left, so the window closes
    assert windows(env) == []
    fresh = env.tmux.read_meta(env.manager().start("leader")["window_id"])
    extra = set(meta) - set(fresh) - {"handoff_file"}    # the restart's own input, which a first start lacks
    assert set(fresh) <= set(meta) and extra and all(not meta[key] for key in extra)
    assert all(type(meta[key]) is type(fresh[key]) for key in fresh
               if fresh[key] is not None and meta[key] is not None)


def test_restart_without_a_person_pane_reuses_the_window_too(session_env):
    env = session_env
    cr = env.cr()
    worker = env.manager().start(cr)
    env.handoff("seat-0", "Continue the fixture change.")
    restarted = env.manager().control("restart", job=cr)
    assert restarted["window_id"] == worker["window_id"]
    assert windows(env) == [worker["window_id"]]
    assert window_names(env) == [worker["window_id"] + " fixture-seat0-" + cr]
    assert restarted["cleanup"] == {"closed": [], "kept": []}


def test_self_restart_reuses_the_window_and_leaves_no_pending_control(session_env):
    env = session_env
    leader = env.manager().start("leader")
    user = add_pane(env, leader["window_id"])
    env.handoff("leader", "Continue the Leader work.")
    result = self_control(env, "restart", "leader", leader["session"]["session_id"])
    data = result["data"]
    assert result["ok"] is True and data["completed"] is True and data["restarted"] is True
    assert data["window_id"] == leader["window_id"] and data["run_id"] != leader["run_id"]
    assert panes(env, leader["window_id"]) == [leader["pane_id"], user]
    assert windows(env) == [leader["window_id"]]
    meta = env.tmux.read_meta(leader["window_id"])
    assert meta["run_id"] == data["run_id"] and meta["control_pending"] is False and meta["controller_pid"] is None
    saved = env.base / "agent/runs" / leader["run_id"] / "control-result.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == result
    assert env.tmux.get_current("fixture", "leader")["run_id"] == data["run_id"]


def test_stop_keeps_a_window_with_a_person_pane_until_the_next_start_takes_it(session_env):
    env = session_env
    leader = env.manager().start("leader")
    user = add_pane(env, leader["window_id"])
    stopped = env.manager().control("stop", job="leader")
    assert stopped["released"] is True
    assert stopped["cleanup"]["closed"] == [] and stopped["cleanup"]["kept"][0]["reason"] == "window_shared"
    assert window_names(env) == [leader["window_id"] + " fixture-leader-exited-" + leader["run_id"][:8]]
    again = env.manager().start("leader")
    assert again["window_id"] == leader["window_id"] and again["run_id"] != leader["run_id"]
    assert panes(env, leader["window_id"]) == [leader["pane_id"], user]
    assert window_names(env) == [leader["window_id"] + " fixture-leader"]
    assert env.tmux.get_current("fixture", "leader")["run_id"] == again["run_id"]
    # Without a person's pane the window still closes at stop, as before.
    env.tmux.command("kill-pane", "-t", user)
    closed = env.manager().control("stop", job="leader")
    assert closed["cleanup"]["closed"] == [leader["window_id"]] and windows(env) == []


def test_the_seats_next_cr_takes_the_window_of_the_released_one(session_env):
    env = session_env
    first_cr = env.cr()
    first = env.manager().start(first_cr)
    user = add_pane(env, first["window_id"])
    env.finish(first_cr, state="done", outcome="waived", note="no change needed")
    stopped = env.manager().control("stop", job=first_cr)
    assert stopped["released"] is True and env.store.read()["0"] == EMPTY
    assert window_names(env) == [first["window_id"] + " fixture-seat0-" + first_cr + "-exited-" + first["run_id"][:8]]
    second_cr = env.cr(number=2)
    second = env.manager().start(second_cr)
    assert second["seat"] == 0 and second["window_id"] == first["window_id"]
    assert panes(env, first["window_id"]) == [first["pane_id"], user]
    assert window_names(env) == [first["window_id"] + " fixture-seat0-" + second_cr]
    meta = env.tmux.read_meta(first["window_id"])
    assert meta["job_id"] == second_cr and meta["run_id"] == second["run_id"]
    assert env.tmux.get_current("fixture", "seat-0")["run_id"] == second["run_id"]


@pytest.mark.parametrize("why", ["pending", "controller", "restored", "unconfirmed", "live"])
def test_a_window_that_is_not_surely_ended_is_left_and_a_new_one_opens(session_env, monkeypatch, why):
    from agent_session_fake_provider import FakeProvider
    from agent_session.process import birth

    env = session_env
    leader = env.manager().start("leader")
    user = add_pane(env, leader["window_id"])
    env.manager().control("stop", job="leader")
    meta = env.tmux.read_meta(leader["window_id"])
    if why == "pending":
        env.tmux.write_meta(leader["window_id"], {"control_pending": True})
    elif why == "controller":
        env.tmux.write_meta(leader["window_id"], {"controller_pid": os.getpid(), "controller_birth": birth(os.getpid())})
    elif why == "restored":                         # the window carries another server's identity
        env.tmux.command("set-option", "-w", "-t", leader["window_id"], "@agent_session_server_pid", "1")
    elif why == "unconfirmed":
        observe = FakeProvider.observe
        monkeypatch.setattr(FakeProvider, "observe", lambda self, session, context, meta=None, timeout=30: (
            {"known": False} if session["session_id"] == leader["session"]["session_id"]
            else observe(self, session, context, meta, timeout)))
    else:                                           # the managed pane lives again
        env.tmux.command("respawn-pane", "-t", leader["pane_id"], "sleep", "86400")
    again = env.manager().start("leader")
    assert again["window_id"] != leader["window_id"]
    assert leader["window_id"] in windows(env) and user in panes(env, leader["window_id"])
    assert window_names(env)[0] == leader["window_id"] + " fixture-leader-exited-" + leader["run_id"][:8]
    assert env.tmux.get_current("fixture", "leader")["run_id"] == again["run_id"]


def test_the_most_recent_runs_window_is_the_one_a_slot_takes(session_env, monkeypatch):
    import agent_session.lifecycle as lifecycle

    env = session_env
    cr = env.cr()
    with monkeypatch.context() as quiet:
        quiet.setattr(lifecycle.Manager, "_reusable", lambda self, target, ending=None: None)
        quiet.setattr(lifecycle.Manager, "_sweep", lambda self, target, owner=None: {"closed": [], "kept": []})
        first = env.manager().start(cr)
        env.handoff("seat-0", "Continue the fixture change.")
        second = env.manager().control("restart", job=cr)
        env.manager().control("stop", job=cr)
    assert first["window_id"] != second["window_id"] and len(windows(env)) == 2
    env.finish(cr, state="done", outcome="waived", note="no change needed")
    env.tmux.clear_current("fixture", "seat-0", second["run_id"])   # a release that left no pointer
    chosen = env.manager()._reusable("seat-0")
    assert chosen["window_id"] == second["window_id"]
    # A window whose newer run is the one that ended is the choice; an older one is not tried.
    os.utime(env.base / "agent/runs" / first["run_id"] / "launch.sh", (time.time() + 60, time.time() + 60))
    assert env.manager()._reusable("seat-0")["window_id"] == first["window_id"]


def test_a_run_of_the_retired_window_cannot_write_into_the_next_runs_values(session_env, monkeypatch):
    from agent_session import internal
    from agent_session.process import birth

    env = session_env
    first = env.manager().start("leader")
    old = env.tmux.read_meta(first["window_id"])
    env.handoff("leader", "Continue the Leader work.")
    restarted = env.manager().control("restart", job="leader")
    assert restarted["window_id"] == first["window_id"]
    before = env.tmux.read_meta(first["window_id"])
    project = env.manager().project
    # The callbacks have already matched the old run to the window when the window is handed over.
    monkeypatch.setattr(internal, "_run", lambda run_id, config_path, socket_path, cwd=None: (
        project, env.tmux, dict(old)))
    monkeypatch.setattr(env.tmux.__class__, "get_current", lambda self, project_id, target: dict(old))
    pane_pid = env.tmux.pane_info(old["pane_id"])["pane_pid"]
    with pytest.raises(SessionError) as error:
        internal.mark_process(old["run_id"], str(env.config), old["socket_path"], pane_pid)
    assert error.value.code == "target_changed"
    monkeypatch.setattr("agent_session.process.alive", lambda pid, fingerprint=None: True)
    with pytest.raises(SessionError) as error:
        internal._register(old["run_id"], str(env.config), old["socket_path"], old["session_id"],
                           old["endpoint"], cwd=old["cwd"])
    assert error.value.code == "target_changed"
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps({
        "session_id": old["session_id"], "hook_event_name": "Stop", "cwd": old["cwd"]})))
    with pytest.raises(SessionError) as error:
        internal.register_from_hook(old["run_id"], str(env.config), old["socket_path"], old["session_id"])
    assert error.value.code == "target_changed"
    manager = env.manager()
    manager.provider = type("Codex", (), {})()
    with pytest.raises(SessionError) as error:
        manager._record_background_clear({**old, "provider": "codex"}, {"known": True, "terminal": True,
                                                                         "latest_turn_id": "turn"})
    assert error.value.code == "target_changed"
    stopping = SessionError("fixture", "The fixture error.")
    manager._restore_stopping(old, stopping)
    assert stopping.details["stopping_restored"] is False and stopping.details["stopping_kept"] == "target_changed"
    assert env.tmux.read_meta(first["window_id"]) == before
