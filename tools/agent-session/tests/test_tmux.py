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
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from agent_session.config import Project
from agent_session.errors import SessionError
from agent_session.lifecycle import Manager
from agent_session.process import alive, birth
from agent_session.tmux import Tmux
from agent_session_fixture import stop_test_server


@pytest.fixture
def tmux():
    if not shutil.which("tmux"):
        pytest.skip("tmux is unavailable")
    name = "agent-session-test-" + uuid.uuid4().hex[:12]
    instance = Tmux(socket_name=name)
    original_argv = instance._argv
    instance._argv = lambda arguments: ["tmux", "-f", os.devnull] + original_argv(arguments)[1:]
    yield instance
    stop_test_server(name)


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
    instance._run = lambda *arguments, **options: "\t".join(["@1", "%1", pid, dead, "", ""])
    return instance


@pytest.mark.parametrize(("pid", "dead", "expected"), [("", "1", None), ("4242", "1", 4242), ("4242", "0", 4242)])
def test_dead_pane_may_have_no_pid(pid, dead, expected):
    # tmux 3.8 clears pane_pid once the pane process exits; tmux 3.6a keeps it.
    assert fixed_pane(pid, dead).pane_info("%1")["pane_pid"] == expected


def test_live_pane_without_pid_is_incomplete():
    with pytest.raises(SessionError) as error:
        fixed_pane("", "0").pane_info("%1")
    assert error.value.code == "tmux_unknown"
    assert error.value.exit_code == 4
    assert error.value.message == "The managed pane observation is incomplete."


@pytest.mark.parametrize(("raw", "count"), [
    ("@1\t%1\t\t0\t\t", 6),                   # no pid on a live pane
    ("@1\t%1\t4242\t1", 4),                    # too few fields
    ("@1\t%1\t42\t42\t0\t\t", 7),             # a tab inside a value
    ("", 1),
])
def test_incomplete_observation_reports_what_tmux_returned(raw, count):
    instance = Tmux(socket_name="unused")
    instance._run = lambda *arguments, **options: raw
    with pytest.raises(SessionError) as error:
        instance.pane_info("%7")
    assert error.value.details == {"pane": "%7", "raw": raw, "field_count": count}


def test_pane_whose_directory_has_a_tab_is_still_observed(tmp_path, tmux):
    # tmux prints a tab inside pane_current_path as is, which must not shift the other fields.
    directory = tmp_path / "with\ttab"
    directory.mkdir()
    meta = tmux.create_window("demo", "demo-worker-0-J-20261103-01", directory,
                              {"base": str(tmp_path), "run_id": "run-one", "target": "seat-0",
                               "job_id": "J-20261103-01"})
    pane = tmux.pane_info(meta["pane_id"])
    assert pane["pane_pid"] == meta["placeholder_pid"] and pane["pane_dead"] is False


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


def test_two_digit_seat_target_has_its_own_current_pointer(tmp_path, tmux):
    meta = new_window(tmux, tmp_path, target="seat-10")
    assert tmux.get_current("demo", "seat-10") is None
    tmux.set_current("demo", "seat-10", meta)
    assert tmux.get_current("demo", "seat-10")["run_id"] == "run-one"
    assert tmux.get_current("demo", "seat-1") is None


@pytest.mark.parametrize("target", ["seat-01", "seat-", "seat-1a", "seat--1"])
def test_malformed_seat_target_is_rejected(tmp_path, tmux, target):
    new_window(tmux, tmp_path)      # the session exists, so only the target is wrong
    with pytest.raises(SessionError) as error:
        new_window(tmux, tmp_path, run="run-two", target=target)
    assert error.value.code == "tmux_input"
    with pytest.raises(SessionError) as error:
        tmux.get_current("demo", target)
    assert error.value.code == "tmux_input"


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

    assert wait_for(exit_signal) in ("15", "term")  # tmux uses a signal name on macOS
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


