"""An explicit start seat never falls back to another local or remote workspace."""

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from agent_session_fixture import git, session_env
from agent_session import git_ops, remote, remote_lifecycle
from agent_session.errors import SessionError
from agent_session.state import locked


EMPTY = {"job_id": None, "git_hash": None, "session": None}


def test_explicit_remote_seat_is_chosen_while_an_earlier_local_seat_is_free(session_env, monkeypatch):
    env = session_env
    registry = json.loads(env.config.read_text())
    registry[str(env.base)]["seats"][1] = {"host": "macbook-worker", "path": str(env.seats[1])}
    env.config.write_text(json.dumps(registry))
    operations = []

    def ssh(seat, operation, payload=None, timeout=120):
        operations.append((seat.host, str(seat), operation))
        root = Path(str(seat))
        if operation == "ensure_seat":
            return False
        if operation == "is_git":
            return git_ops.is_git(root)
        if operation == "index_lock":
            lock = git_ops.index_lock(root)
            return str(lock) if lock else None
        assert operation == "git"
        return git_ops.git(root, *payload["args"], timeout=timeout)

    monkeypatch.setattr(remote, "call", ssh)
    monkeypatch.setattr(remote_lifecycle, "launch", lambda manager, context: manager._result(context))
    job = env.cr()
    result = env.manager().start(job, seat=1)
    assert result["seat"] == 1 and result["host"] == "macbook-worker"
    state = env.store.read()
    assert state["0"] == EMPTY and state["1"]["job_id"] == job
    assert git(env.seats[0], "branch", "--show-current") == "main"
    assert git(env.seats[0], "status", "--porcelain") == ""
    assert git(env.seats[1], "branch", "--show-current") == f"cr/{job}"
    assert operations and all(host == "macbook-worker" and path == str(env.seats[1])
                              for host, path, operation in operations)


def test_explicit_local_seat_and_same_seat_retry_preserve_the_assignment(session_env):
    env = session_env
    job = env.cr()
    started = env.manager().start(job, seat=1)
    repeated = env.manager().start(job, seat=1)
    assert started["seat"] == 1
    assert repeated["run_id"] == started["run_id"] and repeated["session"] == started["session"]
    assert env.store.read()["0"] == EMPTY


def test_an_explicit_seat_cannot_move_an_existing_job(session_env):
    env = session_env
    job = env.cr()
    started = env.manager().start(job, seat=1)
    before = env.store.read()
    with pytest.raises(SessionError) as error:
        env.manager().start(job, seat=0)
    assert error.value.code == "assignment_mismatch"
    assert env.store.read() == before
    assert env.tmux.get_current("fixture", "seat-1")["run_id"] == started["run_id"]


def test_occupied_explicit_seat_does_not_fall_back_to_a_free_seat(session_env):
    env = session_env
    env.manager().start(env.cr(), seat=1)
    other = env.cr(2)
    before = env.store.read()
    with pytest.raises(SessionError) as error:
        env.manager().start(other, seat=1)
    assert error.value.code == "no_available_seat"
    assert env.store.read() == before and env.cr_state(other)[0] == "todo"
    assert before["0"] == EMPTY


def test_busy_explicit_seat_does_not_fall_back_to_a_free_seat(session_env):
    env = session_env
    job = env.cr()
    with locked(env.base / "agent/control/seat-1.lock"):
        with pytest.raises(SessionError) as error:
            env.manager().start(job, seat=1)
    assert error.value.code == "no_available_seat"
    assert env.store.read(missing_ok=True)["0"] == EMPTY
    assert env.cr_state(job)[0] == "todo"


@pytest.mark.parametrize("seat", [-1, 2, True, "1"])
def test_invalid_explicit_seat_changes_no_assignment(session_env, seat):
    env = session_env
    job = env.cr()
    with pytest.raises(SessionError) as error:
        env.manager().start(job, seat=seat)
    assert error.value.code == "seat_invalid"
    assert env.cr_state(job)[0] == "todo"
    assert env.store.read(missing_ok=True)["0"] == EMPTY


START_RULES = [
    (["--job", "leader", "--seat", "0"], "--seat is only valid for a Worker JOB."),
    (["--job", "TOOL-001", "--prompt-file", "REQUEST.md"], "--prompt-file is only valid for --job leader."),
    (["--job", "TOOL-001", "--prompt-file", "REQUEST.md", "--seat", "9"], "--prompt-file is only valid for --job leader."),
]


@pytest.mark.parametrize("argv, message", START_RULES)
def test_start_argument_rules_belong_to_the_manager(session_env, argv, message):
    """The Manager enforces them, so the CLI and any other caller get the same error before an effect."""
    env = session_env
    job, prompt, seat = argv[1], None, None
    if "--prompt-file" in argv:
        prompt = argv[argv.index("--prompt-file") + 1]
    if "--seat" in argv:
        seat = int(argv[argv.index("--seat") + 1])
    with pytest.raises(SessionError) as error:
        env.manager().start(job, prompt_file=prompt, seat=seat)
    assert (error.value.code, error.value.exit_code, str(error.value)) == ("invalid_arguments", 2, message)
    assert not (env.base / "agent" / "state.json").exists() or env.store.read(missing_ok=True)["0"] == EMPTY


@pytest.mark.parametrize("argv, message", START_RULES)
def test_cli_start_reports_the_manager_rule(session_env, monkeypatch, capsys, argv, message):
    from agent_session import cli
    env = session_env
    monkeypatch.chdir(env.base)
    monkeypatch.delenv("AGENT_SESSION_UPLINK", raising=False)
    code = cli.main(["--config", str(env.config), "--socket-name", env.socket_name, "start", *argv])
    output = capsys.readouterr()
    assert code == 2 and not output.err
    assert json.loads(output.out) == {"ok": False, "data": None, "error": {
        "code": "invalid_arguments", "message": message, "details": {}}}


@pytest.mark.parametrize("argv, message", START_RULES)
def test_cli_start_rule_error_does_not_depend_on_the_project(tmp_path, monkeypatch, capsys, argv, message):
    """Outside every registered base the same bad request still gets the rule's error, not project_not_found."""
    from agent_session import cli
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_SESSION_UPLINK", raising=False)
    monkeypatch.delenv("AGENT_SESSION_CONFIG", raising=False)
    code = cli.main(["--config", str(tmp_path / "none.json"), "start", *argv])
    output = capsys.readouterr()
    assert code == 2 and not output.err
    assert json.loads(output.out) == {"ok": False, "data": None, "error": {
        "code": "invalid_arguments", "message": message, "details": {}}}
