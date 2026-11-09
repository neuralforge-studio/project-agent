"""The one existing file the installer edits: the managed block in the user's tmux settings (contract section 3)."""

BEGIN = "# >>> project-agent (managed block, do not edit) >>>"
SOURCE = "source-file -q ~/.local/lib/project-agent/tmux.conf"
END = "# <<< project-agent <<<"
# The first newline belongs to the block: removing the block restores the original byte for byte, also
# when the original did not end with a newline.
BLOCK = ("\n%s\n%s\n%s\n" % (BEGIN, SOURCE, END)).encode()
INTEGRATION = "source-file -q ~/.local/lib/project-agent/current/integrations/tmux/project-agent.conf\n"
RELOAD = "tmux source-file ~/.local/lib/project-agent/tmux.conf"


def has_block(data):
    return BEGIN.encode() in data.split(b"\n")


def target(env):
    """The settings file tmux reads first: `~/.tmux.conf`, else `~/.config/tmux/tmux.conf`, else None."""
    import os
    for path in env.tmux_candidates:
        if os.path.lexists(path):
            return path
    return None
