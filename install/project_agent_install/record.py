"""The install record `~/.local/lib/project-agent/install.json`: what the installer made and owns.

The record keeps no time, so that installing again from the same release changes nothing.
"""

import json
import os

from . import paths
from .actions import sha256
from .layout import InstallerError

FORMAT = 1


def new_record(current):
    return {"format": FORMAT, "current": current, "previous": None, "releases": [current],
            "created_dirs": [], "owned": [], "tmux": {"state": "none"}, "provider_homes": {}}


def encode(record):
    return (json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def read(env):
    """The record, or None when nothing is installed. A record that cannot be read is an error."""
    try:
        raw = env.record.read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as error:
        raise InstallerError("record_unreadable", "Cannot read the install record.",
                             {"path": env.display(env.record), "reason": str(error)}) from error
    try:
        record = json.loads(raw)
        ok = (isinstance(record, dict) and record["format"] == FORMAT and isinstance(record["current"], str)
              and isinstance(record["releases"], list) and isinstance(record["owned"], list)
              and isinstance(record["created_dirs"], list) and isinstance(record["tmux"], dict))
    except (ValueError, KeyError, TypeError):
        ok = False
    if not ok:
        raise InstallerError("record_invalid", "The install record is not valid. Preserve it and ask for help.",
                             {"path": env.display(env.record)})
    paths.validate_record(env, record)
    return record


def owned(path, kind, **fields):
    return {"path": path, "kind": kind, **fields}


def find_owned(record, path):
    return next((entry for entry in record["owned"] if entry["path"] == path), None)


def mismatches(env, record):
    """(display path, "missing" | "changed", expected) for every owned path that is not as recorded."""
    problems = []
    for entry in record["owned"]:
        path = env.expand(entry["path"])
        kind = entry["kind"]
        if not os.path.lexists(path):
            problems.append((entry["path"], "missing", kind))
            continue
        link = path.is_symlink()
        if kind == "symlink":
            same = link and os.readlink(path) == entry["target"]
        elif kind == "dir":
            same = not link and path.is_dir()
        elif kind == "tree":
            same = not link and path.is_dir()
        else:
            same = not link and path.is_file()
            if same and "sha256" in entry:
                same = sha256(path.read_bytes()) == entry["sha256"]
        if not same:
            problems.append((entry["path"], "changed", kind))
    return problems
