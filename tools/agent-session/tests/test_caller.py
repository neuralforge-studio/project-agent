"""The caller rule shared with project-item: real tmux runs decide who may move an in-progress CR."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from agent_session_fixture import git, session_env  # noqa: F401
from agent_session import api
from project_item.cli import main


def move(env, capsys, *args):
    code = main(["move", "--config", str(env.config), "--project", "fixture", *args])
    out = capsys.readouterr()
    return code, out.err


def test_caller_names_the_slot_of_each_conversation(session_env, monkeypatch):
    env = session_env
    leader = env.manager().start("leader")
    worker = env.manager().start(env.cr())
    monkeypatch.setenv("AGENT_SESSION_SOCKET", env.tmux.effective_socket())
    for session, slot in ((leader["session"], "leader"), (worker["session"], "seat-0")):
        monkeypatch.setenv("CODEX_THREAD_ID", session["session_id"])
        assert api.caller(env.project) == (slot, session["session_id"])
        api.require_live(env.project, slot, session["session_id"])
    monkeypatch.setenv("CODEX_THREAD_ID", "someone-else")
    assert api.caller(env.project) == ("unmanaged-agent", "someone-else")
    monkeypatch.delenv("CODEX_THREAD_ID")
    assert api.caller(env.project) == ("operator", None)


def test_only_the_leader_and_an_operator_move_an_in_progress_cr(session_env, monkeypatch, capsys):
    env = session_env
    leader = env.manager().start("leader")
    cr = env.cr()
    worker = env.manager().start(cr)
    monkeypatch.setenv("AGENT_SESSION_SOCKET", env.tmux.effective_socket())
    path = env.cr_state(cr)[1]
    before = path.read_text()
    for who in (worker["session"]["session_id"], "unregistered-agent"):
        monkeypatch.setenv("CODEX_THREAD_ID", who)
        code, err = move(env, capsys, cr, "todo")
        assert code == 2 and "role_denied" in err
        assert path.read_text() == before and env.cr_state(cr)[0] == "in-progress"
    monkeypatch.setenv("CODEX_THREAD_ID", leader["session"]["session_id"])
    assert move(env, capsys, cr, "todo")[0] == 0
    assert env.cr_state(cr)[0] == "todo"
