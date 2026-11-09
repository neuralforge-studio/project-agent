"""Acceptance tests T24~T29 of install-contract.md section 8.2: `install --adopt-dev-links` (INSTALL-005).

The HOME is this workstation's shape: the shims and the Codex skill links are absolute links into an old
development checkout, `~/.claude/skills` is a symlink into that checkout, and the Claude skill links in it are
relative. The checkout is outside HOME, so every case snapshots both.
"""

import json
import os
import shutil
import threading

import pytest

from harness import (CLAUDE_LINKS, CODEX_LINKS, INSTALLER, LIB, SHIMS, assert_changes, install_paths, snapshot)

LINKS = (*SHIMS, *CLAUDE_LINKS, *CODEX_LINKS)
OLD_RELATIVE = {path: "../../codex/skills/" + path.rsplit("/", 1)[1] for path in CLAUDE_LINKS}
TOOLS = ("agent-session", "project-item", "project-board")
SKILLS = ("project-team", "project-item")


def tree(name):
    return LIB + "/releases/" + name


def make_checkout(root, name):
    """A development checkout: `codex/tools/<tool>/bin/<tool>` and `codex/skills/<name>` (the known shape)."""
    checkout = root / name
    for tool in TOOLS:
        entry = checkout / "codex/tools" / tool / "bin" / tool
        entry.parent.mkdir(parents=True)
        entry.write_text("#!/bin/sh\n")
    for skill in SKILLS:
        (checkout / "codex/skills" / skill).mkdir(parents=True)
        (checkout / "codex/skills" / skill / "SKILL.md").write_text(skill)
    return checkout


class Workstation:
    def __init__(self, home):
        self.home = home
        self.dev = make_checkout(home.root, "dev")
        home.write(".claude/project.json", b"{}\n")                 # a registry exists: no draft is made
        bin_dir = home.path(".local/bin")
        bin_dir.mkdir(parents=True)
        for tool in TOOLS:
            (bin_dir / tool).symlink_to(self.dev / "codex/tools" / tool / "bin" / tool)
        (self.dev / "claude").mkdir()
        shutil.move(str(home.path(".claude/skills")), str(self.dev / "claude/skills"))
        home.path(".claude/skills").symlink_to(self.dev / "claude/skills")
        for skill in SKILLS:
            (self.dev / "claude/skills" / skill).symlink_to("../../codex/skills/" + skill)
            home.path(".codex/skills/" + skill).symlink_to(self.dev / "codex/skills" / skill)

    def snapshot(self):
        return self.home.snapshot(), snapshot(self.dev)

    def adopt(self, source, *args, checkout=None, env=None):
        return self.home.run("install", "--adopt-dev-links", str(checkout or self.dev), *args, source=source, env=env)


@pytest.fixture
def station(home):
    return Workstation(home)


def real_link(station, relative):
    """The place of a link as the file system has it (`~/.claude/skills` leads into the checkout)."""
    return station.home.path(relative).parent.resolve() / relative.rsplit("/", 1)[1]


# ---------------------------------------------------------------- T24: without the option

def test_t24_without_the_option_old_links_refuse_everything_and_change_nothing(station, source):
    before = station.snapshot()
    result = station.home.run("install", source=source)
    assert result.returncode == 3
    assert station.snapshot() == before
    for relative in (*SHIMS, *CLAUDE_LINKS, *CODEX_LINKS):
        assert "~/" + relative in result.stderr


# ---------------------------------------------------------------- T25: with the option

def test_t25_only_links_of_the_known_shape_are_taken_over_and_the_record_keeps_the_old_targets(station, source, name):
    home, dev = station.home, station.dev
    before_home, before_dev = station.snapshot()
    result = station.adopt(source)
    assert result.returncode == 0, result.stderr
    after_home, after_dev = station.snapshot()
    assert_changes(before_home, after_home,
                   created=install_paths(name, draft=False, claude=False, codex=False, bin_dir=False,
                                         home_dirs=(".local/lib",)) | {".tmux.conf"},
                   modified={*SHIMS, *CODEX_LINKS}, trees=[tree(name)])
    assert_changes(before_dev, after_dev, modified={"claude/skills/project-team", "claude/skills/project-item"})
    for relative in LINKS:
        link = real_link(station, relative)
        tail = "tools/%s/bin/%s" % ((relative.rsplit("/", 1)[1],) * 2) if relative in SHIMS else (
            "skills/" + relative.rsplit("/", 1)[1])
        assert os.readlink(link) == str(home.path(LIB + "/current/" + tail))
    record = json.loads(home.read(LIB + "/install.json"))
    adopted = {entry["path"]: entry["adopted_from"] for entry in record["owned"] if "adopted_from" in entry}
    assert adopted == {
        **{"~/" + path: str(dev / "codex/tools" / path.rsplit("/", 1)[1] / "bin" / path.rsplit("/", 1)[1])
           for path in SHIMS},
        **{"~/" + path: OLD_RELATIVE[path] for path in CLAUDE_LINKS},      # the relative text, byte for byte
        **{"~/" + path: str(dev / "codex/skills" / path.rsplit("/", 1)[1]) for path in CODEX_LINKS}}
    assert str(dev / "claude/skills") in result.stdout          # the real place of the Claude links is named
    assert "~/.local/bin/agent-session" in result.stdout
    assert home.run("check").returncode == 0


