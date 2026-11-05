"""Registration regression tests across real tmux and canonical state."""

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

import pytest

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from agent_session import api, internal, providers
from agent_session.config import resolve_project
from agent_session.errors import SessionError
from agent_session.state import StateStore, locked
from agent_session.tmux import Tmux
from agent_session_fixture import stop_test_server


@pytest.fixture
def native_slot(tmp_path, monkeypatch):
    if not shutil.which("tmux"):
        pytest.skip("tmux is unavailable")
    for name in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "AGENT_SESSION_CONFIG", "AGENT_SESSION_SOCKET"):
        monkeypatch.delenv(name, raising=False)
    base = tmp_path / "main"
    seat = tmp_path / "seat0"
    base.mkdir()
    seat.mkdir()
    config = tmp_path / "project.json"
    config.write_text(json.dumps({str(base): {"project": "fixture", "provider": "codex", "seats": [str(seat)]}}))
    project = resolve_project(base, config)
    store = StateStore(project)
    socket_name = "agent-internal-test-" + uuid.uuid4().hex[:12]
    subprocess.run(["tmux", "-L", socket_name, "-f", os.devnull, "new-session", "-d", "-s", "harness",
                    "sleep", "86400"], check=True, capture_output=True)
    control = Tmux(socket_name=socket_name)
    script = tmp_path / "dummy-provider.sh"
    script.write_text("#!/bin/bash\nexec sleep 86400\n")
    job_id = "J-20261103-01"
    endpoint = "unix:///tmp/agent-internal-fixture.sock"

    def publish(run_id, session_id):
        context = {"base": str(base), "target": "seat-0", "job_id": job_id, "run_id": run_id,
                   "provider": "codex", "config_path": str(config), "endpoint": endpoint}
        meta = control.create_window("fixture", "fixture-worker-0-" + run_id, seat, context)
        control.set_current("fixture", "seat-0", meta)
        meta = control.launch(meta["window_id"], seat, script)
        control.write_meta(meta["window_id"], {"session_id": session_id, "registered": True, "ready": True})
        store.update(lambda state: state["0"].update(job_id=job_id,
                     session={"session_id": session_id, "endpoint": endpoint}))
        return control.get_current("fixture", "seat-0")

    previous = publish("old-run", str(uuid.uuid4()))
    yield {"project": project, "store": store, "tmux": control, "previous": previous,
           "config": config, "base": base, "seat": seat, "endpoint": endpoint, "publish": publish}
    stop_test_server(socket_name)


def test_late_registration_cannot_replace_a_new_run_after_native_check(native_slot, monkeypatch):
    """A stale native lookup must not publish after a replacement owns the slot."""
    fixture = native_slot
    old = fixture["previous"]
    new_session_id = str(uuid.uuid4())
    schedule = {"verified": False, "published": False}

    class Provider:
        def verify_binding(self, session, context, metadata, timeout=20):
            schedule["verified"] = True
            return session

    monkeypatch.setattr(providers, "get_provider", lambda name: Provider())
    original = Tmux.get_current

    def delayed_observation(control, project_id, target):
        observed = original(control, project_id, target)
        if schedule["verified"] and not schedule["published"] and target == "seat-0":
            schedule["published"] = True
            fixture["publish"]("new-run", new_session_id)
        return observed

    monkeypatch.setattr(Tmux, "get_current", delayed_observation)
    try:
        internal._register(old["run_id"], str(fixture["config"]), old["socket_path"],
                           old["session_id"], fixture["endpoint"], cwd=fixture["seat"])
    except SessionError as error:
        assert error.code in ("target_changed", "owner_mismatch")
    assert schedule["published"], "The replacement must race the old native lookup."
    current = fixture["store"].read()["0"]["session"]
    assert current["session_id"] == new_session_id
    assert original(fixture["tmux"], "fixture", "seat-0")["run_id"] == "new-run"


def test_registration_records_local_facts_without_publishing_canonical_state(native_slot, monkeypatch):
    fixture = native_slot
    old = fixture["store"].read()["0"]["session"].copy()
    control = fixture["tmux"]
    pending = control.create_window("fixture", "new-conversation", fixture["seat"],
                                    {"base": str(fixture["base"]), "target": "seat-0",
                                     "job_id": "J-20261103-01", "run_id": "pending-run",
                                     "provider": "codex", "endpoint": fixture["endpoint"],
                                     "config_path": str(fixture["config"])})
    control.set_current("fixture", "seat-0", pending)
    script = fixture["base"].parent / "next-provider.sh"
    script.write_text("#!/bin/bash\nexec sleep 86400\n")
    control.launch(pending["window_id"], fixture["seat"], script)
    class Provider:
        def verify_binding(self, session, context, metadata, timeout=20):
            return session
    monkeypatch.setattr(providers, "get_provider", lambda name: Provider())
    native_id = str(uuid.uuid4())
    internal._register("pending-run", str(fixture["config"]), pending["socket_path"],
                       native_id, fixture["endpoint"], cwd=fixture["seat"])
    assert fixture["store"].read()["0"]["session"] == old
    assert control.get_current("fixture", "seat-0")["session_id"] == native_id
    assert control.get_current("fixture", "seat-0")["ready"] is False


