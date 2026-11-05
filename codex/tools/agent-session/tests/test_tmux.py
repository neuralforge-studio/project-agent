import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_session.config import Project
from agent_session.errors import SessionError
from agent_session.lifecycle import Manager
from agent_session.process import alive, birth
from agent_session.tmux import Tmux


@pytest.fixture
def tmux():
    if not shutil.which("tmux"):
        pytest.skip("tmux is unavailable")
    name = "agent-session-test-" + uuid.uuid4().hex[:12]
    instance = Tmux(socket_name=name)
    original_argv = instance._argv
    instance._argv = lambda arguments: ["tmux", "-f", os.devnull] + original_argv(arguments)[1:]
    yield instance
    subprocess.run(["tmux", "-L", name, "kill-server"], capture_output=True, timeout=10)


def new_window(tmux, tmp_path, run="run-one", target="seat-0", job="J-20261103-01"):
    return tmux.create_window("demo", f"demo-worker-0-{job}", tmp_path,
                              {"base": str(tmp_path), "run_id": run, "target": target, "job_id": job})


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.01)
    raise AssertionError("The managed pane did not reach the expected condition")


def fixed_pane(pid, dead):
    instance = Tmux(socket_name="unused")
    instance._run = lambda *arguments, **options: "\t".join(["@1", "%1", pid, "", "bash", dead, "", ""])
    return instance


@pytest.mark.parametrize(("pid", "dead", "expected"), [("", "1", None), ("4242", "1", 4242), ("4242", "0", 4242)])
def test_dead_pane_may_have_no_pid(pid, dead, expected):
    # tmux 3.8 clears pane_pid once the pane process exits; tmux 3.6a keeps it.
    assert fixed_pane(pid, dead).pane_info("%1")["pane_pid"] == expected


def test_live_pane_without_pid_is_incomplete():
    with pytest.raises(SessionError) as error:
        fixed_pane("", "0").pane_info("%1")
    assert error.value.code == "tmux_unknown"


def test_window_and_server_identity_are_exact_and_current(tmp_path, tmux):
    meta = new_window(tmux, tmp_path)
    assert meta["window_id"].startswith("@") and meta["pane_id"].startswith("%")
    assert meta["server_pid"] != os.getpid()
    assert meta["server_started"].isdigit()
    assert meta["server_birth"] == birth(meta["server_pid"])
    assert meta["socket_path"] == tmux.effective_socket()
    assert meta["provider_launch_attempted"] is False
    assert tmux.command("show-options", "-w", "-v", "-t", meta["window_id"], "remain-on-exit") == "on"
    assert tmux.get_current("demo", "seat-0") is None
    tmux.set_current("demo", "seat-0", meta)
    assert tmux.get_current("demo", "seat-0")["run_id"] == "run-one"


def test_bad_metadata_update_has_no_partial_side_effect(tmp_path, tmux):
    meta = new_window(tmux, tmp_path)
    with pytest.raises(SessionError):
        tmux.write_meta(meta["window_id"], {"ready": True, "run_id": "wrong-run"})
    assert tmux.read_meta(meta["window_id"])["ready"] is False


def test_reused_placeholder_pid_is_not_replaced(tmp_path, tmux):
    meta = new_window(tmux, tmp_path)
    tmux.set_current("demo", "seat-0", meta)
    tmux.write_meta(meta["window_id"], {"placeholder_birth": "different-creation"})
    script = tmp_path / "launch.sh"
    script.write_text("#!/bin/bash\nexit 0\n")
    with pytest.raises(SessionError) as error:
        tmux.launch(meta["window_id"], tmp_path, script)
    assert error.value.code == "target_changed"
    assert tmux.pane_info(meta["pane_id"])["pane_dead"] is False
    assert tmux.read_meta(meta["window_id"])["provider_launch_attempted"] is False
    tmux.write_meta(meta["window_id"], {"session_id": "native-id", "ready": True})
    assert tmux.get_current("demo", "seat-0")["session_id"] == "native-id"


def test_mutable_updates_merge_and_identity_cannot_be_rewritten(tmp_path, tmux):
    meta = new_window(tmux, tmp_path)
    tmux.set_current("demo", "seat-0", meta)
    tmux.write_meta(meta["window_id"], {"session_id": "uuid", "message_to": "worker [abc123]"})
    tmux.write_meta(meta["window_id"], {"ready": True})
    current = tmux.get_current("demo", "seat-0")
    assert current["session_id"] == "uuid" and current["ready"] is True
    with pytest.raises(SessionError) as error:
        tmux.write_meta(meta["window_id"], {"run_id": "late-old-run"})
    assert error.value.code == "target_changed"
    assert tmux.get_current("demo", "seat-0")["run_id"] == "run-one"


