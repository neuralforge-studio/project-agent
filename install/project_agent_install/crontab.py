"""The project-agent sections that stay in the user's crontab (contract 5.4, 7).

`agent-session` writes them when a Leader starts; the installer never writes the crontab (decision
D-20261109-09: the one existing file it edits is the tmux settings). It reads the sections through
`agent_session.api.crontab_sections`, the one reader of the section format, and only tells the user: `uninstall`
prints the commands that remove them, `check` names a section whose command points at a release that is gone.
"""

import os
import re
import shlex

from . import runs

SPECIAL = re.compile(r"([\\.\[\]*^$/])")


def read(source_root):
    """`(sections, problem)`: the project sections of the crontab, or why they could not be read."""
    api = runs.api_of(source_root)
    try:
        return api.crontab_sections(), None
    except api.SessionError as error:
        return [], error.code


def _command_path(command):
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    return words[0] if words else None


def missing_programs(sections):
    """`[(project, job id, path)]` for the jobs whose program does not exist any more."""
    found = []
    for section in sections:
        for job in section["jobs"]:
            path = _command_path(job["command"])
            if path and os.path.isabs(path) and not os.path.exists(path):
                found.append((section["project"], job["id"], path))
    return found


def removal(section):
    """The shell command that takes one section out of the crontab, or None when the section cannot be read
    (a range delete on a section without its end line would cut to the end of the crontab).

    The crontab is read first and nothing is written when that fails. The blank line that separates the
    section from the lines before it stays."""
    if section["error"]:
        return None
    script = "/^%s$/,/^%s$/d" % (SPECIAL.sub(r"\\\1", section["begin"]), SPECIAL.sub(r"\\\1", section["end"]))
    return "text=$(crontab -l) && printf '%%s\\n' \"$text\" | sed %s | crontab -" % shlex.quote(script)
