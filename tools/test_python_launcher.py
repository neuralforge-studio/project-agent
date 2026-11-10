"""The three CLI entry points select Python through python-launcher.sh (install contract 6.1)."""

import json
import os
from pathlib import Path
import shutil
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
            if key not in ("PROJECT_AGENT_PYTHON", "PROJECT_AGENT_PYTHONPATH", "PROJECT_AGENT_LD_LIBRARY_PATH", "PYTHONPATH")}
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
    # agent-session and project-item (standard library only) skip the site step: `-S` first. project-board
    # needs the interpreter's site-packages for textual: `python -m <package>`.
    assert result.stdout.startswith("ARGV1=-m" if name == "project-board" else "ARGV1=-S")


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


@pytest.mark.parametrize("command,site_flag", [("sync", True), ("click", True), ("toggle", True),
                                                ("sidebar", False), ("popup", False), (None, False)])
def test_project_board_skips_site_only_for_the_commands_without_textual(command, site_flag, fake_python):
    """The tmux hooks and keys run at every window change and import no textual; the TUI needs site-packages."""
    result = run(ENTRIES["project-board"], *([command] if command else []), env={"PROJECT_AGENT_PYTHON": str(fake_python)})
    assert result.stdout.startswith("ARGV1=-S" if site_flag else "ARGV1=-m")


def test_project_board_without_package_paths_keeps_only_its_root(fake_python):
    result = run(ENTRIES["project-board"], env={"PROJECT_AGENT_PYTHON": str(fake_python)})
    assert f"PYTHONPATH={ENTRIES['project-board'].parents[1]} " in result.stdout


def test_project_item_ignores_package_paths(fake_python, tmp_path):
    result = run(ENTRIES["project-item"], env={"PROJECT_AGENT_PYTHON": str(fake_python),
                                               "PROJECT_AGENT_PYTHONPATH": str(tmp_path)})
    assert f"PYTHONPATH={ENTRIES['project-item'].parents[1]} " in result.stdout


@pytest.mark.parametrize("name", ["agent-session", "project-item"])
def test_standard_library_tools_do_not_run_the_site_step(name, tmp_path):
    """`-S`: site-packages, `.pth` files and sitecustomize cost tens of milliseconds on NFS and are not needed."""
    (tmp_path / "sitecustomize.py").write_text(f"open({str(tmp_path / 'ran')!r}, 'w').close()\n")
    result = run(ENTRIES[name], "--help", env={"PYTHONPATH": str(tmp_path)})
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "ran").exists()