def test_metadata_values_round_trip_shell_and_format_characters(tmp_path, tmux):
    # show-options prints $ as \$ inside quotes, which shlex keeps and JSON rejects (SESSION-002).
    text = 'cost $HOME \\$x back\\slash "quoted" #{pane_id} 한글'
    value = {"message": text, "items": [text]}
    meta = new_window(tmux, tmp_path)
    written = tmux.write_meta(meta["window_id"], {"note": text, "nested": value})
    assert written["note"] == text and written["nested"] == value
    read = tmux.read_meta(meta["window_id"])
    assert read["note"] == text and read["nested"] == value and read["run_id"] == "run-one"


def test_metadata_read_is_one_snapshot_when_keys_are_added_meanwhile(tmp_path, tmux):
    # Registration sets session_id, then registered=True, as separate options. A read that lists
    # the keys before that write and reads values after it must not see registered without its ID.
    meta = new_window(tmux, tmp_path)
    run = tmux._run
    written = []

    def register_after_first_call(*arguments, **options):
        output = run(*arguments, **options)
        if not written:
            written.append(True)
            tmux.write_meta(meta["window_id"], {"session_id": "native-id", "registered": True})
        return output

    tmux._run = register_after_first_call
    read = tmux.read_meta(meta["window_id"])
    assert written and (read["registered"], read.get("session_id")) in ((False, None), (True, "native-id"))


def test_registration_update_is_never_seen_half_written(tmp_path, tmux):
    # SESSION-003: a start that read registered=True before message_to raised KeyError in _session.
    meta = tmux.create_window("demo", "demo-worker-0-J-20261103-01", tmp_path,
                              {"base": str(tmp_path), "run_id": "run-one", "target": "seat-0",
                               "job_id": "J-20261103-01", "provider": "claude"})
    window = meta["window_id"]
    reader = Tmux(socket_name=tmux.socket_name)
    run = tmux._run
    records = []

    def read_after_each_call(*arguments, **options):
        output = run(*arguments, **options)
        records.append(reader.read_meta(window))
        return output

    tmux._run = read_after_each_call
    tmux.write_meta(window, {"session_id": "native-id", "registered": True, "message_to": "worker [abc123]",
                             "ends_with_separator": "a;", "spaced_separator": "x ; y"})
    tmux._run = run
    assert records
    before = (None, False, None)
    after = ("native-id", True, "worker [abc123]")
    for record in records:
        if record["registered"]:
            assert Manager._session(record) == {"session_id": "native-id", "message_to": "worker [abc123]"}
    for record in records:
        assert (record.get("session_id"), record["registered"], record.get("message_to")) in (before, after)
    read = reader.read_meta(window)
    assert read["ends_with_separator"] == "a;" and read["spaced_separator"] == "x ; y"


def test_unowned_and_restored_session_options_do_not_get_adopted(tmp_path, tmux):
    tmux.command("new-session", "-d", "-s", "user-session", "sleep", "86400")
    with pytest.raises(SessionError) as error:
        tmux.create_window("user-session", "worker", tmp_path,
                           {"base": str(tmp_path), "run_id": "one", "target": "leader", "job_id": None})
    assert error.value.code == "tmux_owner_mismatch"
    meta = new_window(tmux, tmp_path)
    tmux.set_current("demo", "seat-0", meta)
    owner = json.loads(tmux.command("show-options", "-qv", "-t", "demo", "@agent_session_owner"))
    owner["server_pid"] += 1
    tmux.command("set-option", "-t", "demo", "@agent_session_owner", json.dumps(owner))
    with pytest.raises(SessionError) as error:
        tmux.get_current("demo", "seat-0")
    assert error.value.code == "tmux_owner_mismatch"


def test_launch_records_attempt_before_exec_and_exit_keeps_dead_pane(tmp_path, tmux):
    meta = new_window(tmux, tmp_path)
    tmux.set_current("demo", "seat-0", meta)
    observed = tmp_path / "attempt.txt"
    script = tmp_path / "launch.sh"
    command = ["tmux", "-S", meta["socket_path"], "show-options", "-w", "-v", "-t", meta["window_id"],
               "@agent_session_provider_launch_attempted"]
    received = tmp_path / "received.txt"
    python_code = ("import sys; line = sys.stdin.readline(); open(sys.argv[1], 'w').write(line); "
                   "sys.exit(0 if line.strip() == '/exit' else 9)")
    script.write_text("#!/bin/bash\n" + shlex.join(command) + " > " + shlex.quote(str(observed)) + "\nexec "
                      + shlex.join([sys.executable, "-u", "-c", python_code, str(received)]) + "\n")
    launched = tmux.launch(meta["window_id"], tmp_path, script)
    assert wait_for(lambda: observed.exists())
    assert observed.read_text().strip() == "true"
    assert launched["provider_launch_attempted"] is True
    assert launched["cli_pid"] != meta["placeholder_pid"]
    assert launched["cli_birth"] == birth(launched["cli_pid"])
    with pytest.raises(SessionError) as error:
        tmux.launch(meta["window_id"], tmp_path, script)
    assert error.value.code == "launch_already_attempted"
    with pytest.raises(SessionError):
        tmux.write_meta(meta["window_id"], {"provider_launch_attempted": False})
    tmux.send_exit(meta["pane_id"])

    # tmux 3.4 may never record pane_dead_status (see the paste test); the CLI read /exit and the
    # lifecycle stop evidence (dead pane, CLI not alive) hold without it.
    def exited():
        return (tmux.pane_info(meta["pane_id"])["pane_dead"]
                and not alive(launched["cli_pid"], launched["cli_birth"]))

    assert wait_for(exited)
    assert received.read_text() == "/exit\n"
    assert tmux.read_meta(meta["window_id"])["run_id"] == "run-one"


