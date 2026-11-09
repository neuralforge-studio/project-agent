"""The paths and names of an installation (install-contract.md section 2) and the user's environment."""

import os
from pathlib import Path

TOOLS = ("agent-session", "project-item", "project-board")
SKILLS = ("project-team", "project-item")
# The Claude and Codex homes; each is relocated by its environment variable (contract section 2, rule 7).
PROVIDERS = (("claude", "CLAUDE_CONFIG_DIR", ".claude"), ("codex", "CODEX_HOME", ".codex"))
REGISTRY_LOCATIONS = (".config/project-agent/project.json", ".codex/project.json", ".claude/project.json")
TMUX_CANDIDATES = (".tmux.conf", ".config/tmux/tmux.conf")


class InstallerError(Exception):
    """A refusal or failure with a code for the output. `exit_code` 3 refuses, 4 failed and was undone."""

    def __init__(self, code, message, details=None, exit_code=3):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.exit_code = exit_code


class Env:
    """The user's home and everything the installer addresses under it. Nothing here reads the disk."""

    def __init__(self):
        self.home = Path.home()
        self.lib = self.home / ".local/lib/project-agent"
        self.bin = self.home / ".local/bin"
        self.releases = self.lib / "releases"
        self.current = self.lib / "current"
        self.tmux_conf = self.lib / "tmux.conf"
        self.record = self.lib / "install.json"
        self.backup = self.lib / "backup"
        self.registry = self.home / REGISTRY_LOCATIONS[0]
        self.registry_candidates = [self.home / location for location in REGISTRY_LOCATIONS]
        self.tmux_candidates = [self.home / location for location in TMUX_CANDIDATES]
        self.runtime_skills_record = self.home / ".cache/agent-session/skills.json"
        self.runtime_codex_skills = self.home / ".codex/skills"

    def shim(self, tool):
        return self.bin / tool

    def provider_homes(self):
        """(provider, home directory) with the environment variable applied."""
        result = []
        for provider, variable, default in PROVIDERS:
            configured = os.environ.get(variable)
            result.append((provider, Path(os.path.abspath(os.path.expanduser(configured))) if configured
                           else self.home / default))
        return result

    def display(self, path):
        """`~/…` for a path under the home, else the path itself (install record and output form)."""
        path = Path(path)
        try:
            return "~/" + path.relative_to(self.home).as_posix()
        except ValueError:
            return str(path)

    def expand(self, text):
        return self.home / text[2:] if text.startswith("~/") else Path(text)
