#!/usr/bin/env python3
"""Show the open decision items of every registered project in the tmux status line.

usage: tmux_decide_status.py

Output example (tmux style markup, white on red):
    결정 4

Nothing is printed when no decision is open or when no count is known yet.

A decision item is open when its file is in the `open` directory of the
project's `path_decide` (project-item skill). The registry and the item files
are read through the project-item code (tools/project-item), so this
script has no second parser of the registry. The count is never stored as a
source of truth: the cache below only remembers the last observation.

tmux runs this script every status-interval (1 s). The directories are read at
most once per CACHE_TTL seconds, by one run at a time (flock). A run that finds
the lock taken, or a read that fails, prints the last known value. A project
whose directory cannot be read keeps its last known decisions.

A new decision is announced once, when an open ID appears that the last read
did not have:
  - `display-message -d ALARM_MS` on every attached client, and
  - a BEL on the tty of the active pane of the project's Leader window
    (`<project>-leader`), which sets the tmux window bell style. This is output
    to the pane, never input.
The first run, and the first read of a project, only store the baseline. An ID
that goes to done and opens again is announced again. The alarm format matches
the shutdown alarm of agent-session (display-message -d 10000 and window bell,
no popup), but the code is separate: agent-session has its own tmux layer.
Only the Python standard library is used besides the project-item code.
"""

import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

CACHE_TTL = 15          # seconds between two reads of the decision directories
ALARM_MS = 10000        # display-message duration
STATUS_STYLE = "#[fg=white,bg=red,bold]"
TOOLS = Path(__file__).resolve().parents[2] / "tools"


def cache_path():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "tmux-decide-status.json")


def read_cache(path):
    """Return (known, age_seconds): {project: {id: title}} and the cache age, or (None, None)."""
    try:
        age = time.time() - os.stat(path).st_mtime
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        known = data["projects"]
        if not (isinstance(known, dict) and all(
                isinstance(ids, dict) for ids in known.values())):
            return None, None
        return known, age
    except (OSError, ValueError, KeyError, TypeError):
        return None, None


def write_cache(path, known):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"projects": known}, handle, ensure_ascii=False)
    os.replace(tmp, path)


def load_project_item():
    """Load the public registration and item observation boundaries."""
    for tool in ("project-item", "agent-session"):
        path = str(TOOLS / tool)
        if path not in sys.path:
            sys.path.insert(0, path)
    from project_item import api
    from agent_session import registry
    return api, registry


def read_open_decisions(previous):
    """Read open items; preserve one project's last observation on a read failure."""
    try:
        items, registry = load_project_item()
        projects = registry.load_registry()
    except Exception:
        return None
    current = {}
    for project in projects:
        try:
            root = items.item_root(project, "decide")
            ids = items.open_decisions(root)
        except Exception:
            if project.project_id in previous:
                current[project.project_id] = previous[project.project_id]
            continue
        current[project.project_id] = ids
    return current


def new_decisions(previous, current):
    """The [(project, id, title)] open now that the last read did not have.

    Without a previous read, or for a project that the last read did not have, nothing is new.
    """
    if previous is None:
        return []
    return [(project, item_id, title)
            for project, ids in sorted(current.items()) if project in previous
            for item_id, title in sorted(ids.items()) if item_id not in previous[project]]


def tmux(*args):
    """Return the tmux output, or None when the command fails."""
    try:
        proc = subprocess.run(("tmux",) + args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else None


def ring_bell(tty):
    """Write BEL to a pane tty. The pane shows it as output and sets its window bell flag."""
    try:
        fd = os.open(tty, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
    except OSError:
        return
    try:
        os.write(fd, b"\a")
    except OSError:
        pass
    finally:
        os.close(fd)


def alarm(new):
    """Tell every client about the new decisions and ring the Leader window of each project."""
    text = "새 결정: " + " / ".join("%s %s %s" % entry for entry in new)
    text = text.replace("#", "##")
    for client in (tmux("list-clients", "-F", "#{client_name}") or "").splitlines():
        tmux("display-message", "-c", client, "-d", str(ALARM_MS), text)
    leaders = {"%s-leader" % project for project in {entry[0] for entry in new}}
    for line in (tmux("list-panes", "-a", "-F",
                      "#{window_name}\t#{pane_active}\t#{pane_tty}") or "").splitlines():
        name, _, rest = line.partition("\t")
        active, _, tty = rest.partition("\t")
        if name in leaders and active == "1" and tty:
            ring_bell(tty)


def refresh(path):
    """Read the directories under the lock, store the observation, then announce the new IDs."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lock = os.open(path + ".lock", os.O_CREAT | os.O_WRONLY, 0o600)
    except OSError:
        return
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return              # another run reads now; keep the last value
        known, age = read_cache(path)
        if known is not None and age <= CACHE_TTL:
            return              # that run just finished
        current = read_open_decisions(known or {})
        if current is None:
            if known is not None:
                os.utime(path, None)    # retry after CACHE_TTL, not every second
            return
        try:
            write_cache(path, current)
        except OSError:
            return              # no stored baseline: announcing now would repeat every read
        new = new_decisions(known, current)
        if new:
            alarm(new)
    finally:
        os.close(lock)


def load_known():
    path = cache_path()
    known, age = read_cache(path)
    if known is None or age > CACHE_TTL:
        refresh(path)
        known, _ = read_cache(path)
    return known


def main():
    known = load_known()
    count = sum(len(ids) for ids in (known or {}).values())
    if count:
        sys.stdout.write("%s 결정 %d #[default]" % (STATUS_STYLE, count))
    return 0


if __name__ == "__main__":
    sys.exit(main())
