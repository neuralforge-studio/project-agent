"""Exercise lifecycle commands with real temporary Git and tmux resources and CR files as JOBs."""

import json
import os
from pathlib import Path
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from agent_session_fixture import git, session_env
from agent_session.errors import SessionError
from agent_session.state import locked


EMPTY = {"job_id": None, "git_hash": None, "session": None}


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
    assert state["leader"] == leader["session"]
    assert state["0"]["job_id"] == cr and state["0"]["git_hash"] == env.initial_hash
    assert state["0"]["session"] == worker["session"]
    assert state["1"] == EMPTY
    assert env.cr_state(cr)[0] == "in-progress"
    commit_time = git(env.seats[0], "show", "-s", "--format=%cI", "HEAD")
    assert env.cr_header(cr, "Base") == f"{env.initial_hash} {commit_time}"
    assert git(env.seats[0], "branch", "--show-current") == "cr/TOOL-001"
    prompt = (env.base / "agent/runs" / worker["run_id"] / "prompt.md").read_text()
    assert "배정 CR: TOOL-001" in prompt and "## Implementation" in prompt and "## Result" in prompt
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
    assert env.tmux.pane_info(worker["pane_id"])["pane_dead"]
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
    assert env.store.read()["0"]["session"] == worker["session"]


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
