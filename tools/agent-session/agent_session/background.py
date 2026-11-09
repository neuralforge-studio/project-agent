"""A managed Claude conversation that moved to a background session.

Claude 2.1.319 moves a conversation to a background session when `/background` or the left arrow runs,
or when the CLI ends with background work (exit handoff). The conversation continues under a new
session ID in a `claude daemon` process, and the managed pane's CLI only displays it.
The provider reports the move; this module records it and judges whether it has ended.
"""

import datetime as dt

from . import process
from .errors import SessionError


def record_of(provider, old_session_id, new_session_id, cwd, timeout):
    """The record of a move from `old_session_id`, or None when its transcript does not show one.

    `new_session_id` is the ID that a hook reported, when there is one; the transcript must name it.
    The host process is looked up on a best-effort basis: an unknown host stays None."""
    moved = provider.moved_to(old_session_id)
    if not moved or (new_session_id and moved != new_session_id):
        return None
    record = {"old_session_id": old_session_id, "new_session_id": moved, "host_pid": None, "host_birth": None,
              "detected_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        host = provider.background_host(moved, cwd, timeout)
    except SessionError:
        return record
    return with_host(record, host)


def with_host(record, host):
    """The record with the host PID that the provider's listing names; unchanged without one."""
    pid = host.get("pid") if host.get("listed") else None
    if not pid or pid == record.get("host_pid"):
        return record
    try:
        birth = process.birth(pid)
    except SessionError:
        birth = None
    return {**record, "host_pid": pid, "host_birth": birth}


def cli_state(meta, pane):
    """The managed CLI: alive, ended (pane dead and the recorded process gone), or unknown."""
    pid, birth = meta.get("cli_pid"), meta.get("cli_birth")
    if not pane["pane_dead"]:
        return "alive"
    if not pid or not birth:
        return "unknown"
    try:
        return "alive" if process.alive(int(pid), birth) else "ended"
    except SessionError:
        return "unknown"


def _host(provider, meta, record, timeout):
    """The background conversation: alive, ended (not listed and its host process gone), or unknown.

    Returns the state and the record, which gains the host PID when the listing shows it now."""
    pid, birth = record.get("host_pid"), record.get("host_birth")
    try:
        host = provider.background_host(record["new_session_id"], meta["cwd"], timeout)
    except SessionError:
        host = None
    if host is not None and host.get("listed"):
        return "alive", with_host(record, host)
    if not pid:
        return "unknown", record
    try:
        gone = not process.alive(int(pid), birth)
    except SessionError:
        return "unknown", record
    # A listing that cannot be read leaves only the process: a live host stays alive, a gone one is unconfirmed.
    if host is None:
        return ("unknown" if gone else "alive"), record
    return ("ended" if gone else "alive"), record


def judge(provider, meta, record, pane, timeout):
    """Whether the moved run ended: ended only when both the conversation and the CLI ended.

    Any unknown fact keeps the run: `state` is `running` when one of them is alive, else `unknown`."""
    cli = cli_state(meta, pane)
    host, record = _host(provider, meta, record, timeout)
    if cli == "ended" and host == "ended":
        state = "ended"
    elif "alive" in (cli, host):
        state = "running"
    else:
        state = "unknown"
    return {"state": state, "cli": cli, "host": host, "record": record}


def details(meta, record, judged=None):
    """The identity of a moved run for an error or an observation."""
    return {"run_id": meta.get("run_id"), "window_id": meta.get("window_id"), "pane_id": meta.get("pane_id"),
            "old_session_id": record["old_session_id"], "new_session_id": record["new_session_id"],
            "host_pid": record.get("host_pid"),
            **({"conversation": judged["host"], "cli": judged["cli"], "state": judged["state"]} if judged else {})}
