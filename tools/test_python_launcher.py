"""The three CLI entry points select Python through python-launcher.sh (install contract 6.1)."""

import json
import os
from pathlib import Path
import subprocess

import pytest

TOOLS = Path(__file__).resolve().parent
ENTRIES = {name: TOOLS / name / "bin" / name for name in ("agent-session", "project-item", "project-board")}


def run(entry, *args, env=None, link_dir=None):
    path = entry
    if link_dir is not None:
        path = link_dir / entry.name
        path.symlink_to(entry)
    base = {key: value for key, value in os.environ.items()
            if key not in ("PROJECT_AGENT_PYTHON", "PROJECT_AGENT_PYTHONPATH", "PYTHONPATH")}
    return subprocess.run([str(path), *args], env={**base, **(env or {})}, capture_output=True, text=True, timeout=60)


@pytest.fixture
def fake_python(tmp_path):
    """An interpreter that reports how the launcher called it."""
    path = tmp_path / "fake-python"
    path.write_text('#!/bin/sh\nprintf "ARGV1=%s PYTHONPATH=%s NOUSERSITE=%s\\n" "$1" "$PYTHONPATH" "$PYTHONNOUSERSITE"\n')
    path.chmod(0o755)
    return path


@pytest.mark.parametrize("name", sorted(ENTRIES))
def test_installer_interpreter_is_the_only_candidate(name, fake_python):
    result = run(ENTRIES[name], "--help", env={"PROJECT_AGENT_PYTHON": str(fake_python)})
    assert result.returncode == 0
    assert result.stdout.startswith("ARGV1=")
    # project-item and project-board run `python -m <package>`; agent-session runs `python -c <source>`.
    assert ("ARGV1=-c" if name == "agent-session" else "ARGV1=-m") in result.stdout


def test_missing_interpreter_is_a_json_error_for_agent_session(tmp_path):
    result = run(ENTRIES["agent-session"], "--help", env={"PROJECT_AGENT_PYTHON": str(tmp_path / "absent")})
    assert result.returncode == 5
    error = json.loads(result.stdout)
    assert (error["ok"], error["error"]["code"]) == (False, "python_unavailable")


@pytest.mark.parametrize("name", ["project-item", "project-board"])
def test_missing_interpreter_stops_the_other_entry_points(name, tmp_path):
    result = run(ENTRIES[name], "--help", env={"PROJECT_AGENT_PYTHON": str(tmp_path / "absent")})
    assert result.returncode == 5
    assert result.stdout == ""
    assert "unavailable" in result.stderr


def test_project_board_adds_package_paths_after_its_own_root(fake_python, tmp_path):
    packages = f"{tmp_path}/lib/a:{tmp_path}/lib/b"
    result = run(ENTRIES["project-board"], env={"PROJECT_AGENT_PYTHON": str(fake_python),
                                                "PROJECT_AGENT_PYTHONPATH": packages}, link_dir=tmp_path)
    root = str(ENTRIES["project-board"].parents[1])
    assert f"PYTHONPATH={root}:{packages} " in result.stdout
    assert "NOUSERSITE=1" in result.stdout


def test_project_board_without_package_paths_keeps_only_its_root(fake_python):
    result = run(ENTRIES["project-board"], env={"PROJECT_AGENT_PYTHON": str(fake_python)})
    assert f"PYTHONPATH={ENTRIES['project-board'].parents[1]} " in result.stdout


def test_project_item_ignores_package_paths(fake_python, tmp_path):
    result = run(ENTRIES["project-item"], env={"PROJECT_AGENT_PYTHON": str(fake_python),
                                               "PROJECT_AGENT_PYTHONPATH": str(tmp_path)})
    assert f"PYTHONPATH={ENTRIES['project-item'].parents[1]} " in result.stdout


@pytest.mark.parametrize("name", sorted(ENTRIES))
def test_development_checkout_runs_without_installer_values(name):
    result = run(ENTRIES[name], "--help")
    assert result.returncode == 0, result.stderr
    assert "usage" in result.stdout.lower()
