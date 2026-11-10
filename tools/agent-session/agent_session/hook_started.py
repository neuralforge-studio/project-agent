"""The record that a run's registration hook started, and what its end without a result means.

The Claude SessionStart hook writes this record in the run's directory before it binds and publishes. A hook
that Claude ends at its time limit leaves no result: it neither publishes nor records a failure. The waiting
`start` reads the record and sees that the hook process is gone while the run is neither ready nor failed, so
it reports the failure instead of waiting out its whole limit.

The record names the hook process (PID and birth); a process cannot come back with the same birth. It is
evidence of the hook only; the assignment stays in the state file, and nothing here is a second source of it.

Dependency direction: `internal` and `lifecycle` import this module; it imports only `launch_artifacts`,
`process` and `util`.
"""

import json
import os
import time

from . import process
from .errors import SessionError
from .launch_artifacts import run_directory
from .util import write_json

FILE = "hook-started.json"


def path(project, run_id):
    return run_directory(project, run_id) / FILE


def write(project, run_id):
    """Record that this process is the registration hook of `run_id`."""
    write_json(path(project, run_id), {
        "run_id": run_id, "pid": os.getpid(), "birth": process.birth(os.getpid()),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })


def ended(project, run_id):
    """Whether the run's registration hook started and its process is gone. A missing, foreign or unreadable
    record, or a process that cannot be observed, is not an end."""
    try:
        record = json.loads(path(project, run_id).read_text(encoding="utf-8"))
        if (not isinstance(record, dict) or record.get("run_id") != run_id
                or not isinstance(record.get("pid"), int) or not isinstance(record.get("birth"), str)):
            return False
        return not process.alive(record["pid"], record["birth"])
    except (OSError, ValueError, SessionError):
        return False
