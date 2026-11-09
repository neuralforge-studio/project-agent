"""Give each pytest run of the tools its own temporary root.

pytest's default root (``$TMPDIR/pytest-of-<user>``) is shared by every project run by the same
user, and each run prunes the numbered directories of the others. An explicit ``--basetemp`` is
kept as given. Otherwise the run gets a short private directory directly under ``TMPDIR`` (short
so Unix socket paths stay under the ~108 byte limit), removed after a passing run.

A run that does not pass keeps its directory for debugging. The next run removes the directories
of ended runs beyond the newest five, and never one whose run is still going; ``tests/private_root.py``
owns that rule and its reasons.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
import private_root  # noqa: E402


def pytest_configure(config):
    private_root.configure(config)


def pytest_sessionfinish(session, exitstatus):
    private_root.finish(session, exitstatus)
