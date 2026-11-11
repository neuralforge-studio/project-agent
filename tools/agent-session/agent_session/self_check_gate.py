"""The Leader's self-check gate: a Claude `UserPromptSubmit` hook that keeps an idle check out of the session.

The Leader's session cron (`skills/project-team/references/self-check.md`, which owns the cron expression
and the prompt) enters the Leader session every 30 minutes whether or not there is anything to look at.
The Leader's run settings carry this hook; it blocks that one prompt when the project has no open, todo or
in-progress CR and no open or answered decision. A blocked prompt makes no model turn and no user record.
Claude still shows the "Running scheduled task" line and the one-line block notice (`suppressOutput` does not
hide them), so the screen is not silent, only short.

What the hook never does: it passes every other prompt (a user's input, a message from a peer, the Worker's
check prompt), and it passes the check whenever it cannot judge (an unreadable registry or item directory,
an unexpected payload, an error of any kind). A wrong guess toward "block" would stop the Leader's watch.

The check also passes once in `HEARTBEAT` seconds when idle. A session cron expires after 7 days and the
check prompt is what registers it again (self-check.md, last item), so a Leader that blocked every prompt
would lose its cron without anyone noticing, and work that arrives later would never be looked at. The pass
time is recorded in the run's directory; a missing or unwritable record passes the check.

Dependency direction: `providers/claude` installs this hook. This module imports only the standard library at
the top; the registry, `jobs` and project-item load when a Leader check is judged, so every other prompt costs
one interpreter start and a JSON read. The work states are project-item's (`CR.listed` without `CR.terminal`,
`DECIDE.listed`); nothing here lists them again.
"""

import json
import sys
import time

HOOK_TIMEOUT = 10          # seconds Claude lets the hook run; a hook it ends at the limit passes the prompt
HEARTBEAT = 24 * 3600      # seconds an idle Leader may go without one check that really runs (keeps the 7-day renewal)
MARKER = "[자기 점검]"       # the first words of every self-check prompt (self-check.md)
LEADER_WORDS = "Leader 자기 점검"   # in the first line of the Leader's, not of the Worker's
STATE_FILE = "self-check-gate.json"
BLOCK_REASON = "Leader 자기 점검 생략: open·todo·in-progress CR과 open·answered 결정 항목이 없습니다."


def is_leader_check(prompt):
    """Whether `prompt` is the Leader's self-check prompt (a test keeps this and self-check.md together)."""
    if not isinstance(prompt, str):
        return False
    first = prompt.split("\n", 1)[0]
    return first.startswith(MARKER) and LEADER_WORDS in first


def has_work(project):
    """Whether `project` has a CR or a decision that the Leader's check would look at.

    Raises when the item roots cannot be read: the caller passes the check then."""
    from .jobs import item_api

    api = item_api()
    for kind, states in ((api.CR, tuple(state for state in api.CR.listed if state not in api.CR.terminal)),
                         (api.DECIDE, api.DECIDE.listed)):
        root = api.item_root(project, kind.name)
        if any(api.item_files(kind, root, state) for state in states):
            return True
    return False


def _record_path(project, run_id):
    from .launch_artifacts import run_directory

    return run_directory(project, run_id) / STATE_FILE


def _passed_recently(path, now):
    try:
        passed = json.loads(path.read_text(encoding="utf-8"))["passed_at"]
        return isinstance(passed, (int, float)) and 0 <= now - passed < HEARTBEAT
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _record_pass(path, now):
    try:
        path.write_text(json.dumps({"passed_at": now}), encoding="utf-8")
    except OSError:
        pass


def should_block(project, run_id, now=None):
    """Whether the Leader check of this run is blocked now. Records the time of a check that passes."""
    now = time.time() if now is None else now
    path = _record_path(project, run_id)
    if not has_work(project) and _passed_recently(path, now):
        return True
    _record_pass(path, now)
    return False


def main(run_id, config_path, base):
    """The hook: read one `UserPromptSubmit` event on stdin; print Claude's block decision, or nothing to pass."""
    try:
        payload = json.load(sys.stdin)
        if payload.get("hook_event_name") != "UserPromptSubmit" or not is_leader_check(payload.get("prompt")):
            return
        from .config import resolve_project

        if not should_block(resolve_project(base, config_path), run_id):
            return
    except Exception:                       # a hook that cannot judge passes the prompt
        return
    print(json.dumps({"decision": "block", "reason": BLOCK_REASON}, ensure_ascii=False))
