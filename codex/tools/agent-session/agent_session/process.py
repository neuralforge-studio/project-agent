"""Observe process identity without signalling or adopting a reused PID."""

import errno
import os
from pathlib import Path
import subprocess
import sys

from .errors import SessionError


def _pid(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SessionError("process_unknown", "A positive process ID is required.", 4)
    return value


def _linux_row(pid):
    try:
        data = (Path("/proc") / str(pid) / "stat").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return None
    except (OSError, UnicodeError) as exc:
        raise SessionError("process_unknown", "Cannot observe the process identity.", 4,
                           {"pid": pid}) from exc
    try:
        fields = data.rsplit(")", 1)[1].split()
        return {"pid": pid, "parent": int(fields[1]), "group": int(fields[2]),
                "state": fields[0], "birth": fields[19]}
    except (IndexError, ValueError) as exc:
        raise SessionError("process_unknown", "The process identity record is incomplete.", 4,
                           {"pid": pid}) from exc


def _ps_rows():
    env = dict(os.environ, LC_ALL="C")
    try:
        result = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid=,stat=,lstart="],
                                capture_output=True, text=True, timeout=10, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SessionError("process_unknown", "Cannot obtain the process list.", 4) from exc
    if result.returncode:
        raise SessionError("process_unknown", "The process list command failed.", 4)
    rows = {}
    for line in result.stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) != 5 or not all(part.isdigit() for part in parts[:3]):
            raise SessionError("process_unknown", "The process list contains an incomplete record.", 4)
        pid, parent, group = map(int, parts[:3])
        rows[pid] = {"pid": pid, "parent": parent, "group": group,
                     "state": parts[3], "birth": parts[4]}
    return rows


def processes():
    """Return one observation of process ancestry and process groups."""
    if not sys.platform.startswith("linux"):
        return _ps_rows()
    try:
        paths = tuple(Path("/proc").iterdir())
    except OSError as exc:
        raise SessionError("process_unknown", "Cannot inspect the process directory.", 4) from exc
    rows = {}
    for path in paths:
        if path.name.isdecimal():
            row = _linux_row(int(path.name))
            if row is not None:
                rows[row["pid"]] = row
    return rows


def birth(pid):
    """Return a process creation fingerprint, or None if the PID is absent."""
    pid = _pid(pid)
    if sys.platform.startswith("linux"):
        row = _linux_row(pid)
        if row is None:
            return None
        try:
            boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except OSError as exc:
            raise SessionError("process_unknown", "Cannot identify the current boot.", 4) from exc
        if not boot:
            raise SessionError("process_unknown", "The current boot identity is unavailable.", 4)
        return "linux:" + boot + ":" + row["birth"]
    row = _ps_rows().get(pid)
    return None if row is None else sys.platform + ":" + row["birth"]


def alive(pid, expected_birth=None):
    """A zombie or a PID with a different creation fingerprint is not alive."""
    pid = _pid(pid)
    row = _linux_row(pid) if sys.platform.startswith("linux") else _ps_rows().get(pid)
    if row is None or row["state"].startswith(("Z", "X")):
        return False
    return expected_birth is None or birth(pid) == expected_birth


def group_alive(pgid):
    """Return whether a process group has a non-zombie member."""
    pgid = _pid(pgid)
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        raise SessionError("process_unknown", "Cannot observe the process group.", 4,
                           {"process_group": pgid}) from exc
    return any(row["group"] == pgid and not row["state"].startswith(("Z", "X"))
               for row in processes().values())


def descendants(pid):
    """Return live descendants from one ancestry snapshot, excluding the parent."""
    pid = _pid(pid)
    rows = processes()
    found = set()
    parents = {pid}
    while parents:
        children = {child for child, row in rows.items()
                    if row["parent"] in parents and child not in found and child != pid}
        found.update(children)
        parents = children
    return sorted(child for child in found if not rows[child]["state"].startswith(("Z", "X")))