def test_t25_uninstall_points_the_links_back_at_their_old_targets(station, source):
    before = station.snapshot()
    assert station.adopt(source).returncode == 0
    result = station.home.run("uninstall")
    assert result.returncode == 0, result.stderr
    assert station.snapshot() == before                           # links, relative text included, as they were
    assert OLD_RELATIVE[CLAUDE_LINKS[0]] == os.readlink(station.dev / "claude/skills/project-team")


def test_t25_uninstall_leaves_a_taken_over_link_that_the_user_changed_since(station, source):
    assert station.adopt(source).returncode == 0
    link = station.home.path(SHIMS[0])
    link.unlink()
    link.symlink_to(station.home.root / "mine")
    result = station.home.run("uninstall")
    assert result.returncode == 0, result.stderr
    assert os.readlink(link) == str(station.home.root / "mine") and "~/" + SHIMS[0] in result.stdout
    for relative in (*SHIMS[1:], *CLAUDE_LINKS, *CODEX_LINKS):         # the others are back where they were
        assert os.readlink(real_link(station, relative)) in (OLD_RELATIVE.get(relative), str(
            station.dev / ("codex/tools/%s/bin/%s" % ((relative.rsplit("/", 1)[1],) * 2) if relative in SHIMS else
                           "codex/skills/" + relative.rsplit("/", 1)[1]))), relative


def test_t25_a_record_whose_old_target_is_not_of_the_known_shape_is_refused(station, source):
    assert station.adopt(source).returncode == 0
    record = station.home.path(LIB + "/install.json")
    value = json.loads(record.read_text())
    next(entry for entry in value["owned"] if "adopted_from" in entry)["adopted_from"] = "/etc/passwd"
    record.write_text(json.dumps(value))
    before = station.snapshot()
    result = station.home.run("uninstall")
    assert result.returncode == 3 and "record_invalid" in result.stderr
    assert station.snapshot() == before


def test_t25_the_option_changes_nothing_when_no_old_link_exists(home, source, name):
    home.write(".claude/project.json", b"{}\n")
    result = home.run("install", "--adopt-dev-links", str(home.root / "dev"), source=source)
    assert result.returncode == 0, result.stderr
    assert "adopted_from" not in home.read(LIB + "/install.json").decode()


def test_t25_dry_run_lists_the_swaps_and_changes_nothing(station, source):
    before = station.snapshot()
    dry = station.adopt(source, "--dry-run", "--json")
    assert dry.returncode == 0, dry.stderr
    assert station.snapshot() == before
    replaced = {change["path"] for change in json.loads(dry.stdout)["changes"] if change["action"] == "replace"}
    assert replaced == {"~/" + path for path in LINKS}
    real = station.adopt(source, "--json")
    assert {change["path"] for change in json.loads(real.stdout)["changes"]} == {
        change["path"] for change in json.loads(dry.stdout)["changes"]}


# ---------------------------------------------------------------- T26: what is refused

def retarget(path, target):
    path.unlink()
    path.symlink_to(target)


def break_unknown_shape(station, relative):
    other = station.dev / "elsewhere"
    other.mkdir()
    retarget(real_link(station, relative), other)


def break_other_checkout(station, relative):
    other = make_checkout(station.home.root, "dev2")
    name = relative.rsplit("/", 1)[1]
    retarget(real_link(station, relative),
             other / ("codex/tools/%s/bin/%s" % (name, name) if relative in SHIMS else "codex/skills/" + name))


def break_relative_elsewhere(station, relative):
    (station.dev / "claude/codex2/skills/project-item").mkdir(parents=True)
    retarget(real_link(station, relative), "../codex2/skills/project-item")


def break_file(station, relative):
    path = real_link(station, relative)
    path.unlink()
    path.write_text("mine")


def break_directory(station, relative):
    path = real_link(station, relative)
    path.unlink()
    path.mkdir()


@pytest.mark.parametrize("breaker", [break_unknown_shape, break_other_checkout, break_file, break_directory])
@pytest.mark.parametrize("relative", [SHIMS[1], CLAUDE_LINKS[0], CODEX_LINKS[1]])
def test_t26_one_link_that_is_not_the_known_shape_refuses_the_whole_install(station, source, relative, breaker):
    breaker(station, relative)
    before = station.snapshot()
    result = station.adopt(source)
    assert result.returncode == 3
    assert station.snapshot() == before                           # the good links were not taken over either
    assert "~/" + relative in result.stderr


