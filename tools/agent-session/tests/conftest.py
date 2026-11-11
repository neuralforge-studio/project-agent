"""Import the source package without installing it into the test interpreter."""

import sys
from pathlib import Path

SOURCE = str(Path(__file__).resolve().parents[1])
if SOURCE not in sys.path:
    sys.path.insert(0, SOURCE)
SHARED_TESTS = str(Path(__file__).resolve().parents[2] / "tests")  # tmux_test_server, shared by every tool's tests
if SHARED_TESTS not in sys.path:
    sys.path.insert(0, SHARED_TESTS)


import pytest  # noqa: E402
import fake_crontab  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_crontab(tmp_path_factory, monkeypatch):
    """No test reaches the user's crontab: `crontab` is a shim over a file of the test (tests/fake_crontab.py)."""
    directory = tmp_path_factory.mktemp("crontab")
    for name, value in fake_crontab.install(directory / "bin", directory / "crontab.txt").items():
        monkeypatch.setenv(name, value)
