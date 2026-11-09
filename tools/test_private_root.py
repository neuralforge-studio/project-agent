"""The tools' tests must not share pytest's per-user temporary root with other projects."""

import getpass
from pathlib import Path
import tempfile


def test_temporary_directories_are_outside_the_shared_user_root(tmp_path, request):
    root = request.config.option.basetemp
    assert root is not None
    assert Path(root).resolve() in tmp_path.resolve().parents
    shared = Path(tempfile.gettempdir()).resolve() / f"pytest-of-{getpass.getuser()}"
    assert shared not in tmp_path.resolve().parents
