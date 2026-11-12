"""The tmux that project-agent runs is the installer's record (TMUX-004), never the PATH of the caller.

The record is `tools/tmux.env` of a release (`agent_session/tmux_program.py`); a tree without it is a development
checkout, which runs the `tmux` in PATH. `tools/project-board/tests/test_tmux_record.py` holds the Python, shell and
Rust readers to the same answers; these tests are about what `agent-session` does with the answer."""

import os
import shlex

import pytest

from agent_session import tmux as tmux_module, tmux_program
from agent_session.errors import SessionError
from agent_session.tmux import Tmux, quiet_shell


@pytest.fixture
def record(tmp_path, monkeypatch):
    """Write the record of the tree under test: `write(text)`; the tree has none until it is called."""
    path = tmp_path / "tmux.env"
    monkeypatch.setattr(tmux_program, "RECORD", path)
    monkeypatch.delenv(tmux_program.PROGRAM_NAME, raising=False)
    monkeypatch.delenv(tmux_program.LIBRARY_NAME, raising=False)
    tmux_program._record.cache_clear()

    def write(text):
        path.write_text(text)
        tmux_program._record.cache_clear()

    yield write
    tmux_program._record.cache_clear()


def stub(directory, body, name="tmux"):
    path = directory / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def test_a_tree_without_a_record_runs_the_tmux_in_path(record):
    assert tmux_program.settings() == ("tmux", "")
    assert tmux_program.environment() is None
    assert Tmux(socket_name="x")._argv(["list-windows"]) == ["tmux", "-L", "x", "list-windows"]


def test_the_record_names_the_program_and_the_library_and_the_caller_s_path_does_not_matter(record, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    stub(elsewhere, "echo wrong")
    monkeypatch.setenv("PATH", f"{elsewhere}:{os.environ['PATH']}")
    recorded = stub(tmp_path, 'echo "$LD_LIBRARY_PATH|$*"', name="recorded-tmux")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/already")
    record(f"PROJECT_AGENT_TMUX={recorded}\nPROJECT_AGENT_TMUX_LD_LIBRARY_PATH=/lib/one:/lib/two\n")
    assert tmux_program.settings() == (str(recorded), "/lib/one:/lib/two")
    assert Tmux(socket_path=str(tmp_path / "s")).command("list-windows") == f"/lib/one:/lib/two:/already|-S {tmp_path / 's'} list-windows"


def test_an_environment_value_wins_over_the_record_name_by_name(record, monkeypatch):
    record("PROJECT_AGENT_TMUX=/rec/tmux\nPROJECT_AGENT_TMUX_LD_LIBRARY_PATH=/rec/lib\n")
    monkeypatch.setenv(tmux_program.PROGRAM_NAME, "/env/tmux")
    assert tmux_program.settings() == ("/env/tmux", "/rec/lib")
    monkeypatch.setenv(tmux_program.PROGRAM_NAME, "")                       # empty is no value
    monkeypatch.setenv(tmux_program.LIBRARY_NAME, "/env/lib")
    assert tmux_program.settings() == ("/rec/tmux", "/env/lib")


def test_a_record_that_names_no_tmux_refuses_with_a_named_error(record):
    record("PROJECT_AGENT_TMUX=\nPROJECT_AGENT_TMUX_LD_LIBRARY_PATH=\n")
    with pytest.raises(SessionError) as error:
        Tmux().command("list-windows")
    assert (error.value.code, error.value.exit_code) == ("tmux_unavailable", 5)


def test_a_recorded_tmux_that_is_gone_refuses_with_a_named_error_and_names_it(record, tmp_path):
    gone = tmp_path / "gone" / "tmux"
    record(f"PROJECT_AGENT_TMUX={gone}\n")
    with pytest.raises(SessionError) as error:
        Tmux().command("list-windows")
    assert (error.value.code, error.value.exit_code) == ("tmux_unavailable", 5)
    assert error.value.details == {"program": str(gone)}


def test_the_version_check_runs_the_recorded_tmux_when_no_server_answers(record, tmp_path, monkeypatch):
    old = stub(tmp_path, '[ "$1" = "-V" ] && echo "tmux 2.7"\necho "no server running" >&2\nexit 1\n')
    new = stub(tmp_path, '[ "$1" = "-V" ] && echo "tmux 3.8"\necho "no server running" >&2\nexit 1\n', name="new-tmux")
    wrong = tmp_path / "wrong"
    wrong.mkdir()
    stub(wrong, '[ "$1" = "-V" ] && echo "tmux 2.7"\necho "no server running" >&2\nexit 1\n')
    monkeypatch.setenv("PATH", f"{wrong}:{os.environ['PATH']}")             # the first tmux in PATH is too old
    record(f"PROJECT_AGENT_TMUX={new}\n")
    Tmux(socket_name="version-test").require_version()
    record(f"PROJECT_AGENT_TMUX={old}\n")
    with pytest.raises(SessionError) as error:
        Tmux(socket_name="version-test").require_version()
    assert error.value.code == "tmux_too_old" and error.value.details["program"] == str(old)


def test_a_job_text_runs_the_recorded_tmux_and_quotes_a_path_a_shell_would_split(record, tmp_path):
    record("PROJECT_AGENT_TMUX=/opt/tmux/bin/tmux\n")
    assert "; /opt/tmux/bin/tmux -S /s set-option" in quiet_shell("exit 5", "job", "/s")
    record("PROJECT_AGENT_TMUX=/opt/my tmux/tmux\n")
    assert f"; {shlex.quote('/opt/my tmux/tmux')} -S /s set-option" in quiet_shell("exit 5", "job", "/s")


def test_the_exit_hook_is_not_written_when_the_recorded_tmux_cannot_be_carried_by_it(record, tmp_path):
    record("PROJECT_AGENT_TMUX=/opt/my tmux/tmux\n")
    assert Tmux(socket_name="hook-test").install_exit_hook("/py/python3", "/lib") is False


def test_the_remote_display_command_and_the_remote_runtime_share_one_path():
    from agent_session import remote
    assert remote.REMOTE_PATH == ("$HOME/.local/bin", "/opt/homebrew/bin")
    assert ":".join(remote.REMOTE_PATH) + ":" in remote.BOOTSTRAP
    assert "@REMOTE_PATH@" not in remote.BOOTSTRAP
    compile(remote.BOOTSTRAP, "<bootstrap>", "exec")
