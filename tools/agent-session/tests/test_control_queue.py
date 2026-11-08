"""One deferred control request owns a run's single result location."""

import json
import os
import time
from types import SimpleNamespace

import pytest

from agent_session.errors import SessionError
from agent_session.lifecycle import Manager


def manager(tmp_path):
    base = tmp_path.resolve()
    meta = {"base": str(base), "run_id": "fixture-run", "target": "seat-0", "window_id": "@1",
            "pane_id": "%1", "job_id": "J-20261103-01", "session_id": "native-fixture",
            "socket_path": str(tmp_path / "tmux.sock")}
    state = {"leader": None, "0": {"job_id": meta["job_id"], "git_hash": None,
                                   "session": {"session_id": meta["session_id"]}}}
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
    value.project = SimpleNamespace(base=base, runtime_path=tmp_path / "agent",
                                    project_id="fixture", config_path=tmp_path / "projects.json", seats=(tmp_path / "seat",))
    value.timeout = 10
    value.end = time.monotonic() + 10
    value.store = SimpleNamespace(timeout=10, read=lambda: state)
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
    with pytest.raises(SessionError) as error:
        subject.control("restart", job=meta["job_id"])
    assert error.value.code == "control_busy"
    assert len(subject.tmux.submitted) == 1


def test_self_restart_needs_a_handoff_written_during_the_run(tmp_path):
    subject, meta = manager(tmp_path)
    run = tmp_path / "agent/runs/fixture-run"
    run.mkdir(parents=True)
    (run / "launch.sh").write_text("#!/bin/bash\n")
    with pytest.raises(SessionError) as error:
        subject._self_control("restart", meta, meta["job_id"], None)
    assert error.value.code == "handoff_required"
    assert subject.tmux.submitted == []
    handoff = tmp_path / "agent/handoff/seat-0.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text("next steps\n")
    later = (run / "launch.sh").stat().st_mtime + 1
    os.utime(handoff, (later, later))
    assert subject._self_control("restart", meta, meta["job_id"], None)["accepted"] is True
    assert len(subject.tmux.submitted) == 1
