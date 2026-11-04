"""The legacy `cr` tool keeps working on the format module of project-item."""
import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2]
LEGACY = TOOLS / "cr"
NAMES = {"STATES", "SEVERITIES", "ID_RE", "TITLE_RE", "HEADER_RE", "SECTION_RE", "DATE_RE", "OUTCOME_RE",
         "STATUS_LINE_RE", "REQUIRED_HEADERS", "FINDING_SECTIONS", "PLAN_SECTIONS", "SECTION_ORDER", "Cr",
         "state_of", "parse", "check", "files", "next_id", "slug", "TEMPLATE", "EMPTY_BODY"}


def legacy_tree(tmp_path):
    """A copy of the cr tool next to the real project-item, with its own programs.json."""
    tools = tmp_path / "tools"
    shutil.copytree(LEGACY, tools / "cr", ignore=shutil.ignore_patterns("__pycache__"))
    (tools / "project-item").symlink_to(TOOLS / "project-item", target_is_directory=True)
    repo = tmp_path / "prog"
    (repo / "docs/cr/open").mkdir(parents=True)
    (tools / "cr/programs.json").write_text(json.dumps({"sessions_dir": str(tmp_path), "programs": {
        "prog": {"repo": str(repo), "cr_dir": "docs/cr", "owner_cwd": [str(repo)]}}}))
    return tools / "cr/bin/cr", repo / "docs/cr"


def test_fmt_re_exports_every_former_name():
    sys.path.insert(0, str(LEGACY))
    try:
        from cr_tool import export, fmt  # noqa: F401  (export imports the names it uses)
        from project_item import cr
    finally:
        sys.path.remove(str(LEGACY))
    assert NAMES <= set(vars(fmt))
    assert all(getattr(fmt, name) is getattr(cr, name) for name in NAMES)


def test_cr_new_list_and_check_through_the_entry(tmp_path):
    entry, root = legacy_tree(tmp_path)
    run = lambda *args: subprocess.run([str(entry), *args], capture_output=True, text=True, cwd=tmp_path)
    created = run("new", "prog", "--area", "TOOL", "--title", "Lost lock")
    assert created.returncode == 0, created.stderr
    assert (root / "open/TOOL-001-lost-lock.md").exists()
    listed = run("list", "prog")
    assert "TOOL-001" in listed.stdout and "open=1" in listed.stdout
    checked = run("check", "prog")
    assert checked.returncode == 0 and "1 checked, 0 with violations" in checked.stdout


def test_new_module_is_the_former_module_plus_parse_text():
    tree = ast.parse((TOOLS / "project-item/project_item/cr.py").read_text())
    names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    names |= {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    assert names == NAMES | {"parse_text"}
