"""The remote runtime links the product skills only on a host without an installed release."""

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_session import remote_runtime

NAMES = ("project-team", "project-item")


@pytest.fixture
def host(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    source = tmp_path / "run/source"
    for name in NAMES:
        (source / "guidance/codex/skills" / name).mkdir(parents=True)
    return home, source


def test_host_without_installed_release_gets_runtime_links(host):
    home, source = host
    remote_runtime._install_skills(source)
    for name in NAMES:
        link = home / ".codex/skills" / name
        assert link.is_symlink() and link.resolve() == (source / "guidance/codex/skills" / name).resolve()
    owned = json.loads((home / ".cache/agent-session/skills.json").read_text())
    assert set(owned) == set(NAMES)


def test_installed_release_keeps_every_skill_path_untouched(host):
    home, source = host
    record = home / ".local/lib/project-agent/install.json"
    record.parent.mkdir(parents=True)
    record.write_text("{}")
    installed = home / "release/skills/project-team"
    installed.mkdir(parents=True)
    link = home / ".codex/skills/project-team"
    link.parent.mkdir(parents=True)
    link.symlink_to(installed)
    before = sorted(str(path.relative_to(home)) for path in home.rglob("*"))
    remote_runtime._install_skills(source)
    assert sorted(str(path.relative_to(home)) for path in home.rglob("*")) == before
    assert link.resolve() == installed.resolve()
    assert not (home / ".codex/skills/project-item").exists()
    assert not (home / ".cache").exists()


def test_installed_release_does_not_repair_a_runtime_link(host):
    home, source = host
    remote_runtime._install_skills(source)
    link = home / ".codex/skills/project-item"
    old_target = link.readlink()
    newer = source.parent / "newer"
    for name in NAMES:
        (newer / "guidance/codex/skills" / name).mkdir(parents=True)
    record = home / ".local/lib/project-agent/install.json"
    record.parent.mkdir(parents=True)
    record.write_text("{}")
    skills_json = home / ".cache/agent-session/skills.json"
    recorded = skills_json.read_text()
    remote_runtime._install_skills(newer)
    assert link.readlink() == old_target
    assert skills_json.read_text() == recorded