def test_t26_a_relative_link_to_another_place_in_a_symlinked_skills_directory_is_refused(station, source):
    break_relative_elsewhere(station, CLAUDE_LINKS[1])
    before = station.snapshot()
    result = station.adopt(source)
    assert result.returncode == 3 and "~/" + CLAUDE_LINKS[1] in result.stderr
    assert station.snapshot() == before


def test_t26_links_into_another_checkout_than_the_one_named_are_refused(station, source):
    other = make_checkout(station.home.root, "dev2")
    before = station.snapshot()
    result = station.adopt(source, checkout=other)
    assert result.returncode == 3
    assert station.snapshot() == before
    for relative in LINKS:
        assert "~/" + relative in result.stderr


def test_t26_a_link_that_another_user_owns_is_refused(station, source):
    hook = station.home.root / "uid-hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text("import os\nreal = os.getuid()\nos.getuid = lambda: real + 1\n")
    before = station.snapshot()
    result = station.adopt(source, env={"PYTHONPATH": str(hook)})
    assert result.returncode == 3
    assert station.snapshot() == before
    for relative in LINKS:
        assert "~/" + relative in result.stderr


# ---------------------------------------------------------------- T27: a symlinked skills directory

def test_t27_the_claude_links_inside_a_symlinked_skills_directory_are_taken_over_and_restored(station, source):
    skills = station.home.path(".claude/skills")
    assert skills.is_symlink()
    before = station.snapshot()
    result = station.adopt(source)
    assert result.returncode == 0, result.stderr
    assert skills.is_symlink() and (station.dev / "claude/skills/other-skill/SKILL.md").read_bytes() == b"other skill\n"
    for skill in SKILLS:
        assert (station.dev / "claude/skills" / skill).is_symlink()
        assert os.readlink(station.dev / "claude/skills" / skill).endswith("/current/skills/" + skill)
    assert station.home.run("uninstall").returncode == 0
    assert station.snapshot() == before


# ---------------------------------------------------------------- T28: nobody sees a missing or dangling entry point

def watch(paths, stop, bad, count):
    while not stop.is_set():
        for path in paths:
            try:
                os.stat(path)
            except OSError as error:
                bad.append("%s: %s" % (path, error))
        count[0] += 1


def test_t28_no_observer_sees_an_entry_point_missing_or_dangling_during_the_takeover_and_the_restore(station, source):
    paths = [station.home.path(relative) for relative in LINKS]
    stop, bad, count = threading.Event(), [], [0]
    reader = threading.Thread(target=watch, args=(paths, stop, bad, count))
    reader.start()
    try:
        assert station.adopt(source).returncode == 0
        assert station.home.run("uninstall").returncode == 0
    finally:
        stop.set()
        reader.join()
    assert count[0] > 10 and not bad, bad[:3]


# ---------------------------------------------------------------- T29: a link the user changes after the plan

REPLACE_HOOK = '''\
import os, sys
spec = os.environ.get("INSTALLER_REPLACE")
if spec:
    sys.path.insert(0, os.environ["INSTALLER_DIR"])
    from project_agent_install import actions
    index, link, target = spec.split("|")

    def checkpoint(where, number):
        if where == "before" and number == int(index):      # the user swaps the link just before the installer does
            os.unlink(link)
            os.symlink(target, link)
    actions.checkpoint = checkpoint
'''


@pytest.mark.parametrize("relative", [SHIMS[0], CLAUDE_LINKS[1], CODEX_LINKS[0]])
def test_t29_a_link_the_user_changes_after_the_plan_is_not_overwritten_and_the_run_is_undone(station, source, relative):
    home = station.home
    plan = json.loads(station.adopt(source, "--dry-run", "--json").stdout)["changes"]
    index = next(number for number, change in enumerate(plan) if change["path"] == "~/" + relative)
    hook = home.root / "replace-hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(REPLACE_HOOK)
    mine = home.root / "mine"
    mine.mkdir()
    link = real_link(station, relative)
    before = station.snapshot()
    result = station.adopt(source, env={"PYTHONPATH": str(hook), "INSTALLER_DIR": str(INSTALLER.parent),
                                        "INSTALLER_REPLACE": "%d|%s|%s" % (index, link, mine)})
    assert result.returncode == 4, result.stdout + result.stderr
    assert os.readlink(link) == str(mine)                         # the user's link is still the user's
    after_home, after_dev = station.snapshot()
    home_name, dev_name = (relative, None) if link.is_relative_to(home.home) else (None, "claude/skills/" + relative.rsplit("/", 1)[1])
    for snap, was, name in ((after_home, before[0], home_name), (after_dev, before[1], dev_name)):
        changed = {path for path in set(snap) | set(was) if snap.get(path) != was.get(path)}
        assert changed == ({name} if name else set()), changed    # everything else was undone
