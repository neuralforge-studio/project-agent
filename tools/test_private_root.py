"""The tools' tests must not share pytest's per-user temporary root with other projects."""

import getpass
import os
from pathlib import Path
import shutil
import site
import subprocess
import sys
import tempfile
import time

import pytest


def test_temporary_directories_are_outside_the_shared_user_root(tmp_path, request):
    root = request.config.option.basetemp
    assert root is not None
    assert Path(root).resolve() in tmp_path.resolve().parents
    shared = Path(tempfile.gettempdir()).resolve() / f"pytest-of-{getpass.getuser()}"
    assert shared not in tmp_path.resolve().parents


# TEST-004: the roots of runs that did not pass are pruned by the next run.
sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
import private_root  # noqa: E402


def dead_pid():
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def make_root(parent, name, pid=None, age=0.0):
    root = parent / name
    root.mkdir()
    (root / "t").mkdir()
    if pid is not None:
        (root / private_root.OWNER).write_text(f"{pid}\n")
    stamp = time.time() - age
    os.utime(root, (stamp, stamp))
    return root


def test_a_new_root_names_its_owner_outside_the_directory_pytest_empties(tmp_path):
    root = Path(private_root.create(tmp_path))
    assert root.name.startswith("pt-")
    assert (root / private_root.OWNER).read_text().strip() == str(os.getpid())
    assert Path(private_root.basetemp(root)).parent == root


def test_prune_keeps_the_newest_ended_roots_and_every_root_whose_owner_is_alive(tmp_path):
    dead = dead_pid()
    ended = [make_root(tmp_path, f"pt-ended{n}", dead, age=100 * n) for n in range(8)]
    running = make_root(tmp_path, "pt-running", os.getpid(), age=10_000_000)
    removed = private_root.prune(tmp_path, keep=5)
    assert sorted(path.name for path in removed) == ["pt-ended5", "pt-ended6", "pt-ended7"]
    assert all(root.exists() for root in ended[:5]) and running.exists()
    assert not any(root.exists() for root in ended[5:])


def test_prune_judges_a_root_without_an_owner_by_its_age_only(tmp_path):
    fresh = make_root(tmp_path, "pt-fresh", age=60)
    old = make_root(tmp_path, "pt-old", age=private_root.UNKNOWN_OWNER_AGE + 60)
    unreadable = make_root(tmp_path, "pt-unreadable")
    (unreadable / private_root.OWNER).write_text("not a pid\n")
    stamp = time.time() - private_root.UNKNOWN_OWNER_AGE - 60
    os.utime(unreadable, (stamp, stamp))
    private_root.prune(tmp_path)
    assert fresh.exists() and not old.exists() and not unreadable.exists()


def test_prune_ignores_what_is_not_a_directory_of_this_user(tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "keep.txt").write_text("x")
    old = time.time() - private_root.UNKNOWN_OWNER_AGE - 60
    link = tmp_path / "pt-link"
    link.symlink_to(target)
    plain = tmp_path / "pt-file"
    plain.write_text("x")
    for path in (link, plain):
        os.utime(path, (old, old), follow_symlinks=False)
    private_root.prune(tmp_path)
    assert link.is_symlink() and plain.exists() and (target / "keep.txt").exists()


# TEST-010: pytest runs that start together prune the same directories at the same time.
def rival_prune(monkeypatch, moment):
    """Make another run's prune remove every listed root at ``moment``: after the listing or after each ``lstat``."""
    real_glob, real_lstat = Path.glob, Path.lstat

    def glob(self, pattern):
        found = list(real_glob(self, pattern))
        if moment == "listing":
            for path in found:
                shutil.rmtree(path)
        return iter(found)

    def lstat(self, *args, **kwargs):
        info = real_lstat(self, *args, **kwargs)
        if moment == "lstat" and self.name.startswith("pt-") and self.exists():
            shutil.rmtree(self)
        return info

    monkeypatch.setattr(Path, "glob", glob)
    monkeypatch.setattr(Path, "lstat", lstat)


