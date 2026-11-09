"""tmux_test_server leaves no tmux server, pane process or socket file behind (TEST-004)."""

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
import tmux_test_server  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")

# A test process that owns one server with one pane process (the stand-in for a fake provider),
# reports both and waits to be killed.
OWNER = r'''
import subprocess, sys, time
sys.path.insert(0, sys.argv[1])
import tmux_test_server
name = tmux_test_server.claim("pa-selftest")
subprocess.run(["tmux", "-L", name, "-f", "/dev/null", "new-session", "-d", "-s", "harness", "sleep", "86400"], check=True)
pane = subprocess.run(["tmux", "-L", name, "display-message", "-p", "#{pane_pid}"], check=True,
                      capture_output=True, text=True).stdout.strip()
print(name, pane, flush=True)
time.sleep(600)
'''


def start_owner():
    process = subprocess.Popen([sys.executable, "-c", OWNER, str(Path(__file__).resolve().parent / "tests")],
                               stdout=subprocess.PIPE, text=True)
    name, pane = process.stdout.readline().split()
    return process, name, int(pane)


def server_alive(name):
    return subprocess.run(["tmux", "-S", str(tmux_test_server.socket_path(name)), "has-session"],
                          capture_output=True).returncode == 0


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie awaiting its reaper is gone for this purpose.
    return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z" if Path(f"/proc/{pid}").exists() else True


def wait_until(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


def gone(name, pane):
    return not server_alive(name) and not tmux_test_server.socket_path(name).exists() and not alive(pane)


def test_release_ends_the_server_its_pane_process_and_its_socket_file():
    name = tmux_test_server.claim("pa-selftest")
    subprocess.run(["tmux", "-L", name, "-f", os.devnull, "new-session", "-d", "-s", "harness", "sleep", "86400"],
                   check=True)
    pane = int(subprocess.run(["tmux", "-L", name, "display-message", "-p", "#{pane_pid}"], check=True,
                              capture_output=True, text=True).stdout)
    assert server_alive(name) and tmux_test_server.socket_path(name).exists()
    tmux_test_server.release(name)
    assert wait_until(lambda: gone(name, pane))
    tmux_test_server.release(name)  # a second call is harmless


@pytest.mark.parametrize("sig", [signal.SIGKILL, signal.SIGTERM, signal.SIGINT])
def test_a_killed_owner_leaves_no_server_pane_process_or_socket_file(sig):
    owner, name, pane = start_owner()
    try:
        assert server_alive(name) and alive(pane)
        owner.send_signal(sig)
        owner.wait(timeout=10)
        assert wait_until(lambda: gone(name, pane))
    finally:
        owner.kill()
        owner.wait()
        tmux_test_server.release(name)


def test_a_killed_owner_does_not_touch_another_owners_server():
    mine = tmux_test_server.claim("pa-selftest")
    subprocess.run(["tmux", "-L", mine, "-f", os.devnull, "new-session", "-d", "-s", "harness", "sleep", "86400"],
                   check=True)
    owner, name, pane = start_owner()
    try:
        owner.kill()
        owner.wait()
        assert wait_until(lambda: gone(name, pane))
        time.sleep(2)  # past any watchdog that was still going to act
        assert server_alive(mine)
    finally:
        tmux_test_server.release(mine)
        tmux_test_server.release(name)
