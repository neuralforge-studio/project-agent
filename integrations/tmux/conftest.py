"""The tmux integration tests run without `tools/conftest.py` when started alone: keep the real crontab out of reach (TEST-015)."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "tests"))
import real_crontab  # noqa: E402


def pytest_configure(config):
    real_crontab.block()
