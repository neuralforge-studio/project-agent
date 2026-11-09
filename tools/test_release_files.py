"""The version file and the format-version declaration that the installer reads (RELEASE-001)."""

import json
from pathlib import Path
import re

REPOSITORY = Path(__file__).resolve().parents[1]


def test_version_is_one_semver_line():
    text = (REPOSITORY / "VERSION").read_text(encoding="utf-8")
    assert re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\n", text)


def test_format_versions_are_declared_for_the_three_formats():
    declared = json.loads((REPOSITORY / "tools/formats.json").read_text(encoding="utf-8"))
    assert set(declared) == {"agent_session", "tmux_options", "item_files"}
    assert all(type(value) is int and value >= 1 for value in declared.values())
