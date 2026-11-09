"""Other tools use agent-session only through `agent_session.api`; its modules share no underscore names.

Boundary: docs/project-team/README.md ("공개 진입점", "의존 관계(현행)") and docs/project-team/spec.md
section 5. The public names are `api.__all__` and nowhere else.
Limit: this reads import statements only. A dynamic import (`__import__`, `importlib`) and
monkeypatch targets in tests are not seen.
"""
import ast
from pathlib import Path

from agent_session import api

REPO = Path(__file__).resolve().parents[3]
PACKAGE = "agent_session"
PUBLIC = f"{PACKAGE}.api"
SOURCE = Path(api.__file__).parent


def _is_test(relative: Path) -> bool:
    return "tests" in relative.parts or relative.name.startswith("test_") or "fixtures" in relative.parts


def _other_tool_files():
    for root in ("tools", "integrations"):
        for path in sorted((REPO / root).rglob("*.py")):
            relative = path.relative_to(REPO)
            if relative.parts[:2] != ("tools", "agent-session") and not _is_test(relative):
                yield relative


def outside_violations(source: str) -> list[str]:
    """Imports of agent-session names other than `agent_session.api` and the names it lists."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [f"line {node.lineno}: import {alias.name}" for alias in node.names
                      if (alias.name == PACKAGE or alias.name.startswith(PACKAGE + ".")) and alias.name != PUBLIC]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == PACKAGE:
                found += [f"line {node.lineno}: from {PACKAGE} import {alias.name}"
                          for alias in node.names if alias.name != "api"]
            elif node.module == PUBLIC:
                found += [f"line {node.lineno}: {alias.name} is not in agent_session.api.__all__"
                          for alias in node.names if alias.name not in api.__all__]
            elif node.module.startswith(PACKAGE + "."):
                found.append(f"line {node.lineno}: from {node.module} import ...")
    return found


def private_imports(source: str) -> list[str]:
    """Imports of an underscore name from another module of the package."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ImportFrom):
            continue
        from_package = node.level == 1 or (node.level == 0 and (node.module or "").split(".")[0] == PACKAGE)
        if from_package:
            found += [f"line {node.lineno}: {alias.name}" for alias in node.names if alias.name.startswith("_")]
    return found


def test_other_tools_import_only_the_public_api():
    consumers = []
    for relative in _other_tool_files():
        source = (REPO / relative).read_text(encoding="utf-8")
        if PACKAGE in source:
            consumers.append(relative.name)
        assert outside_violations(source) == [], str(relative)
    assert {"registry.py", "model.py", "tmux_control.py"} <= set(consumers)


def test_package_modules_import_no_underscore_name_from_each_other():
    modules = sorted(SOURCE.rglob("*.py"))
    assert len(modules) > 10
    for path in modules:
        assert private_imports(path.read_text(encoding="utf-8")) == [], str(path.relative_to(SOURCE))


def test_the_checks_see_violations_and_accept_the_api():
    assert outside_violations("from agent_session import api\nfrom agent_session.api import SessionError, Tmux\n"
                              "import agent_session.api\n") == []
    bad = ("from agent_session.config import load_registry\n"
           "from agent_session import tmux\n"
           "import agent_session.errors\n"
           "def f():\n    from agent_session.tmux import Tmux\n"
           "from agent_session.api import _tmux\n")
    assert len(outside_violations(bad)) == 5
    assert private_imports("from .tmux import Tmux, check_owner\nfrom json import _x\n") == []
    assert len(private_imports("from .api import _project\nfrom . import _tmux\n"
                               "from agent_session.state import _x\n")) == 3


def test_public_names_are_one_list_and_all_resolve():
    assert len(set(api.__all__)) == len(api.__all__)
    for name in api.__all__:
        assert hasattr(api, name), name
    assert api.PANE_ID_OPTION == "@agent_session_pane_id"
