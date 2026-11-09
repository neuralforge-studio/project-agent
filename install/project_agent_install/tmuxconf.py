"""The one existing file the installer edits: the managed block in the user's tmux settings (contract section 3)."""

import os
from pathlib import Path
import re
import shutil
import subprocess

BEGIN = "# >>> project-agent (managed block, do not edit) >>>"
SOURCE = "source-file -q ~/.local/lib/project-agent/tmux.conf"
END = "# <<< project-agent <<<"
# The first newline belongs to the block: removing the block restores the original byte for byte, also
# when the original did not end with a newline.
BLOCK = ("\n%s\n%s\n%s\n" % (BEGIN, SOURCE, END)).encode()
INTEGRATION = "source-file -q ~/.local/lib/project-agent/current/integrations/tmux/project-agent.conf\n"
LIMIT = 1 << 20                 # a larger tmux file is not rewritten: the installer prints the line instead
RELOAD = "tmux source-file ~/.local/lib/project-agent/tmux.conf"
COMPANY_TMUX = "/primehome/tools/Inhouse/tmux/latest/bin"
# The minimum tmux version has one definition: this option in the integration file, which every tmux
# reads before anything else of it (contract section 3). The installer reads it from there.
MINIMUM = re.compile(r"^set-option -g @project_agent_tmux_min '([^']+)'$", re.MULTILINE)
VERSION = re.compile(r"(?:next-)?(\d+)\.(\d+)")      # `3.8`, `3.6a`, `next-3.9`, as the integration file reads it


def has_block(data):
    return BEGIN.encode() in data.split(b"\n")


def has_source(path):
    """True when the file (a symlink is followed) has the `SOURCE` line as a line of its own that is not a comment."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return False
    return SOURCE.encode() in (line.strip() for line in data.splitlines())


def target(env):
    """The settings file tmux reads first: `~/.tmux.conf`, else `~/.config/tmux/tmux.conf`, else None."""
    for path in env.tmux_candidates:
        if os.path.lexists(path):
            return path
    return None


def rewrite_problem(path, info):
    """Why the installer will not rewrite this file (it prints the line to add instead), or None. A rename makes a
    new file, so it must not break a second name, change the owner, ignore a read-only mark, or lose what the
    file system keeps besides the bytes and the permission bits (ACLs and extended attributes)."""
    if info.st_nlink != 1:
        return "linked under more than one name"
    if info.st_uid != os.getuid():
        return "owned by another user"
    if not os.access(path, os.W_OK):
        return "read-only"
    try:
        if os.listxattr(path, follow_symlinks=False):
            return "carrying extended attributes or ACLs"
    except (OSError, AttributeError):
        pass
    if info.st_size > LIMIT:
        return "larger than 1 MiB"
    return None


def number(version):
    """`major * 1000 + minor` of a tmux version word, 0 when it has no `major.minor` (the integration file
    treats such a tmux as too old as well)."""
    found = VERSION.match(version)
    return int(found.group(1)) * 1000 + int(found.group(2)) if found else 0


def minimum(release):
    """The minimum tmux version of the integration file under the release (or source) root `release`."""
    try:
        found = MINIMUM.search((Path(release) / "integrations/tmux/project-agent.conf").read_text())
    except OSError:
        return None
    return found.group(1) if found else None


def too_old(release):
    """`(text, failing)` when the first `tmux` in PATH is older than the minimum of `release`, else None.
    An older tmux is a failure; no tmux in PATH is only a notice (`failing` is False)."""
    wanted = minimum(release)
    if wanted is None:
        return None
    found = shutil.which("tmux")
    if found is None:
        return "No tmux was found in PATH; project-agent needs tmux %s or newer." % wanted, False
    try:
        output = subprocess.run([found, "-V"], capture_output=True, text=True, timeout=10).stdout.split()
    except (OSError, subprocess.SubprocessError):
        output = []
    version = output[-1] if output else ""
    if number(version) >= number(wanted):
        return None
    return ("The tmux first in PATH is %s (%s), older than the minimum %s; the project-agent tmux integration "
            "binds nothing there. Put %s before it in PATH."
            % (version or "of an unknown version", found, wanted, COMPANY_TMUX)), True
