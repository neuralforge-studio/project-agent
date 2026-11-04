"""One deferred control request owns a run's single result location."""

import json
import time
from types import SimpleNamespace

import pytest

from agent_session.errors import SessionError
from agent_session.lifecycle import Manager


def manager(tmp_path):
    meta = {"run_id": "fixture-run", "target": "seat-0", "window_id": "@1",
            "pane_id": "%1", "job_id": "J-20261103-01", "session_id": "native-fixture",
            "socket_path": str(tmp_path / "tmux.sock")}
    class Tmux:
        def __init__(self):
            self.submitted = []

        def get_current(self, project, target):
            return dict(meta)

        def read_meta(self, window):
            return dict(meta)

        def write_meta(self, window, values):
            meta.update(values)
            return dict(meta)

        def run_controller(self, script, cwd):
            self.submitted.append(str(script))
    value = Manager.__new__(Manager)
    value.project = SimpleNamespace(base=tmp_path, runtime_path=tmp_path / "agent",
                                    project_id="fixture", config_path=tmp_path / "projects.json")
    value.timeout = 10
    value.end = time.monotonic() + 10
    value.store = SimpleNamespace(timeout=10)
    value.tmux = Tmux()
    return value, meta


def test_pending_control_cannot_be_replaced_by_another_operation(tmp_path):
    subject, meta = manager(tmp_path)
    accepted = subject._self_control("stop", meta, meta["job_id"], None)
    with pytest.raises(SessionError) as error:
        subject._self_control("restart", meta, meta["job_id"], None)
    assert error.value.code == "control_busy"
    assert len(subject.tmux.submitted) == 1
    request = json.loads((tmp_path / "agent/runs/fixture-run/control-request.json").read_text())
    assert request["operation"] == "stop"
    assert json.loads(open(accepted["result_file"]).read())["data"]["completed"] is False


def test_same_pending_request_returns_one_result_location(tmp_path):
    subject, meta = manager(tmp_path)
    first = subject._self_control("stop", meta, meta["job_id"], None)
    second = subject._self_control("stop", meta, meta["job_id"], None)
    assert second == first
    assert len(subject.tmux.submitted) == 1


def test_external_control_cannot_overtake_a_pending_self_request(tmp_path):
    subject, meta = manager(tmp_path)
    subject._self_control("stop", meta, meta["job_id"], None)
    subject._target = lambda *args: dict(meta)
    subject._authorize = lambda *args: ("operator", None)
    handoffs = []
    subject.adapter = SimpleNamespace(prepare_restart=lambda target: handoffs.append(target))
    with pytest.raises(SessionError) as error:
        subject.control("restart", job=meta["job_id"])
    assert error.value.code == "control_busy"
    assert handoffs == []
    assert len(subject.tmux.submitted) == 1
