"""Other tools and tmux scripts use project-item only through `project_item.api`.

Boundary: docs/project-team/README.md ("공개 진입점", "의존 관계(현행)"). The consumers below are
the rows of the 현행 table that use project-item; keep the two in step.
Limit: this reads import statements only. A dynamic import (`__import__`, `importlib`) is not seen.
"""
import ast
from pathlib import Path

from project_item import api

REPO = Path(__file__).resolve().parents[3]
CONSUMERS = (
    "tools/project-board/project_board/model.py",
    "tools/project-board/project_board/answer.py",
    "integrations/tmux/tmux_decide_status.py",
    "tools/agent-session/agent_session/jobs.py",
    "tools/agent-session/agent_session/remote_bridge.py",
)
PACKAGE = "project_item"
PUBLIC = f"{PACKAGE}.api"


def _imports_package(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == PACKAGE for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] == PACKAGE:
            return True
    return False


def violations(source: str) -> list[str]:
    """Imports of project-item names other than `project_item.api` and the names it lists."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if (alias.name == PACKAGE or alias.name.startswith(PACKAGE + ".")) and alias.name != PUBLIC:
                    found.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == PACKAGE:
                found += [f"line {node.lineno}: from {PACKAGE} import {alias.name}"
                          for alias in node.names if alias.name != "api"]
            elif node.module == PUBLIC:
                found += [f"line {node.lineno}: {alias.name} is not in project_item.api.__all__"
                          for alias in node.names if alias.name not in api.__all__]
            elif node.module.startswith(PACKAGE + "."):
                found.append(f"line {node.lineno}: from {node.module} import ...")
    return found


def test_consumers_import_only_the_public_api():
    for relative in CONSUMERS:
        assert violations((REPO / relative).read_text(encoding="utf-8")) == [], relative


def test_every_importing_file_is_a_listed_consumer():
    """A new file that imports project-item must join CONSUMERS (and the 현행 table).
    remote_bridge reaches project-item through `jobs.item_api()`, so it may import nothing itself."""
    importing = set()
    for root in ("tools", "integrations"):
        for path in (REPO / root).rglob("*.py"):
            relative = path.relative_to(REPO)
            if (relative.parts[:2] == ("tools", "project-item") or "tests" in relative.parts
                    or path.name.startswith("test_") or "fixtures" in relative.parts):
                continue
            if _imports_package(path.read_text(encoding="utf-8")):
                importing.add(str(relative))
    assert importing <= set(CONSUMERS)


def test_the_check_sees_internal_imports_and_accepts_the_api():
    assert violations("from project_item import api\nfrom project_item.api import CR, ItemError\n"
                      "import project_item.api\n") == []
    bad = ("from project_item import store\n"
           "from project_item.render import cr_states\n"
           "import project_item.assign\n"
           "def f():\n    from project_item import assign, registry\n"
           "from project_item.api import _private\n")
    assert len(violations(bad)) == 6


def test_the_domain_core_does_not_import_the_output_layer():
    """README "Layers and public API": render.py and cli.py are output; the core never uses them."""
    source = Path(api.__file__).parent
    for name in ("errors", "cr", "decide", "kinds", "read", "store"):
        tree = ast.parse((source / f"{name}.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                imported.add(node.module or "")
                imported.update(alias.name for alias in node.names if not node.module)
        assert not imported & {"render", "cli"}, name
