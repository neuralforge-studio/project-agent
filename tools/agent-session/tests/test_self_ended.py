"""A managed CLI that ends by itself is wrapped up without a command (SESSION-007), with real tmux and Git."""

import json
import os
from pathlib import Path
import signal
import sys
import time

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(FIXTURES))
from agent_session_fixture import command_timeout, git, session_env  # noqa: F401,E402  (pytest fixture)
from agent_session import ended  # noqa: E402
from agent_session.errors import SessionError  # noqa: E402
from agent_session.state import control_lock  # noqa: E402
from agent_session.tmux import EXIT_HOOK, Tmux  # noqa: E402
from test_lifecycle import EMPTY, add_pane, claude_project, panes, windows  # noqa: E402

LIBRARY = Path(__file__).resolve().parents[1]


def fixture_hook(monkeypatch, kind="codex"):
    """Install the server's pane-died hook with the fixture provider (the real hook runs the real provider)."""
    def install(self, python, library):
        shell = (f"exec {sys.executable} {FIXTURES / 'agent_session_finish_hook.py'} {library} {FIXTURES} {kind} "
                 "#{socket_path} #{window_id} #{pane_id} >/dev/null 2>&1")
        command = ("if-shell -F '#{==:#{@agent_session_pane_id},\"#{pane_id}\"}' 'run-shell -b \"" + shell + "\"'")
        self._run("set-hook", "-g", EXIT_HOOK, command)
        return True
    monkeypatch.setattr(Tmux, "install_exit_hook", install)


def result_file(env, run_id):
    return env.base / "agent" / "runs" / run_id / "finish-result.json"


def finished(env, run_id, limit=30):
    """The wrap-up's saved result, once the server's hook ran it."""
    path = result_file(env, run_id)
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        time.sleep(0.1)
    raise AssertionError("The pane-died hook left no result.")


def type_exit(env, pane_id):
    env.tmux.command("send-keys", "-t", pane_id, "/exit", "Enter")


def kill_cli(env, window_id):
    os.kill(env.tmux.read_meta(window_id)["cli_pid"], signal.SIGKILL)


def test_a_leader_that_exits_is_released_and_its_window_closed_without_a_command(session_env, monkeypatch):
    env = session_env
    fixture_hook(monkeypatch)
    leader = env.manager().start("leader")
    type_exit(env, leader["pane_id"])
    result = finished(env, leader["run_id"])
    assert result["ok"] is True and result["data"]["finished"] is True and result["data"]["released"] is True
    assert windows(env) == []                       # the server's last window closed too, so the wrap-up ran to its end
    assert env.store.read()["leader"] is None
    record = json.loads(ended.path(env.project, leader["run_id"]).read_text(encoding="utf-8"))
    assert record["run_id"] == leader["run_id"] and record["target"] == "leader" and record["basis"] == "provider"
    assert record["cli_pid"] and record["cli_birth"]


def test_the_real_hook_starts_the_wrap_up_for_a_crashed_cli(session_env):
    """The generated hook command itself (no fixture provider): the server ran it and it saved what it found."""
    env = session_env
    worker = env.manager().start(env.cr())
    assert EXIT_HOOK in env.tmux.command("show-hooks", "-g", "pane-died")
    kill_cli(env, worker["window_id"])
    result = finished(env, worker["run_id"])
    # The real provider cannot see the fixture CLI, so the wrap-up may leave the run; what counts is that it ran.
    assert result["ok"] is True and result["data"]["finished"] in (True, False)


def test_a_worker_whose_cr_is_not_in_progress_is_released_and_its_window_closed(session_env, monkeypatch):
    env = session_env
    fixture_hook(monkeypatch)
    cr = env.cr()
    worker = env.manager().start(cr)
    env.finish(cr, state="done", outcome="waived", note="no change needed")
    kill_cli(env, worker["window_id"])                      # a crash: no /exit and no SessionEnd
    result = finished(env, worker["run_id"])
    assert result["data"]["finished"] is True and result["data"]["released"] is True
    assert env.store.read()["0"] == EMPTY
    assert env.tmux.managed_windows("fixture", "seat-0") == [] and env.tmux.get_current("fixture", "seat-0") is None


def test_a_persons_pane_in_the_window_stays_when_a_run_ends_itself(session_env, monkeypatch):
    env = session_env
    fixture_hook(monkeypatch)
    cr = env.cr()
    worker = env.manager().start(cr)
    user = add_pane(env, worker["window_id"])
    env.finish(cr, state="done", outcome="waived", note="no change needed")
    type_exit(env, worker["pane_id"])
    result = finished(env, worker["run_id"])
    assert result["data"]["cleanup"]["pane_closed"] == [worker["window_id"]]
    assert panes(env, worker["window_id"]) == [user]
    assert env.tmux.managed_windows("fixture", "seat-0") == []


def test_a_run_whose_cr_is_in_progress_holds_its_release_until_the_cr_moves(session_env, monkeypatch):
    env = session_env
    fixture_hook(monkeypatch)
    cr = env.cr()
    worker = env.manager().start(cr)
    type_exit(env, worker["pane_id"])
    result = finished(env, worker["run_id"])
    assert result["data"]["finished"] is True and result["data"]["released"] is False
    meta = env.tmux.get_current("fixture", "seat-0")
    assert meta["run_id"] == worker["run_id"] and meta["release_pending"]["reasons"] and meta["stopping"] is True
    assert env.store.read()["0"]["job_id"] == cr
    assert env.manager().pending_releases()[cr]["seat"] == 0
    env.finish(cr, state="todo", outcome=None, note="paused")
    finishing = env.manager().finish_release(cr)
    assert finishing["released"] is True               # the seat is clean and its HEAD is on origin
    assert env.store.read()["0"] == EMPTY and windows(env) == []


