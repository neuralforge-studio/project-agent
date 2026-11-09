"""The record that a run's CLI ended on its own, and what it confirms.

When a managed CLI ends by itself (`/exit`, a crash, a signal), the wrap-up in `Manager.finish_ended`
confirms the end once and records it here, in the run's directory. The window may be closed after that,
so the end must not depend on the dead pane: `Manager._observe` reads this record as the run's confirmed
end, and `stop`, `restart`, `start`, and the window cleanup judge the run by it.

The record names the CLI process (PID and birth) and the conversation it ended. A process cannot come back
with the same birth, so the record stays true for its run. It is the end's evidence only; the assignment
stays in the state file, and nothing here is a second source of it.

Dependency direction: `lifecycle` imports this module; it imports only `launch_artifacts` and `util`.
"""

import json
import time

from .launch_artifacts import run_directory
from .util import write_json

FILE = "ended.json"


def path(project, run_id):
    return run_directory(project, run_id) / FILE


def write(project, meta, basis):
    """Record the confirmed end of `meta`'s run. `basis` is `provider` (the provider reported the end) or
    `process` (the CLI, its process group and its tracked PIDs are gone and the provider cannot tell more)."""
    write_json(path(project, meta["run_id"]), {
        "run_id": meta["run_id"], "target": meta["target"], "job_id": meta.get("job_id"),
        "session_id": meta.get("session_id"), "cli_pid": meta.get("cli_pid"), "cli_birth": meta.get("cli_birth"),
        "process_group": meta.get("process_group"), "basis": basis,
        "ended_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })


def confirms(project, meta):
    """Whether the record confirms the end of `meta`'s run: the same run, conversation, and CLI process."""
    if not meta.get("run_id") or not meta.get("cli_pid") or not meta.get("cli_birth"):
        return False
    try:
        record = json.loads(path(project, meta["run_id"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (isinstance(record, dict) and record.get("run_id") == meta["run_id"]
            and record.get("session_id") == meta.get("session_id")
            and record.get("cli_pid") == meta["cli_pid"] and record.get("cli_birth") == meta["cli_birth"])
