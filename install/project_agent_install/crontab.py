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


def _script(section):
    return "/^%s$/,/^%s$/d" % (SPECIAL.sub(r"\\\1", section["begin"]), SPECIAL.sub(r"\\\1", section["end"]))


def by_hand(section):
    """Why the section gets no printed command (it is removed by hand with `crontab -e`), or None.

    A broken section (no end line, repeated) is refused because a range delete without its end line would cut to
    the end of the crontab. A name with `'` or `!` is refused because csh changes `!` even inside single quotes
    and the quoting of `'` differs between the shells, so one command could not mean the same in all of them."""
    if section["error"]:
        return "incomplete or repeated (%s)" % section["error"]
    if "'" in section["project"] or "!" in section["project"]:
        return "the project name has a character (' or !) that the shells read differently"
    return None


def removal(section):
    """The one-line command that takes one section out of the crontab, or None when `by_hand` says no.

    It runs the same in csh and tcsh as in sh, bash and zsh (a login shell here is csh): the crontab goes to a
    file in HOME named with the shell's PID, `sed` deletes the range from the start line to the end line, and
    `crontab -` writes the result. Nothing is written when `crontab -l` fails (`&&`), and the file is removed at
    the end either way. The blank line that separates the section from the lines before it stays."""
    if by_hand(section):
        return None
    saved = "~/.project-agent-crontab.$$"
    return "crontab -l > %s && sed '%s' %s | crontab - ; rm -f %s" % (saved, _script(section), saved, saved)
