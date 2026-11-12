"""Which tmux a release records in `tools/tmux.env` (contract section 6.2), and the check of that record.

The installer picks the tmux once, because nothing else can: an environment's PATH does not say which of the
two tmux of the host (they cannot talk to each other) project-agent needs. `agent-session`, `project-board`, the
Rust sidebar and the tmux scripts read the record (`agent_session/tmux_program.py` owns the rule)."""

import os
import re
import shutil
import subprocess

from . import runs
from .layout import InstallerError
from .release import PROBE_ENV            # the environment cron gives: the record must work with nothing else
from .tmuxconf import minimum, number

TMUX_ENV = "tools/tmux.env"
SYSTEM_LIBRARIES = ("/lib", "/lib64", "/usr/lib", "/usr/lib64", "/usr/local/lib", "/usr/local/lib64")
EXPLICIT = "PROJECT_AGENT_TMUX"             # the installer's environment names the tmux (same name as the record)


def env_text(program, library):
    """The release's `tools/tmux.env`: an empty program says that no usable tmux was found."""
    return ("PROJECT_AGENT_TMUX=%s\nPROJECT_AGENT_TMUX_LD_LIBRARY_PATH=%s\n" % (program, library)).encode()


def read(release):
    """`{name: value}` of the release's `tools/tmux.env`, or None when the release has none."""
    try:
        text = (release / TMUX_ENV).read_text()
    except OSError:
        return None
    values = {}
    for line in text.splitlines():
        name, separator, value = line.partition("=")
        if separator:
            values[name] = value
    return values


def version_of(program, library=""):
    """The version word of `tmux -V` run with nothing in its environment but `library`, or None when it does not run."""
    env = {**PROBE_ENV, **({"LD_LIBRARY_PATH": library} if library else {})}
    try:
        result = subprocess.run([program, "-V"], capture_output=True, text=True, timeout=10, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    words = result.stdout.split()
    return (words[-1] if words else "") if result.returncode == 0 else None


def library_candidates(program):
    """The directories outside the system's that `program` loads its libraries from, as `ldd` resolves them in
    this environment. The first `""` is "none needed"; when it does not run in an empty environment the
    directories are tried (the company tmux needs libevent and ncurses from its own library directories)."""
    found = [""]
    try:
        text = subprocess.run(["ldd", program], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return found
    directories = []
    for line in text.splitlines():
        match = re.search(r"=> (/\S+)", line)
        directory = os.path.dirname(match.group(1)) if match else None
        if directory and directory not in directories and not any(
                directory == system or directory.startswith(system + "/") for system in SYSTEM_LIBRARIES):
            directories.append(directory)
    return found + ([":".join(directories)] if directories else [])


def start(program):
    """`(library, version)` of the first library setting with which `program` runs in an empty environment, or None."""
    if not os.path.isabs(program) or not os.access(program, os.X_OK):
        return None
    for library in library_candidates(program):
        version = version_of(program, library)
        if version is not None:
            return library, version
    return None


def candidates(source_root, environ=None):
    """`[(program, explicit)]` in the order the installer tries them: the tmux the installer's environment names
    (`PROJECT_AGENT_TMUX`), then the first `tmux` in PATH (the tmux this person already runs a server with), then
    the company tmux. A symlink (`.../tmux/latest/bin/tmux`) is kept, so a new version of it is followed."""
    environ = os.environ if environ is None else environ
    found = []
    if environ.get(EXPLICIT):
        found.append((environ[EXPLICIT], True))
    which = shutil.which("tmux", path=environ.get("PATH"))
    if which:
        found.append((os.path.abspath(which), False))
    company = os.path.join(runs.api_of(source_root).COMPANY_TMUX, "tmux")
    if company not in [program for program, _ in found]:
        found.append((company, False))
    return found


def choose(source_root, environ=None, tried=None):
    """`(program, library, notes)`: the first tmux of `candidates` that runs and is of the minimum version, with
    the library directories it needs; `("", "", notes)` when there is none (the install goes on and says so; every
    tmux action of that release then fails with `tmux_unavailable`). A tmux that the installer's environment names
    and that is not usable is refused: the person asked for that one."""
    wanted = minimum(source_root)
    notes = []
    for program, explicit in (tried or candidates(source_root, environ)):
        started = start(program)
        if started is None:
            reason = "does not run"
        elif number(started[1]) < number(wanted or ""):
            reason = "is %s, older than the minimum %s" % (started[1] or "of an unknown version", wanted)
        else:
            return program, started[0], notes
        if explicit:
            raise InstallerError("tmux_environment", "%s=%s %s. Nothing was changed." % (EXPLICIT, program, reason))
        if os.path.lexists(program):            # a company tmux that this host does not have is not worth a note
            notes.append("The tmux %s %s." % (program, reason))
    notes.append("No tmux of the minimum version %s was found, so this release records none and every tmux action "
                 "of it fails (`tmux_unavailable`). Install one (the company tmux is in %s) or name it with %s, and "
                 "install again (contract section 6.2)."
                 % (wanted, runs.api_of(source_root).COMPANY_TMUX, EXPLICIT))
    return "", "", notes


def check(release, source_root):
    """`(text, failing)` when the release's tmux record is not usable, else None.

    A release made before the record existed has none: that is a notice (the release still finds `tmux` in PATH).
    A record that names a tmux which does not run in an empty environment, or is older than the minimum, or names
    none, is a failure."""
    values = read(release)
    if values is None:
        return "This release records no tmux (made before TMUX-004); it runs the first tmux in PATH.", False
    program = values.get("PROJECT_AGENT_TMUX", "")
    library = values.get("PROJECT_AGENT_TMUX_LD_LIBRARY_PATH", "")
    wanted = minimum(release)
    if not program:
        return ("This release records no tmux: none of the minimum version %s was found when it was made. Install one "
                "(the company tmux is in %s) and run `upgrade` or `install` again."
                % (wanted, runs.api_of(source_root).COMPANY_TMUX)), True
    version = version_of(program, library)
    if version is None:
        return ("The tmux %s that this release records does not run in an empty environment "
                "(PROJECT_AGENT_TMUX_LD_LIBRARY_PATH=%s in %s). Install it again or run the installer again."
                % (program, library, TMUX_ENV)), True
    if number(version) < number(wanted or ""):
        return ("The tmux %s that this release records is %s, older than the minimum %s. Run the installer again "
                "with a newer one." % (program, version or "of an unknown version", wanted)), True
    return None
