"""A managed Claude conversation that moved to a background session, and a run whose CLI ended unregistered."""

import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from agent_session_fixture import session_env
from agent_session import process
from agent_session.errors import SessionError
from test_lifecycle import claude_project, wait_until

NEW = "ddfda1ec-803a-420d-897c-bd8444c16abd"


def background(monkeypatch, moved=NEW, host=None):
    """Make the provider report a move for every conversation and the given result for the host listing.

    `host` is a dict, or an exception to raise (a listing that cannot be read)."""
    from agent_session_fake_provider import FakeClaudeProvider

    monkeypatch.setattr(FakeClaudeProvider, "moved_to", lambda self, session_id: moved)

    def listing(self, session_id, cwd, timeout=8):
        if isinstance(host, Exception):
            raise host
        return host

    monkeypatch.setattr(FakeClaudeProvider, "background_host", listing)


def not_listed(monkeypatch):
    """ListAgents no longer shows the managed pane, as for a conversation that moved to the background."""
    from agent_session_fake_provider import FakeClaudeProvider

    def observe(self, session, context, meta=None, timeout=30):
        raise SessionError("session_not_bound", "Claude ListAgents does not identify one managed pane.", 3)

    monkeypatch.setattr(FakeClaudeProvider, "observe", observe)


def ended_pid():
    child = subprocess.Popen(["sleep", "0"])
    child.wait()
    return child.pid


def end_cli(env, meta):
    os.kill(meta["cli_pid"], signal.SIGTERM)
    wait_until(lambda: env.tmux.pane_info(meta["pane_id"])["pane_dead"])


def record(env, meta, pid=None, birth="linux:old-boot:1"):
    env.tmux.write_meta(meta["window_id"], {"run_id": meta["run_id"], "moved_to_background": {
        "old_session_id": meta["session_id"], "new_session_id": NEW, "host_pid": pid, "host_birth": birth,
        "detected_at": "2026-11-09T00:00:00Z"}})