@pytest.mark.parametrize("moment", ["listing", "lstat"])
def test_prune_counts_a_root_that_another_run_already_removed_as_removed(tmp_path, monkeypatch, moment):
    dead = dead_pid()
    make_root(tmp_path, "pt-ended", dead)
    make_root(tmp_path, "pt-unknown", age=private_root.UNKNOWN_OWNER_AGE + 60)
    survivor = tmp_path / "other"
    survivor.mkdir()
    rival_prune(monkeypatch, moment)
    private_root.prune(tmp_path, keep=0)
    assert not list(tmp_path.glob("pt-*")) and survivor.exists()


# TEST-014: a run has a HOME of its own, so no test leaves files (project-item locks) in the real HOME.
def test_the_home_of_the_run_is_private(request):
    home = private_root.home(request.config.option.basetemp)
    assert os.environ["HOME"] == home and Path.home() == Path(home)
    assert Path(home).parent == Path(request.config.option.basetemp).parent  # inside the root that holds basetemp


INNER_CONFTEST = """
import sys
sys.path.insert(0, {tests!r})
import private_root


def pytest_configure(config):
    private_root.configure(config)


def pytest_sessionfinish(session, exitstatus):
    private_root.finish(session, exitstatus)
"""

INNER_TEST = """
import os
from pathlib import Path
import site
import subprocess
import sys


def test_one():
    locks = Path.home() / ".cache" / "project-item" / "locks"
    locks.mkdir(parents=True)
    (locks / "leak.lock").write_text("")
    assert Path.home() == Path(os.environ["HOME"])
    child = subprocess.run([sys.executable, "-c", "import site; print(site.getuserbase())"],
                           capture_output=True, text=True, check=True).stdout.strip()
    assert site.getuserbase() == child == os.environ["EXPECT_USERBASE"]
    assert os.environ["RUSTUP_HOME"] == os.environ["EXPECT_RUSTUP"]
"""


@pytest.mark.parametrize("extra", [[], ["--basetemp", "explicit"], ["-n", "2"]], ids=["default", "basetemp", "xdist"])
def test_a_passing_run_leaves_nothing_in_the_real_home_and_removes_its_own(tmp_path, extra):
    if "-n" in extra:
        pytest.importorskip("xdist")
    project = tmp_path / "inner"
    project.mkdir()
    (project / "conftest.py").write_text(INNER_CONFTEST.format(tests=str(Path(__file__).resolve().parent / "tests")))
    (project / "test_inner.py").write_text(INNER_TEST)
    real_home = tmp_path / "real-home"
    real_home.mkdir()
    temp = tmp_path / "tmp"
    temp.mkdir()
    env = {**os.environ, "HOME": str(real_home), "TMPDIR": str(temp)}
    for name in ("PYTEST_ADDOPTS", "PYTEST_XDIST_WORKER", "PYTEST_CURRENT_TEST", "PYTHONUSERBASE", "RUSTUP_HOME"):
        env.pop(name, None)
    env.update(EXPECT_USERBASE=str(real_home / ".local"), EXPECT_RUSTUP=str(real_home / ".rustup"))
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *extra],
                          cwd=project, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    assert list(real_home.iterdir()) == []                 # the real HOME of the run is untouched
    assert list(temp.iterdir()) == []                      # the private root and its HOME are gone
    assert not (project / "explicit-home").exists()        # so is the HOME next to an explicit --basetemp


def test_a_tool_location_that_is_already_set_stays(tmp_path):
    project = tmp_path / "inner"
    project.mkdir()
    (project / "conftest.py").write_text(INNER_CONFTEST.format(tests=str(Path(__file__).resolve().parent / "tests")))
    (project / "test_inner.py").write_text(
        "import os\n\n\ndef test_kept():\n"
        "    assert os.environ['PYTHONUSERBASE'] == os.environ['EXPECT_USERBASE']\n"
        "    assert os.environ['RUSTUP_HOME'] == os.environ['EXPECT_RUSTUP']\n")
    env = {**os.environ, "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
           "PYTHONUSERBASE": str(tmp_path / "ub"), "RUSTUP_HOME": str(tmp_path / "ru")}
    env.update(EXPECT_USERBASE=env["PYTHONUSERBASE"], EXPECT_RUSTUP=env["RUSTUP_HOME"])
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                          cwd=project, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
