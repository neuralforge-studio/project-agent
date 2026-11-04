"""Shared fixtures: an isolated HOME (lock files), a registry file and item roots."""
import json
import sys
from pathlib import Path

import pytest

SOURCE = str(Path(__file__).resolve().parents[1])
if SOURCE not in sys.path:
    sys.path.insert(0, SOURCE)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def no_legacy(tmp_path, monkeypatch):
    """Point the legacy cr registry at an empty file."""
    from project_item import registry
    legacy = tmp_path / "programs.json"
    legacy.write_text(json.dumps({"sessions_dir": str(tmp_path), "programs": {}}))
    monkeypatch.setattr(registry, "LEGACY_PROGRAMS", legacy)
    return legacy


@pytest.fixture
def project(tmp_path, no_legacy):
    """A registered project 'demo' with cr/ and decide/ under its base, and a second one 'other'."""
    base = tmp_path / "demo.main"
    base.mkdir()
    other = tmp_path / "other.main"
    other.mkdir()
    config = tmp_path / "project.json"
    config.write_text(json.dumps({
        str(base): {"project": "demo", "provider": "codex", "seats": [], "path_cr": "cr", "path_decide": "decide"},
        str(other): {"project": "other", "provider": "claude", "seats": []},
    }))
    return {"base": base, "other": other, "config": config, "cr": base / "cr", "decide": base / "decide"}
