"""BOARD-028: the Rust sidebar and the Python Board read the release they belong to by the same rule.

The Rust binary reads it from its own path (`project-board-sidebar release`, and `--version`), Python from the
`tools/project-board` directory (`release.name_of`). The same layouts are given to both, installed ones and ones that
are not (docs/project-team/README.md, the exception for rules that Rust and Python both hold)."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import board_testing  # noqa: F401  (adds the Board tool to sys.path)
from project_board import release
from rust_binary import sidebar_binary

NAME = "0.11.0-aaaaaaaaaaaa"


def _layout(root, releases="releases", name=NAME, tools="tools", tool="project-board", current="link"):
    """`root/<releases>/<name>/<tools>/<tool>/bin/project-board-sidebar`, a copy of the binary, with `root/current`
    a symlink (`link`), a directory, or missing."""
    tool_dir = root / releases / name / tools / tool
    (tool_dir / "bin").mkdir(parents=True)
    shutil.copy2(sidebar_binary(), tool_dir / "bin" / "project-board-sidebar")
    if current == "link":
        (root / "current").symlink_to(f"{releases}/{name}")
    elif current == "directory":
        (root / "current").mkdir()
    return tool_dir


LAYOUTS = {
    "installed": {},
    "no current": {"current": "none"},
    "current is a directory": {"current": "directory"},
    "not under releases": {"releases": "versions"},
    "tools is another name": {"tools": "tool"},
    "the tool is another name": {"tool": "board"},
}


@pytest.mark.parametrize("situation", list(LAYOUTS))
def test_rust_and_python_name_the_same_release_for_the_same_place(tmp_path, situation):
    tool_dir = _layout(tmp_path.resolve(), **LAYOUTS[situation])
    binary = tool_dir / "bin" / "project-board-sidebar"
    said = json.loads(subprocess.run([str(binary), "release"], capture_output=True, text=True, check=True).stdout)
    assert (said["release"] or "") == release.name_of(tool_dir)
    version = subprocess.run([str(binary), "--version"], capture_output=True, text=True, check=True).stdout.strip()
    assert version == "project-board-sidebar " + (said["release"] or "(not in an installed release)")


def test_the_cases_are_not_vacuous(tmp_path):
    installed = _layout(tmp_path.resolve())
    assert release.name_of(installed) == NAME
    other = _layout(tmp_path.resolve() / "x", current="none")
    assert release.name_of(other) == ""


def test_the_binary_of_a_checkout_is_in_no_release():
    said = json.loads(subprocess.run([str(sidebar_binary()), "release"], capture_output=True, text=True, check=True).stdout)
    assert said == {"release": None}
    assert release.name_of(Path(release.__file__).resolve().parents[1]) == ""
