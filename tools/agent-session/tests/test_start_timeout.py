"""A start that runs out of its total wait limit says where it stopped, and the same start continues (SESSION-014).

fc2_cpu saw `start` end with a bare "total wait limit expired" after its Git preparation took the whole
limit: the preparation's steps run on their own 600 s limits and never looked at the command's deadline, so a
slow seat ran every step and the command failed only when it reached the launch."""

from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from agent_session_fixture import git, session_env
from agent_session import git_ops
import agent_session.lifecycle as lifecycle
from agent_session.errors import SessionError


def expire_during(monkeypatch, manager, word):
    """The command's deadline passes while its Git runs the first command that has `word` as its subcommand.

    Returns the list of every Git command line that was started."""
    started = []
    real = git_ops._argv

    def argv(root, *args):
        started.append(" ".join(args))
        if args and args[0] == word:
            manager.end = time.monotonic()
        return real(root, *args)

    monkeypatch.setattr(git_ops, "_argv", argv)
    return started


def test_git_preparation_stops_at_the_deadline_and_names_its_step(session_env, monkeypatch):
    env = session_env
    job = env.cr()
    manager = env.manager()
    started = expire_during(monkeypatch, manager, "fetch")
    with pytest.raises(SessionError) as error:
        manager.start(job)
    err = error.value
    assert (err.code, err.exit_code) == ("timeout", 4)
    assert err.details["stage"] == "git"
    assert err.details["step"].startswith("merge --ff-only")
    assert err.details["retry_safe"] is True
    assert (err.details["job_id"], err.details["seat"]) == (job, 0)
    assert [item["step"] for item in err.details["git_steps"]][-1] == "fetch origin main"
    assert "git" in err.details["elapsed"] and "assignment" in err.details["elapsed"]
    # No Git command was started after the deadline: nothing runs on, and nothing is half applied.
    assert not any(line.startswith(("merge", "switch -c", "switch --no-overwrite-ignore -c", "submodule"))
                   for line in started[started.index("fetch origin main"):])
    assert git(env.seats[0], "status", "--porcelain") == ""

    # The seat, the CR and the waiting window stay, and the same start continues them.
    window = env.tmux.get_current("fixture", "seat-0")
    assert window["job_id"] == job and not window.get("registered")
    assert env.store.read()["0"]["job_id"] == job
    result = env.manager().start(job)
    assert result["seat"] == 0 and result["run_id"] == window["run_id"]
    assert result["window_id"] == window["window_id"]
    assert git(env.seats[0], "branch", "--show-current") == f"cr/{job}"
    assert env.cr_state(job)[0] == "in-progress"


def test_timeout_while_waiting_for_the_registration_names_that_stage(session_env, monkeypatch):
    from agent_session_fake_provider import FakeProvider

    class Held(FakeProvider):
        manager = None

        def startup_dialog(self, screen):
            self.manager.end = time.monotonic()
            return None

    provider = Held(dialog=True)
    monkeypatch.setattr(lifecycle, "get_provider", lambda name: provider)
    env = session_env
    first = env.manager()
    provider.manager = first
    with pytest.raises(SessionError) as error:
        first.start("leader")
    err = error.value
    assert err.code == "timeout"
    assert err.details["stage"] == "registration" and err.details["retry_safe"] is True
    assert "registration" in err.details["elapsed"]
    window = env.tmux.get_current("fixture", "leader")

    second = env.manager()
    provider.manager = second
    with pytest.raises(SessionError) as again:
        second.start("leader")                       # takes over the same run instead of opening another
    assert again.value.details["stage"] == "registration"
    assert env.tmux.get_current("fixture", "leader")["run_id"] == window["run_id"]
