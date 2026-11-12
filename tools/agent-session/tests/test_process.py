import errno
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_session import process
from agent_session.errors import SessionError
from wait_limit import command_timeout


def wait_for(predicate):
    deadline = time.monotonic() + command_timeout()
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("Process observation did not reach the expected condition")


def test_creation_fingerprint_and_reused_identity():
    identity = process.birth(os.getpid())
    assert isinstance(identity, str) and identity
    assert process.alive(os.getpid(), identity)
    assert not process.alive(os.getpid(), "different-creation")
    assert process.birth(2**30) is None
    assert not process.alive(2**30)


def test_group_and_descendants_are_observed_without_signalling():
    code = "import subprocess,time; c=subprocess.Popen(['sleep','30']); print(c.pid,flush=True); time.sleep(30)"
    child = subprocess.Popen([sys.executable, "-u", "-c", code], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
    grandchild = None
    try:
        grandchild = int(child.stdout.readline().strip())
        assert process.group_alive(child.pid)
        assert grandchild in wait_for(lambda: process.descendants(child.pid))
        assert child.pid not in process.descendants(child.pid)
    finally:
        if grandchild is not None:
            os.kill(grandchild, 15)
        child.terminate()
        child.wait(timeout=command_timeout())
    wait_for(lambda: not process.group_alive(child.pid))


def test_permission_or_observation_failure_is_not_an_empty_process_list(monkeypatch):
    monkeypatch.setattr(process.sys, "platform", "darwin")
    monkeypatch.setattr(process.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 1, "", "ps unavailable"))
    with pytest.raises(SessionError) as error:
        process.birth(os.getpid())
    assert error.value.code == "process_unknown"
    assert error.value.exit_code == 4


def test_ps_fallback_uses_creation_time_and_ignores_zombies(monkeypatch):
    monkeypatch.setattr(process.sys, "platform", "darwin")
    rows = "123 1 123 S Mon Nov  3 10:00:00 2026\n124 123 123 Z Mon Nov  3 10:00:01 2026\n"
    monkeypatch.setattr(process.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 0, rows, ""))
    assert process.birth(123) == "darwin:Mon Nov  3 10:00:00 2026"
    assert process.alive(123)
    assert not process.alive(124)
    assert process.descendants(123) == []


@pytest.mark.parametrize("error_type,number", [(FileNotFoundError, errno.ENOENT),
                                               (ProcessLookupError, errno.ESRCH)])
def test_a_process_disappearing_after_listing_does_not_hide_live_processes(monkeypatch, error_type, number):
    monkeypatch.setattr(process.sys, "platform", "linux")
    original_read = Path.read_text
    original_iterdir = Path.iterdir
    live_record = "7001 (fixture parent) S 1 7001 7001 0 0 0 0 0 0 0 0 0 0 0 20 0 1 0 12345 0 0\n"

    def read_stat(path, *args, **kwargs):
        if path == Path("/proc/7001/stat"):
            return live_record
        if path == Path("/proc/7002/stat"):
            raise error_type(number, "The listed process has exited.")
        return original_read(path, *args, **kwargs)

    def list_processes(path):
        if path == Path("/proc"):
            return iter((Path("/proc/7001"), Path("/proc/7002")))
        return original_iterdir(path)

    monkeypatch.setattr(Path, "read_text", read_stat)
    monkeypatch.setattr(Path, "iterdir", list_processes)
    monkeypatch.setattr(process.os, "killpg", lambda pgid, number: None)
    assert set(process.processes()) == {7001}
    assert process.group_alive(7001) is True
    assert process.descendants(1) == [7001]
    assert process.birth(7002) is None
    assert process.alive(7002) is False


@pytest.mark.parametrize("failure", [PermissionError(errno.EACCES, "Access denied."),
                                     OSError(errno.EIO, "Process observation failed.")])
def test_linux_process_read_failure_stays_unknown(monkeypatch, failure):
    monkeypatch.setattr(process.sys, "platform", "linux")
    monkeypatch.setattr(Path, "iterdir", lambda path: iter((Path("/proc/7002"),)))

    def unreadable(*args, **kwargs):
        raise failure

    monkeypatch.setattr(Path, "read_text", unreadable)
    with pytest.raises(SessionError) as error:
        process.processes()
    assert error.value.code == "process_unknown"
    assert error.value.exit_code == 4


def test_boot_time_is_a_past_instant_before_this_process_started():
    seconds = process.boot_time()
    assert 0 < seconds < time.time()


def test_session_holders_finds_a_process_that_names_the_conversation_and_not_this_one():
    # session_holders scans every process of the host, so an ID shared with a concurrent run of this suite
    # (another seat's) would find that run's child; each run names its own conversation.
    conversation = str(uuid.uuid4())
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "--resume", conversation])
    try:
        assert wait_for(lambda: process.session_holders(conversation) == [child.pid]) is True
        assert process.session_holders("00000000-0000-4000-8000-000000000000") == []
    finally:
        child.kill()
        child.wait()
    assert process.session_holders(conversation) == []


def test_session_holders_reports_an_unreadable_process_list_as_unknown(monkeypatch):
    real = Path.read_bytes

    def refuse(self):
        if self.name == "cmdline":
            raise PermissionError(errno.EACCES, "denied")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", refuse)
    with pytest.raises(SessionError) as error:
        process.session_holders("5d0c3a2e-9d3f-4c1c-8a55-0f6d6f0e7b11")
    assert error.value.code == "process_unknown"
