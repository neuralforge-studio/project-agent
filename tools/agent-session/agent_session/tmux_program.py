"""The tmux that project-agent runs: one record that every component reads the same way (TMUX-004).

The machine has two tmux that cannot talk to each other (the system one and the company one), and an
environment's PATH does not say which one project-agent needs (cron has `/usr/bin:/bin`). So the choice is made
once, by the installer, and written to the release as `tools/tmux.env` (install contract 6.2), next to
`python.env`. The Python of `agent-session` and `project-board`, the Rust sidebar and the shell scripts of
`integrations/tmux` read it by the same rule:

    PROJECT_AGENT_TMUX                 absolute path of the tmux executable
    PROJECT_AGENT_TMUX_LD_LIBRARY_PATH library directories that executable needs to start (empty when none)

An environment variable with a value wins over the file (per name, as `python-launcher.sh` does). A tree with
no `tmux.env` is a development checkout or the remote runtime: the program is `tmux` found in that process's
PATH, which is the rule of a checkout and of the remote host (`remote.REMOTE_PATH`), and the library is not
changed. A `tmux.env` that names no program says that the installer found no tmux of the minimum version:
every run then fails with `tmux_unavailable`.
"""

import functools
import os
from pathlib import Path

from .errors import SessionError

COMPANY_TMUX = "/primehome/tools/Inhouse/tmux/latest/bin"   # the directory of the company tmux; the installer tries it
PROGRAM_NAME = "PROJECT_AGENT_TMUX"
LIBRARY_NAME = "PROJECT_AGENT_TMUX_LD_LIBRARY_PATH"
RECORD = Path(__file__).resolve().parents[2] / "tmux.env"   # `tools/tmux.env` of a release; absent elsewhere


@functools.lru_cache(maxsize=None)
def _record(path):
    """`{name: value}` of the record's two names, or None when there is no such file. The file is parsed, never
    sourced: one `NAME=value` per line, the value is the rest of the line (the last line of a name wins)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    values = {}
    for line in text.splitlines():
        name, separator, value = line.partition("=")
        if separator and name in (PROGRAM_NAME, LIBRARY_NAME):
            values[name] = value
    return values


def settings():
    """`(program, library)`: the tmux executable to run and the library directories it needs ('' for none)."""
    recorded = _record(str(RECORD))
    program = os.environ.get(PROGRAM_NAME) or (recorded or {}).get(PROGRAM_NAME, "")
    library = os.environ.get(LIBRARY_NAME) or (recorded or {}).get(LIBRARY_NAME, "")
    if recorded is not None and not program:
        raise SessionError(
            "tmux_unavailable", "This release has no tmux of the minimum version recorded. Install one, then run "
            "the installer again (install contract 6.2).", 5, {"record": str(RECORD)})
    return program or "tmux", library


def program():
    """The tmux executable to run, as a path (or `tmux` for a tree without a record)."""
    return settings()[0]


def environment():
    """The environment to run the tmux with: the library directories in front of `LD_LIBRARY_PATH`. None when
    the record names none, so that the process keeps its own environment."""
    library = settings()[1]
    if not library:
        return None
    return {**os.environ, "LD_LIBRARY_PATH": library + (":" + os.environ["LD_LIBRARY_PATH"]
                                                        if os.environ.get("LD_LIBRARY_PATH") else "")}
