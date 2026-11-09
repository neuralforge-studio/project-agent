"""The product's documents and code must not depend on files outside the product (DIST-003).

A host that has only the installed release has neither a personal guidance directory nor this
repository's common principle documents. The product paths below must not name them.
"""

from pathlib import Path
import re

import pytest

REPOSITORY = Path(__file__).resolve().parents[1]
PRODUCT_PATHS = (
    "tools/agent-session", "tools/project-item", "tools/project-board",
    "tools/python-launcher.sh", "skills/project-team", "skills/project-item",
    "docs/project-team", "integrations/tmux", "CHANGELOG.md", "tools/formats.json",
)
SUFFIXES = {".py", ".md", ".sh", ".json", ".yaml", ".yml", ".txt", ".conf", ""}
# Personal guidance files and the repository's common principle documents. The common principle
# directory is `codex/references/`; the personal copy is `~/.codex/references/` or `~/.claude/references/`.
FORBIDDEN = re.compile(r"(~|\$HOME|\$\{HOME\})/\.(codex|claude)/references|(?<![\w-])codex/references/|(?<![\w.])\.\./references/[\w-]+\.md")
# path -> reason. A file may name a forbidden pattern only to describe or test the rule itself.
ALLOWED = {
    "tools/test_distribution_boundary.py": "defines the rule and its examples",
}


def product_files():
    for entry in PRODUCT_PATHS:
        root = REPOSITORY / entry
        for path in ([root] if root.is_file() else sorted(root.rglob("*"))):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix in SUFFIXES:
                yield path


def test_product_paths_exist():
    assert all((REPOSITORY / entry).exists() for entry in PRODUCT_PATHS)


def test_product_files_do_not_name_personal_or_repository_guidance():
    found = []
    for path in product_files():
        relative = path.relative_to(REPOSITORY).as_posix()
        if relative in ALLOWED:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if FORBIDDEN.search(line):
                found.append(f"{relative}:{number}: {line.strip()[:100]}")
    assert not found, "\n".join(found)


@pytest.mark.parametrize("line", [
    "see ~/.codex/references/planning-execution.md",
    "[x](../../codex/references/program-architecture.md)",
    "cp $HOME/.claude/references/a.md .",
    "[x](../references/verification-rtm.md)",
])
def test_rule_catches_each_reference_form(line):
    assert FORBIDDEN.search(line)


@pytest.mark.parametrize("line", [
    "skills/project-item/references/cr.md",
    "[cr](references/cr.md)",
    "~/.codex/skills/project-team",
])
def test_rule_allows_product_owned_references(line):
    assert not FORBIDDEN.search(line)
