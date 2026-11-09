"""The tools' tests must not share pytest's per-user temporary root with other projects."""

import getpass
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


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