def test_a_second_wrap_up_of_the_same_run_changes_nothing(session_env, monkeypatch):
    env = session_env
    fixture_hook(monkeypatch)
    cr = env.cr()
    worker = env.manager().start(cr)
    type_exit(env, worker["pane_id"])
    first = finished(env, worker["run_id"])
    assert first["data"]["finished"] is True
    again = env.manager().finish_ended(worker["run_id"], "seat-0", worker["pane_id"])
    assert again == {"finished": False, "reason": "control_active"}      # stopping is already recorded


def test_the_wrap_up_leaves_a_run_to_the_command_that_controls_it(session_env, monkeypatch):
    import agent_session.lifecycle as lifecycle

    env = session_env
    cr = env.cr()
    worker = env.manager().start(cr)
    kill_cli(env, worker["window_id"])
    time.sleep(0.5)
    monkeypatch.setattr(lifecycle, "FINISH_LOCK_SECONDS", 0.2)
    with control_lock(env.project, "seat-0", 5):             # a stop or restart holds the slot's control lock
        busy = env.manager().finish_ended(worker["run_id"], "seat-0", worker["pane_id"])
    assert busy["finished"] is False and busy["reason"]
    assert env.store.read()["0"]["job_id"] == cr and not ended.path(env.project, worker["run_id"]).exists()
    env.tmux.write_meta(worker["window_id"], {"run_id": worker["run_id"], "control_pending": True})
    assert env.manager().finish_ended(worker["run_id"], "seat-0", worker["pane_id"]) == {
        "finished": False, "reason": "control_active"}
    env.tmux.write_meta(worker["window_id"], {"run_id": worker["run_id"], "control_pending": False, "stopping": True})
    assert env.manager().finish_ended(worker["run_id"], "seat-0", worker["pane_id"])["reason"] == "control_active"


def test_a_run_that_is_no_longer_current_or_not_published_is_not_wrapped_up(session_env):
    env = session_env
    worker = env.manager().start(env.cr())
    manager = env.manager()
    assert manager.finish_ended("0" * 32, "seat-0", worker["pane_id"]) == {"finished": False, "reason": "not_current"}
    assert manager.finish_ended(worker["run_id"], "seat-0", "%999") == {"finished": False, "reason": "not_current"}
    # The CLI lives: its pane is not dead, so nothing is confirmed ended.
    assert manager.finish_ended(worker["run_id"], "seat-0", worker["pane_id"]) == {
        "finished": False, "reason": "termination_unconfirmed"}
    assert env.store.read()["0"]["job_id"] == worker["job_id"]


def test_a_crashed_claude_cli_is_confirmed_from_its_processes_when_the_provider_cannot_tell(session_env, monkeypatch):
    env = session_env
    claude_project(env, monkeypatch)
    fixture_hook(monkeypatch, "claude")
    cr = env.cr()
    worker = env.manager().start(cr)
    # The last Stop report named a background task and no SessionEnd came: the provider never says "ended".
    (env.base / "agent" / "fixture-background-seat-0").write_text("")
    kill_cli(env, worker["window_id"])
    result = finished(env, worker["run_id"])
    assert result["data"]["finished"] is True and result["data"]["basis"] == "process"
    # stop, restart and the window cleanup now read the record, not the dead pane's provider report
    meta = env.tmux.get_current("fixture", "seat-0")
    assert ended.confirms(env.project, meta) and env.manager()._observe(meta)["stopped"] is True
    stopped = env.manager().control("stop", job=cr)
    assert stopped["stopped"] is True and stopped["released"] is False
    env.handoff("seat-0", "continue")
    restarted = env.manager().control("restart", job=cr)
    assert restarted["restarted"] is True and restarted["run_id"] != worker["run_id"]


def test_a_claude_cli_that_still_has_a_live_process_group_is_not_confirmed(session_env, monkeypatch):
    import agent_session.lifecycle as lifecycle

    env = session_env
    claude_project(env, monkeypatch)
    monkeypatch.setattr(lifecycle, "FINISH_END_SECONDS", 1)
    cr = env.cr()
    worker = env.manager().start(cr)
    (env.base / "agent" / "fixture-background-seat-0").write_text("")
    kill_cli(env, worker["window_id"])
    meta = env.tmux.read_meta(worker["window_id"])
    manager = env.manager()
    monkeypatch.setattr(lifecycle.Manager, "_process_facts", staticmethod(lambda meta, pane: (False, True, False)))
    time.sleep(0.5)
    assert manager.finish_ended(worker["run_id"], "seat-0", worker["pane_id"]) == {
        "finished": False, "reason": "termination_unconfirmed"}
    assert not ended.path(env.project, worker["run_id"]).exists()


def test_the_hook_keeps_the_hooks_of_a_persons_configuration(session_env):
    env = session_env
    env.manager().start("leader")
    mark = env.root / "persons-hook-ran"
    env.tmux.command("set-hook", "-g", "pane-died[person]", f"run-shell 'touch {mark}'")
    worker_cr = env.cr()
    worker = env.manager().start(worker_cr)
    hooks = env.tmux.command("show-hooks", "-g", "pane-died")
    assert "pane-died[person]" in hooks and EXIT_HOOK in hooks
    kill_cli(env, worker["window_id"])
    deadline = time.monotonic() + 10
    while not mark.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert mark.exists()
