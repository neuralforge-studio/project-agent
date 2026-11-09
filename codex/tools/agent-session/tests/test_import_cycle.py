"""agent-session and project-item use each other, but no import cycle exists at import time.

Boundary: docs/project-team/README.md ("의존 관계", "예외: 양방향 의존"). agent-session imports
project-item only inside `jobs.item_api()`; project-item imports agent-session at module load.
Each case runs in a new interpreter whose `sys.path` holds only the entry point's own tool, as
the real entry points do, and checks that the first import succeeds.
Limit: this checks the four import orders below. It does not see a cycle that only a different
`sys.path` or a dynamic import (`importlib`) would create.
"""
import ast
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2]

# (test id, tool directory put on sys.path, module imported first)
ORDERS = (
    ("agent_session_api_first", "agent-session", "agent_session.api"),
    ("project_item_api_first", "project-item", "project_item.api"),
    ("project_board_model", "project-board", "project_board.model"),
    ("agent_session_internal_hook_path", "agent-session", "agent_session.internal"),
)

_PROGRAM = """
import importlib, sys
sys.path.insert(0, {path!r})
importlib.import_module({module!r})
if {lazy!r}:
    loaded = sorted(name for name in sys.modules if name.split('.')[0] == 'project_item')
    assert not loaded, 'project_item loaded at import time: ' + ', '.join(loaded)
"""


@pytest.mark.parametrize("tool,module", [order[1:] for order in ORDERS], ids=[order[0] for order in ORDERS])
def test_first_import_succeeds_in_a_new_interpreter(tool, module):
    # agent-session must not pull in project-item until jobs.item_api() runs.
    program = _PROGRAM.format(path=str(TOOLS / tool), module=module, lazy=tool == "agent-session")
    result = subprocess.run([sys.executable, "-I", "-c", program], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"import {module} failed:\n{result.stderr}"


PACKAGE = TOOLS / "agent-session" / "agent_session"


def _imports(module):
    """Names of the agent_session modules that `module` imports anywhere, including inside functions."""
    found = set()
    for node in ast.walk(ast.parse((PACKAGE / f"{module}.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                found.add(node.module.split(".")[0])
            else:
                found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(alias.name.split(".")[1] for alias in node.names
                         if alias.name.startswith("agent_session."))
    return found


def test_lifecycle_and_suspend_do_not_import_each_other():
    # Manager inherits SuspendMixin, so lifecycle -> suspend is the one allowed direction.
    # Fleet gets the Manager from the assembling code (cli) instead of importing it.
    assert "suspend" in _imports("lifecycle")
    assert "lifecycle" not in _imports("suspend")
