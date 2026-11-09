"""Give each pytest run of the tools its own temporary root.

pytest's default root (``$TMPDIR/pytest-of-<user>``) is shared by every project run by the same
user, and each run prunes the numbered directories of the others. An explicit ``--basetemp`` is
kept as given. Otherwise the run gets a short private directory directly under ``TMPDIR`` (short
so Unix socket paths stay under the ~108 byte limit), removed after a passing run.
"""

import shutil
import tempfile

import pytest

PRIVATE_ROOT = pytest.StashKey[str]()


def pytest_configure(config):
    if config.option.basetemp is not None or hasattr(config, "workerinput"):
        return
    root = tempfile.mkdtemp(prefix="pt-")
    config.option.basetemp = root
    config.stash[PRIVATE_ROOT] = root


def pytest_sessionfinish(session, exitstatus):
    root = session.config.stash.get(PRIVATE_ROOT, None)
    if root and exitstatus == 0:
        shutil.rmtree(root, ignore_errors=True)