def test_a_move_is_detected_from_the_transcript_when_the_listing_lost_the_pane(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    worker = env.manager().start(env.cr())
    old = env.tmux.get_current("fixture", "seat-0")["session_id"]
    background(monkeypatch, host={"listed": True, "pid": os.getpid()})
    not_listed(monkeypatch)
    with pytest.raises(SessionError) as error:
        env.manager().send(job=worker["job_id"], message="hello")
    assert error.value.code == "conversation_backgrounded"
    assert (error.value.details["old_session_id"], error.value.details["new_session_id"],
            error.value.details["host_pid"]) == (old, NEW, os.getpid())
    saved = env.tmux.get_current("fixture", "seat-0")["moved_to_background"]
    assert saved["new_session_id"] == NEW and saved["host_pid"] == os.getpid()


def test_without_a_transcript_move_a_lost_pane_stays_session_not_bound(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    worker = env.manager().start(env.cr())
    background(monkeypatch, moved=None)
    not_listed(monkeypatch)
    with pytest.raises(SessionError) as error:
        env.manager().control("stop", job=worker["job_id"])
    assert error.value.code == "session_not_bound"
    assert not env.tmux.get_current("fixture", "seat-0").get("moved_to_background")


def test_a_transcript_move_with_a_pane_still_listed_is_not_a_move(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    worker = env.manager().start(env.cr())
    background(monkeypatch)                 # a resumed conversation: the transcript ends with the move, the pane is listed
    assert env.manager().send(job=worker["job_id"], message="hello")["disposition"] == "accepted"
    assert not env.tmux.get_current("fixture", "seat-0").get("moved_to_background")


@pytest.mark.parametrize("operation", ["send", "restart", "stop", "review"])
def test_a_moved_run_gets_a_distinct_error_from_every_command(session_env, monkeypatch, operation):
    env = session_env
    claude_project(env, monkeypatch)
    env.manager().start("leader")
    worker = env.manager().start(env.cr())
    meta = env.tmux.get_current("fixture", "seat-0")
    background(monkeypatch, host={"listed": True, "pid": os.getpid()})
    record(env, meta, pid=os.getpid(), birth=process.birth(os.getpid()))
    manager = env.manager()
    with pytest.raises(SessionError) as error:
        {"send": lambda: manager.send(job=worker["job_id"], message="hello"),
         "restart": lambda: manager.control("restart", job=worker["job_id"]),
         "stop": lambda: manager.control("stop", job=worker["job_id"]),
         "review": lambda: manager.review(job=worker["job_id"])}[operation]()
    assert error.value.code == "conversation_backgrounded" and error.value.exit_code == 4
    assert (error.value.details["old_session_id"], error.value.details["new_session_id"],
            error.value.details["host_pid"]) == (meta["session_id"], NEW, os.getpid())
    assert env.tmux.get_current("fixture", "seat-0")["run_id"] == meta["run_id"]
    assert env.manager().store.read()["0"]["job_id"] == worker["job_id"]


def test_start_of_a_moved_leader_with_a_live_host_is_refused_and_changes_nothing(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    env.manager().start("leader")
    meta = env.tmux.get_current("fixture", "leader")
    background(monkeypatch, host={"listed": True, "pid": os.getpid()})
    record(env, meta, pid=os.getpid(), birth=process.birth(os.getpid()))
    before = env.manager().store.read()
    with pytest.raises(SessionError) as error:
        env.manager().start("leader")
    assert error.value.code == "conversation_backgrounded"
    assert env.manager().store.read() == before and env.tmux.get_current("fixture", "leader")["run_id"] == meta["run_id"]


@pytest.mark.parametrize("why", ["cli-alive", "host-unknown", "host-pid-alive", "cli-unknown"])
def test_a_moved_leader_is_kept_while_any_end_is_unconfirmed(session_env, monkeypatch, why):
    env = session_env
    claude_project(env, monkeypatch)
    env.manager().start("leader")
    meta = env.tmux.get_current("fixture", "leader")
    host_alive = {"listed": False, "pid": None}
    if why != "cli-alive":
        end_cli(env, meta)
    if why == "cli-unknown":
        env.tmux.write_meta(meta["window_id"], {"cli_pid": None})
    background(monkeypatch, host=host_alive if why != "host-unknown" else SessionError("provider_command_failed", "x", 5))
    pid = {"host-unknown": None, "host-pid-alive": os.getpid()}.get(why, ended_pid())
    record(env, meta, pid=pid, birth=process.birth(os.getpid()) if pid == os.getpid() else "linux:old-boot:1")
    before = env.manager().store.read()
    with pytest.raises(SessionError) as error:
        env.manager().start("leader")
    expected = "execution_unknown" if why in ("host-unknown", "cli-unknown") else "conversation_backgrounded"
    assert error.value.code == expected
    assert error.value.details["new_session_id"] == NEW
    assert env.manager().store.read() == before and env.tmux.get_current("fixture", "leader")["run_id"] == meta["run_id"]


def test_a_moved_leader_whose_conversation_and_cli_ended_starts_a_new_conversation(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    first = env.manager().start("leader")
    meta = env.tmux.get_current("fixture", "leader")
    end_cli(env, meta)
    background(monkeypatch, host={"listed": False, "pid": None})
    record(env, meta, pid=ended_pid())
    second = env.manager().start("leader")
    assert second["session"]["session_id"] != first["session"]["session_id"]
    assert env.manager().store.read()["leader"]["session_id"] == second["session"]["session_id"]
    assert env.tmux.get_current("fixture", "leader")["run_id"] != meta["run_id"]


def test_a_moved_worker_whose_conversation_and_cli_ended_restarts_on_its_seat(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    worker = env.manager().start(env.cr())
    meta = env.tmux.get_current("fixture", "seat-0")
    branch = env.cr_header(worker["job_id"], "Base")
    env.handoff("seat-0")
    end_cli(env, meta)
    background(monkeypatch, host={"listed": False, "pid": None})
    record(env, meta, pid=ended_pid())
    result = env.manager().control("restart", job=worker["job_id"])
    assert result["restarted"] is True and result["session"]["session_id"] != meta["session_id"]
    assert env.manager().store.read()["0"]["job_id"] == worker["job_id"]
    assert env.manager().store.read()["0"]["session"]["session_id"] == result["session"]["session_id"]
    assert env.cr_header(worker["job_id"], "Base") == branch
    assert env.tmux.get_current("fixture", "seat-0")["run_id"] != meta["run_id"]


def test_a_moved_worker_that_ended_can_be_stopped_and_started_again(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    cr = env.cr()
    worker = env.manager().start(cr)
    meta = env.tmux.get_current("fixture", "seat-0")
    end_cli(env, meta)
    background(monkeypatch, host={"listed": False, "pid": None})
    record(env, meta, pid=ended_pid())
    again = env.manager().start(cr)
    assert again["seat"] == worker["seat"] and again["session"]["session_id"] != meta["session_id"]


@pytest.mark.parametrize("target", ["leader", "worker"])
def test_a_run_that_ended_without_registering_is_replaced_by_the_next_start(session_env, monkeypatch, target):
    env = session_env
    cr = env.cr()
    start = (lambda: env.manager().start("leader")) if target == "leader" else (lambda: env.manager().start(cr))
    slot = "leader" if target == "leader" else "seat-0"
    first = start()
    meta = env.tmux.get_current("fixture", slot)
    end_cli(env, meta)
    env.tmux.write_meta(meta["window_id"], {"registered": False, "ready": False,
                                            "start_error": {"code": "session_not_bound", "message": "unlisted"}})
    second = start()
    assert second["session"]["session_id"] != first["session"]["session_id"]
    assert env.tmux.get_current("fixture", slot)["run_id"] != meta["run_id"]
    if target == "worker":
        assert second["seat"] == first["seat"] and env.manager().store.read()["0"]["job_id"] == cr


@pytest.mark.parametrize("why", ["cli-alive", "no-process-record"])
def test_a_run_that_may_still_run_unregistered_is_not_replaced(session_env, monkeypatch, why):
    env = session_env
    env.manager().start("leader")
    meta = env.tmux.get_current("fixture", "leader")
    updates = {"registered": False, "ready": False}
    if why == "no-process-record":
        end_cli(env, meta)
        updates.update(cli_pid=None, cli_birth=None, start_error={"code": "session_not_bound", "message": "x"})
    else:
        updates.update(start_error={"code": "session_not_bound", "message": "unlisted"})
    env.tmux.write_meta(meta["window_id"], updates)
    with pytest.raises(SessionError) as error:
        env.manager().start("leader")
    assert error.value.code in ("registration_failed", "leader_exists")
    assert env.tmux.get_current("fixture", "leader")["run_id"] == meta["run_id"]