def test_find_native_session_returns_connection_in_its_project(tmp_path, tmux):
    meta = new_window(tmux, tmp_path)
    project = Project(tmp_path, str(tmp_path), "demo", "codex", (), tmp_path / "project.json")
    tmux.write_meta(meta["window_id"], {"session_id": "native-id"})
    assert tmux.find_by_session(project, "native-id")["pane_id"] == meta["pane_id"]
    assert tmux.find_by_session(project, "other-id") is None


def test_controller_is_started_by_tmux_outside_the_callers_process(tmp_path, tmux):
    new_window(tmux, tmp_path)
    result_path = tmp_path / "controller-result.json"
    python_code = "import json,os,sys; open(sys.argv[1], 'w').write(json.dumps({'pid':os.getpid(),'parent':os.getppid(),'cwd':os.getcwd()}))"
    script = tmp_path / "controller.sh"
    script.write_text("#!/bin/bash\nexec " + shlex.join([sys.executable, "-c", python_code, str(result_path)]) + "\n")
    submitted = tmux.run_controller(script, tmp_path)
    assert submitted["submitted"] is True
    wait_for(lambda: result_path.exists() and bool(result_path.read_text()))
    result = json.loads(result_path.read_text())
    assert result["parent"] != os.getpid()
    assert result["pid"] != os.getpid()
    assert result["cwd"] == str(tmp_path)


def test_missing_current_window_preserves_pointer_and_reports_missing_evidence(tmp_path, tmux):
    missing = new_window(tmux, tmp_path)
    tmux.set_current("demo", "seat-0", missing)
    survivor = new_window(tmux, tmp_path, run="other-run", target="leader", job=None)
    before = tmux.command("show-options", "-qv", "-t", "demo", "@agent_session_current_seat_0")
    tmux.command("kill-window", "-t", missing["window_id"])
    with pytest.raises(SessionError) as error:
        tmux.get_current("demo", "seat-0")
    assert error.value.code == "execution_evidence_missing"
    assert error.value.exit_code == 4
    assert error.value.details == {"target": "seat-0", "window_id": missing["window_id"], "run_id": "run-one"}
    assert tmux.command("show-options", "-qv", "-t", "demo", "@agent_session_current_seat_0") == before
    assert tmux.command("list-windows", "-t", "demo", "-F", "#{window_id}").splitlines() == [survivor["window_id"]]


def zombie_signal(pid):
    """The terminating signal of an unreaped child, read from /proc (Linux).

    tmux 3.4 can miss SIGCHLD while libutempter waits for its helper; the pane is then dead
    but pane_dead_signal stays empty and the child remains a zombie with its wait status.
    """
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except (FileNotFoundError, IndexError):
        return None                                  # reaped meanwhile: tmux records the signal
    if fields[0] != "Z":
        return None
    signal = int(fields[-1]) & 0x7F
    return str(signal) if signal else None


def test_unlaunched_placeholder_stops_with_term_and_retains_runtime_evidence(tmp_path, tmux):
    meta = new_window(tmux, tmp_path)
    tmux.set_current("demo", "seat-0", meta)
    assert meta["placeholder_process_group"] == os.getpgid(meta["placeholder_pid"])
    assert tmux.request_placeholder_stop(meta["window_id"])["requested"] is True

    def exit_signal():
        pane = tmux.pane_info(meta["pane_id"])
        if not pane["pane_dead"] or alive(meta["placeholder_pid"], meta["placeholder_birth"]):
            return None
        return pane["pane_dead_signal"] or zombie_signal(meta["placeholder_pid"])

    assert wait_for(exit_signal) == "15"
    current = tmux.get_current("demo", "seat-0")
    assert current["run_id"] == meta["run_id"]
    assert current["provider_launch_attempted"] is False
    assert current["registered"] is False
    assert tmux.request_placeholder_stop(meta["window_id"]) == {"requested": False, "pane_dead": True}


