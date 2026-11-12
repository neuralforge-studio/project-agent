"""TEST-015: no test can use the user's real crontab, whatever PATH it sets.

Every check here only reads. A read fails for the same reason a write does (the crontab spool is readable only
with the set-uid privilege of `crontab`), so a regression of the block shows up as a failed assertion
and never as a changed crontab.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
import fake_crontab  # noqa: E402
import real_crontab  # noqa: E402

REAL = "/usr/bin/crontab"
linux_with_crontab = pytest.mark.skipif(
    not sys.platform.startswith("linux") or not os.access(REAL, os.X_OK), reason="needs Linux and /usr/bin/crontab")


def no_new_privs():
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("NoNewPrivs:"):
            return line.split()[1] == "1"
    return None


@linux_with_crontab
def test_the_run_cannot_gain_privilege(request):
    assert no_new_privs() is True


@linux_with_crontab
def test_a_test_that_replaces_path_wholesale_cannot_read_the_real_crontab():
    """The SESSION-016 case: PATH is `<directory>:/usr/bin:/bin`, so the shim is hidden and `crontab` is the real one."""
    for path in ("/usr/bin:/bin", f"{os.getcwd()}:/usr/bin:/bin"):
        done = subprocess.run(["crontab", "-l"], env={**os.environ, "PATH": path}, capture_output=True, text=True)
        assert done.returncode != 0 and "Permission denied" in done.stderr, (path, done)
        assert done.stdout == ""


@linux_with_crontab
def test_the_real_crontab_is_unusable_for_a_grandchild_too(tmp_path):
    script = tmp_path / "run.sh"
    script.write_text(f"#!/bin/sh\nPATH=/usr/bin:/bin {REAL} -l\n")
    script.chmod(0o755)
    done = subprocess.run(["sh", "-c", f"{script}"], capture_output=True, text=True)
    assert done.returncode != 0 and "Permission denied" in done.stderr


def test_a_shim_still_works_under_the_block(tmp_path):
    crontab = tmp_path / "crontab.txt"
    crontab.write_text("0 1 * * * /user-job\n")
    env = {**os.environ, **fake_crontab.install(tmp_path / "bin", crontab)}
    done = subprocess.run(["crontab", "-l"], env=env, capture_output=True, text=True)
    assert (done.returncode, done.stdout) == (0, "0 1 * * * /user-job\n")
    assert shutil.which("crontab", path=env["PATH"]) == str(tmp_path / "bin" / "crontab")


def test_a_platform_without_the_flag_says_the_crontab_is_not_blocked(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.warns(RuntimeWarning, match="real crontab is not blocked"):
        assert real_crontab.block() is False
