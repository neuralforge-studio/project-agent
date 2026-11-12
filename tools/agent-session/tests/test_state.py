import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_session.config import Project
from agent_session.errors import SessionError
from agent_session.state import StateStore, binding_identity, empty_state, locked
from wait_limit import command_timeout


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


UNASSIGNED = {"job_id": None, "git_hash": None, "session": None}


@pytest.mark.parametrize("raw", ["{broken", '{"leader":null,"leader":null}',
                                 '{"leader":null,"0":{"job_id":null,"git_hash":"a","session":null}}',
                                 '{"leader":null,"1":{"job_id":null,"git_hash":null,"session":null}}',
                                 '{"leader":null,"0":{"job_id":null,"git_hash":null,"session":null},"x":null}',
                                 '{"leader":null,"0":{"job_id":null}}'])
def test_damaged_state_is_not_replaced(tmp_path, raw):
    value = project(tmp_path, count=1)
    value.runtime_path.mkdir()
    value.state_path.write_text(raw)
    with pytest.raises(SessionError):
        StateStore(value).update(lambda state: empty_state(value))
    assert value.state_path.read_text() == raw


def write_state(value, rows):
    value.runtime_path.mkdir(exist_ok=True)
    value.state_path.write_text(json.dumps({"leader": None, **rows}))


def test_added_registry_seat_reads_as_unassigned_and_is_saved_on_next_write(tmp_path):
    held = {"job_id": "J-1", "git_hash": "a" * 40, "session": None}
    write_state(project(tmp_path, count=2), {"0": held, "1": UNASSIGNED})
    grown = project(tmp_path, count=3)
    store = StateStore(grown)
    assert store.read() == {"leader": None, "0": held, "1": UNASSIGNED, "2": UNASSIGNED}
    assert "2" not in json.loads(grown.state_path.read_text())
    store.update(lambda state: state["2"].update(job_id="J-2"))
    saved = json.loads(grown.state_path.read_text())
    assert saved["0"] == held and saved["2"]["job_id"] == "J-2"


def test_removed_registry_seat_is_dropped_only_when_unassigned(tmp_path):
    held = {"job_id": "J-1", "git_hash": None, "session": None}
    write_state(project(tmp_path, count=3), {"0": held, "1": UNASSIGNED, "2": UNASSIGNED})
    shrunk = project(tmp_path, count=2)
    store = StateStore(shrunk)
    assert store.read() == {"leader": None, "0": held, "1": UNASSIGNED}
    store.update(lambda state: None)
    assert set(json.loads(shrunk.state_path.read_text())) == {"leader", "0", "1"}

    write_state(shrunk, {"0": held, "1": UNASSIGNED, "2": held | {"job_id": "J-2"}})
    raw = shrunk.state_path.read_text()
    for call in (lambda: store.read(), lambda: store.update(lambda state: None)):
        with pytest.raises(SessionError) as error:
            call()
        assert error.value.code == "state_invalid" and error.value.details == {"seat": 2}
    assert shrunk.state_path.read_text() == raw


def test_removed_registry_seat_with_broken_row_is_rejected(tmp_path):
    write_state(project(tmp_path, count=3), {"0": UNASSIGNED, "1": UNASSIGNED, "2": {"job_id": None}})
    with pytest.raises(SessionError) as error:
        StateStore(project(tmp_path, count=2)).read()
    assert error.value.details == {"seat": 2}


def test_conflicting_jobs_and_unassigned_data_are_rejected(tmp_path):
    store = StateStore(project(tmp_path))
    store.update(lambda state: state["0"].update(job_id="J-20261103-01"))
    with pytest.raises(SessionError):
        store.update(lambda state: state["1"].update(job_id="J-20261103-01"))
    with pytest.raises(SessionError):
        store.update(lambda state: state["1"].update(git_hash="f" * 40))
    assert store.read()["1"] == {"job_id": None, "git_hash": None, "session": None}



CONNECTION = {"session_id": "native-id", "endpoint": "unix:///tmp/test.sock"}


def test_connection_time_is_optional_but_exact(tmp_path):
    store = StateStore(project(tmp_path))
    legacy = store.update(lambda state: state.update(leader=dict(CONNECTION)))
    assert legacy["leader"] == CONNECTION
    timed = {**CONNECTION, "connected_at": "2026-11-04T09:12:30Z"}
    assert store.update(lambda state: state.update(leader=timed))["leader"] == timed
    for bad in ("2026-11-04 09:12:30", "2026-11-04T09:12:30+09:00", "2026-13-04T09:12:30Z", 1793785072):
        with pytest.raises(SessionError) as error:
            store.update(lambda state: state.update(leader={**CONNECTION, "connected_at": bad}))
        assert error.value.code == "state_invalid"
    assert store.read()["leader"] == timed


def test_review_mark_is_leader_only_and_names_an_assigned_job(tmp_path):
    store = StateStore(project(tmp_path))
    store.update(lambda state: state["0"].update(job_id="TOOL-013", session=dict(CONNECTION, session_id="worker")))
    marked = store.update(lambda state: state.update(leader={**CONNECTION, "reviewing": "TOOL-013"}))
    assert marked["leader"]["reviewing"] == "TOOL-013"
    rejected = [
        lambda state: state["leader"].update(reviewing="TOOL-099"),
        lambda state: state["leader"].update(reviewing="leader"),
        lambda state: state["leader"].update(reviewing=""),
        lambda state: state["0"].update(job_id=None, session=None),
        lambda state: state["0"]["session"].update(reviewing="TOOL-013"),
    ]
    for mutation in rejected:
        with pytest.raises(SessionError) as error:
            store.update(mutation)
        assert error.value.code == "state_invalid"
    assert store.read() == marked
    store.update(lambda state: state["0"].update(session=None))
    assert store.read()["leader"]["reviewing"] == "TOOL-013"


def test_connection_identity_ignores_review_and_time_but_not_the_address():
    codex = {**CONNECTION, "connected_at": "2026-11-04T09:12:30Z", "reviewing": "TOOL-013"}
    assert binding_identity(codex, "codex") == binding_identity(CONNECTION, "codex")
    assert binding_identity(dict(CONNECTION, endpoint="unix:///other"), "codex") != binding_identity(CONNECTION, "codex")
    claude = {"session_id": "uuid", "message_to": "worker [123abc]"}
    assert binding_identity(dict(claude, message_to="worker [456def]"), "claude") == binding_identity(claude, "claude")
    assert binding_identity(None, "codex") is None

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
        _, error = child.communicate(timeout=command_timeout())
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
            with locked(path, timeout=0.01):    # short limit: the lock is held for the whole test, so the wait only ends by its limit
                pass
        assert error.value.code == "lock_timeout"
    with locked(path, blocking=False):
        assert path.exists()


def test_state_update_uses_its_remaining_timeout(tmp_path):
    store = StateStore(project(tmp_path), timeout=0.01)   # short limit: the lock is held for the whole test
    with locked(store.lock_path):
        with pytest.raises(SessionError) as error:
            store.update(lambda state: state)
    assert error.value.code == "lock_timeout"
    assert not store.path.exists()
