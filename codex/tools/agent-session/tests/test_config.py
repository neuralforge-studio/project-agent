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


def test_item_paths_are_optional_and_resolved_like_seats(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    base = tmp_path / "demo.main"
    base.mkdir()
    plain = tmp_path / "plain.main"
    plain.mkdir()
    config = write_registry(tmp_path / "project.json", {
        str(base): {**entry(), "path_cr": "cr", "path_decide": "~/ops/decide"},
        str(plain): entry("plain"),
    })
    project = resolve_project(base, config)
    assert project.path_cr == base / "cr"
    assert project.path_decide == tmp_path / "home/ops/decide"
    assert not project.path_cr.exists()
    other = resolve_project(plain, config)
    assert (other.path_cr, other.path_decide) == (None, None)
    assert other == load_registry(config)[1]
    assert hash(project) != hash(other)


def test_item_paths_do_not_select_projects(tmp_path):
    base = tmp_path / "demo.main"
    base.mkdir()
    items = tmp_path / "items"
    (items / "cr").mkdir(parents=True)
    config = write_registry(tmp_path / "project.json", {str(base): {**entry(), "path_cr": str(items / "cr")}})
    with pytest.raises(SessionError) as error:
        resolve_project(items / "cr", config)
    assert error.value.code == "project_not_found"


@pytest.mark.parametrize("first, second", [
    ({"path_cr": "items"}, {"path_cr": "/x/items"}),
    ({"path_cr": "items"}, {"path_decide": "/x/items/decide"}),
    ({"path_decide": "/x/items/decide"}, {"path_cr": "/x/items"}),
])
def test_item_paths_must_not_be_equal_or_nested_across_projects(tmp_path, first, second):
    one = tmp_path / "x"
    two = tmp_path / "y"
    one.mkdir()
    two.mkdir()
    def local(paths):
        return {key: value.replace("/x", str(one)) for key, value in paths.items()}
    config = write_registry(tmp_path / "project.json", {
        str(one): {**entry("one"), **local(first)}, str(two): {**entry("two"), **local(second)}})
    with pytest.raises(SessionError) as error:
        load_registry(config)
    assert error.value.code == "registry_invalid"


@pytest.mark.parametrize("paths", [
    {"path_cr": "items", "path_decide": "items"},
    {"path_cr": "items", "path_decide": "items/open/decide"},
    {"path_cr": "", "path_decide": "decide"},
    {"path_cr": ["cr"]},
    {"path_cr": "cr", "path_report": "report"},
])
def test_invalid_item_paths_in_one_project(tmp_path, paths):
    base = tmp_path / "demo.main"
    base.mkdir()
    config = write_registry(tmp_path / "project.json", {str(base): {**entry(), **paths}})
    with pytest.raises(SessionError) as error:
        load_registry(config)
    assert error.value.code == "registry_invalid"


def test_launch_args_are_optional(tmp_path):
    base = tmp_path / "demo.main"
    base.mkdir()
    plain = tmp_path / "plain.main"
    plain.mkdir()
    config = write_registry(tmp_path / "project.json", {
        str(base): {**entry(), "launch": {"args": ["--dangerously-bypass-approvals-and-sandbox"]}},
        str(plain): entry("plain"),
    })
    project = resolve_project(base, config)
    assert project.launch_args == ("--dangerously-bypass-approvals-and-sandbox",)
    assert resolve_project(plain, config).launch_args == ()
    hash(project)


def test_role_launch_args_follow_the_common_args(tmp_path):
    base = tmp_path / "demo.main"
    base.mkdir()
    only_worker = tmp_path / "worker.main"
    only_worker.mkdir()
    config = write_registry(tmp_path / "project.json", {
        str(base): {**entry(), "launch": {"args": ["--permission-mode", "bypassPermissions"],
                                         "leader_args": ["--model", "opus"],
                                         "worker_args": ["--model", "sonnet"]}},
        str(only_worker): {**entry("worker"), "launch": {"worker_args": ["--model", "sonnet"]}},
    })
    project = resolve_project(base, config)
    assert project.args_for("leader") == ("--permission-mode", "bypassPermissions", "--model", "opus")
    assert project.args_for("worker") == ("--permission-mode", "bypassPermissions", "--model", "sonnet")
    other = resolve_project(only_worker, config)
    assert other.args_for("leader") == ()
    assert other.args_for("worker") == ("--model", "sonnet")
    hash(project)


@pytest.mark.parametrize("key, block", [
    ("launch", {"args": ["-m", "x"], "env": {"A": "1"}}),
    ("launch", {"submodules": ["lib"]}),
    ("launch", {}),
    ("launch", {"args": "--flag"}),
    ("launch", {"args": [""]}),
    ("launch", {"args": ["--cd", "/x"]}),
    ("launch", {"args": ["--session-id=abc"]}),
    ("launch", {"worker_args": "--flag"}),
    ("launch", {"worker_args": ["--settings", "x.json"]}),
    ("launch", {"leader_args": ["--resume"]}),
    ("launch", {"reviewer_args": ["--model", "x"]}),
    ("worker", {"args": []}),
    ("leader", {"args": []}),
    ("roles", {}),
])
def test_invalid_launch_declarations(tmp_path, key, block):
    base = tmp_path / "demo.main"
    base.mkdir()
    config = write_registry(tmp_path / "project.json", {str(base): {**entry(), key: block}})
    with pytest.raises(SessionError) as error:
        load_registry(config)
    assert error.value.code == "registry_invalid"
