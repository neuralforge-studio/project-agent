"""The registry's public boundary delegates to its existing parser and models."""
import json

import pytest

from agent_session import config, registry


def test_registry_boundary_uses_existing_models_and_selection(tmp_path):
    base = tmp_path / "main"
    seat = tmp_path / "seat0"
    base.mkdir()
    seat.mkdir()
    path = tmp_path / "project.json"
    path.write_text(json.dumps({str(base): {"project": "demo", "provider": "codex",
                                          "seats": [str(seat)], "path_cr": "cr"}}), encoding="utf-8")
    assert registry.Project is config.Project and registry.RemoteSeat is config.RemoteSeat
    project = registry.select_project(path, "demo")
    assert project == registry.select_project(path, cwd=seat)
    assert project.path_cr == base / "cr"
    assert registry.find_project(path, "missing") is None
    with pytest.raises(registry.SessionError) as caught:
        registry.select_project(path, "missing")
    assert caught.value.code == "project_not_found"
