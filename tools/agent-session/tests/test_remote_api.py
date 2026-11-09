"""Remote process facts remain authoritative when a local SSH display disappears."""

import copy
from pathlib import PurePosixPath

import pytest

from agent_session import api, config, process, remote, tmux
from agent_session.config import Project, RemoteSeat
from agent_session.errors import SessionError
from agent_session.state import StateStore


@pytest.fixture
def remote_slot(tmp_path, monkeypatch):
    base = tmp_path / "base"
    base.mkdir()
    project = Project(base, str(base), "remote-test", "codex",
                      (RemoteSeat("macbook-worker", PurePosixPath("/Users/swain/seat")),),
                      tmp_path / "project.json")
    session = {"session_id": "remote-thread", "endpoint": "unix:///remote/codex.sock"}
    store = StateStore(project)
    store.update(lambda state: state["0"].update(job_id="TEST-001", session=session))
    meta = {
        "base": str(base), "project_id": project.project_id, "target": "seat-0", "seat": 0,
        "job_id": "TEST-001", "run_id": "a" * 32, "window_id": "@2", "pane_id": "%3",
        "server_pid": 400, "server_started": "local-server", "ready": True, "registered": True,
        "remote_seat": {"host": "macbook-worker", "path": "/Users/swain/seat", "python": "python3"},
        "remote_native": {"session_id": session["session_id"], "run_id": "a" * 32},
        "cwd": "/Users/swain/seat", **session,
    }

    class Display:
        def get_current(self, project_id, slot):
            assert project_id == project.project_id and slot == "seat-0"
            return copy.deepcopy(meta)

        def read_meta(self, window_id):
            assert window_id == meta["window_id"]
            return copy.deepcopy(meta)

        def pane_info(self, pane_id):
            pytest.fail("a local SSH display is not remote process evidence")

    def local_process(*args):
        pytest.fail("remote PID values must not be inspected on the local host")

    control = Display()
    monkeypatch.setattr(config, "current_project", lambda *args: project)
    monkeypatch.setattr(tmux, "control", lambda *args: control)
    monkeypatch.setattr(process, "alive", local_process)
    monkeypatch.setattr(process, "group_alive", local_process)
    return project, store, meta, control


def test_remote_liveness_does_not_use_a_dead_local_ssh_display(remote_slot, monkeypatch):
    project, _, meta, _ = remote_slot
    monkeypatch.setattr(remote, "liveness", lambda current: "alive")
    assert api.liveness(project.base) == {"0": {"session_id": meta["session_id"], "state": "alive"}}


def test_remote_disconnect_is_unknown_and_keeps_the_assignment(remote_slot, monkeypatch):
    project, store, meta, _ = remote_slot
    before = project.state_path.read_bytes()

    def disconnected(current):
        raise SessionError("remote_unknown", "SSH connection lost.", 4)

    monkeypatch.setattr(remote, "liveness", disconnected)
    assert api.liveness(project.base) == {"0": {"session_id": meta["session_id"], "state": "unknown"}}
    assert project.state_path.read_bytes() == before
    assert store.read()["0"]["job_id"] == "TEST-001"


@pytest.mark.parametrize("field,value", [("host", "other-host"), ("path", "/other/seat"),
                                         ("python", "/other/python")])
def test_remote_registry_binding_cannot_be_changed_while_a_run_is_active(remote_slot, monkeypatch, field, value):
    project, store, meta, _ = remote_slot
    meta["remote_seat"][field] = value
    before = store.read()
    monkeypatch.setattr(remote, "run_call", lambda *args, **kwargs: pytest.fail("A changed host must not be called"))
    with pytest.raises(SessionError) as caught:
        api.check_binding(project.base, "TEST-001")
    assert caught.value.code == "owner_mismatch"
    assert store.read() == before


def test_remote_caller_uses_remote_liveness_without_a_local_cli_pid(remote_slot, monkeypatch):
    project, _, meta, control = remote_slot
    monkeypatch.setattr(remote, "liveness", lambda current: "alive")
    api.require_live(project, "seat-0", meta["session_id"], tmux=control)
    monkeypatch.setattr(remote, "liveness", lambda current: "stopped")
    with pytest.raises(SessionError, match="live managed CLI") as caught:
        api.require_live(project, "seat-0", meta["session_id"], tmux=control)
    assert caught.value.code == "caller_not_running"


def test_binding_uses_remote_termination_and_rechecks_the_local_assignment(remote_slot, monkeypatch):
    project, store, meta, _ = remote_slot
    observation = {"known": True, "stopped": False, "terminal": True}

    def binding(current, operation, payload=None, timeout=30):
        assert operation == "check_binding" and current["run_id"] == meta["run_id"]
        return {"alive": True, "termination_confirmed": False, "ready": True,
                "session": store.read()["0"]["session"], "observation": observation}

    monkeypatch.setattr(remote, "run_call", binding)
    checked = api.check_binding(project.base, "TEST-001")
    assert checked["alive"] is True and checked["termination_confirmed"] is False
    assert checked["observation"] == observation
    assert checked["window_id"] == meta["window_id"]
    assert checked["cwd"] == "/Users/swain/seat"

    def changed(current, operation, payload=None, timeout=30):
        value = binding(current, operation, payload, timeout)
        store.update(lambda state: state["0"]["session"].update(session_id="replacement-thread"))
        return value

    monkeypatch.setattr(remote, "run_call", changed)
    with pytest.raises(SessionError) as caught:
        api.check_binding(project.base, "TEST-001")
    assert caught.value.code == "target_changed"


@pytest.mark.parametrize("response", [{}, {"alive": "true", "ready": True,
                                        "termination_confirmed": False, "observation": {}}])
def test_incomplete_remote_binding_cannot_confirm_termination(remote_slot, monkeypatch, response):
    project, _, _, _ = remote_slot
    before = project.state_path.read_bytes()
    monkeypatch.setattr(remote, "run_call", lambda *args, **kwargs: response)
    with pytest.raises(SessionError) as caught:
        api.check_binding(project.base, "TEST-001")
    assert caught.value.code == "remote_unknown"
    assert project.state_path.read_bytes() == before
