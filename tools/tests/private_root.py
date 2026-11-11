"""The private temporary root of one pytest run, and how old roots are removed (TEST-004).

A run that passes removes its own ``pt-*`` directory when it ends. A run that fails, is interrupted
or is killed leaves it, which is what a person debugging the failure wants, but nothing removed it
and a day of runs on a shared host left hundreds of them (up to 144 MB each). So the run that
starts next prunes the directories of runs that are over:

- ``owner`` in each directory holds the pid of the pytest that made it (it sits next to ``t``, the
  directory pytest uses and empties). A directory whose owner is still alive belongs to a run in
  progress, this seat's or another seat's, and is never removed.
- Of the directories whose owner is gone, the newest ``KEEP_ENDED`` (5) stay, for debugging; the
  rest are removed. Five is enough to read the last failures of a run and caps the space at about
  five runs, however many runs fail.
- A directory with no readable ``owner`` (made before this rule) cannot be judged by its owner, so
  it is removed only when untouched for ``UNKNOWN_OWNER_AGE`` (24 hours), longer than any run.

The run also gets a HOME of its own (TEST-014), ``<basetemp>-home`` next to the directory pytest uses, so the
root removes it with everything else. ``Path.home()`` and every child process of the run (xdist workers
included, which inherit the environment) then resolve ``~`` there, and no test can leave files such as
``~/.cache/project-item/locks`` in the real HOME or share the lock directory of the real project items. A test
that needs its own HOME still sets one with ``monkeypatch.setenv``.

Two tool locations that the run only reads are derived from HOME, and an empty HOME would lose them: the Python
user site (``PYTHONUSERBASE``, where a ``pip install --user`` puts pytest, xdist and textual) and rustup's
toolchains (``RUSTUP_HOME``, behind a ``~/.cargo/bin/cargo`` proxy). Before HOME changes they are fixed to their
value then, only when unset; a value already set stays. ``CARGO_HOME`` is left alone: its caches belong in the run's HOME.

Runs that start together prune the same directories: one already removed by another run is pruned,
not an error. ``_owner`` and ``rmtree(ignore_errors=True)`` already read it that way.

A pid that was reused by another process makes a directory look alive: it is kept too long, never
removed too early.
"""

import os
from pathlib import Path
import shutil
import site
import tempfile
import time

import pytest

OWNER = "owner"
ROOT_ENV = "PROJECT_AGENT_TEST_ROOT"  # the root of the run in progress, passed on to its xdist workers
PRIVATE_ROOT = pytest.StashKey[str]()
WORKDIR = "t"  # pytest's basetemp inside the root: pytest empties its basetemp, which must not remove ``owner``
KEEP_ENDED = 5
UNKNOWN_OWNER_AGE = 24 * 60 * 60


def create(parent=None):
    """Make this run's ``pt-*`` directory (short, so Unix socket paths stay under ~108 bytes) and name its owner."""
    root = tempfile.mkdtemp(prefix="pt-", dir=parent)
    Path(root, OWNER).write_text(f"{os.getpid()}\n")
    return root


def basetemp(root):
    """The directory to give pytest as ``--basetemp`` for a root made by ``create``."""
    return str(Path(root, WORKDIR))


def _owner(directory):
    """The owner pid, or None when it is missing or unreadable."""
    try:
        return int(Path(directory, OWNER).read_text())
    except (OSError, ValueError):
        return None


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def prune(parent=None, keep=KEEP_ENDED, unknown_age=UNKNOWN_OWNER_AGE, now=None):
    """Remove the ``pt-*`` directories of ended runs beyond ``keep``; return the removed paths."""
    parent = Path(parent or tempfile.gettempdir())
    now = time.time() if now is None else now
    ended, removed = [], []
    for directory in parent.glob("pt-*"):
        try:
            info = directory.lstat()
        except FileNotFoundError:  # another run's prune removed it after the listing: it is already pruned
            continue
        if directory.is_symlink() or not directory.is_dir() or info.st_uid != os.getuid():
            continue
        pid = _owner(directory)
        if pid is None:
            if now - info.st_mtime > unknown_age:
                removed.append(directory)
        elif not _alive(pid):
            ended.append((info.st_mtime, directory))
    removed += [directory for _, directory in sorted(ended, key=lambda item: item[0], reverse=True)[keep:]]
    for directory in removed:
        shutil.rmtree(directory, ignore_errors=True)
    return removed


def home(basetemp):
    """The HOME of the run whose pytest directory is ``basetemp``."""
    return f"{basetemp}-home"


def _isolate_home(basetemp):
    directory = home(basetemp)
    Path(directory).mkdir(parents=True, exist_ok=True)
    if not os.environ.get("PYTHONUSERBASE"):
        os.environ["PYTHONUSERBASE"] = site.getuserbase()
    if not os.environ.get("RUSTUP_HOME"):
        os.environ["RUSTUP_HOME"] = str(Path.home() / ".rustup")
    os.environ["HOME"] = directory


def configure(config, temp=False):
    """The ``pytest_configure`` of a conftest: prune old roots and give this run a root and a HOME of its own.

    An explicit ``--basetemp`` is kept as given (the HOME still goes next to it). With ``temp``,
    ``tempfile`` of the run (and of its xdist workers) also makes its directories inside the root (``m``), for tests that call
    ``mkdtemp`` themselves and so would leave them behind when pytest is killed.
    """
    if hasattr(config, "workerinput"):
        if temp and os.environ.get(ROOT_ENV):
            _temp_inside(os.environ[ROOT_ENV])
        return
    if config.option.basetemp is not None:
        _isolate_home(config.option.basetemp)
        return
    prune()
    root = create()
    config.option.basetemp = basetemp(root)
    config.stash[PRIVATE_ROOT] = root
    _isolate_home(config.option.basetemp)
    if temp:
        os.environ[ROOT_ENV] = root
        _temp_inside(root)


def finish(session, exitstatus):
    """The ``pytest_sessionfinish`` of a conftest: a passing run removes its root."""
    root = session.config.stash.get(PRIVATE_ROOT, None)
    if root and exitstatus == 0:
        shutil.rmtree(root, ignore_errors=True)
    elif exitstatus == 0 and not hasattr(session.config, "workerinput") and session.config.option.basetemp:
        shutil.rmtree(home(session.config.option.basetemp), ignore_errors=True)  # next to an explicit --basetemp


def _temp_inside(root):
    directory = Path(root, "m")
    directory.mkdir(exist_ok=True)
    tempfile.tempdir = str(directory)
