"""Registration regression tests across real tmux and canonical state."""

import contextlib
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
from agent_session import api, hook_started, internal, process, providers
from agent_session.config import resolve_project
from agent_session.errors import SessionError
from agent_session.state import StateStore, locked
from agent_session.tmux import Tmux
import tmux_test_server  # noqa: E402


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
    socket_name = tmux_test_server.claim("agent-internal-test")
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
    tmux_test_server.release(socket_name)


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


def pending_run(fixture, monkeypatch, run_id="pending-run"):
    """A launched run that took over seat-0 from the published old run and has not registered."""
    control = fixture["tmux"]
    pending = control.create_window("fixture", "new-conversation", fixture["seat"],
                                    {"base": str(fixture["base"]), "target": "seat-0",
                                     "job_id": "J-20261103-01", "run_id": run_id,
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
    return pending


def test_registration_binds_and_publishes_in_one_step(native_slot, monkeypatch):
    fixture = native_slot
    old = fixture["store"].read()["0"]["session"].copy()
    pending = pending_run(fixture, monkeypatch)
    native_id = str(uuid.uuid4())
    internal._register("pending-run", str(fixture["config"]), pending["socket_path"],
                       native_id, fixture["endpoint"], cwd=fixture["seat"])
    published = fixture["store"].read()["0"]["session"]
    assert published["session_id"] == native_id != old["session_id"]
    assert published["endpoint"] == fixture["endpoint"] and "connected_at" in published
    current = fixture["tmux"].get_current("fixture", "seat-0")
    assert current["session_id"] == native_id and current["registered"] is True and current["ready"] is True


def test_session_start_hook_publishes_the_new_conversation(native_slot, monkeypatch):
    fixture = native_slot
    pending = pending_run(fixture, monkeypatch)
    native_id = str(uuid.uuid4())
    payload = {"session_id": native_id, "hook_event_name": "SessionStart", "cwd": str(fixture["seat"]),
               "source": "startup"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    internal.register_from_hook("pending-run", str(fixture["config"]), pending["socket_path"],
                                expected_session_id=native_id, endpoint=fixture["endpoint"])
    assert fixture["store"].read()["0"]["session"]["session_id"] == native_id
    current = fixture["tmux"].get_current("fixture", "seat-0")
    assert current["ready"] is True and "SessionStart" in current["hook_observations"]


def test_registration_waits_for_the_control_lock_inside_its_limit(native_slot, monkeypatch):
    from agent_session.state import control_lock

    fixture = native_slot
    pending = pending_run(fixture, monkeypatch)
    monkeypatch.setattr(internal, "_HOOK_BUDGET", 1)
    before = fixture["store"].read()
    with control_lock(fixture["project"], "seat-0"):
        with pytest.raises(SessionError) as error:
            internal._register("pending-run", str(fixture["config"]), pending["socket_path"],
                               str(uuid.uuid4()), fixture["endpoint"], cwd=fixture["seat"])
    assert error.value.code == "lock_timeout"
    current = fixture["tmux"].get_current("fixture", "seat-0")
    assert current["registered"] is False and current["ready"] is False
    assert current["start_error"]["code"] == "lock_timeout"
    assert fixture["store"].read() == before


class Killed(BaseException):
    """Stands for a process that ends where it is raised: nothing after it, no clean-up, runs."""


def test_a_failed_window_update_puts_the_published_session_back(native_slot, monkeypatch):
    fixture = native_slot
    before = fixture["store"].read()
    pending = pending_run(fixture, monkeypatch)
    original = Tmux.write_meta

    def lose_window_update(self, window_id, updates):
        if updates.get("ready") is True:
            raise SessionError("tmux_command_failed", "The fixture lost the window update.", 5)
        return original(self, window_id, updates)

    monkeypatch.setattr(Tmux, "write_meta", lose_window_update)
    with pytest.raises(SessionError) as error:
        internal._register("pending-run", str(fixture["config"]), pending["socket_path"],
                           str(uuid.uuid4()), fixture["endpoint"], cwd=fixture["seat"])
    assert error.value.code == "tmux_command_failed"
    assert fixture["store"].read() == before                  # nothing stays published
    current = fixture["tmux"].get_current("fixture", "seat-0")
    assert current["registered"] is False and current["ready"] is False and current.get("publishing") is None
    assert current["start_error"]["code"] == "tmux_command_failed"


def test_a_process_that_ends_after_the_commit_leaves_what_complete_publication_finishes(native_slot, monkeypatch):
    from agent_session.state import complete_publication, control_lock

    fixture = native_slot
    pending = pending_run(fixture, monkeypatch)
    native_id = str(uuid.uuid4())
    original = Tmux.write_meta

    def end_at_window_update(self, window_id, updates):
        if updates.get("ready") is True:
            raise Killed()
        return original(self, window_id, updates)

    saves = []
    update = StateStore.update

    def only_the_commit(self, mutator):
        saves.append(True)
        if len(saves) > 1:
            raise SessionError("state_write_failed", "The state cannot be saved again.", 5)
        return update(self, mutator)

    # The process ends at the window update and its clean-up cannot save the state either, as when it is
    # killed there: nothing is put back.
    monkeypatch.setattr(Tmux, "write_meta", end_at_window_update)
    monkeypatch.setattr(StateStore, "update", only_the_commit)
    with pytest.raises(Killed):
        internal._register("pending-run", str(fixture["config"]), pending["socket_path"],
                           native_id, fixture["endpoint"], cwd=fixture["seat"])
    monkeypatch.setattr(Tmux, "write_meta", original)
    monkeypatch.setattr(StateStore, "update", update)
    # The state names the new conversation, the window has the intent and is not ready.
    committed = fixture["store"].read()["0"]["session"]
    assert committed["session_id"] == native_id
    current = fixture["tmux"].get_current("fixture", "seat-0")
    assert current["ready"] is False and current["registered"] is False
    assert current["publishing"] == {"session_id": native_id, "endpoint": fixture["endpoint"]}
    with control_lock(fixture["project"], "seat-0"):
        finished = complete_publication(fixture["project"], fixture["tmux"], fixture["store"], current)
    assert finished["ready"] is True and finished["registered"] is True and finished["session_id"] == native_id
    assert finished["publishing"] is None
    assert fixture["store"].read()["0"]["session"] == committed       # decided nothing new


def test_complete_publication_finishes_nothing_the_state_does_not_name(native_slot, monkeypatch):
    from agent_session.state import complete_publication, control_lock

    fixture = native_slot
    pending = pending_run(fixture, monkeypatch)
    before = fixture["store"].read()
    other = {"session_id": str(uuid.uuid4()), "endpoint": fixture["endpoint"]}
    fixture["tmux"].write_meta(pending["window_id"], {"run_id": "pending-run", "publishing": other})
    current = fixture["tmux"].get_current("fixture", "seat-0")
    with control_lock(fixture["project"], "seat-0"):
        assert complete_publication(fixture["project"], fixture["tmux"], fixture["store"], current) is None
    assert fixture["store"].read() == before
    after = fixture["tmux"].get_current("fixture", "seat-0")
    assert after["ready"] is False and after["registered"] is False


def run_register(fixture, budget, session_id=None):
    """Register the pending run with a small deadline; return the error and the seconds it took."""
    started = time.monotonic()
    with pytest.raises(SessionError) as error:
        internal._register("pending-run", str(fixture["config"]), fixture["pending"]["socket_path"],
                           session_id or str(uuid.uuid4()), fixture["endpoint"], cwd=fixture["seat"])
    return error.value, time.monotonic() - started


@pytest.mark.parametrize("slow", ["binding", "control_lock", "state_lock"])
def test_every_step_of_a_registration_ends_inside_its_one_deadline(native_slot, monkeypatch, slow):
    from agent_session.state import control_lock

    fixture = native_slot
    fixture["pending"] = pending_run(fixture, monkeypatch)
    before = fixture["store"].read()
    monkeypatch.setattr(internal, "_HOOK_BUDGET", 3)
    monkeypatch.setattr(internal, "_PUBLISH_RESERVE", 1)
    monkeypatch.setattr(internal, "_BINDING_INTERVAL", 0.2)
    if slow == "binding":
        class Slow:
            def verify_binding(self, session, context, metadata, timeout=20):
                raise SessionError("session_not_bound", "The listing does not show the pane yet.", 3,
                                   {"retryable": True})
        monkeypatch.setattr(providers, "get_provider", lambda name: Slow())
        error, seconds = run_register(fixture, 3)
    elif slow == "control_lock":
        with control_lock(fixture["project"], "seat-0"):
            error, seconds = run_register(fixture, 3)
    else:
        with locked(fixture["project"].state_path.with_name("state.lock")):
            error, seconds = run_register(fixture, 3)
    assert error.code == ("session_not_bound" if slow == "binding" else "lock_timeout")
    assert seconds < 6, "the steps did not share the 3 second deadline"     # added limits would be far above
    assert fixture["store"].read() == before
    current = fixture["tmux"].get_current("fixture", "seat-0")
    assert current["registered"] is False and current["ready"] is False and current.get("publishing") is None
    assert current["start_error"]["code"] == error.code


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


@pytest.mark.parametrize("resume, source, accepted", [
    (True, "resume", True), (True, "startup", False), (False, "startup", True), (False, "resume", False),
])
def test_session_start_binds_only_the_source_that_fits_the_run(native_slot, monkeypatch, resume, source, accepted):
    fixture = native_slot
    old = fixture["previous"]
    if resume:
        fixture["tmux"].write_meta(old["window_id"], {"resume": True})
    bound = []

    def register(*arguments, **keywords):
        bound.append(arguments)
        return None, fixture["tmux"], fixture["tmux"].get_current("fixture", "seat-0"), None

    monkeypatch.setattr(internal, "_register", register)
    payload = {"session_id": old["session_id"], "hook_event_name": "SessionStart", "cwd": str(fixture["seat"]),
               "source": source}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    call = lambda: internal.register_from_hook(old["run_id"], str(fixture["config"]), old["socket_path"],
                                               expected_session_id=old["session_id"])
    if accepted:
        call()
        assert len(bound) == 1
    else:
        with pytest.raises(SessionError) as error:
            call()
        assert error.value.code == "hook_invalid" and bound == []


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
    # A caller that already holds the project (BOARD-002) gets the same answers without selecting it again.
    project = api.resolve_project(fixture["seat"], config_path=fixture["config"])
    assert api.project_liveness(project, socket=previous["socket_path"]) == call()
    assert api.project_state(project) == api.read_state(fixture["seat"], config_path=fixture["config"])
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


def _registering(fixture, monkeypatch, provider):
    """A pending run that registers through `provider`; returns the call that registers it."""
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
    monkeypatch.setattr(providers, "get_provider", lambda name: provider)
    monkeypatch.setattr(internal, "_BINDING_INTERVAL", 0.01)
    native_id = str(uuid.uuid4())
    return pending, lambda: internal._register("pending-run", str(fixture["config"]), pending["socket_path"],
                                               native_id, fixture["endpoint"], cwd=fixture["seat"])


def _not_listed():
    return SessionError("session_not_bound", "Claude ListAgents does not identify one managed pane.", 3,
                        {"retryable": True})


def test_the_retries_of_the_binding_check_share_one_provider_connection(native_slot, monkeypatch):
    """SESSION-013. Each look used to start `claude mcp serve` again (8-32 s under load); one block serves them all."""
    events = []

    class Provider:
        @contextlib.contextmanager
        def reusing_client(self, timeout):
            events.append(("open", timeout))
            try:
                yield
            finally:
                events.append(("close",))

        def verify_binding(self, session, context, metadata, timeout=20):
            events.append(("look",))
            if sum(event == ("look",) for event in events) <= 3:
                raise _not_listed()
            return session

    pending, register = _registering(native_slot, monkeypatch, Provider())
    register()
    assert [event[0] for event in events] == ["open", "look", "look", "look", "look", "close"]
    assert 0 < events[0][1] <= internal._BINDING_TIMEOUT


def test_registration_waits_out_a_listing_that_misses_the_pane_at_first(native_slot, monkeypatch):
    calls = []

    class Provider:
        def verify_binding(self, session, context, metadata, timeout=20):
            calls.append(timeout)
            if len(calls) <= 2:
                raise _not_listed()
            return session

    pending, register = _registering(native_slot, monkeypatch, Provider())
    register()
    assert len(calls) == 3 and all(0 < timeout <= internal._BINDING_TIMEOUT for timeout in calls)
    current = native_slot["tmux"].get_current("fixture", "seat-0")
    assert current["registered"] is True and not current.get("start_error")


@pytest.mark.parametrize("error", [
    SessionError("session_not_bound", "Claude ListAgents does not identify one managed pane.", 3),
    SessionError("session_mismatch", "Claude UUID does not match the managed run.", 3),
])
def test_registration_does_not_retry_a_binding_that_is_not_transient(native_slot, monkeypatch, error):
    calls = []

    class Provider:
        def verify_binding(self, session, context, metadata, timeout=20):
            calls.append(timeout)
            raise error

    _, register = _registering(native_slot, monkeypatch, Provider())
    with pytest.raises(SessionError) as caught:
        register()
    assert caught.value.code == error.code and len(calls) == 1


def test_registration_gives_up_when_the_listing_never_shows_the_pane(native_slot, monkeypatch):
    calls = []

    class Provider:
        def verify_binding(self, session, context, metadata, timeout=20):
            calls.append(timeout)
            raise _not_listed()

    pending, register = _registering(native_slot, monkeypatch, Provider())
    monkeypatch.setattr(internal, "_BINDING_TIMEOUT", 0.3)
    with pytest.raises(SessionError) as caught:
        register()
    assert caught.value.code == "session_not_bound" and len(calls) > 1
    failed = native_slot["tmux"].get_current("fixture", "seat-0")
    assert failed.get("registered") is not True
    assert failed["start_error"]["code"] == "session_not_bound"
    assert "ListAgents" in failed["start_error"]["message"]


def _hook_with(fixture, monkeypatch, session_id, moved, host):
    """Run a Stop hook that carries `session_id` for a run that expects another conversation."""
    old = fixture["previous"]

    class Provider:
        def moved_to(self, expected):
            assert expected == old["session_id"]
            return moved

        def background_host(self, session_id, cwd, timeout=8):
            if host is None:
                raise SessionError("provider_command_failed", "The listing failed.", 5)
            return host

    monkeypatch.setattr(providers, "get_provider", lambda name: Provider())
    payload = {"session_id": session_id, "hook_event_name": "Stop", "cwd": str(fixture["seat"]),
               "background_tasks": [], "session_crons": []}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    internal.register_from_hook(old["run_id"], str(fixture["config"]), old["socket_path"],
                                expected_session_id=old["session_id"])


def test_a_hook_from_the_background_session_records_the_move(native_slot, monkeypatch):
    fixture = native_slot
    new = str(uuid.uuid4())
    with pytest.raises(SessionError) as error:
        _hook_with(fixture, monkeypatch, new, new, {"listed": True, "pid": os.getpid()})
    assert error.value.code == "conversation_backgrounded"
    recorded = fixture["tmux"].get_current("fixture", "seat-0")["moved_to_background"]
    assert (recorded["old_session_id"], recorded["new_session_id"]) == (fixture["previous"]["session_id"], new)
    assert recorded["host_pid"] == os.getpid() and recorded["host_birth"]
    assert (error.value.details["old_session_id"], error.value.details["new_session_id"],
            error.value.details["host_pid"]) == (recorded["old_session_id"], new, os.getpid())


def test_an_unknown_host_is_recorded_as_unknown(native_slot, monkeypatch):
    new = str(uuid.uuid4())
    with pytest.raises(SessionError) as error:
        _hook_with(native_slot, monkeypatch, new, new, None)
    assert error.value.code == "conversation_backgrounded" and error.value.details["host_pid"] is None
    assert native_slot["tmux"].get_current("fixture", "seat-0")["moved_to_background"]["host_pid"] is None


@pytest.mark.parametrize("moved", [None, "another-session"])
def test_a_hook_with_another_id_stays_an_owner_mismatch_without_a_move_record(native_slot, monkeypatch, moved):
    with pytest.raises(SessionError) as error:
        _hook_with(native_slot, monkeypatch, str(uuid.uuid4()), moved, {"listed": True, "pid": 1})
    assert error.value.code == "owner_mismatch"
    assert not native_slot["tmux"].get_current("fixture", "seat-0").get("moved_to_background")


def test_a_session_start_hook_records_that_it_started(native_slot, monkeypatch):
    """SESSION-011. A hook that Claude ends at its limit leaves no result; the record is how `start` learns it ended."""
    fixture = native_slot
    pending = pending_run(fixture, monkeypatch)
    native_id = str(uuid.uuid4())
    payload = {"session_id": native_id, "hook_event_name": "SessionStart", "cwd": str(fixture["seat"]),
               "source": "startup"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    internal.register_from_hook("pending-run", str(fixture["config"]), pending["socket_path"],
                                expected_session_id=native_id, endpoint=fixture["endpoint"])
    record = json.loads(hook_started.path(fixture["project"], "pending-run").read_text())
    assert record["run_id"] == "pending-run" and record["pid"] == os.getpid()
    assert record["birth"] == process.birth(os.getpid())
    assert hook_started.ended(fixture["project"], "pending-run") is False       # this process is alive


def test_a_hook_record_says_ended_only_for_its_own_dead_process(tmp_path):
    from types import SimpleNamespace

    project = SimpleNamespace(runtime_path=tmp_path)
    assert hook_started.ended(project, "run-a") is False                            # no record: not an end
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        record = {"run_id": "run-a", "pid": child.pid, "birth": process.birth(child.pid)}
        path = hook_started.path(project, "run-a")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(record))
        assert hook_started.ended(project, "run-a") is False                        # the hook is running
        assert hook_started.ended(project, "run-b") is False                        # another run's record is not read
        child.kill()
        child.wait()
        assert hook_started.ended(project, "run-a") is True
        path.write_text(json.dumps({**record, "birth": "linux:other:1"}))           # a reused PID is another process
        assert hook_started.ended(project, "run-a") is True
        path.write_text(json.dumps({**record, "run_id": "run-b"}))
        assert hook_started.ended(project, "run-a") is False
        path.write_text("{not json")
        assert hook_started.ended(project, "run-a") is False
    finally:
        child.kill()
        child.wait()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the creation time is read from /proc")
def test_the_hook_deadline_counts_from_the_creation_of_its_process(monkeypatch):
    """Claude's hook limit counts from the process start; a loaded host spends seconds in the interpreter's start
    and imports, which the budget must include."""
    monkeypatch.setattr(process, "age", lambda pid: 7.0)
    now = time.monotonic()
    budget = internal._HOOK_BUDGET
    assert budget - 7 - 0.5 < internal._hook_deadline() - now <= budget - 7 + 0.5
    monkeypatch.setattr(process, "age", lambda pid: 600.0)                          # a wrong clock costs the cap at most
    assert internal._hook_deadline() - time.monotonic() > budget - internal._STARTUP_CAP - 0.5


def test_the_registration_deadline_is_shorter_than_the_hook_limit_claude_is_given():
    """SESSION-013. The hook writes its own failure before Claude ends it: every step of the deadline fits inside
    the settings `timeout`, and the settings `timeout` is the one the registration's budget derives from."""
    from agent_session.providers.claude import ClaudeProvider

    limit = hook_started.HOOK_TIMEOUT
    assert limit == 60 and internal._HOOK_BUDGET < limit
    assert internal._BINDING_TIMEOUT < internal._HOOK_BUDGET      # and it ends `_PUBLISH_RESERVE` before the deadline anyway
    assert internal._STARTUP_CAP < internal._HOOK_BUDGET - internal._PUBLISH_RESERVE      # the binding keeps time
    context = {"python": sys.executable, "library_path": "/lib", "run_id": "r", "config_path": "/c", "socket_path": "/s",
               "expected_session_id": str(uuid.uuid4())}
    hooks = ClaudeProvider().registration_hooks(context)
    assert {entry["hooks"][0]["timeout"] for entries in hooks.values() for entry in entries} == {limit}


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the creation time is read from /proc")
def test_process_age_is_the_seconds_since_creation():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        time.sleep(1.2)
        assert 1.0 <= process.age(child.pid) < 60
    finally:
        child.kill()
        child.wait()
    assert process.age(child.pid) == 0.0                                               # a gone process has no age