@pytest.mark.parametrize("mode", ["copy-mode", "view-mode"])
@pytest.mark.parametrize("after_literal", [False, True])
def test_exit_refuses_tmux_mode_and_preserves_partial_input(tmp_path, tmux, mode, after_literal, request, monkeypatch):
    meta = new_window(tmux, tmp_path)
    tmux.set_current("demo", "seat-0", meta)
    ready, observation = tmp_path / "ready.txt", tmp_path / "input.json"
    fixture = Path(__file__).parent / "fixtures" / "paste_sensitive_tui.py"
    script = tmp_path / "launch.sh"
    script.write_text("#!/bin/bash\nexec " + shlex.join([sys.executable, "-u", str(fixture),
                                                      str(ready), str(observation)]) + "\n")
    launched = tmux.launch(meta["window_id"], tmp_path, script)
    wait_for(ready.exists)
    client = subprocess.Popen(tmux._argv(["-C", "attach", "-t", "demo"]),
                              stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def detach():
        client.stdin.close()
        client.wait(timeout=10)

    request.addfinalizer(detach)
    wait_for(lambda: tmux.command("list-clients", "-F", "#{client_pid}").strip())
    def open_mode():
        if mode == "copy-mode":
            tmux.command("copy-mode", "-t", meta["pane_id"])
        else:
            # run-shell output opens view-mode without sending anything to the TUI.
            tmux.command("run-shell", "-t", meta["pane_id"], "printf 'fixture output\\n'")

    if after_literal:
        run = tmux._run

        def mode_after_text(*arguments, **options):
            result = run(*arguments, **options)
            if arguments == ("send-keys", "-t", meta["pane_id"], "-l", "/exit"):
                open_mode()
            return result

        monkeypatch.setattr(tmux, "_run", mode_after_text)
    else:
        open_mode()
    with pytest.raises(SessionError) as error:
        tmux.send_exit(meta["pane_id"])
    assert (error.value.code, error.value.exit_code) == ("pane_input_blocked", 4), error.value.as_dict()
    assert error.value.details["pane_mode"] == mode
    assert error.value.details["exit_delivery"] == {"stage": "enter" if after_literal else "literal",
                                                   "literal_confirmed": after_literal}
    assert not observation.exists()
    assert alive(launched["cli_pid"], launched["cli_birth"])
    assert tmux.command("display-message", "-p", "-t", meta["pane_id"], "#{pane_mode}") == mode

    # Only the isolated test operator closes its mode, then makes a new explicit request.
    tmux.command("send-keys", "-X", "-t", meta["pane_id"], "cancel")
    if after_literal:
        tmux.command("send-keys", "-t", meta["pane_id"], "Enter")
    else:
        tmux.send_exit(meta["pane_id"])
    wait_for(observation.exists)
    assert json.loads(observation.read_text()) == {"text": "/exit", "enter_suppressed": False, "enter_count": 1}
    assert wait_for(lambda: tmux.pane_info(meta["pane_id"])["pane_dead"]
                    and not alive(launched["cli_pid"], launched["cli_birth"]))


@pytest.mark.parametrize("raw", ["", "0", "2\t", "0\tview-mode", "1\t", "1\tcopy-mode\textra"])
def test_exit_sends_no_keys_when_the_input_mode_is_unknown(tmp_path, tmux, monkeypatch, raw):
    meta = new_window(tmux, tmp_path)
    tmux.set_current("demo", "seat-0", meta)
    script = tmp_path / "launch.sh"
    script.write_text("#!/bin/bash\nexec /bin/cat\n")
    launched = tmux.launch(meta["window_id"], tmp_path, script)
    run = tmux._run

    def incomplete_mode(*arguments, **options):
        if arguments == ("display-message", "-p", "-t", meta["pane_id"], "#{pane_in_mode}\t#{pane_mode}"):
            return raw
        assert arguments[0] != "send-keys", "Unknown input mode must not receive keys."
        return run(*arguments, **options)

    monkeypatch.setattr(tmux, "_run", incomplete_mode)
    with pytest.raises(SessionError) as error:
        tmux.send_exit(meta["pane_id"])
    assert (error.value.code, error.value.exit_code) == ("tmux_unknown", 4)
    assert error.value.details["exit_delivery"] == {"stage": "literal", "literal_confirmed": False}
    assert alive(launched["cli_pid"], launched["cli_birth"])


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


def test_notify_reaches_each_attached_client_and_says_none_when_nobody_is_attached(tmux, tmp_path):
    new_window(tmux, tmp_path)
    assert tmux.notify("agent shutdown: 대상 1", 1000) == 0
    log = tmp_path / "client.out"
    client = subprocess.Popen(["tmux", *tmux._argv([])[1:], "-C", "attach", "-t", "demo"],
                              stdin=subprocess.PIPE, stdout=log.open("w"), stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 60               # a loaded machine attaches slowly
        while tmux.notify("agent shutdown: 100# #{pane_id}", 1000) != 1:
            assert time.monotonic() < deadline, "The control client did not attach."
            time.sleep(0.1)
        while "%message agent shutdown: 100# #{pane_id}" not in log.read_text():
            assert time.monotonic() < deadline, "The client did not receive the message."
            time.sleep(0.1)
    finally:
        client.stdin.close()
        client.wait(timeout=10)


def test_bell_is_output_to_the_pane_tty_and_flags_only_that_window(tmux, tmp_path):
    first = new_window(tmux, tmp_path, run="run-one")
    second = new_window(tmux, tmp_path, run="run-two", target="seat-1", job="J-20261103-02")
    tmux.ring_bell(second["pane_id"])
    flags = lambda: dict(line.split(" ") for line in tmux.command(
        "list-windows", "-t", "demo", "-F", "#{window_id} #{window_bell_flag}").splitlines())
    assert wait_for(lambda: flags().get(second["window_id"]) == "1")
    assert flags()[first["window_id"]] == "0"
    with pytest.raises(SessionError) as error:
        tmux.ring_bell("%999999")
    assert error.value.code in ("tmux_command_failed", "tmux_unknown")


def retired_window(tmux, tmp_path, run="run-one", target="seat-0", job="J-20261103-01", panes=1):
    """A launched run that ended: a dead managed pane, optionally beside panes that a person added."""
    meta = new_window(tmux, tmp_path, run=run, target=target, job=job)
    tmux.set_current("demo", target, meta)
    tmux.write_meta(meta["window_id"], {
        "provider_launch_attempted": True, "registered": True, "ready": True, "session_id": "session-one",
        "cli_pid": meta["placeholder_pid"], "cli_birth": meta["placeholder_birth"], "process_group": 1,
        "hook_observations": {"Stop": {"observed_at": "then"}}, "message_to": "peer-one",
        "controller_pid": 7, "controller_birth": "then", "control_pending": True, "control_operation": "restart",
        "last_background_clear": {"run_id": run}, "launch_file": "launch-one.sh", "provider_name": "name-one",
        "start_error": "old failure", "resume": True, "handoff_file": "handoff-one.md", "leader_request": "ask"})
    for _ in range(panes - 1):
        tmux.command("split-window", "-d", "-t", meta["window_id"], "sleep", "86400")
    os.kill(meta["placeholder_pid"], 15)
    assert wait_for(lambda: tmux.pane_info(meta["pane_id"])["pane_dead"])
    return tmux.read_meta(meta["window_id"])


def next_run(tmp_path, run="run-two", job="J-20261103-02", **extra):
    return {"base": str(tmp_path), "run_id": run, "target": "seat-0", "job_id": job, **extra}


def test_a_retired_window_goes_to_the_next_run_and_reads_like_a_new_window(tmp_path, tmux):
    old = retired_window(tmux, tmp_path, panes=3)
    people = [pane for pane in tmux.command("list-panes", "-t", old["window_id"], "-F", "#{pane_id}").splitlines()
              if pane != old["pane_id"]]
    assert len(people) == 2
    metadata = next_run(tmp_path, session_id="session-two")
    reused = tmux.reuse_window("demo", "demo-worker-0-J-20261103-02", tmp_path, metadata, old)
    # The window, the managed pane's place, and the people's panes stay.
    assert (reused["window_id"], reused["pane_id"]) == (old["window_id"], old["pane_id"])
    assert tmux.command("list-panes", "-t", old["window_id"], "-F", "#{pane_id}").splitlines() == [old["pane_id"], *people]
    assert tmux.command("display-message", "-p", "-t", old["window_id"], "#{window_name}") == "demo-worker-0-J-20261103-02"
    pane = tmux.pane_info(old["pane_id"])
    assert pane["pane_dead"] is False and pane["pane_pid"] == reused["placeholder_pid"] != old["placeholder_pid"]
    assert alive(reused["placeholder_pid"], reused["placeholder_birth"])
    assert tmux.get_current("demo", "seat-0")["run_id"] == "run-two"
    # It reads as the window that the same call would have made: no value of the retired run is left.
    fresh = tmux.create_window("other", "other-worker-0-J-20261103-02", tmp_path, {**metadata, "base": str(tmp_path)})
    per_window = {"window_id", "pane_id", "project_id", "placeholder_pid", "placeholder_birth",
                  "placeholder_process_group"}
    assert {key: value for key, value in reused.items() if key in fresh and key not in per_window} == {
        key: value for key, value in fresh.items() if key not in per_window}
    assert {key: reused[key] for key in set(reused) - set(fresh)} == {
        "cli_pid": None, "cli_birth": None, "process_group": None, "background_pids": [],
        "last_background_clear": None, "hook_observations": {}, "controller_pid": None, "controller_birth": None,
        "control_pending": False, "control_operation": None, "message_to": None, "start_error": None,
        "launch_file": None, "provider_name": None, "resume": False, "expected_session_id": None,
        "handoff_file": None, "leader_request": None, "remote_seat": None, "remote_native": None,
        "upstream": None, "upstream_bin": None, "moved_to_background": None}
    assert reused["registered"] is reused["ready"] is reused["stopping"] is False
    assert reused["provider_launch_attempted"] is False


def test_a_window_is_not_handed_over_while_its_managed_pane_lives(tmp_path, tmux):
    live = new_window(tmux, tmp_path)
    tmux.set_current("demo", "seat-0", live)
    before = tmux.read_meta(live["window_id"])
    with pytest.raises(SessionError) as error:
        tmux.reuse_window("demo", "demo-worker-0-J-20261103-02", tmp_path, next_run(tmp_path), live)
    assert error.value.code == "target_running"
    assert tmux.read_meta(live["window_id"]) == before
    assert tmux.pane_info(live["pane_id"])["pane_pid"] == live["placeholder_pid"]
    assert tmux.command("display-message", "-p", "-t", live["window_id"], "#{window_name}") == "demo-worker-0-J-20261103-01"
    assert tmux.get_current("demo", "seat-0")["run_id"] == "run-one"


@pytest.mark.parametrize("change", ["other_run", "server", "metadata_key", "other_target"])
def test_a_refused_hand_over_changes_nothing(tmp_path, tmux, change):
    old = retired_window(tmux, tmp_path)
    expected, metadata = old, next_run(tmp_path)
    if change == "other_run":
        expected = {**old, "run_id": "another-run"}
    elif change == "server":                       # a window that tmux-resurrect restored carries another server
        tmux.command("set-option", "-w", "-t", old["window_id"], "@agent_session_server_pid", "1")
    elif change == "metadata_key":                 # a value that no run of this version writes cannot be replaced
        tmux.command("set-option", "-w", "-t", old["window_id"], "@agent_session_legacy_value", "1")
    else:
        metadata = {**metadata, "target": "seat-1"}
    before = tmux.read_meta(old["window_id"])
    with pytest.raises(SessionError) as error:
        tmux.reuse_window("demo", "demo-worker-0-J-20261103-02", tmp_path, metadata, expected)
    assert error.value.code in ("target_changed", "tmux_owner_mismatch", "window_unreusable")
    assert tmux.read_meta(old["window_id"]) == before
    assert tmux.pane_info(old["pane_id"])["pane_dead"] is True
    assert tmux.command("display-message", "-p", "-t", old["window_id"], "#{window_name}") == "demo-worker-0-J-20261103-01"
    if change != "server":                         # the doctored server value no longer matches the pointer
        assert tmux.get_current("demo", "seat-0")["run_id"] == "run-one"


def test_a_hand_over_that_fails_after_the_respawn_ends_its_own_waiting_process(tmp_path, tmux, monkeypatch):
    old = retired_window(tmux, tmp_path)
    before = tmux.read_meta(old["window_id"])

    def refuse(window_id, updates):
        raise SessionError("tmux_command_failed", "The fixture refused the metadata write.", 5)

    monkeypatch.setattr(tmux, "_option_arguments", refuse)
    with pytest.raises(SessionError) as error:
        tmux.reuse_window("demo", "demo-worker-0-J-20261103-02", tmp_path, next_run(tmp_path), old)
    assert error.value.code == "tmux_command_failed"
    # The window is the retired run's evidence again: its old values, a dead pane, the old pointer.
    assert wait_for(lambda: tmux.pane_info(old["pane_id"])["pane_dead"])
    assert tmux.read_meta(old["window_id"]) == before
    assert tmux.get_current("demo", "seat-0")["run_id"] == "run-one"


def test_a_write_naming_the_retired_run_cannot_reach_the_window_of_the_next_run(tmp_path, tmux):
    old = retired_window(tmux, tmp_path)
    reused = tmux.reuse_window("demo", "demo-worker-0-J-20261103-02", tmp_path, next_run(tmp_path), old)
    for updates in ({"hook_observations": {"Stop": {}}}, {"registered": True, "session_id": "session-one"},
                    {"control_pending": False}, {"cli_pid": 1}):
        with pytest.raises(SessionError) as error:
            tmux.write_meta(old["window_id"], {"run_id": "run-one", **updates})
        assert error.value.code == "target_changed"
    assert tmux.read_meta(old["window_id"]) == reused
