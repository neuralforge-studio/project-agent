import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_session.config import Project
from agent_session.errors import SessionError
from agent_session.state import StateStore, empty_state, locked


def project(tmp_path, provider="codex", count=2):
    base = tmp_path / "main"
    base.mkdir(exist_ok=True)
    return Project(base, str(base), "demo", provider,
                   tuple(tmp_path / f"seat{n}" for n in range(count)), tmp_path / "project.json")


def test_read_only_missing_state_and_exact_root_shape(tmp_path):
    value = project(tmp_path)
    store = StateStore(value)
    assert store.read(missing_ok=True) == {"leader": None, "0": {"job_id": None, "git_hash": None, "session": None},
                                          "1": {"job_id": None, "git_hash": None, "session": None}}
    assert not value.runtime_path.exists()
    with pytest.raises(SessionError) as error:
        store.read()
    assert error.value.code == "state_not_found"
    assert not value.runtime_path.exists()


def test_update_preserves_other_assignments_and_connection(tmp_path):
    value = project(tmp_path)
    store = StateStore(value)
    store.update(lambda state: state["0"].update(job_id="J-20261103-01"))
    store.update(lambda state: state["1"].update(job_id="J-20261103-02", git_hash="a" * 64))
    connection = {"session_id": "native-id", "endpoint": "unix:///tmp/test.sock"}
    result = store.update(lambda state: state.update(leader=connection))
    assert result["0"]["job_id"] == "J-20261103-01"
    assert result["1"]["git_hash"] == "a" * 64
    assert result["leader"] == connection
    assert store.read() == result
    assert not tuple(value.runtime_path.glob(".state.*.tmp"))


def test_claude_connection_has_exact_transport_fields(tmp_path):
    value = project(tmp_path, "claude", 0)
    store = StateStore(value)
    expected = {"leader": {"session_id": "uuid", "message_to": "worker [123abc]"}}
    assert store.update(lambda state: expected) == expected
    with pytest.raises(SessionError):
        store.update(lambda state: state.update(leader={"session_id": "uuid", "endpoint": "unix:///a"}))
    assert store.read() == expected


@pytest.mark.parametrize("raw", ["{broken", '{"leader":null,"leader":null}', '{"leader":null}',
                                       '{"leader":null,"0":{"job_id":null,"git_hash":"a","session":null}}'])
def test_damaged_state_is_not_replaced(tmp_path, raw):
    value = project(tmp_path, count=1)
    value.runtime_path.mkdir()
    value.state_path.write_text(raw)
    with pytest.raises(SessionError):
        StateStore(value).update(lambda state: empty_state(value))
    assert value.state_path.read_text() == raw


def test_conflicting_jobs_and_unassigned_data_are_rejected(tmp_path):
    store = StateStore(project(tmp_path))
    store.update(lambda state: state["0"].update(job_id="J-20261103-01"))
    with pytest.raises(SessionError):
        store.update(lambda state: state["1"].update(job_id="J-20261103-01"))
    with pytest.raises(SessionError):
        store.update(lambda state: state["1"].update(git_hash="f" * 40))
    assert store.read()["1"] == {"job_id": None, "git_hash": None, "session": None}


def test_process_updates_merge_instead_of_losing_seats(tmp_path):
    value = project(tmp_path, count=4)
    value.config_path.write_text(json.dumps({str(value.base): {"project": "demo", "provider": "codex",
                                                            "seats": [str(p) for p in value.seats]}}))
    code = """import sys
sys.path.insert(0, sys.argv[1])
from agent_session.config import resolve_project
from agent_session.state import StateStore
store = StateStore(resolve_project(sys.argv[2], sys.argv[3]))
store.update(lambda state: state[sys.argv[4]].update(job_id='J-20261103-'+sys.argv[4]))
"""
    children = [subprocess.Popen([sys.executable, "-c", code, str(Path(__file__).resolve().parents[1]),
                                  str(value.base), str(value.config_path), str(n)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for n in range(4)]
    for child in children:
        _, error = child.communicate(timeout=20)
        assert child.returncode == 0, error
    assert [StateStore(value).read()[str(n)]["job_id"] for n in range(4)] == [f"J-20261103-{n}" for n in range(4)]


def test_lock_wait_is_bounded_and_file_is_retained(tmp_path):
    path = tmp_path / "control.lock"
    with locked(path):
        with pytest.raises(SessionError) as error:
            with locked(path, blocking=False):
                pass
        assert error.value.code == "control_busy"
        with pytest.raises(SessionError) as error:
            with locked(path, timeout=0.01):
                pass
        assert error.value.code == "lock_timeout"
    with locked(path, blocking=False):
        assert path.exists()


def test_state_update_uses_its_remaining_timeout(tmp_path):
    store = StateStore(project(tmp_path), timeout=0.01)
    with locked(store.lock_path):
        with pytest.raises(SessionError) as error:
            store.update(lambda state: state)
    assert error.value.code == "lock_timeout"
    assert not store.path.exists()
