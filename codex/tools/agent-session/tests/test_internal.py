"""Registration regression tests across real tmux and canonical state."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import pytest

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from agent_session import api, internal, providers
from agent_session.config import resolve_project
from agent_session.errors import SessionError
from agent_session.state import StateStore, locked
from agent_session.tmux import Tmux


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
    subprocess.run(["tmux", "-L", socket_name, "kill-server"], capture_output=True, timeout=10)


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
