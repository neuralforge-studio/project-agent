"""SSH transport, native ownership and authoritative CR Result return contracts."""

import json
from pathlib import Path
import shlex
import subprocess
import socket
import uuid
from types import SimpleNamespace

import pytest

from agent_session import remote, remote_bridge, remote_runtime
from agent_session.config import Project, RemoteSeat
from agent_session.errors import SessionError


def test_remote_seat_before_any_ssh_launch_uses_only_its_local_waiting_process(monkeypatch):
    from agent_session import process
    from agent_session.lifecycle import Manager
    manager = object.__new__(Manager)
    manager.remaining = lambda: 5
    manager.tmux = SimpleNamespace(pane_info=lambda pane: {"pane_dead": True})
    monkeypatch.setattr(remote, "observe", lambda *args, **kwargs: pytest.fail("No remote launch was attempted"))
    monkeypatch.setattr(process, "alive", lambda *args: False)
    monkeypatch.setattr(process, "group_alive", lambda *args: False)
    observed = manager._observe({"remote_seat": {"host": "macbook-worker"}, "pane_id": "%1",
                                 "provider_launch_attempted": False, "registered": False,
                                 "placeholder_pid": 123, "placeholder_birth": "known", "placeholder_process_group": 123})
    assert observed["stopped"] is True


def test_native_stop_can_finish_after_the_ssh_display_already_left(monkeypatch):
    calls = []

    def command(*args):
        calls.append(args)
        assert args == ("list-clients", "-F", "#{session_name}")
        return ""

    manager = SimpleNamespace(project=SimpleNamespace(project_id="remote-test"), tmux=SimpleNamespace(command=command))
    monkeypatch.setattr(remote_runtime, "_current", lambda *args: (manager, {}))
    assert remote_runtime.dispatch("/remote/seat", "detach", {"run_id": "a" * 32}, None) == {}
    assert len(calls) == 1


@pytest.mark.parametrize("existing", ["socket", "file"])
def test_reconnect_clears_only_its_owned_forwarding_socket(monkeypatch, existing):
    run_id = uuid.uuid4().hex
    path = Path("/tmp/as-u-" + run_id[:24] + ".sock")
    listener = socket.socket(socket.AF_UNIX)
    monkeypatch.setattr(remote_runtime, "_current", lambda *args: (None, {}))
    try:
        if existing == "socket":
            listener.bind(str(path))
            assert remote_runtime.dispatch("/remote/seat", "prepare_display", {"run_id": run_id}, None) == {}
            assert not path.exists()
            replacement = socket.socket(socket.AF_UNIX)
            try:
                replacement.bind(str(path))
            finally:
                replacement.close()
        else:
            path.write_text("keep this file")
            with pytest.raises(SessionError) as caught:
                remote_runtime.dispatch("/remote/seat", "prepare_display", {"run_id": run_id}, None)
            assert caught.value.code == "owner_mismatch"
            assert path.read_text() == "keep this file"
    finally:
        listener.close()
        path.unlink(missing_ok=True)


def test_transport_keeps_paths_and_arguments_out_of_the_ssh_command(monkeypatch):
    seat = RemoteSeat("macbook-worker", "/remote/space 'quote';$(touch sentinel)",
                      "/python path/python'3;touch sentinel")
    payload = {"args": ["show", "branch;$(touch sentinel)"]}
    captured = {}

    def run(argv, **kwargs):
        captured.update(argv=argv, **kwargs)
        return subprocess.CompletedProcess(argv, 0, json.dumps({"ok": True, "data": "remote-output"}), "")

    monkeypatch.setattr(remote.subprocess, "run", run)
    assert remote.call(seat, "git", payload) == "remote-output"
    argv = captured["argv"]
    assert argv[-2] == "macbook-worker" and argv[-3] == "--"
    assert shlex.split(argv[-1]) == [seat.python, "-c", remote.BOOTSTRAP]
    request = json.loads(captured["input"])
    assert request["seat"] == str(seat) and request["payload"] == payload
    assert str(seat) not in argv[-1]
    assert not captured.get("shell", False)


@pytest.mark.parametrize("host", ["-oProxyCommand=bad", "book;touch bad", "book\nother", "book $(id)"])
def test_transport_rejects_host_command_injection_before_ssh(monkeypatch, host):
    monkeypatch.setattr(remote.subprocess, "run", lambda *args, **kwargs: pytest.fail("SSH must not run"))
    with pytest.raises(SessionError) as error:
        remote.call(RemoteSeat(host, "/remote/seat"), "is_git")
    assert error.value.code == "registry_invalid" and error.value.exit_code == 2


