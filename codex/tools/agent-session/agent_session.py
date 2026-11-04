#!/usr/bin/env python3
"""Run the source package without relying on an inherited PYTHONPATH."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_session.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
