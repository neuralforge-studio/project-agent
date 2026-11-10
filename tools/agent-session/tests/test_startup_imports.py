"""What a command imports at start is part of its time: every stdlib or package module is a file read on NFS.

PERF-002. Each case runs in a new interpreter that has only this tool on `sys.path` (as the entry points do)
and checks which modules the code path loaded. A module that comes back into a path that does not use it
fails here. Limit: this checks module names, not time; the timing evidence is in the CR's Result.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2]


def loaded_after(program):
    """Run `program` in `python -I -S`; it must print a JSON list of the module names to report."""
    code = f"import sys, json\nsys.path.insert(0, {str(TOOLS / 'agent-session')!r})\n{program}\n"
    result = subprocess.run([sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return set(json.loads(result.stdout))


def test_a_claude_project_does_not_load_the_codex_provider():
    loaded = loaded_after("""
from agent_session.providers import get_provider
assert type(get_provider("claude")).__name__ == "ClaudeProvider"
print(json.dumps(list(sys.modules)))""")
    assert "agent_session.providers.claude" in loaded
    # The Codex module brings tomllib, the WebSocket client and the URL code with it.
    assert not loaded & {"agent_session.providers.codex", "agent_session.providers.websocket", "tomllib"}


def test_a_codex_project_does_not_load_the_claude_provider():
    loaded = loaded_after("""
from agent_session.providers import get_provider
assert type(get_provider("codex")).__name__ == "CodexProvider"
print(json.dumps(list(sys.modules)))""")
    assert "agent_session.providers.codex" in loaded
    assert "agent_session.providers.claude" not in loaded


def test_the_shared_api_does_not_load_what_only_a_command_needs():
    """project-item and the Board import `agent_session.api`; the SSH archive builder and the lifecycle are not theirs."""
    loaded = loaded_after("import agent_session.api\nprint(json.dumps(list(sys.modules)))")
    assert not loaded & {"zipfile", "base64", "agent_session.lifecycle", "agent_session.providers.codex"}


def test_listing_pending_releases_does_not_load_the_lifecycle(tmp_path):
    """`project-item ls` asks for the held releases of its project; that needs the state and tmux, not a Manager."""
    base = tmp_path / "fx.main"
    base.mkdir()
    config = tmp_path / "project.json"
    config.write_text(json.dumps({str(base): {"project": "fx", "provider": "claude", "seats": ["../fx.seat0"]}}))
    loaded = loaded_after(f"""
from agent_session import api
assert api.pending_releases({str(base)!r}, {str(config)!r}) == {{}}
print(json.dumps(list(sys.modules)))""")
    assert not loaded & {"agent_session.lifecycle", "agent_session.providers.codex", "tomllib", "zipfile"}
