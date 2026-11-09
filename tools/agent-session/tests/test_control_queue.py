"""One deferred control request owns a run's single result location."""

import json
import os
import time
from types import SimpleNamespace

import pytest

from agent_session.errors import SessionError
from agent_session.lifecycle import Manager
from fake_tmux import FakeTmux, fake_tmux


def manager(tmp_path):
    base = tmp_path.resolve()
    meta = {"base": str(base), "run_id": "fixture-run", "target": "seat-0", "window_id": "@1",
            "pane_id": "%1", "job_id": "J-20261103-01", "session_id": "native-fixture",
            "socket_path": str(tmp_path / "tmux.sock")}
    state = {"leader": None, "0": {"job_id": meta["job_id"], "git_hash": None,
                                   "session": {"session_id": meta["session_id"]}}}
    class Tmux(FakeTmux):
        def __init__(self):
            self.submitted = []

        def require_version(self):
            pass

        def get_current(self, project_id, target):
            return dict(meta)

        def read_meta(self, window_id):
            return dict(meta)

        def write_meta(self, window_id, updates):
            meta.update(updates)
            return dict(meta)

        def run_controller(self, script_path, cwd):
            self.submitted.append(str(script_path))
    value = Manager.__new__(Manager)
    value.project = SimpleNamespace(base=base, runtime_path=tmp_path / "agent",
                                    project_id="fixture", config_path=tmp_path / "projects.json", seats=(tmp_path / "seat",))
    value.timeout = 10
    value.end = time.monotonic() + 10
    value._held = {}
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
    subject._target = lambda *args, **keywords: dict(meta)
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


def test_a_fake_tmux_follows_the_product_interface():
    from agent_session.tmux import Tmux

    class Faked(FakeTmux):
        def read_meta(self, window_id):
            return {}

    assert Faked().read_meta("@1") == {}
    with pytest.raises(AssertionError, match="does not fake the tmux call"):
        Faked().require_version()                        # an unwritten product method reaches no real tmux
    assert Tmux.read_meta.__name__ == "read_meta"
    with pytest.raises(AssertionError, match="not a method"):
        class Removed(FakeTmux):
            def no_such_method(self):
                pass
    with pytest.raises(AssertionError, match="differs from"):
        class Renamed(FakeTmux):
            def read_meta(self, window):
                pass


def test_a_fake_tmux_built_from_callables_follows_the_product_interface():
    fake = fake_tmux(get_current=lambda *args: {"run_id": "r"}, pane_info=lambda pane_id: {"pane_dead": True})
    assert fake.get_current("p", "seat-0") == {"run_id": "r"} and fake.pane_info("%1") == {"pane_dead": True}
    with pytest.raises(AssertionError, match="not a method"):
        fake_tmux(no_such_method=lambda: None)
    with pytest.raises(AssertionError, match="differs from"):
        fake_tmux(pane_info=lambda pane: None)
    with pytest.raises(AssertionError, match="differs from"):
        fake_tmux(pane_info=lambda pane_id, extra: None)
