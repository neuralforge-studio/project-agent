"""The one existing file the installer edits: the managed block in the user's tmux settings (contract section 3)."""

import os

BEGIN = "# >>> project-agent (managed block, do not edit) >>>"
SOURCE = "source-file -q ~/.local/lib/project-agent/tmux.conf"
END = "# <<< project-agent <<<"
# The first newline belongs to the block: removing the block restores the original byte for byte, also
# when the original did not end with a newline.
BLOCK = ("\n%s\n%s\n%s\n" % (BEGIN, SOURCE, END)).encode()
INTEGRATION = "source-file -q ~/.local/lib/project-agent/current/integrations/tmux/project-agent.conf\n"
LIMIT = 1 << 20                 # a larger tmux file is not rewritten: the installer prints the line instead
RELOAD = "tmux source-file ~/.local/lib/project-agent/tmux.conf"


def has_block(data):
    return BEGIN.encode() in data.split(b"\n")


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
