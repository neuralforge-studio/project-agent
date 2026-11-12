"""TMUX-004: the installer records the tmux that project-agent runs, and `check` judges that record
(install-contract.md 6.2, T43 and T44).

A stub `tmux` that only answers `-V` stands for a tmux of any version, so the tests do not depend on the tmux of
the host; the company tmux (which needs library directories) is used where the host has it."""

import os
from pathlib import Path
import re
import stat
import subprocess
import sys

import pytest

from harness import INSTALLER, LIB, REPO, command_timeout

sys.path.insert(0, str(INSTALLER.parent))
from project_agent_install import runs as installer_runs, tmuxrecord  # noqa: E402

COMPANY_DIRECTORY = installer_runs.api_of(REPO).COMPANY_TMUX       # the one definition of the company tmux
COMPANY = os.path.join(COMPANY_DIRECTORY, "tmux")
MINIMUM = re.search(r"^최소 버전: tmux (\S+)$", (REPO / "docs/project-team/install-contract.md").read_text(),
                    re.MULTILINE).group(1)
needs_company = pytest.mark.skipif(not os.access(COMPANY, os.X_OK), reason="this host has no company tmux")


def stub_tmux(home, version, name="stub"):
    """A `tmux` that answers `-V` with `tmux <version>`; returns its path."""
    directory = home.root / name
    directory.mkdir(exist_ok=True)
    path = directory / "tmux"
    path.write_text('#!/bin/sh\n[ "$1" = "-V" ] && echo "tmux %s"\n' % version)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def in_path(home, path):
    return {"PATH": str(Path(path).parent) + os.pathsep + home.env["PATH"]}


def recorded(home, name):
    text = home.read(LIB + "/releases/%s/tools/tmux.env" % name).decode()
    return dict(line.split("=", 1) for line in text.splitlines())


def test_the_first_tmux_in_path_is_recorded_when_it_is_new_enough(home, source, name):
    mine = stub_tmux(home, MINIMUM)
    result = home.run("install", source=source, env=in_path(home, mine))
    assert result.returncode == 0, result.stderr
    assert recorded(home, name) == {"PROJECT_AGENT_TMUX": str(mine), "PROJECT_AGENT_TMUX_LD_LIBRARY_PATH": ""}
    assert "older than the minimum" not in result.stdout
    check = home.run("check")                       # the installer's own PATH has no stub: the record decides
    assert check.returncode == 0, check.stdout + check.stderr


@needs_company
def test_an_old_tmux_in_path_is_skipped_and_the_company_tmux_is_recorded_with_its_library_path(home, source, name):
    old = stub_tmux(home, "2.7")
    result = home.run("install", source=source, env=in_path(home, old))
    assert result.returncode == 0, result.stderr
    assert "The tmux %s is 2.7, older than the minimum %s" % (old, MINIMUM) in result.stdout
    values = recorded(home, name)
    assert values["PROJECT_AGENT_TMUX"] == COMPANY
    library = values["PROJECT_AGENT_TMUX_LD_LIBRARY_PATH"]
    assert library                                  # libevent and ncurses are outside the system's directories
    cron_like = subprocess.run([COMPANY, "-V"], capture_output=True, text=True, timeout=command_timeout(),
                               env={"PATH": "/usr/bin:/bin", "LD_LIBRARY_PATH": library})
    assert cron_like.returncode == 0 and cron_like.stdout.startswith("tmux ")
    withoutlib = subprocess.run([COMPANY, "-V"], capture_output=True, text=True, timeout=command_timeout(), env={"PATH": "/usr/bin:/bin"})
    assert withoutlib.returncode != 0               # so the library path in the record is what makes it start
    assert home.run("check").returncode == 0


def test_the_tmux_the_installer_environment_names_wins_over_path(home, source, name):
    mine, other = stub_tmux(home, "3.9", "mine"), stub_tmux(home, "4.0", "other")
    result = home.run("install", source=source, env={**in_path(home, other), "PROJECT_AGENT_TMUX": str(mine)})
    assert result.returncode == 0, result.stderr
    assert recorded(home, name)["PROJECT_AGENT_TMUX"] == str(mine)


@pytest.mark.parametrize("kind", ["old", "missing"])
def test_a_named_tmux_that_cannot_be_used_refuses_the_install_and_changes_nothing(home, source, kind):
    named = stub_tmux(home, "2.7") if kind == "old" else home.root / "gone" / "tmux"
    before = home.snapshot()
    result = home.run("install", source=source, env={"PROJECT_AGENT_TMUX": str(named)})
    assert result.returncode == 3
    assert "tmux_environment" in result.stderr and str(named) in result.stderr
    assert home.snapshot() == before


def restricted_installer(home, tmux):
    """The installer with the tmux candidates reduced to `tmux` (this host has a company tmux that would
    otherwise be found)."""
    path = home.root / "restricted-installer"
    path.write_text('import sys\nsys.argv[0] = %r\nsys.path.insert(0, %r)\n'
                    'from project_agent_install import tmuxrecord\n'
                    'tmuxrecord.candidates = lambda root, environ=None: [(%r, False)]\n'
                    'from project_agent_install.cli import main\nsys.exit(main())\n'
                    % (str(INSTALLER), str(INSTALLER.parent), str(tmux)))
    return path


