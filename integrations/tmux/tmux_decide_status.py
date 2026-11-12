#!/usr/bin/env python3
"""Show the open decision items of every registered project in the tmux status line.

usage: tmux_decide_status.sh   (runs this script with the release interpreter)

Output example (tmux style markup, white on red):
    결정 4

Nothing is printed when no decision is open or when no count is known yet.

A decision item is open when its file is in the `open` directory of the
project's `path_decide` (project-item skill). The registry and the item files
are read through the project-item code (tools/project-item), so this
script has no second parser of the registry. The count is never stored as a
source of truth: the cache below only remembers the last observation.

tmux runs tmux_decide_status.sh every status-interval (1 s). The directories are
read at most once per CACHE_TTL seconds, by one run at a time (flock). A run that
finds the lock taken, or a read that fails, prints the last known value. A project
whose directory cannot be read keeps its last known decisions.

While the cache is valid the .sh prints the status line without starting Python.
Every run of this script that finds a valid cache stores the status line next to
the cache (VIEW_NAME): the first line is the epoch second until which the cache
is valid (the cache mtime plus CACHE_TTL, so CACHE_TTL is kept here only), the
rest is the text printed. The .sh prints that text while the clock is at or
before the first line, and runs this script otherwise.

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
import math
import os
import subprocess
import sys
import time
from pathlib import Path

CACHE_TTL = 15          # seconds between two reads of the decision directories
ALARM_MS = 10000        # display-message duration
STATUS_STYLE = "#[fg=white,bg=red,bold]"
CACHE_NAME = "tmux-decide-status.json"
VIEW_NAME = "tmux-decide-status.view"   # read by tmux_decide_status.sh in the same directory
PROJECT_ITEM = Path(__file__).resolve().parents[2] / "tools" / "project-item"


def cache_path():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, CACHE_NAME)


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


def render(known):
    count = sum(len(ids) for ids in (known or {}).values())
    return "%s 결정 %d #[default]" % (STATUS_STYLE, count) if count else ""


def write_view(path, text):
    """Store `text` for the .sh until the cache at `path` expires. Failing to store only costs a Python run."""
    try:
        expires = math.floor(os.stat(path).st_mtime + CACHE_TTL)
        if time.time() > expires:
            return
        view = os.path.join(os.path.dirname(path), VIEW_NAME)
        tmp = "%s.%d.tmp" % (view, os.getpid())
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write("%d\n%s" % (expires, text))
        os.replace(tmp, view)
    except OSError:
        pass


def load_project_item():
    """Import the public interface of project-item (project_item.api)."""
    if str(PROJECT_ITEM) not in sys.path:
        sys.path.insert(0, str(PROJECT_ITEM))
    from project_item import api
    return api


def read_open_decisions(previous):
    """Return {project: {id: title}} of the open decisions, or None when the registry is unusable.

    A project whose directory cannot be read keeps its entry of `previous`; without one it is left out.
    """
    try:
        item_api = load_project_item()
        projects = item_api.projects()
    except Exception:
        return None
    current = {}
    for project in projects:
        try:
            root = item_api.item_root(project, "decide")
            ids = {}
            for path in item_api.item_files(item_api.DECIDE, root, "open"):
                item_id = item_api.file_id(item_api.DECIDE, path) or path.stem
                try:
                    title = item_api.DECIDE.fmt.parse(path, "open").title or ""
                except (OSError, ValueError):
                    title = ""
                ids[item_id] = title
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
        proc = subprocess.run((os.environ.get("PROJECT_AGENT_TMUX") or "tmux",) + args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
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
    text = render(known)
    if known is not None:
        write_view(cache_path(), text)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
