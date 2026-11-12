"""A release-shaped copy of the tools that records a tmux in `tools/tmux.env` (TMUX-004), for tests that must run
the product the way an installed release runs: in the minimal environment of cron, with no PATH to the tmux.

The tmux is the real one of this host with the library directories it needs, found by the installer's own rule
(`install/project_agent_install/tmuxrecord.py`). The copy leaves out tests, caches and the Rust crate.

This module is test code only: it lives under ``tools/tests`` and is not part of the release."""

from pathlib import Path
import shutil
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "install"))
from project_agent_install import tmuxrecord  # noqa: E402

TOOLS = REPO / "tools"
SHARED = ("python-launcher.sh", "bundle_boot.py", "formats.json")
IGNORE = shutil.ignore_patterns("tests", "test_*.py", "conftest.py", "__pycache__", "*.pyc", "fixtures", "target")


def real_tmux():
    """`(program, library)` of the tmux this host runs: the first of the installer's candidates that starts."""
    program, library, _ = tmuxrecord.choose(REPO)
    assert program, "the host has no tmux of the minimum version"
    return program, library


def release_tools(directory, program, library):
    """`<directory>/tools` with the tools and `tmux.env` naming `program` and `library`; returns that directory."""
    tools = Path(directory) / "tools"
    for tool in ("agent-session", "project-item"):
        shutil.copytree(TOOLS / tool, tools / tool, ignore=IGNORE)
    for name in SHARED:
        shutil.copy2(TOOLS / name, tools / name)
    conf = Path(directory) / "integrations" / "tmux"
    conf.mkdir(parents=True)
    shutil.copy2(REPO / "integrations/tmux/project-agent.conf", conf / "project-agent.conf")
    (tools / "tmux.env").write_bytes(tmuxrecord.env_text(program, library))
    return tools