def test_without_a_usable_tmux_the_install_goes_on_records_none_and_check_fails(home, source, name):
    old = stub_tmux(home, "2.7")
    result = home.run("install", source=source, installer=restricted_installer(home, old))
    assert result.returncode == 0, result.stderr
    assert "No tmux of the minimum version %s was found" % MINIMUM in result.stdout
    assert recorded(home, name) == {"PROJECT_AGENT_TMUX": "", "PROJECT_AGENT_TMUX_LD_LIBRARY_PATH": ""}
    before = home.snapshot()
    check = home.run("check")
    assert check.returncode == 1
    assert "records no tmux" in check.stdout and MINIMUM in check.stdout
    assert home.snapshot() == before


def test_candidates_are_the_named_tmux_then_path_then_the_company_tmux(tmp_path):
    api_company = COMPANY
    first, second = tmp_path / "a", tmp_path / "b"
    for directory in (first, second):
        directory.mkdir()
        (directory / "tmux").write_text("#!/bin/sh\n")
        (directory / "tmux").chmod(0o755)
    found = tmuxrecord.candidates(REPO, {"PROJECT_AGENT_TMUX": str(second / "tmux"), "PATH": str(first)})
    assert found == [(str(second / "tmux"), True), (str(first / "tmux"), False), (api_company, False)]
    assert tmuxrecord.candidates(REPO, {"PATH": "/nonexistent"}) == [(api_company, False)]


def test_a_library_directory_is_found_from_what_ldd_resolves_outside_the_system(tmp_path, monkeypatch):
    class Done:
        stdout = ("\tlinux-vdso.so.1 (0x1)\n\tlibevent.so.7 => /opt/libs/libevent/lib/libevent.so.7 (0x2)\n"
                  "\tlibc.so.6 => /lib64/libc.so.6 (0x3)\n\tlibm.so.6 => /usr/lib64/libm.so.6 (0x4)\n"
                  "\tlibncurses.so.6 => /opt/libs/ncurses/lib/libncurses.so.6 (0x5)\n"
                  "\tlibevent2.so => /opt/libs/libevent/lib/libevent2.so (0x6)\n")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Done())
    assert tmuxrecord.library_candidates("/x/tmux") == ["", "/opt/libs/libevent/lib:/opt/libs/ncurses/lib"]


# T44: `check` judges the record of the current release.

def installed_with(home, source, name, tmux):
    result = home.run("install", source=source, env={"PROJECT_AGENT_TMUX": str(tmux)})
    assert result.returncode == 0, result.stderr
    return recorded(home, name)["PROJECT_AGENT_TMUX"]


@pytest.mark.parametrize("kind, text", [("older", "3.6a"), ("older", "2.7"), ("older", "master"), ("gone", None)])
def test_check_fails_when_the_recorded_tmux_became_older_or_disappeared(home, source, name, kind, text):
    mine = stub_tmux(home, MINIMUM)
    installed_with(home, source, name, mine)
    if text is None:
        mine.unlink()
    else:
        mine.write_text('#!/bin/sh\n[ "$1" = "-V" ] && echo "tmux %s"\n' % text)
    before = home.snapshot()
    result = home.run("check")
    assert result.returncode == 1
    output = result.stdout + result.stderr
    assert str(mine) in output
    assert ("does not run" in output) if text is None else ("older than the minimum %s" % MINIMUM in output)
    assert home.snapshot() == before


def test_check_does_not_look_at_the_tmux_in_the_users_path(home, source, name):
    mine = stub_tmux(home, MINIMUM)
    installed_with(home, source, name, mine)
    for version in ("2.7", "9.9"):
        wrong = stub_tmux(home, version, "path-" + version)
        result = home.run("check", env=in_path(home, wrong))
        assert result.returncode == 0, result.stdout + result.stderr


def test_a_release_without_a_record_is_a_notice_not_a_failure(tmp_path):
    """A release made before TMUX-004 has no `tools/tmux.env`; it keeps running the tmux in PATH."""
    (tmp_path / "tools").mkdir()
    text, failing = tmuxrecord.check(tmp_path, REPO)
    assert "records no tmux (made before TMUX-004)" in text and failing is False


# T45: the whole chain in cron's environment

def test_t45_the_check_line_of_an_installed_release_reaches_the_recorded_tmux_in_crons_environment(home, source, runs):
    """The installer records the tmux; a Leader start writes the check line; cron's minimal environment, with a tmux
    that cannot reach the server first in PATH, runs that line and the run is recorded `ok` (SESSION-016, TMUX-004)."""
    assert home.run("install", source=source).returncode == 0
    runs.start_leader()
    jobs = [line for line in home.crontab.read_text().splitlines() if "agent-session" in line and " check " in line]
    assert len(jobs) == 1
    line = jobs[0].split(None, 5)[5]
    assert "env " not in line and "PATH=" not in line
    wrong = home.root / "wrong"
    wrong.mkdir()
    (wrong / "tmux").write_text("#!/bin/sh\necho 'lost server' >&2\nexit 1\n")
    (wrong / "tmux").chmod(0o755)
    cron = subprocess.run(["env", "-i", "HOME=%s" % home.home, "PATH=%s:/usr/bin:/bin" % wrong, "/bin/sh", "-c", line],
                          capture_output=True, text=True, timeout=command_timeout())
    assert (cron.returncode, cron.stdout, cron.stderr) == (0, "", "")
    import json
    kept = json.loads((runs.base / "agent" / "cron" / "check.json").read_text())
    assert kept["ok"] is True and "code" not in kept, kept