@pytest.mark.parametrize("failure", ["disconnect", "timeout", "missing_ssh", "invalid_json", "incomplete_reply"])
def test_transport_failure_is_unknown_with_exit_four(monkeypatch, failure):
    def run(argv, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        if failure == "missing_ssh":
            raise FileNotFoundError("ssh")
        stdout = {"disconnect": "", "invalid_json": "partial", "incomplete_reply": '{"ok":true}'}[failure]
        return subprocess.CompletedProcess(argv, 255 if failure == "disconnect" else 0, stdout, "connection lost")

    monkeypatch.setattr(remote.subprocess, "run", run)
    with pytest.raises(SessionError) as error:
        remote.call(RemoteSeat("macbook-worker", "/remote/seat"), "observe")
    assert error.value.code == "remote_unknown" and error.value.exit_code == 4
    assert error.value.details["host"] == "macbook-worker"


def test_remote_native_error_keeps_its_code_and_exit(monkeypatch):
    response = {"ok": False, "error": {"code": "owner_mismatch", "message": "Native run changed.",
                                       "exit_code": 4, "details": {"run_id": "old"}}}
    monkeypatch.setattr(remote.subprocess, "run", lambda argv, **kwargs:
                        subprocess.CompletedProcess(argv, 0, json.dumps(response), ""))
    with pytest.raises(SessionError) as error:
        remote.call(RemoteSeat("macbook-worker", "/remote/seat"), "observe")
    assert error.value.code == "owner_mismatch" and error.value.exit_code == 4
    assert error.value.details == {"run_id": "old"}


@pytest.fixture
def cr(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    root = tmp_path / "cr"
    (root / "in-progress").mkdir(parents=True)
    path = root / "in-progress/TOOL-001-example.md"
    original = ("# TOOL-001: Example\n\n- Opened: 2026-11-08\n- Scope: tool\n- Severity: S2\n\n"
                "## Contract\nWork in the assigned seat.\n\n## Disposition\n- Leader: approved.\n\n"
                "## Result\nInitial result.\n")
    path.write_text(original, encoding="utf-8")
    project = Project(base, str(base), "example", "codex", (), tmp_path / "project.json", path_cr=root)
    return project, path, original, {"job_id": "TOOL-001"}


def test_result_return_preserves_new_leader_disposition_and_accepts_a_retry(cr):
    project, path, original, settings = cr
    current = original.replace("- Leader: approved.", "- Leader: approved.\n- Leader: keep this decision.")
    path.write_text(current, encoding="utf-8")
    updated = original.replace("Initial result.", "- 제출 commit: " + "a" * 40 + "\n- Verification: PASS.")
    remote_bridge.sync_result(project, settings, original, updated)
    expected = updated.replace("- Leader: approved.", "- Leader: approved.\n- Leader: keep this decision.")
    assert path.read_text(encoding="utf-8") == expected
    remote_bridge.sync_result(project, settings, original, updated)
    assert path.read_text(encoding="utf-8") == expected


def test_first_remote_result_can_fill_an_empty_result_section(cr):
    project, path, original, settings = cr
    original = original.replace("Initial result.\n", "")
    path.write_text(original, encoding="utf-8")
    updated = original + "- Verification: PASS.\n"
    remote_bridge.sync_result(project, settings, original, updated)
    assert path.read_text(encoding="utf-8") == updated


def test_result_return_rejects_worker_changes_outside_result(cr):
    project, path, original, settings = cr
    changed = original.replace("Work in the assigned seat.", "Change the scope.")
    with pytest.raises(SessionError) as error:
        remote_bridge.sync_result(project, settings, original, changed)
    assert error.value.code == "remote_result_invalid"
    assert path.read_text(encoding="utf-8") == original


def test_result_conflict_preserves_the_authoritative_cr(cr):
    project, path, original, settings = cr
    current = original.replace("Initial result.", "Leader's independent result.")
    path.write_text(current, encoding="utf-8")
    updated = original.replace("Initial result.", "Worker result.")
    with pytest.raises(SessionError) as error:
        remote_bridge.sync_result(project, settings, original, updated)
    assert error.value.code == "remote_result_conflict" and error.value.exit_code == 4
    assert path.read_text(encoding="utf-8") == current


def test_result_return_rejects_a_cr_that_left_in_progress(cr):
    project, path, original, settings = cr
    done = project.path_cr / "done"
    done.mkdir()
    moved = done / path.name
    path.rename(moved)
    with pytest.raises(SessionError) as error:
        remote_bridge.sync_result(project, settings, original, original.replace("Initial result.", "Late result."))
    assert error.value.code == "target_changed"
    assert moved.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("changed", ["run_id", "job_id", "project_id", "window_id", "pane_id", "server_pid",
                                     "server_started", "server_birth", "socket_path", "session_id", "endpoint"])
def test_native_observation_rejects_replaced_execution_before_provider_call(monkeypatch, changed):
    run_id = "a" * 32
    native = {"run_id": run_id, "job_id": "TOOL-001", "project_id": "remote-example", "window_id": "@1",
              "pane_id": "%1", "server_pid": 123, "server_started": "started-1", "server_birth": "birth-1", "socket_path": "/tmp/native.sock",
              "session_id": "thread-1", "endpoint": "unix:///tmp/daemon-1.sock"}
    actual = {**native, changed: "replaced"}
    manager = SimpleNamespace(project=SimpleNamespace(project_id="remote-example"),
                              tmux=SimpleNamespace(get_current=lambda *args: actual),
                              _observe=lambda *args: pytest.fail("A replaced native run must not be observed"))
    monkeypatch.setattr(remote_runtime, "_manager", lambda directory: (manager, {"seat": "/remote/seat", "job_id": "TOOL-001"}))
    with pytest.raises(SessionError) as error:
        remote_runtime.dispatch("/remote/seat", "observe", {"run_id": run_id, "native": native}, Path("/runtime"))
    assert error.value.code in {"execution_unknown", "owner_mismatch"}
    assert error.value.exit_code == 4


def test_launch_response_loss_retries_the_same_run_without_git_preparation(tmp_path, monkeypatch):
    from agent_session import git_ops, jobs, remote_lifecycle
    from agent_session.lifecycle import Manager

    cr = tmp_path / "cr.md"
    cr.write_text("# TOOL-001: Example\n\n## Result\n", encoding="utf-8")
    metadata = {"run_id": "a" * 32, "window_id": "@1", "target": "seat-0", "job_id": "TOOL-001",
                "job": {"job_id": "TOOL-001", "path": str(cr)}, "registered": False,
                "provider_launch_attempted": False,
                "remote_seat": {"host": "macbook-worker", "path": "/remote/seat"}}
    launches = []

    def write_meta(window, update):
        metadata.update(update)
        return dict(metadata)

    native = {"run_id": metadata["run_id"], "session_id": "thread-1", "endpoint": "unix:///tmp/native.sock"}

    def request(meta, operation, payload=None, timeout=30):
        if operation == "launch":
            assert metadata["provider_launch_attempted"] is True
            launches.append(meta["run_id"])
            if len(launches) == 1:
                raise SessionError("remote_unknown", "The accepted launch lost its response.", 4)
            return {}
        assert operation == "poll"
        return {"ready": True, "native": native}

    manager = SimpleNamespace(project=SimpleNamespace(args_for=lambda role: (), base=tmp_path),
                              tmux=SimpleNamespace(write_meta=write_meta), remaining=lambda: 30,
                              _authorize=lambda *args: None,
                              _wait_ready=lambda meta: {"run_id": meta["run_id"], "ready": True},
                              _sweep=lambda target: {})
    monkeypatch.setattr(remote_bridge, "prepare", lambda *args: {"remote_listen": "/tmp/uplink", "token": "token"})
    monkeypatch.setattr(remote, "run_call", request)
    monkeypatch.setattr(remote_lifecycle, "attach", lambda manager, meta: meta)
    monkeypatch.setattr(jobs, "lookup", lambda *args: {"state": "in-progress"})
    monkeypatch.setattr(git_ops, "prepare", lambda *args: pytest.fail("Git must not run again after an uncertain launch"))
    with pytest.raises(SessionError) as error:
        remote_lifecycle.launch(manager, dict(metadata))
    assert error.value.code == "remote_unknown"
    result = Manager._start_existing(manager, dict(metadata))
    assert result["ready"] is True
    assert launches == [metadata["run_id"], metadata["run_id"]]


def test_duplicate_remote_launch_does_not_create_another_controller(tmp_path, monkeypatch):
    run_id = "b" * 32
    directory = tmp_path / "run"
    directory.mkdir()
    saved = {"seat": "/remote/seat", "job_id": "TOOL-001", "run_id": run_id, "socket_path": "/tmp/native.sock"}
    (directory / "execution.json").write_text(json.dumps(saved))
    monkeypatch.setattr(remote_runtime, "_directory", lambda identity: directory)
    monkeypatch.setattr(remote_runtime.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("The run already exists"))
    assert remote_runtime.dispatch("/remote/seat", "launch", {"run_id": run_id, "job": {"job_id": "TOOL-001"}}, tmp_path) == saved
    with pytest.raises(SessionError) as error:
        remote_runtime.dispatch("/remote/seat", "launch", {"run_id": run_id, "job": {"job_id": "TOOL-002"}}, tmp_path)
    assert error.value.code == "owner_mismatch"


def test_dead_report_bridge_reuses_its_token_and_replaces_its_stale_socket(tmp_path, monkeypatch):
    import socket
    import uuid
    from agent_session import process

    run_id = "c" * 32
    directory = tmp_path / "agent/runs" / run_id
    directory.mkdir(parents=True)
    listen = Path("/tmp") / ("as-test-" + uuid.uuid4().hex + ".sock")
    with socket.socket(socket.AF_UNIX) as stale:
        stale.bind(str(listen))
    settings = {"base": str(tmp_path), "config_path": str(tmp_path / "project.json"),
                "socket_path": "/tmp/leader.sock", "run_id": run_id, "target": "seat-0", "job_id": "TOOL-001",
                "token": "preserved-token", "listen": str(listen), "remote_listen": "/tmp/remote-uplink.sock",
                "pid": 2**30, "birth": "dead-controller"}
    (directory / "bridge.json").write_text(json.dumps(settings))
    manager = SimpleNamespace(project=SimpleNamespace(base=tmp_path, runtime_path=tmp_path / "agent",
                                                      config_path=tmp_path / "project.json"))
    children = []
    popen = remote_bridge.subprocess.Popen

    def capture(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(remote_bridge.subprocess, "Popen", capture)
    try:
        prepared = remote_bridge.prepare(manager, {"run_id": run_id})
        assert prepared["token"] == settings["token"]
        assert prepared["pid"] != settings["pid"] and process.alive(prepared["pid"], prepared["birth"])
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(5)
            client.connect(str(listen))
            client.sendall(json.dumps({"token": "wrong", "run_id": run_id}).encode() + b"\n")
            response = json.loads(client.makefile("rb").readline())
        assert response["ok"] is False and response["error"]["code"] == "owner_mismatch"
    finally:
        for child in children:
            child.terminate()
            child.wait(timeout=5)
        listen.unlink(missing_ok=True)


def test_late_remote_binding_can_finish_after_a_user_dialog(tmp_path, monkeypatch):
    from contextlib import nullcontext

    native = {"run_id": "d" * 32, "job_id": "TOOL-001", "registered": True, "ready": False, "pane_id": "%1"}
    directory = tmp_path / "run"
    directory.mkdir()

    def publish(meta):
        native["ready"] = True
        return {"ready": True}

    manager = SimpleNamespace(project=SimpleNamespace(project_id="remote-example"),
                              tmux=SimpleNamespace(get_current=lambda *args: dict(native), capture_pane=lambda pane: ""),
                              provider=SimpleNamespace(startup_dialog=lambda screen: None),
                              _lock=lambda slot: nullcontext(), _wait_ready=publish)
    monkeypatch.setattr(remote_runtime, "_directory", lambda identity: directory)
    monkeypatch.setattr(remote_runtime, "_manager", lambda path: (manager, {"seat": "/remote/seat", "job_id": "TOOL-001"}))
    result = remote_runtime.dispatch("/remote/seat", "poll", {"run_id": native["run_id"]}, tmp_path)
    assert result["ready"] is True and result["dialog"] is None
    assert not (directory / "start-error.json").exists()


def test_report_rechecks_the_run_under_control_lock_before_changing_result(tmp_path, monkeypatch):
    import socket
    from contextlib import contextmanager
    from agent_session import lifecycle

    run_id = "e" * 32
    settings = {"base": str(tmp_path), "config_path": str(tmp_path / "project.json"), "socket_path": "/tmp/leader.sock",
                "target": "seat-0", "job_id": "TOOL-001", "token": "token", "run_id": run_id}
    path = tmp_path / "bridge.json"
    path.write_text(json.dumps(settings))
    first = {"run_id": run_id, "target": "seat-0", "session_id": "thread-1", "ready": True}
    locked = False

    @contextmanager
    def control_lock(slot):
        nonlocal locked
        locked = True
        yield

    def current(*args):
        return {**first, "run_id": "new-run"} if locked else first

    manager = SimpleNamespace(project=SimpleNamespace(project_id="example"),
                              tmux=SimpleNamespace(get_current=current), _lock=control_lock)
    recheck = lifecycle.Manager._same
    manager._same = lambda selected: recheck(manager, selected)
    monkeypatch.setattr(lifecycle, "Manager", lambda *args, **kwargs: manager)
    monkeypatch.setenv("CODEX_THREAD_ID", "previous-thread")
    monkeypatch.setattr(remote_bridge, "sync_result", lambda *args: pytest.fail("A replaced Worker must not write Result"))
    client, server = socket.socketpair()
    try:
        client.sendall(json.dumps({"token": "token", "run_id": run_id, "session_id": "thread-1", "operation": "send"}).encode() + b"\n")
        remote_bridge.Handler(server, None, SimpleNamespace(settings_path=path))
        response = json.loads(client.makefile("rb").readline())
        assert response["ok"] is False and response["error"]["code"] == "target_changed"
    finally:
        client.close()
        server.close()


def test_user_dialog_does_not_become_a_permanent_remote_start_error(tmp_path, monkeypatch):
    directory = tmp_path / "run"
    directory.mkdir()
    job = {"job_id": "TOOL-001", "base": {"base_hash": "a" * 40}}
    (directory / "request.json").write_text(json.dumps({"run_id": "f" * 32, "job": job}))
    state = {"0": {}}

    def wait_for_user(*args, **kwargs):
        raise SessionError("needs_user_action", "Answer the workspace dialog.", 3)

    manager = SimpleNamespace(store=SimpleNamespace(update=lambda change: change(state)),
                              _context=lambda *args, **kwargs: {}, _new_window=lambda context: context,
                              _launch=wait_for_user, _handoff_path=lambda context: directory / "handoff.md")
    monkeypatch.setattr(remote_runtime, "_manager", lambda path: (manager, {"seat": "/remote/seat"}))
    remote_runtime.controller(directory)
    assert not (directory / "start-error.json").exists()
    assert state["0"]["job_id"] == "TOOL-001"


@pytest.mark.parametrize("fresh", [True, False])
def test_remote_handoff_uses_native_freshness_before_updating_the_central_copy(tmp_path, monkeypatch, fresh):
    from agent_session.lifecycle import Manager

    meta = {"run_id": "a" * 32, "target": "seat-2", "remote_seat": {"host": "macbook-worker", "path": "/remote/seat"}}
    manager = SimpleNamespace(project=SimpleNamespace(runtime_path=tmp_path / "agent"), remaining=lambda: 30)
    manager._handoff_path = lambda current: Manager._handoff_path(manager, current)
    manager._fresh_handoff = lambda current: Manager._fresh_handoff(manager, current)
    central = manager._handoff_path(meta)
    central.parent.mkdir(parents=True)
    central.write_text("Older central handoff.\n", encoding="utf-8")
    text = "HEAD: " + "b" * 40 + "\nNext: continue the remote verification.\n"

    def native_handoff(current, operation, timeout=30):
        assert current["run_id"] == meta["run_id"] and operation == "handoff"
        return {"fresh": fresh, "text": text}

    monkeypatch.setattr(remote, "run_call", native_handoff)
    result = manager._fresh_handoff(meta)
    if fresh:
        assert result == str(central)
        assert central.read_text(encoding="utf-8") == text
    else:
        assert result is None
        assert central.read_text(encoding="utf-8") == "Older central handoff.\n"
        with pytest.raises(SessionError) as error:
            Manager._require_handoff(manager, meta)
        assert error.value.code == "handoff_required"


def test_native_controller_includes_the_transferred_handoff_in_the_new_run_prompt(tmp_path, monkeypatch):
    from agent_session.lifecycle import Manager

    directory = tmp_path / "new-run"
    directory.mkdir()
    run_id = "c" * 32
    text = "HEAD: " + "d" * 40 + "\nPending: review the remote CPU result.\n"
    job = {"job_id": "TOOL-001", "title": "Example", "path": "/runtime/cr.md", "cwd": ".",
           "mode": "write", "branch": "cr/TOOL-001", "base": {"base_hash": "e" * 40}}
    (directory / "request.json").write_text(json.dumps({"run_id": run_id, "job": job, "handoff_text": text}), encoding="utf-8")
    state = {"0": {}}
    captured = {}
    context = {"python": "/usr/bin/python3", "library_path": "/runtime/agent-session", "run_id": run_id,
               "config_path": "/runtime/project.json", "socket_path": "/tmp/native.sock", "cwd": "/remote/seat",
               "seat": 0, "seat_root": "/remote/seat", "target": "seat-0", "job": job}
    manager = SimpleNamespace(project=SimpleNamespace(provider="codex"),
                              store=SimpleNamespace(update=lambda change: change(state)),
                              _context=lambda *args, **kwargs: dict(context), _new_window=lambda current: current,
                              _handoff_path=lambda current: directory / "next-handoff.md")

    def launch(current, request):
        captured["handoff_file"] = current["handoff_file"]
        captured["prompt"] = Manager._write_prompt(manager, current, request)

    manager._launch = launch
    monkeypatch.setattr(remote_runtime, "_manager", lambda path: (manager, {"seat": "/remote/seat"}))
    remote_runtime.controller(directory)
    assert Path(captured["handoff_file"]).read_text(encoding="utf-8") == text
    assert text in captured["prompt"] and run_id in captured["prompt"]
    assert "배정 CR: TOOL-001" in captured["prompt"]
    assert not (directory / "start-error.json").exists()


@pytest.fixture
def remote_launch_files(tmp_path, monkeypatch):
    import hashlib
    from agent_session import process

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    spawned = []

    def spawn(*args, **kwargs):
        child = SimpleNamespace(pid=100 + len(spawned), env=kwargs["env"])
        spawned.append(child)
        return child

    monkeypatch.setattr(remote_runtime.subprocess, "Popen", spawn)
    monkeypatch.setattr(process, "birth", lambda pid: "birth-" + str(pid))
    monkeypatch.setattr(process, "alive", lambda pid, birth=None: pid == 700)

    def bundle(name):
        source = home / ".cache/agent-session/runtime" / hashlib.sha256(name.encode()).hexdigest()
        source.mkdir(parents=True)
        (source / "ready").touch()
        for skill in ("project-team", "project-item"):
            target = source / "guidance/codex/skills" / skill
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text(name + " " + skill)
        return source

    def request(run_id="1" * 32):
        return {"run_id": run_id, "args": [], "job": {"job_id": "TOOL-001", "mode": "write", "cwd": ".",
                "base": {"base_hash": "a" * 40}}, "cr_text": "# TOOL-001: Example\n\n## Result\n", "uplink": {}}

    return SimpleNamespace(home=home, spawned=spawned, bundle=bundle, request=request)


def test_runtime_owned_skill_links_follow_the_next_source_bundle(remote_launch_files):
    env = remote_launch_files
    first, second = env.bundle("first"), env.bundle("second")
    remote_runtime.dispatch("/remote/seat", "launch", env.request("1" * 32), first)
    remote_runtime.dispatch("/remote/seat", "launch", env.request("2" * 32), second)
    for name in ("project-team", "project-item"):
        link = env.home / ".codex/skills" / name
        assert link.is_symlink()
        assert link.resolve() == second / "guidance/codex/skills" / name


def test_skill_refresh_preserves_user_installs_and_user_replaced_links(remote_launch_files):
    env = remote_launch_files
    first, second = env.bundle("first"), env.bundle("second")
    skills = env.home / ".codex/skills"
    skills.mkdir(parents=True)
    user_install = skills / "project-team"
    user_install.mkdir()
    (user_install / "SKILL.md").write_text("User-maintained skill.")
    remote_runtime.dispatch("/remote/seat", "launch", env.request("1" * 32), first)
    user_target = env.home / "user-project-item"
    user_target.mkdir()
    (skills / "project-item").unlink()
    (skills / "project-item").symlink_to(user_target, target_is_directory=True)
    remote_runtime.dispatch("/remote/seat", "launch", env.request("2" * 32), second)
    assert not user_install.is_symlink()
    assert (user_install / "SKILL.md").read_text() == "User-maintained skill."
    assert (skills / "project-item").resolve() == user_target


def test_legacy_runtime_skill_links_can_refresh_without_claiming_other_links(remote_launch_files):
    env = remote_launch_files
    first, second = env.bundle("first"), env.bundle("second")
    skills = env.home / ".codex/skills"
    skills.mkdir(parents=True)
    (skills / "project-team").symlink_to(first / "guidance/codex/skills/project-team", target_is_directory=True)
    user_target = env.home / "user-project-item"
    user_target.mkdir()
    (skills / "project-item").symlink_to(user_target, target_is_directory=True)
    remote_runtime.dispatch("/remote/seat", "launch", env.request("2" * 32), second)
    assert (skills / "project-team").resolve() == second / "guidance/codex/skills/project-team"
    assert (skills / "project-item").resolve() == user_target


@pytest.fixture
def failed_remote_controller(remote_launch_files, monkeypatch):
    from contextlib import nullcontext

    env = remote_launch_files
    source = env.bundle("retry")
    payload = env.request()
    saved = remote_runtime.dispatch("/remote/seat", "launch", payload, source)
    directory = remote_runtime._directory(payload["run_id"])
    state = {"0": {}}
    observed = {"native": None, "fail": "prepare", "windows": 0, "launches": 0}

    def current(*args):
        return observed["native"]

    def window(context):
        observed["windows"] += 1
        if observed["fail"] == "prepare":
            raise SessionError("provider_unavailable", "Install the provider CLI.", 3)
        observed["native"] = {**context, "job_id": "TOOL-001", "window_id": "@1", "pane_id": "%1",
                              "provider_launch_attempted": False, "registered": False, "ready": False,
                              "placeholder_pid": 700, "placeholder_birth": "birth-700", "placeholder_process_group": 700}
        return observed["native"]

    def launch(context, request=None):
        observed["launches"] += 1
        if observed["fail"] == "config":
            raise SessionError("unsupported_sandbox", "Correct the provider configuration.", 3)
        observed["native"].update(provider_launch_attempted=True, registered=True, ready=True, session_id="thread-1")

    manager = SimpleNamespace(project=SimpleNamespace(project_id="remote-example", base=directory / "control"),
                              store=SimpleNamespace(update=lambda change: change(state)),
                              _context=lambda *args, **kwargs: {"run_id": payload["run_id"], "target": "seat-0", "job": payload["job"],
                                  "endpoint": "unix:///tmp/original-provider.sock",
                                  "library_path": str(Path(json.loads((directory / "request.json").read_text())["source"]) / "agent-session")},
                              _new_window=window, _launch=launch, _handoff_path=lambda context: directory / "handoff.md",
                              _lock=lambda slot: nullcontext(), _adopted=lambda native, slot: native,
                              provider=SimpleNamespace(prepare_context=lambda context: context),
                              tmux=SimpleNamespace(get_current=current, has_session=lambda name: observed["native"] is not None,
                                  managed_windows=lambda *args: ["@1"] if observed["native"] else [],
                                  pane_info=lambda pane: {"pane_pid": 700, "pane_dead": False}))
    manager.tmux.write_meta = lambda window, update: observed["native"].update(update) or observed["native"]
    monkeypatch.setattr(remote_runtime, "_manager", lambda path: (manager, json.loads((directory / "execution.json").read_text())))
    return SimpleNamespace(env=env, source=source, payload=payload, saved=saved, directory=directory,
                           state=state, observed=observed, manager=manager)


@pytest.mark.parametrize("failure", ["prepare", "config"])
def test_failed_provider_preparation_retries_the_same_run_after_the_cause_is_fixed(failed_remote_controller, failure):
    case = failed_remote_controller
    case.observed["fail"] = failure
    with pytest.raises(SessionError):
        remote_runtime.controller(case.directory)
    assert (case.directory / "start-error.json").is_file()
    case.observed["fail"] = None
    corrected_source = case.env.bundle("corrected")
    retried = remote_runtime.dispatch("/remote/seat", "launch", case.payload, corrected_source)
    assert len(case.env.spawned) == 2
    assert retried["run_id"] == case.saved["run_id"]
    remote_runtime.controller(case.directory)
    assert case.observed["native"]["ready"] is True
    assert case.observed["native"]["window_id"] == "@1"
    assert case.observed["native"]["library_path"] == str(corrected_source / "agent-session")
    assert case.env.spawned[-1].env["PYTHONPATH"] == str(corrected_source / "agent-session")
    assert case.observed["windows"] == (2 if failure == "prepare" else 1)
    assert case.state["0"] == {"job_id": "TOOL-001", "git_hash": "a" * 40}
    assert not (case.directory / "start-error.json").exists()


@pytest.mark.parametrize("uncertain", ["controller_alive", "missing_controller_birth", "launch_attempted", "attempt_missing",
                                       "registered", "missing_native", "placeholder_changed", "server_changed", "placeholder_dead"])
def test_retry_preserves_uncertain_or_already_started_native_execution(failed_remote_controller, monkeypatch, uncertain):
    from agent_session import process

    case = failed_remote_controller
    case.observed["fail"] = "config"
    with pytest.raises(SessionError):
        remote_runtime.controller(case.directory)
    original_error = (case.directory / "start-error.json").read_text()
    record = case.directory / "execution.json"
    if uncertain == "controller_alive":
        monkeypatch.setattr(process, "alive", lambda *args: True)
    elif uncertain == "missing_controller_birth":
        saved = json.loads(record.read_text())
        saved.pop("controller_birth")
        record.write_text(json.dumps(saved))
    elif uncertain == "launch_attempted":
        case.observed["native"]["provider_launch_attempted"] = True
    elif uncertain == "attempt_missing":
        case.observed["native"].pop("provider_launch_attempted")
    elif uncertain == "registered":
        case.observed["native"]["registered"] = True
    elif uncertain == "missing_native":
        case.observed["native"] = None
    elif uncertain == "server_changed":
        case.observed["native"]["server_birth"] = "changed-server"
    elif uncertain == "placeholder_dead":
        monkeypatch.setattr(process, "alive", lambda *args: False)
    else:
        case.manager.tmux.pane_info = lambda pane: {"pane_pid": 701, "pane_dead": False}
    try:
        remote_runtime.dispatch("/remote/seat", "launch", case.payload, case.source)
    except SessionError as error:
        assert error.exit_code == 4
    assert len(case.env.spawned) == 1
    assert (case.directory / "start-error.json").read_text() == original_error


def test_retry_cannot_treat_lost_native_evidence_as_a_first_preparation_failure(failed_remote_controller):
    case = failed_remote_controller
    with pytest.raises(SessionError):
        remote_runtime.controller(case.directory)
    path = case.directory / "start-error.json"
    error = json.loads(path.read_text())
    error.pop("before_window", None)
    path.write_text(json.dumps(error))
    before = path.read_text()
    with pytest.raises(SessionError) as caught:
        remote_runtime.dispatch("/remote/seat", "launch", case.payload, case.source)
    assert caught.value.code == "remote_unknown" and caught.value.exit_code == 4
    assert len(case.env.spawned) == 1 and path.read_text() == before


def test_read_only_remote_controller_preserves_the_read_only_instruction(tmp_path, monkeypatch):
    directory = tmp_path / "read-only-run"
    directory.mkdir()
    job = {"job_id": "TOOL-001", "mode": "read-only", "base": {"base_hash": "a" * 40}}
    (directory / "request.json").write_text(json.dumps({"run_id": "f" * 32, "job": job}))
    captured = {}
    manager = SimpleNamespace(store=SimpleNamespace(update=lambda change: change({"0": {}})),
                              _context=lambda *args, **kwargs: {}, _new_window=lambda context: context,
                              _launch=lambda context, request: captured.update(request=request),
                              _handoff_path=lambda context: directory / "handoff.md")
    monkeypatch.setattr(remote_runtime, "_manager", lambda path: (manager, {"seat": "/remote/seat"}))
    remote_runtime.controller(directory)
    assert "읽기 전용 조사·검증" in captured["request"]
    assert "commit·push하십시오" not in captured["request"]
    assert "업무 파일 수정·commit·push는 금지합니다" in captured["request"]


def test_safe_prelaunch_retry_can_refresh_an_unbound_endpoint_and_then_pins_the_bound_session(failed_remote_controller):
    case = failed_remote_controller
    case.observed["fail"] = "config"
    with pytest.raises(SessionError):
        remote_runtime.controller(case.directory)
    waiting = dict(case.observed["native"])
    original_endpoint = waiting["endpoint"]
    refreshed_endpoint = "unix:///tmp/restarted-provider.sock"
    case.manager.provider.prepare_context = lambda context: {**context, "endpoint": refreshed_endpoint}
    case.observed["fail"] = None
    remote_runtime.dispatch("/remote/seat", "launch", case.payload, case.source)
    remote_runtime.controller(case.directory)
    case.manager._observe = lambda current: {"endpoint": current["endpoint"], "session_id": current["session_id"]}
    observed = remote_runtime.dispatch("/remote/seat", "observe", {"run_id": case.payload["run_id"], "native": waiting}, case.source)
    assert observed == {"endpoint": refreshed_endpoint, "session_id": "thread-1"}
    bound = {**case.observed["native"], "endpoint": original_endpoint}
    with pytest.raises(SessionError) as caught:
        remote_runtime.dispatch("/remote/seat", "observe", {"run_id": case.payload["run_id"], "native": bound}, case.source)
    assert caught.value.code == "owner_mismatch" and caught.value.exit_code == 4


def test_unbound_endpoint_change_requires_a_proven_safe_prelaunch_retry(monkeypatch):
    run_id = "a" * 32
    original = {"run_id": run_id, "job_id": "TOOL-001", "project_id": "remote-example", "window_id": "@1",
                "pane_id": "%1", "server_pid": 123, "server_birth": "birth-1", "socket_path": "/tmp/native.sock",
                "session_id": None, "endpoint": "unix:///tmp/original-provider.sock"}
    changed = {**original, "provider_launch_attempted": True, "endpoint": "unix:///tmp/unexplained-provider.sock"}
    manager = SimpleNamespace(project=SimpleNamespace(project_id="remote-example"),
                              tmux=SimpleNamespace(get_current=lambda *args: changed),
                              _observe=lambda *args: pytest.fail("An unproven endpoint must not be used"))
    monkeypatch.setattr(remote_runtime, "_manager", lambda directory: (manager, {"seat": "/remote/seat", "job_id": "TOOL-001"}))
    with pytest.raises(SessionError) as caught:
        remote_runtime.dispatch("/remote/seat", "observe", {"run_id": run_id, "native": original}, Path("/runtime"))
    assert caught.value.code == "owner_mismatch" and caught.value.exit_code == 4
