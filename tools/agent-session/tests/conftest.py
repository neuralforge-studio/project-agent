"""Import the source package without installing it into the test interpreter."""

import sys
from pathlib import Path

SOURCE = str(Path(__file__).resolve().parents[1])
if SOURCE not in sys.path:
    sys.path.insert(0, SOURCE)
SHARED_TESTS = str(Path(__file__).resolve().parents[2] / "tests")  # tmux_test_server, shared by every tool's tests
if SHARED_TESTS not in sys.path:
    sys.path.insert(0, SHARED_TESTS)
