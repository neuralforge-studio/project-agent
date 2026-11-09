"""The tmux minimum version of install-contract.md section 3.2 as `install` and `check` report it.

A stub `tmux` that only answers `-V` is put first in PATH, so the tests do not depend on the tmux of the host.
"""

import os
from pathlib import Path
import re
import stat
import sys

import pytest

from harness import INSTALLER, REPO

COMPANY_TMUX = "/primehome/tools/Inhouse/tmux/latest/bin"
CONTRACT = REPO / "docs/project-team/install-contract.md"


def contract_minimum():
    """The minimum the contract states (the line `최소 버전: tmux X`)."""
    return re.search(r"^최소 버전: tmux (\S+)$", CONTRACT.read_text(), re.MULTILINE).group(1)


def stub_tmux(home, version_text):
    bin_dir = home.root / "stub"
    bin_dir.mkdir(exist_ok=True)
    path = bin_dir / "tmux"
    path.write_text('#!/bin/sh\n[ "$1" = "-V" ] && echo "%s"\n' % version_text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return {"PATH": str(bin_dir) + os.pathsep + home.env["PATH"]}


def installed(home, source, **env):
    result = home.run("install", source=source, env=env)
    assert result.returncode == 0, result.stderr
    return result


def test_the_minimum_of_the_integration_file_is_the_one_of_the_contract():
    conf = (REPO / "integrations/tmux/project-agent.conf").read_text()
    assert re.findall(r"^set-option -g @project_agent_tmux_min '(.+)'$", conf, re.MULTILINE) == [contract_minimum()]
    assert "tmux %s or newer" % contract_minimum() in conf          # the notice of an old tmux names it
    assert COMPANY_TMUX in conf


@pytest.mark.parametrize("version_text", ["tmux 2.7", "tmux 3.6a", "tmux 3.0", "tmux master", "unknown"])
def test_check_fails_when_the_first_tmux_is_older_than_the_minimum(home, source, version_text):
    env = stub_tmux(home, version_text)
    installed(home, source, **env)
    before = home.snapshot()
    result = home.run("check", env=env)
    assert result.returncode == 1
    assert "older than the minimum %s" % contract_minimum() in result.stdout + result.stderr
    assert COMPANY_TMUX in result.stdout + result.stderr
    assert home.snapshot() == before


@pytest.mark.parametrize("version_text", ["tmux 3.8", "tmux 3.9a", "tmux 3.10", "tmux next-3.9", "tmux 4.0"])
def test_check_passes_when_the_first_tmux_is_the_minimum_or_newer(home, source, version_text):
    env = stub_tmux(home, version_text)
    installed(home, source, **env)
    result = home.run("check", env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "older than the minimum" not in result.stdout + result.stderr


def test_install_tells_an_old_tmux_and_still_installs(home, source):
    env = stub_tmux(home, "tmux 2.7")
    result = installed(home, source, **env)
    assert "older than the minimum %s" % contract_minimum() in result.stdout
    assert COMPANY_TMUX in result.stdout
    assert home.path(".local/lib/project-agent/install.json").is_file()


def test_install_is_quiet_about_a_new_enough_tmux(home, source):
    result = installed(home, source, **stub_tmux(home, "tmux %s" % contract_minimum()))
    assert "older than the minimum" not in result.stdout


def test_a_missing_tmux_is_a_notice_for_check(home, source, monkeypatch):
    sys.path.insert(0, str(INSTALLER.parent))
    from project_agent_install import tmuxconf
    monkeypatch.setattr("shutil.which", lambda name: None)
    text, failing = tmuxconf.too_old(REPO)
    assert not failing and "No tmux was found" in text
