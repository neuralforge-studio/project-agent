"""Observe process identity without signalling or adopting a reused PID."""

import errno
import os
from pathlib import Path
import re
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


def age(pid):
    """Seconds since the process was created, or 0.0 when the platform gives no creation time (not Linux, or
    the process is gone)."""
    if not sys.platform.startswith("linux"):
        return 0.0
    row = _linux_row(_pid(pid))
    if row is None:
        return 0.0
    try:
        uptime = float((Path("/proc") / "uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError) as exc:
        raise SessionError("process_unknown", "Cannot read the system uptime.", 4) from exc
    return max(0.0, uptime - int(row["birth"]) / os.sysconf("SC_CLK_TCK"))


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


def started(pid):
    """Unix seconds at which a process started, or None if it is gone. Linux only (process_unknown elsewhere)."""
    if not sys.platform.startswith("linux"):
        raise SessionError("process_unknown", "Process start times are read on Linux only.", 4)
    row = _linux_row(_pid(pid))
    return None if row is None else boot_time() + int(row["birth"]) / os.sysconf("SC_CLK_TCK")


def tree(pid):
    """The live descendants of a process with what `watch` needs: pid, birth, start time, CPU, command line.

    `cpu` is the CPU seconds the process used, including the children it already reaped, so a shell that
    runs short commands in a loop shows their cost. `started` is Unix seconds. Linux only: other platforms
    raise process_unknown, because `ps` cannot give the reaped children's time."""
    if not sys.platform.startswith("linux"):
        raise SessionError("process_unknown", "Process CPU time is read on Linux only.", 4)
    found = []
    ticks = os.sysconf("SC_CLK_TCK")
    for child in descendants(pid):
        try:
            base = Path("/proc") / str(child)
            stat = (base / "stat").read_text().rsplit(")", 1)[1].split()
            args = (base / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
            identity = birth(child)
            used = sum(int(stat[index]) for index in (11, 12, 13, 14))      # utime stime cutime cstime
            began = started(child)
        except (FileNotFoundError, ProcessLookupError):
            continue                       # it ended while the tree was read
        except (OSError, IndexError, ValueError) as exc:
            raise SessionError("process_unknown", "Cannot read a descendant's CPU time.", 4,
                               {"pid": child}) from exc
        if identity is not None and began is not None:
            found.append({"pid": child, "birth": identity, "started": began, "cpu": used / ticks, "args": args})
    return found


def cli_alive(meta, pane):
    """Whether the run's CLI process (or the pane process before it marked one) still runs."""
    pid = meta.get("cli_pid") or pane.get("pane_pid")     # a window handed to a new run holds cli_pid null
    return bool(pid and alive(int(pid), meta.get("cli_birth")))


def unlaunched_observation(meta, pane):
    """The observation of a window whose provider CLI was never launched."""
    if meta.get("provider_launch_attempted") is not False or meta.get("registered") is not False:
        raise SessionError("session_unbound", "The target has no verified native conversation.", 4)
    pid, fingerprint = meta.get("placeholder_pid"), meta.get("placeholder_birth")
    group = meta.get("placeholder_process_group")
    if not pid or not fingerprint or not group:
        raise SessionError("execution_unknown", "The waiting pane process identity is incomplete.", 4)
    placeholder_alive = alive(int(pid), fingerprint)
    stopped = bool(pane["pane_dead"] and not placeholder_alive and not group_alive(int(group)))
    return {"known": True, "terminal": True, "active_turn": False, "pending": [],
            "background": [], "idle": True, "cli_alive": False, "stopped": stopped, "pane": pane}


def boot_time():
    """The system boot time as Unix seconds. Raise process_unknown when it cannot be read.

    Linux reads `btime` of /proc/stat and macOS reads `kern.boottime`. Both are the wall clock at boot, so a
    clock step after the boot (NTP, a manual change) moves them by the same amount."""
    try:
        if sys.platform.startswith("linux"):
            for line in Path("/proc/stat").read_text().splitlines():
                if line.startswith("btime "):
                    return float(line.split()[1])
        elif sys.platform == "darwin":
            result = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=10)
            found = re.search(r"sec\s*=\s*(\d+)", result.stdout) if result.returncode == 0 else None
            if found:
                return float(found.group(1))
    except (OSError, UnicodeError, ValueError, subprocess.TimeoutExpired) as exc:
        raise SessionError("process_unknown", "Cannot read the system boot time.", 4) from exc
    raise SessionError("process_unknown", "The system boot time is not available on this platform.", 4)


def session_holders(session_id):
    """PIDs of the processes whose command line names this conversation ID, excluding this process.

    The CLI carries the ID in its arguments (`--session-id` or `--resume`). Any process that mentions it counts,
    so an unrelated one only makes the answer more cautious. Raise process_unknown when the list is incomplete."""
    if not session_id:
        raise SessionError("process_unknown", "A conversation ID is required.", 4)
    if not sys.platform.startswith("linux"):
        env = dict(os.environ, LC_ALL="C")
        try:
            result = subprocess.run(["ps", "-axww", "-o", "pid=,args="], capture_output=True, text=True,
                                    timeout=10, env=env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SessionError("process_unknown", "Cannot obtain the process list.", 4) from exc
        if result.returncode:
            raise SessionError("process_unknown", "The process list command failed.", 4)
        found = []
        for line in result.stdout.splitlines():
            pid, _, args = line.strip().partition(" ")
            if pid.isdigit() and int(pid) != os.getpid() and session_id in args:
                found.append(int(pid))
        return sorted(found)
    try:
        names = [path.name for path in Path("/proc").iterdir() if path.name.isdecimal()]
    except OSError as exc:
        raise SessionError("process_unknown", "Cannot inspect the process directory.", 4) from exc
    found = []
    for name in names:
        try:
            raw = (Path("/proc") / name / "cmdline").read_bytes()
        except (FileNotFoundError, ProcessLookupError):
            continue                       # it ended while the list was read
        except OSError as exc:
            raise SessionError("process_unknown", "Cannot read a process command line.", 4,
                               {"pid": int(name)}) from exc
        if int(name) != os.getpid() and session_id.encode() in raw:
            found.append(int(name))
    return sorted(found)