def test_placeholder_stop_rejects_another_process_birth_without_a_signal(tmp_path, tmux):
    meta = new_window(tmux, tmp_path)
    tmux.set_current("demo", "seat-0", meta)
    tmux.write_meta(meta["window_id"], {"placeholder_birth": "another-process"})
    with pytest.raises(SessionError) as error:
        tmux.request_placeholder_stop(meta["window_id"])
    assert error.value.code == "target_changed"
    assert tmux.pane_info(meta["pane_id"])["pane_dead"] is False


@pytest.mark.parametrize("attempted", [True, None])
def test_placeholder_stop_rejects_attempted_or_unknown_provider_launch(tmp_path, tmux, attempted):
    meta = new_window(tmux, tmp_path)
    tmux.set_current("demo", "seat-0", meta)
    tmux.write_meta(meta["window_id"], {"provider_launch_attempted": attempted})
    with pytest.raises(SessionError) as error:
        tmux.request_placeholder_stop(meta["window_id"])
    assert error.value.code == "launch_already_attempted"
    assert tmux.pane_info(meta["pane_id"])["pane_dead"] is False


def test_exit_waits_for_paste_sensitive_tui_to_submit_one_enter(tmp_path, tmux):
    meta = new_window(tmux, tmp_path)
    tmux.set_current("demo", "seat-0", meta)
    ready = tmp_path / "ready.txt"
    observation = tmp_path / "input.json"
    fixture = Path(__file__).parent / "fixtures" / "paste_sensitive_tui.py"
    script = tmp_path / "launch.sh"
    script.write_text("#!/bin/bash\nexec " + shlex.join([sys.executable, "-u", str(fixture),
                                                      str(ready), str(observation)]) + "\n")
    launched = tmux.launch(meta["window_id"], tmp_path, script)
    wait_for(ready.exists)
    tmux.send_exit(meta["pane_id"])
    wait_for(observation.exists)
    event = json.loads(observation.read_text())
    if event["enter_suppressed"]:
        assert tmux.pane_info(meta["pane_id"])["pane_dead"] is False
    assert event == {"text": "/exit", "enter_suppressed": False, "enter_count": 1}

    # tmux 3.4 loses SIGCHLD when the TUI exits during libutempter's helper wait, so
    # pane_dead_status can stay empty. Use the lifecycle stop evidence instead.
    def exited():
        return (tmux.pane_info(meta["pane_id"])["pane_dead"]
                and not alive(launched["cli_pid"], launched["cli_birth"]))

    assert wait_for(exited)


def test_pointer_is_cleared_only_for_the_named_run(tmp_path, tmux):
    meta = new_window(tmux, tmp_path)
    tmux.set_current("demo", "seat-0", meta)
    assert tmux.clear_current("demo", "seat-0", "other-run") is False
    assert tmux.get_current("demo", "seat-0")["run_id"] == "run-one"
    assert tmux.clear_current("demo", "seat-0", "run-one") is True
    assert tmux.get_current("demo", "seat-0") is None
    assert tmux.clear_current("demo", "seat-0", "run-one") is False
    assert tmux.read_meta(meta["window_id"])["run_id"] == "run-one"


def test_retired_window_closes_only_with_one_dead_managed_pane(tmp_path, tmux):
    survivor = new_window(tmux, tmp_path, run="leader-run", target="leader", job=None)
    retired = new_window(tmux, tmp_path)
    other = new_window(tmux, tmp_path, run="run-two", target="seat-1", job="J-20261103-02")
    assert tmux.managed_windows("demo", "seat-0") == [retired["window_id"]]
    with pytest.raises(SessionError) as error:
        tmux.close_window(retired["window_id"], retired)
    assert error.value.code == "target_running"
    os.kill(retired["placeholder_pid"], 15)
    assert wait_for(lambda: tmux.pane_info(retired["pane_id"])["pane_dead"])
    extra = tmux.command("split-window", "-d", "-P", "-F", "#{pane_id}", "-t", retired["window_id"], "sleep", "86400")
    with pytest.raises(SessionError) as error:
        tmux.close_window(retired["window_id"], retired)
    assert error.value.code == "window_shared"
    tmux.command("kill-pane", "-t", extra)
    with pytest.raises(SessionError) as error:
        tmux.close_window(retired["window_id"], {**retired, "run_id": "another-run"})
    assert error.value.code == "target_changed"
    assert tmux.close_window(retired["window_id"], retired) is True
    windows = tmux.command("list-windows", "-t", "demo", "-F", "#{window_id}").splitlines()
    assert windows == [survivor["window_id"], other["window_id"]]
    assert tmux.managed_windows("demo", "seat-0") == []
