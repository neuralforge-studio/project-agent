"""INSTALL-006: the installer records what the interpreter needs to start as itself (install-contract.md 6.1),
and `check` runs it that way in an empty environment."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from harness import INSTALLER, LIB

sys.path.insert(0, str(INSTALLER.parent))
from project_agent_install import release as releases  # noqa: E402
from project_agent_install.layout import InstallerError  # noqa: E402

EMPTY = {"PATH": "/usr/bin:/bin"}


def fake_interpreter(tmp_path, monkeypatch, needs):
    """An executable that reports `sys.prefix` as the installer's only when LD_LIBRARY_PATH is `needs` (any value
    when `needs` is None), else as /usr: the shape of an interpreter whose libpython is not found."""
    prefix = tmp_path / "prefix"
    (prefix / "lib").mkdir(parents=True)
    path = tmp_path / "python"
    test = "true" if needs is None else '[ "$LD_LIBRARY_PATH" = "%s" ]' % needs.replace("{prefix}", str(prefix))
    path.write_text('#!/bin/sh\nif %s; then echo "%s"; else echo /usr; fi\n' % (test, prefix))
    path.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(path))
    monkeypatch.setattr(sys, "prefix", str(prefix))
    return prefix


def test_an_interpreter_that_starts_as_itself_needs_no_library_path(tmp_path, monkeypatch):
    prefix = fake_interpreter(tmp_path, monkeypatch, None)
    assert releases.installer_python() == (str(tmp_path / "python"), str(prefix), "")


def test_the_prefix_lib_directory_is_recorded_when_the_empty_environment_runs_another_python(tmp_path, monkeypatch):
    prefix = fake_interpreter(tmp_path, monkeypatch, "{prefix}/lib")
    assert releases.installer_python() == (str(tmp_path / "python"), str(prefix), str(prefix / "lib"))


def test_the_install_is_refused_when_no_library_path_gives_the_same_prefix(tmp_path, monkeypatch):
    fake_interpreter(tmp_path, monkeypatch, "/somewhere/else")
    with pytest.raises(InstallerError) as error:
        releases.installer_python()
    assert error.value.code == "python_environment" and "sys.prefix" in str(error.value)


def python_env(home, name):
    text = home.read(LIB + "/releases/%s/tools/python.env" % name).decode()
    return dict(line.split("=", 1) for line in text.splitlines())


def test_python_env_names_the_interpreter_its_prefix_and_the_library_path_it_needs(home, source, name):
    assert home.run("install", source=source).returncode == 0
    values = python_env(home, name)
    assert list(values) == ["PROJECT_AGENT_PYTHON", "PROJECT_AGENT_PYTHONPATH", "PROJECT_AGENT_LD_LIBRARY_PATH",
                            "PROJECT_AGENT_PYTHON_PREFIX"]
    assert values["PROJECT_AGENT_PYTHON"] == os.path.abspath(sys.executable)
    assert values["PROJECT_AGENT_PYTHON_PREFIX"] == sys.prefix
    # Independent of the installer's code: the recorded path is what makes an empty environment give that prefix.
    library = values["PROJECT_AGENT_LD_LIBRARY_PATH"]
    started = subprocess.run([sys.executable, "-c", "import sys; print(sys.prefix)"], capture_output=True, text=True,
                             env={**EMPTY, **({"LD_LIBRARY_PATH": library} if library else {})})
    assert started.stdout.strip() == sys.prefix


def clean_run(home, command):
    """The user's login environment is gone: only HOME and a minimal PATH."""
    return subprocess.run(command, capture_output=True, text=True, timeout=120,
                          env={**EMPTY, "HOME": str(home.home)})


def test_the_release_entry_points_and_check_work_in_an_empty_environment(home, source, name):
    assert home.run("install", source=source).returncode == 0
    entry = home.path(LIB + "/current/tools/project-item/bin/project-item")
    result = clean_run(home, [str(entry), "--help"])
    assert result.returncode == 0, result.stderr
    # The interpreter an entry point starts is the installed one: same sys.prefix as at install time.
    launched = clean_run(home, ["bash", "-c", 'source "$1"; project_agent_select_python; "$PY" -c "import sys; '
                          'print(sys.prefix)"', "bash", str(home.path(LIB + "/current/tools/python-launcher.sh"))])
    assert launched.stdout.strip() == sys.prefix
    checked = clean_run(home, [sys.executable, str(INSTALLER), "check", "--json"])
    value = json.loads(checked.stdout)
    assert not [item for item in value.get("failures", []) if "sys.prefix" in item], value


def test_check_fails_when_the_interpreter_would_run_with_another_prefix(home, source, name):
    assert home.run("install", source=source).returncode == 0
    env_file = home.path(LIB + "/releases/%s/tools/python.env" % name)
    release = env_file.parent.parent
    os.chmod(release, 0o755)
    os.chmod(env_file.parent, 0o755)
    os.chmod(env_file, 0o644)
    env_file.write_text(env_file.read_text().replace("PROJECT_AGENT_PYTHON_PREFIX=%s" % sys.prefix,
                                                     "PROJECT_AGENT_PYTHON_PREFIX=/not/the/installed/prefix"))
    result = home.run("check")
    assert result.returncode == 1
    assert "sys.prefix" in result.stdout and "/not/the/installed/prefix" in result.stdout


@pytest.mark.skipif(not os.path.isdir(os.path.join(sys.prefix, "lib")), reason="no <prefix>/lib")
def test_check_fails_when_the_recorded_library_path_is_erased(home, source, name):
    """Only meaningful for an interpreter that needs a library path in an empty environment."""
    assert home.run("install", source=source).returncode == 0
    env_file = home.path(LIB + "/releases/%s/tools/python.env" % name)
    library = python_env(home, name)["PROJECT_AGENT_LD_LIBRARY_PATH"]
    if not library:
        pytest.skip("this interpreter starts as itself without a library path")
    for directory in (env_file.parent.parent, env_file.parent):
        os.chmod(directory, 0o755)
    os.chmod(env_file, 0o644)
    env_file.write_text(env_file.read_text().replace("PROJECT_AGENT_LD_LIBRARY_PATH=%s" % library,
                                                     "PROJECT_AGENT_LD_LIBRARY_PATH="))
    result = home.run("check")
    assert result.returncode == 1 and "empty environment" in result.stdout
