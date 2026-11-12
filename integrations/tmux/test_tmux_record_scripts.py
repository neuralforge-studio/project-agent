"""The shell scripts of the tmux integration run the tmux the installer recorded, not the one in their PATH (TMUX-004).

A tmux server runs these scripts from hooks and keys, with whatever PATH the server has. Each script reads
`tools/tmux.env` of its release through `tools/tmux-launcher.sh` (install contract 6.2). The stubs here record the
call and the library path they were given."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from wait_limit import command_timeout

TMUX_DIR = Path(__file__).resolve().parent
TOOLS = TMUX_DIR.parents[1] / "tools"
SCRIPTS = ("project_agent_bind.sh", "project_agent_run.sh", "project_board_visibility.sh", "tmux_decide_status.sh",
           "tmux_decide_status.py")


def stub(path, tag, log):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\necho "%s ld=$LD_LIBRARY_PATH $*" >> "%s"\n' % (tag, log))
    path.chmod(0o755)
    return path


@pytest.fixture
def release(tmp_path):
    """A release layout: the scripts, both launchers, a recorded tmux stub and a different one in PATH."""
    root = tmp_path / "release"
    target = root / "integrations" / "tmux"
    target.mkdir(parents=True)
    for name in SCRIPTS:
        shutil.copy2(TMUX_DIR / name, target / name)
    (root / "tools").mkdir()
    for name in ("python-launcher.sh", "tmux-launcher.sh"):
        shutil.copy2(TOOLS / name, root / "tools" / name)
    log = tmp_path / "log"
    recorded = stub(tmp_path / "recorded" / "tmux", "recorded", log)
    stub(tmp_path / "wrong" / "tmux", "wrong", log)
    python = tmp_path / "python"
    python.write_text('#!/bin/sh\necho "python tmux=$PROJECT_AGENT_TMUX ld=$LD_LIBRARY_PATH" >> "%s"\n' % log)
    python.chmod(0o755)
    (root / "tools" / "python.env").write_text("PROJECT_AGENT_PYTHON=%s\nPROJECT_AGENT_PYTHONPATH=\n" % python)
    (root / "tools" / "tmux.env").write_text("PROJECT_AGENT_TMUX=%s\nPROJECT_AGENT_TMUX_LD_LIBRARY_PATH=/lib/x\n" % recorded)
    return root, log, recorded


def run(tmp_path, command):
    """The script as the server runs it: a PATH that holds a different tmux, and nothing else of the user's."""
    env = {"PATH": "%s:/usr/bin:/bin" % (tmp_path / "wrong"), "HOME": str(tmp_path / "home"),
           "XDG_CACHE_HOME": str(tmp_path / "cache")}
    return subprocess.run(command, env=env, capture_output=True, text=True, timeout=command_timeout(), cwd=str(tmp_path))


def calls(log):
    return log.read_text().splitlines() if log.exists() else []


def test_the_bind_helper_runs_the_recorded_tmux(release, tmp_path):
    root, log, recorded = release
    done = run(tmp_path, ["bash", str(root / "integrations/tmux/project_agent_bind.sh"), "--socket", "/s"])
    assert done.returncode == 0, done.stderr
    found = calls(log)
    assert found and all(line.startswith("recorded ld=/lib/x -S /s ") for line in found), found


def test_the_visibility_helper_runs_the_recorded_tmux(release, tmp_path):
    root, log, recorded = release
    done = run(tmp_path, ["sh", str(root / "integrations/tmux/project_board_visibility.sh"), "--socket", "/s"])
    assert done.returncode == 0, done.stderr
    found = calls(log)
    assert found and all(line.startswith("recorded ld=/lib/x -S /s ") for line in found), found


def test_the_failure_record_of_a_job_is_written_by_the_recorded_tmux(release, tmp_path):
    root, log, recorded = release
    done = run(tmp_path, ["sh", str(root / "integrations/tmux/project_agent_run.sh"), "hook", "/s", "false"])
    assert done.returncode == 0, done.stderr
    found = calls(log)
    assert found and all(line.startswith("recorded ld=/lib/x -S /s set-option -g @project_agent_last_error ")
                         for line in found), found


def test_the_decision_status_runs_its_script_with_the_recorded_tmux_and_its_library(release, tmp_path):
    root, log, recorded = release
    done = run(tmp_path, ["bash", str(root / "integrations/tmux/tmux_decide_status.sh")])
    assert done.returncode == 0, done.stderr
    assert calls(log) == ["python tmux=%s ld=/lib/x" % recorded]


def test_a_record_without_a_tmux_stops_the_decision_status_with_exit_5(release, tmp_path):
    root, log, _ = release
    (root / "tools" / "tmux.env").write_text("PROJECT_AGENT_TMUX=\n")
    done = run(tmp_path, ["bash", str(root / "integrations/tmux/tmux_decide_status.sh")])
    assert done.returncode == 5 and "No tmux" in done.stderr
    assert calls(log) == []


def test_a_checkout_without_a_record_uses_the_tmux_in_path(release, tmp_path):
    root, log, _ = release
    (root / "tools" / "tmux.env").unlink()
    done = run(tmp_path, ["sh", str(root / "integrations/tmux/project_board_visibility.sh"), "--socket", "/s"])
    assert done.returncode == 0, done.stderr
    found = calls(log)
    assert found and all(line.startswith("wrong ld= -S /s ") for line in found), found


def test_the_decision_script_runs_the_tmux_the_wrapper_chose(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("decide_for_record_test", TMUX_DIR / "tmux_decide_status.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    log = tmp_path / "log"
    chosen = stub(tmp_path / "chosen" / "tmux", "chosen", log)
    monkeypatch.setenv("PROJECT_AGENT_TMUX", str(chosen))
    assert module.tmux("list-clients") == ""
    assert calls(log) == ["chosen ld=%s list-clients" % os.environ.get("LD_LIBRARY_PATH", "")]
