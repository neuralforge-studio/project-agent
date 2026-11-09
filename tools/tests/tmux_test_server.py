"""The one place that starts and ends the tmux servers the tests use (TEST-004).

A test that starts a tmux server must leave nothing behind, whether it passes, fails, or its pytest
process is killed. ``kill-server`` ends the server but leaves its socket file in ``/tmp/tmux-<uid>``,
and a finalizer never runs when pytest dies by SIGKILL or SIGTERM. So the lifetime has two owners:

- ``release(name)`` is the normal end: stop the watchdog, ``kill-server``, remove the socket file.
- ``claim(prefix)`` starts a watchdog in its own session that waits for the claiming process (the
  pytest worker) to disappear and then does the same. It names its server by socket (``-S``), so it
  cannot touch the server of another seat or of the user, and it ends as soon as ``release`` runs.

Every test tmux server gets its name from ``claim`` and ends in ``release``: the server may be
started by the test (``tmux -L <name> new-session``) or by the product on its first command; the
watchdog does not care which. A pane's process ends with its server (tmux hangs it up), so a fake
provider in a pane needs no watchdog of its own.

This module is test code only: it lives under ``tools/tests`` and is not part of the release.
"""

import atexit
import os
from pathlib import Path
import signal
import subprocess
import uuid

# The end of a server, for ``release`` and the watchdog alike. Argument 1 is the socket path. Besides
# the socket file, it removes the runtime directory Project Board's tmux_control makes for each server
# (``/tmp/project-board-<uid>-<server pid>``, see ``_private_dir``), which the product never removes.
# project-board's test_tmux_control checks that this name is still the one the product uses.
CLEANUP = (r'pid=$(tmux -S "$1" display-message -p "#{pid}" 2>/dev/null); '
           r'tmux -S "$1" kill-server >/dev/null 2>&1; rm -f "$1"; '
           r'case "$pid" in ""|*[!0-9]*) ;; *) rm -rf "/tmp/project-board-$(id -u)-$pid";; esac')
# Argument 1 is the socket path, argument 2 the owner pid. Plain sh: no tmux session is involved.
WATCHDOG = 'while kill -0 "$2" 2>/dev/null; do sleep 1; done; ' + CLEANUP

_watchdogs = {}


def socket_path(name):
    """The socket file tmux uses for ``-L name``; it need not exist yet."""
    directory = os.environ.get("TMUX_TMPDIR") or "/tmp"
    return Path(directory) / f"tmux-{os.getuid()}" / name


def new_name(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def claim(prefix, owner=None):
    """Return a new unique socket name whose server is removed when ``owner`` (default: this process) ends."""
    name = new_name(prefix)
    watch(name, owner)
    return name


def watch(name, owner=None):
    """Start the watchdog for a ``-L`` socket name chosen by the caller (once per name)."""
    watch_path(socket_path(name), owner)


def release(name):
    """End the server, its panes' processes and its socket file; safe to call again."""
    release_path(socket_path(name))


def watch_path(path, owner=None):
    """``watch`` for a server the test addresses by socket path (``-S``), as the installer tests do."""
    path = str(path)
    if path in _watchdogs:
        return
    if not _watchdogs:
        atexit.register(release_all)
    _watchdogs[path] = subprocess.Popen(
        ["sh", "-c", WATCHDOG, "sh", path, str(owner or os.getpid())],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def release_path(path):
    path = str(path)
    watchdog = _watchdogs.pop(path, None)
    if watchdog is not None:
        try:
            os.killpg(watchdog.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        watchdog.wait()
    subprocess.run(["sh", "-c", CLEANUP, "sh", path], capture_output=True, timeout=10)


def release_all():
    for path in list(_watchdogs):
        release_path(path)