@pytest.mark.parametrize("mismatch", ["cwd", "endpoint"])
def test_registration_rejects_wrong_runtime_context_without_state_change(native_slot, mismatch):
    fixture = native_slot
    before = fixture["store"].read()
    old = fixture["previous"]
    cwd = fixture["base"] if mismatch == "cwd" else fixture["seat"]
    endpoint = "unix:///tmp/unrelated.sock" if mismatch == "endpoint" else fixture["endpoint"]
    with pytest.raises(SessionError) as error:
        internal._register(old["run_id"], str(fixture["config"]), old["socket_path"],
                           old["session_id"], endpoint, cwd=cwd)
    assert error.value.code == "owner_mismatch"
    assert fixture["store"].read() == before


def test_stop_hook_keeps_observation_fields_and_drops_the_reply(native_slot, monkeypatch):
    fixture = native_slot
    old = fixture["previous"]

    def hook(payload):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        internal.register_from_hook(old["run_id"], str(fixture["config"]), old["socket_path"],
                                    expected_session_id=old["session_id"])

    stop = {"session_id": old["session_id"], "hook_event_name": "Stop", "cwd": str(fixture["seat"]),
            "transcript_path": "/tmp/fixture.jsonl", "background_tasks": [], "session_crons": [],
            "last_assistant_message": "Set $HOME first."}
    hook(stop)
    hook({**stop, "last_assistant_message": "Done."})
    saved = fixture["tmux"].get_current("fixture", "seat-0")["hook_observations"]["Stop"]
    assert "last_assistant_message" not in saved and "transcript_path" not in saved
    assert saved["session_id"] == old["session_id"]
    assert saved["background_tasks"] == [] and saved["session_crons"] == []
    assert saved["hook_event_name"] == "Stop" and "observed_at" in saved


def test_read_only_binding_api_does_not_take_the_project_domain_lock(native_slot, monkeypatch):
    fixture = native_slot
    class Provider:
        def verify_binding(self, session, context, metadata, timeout=20):
            return session
        def observe(self, session, context, metadata, timeout=20):
            return {"known": True, "terminal": True, "active_turn": False,
                    "pending": [], "background": [], "idle": True}
    monkeypatch.setattr(providers, "get_provider", lambda name: Provider())
    before = fixture["project"].state_path.read_bytes()
    stamp = fixture["project"].state_path.stat().st_mtime_ns
    with locked(fixture["base"] / "domain.lock"):
        observed = api.check_binding(fixture["seat"], "J-20261103-01",
                                     config_path=fixture["config"], socket=fixture["previous"]["socket_path"])
    assert observed["ready"] is True and observed["alive"] is True
    assert observed["termination_confirmed"] is False
    assert fixture["project"].state_path.read_bytes() == before
    assert fixture["project"].state_path.stat().st_mtime_ns == stamp


@pytest.mark.parametrize("change, changed", [
    (lambda state, endpoint: state.update(leader={"session_id": "leader-native", "endpoint": endpoint,
                                                  "connected_at": "2026-11-04T09:12:30Z",
                                                  "reviewing": "J-20261103-01"}), False),
    (lambda state, endpoint: state["0"]["session"].update(connected_at="2026-11-04T09:12:30Z"), False),
    (lambda state, endpoint: state["0"]["session"].update(endpoint="unix:///tmp/another-endpoint.sock"), True),
    (lambda state, endpoint: state["0"]["session"].update(session_id=str(uuid.uuid4())), True),
])
def test_binding_check_ignores_review_marks_but_not_connection_changes(native_slot, monkeypatch, change, changed):
    fixture = native_slot

    class Provider:
        def verify_binding(self, session, context, metadata, timeout=20):
            return session

        def observe(self, session, context, metadata, timeout=20):
            fixture["store"].update(lambda state: change(state, fixture["endpoint"]))
            return {"known": True, "terminal": True, "active_turn": False,
                    "pending": [], "background": [], "idle": True}
    monkeypatch.setattr(providers, "get_provider", lambda name: Provider())
    call = lambda: api.check_binding(fixture["seat"], "J-20261103-01", config_path=fixture["config"],
                                     socket=fixture["previous"]["socket_path"])
    if changed:
        with pytest.raises(SessionError) as error:
            call()
        assert error.value.code == "target_changed"
    else:
        assert call()["alive"] is True


def test_liveness_reads_tmux_and_process_facts_without_a_provider(native_slot, monkeypatch):
    fixture = native_slot
    previous = fixture["previous"]

    def no_provider(name):
        raise AssertionError("liveness must not call a provider")
    monkeypatch.setattr(providers, "get_provider", no_provider)
    call = lambda: api.liveness(fixture["seat"], config_path=fixture["config"], socket=previous["socket_path"])
    assert call() == {"0": {"session_id": previous["session_id"], "state": "alive"}}
    other = str(uuid.uuid4())
    fixture["store"].update(lambda state: state["0"]["session"].update(session_id=other))
    assert call() == {"0": {"session_id": other, "state": "unknown"}}
    fixture["store"].update(lambda state: state["0"]["session"].update(session_id=previous["session_id"]))
    os.kill(fixture["tmux"].pane_info(previous["pane_id"])["pane_pid"], 15)
    deadline = time.monotonic() + 10
    while not fixture["tmux"].pane_info(previous["pane_id"])["pane_dead"]:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    assert call() == {"0": {"session_id": previous["session_id"], "state": "stopped"}}
    fixture["tmux"].command("kill-window", "-t", previous["window_id"])
    assert call() == {"0": {"session_id": previous["session_id"], "state": "unknown"}}
