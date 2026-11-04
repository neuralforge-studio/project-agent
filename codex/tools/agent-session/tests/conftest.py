"""Import the source package without installing it into the test interpreter."""

import sys
from pathlib import Path

SOURCE = str(Path(__file__).resolve().parents[1])
if SOURCE not in sys.path:
    sys.path.insert(0, SOURCE)
