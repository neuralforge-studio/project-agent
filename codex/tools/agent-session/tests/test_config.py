import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_session.config import load_registry, registry_path, resolve_project
from agent_session.errors import SessionError


def write_registry(path, entries):
    path.write_text(json.dumps(entries))
    return path


def entry(name="demo", provider="codex", seats=None):
    return {"project": name, "provider": provider, "seats": [] if seats is None else seats}


def test_select_base_and_seat_children_without_requiring_unused_seats(tmp_path):
    base = tmp_path / "demo.main"
    base.mkdir()
    child = base / "server"
    child.mkdir()
    seat = tmp_path / "demo.seat0"
    (seat / "src").mkdir(parents=True)
    config = write_registry(tmp_path / "project.json", {str(base): entry(seats=["../demo.seat0", "../missing"])})
    project = resolve_project(child, config)
    assert project.base == base
    assert project.seats == (seat, tmp_path / "missing")
    assert project.state_path == base / "agent" / "state.json"
    assert resolve_project(seat / "src", config) == project
    assert not (base / "agent").exists()


def test_deepest_path_and_component_boundaries(tmp_path):
    base = tmp_path / "project"
    nested = base / "nested"
    nested.mkdir(parents=True)
    outside = tmp_path / "project-other"
    outside.mkdir()
    config = write_registry(tmp_path / "project.json", {str(base): entry("parent"), str(nested): entry("child")})
    assert resolve_project(nested, config).project_id == "child"
    with pytest.raises(SessionError) as error:
        resolve_project(outside, config)
    assert error.value.code == "project_not_found"


def test_symlink_roots_are_not_registered_twice(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(base, target_is_directory=True)
    config = write_registry(tmp_path / "project.json", {str(base): entry("one"), str(alias): entry("two")})
    with pytest.raises(SessionError) as error:
        load_registry(config)
    assert error.value.code == "project_ambiguous"


def test_standard_paths_require_one_actual_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    for tool in (".codex", ".claude"):
        (tmp_path / tool).mkdir()
    with pytest.raises(SessionError) as error:
        registry_path()
    assert error.value.code == "registry_not_found"
    codex = write_registry(tmp_path / ".codex/project.json", {})
    claude = write_registry(tmp_path / ".claude/project.json", {})
    with pytest.raises(SessionError) as error:
        registry_path()
    assert error.value.code == "registry_ambiguous"
    claude.unlink()
    claude.symlink_to(codex)
    assert registry_path() == codex


@pytest.mark.parametrize("body", [
    [],
    {"relative/base": entry()},
    {"/base": {"project": "demo", "provider": "codex", "seats": [], "model": "extra"}},
    {"/base": entry(provider="other")},
    {"/base": entry(seats=["s"] * 11)},
    {"/base": entry(seats=[None])},
    {"/base": entry(name="")},
])
def test_invalid_registry_inputs(tmp_path, body):
    config = write_registry(tmp_path / "project.json", body)
    with pytest.raises(SessionError) as error:
        load_registry(config)
    assert error.value.exit_code == 2


def test_duplicate_json_key_is_not_silently_replaced(tmp_path):
    config = tmp_path / "project.json"
    config.write_text('{"/base":{"project":"one","project":"two","provider":"codex","seats":[]}}')
    with pytest.raises(SessionError) as error:
        load_registry(config)
    assert error.value.code == "registry_invalid"