@pytest.mark.parametrize("name", sorted(ENTRIES))
def test_entry_point_runs_from_its_own_directory_and_through_a_linked_directory(name, tmp_path):
    """The directory of the entry point and of the launcher is found without `dirname`."""
    entry = ENTRIES[name]
    result = subprocess.run(["bash", entry.name, "--help"], cwd=entry.parent, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    (tmp_path / "tools").symlink_to(TOOLS)
    linked = tmp_path / "tools" / name / "bin" / name
    result = subprocess.run([str(linked), "--help"], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", sorted(ENTRIES))
def test_development_checkout_runs_without_installer_values(name):
    result = run(ENTRIES[name], "--help")
    assert result.returncode == 0, result.stderr
    assert "usage" in result.stdout.lower()


# python.env: the installer's values, read by the launcher where the environment has none.
ROOT = TOOLS.parent
RELEASE_ENTRIES = (*sorted(ENTRIES), "tmux_project_board.sh", "tmux_decide_status.sh")


def release_entry(release, name):
    if name in ENTRIES:
        return release / "tools" / name / "bin" / name
    return release / "integrations" / "tmux" / name


@pytest.fixture
def release(tmp_path):
    """A release layout (launcher, the three entry points, the tmux helpers) with no python.env."""
    root = tmp_path / "release"
    (root / "tools").mkdir(parents=True)
    shutil.copy2(TOOLS / "python-launcher.sh", root / "tools")
    for name in ENTRIES:
        shutil.copytree(TOOLS / name / "bin", root / "tools" / name / "bin")
    shutil.copytree(ROOT / "integrations" / "tmux", root / "integrations" / "tmux",
                    ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    return root


def write_env(release, *lines):
    (release / "tools" / "python.env").write_text("".join(line + "\n" for line in lines))


@pytest.mark.parametrize("name", RELEASE_ENTRIES)
def test_python_env_alone_selects_the_interpreter_and_packages(name, release, fake_python, tmp_path):
    packages = f"{tmp_path}/lib/a:{tmp_path}/lib/b"
    write_env(release, f"PROJECT_AGENT_PYTHON={fake_python}", f"PROJECT_AGENT_PYTHONPATH={packages}")
    result = run(release_entry(release, name), "--help")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("ARGV1=")
    if name in ("project-board", "tmux_project_board.sh"):
        root = release / "tools" / "project-board"
        assert f"PYTHONPATH={root}:{packages} " in result.stdout
    if name != "agent-session":
        assert "NOUSERSITE=1" in result.stdout


def test_interpreter_path_may_contain_spaces(release, tmp_path):
    spaced = tmp_path / "my python dir" / "python"
    spaced.parent.mkdir()
    spaced.write_text('#!/bin/sh\necho SPACED\n')
    spaced.chmod(0o755)
    write_env(release, f"PROJECT_AGENT_PYTHON={spaced}")
    assert run(release_entry(release, "project-item")).stdout == "SPACED\n"


@pytest.mark.parametrize("name", RELEASE_ENTRIES)
def test_environment_variables_win_over_python_env(name, release, fake_python, tmp_path):
    other = tmp_path / "other-python"
    other.write_text('#!/bin/sh\necho FROM-FILE\n')
    other.chmod(0o755)
    write_env(release, f"PROJECT_AGENT_PYTHON={other}", f"PROJECT_AGENT_PYTHONPATH={tmp_path}/from-file")
    result = run(release_entry(release, name), env={"PROJECT_AGENT_PYTHON": str(fake_python),
                                                    "PROJECT_AGENT_PYTHONPATH": f"{tmp_path}/from-env"})
    assert result.stdout.startswith("ARGV1=")
    assert "from-file" not in result.stdout
    if name in ("project-board", "tmux_project_board.sh"):
        assert f"{tmp_path}/from-env " in result.stdout


def test_missing_interpreter_in_python_env_is_the_unavailable_error(release, tmp_path):
    write_env(release, f"PROJECT_AGENT_PYTHON={tmp_path / 'absent'}")
    result = run(release_entry(release, "agent-session"), "--help")
    assert result.returncode == 5
    assert json.loads(result.stdout)["error"]["code"] == "python_unavailable"
    for name in ("project-item", "project-board", "tmux_project_board.sh", "tmux_decide_status.sh"):
        result = run(release_entry(release, name), "--help")
        assert result.returncode == 5
        assert result.stdout == ""
        assert "unavailable" in result.stderr


def test_python_env_is_parsed_not_executed(release, fake_python, tmp_path):
    marks = [tmp_path / f"mark{number}" for number in range(4)]
    write_env(release, f"$(touch {marks[0]})", f"touch {marks[1]}", f"OTHER=$(touch {marks[2]})",
              f"PROJECT_AGENT_PYTHON={fake_python}", f"`touch {marks[3]}`")
    result = run(release_entry(release, "project-item"))
    assert result.stdout.startswith("ARGV1=-S")
    assert not any(mark.exists() for mark in marks)


def test_python_env_value_is_literal(release, tmp_path):
    mark = tmp_path / "mark"
    write_env(release, f"PROJECT_AGENT_PYTHON=$(touch {mark})")
    assert run(release_entry(release, "project-item")).returncode == 5
    assert not mark.exists()


def test_python_env_other_names_do_not_select_an_interpreter(release, fake_python):
    # Without PROJECT_AGENT_PYTHON in the file the development checkout rule applies.
    write_env(release, f"PYTHON={fake_python}", f"PROJECT_AGENT_PYTHONX={fake_python}")
    assert not run(release_entry(release, "project-item"), "--help").stdout.startswith("ARGV1=")



# PROJECT_AGENT_LD_LIBRARY_PATH: the library directory the installer's interpreter needs (INSTALL-006).
@pytest.fixture
def ld_python(tmp_path):
    path = tmp_path / "ld-python"
    path.write_text('#!/bin/sh\nprintf "LD=%s\\n" "$LD_LIBRARY_PATH"\n')
    path.chmod(0o755)
    return path


@pytest.mark.parametrize("name", RELEASE_ENTRIES)
def test_python_env_library_path_goes_in_front_of_ld_library_path(name, release, ld_python):
    write_env(release, f"PROJECT_AGENT_PYTHON={ld_python}", "PROJECT_AGENT_LD_LIBRARY_PATH=/lib/installed")
    result = run(release_entry(release, name), env={"LD_LIBRARY_PATH": "/lib/users"})
    assert result.stdout == "LD=/lib/installed:/lib/users\n"


def test_library_path_alone_is_the_whole_value_without_a_user_value(release, ld_python):
    write_env(release, f"PROJECT_AGENT_PYTHON={ld_python}", "PROJECT_AGENT_LD_LIBRARY_PATH=/lib/installed")
    env = {key: value for key, value in os.environ.items() if key != "LD_LIBRARY_PATH"}
    result = subprocess.run([str(release_entry(release, "project-item"))], env=env, capture_output=True, text=True)
    assert result.stdout == "LD=/lib/installed\n"


def test_environment_library_path_wins_over_python_env(release, ld_python):
    write_env(release, f"PROJECT_AGENT_PYTHON={ld_python}", "PROJECT_AGENT_LD_LIBRARY_PATH=/lib/from-file")
    result = run(release_entry(release, "project-item"), env={"PROJECT_AGENT_LD_LIBRARY_PATH": "/lib/from-env",
                                                              "LD_LIBRARY_PATH": ""})
    assert result.stdout == "LD=/lib/from-env\n"


def test_library_path_is_not_applied_without_the_installer_interpreter(release, ld_python):
    """The development checkout rule is unchanged: the value is only read together with PROJECT_AGENT_PYTHON."""
    write_env(release, "PROJECT_AGENT_LD_LIBRARY_PATH=/lib/installed")
    result = run(release_entry(release, "project-item"), "--help", env={"LD_LIBRARY_PATH": "/lib/users"})
    assert "/lib/installed" not in result.stdout + result.stderr
