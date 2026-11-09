"""Acceptance tests T1~T18, T22, T23 of install-contract.md section 8.2, and the release rules of INSTALL-001.

Each case runs the installer as a user would, in an isolated HOME, and compares the HOME before and after
against the change list that the contract gives.
"""

import json
import os
import re
import subprocess
import sys

import pytest

from harness import (BLOCK, CLAUDE_LINKS, CODEX_LINKS, INSTALLER, LIB, OLD, REGISTRY_DRAFT, SHIMS, TMUX_CONF,
                     assert_changes, changes, commit_change, git, install_paths, release_name)

BACKUP = re.compile(r"^%s/backup/\d{8}T\d{6}Z-(.+)$" % re.escape(LIB))
STAMP = re.compile(r"\d{8}T\d{6}Z")


def tree(name):
    return LIB + "/releases/" + name


def installed(home, source, *args, **env):
    result = home.run("install", *args, source=source, env=env)
    assert result.returncode == 0, result.stderr
    return result


def backup_paths(after):
    return {path for path in after if BACKUP.match(path)}


def registry(home, where=".claude/project.json"):
    home.write(where, b"{}\n")


# ---------------------------------------------------------------- T1 ~ T5: install and the tmux block

def test_t1_clean_install_makes_exactly_the_paths_of_section_2(home, source, name):
    before = home.snapshot()
    installed(home, source)
    after = home.snapshot()
    assert_changes(before, after, created=install_paths(name) | {".tmux.conf"}, trees=[tree(name)])
    assert home.read(".tmux.conf") == BLOCK
    assert home.read(LIB + "/tmux.conf") == TMUX_CONF
    assert (home.path(LIB + "/current")).resolve() == home.path(tree(name)).resolve()
    record = json.loads(home.read(LIB + "/install.json"))
    expected = {tree(name), LIB + "/current", LIB + "/tmux.conf", LIB + "/install.json", *SHIMS,
                *CLAUDE_LINKS, *CODEX_LINKS}
    assert {entry["path"] for entry in record["owned"]} == {"~/" + path for path in expected}
    assert home.run("check").returncode == 0
    for tool in ("agent-session", "project-item", "project-board"):
        shim = home.path(".local/bin/" + tool)
        assert shim.is_symlink() and LIB + "/current/" in os.readlink(shim)
    assert subprocess.run([str(home.path(".local/bin/agent-session")), "--help"], capture_output=True,
                          env=home.env).returncode == 0


@pytest.mark.parametrize("original", [b"set -g mouse on\n", b"set -g mouse on", b""],
                         ids=["newline", "no-newline", "empty"])
def test_t2_existing_tmux_file_gets_the_block_and_a_backup(home, source, name, original):
    registry(home)
    home.write(".tmux.conf", original)
    before = home.snapshot()
    installed(home, source)
    after = home.snapshot()
    backups = backup_paths(after)
    assert len(backups) == 1
    assert_changes(before, after, created=install_paths(name, draft=False) | {LIB + "/backup"} | backups,
                   modified={".tmux.conf"}, trees=[tree(name)])
    assert home.read(".tmux.conf") == original + BLOCK
    assert home.read(backups.pop()) == original


def test_t3_tmux_file_under_config_is_used_only_when_the_home_file_is_absent(home, source, name):
    registry(home)
    home.write(".config/tmux/tmux.conf", b"set -g mouse on\n")
    before = home.snapshot()
    installed(home, source)
    after = home.snapshot()
    assert_changes(before, after, created=install_paths(name, draft=False) | {LIB + "/backup"} | backup_paths(after),
                   modified={".config/tmux/tmux.conf"}, trees=[tree(name)])
    assert not home.path(".tmux.conf").exists()
    assert home.read(".config/tmux/tmux.conf") == b"set -g mouse on\n" + BLOCK


def test_t3_when_both_exist_only_the_home_file_changes(home, source, name):
    registry(home)
    home.write(".tmux.conf", b"a\n")
    home.write(".config/tmux/tmux.conf", b"b\n")
    before = home.snapshot()
    installed(home, source)
    after = home.snapshot()
    assert_changes(before, after, created=install_paths(name, draft=False) | {LIB + "/backup"} | backup_paths(after),
                   modified={".tmux.conf"}, trees=[tree(name)])
    assert home.read(".config/tmux/tmux.conf") == b"b\n"


@pytest.mark.parametrize("link", [".tmux.conf", ".config/tmux/tmux.conf"])
def test_t4_a_symlinked_tmux_file_is_never_changed(home, source, name, link):
    registry(home)
    home.write("dotfiles/tmux.conf", b"set -g mouse on\n")
    home.path(link).parent.mkdir(parents=True, exist_ok=True)
    home.path(link).symlink_to(home.path("dotfiles/tmux.conf"))
    before = home.snapshot()
    result = installed(home, source)
    assert_changes(before, home.snapshot(), created=install_paths(name, draft=False), trees=[tree(name)])
    assert "source-file -q ~/.local/lib/project-agent/tmux.conf" in result.stdout
    checked = home.run("check")
    assert checked.returncode == 0 and "수동 연결 필요" in checked.stdout


def test_t5_a_block_that_the_user_made_is_neither_changed_nor_removed(home, source, name):
    registry(home)
    mine = b"set -g mouse on\n" + BLOCK
    home.write(".tmux.conf", mine)
    before = home.snapshot()
    installed(home, source)
    after = home.snapshot()
    assert_changes(before, after, created=install_paths(name, draft=False), trees=[tree(name)])
    uninstalled = home.run("uninstall")
    assert uninstalled.returncode == 0, uninstalled.stderr
    assert home.read(".tmux.conf") == mine


# ---------------------------------------------------------------- T6, T8: upgrade and rollback

def two_releases(home, source):
    installed(home, source)
    first = release_name(source)
    commit_change(source, "1.1.0")
    return first, release_name(source)


@pytest.mark.mutates
def test_t6_upgrade_changes_only_the_new_release_current_and_the_record(home, source):
    first, second = two_releases(home, source)
    before = home.snapshot()
    result = home.run("upgrade", source=source)
    assert result.returncode == 0, result.stderr
    assert_changes(before, home.snapshot(), created={tree(second)}, modified={LIB + "/current", LIB + "/install.json"},
                   trees=[tree(second)])
    assert os.readlink(home.path(LIB + "/current")) == "releases/" + second
    assert json.loads(home.read(LIB + "/install.json"))["previous"] == first
    assert home.run("check").returncode == 0


@pytest.mark.mutates
def test_t8_rollback_swaps_current_back_and_refuses_without_a_previous_release(home, source):
    installed(home, source)
    before = home.snapshot()
    refused = home.run("rollback")
    assert refused.returncode == 3 and home.snapshot() == before
    first, second = release_name(source), None
    commit_change(source, "1.1.0")
    second = release_name(source)
    assert home.run("upgrade", source=source).returncode == 0
    before = home.snapshot()
    result = home.run("rollback")
    assert result.returncode == 0, result.stderr
    assert_changes(before, home.snapshot(), modified={LIB + "/current", LIB + "/install.json"})
    record = json.loads(home.read(LIB + "/install.json"))
    assert (record["current"], record["previous"]) == (first, second)
    assert os.readlink(home.path(LIB + "/current")) == "releases/" + first


def test_t8_a_reader_never_sees_current_missing_or_dangling_while_it_is_swapped(home, source):
    """The swap is one rename. Hammer it in-process while another thread reads the link."""
    import threading
    sys.path.insert(0, str(INSTALLER.parent))
    from project_agent_install import actions
    for name in ("a", "b"):
        (home.root / name).mkdir()
        (home.root / name / "marker").write_text(name)
    link = home.root / "current"
    link.symlink_to("a")
    stop, bad = threading.Event(), []

    def watch():
        while not stop.is_set():
            try:
                (link / "marker").read_text()
            except OSError as error:
                bad.append(str(error))
    reader = threading.Thread(target=watch)
    reader.start()
    try:
        for index in range(3000):
            actions.swap_path(link, "ab"[index % 2])
    finally:
        stop.set()
        reader.join()
    assert not bad, bad[:3]


# ---------------------------------------------------------------- T9: uninstall

def uninstalled_equals_before(home, before, ignore_mtime=(), extra=()):
    """Everything that was there before is as it was, and only `extra` (the registry draft) is new."""
    after = home.snapshot()
    assert set(after) - set(before) == set(extra)
    for path, entry in before.items():
        assert path in after, path
        if path in ignore_mtime:
            assert after[path][:4] == entry[:4], path
        else:
            assert after[path] == entry, path


DRAFT = {".config", ".config/project-agent", REGISTRY_DRAFT}


def test_t9_uninstall_of_a_clean_install_leaves_only_the_registry_draft(home, source, name):
    before = home.snapshot()
    installed(home, source)
    middle = home.snapshot()
    result = home.run("uninstall")
    assert result.returncode == 0, result.stderr
    removed = install_paths(name, draft=False) | {".tmux.conf"}
    assert_changes(middle, home.snapshot(), removed=removed, trees=[tree(name)])
    uninstalled_equals_before(home, before, extra=DRAFT)
    assert "tmux unbind-key -T prefix B" in result.stdout


@pytest.mark.parametrize("original", [b"set -g mouse on\n", b"set -g mouse on", b""],
                         ids=["newline", "no-newline", "empty"])
def test_t9_uninstall_restores_the_tmux_file_byte_for_byte(home, source, original):
    registry(home)
    home.write(".tmux.conf", original)
    before = home.snapshot()
    installed(home, source)
    assert home.run("uninstall").returncode == 0
    assert home.read(".tmux.conf") == original
    uninstalled_equals_before(home, before, ignore_mtime={".tmux.conf"})


def test_t9_uninstall_with_the_tmux_file_under_config(home, source):
    registry(home)
    home.write(".config/tmux/tmux.conf", b"set -g mouse on")
    before = home.snapshot()
    installed(home, source)
    assert home.run("uninstall").returncode == 0
    assert home.read(".config/tmux/tmux.conf") == b"set -g mouse on"
    uninstalled_equals_before(home, before, ignore_mtime={".config/tmux/tmux.conf"})


def test_t9b_edits_outside_the_block_after_the_install_stay(home, source):
    registry(home)
    home.write(".tmux.conf", b"set -g mouse on\n")
    installed(home, source)
    edited = b"# mine\nset -g mouse off\n" + BLOCK + b"set -g status off\n"
    home.path(".tmux.conf").write_bytes(edited)
    assert home.run("uninstall").returncode == 0
    assert home.read(".tmux.conf") == b"# mine\nset -g mouse off\nset -g status off\n"


def test_t9_an_installer_created_tmux_file_that_the_user_extended_is_kept(home, source):
    installed(home, source)
    home.path(".tmux.conf").write_bytes(BLOCK + b"set -g mouse on\n")
    assert home.run("uninstall").returncode == 0
    assert home.read(".tmux.conf") == b"set -g mouse on\n"


# ---------------------------------------------------------------- T11: conflicts

CONFLICT_PATHS = [*SHIMS, *CLAUDE_LINKS, *CODEX_LINKS, LIB]


def make_conflict(home, relative, kind):
    path = home.path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "file":
        path.write_text("mine")
    elif kind == "directory":
        path.mkdir()
        (path / "mine").write_text("mine")
    elif kind == "other-link":
        (home.root / "elsewhere").mkdir(exist_ok=True)
        path.symlink_to(home.root / "elsewhere")
    else:      # a link to what the installer would point at, but not in any record
        tail = relative.split("current/")[-1] if "skills" in relative else None
        target = home.path(LIB + "/current/" + ("skills/" + relative.rsplit("/", 1)[1] if tail is not None else
                                                "tools/%s/bin/%s" % ((relative.rsplit("/", 1)[1],) * 2)))
        path.symlink_to(target)


@pytest.mark.parametrize("kind", ["file", "directory", "other-link", "same-target-link"])
@pytest.mark.parametrize("relative", CONFLICT_PATHS)
def test_t11_a_name_in_use_refuses_everything_and_changes_nothing(home, source, relative, kind):
    if relative == LIB and kind == "same-target-link":
        pytest.skip("the library directory has no link form")
    make_conflict(home, relative, kind)
    before = home.snapshot()
    result = home.run("install", source=source)
    assert result.returncode == 3
    assert home.snapshot() == before
    assert "~/" + relative in result.stderr


def test_t11_every_conflict_is_listed_at_once(home, source):
    for relative in (*SHIMS, *CLAUDE_LINKS, *CODEX_LINKS, LIB):
        make_conflict(home, relative, "file")
    result = home.run("install", source=source)
    assert result.returncode == 3
    for relative in (*SHIMS, *CLAUDE_LINKS, *CODEX_LINKS, LIB):
        assert "~/" + relative in result.stderr


# ---------------------------------------------------------------- T12: paths the user changed

def installed_with_user_link(home, source):
    installed(home, source)
    link = home.path(CLAUDE_LINKS[0])
    link.unlink()
    (home.root / "mine").mkdir()
    link.symlink_to(home.root / "mine")
    return link


def test_t12_check_names_the_changed_path_and_changes_nothing(home, source):
    link = installed_with_user_link(home, source)
    before = home.snapshot()
    result = home.run("check")
    assert result.returncode == 1 and "~/" + CLAUDE_LINKS[0] in result.stdout
    assert home.snapshot() == before and link.is_symlink()


@pytest.mark.mutates
def test_t12_upgrade_leaves_the_changed_path_and_names_it(home, source):
    installed_with_user_link(home, source)
    commit_change(source, "1.1.0")
    second = release_name(source)
    before = home.snapshot()
    result = home.run("upgrade", source=source)
    assert result.returncode == 0, result.stderr
    assert_changes(before, home.snapshot(), created={tree(second)}, modified={LIB + "/current", LIB + "/install.json"},
                   trees=[tree(second)])
    assert "~/" + CLAUDE_LINKS[0] in result.stdout


def test_t12_uninstall_removes_the_rest_and_names_the_changed_path(home, source, name):
    link = installed_with_user_link(home, source)
    before = home.snapshot()
    result = home.run("uninstall")
    assert result.returncode == 0, result.stderr
    removed = install_paths(name, draft=False) | {".tmux.conf"}
    removed.discard(CLAUDE_LINKS[0])
    assert_changes(before, home.snapshot(), removed=removed, trees=[tree(name)])
    assert link.is_symlink() and "~/" + CLAUDE_LINKS[0] in result.stdout


# ---------------------------------------------------------------- T13: the registry draft

@pytest.mark.parametrize("where", [None, ".codex/project.json", ".claude/project.json", REGISTRY_DRAFT])
def test_t13_the_draft_is_made_only_when_no_registry_exists(home, source, name, where):
    if where:
        home.write(where, b'{"/x": {"project": "x", "provider": "claude", "seats": []}}\n')
    before = home.snapshot()
    installed(home, source)
    after = home.snapshot()
    assert_changes(before, after, created=install_paths(name, draft=where is None) | {".tmux.conf"},
                   trees=[tree(name)])
    if where is None:
        assert home.read(REGISTRY_DRAFT) == b"{}\n"


# ---------------------------------------------------------------- T14: dry-run

def planned(output):
    """The plan of a --dry-run --json output as {created, removed, modified} sets of HOME-relative paths."""
    value = json.loads(output)
    sets = {"create": set(), "remove": set(), "replace": set(), "modify": set()}
    trees = set()
    for change in value["changes"]:
        path = STAMP.sub("<stamp>", change["path"][2:])
        sets[change["action"]].add(path)
        if change["kind"] == "tree" or (change["action"] == "remove" and "/releases/" in change["path"]):
            trees.add(path)
    return sets["create"], sets["remove"], sets["replace"] | sets["modify"], trees


def normalized(paths):
    return {STAMP.sub("<stamp>", path) for path in paths}


def dry_run_matches(home, command, source=None):
    before = home.snapshot()
    dry = home.run(*command, "--dry-run", "--json", source=source)
    assert home.snapshot() == before, "the dry run changed the HOME"
    created, removed, modified, trees = planned(dry.stdout)
    real = home.run(*command, "--json", source=source)
    assert real.returncode == dry.returncode, (dry.stderr, real.stderr)
    after = home.snapshot()
    got = changes(before, after, trees)
    assert (normalized(got[0]), normalized(got[1]), normalized(got[2])) == (created, removed, modified)
    return real


@pytest.mark.mutates
def test_t14_dry_run_changes_nothing_and_lists_what_the_real_run_changes(home, source):
    registry(home)
    home.write(".tmux.conf", b"set -g mouse on")
    dry_run_matches(home, ["install"], source)
    dry_run_matches(home, ["install"], source)                    # installed: nothing to change
    commit_change(source, "1.1.0")
    dry_run_matches(home, ["upgrade"], source)
    dry_run_matches(home, ["rollback"])
    dry_run_matches(home, ["uninstall"])


def test_t14_dry_run_on_a_clean_home_and_a_symlinked_tmux_file(home, source):
    dry_run_matches(home, ["install"], source)
    dry_run_matches(home, ["uninstall"])


def test_t14_dry_run_with_a_symlinked_tmux_file(home, source):
    home.write("dotfiles/tmux.conf", b"x\n")
    home.path(".tmux.conf").symlink_to(home.path("dotfiles/tmux.conf"))
    dry_run_matches(home, ["install"], source)
    dry_run_matches(home, ["uninstall"])


def test_t14_dry_run_of_a_refused_command_refuses_the_same_way(home, source):
    make_conflict(home, SHIMS[0], "file")
    before = home.snapshot()
    dry = home.run("install", "--dry-run", source=source)
    assert dry.returncode == 3 and home.snapshot() == before
    assert home.run("check", "--dry-run").returncode == 1            # nothing installed: check fails, changes nothing
    assert home.snapshot() == before


# ---------------------------------------------------------------- T15 ~ T17: failure, repeat, round trip

@pytest.mark.skipif(os.getuid() == 0, reason="permissions do not stop root")
def test_t15_a_failure_in_the_middle_leaves_the_home_as_it_was(home, source):
    home.path(".local/bin").mkdir(parents=True)
    home.path(".local/bin").chmod(0o555)
    try:
        before = home.snapshot()
        result = home.run("install", source=source)
        assert result.returncode == 4
        assert home.snapshot() == before
    finally:
        home.path(".local/bin").chmod(0o755)


def test_t15_a_failure_at_the_last_step_undoes_the_tmux_edit_and_the_backup(home, source):
    registry(home)
    home.write(".tmux.conf", b"set -g mouse on\n")
    before = home.snapshot()
    last = json.loads(home.run("install", "--dry-run", "--json", source=source).stdout)["changes"]
    from harness import stop_at
    result = home.run("install", source=source, env=stop_at(home, "before", len(last) - 1, "SIGTERM"))
    assert result.returncode == 4 and "undone" in result.stderr
    assert home.snapshot() == before


def test_t16_installing_again_changes_nothing(home, source):
    installed(home, source)
    before = home.snapshot()
    result = home.run("install", source=source)
    assert result.returncode == 0 and home.snapshot() == before


def test_t17_install_uninstall_install_gives_the_same_installation(home, source, name):
    installed(home, source)
    first = home.snapshot()
    assert home.run("uninstall").returncode == 0
    middle = home.snapshot()
    installed(home, source)
    second = home.snapshot()
    assert_changes(middle, second, created=install_paths(name, draft=False) | {".tmux.conf"}, trees=[tree(name)])
    assert set(first) == set(second)
    assert {path: entry[:4] for path, entry in first.items()} == {path: entry[:4] for path, entry in second.items()}


# ---------------------------------------------------------------- T18: files the installer never touches

@pytest.mark.mutates
def test_t18_the_users_own_files_are_never_changed_by_any_command(home, source):
    mine = {path: home.snapshot()[path] for path in home.USER_FILES}
    installed(home, source)
    commit_change(source, "1.1.0")
    for command in (["check"], ["upgrade"], ["rollback"], ["check"], ["uninstall"]):
        for dry in ([command[0], "--dry-run"], command):
            result = home.run(*dry, source=source)
            assert result.returncode in (0, 1, 3), result.stderr
    installed(home, source)
    assert home.run("uninstall", "--dry-run").returncode == 0
    after = home.snapshot()
    assert {path: after[path] for path in mine} == mine


# ---------------------------------------------------------------- T22: the remote runtime's skill links

def runtime_links(home, names=("project-team", "project-item")):
    """Links of the remote runtime: `skills.json` records each target (remote_runtime.py)."""
    targets = {}
    for skill in names:
        target = home.path(".cache/agent-session/runtime/%s/guidance/skills/%s" % ("a" * 64, skill))
        target.mkdir(parents=True)
        targets[skill] = str(target)
        link = home.path(".codex/skills/" + skill)
        link.symlink_to(target)
    home.write(".cache/agent-session/skills.json", json.dumps(targets).encode())
    return targets


def test_t22_a_link_of_the_remote_runtime_is_taken_over(home, source, name):
    runtime_links(home)
    registry(home)
    before = home.snapshot()
    installed(home, source)
    after = home.snapshot()
    assert_changes(before, after, created=install_paths(name, draft=False, codex=False) | {".tmux.conf"},
                   modified=set(CODEX_LINKS), trees=[tree(name)])
    for relative in CODEX_LINKS:
        assert os.readlink(home.path(relative)).endswith("/current/skills/" + relative.rsplit("/", 1)[1])
    record = json.loads(home.read(LIB + "/install.json"))
    assert {entry["path"] for entry in record["owned"] if entry.get("adopted")} == {"~/" + p for p in CODEX_LINKS}
    assert after[".cache/agent-session/skills.json"] == before[".cache/agent-session/skills.json"]


def test_t22_a_same_name_link_that_the_runtime_did_not_record_is_a_conflict(home, source):
    runtime_links(home, names=("project-team",))
    other = home.root / "elsewhere"
    other.mkdir()
    home.path(CODEX_LINKS[1]).symlink_to(other)
    before = home.snapshot()
    result = home.run("install", source=source)
    assert result.returncode == 3 and "~/" + CODEX_LINKS[1] in result.stderr
    assert home.snapshot() == before


@pytest.mark.parametrize("change", ["target", "owner-missing"])
def test_t22_a_link_that_differs_from_the_runtime_record_is_a_conflict(home, source, change):
    targets = runtime_links(home)
    if change == "target":
        link = home.path(CODEX_LINKS[0])
        link.unlink()
        link.symlink_to(home.root / "elsewhere")
    else:
        home.write(".cache/agent-session/skills.json", json.dumps({"project-team": None}).encode())
    before = home.snapshot()
    assert home.run("install", source=source).returncode == 3
    assert home.snapshot() == before and targets


# ---------------------------------------------------------------- T23: provider home variables

def test_t23_links_follow_the_provider_home_variables_and_uninstall_uses_the_recorded_paths(home, source, name):
    for sub in ("alt/claude", "alt/codex"):
        home.path(sub).mkdir(parents=True)
    registry(home)
    before = home.snapshot()
    installed(home, source, CLAUDE_CONFIG_DIR=str(home.path("alt/claude")), CODEX_HOME=str(home.path("alt/codex")))
    after = home.snapshot()
    links = {"alt/claude/skills/project-team", "alt/claude/skills/project-item",
             "alt/codex/skills/project-team", "alt/codex/skills/project-item"}
    assert_changes(before, after, created=install_paths(name, draft=False, claude=False, codex=False) | links
                   | {".tmux.conf", "alt/claude/skills", "alt/codex/skills"}, trees=[tree(name)])
    record = json.loads(home.read(LIB + "/install.json"))
    assert {entry["path"] for entry in record["owned"]} >= {"~/" + path for path in links}
    middle = home.snapshot()
    result = home.run("uninstall")
    assert result.returncode == 0, result.stderr
    assert_changes(middle, home.snapshot(), removed=install_paths(name, draft=False, claude=False, codex=False) | links
                   | {".tmux.conf", "alt/claude/skills", "alt/codex/skills"}, trees=[tree(name)])


def test_a_provider_home_that_does_not_exist_gets_no_links_and_no_directory(home, source, name):
    import shutil
    shutil.rmtree(home.path(".codex"))
    registry(home)
    before = home.snapshot()
    result = installed(home, source)
    assert_changes(before, home.snapshot(), created=install_paths(name, draft=False, codex=False) | {".tmux.conf"},
                   trees=[tree(name)])
    assert "~/.codex" in result.stdout


# ---------------------------------------------------------------- release rules

def release_files(home, name):
    base = home.path(tree(name))
    return {path.relative_to(base).as_posix() for path in base.rglob("*")
            if (path.is_file() or path.is_symlink()) and "__pycache__" not in path.parts}


def test_the_release_holds_the_product_paths_and_no_tests_or_cr(home, source, name):
    installed(home, source)
    expected = {entry for entry in git(source, "ls-files").splitlines()
                if ("/" not in entry or entry.split("/")[0] in ("tools", "skills", "docs", "integrations", "install"))
                and not entry.startswith("docs/cr/") and "/tests/" not in entry and "__pycache__" not in entry
                and not re.search(r"(^|/)(test_[^/]*\.py|conftest\.py)$", entry)}
    files = release_files(home, name)
    assert files - {"tools/python.env"} == expected
    assert {"VERSION", "tools/agent-session/bin/agent-session", "skills/project-team/SKILL.md",
            "integrations/tmux/project-agent.conf", "install/project-agent-install"} <= files


def test_the_release_is_precompiled_and_read_only(home, source, name):
    """Running the product must not add `__pycache__` to a release: it is compiled once and made read-only."""
    installed(home, source)
    root = home.path(tree(name))
    assert list(root.glob("tools/agent-session/agent_session/__pycache__/config.*.pyc"))
    writable = [path for path in [root, *root.rglob("*")] if not path.is_symlink() and path.stat().st_mode & 0o222]
    assert not writable, writable[:3]
    assert home.run("check").returncode == 0                    # entry points run from it
    assert home.run("uninstall").returncode == 0 and not root.exists()


def test_the_release_names_its_interpreter_in_python_env(home, source, name):
    installed(home, source)
    text = home.read(tree(name) + "/tools/python.env").decode()
    assert text == "PROJECT_AGENT_PYTHON=%s\nPROJECT_AGENT_PYTHONPATH=\n" % os.path.abspath(sys.executable)
    assert not home.path(".local/lib/project-agent/releases/%s/tools/python.env" % name).is_symlink()


def test_the_release_name_is_the_version_and_the_commit(home, source):
    installed(home, source)
    assert release_name(source) == "1.0.0-" + git(source, "rev-parse", "HEAD")[:12]
    assert home.path(tree(release_name(source))).is_dir()


@pytest.mark.mutates
def test_a_source_without_version_is_refused_and_nothing_changes(home, source):
    (source / "VERSION").unlink()
    git(source, "add", "-A")
    git(source, "commit", "-q", "-m", "drop VERSION")
    before = home.snapshot()
    result = home.run("install", source=source)
    assert result.returncode == 3 and "version_missing" in result.stderr
    assert home.snapshot() == before


@pytest.mark.mutates
def test_an_empty_or_malformed_version_is_refused(home, source):
    for text in ("\n", "1.0 0\n", "../x\n"):
        (source / "VERSION").write_text(text)
        git(source, "commit", "-q", "-am", "version")
        before = home.snapshot()
        result = home.run("install", source=source)
        assert result.returncode == 3 and "version_invalid" in result.stderr, text
        assert home.snapshot() == before


@pytest.mark.mutates
def test_a_working_tree_that_differs_from_the_commit_is_refused(home, source):
    """A release is named by the commit, so release files must equal it: changed or untracked product files refuse."""
    before = home.snapshot()
    notes = source / "docs/project-team/README.md"
    notes.write_text(notes.read_text() + "dirty\n")
    result = home.run("install", source=source)
    assert result.returncode == 3 and "source_dirty" in result.stderr and "docs/project-team/README.md" in result.stderr
    git(source, "checkout", "--", "docs/project-team/README.md")
    (source / "tools/new_tool.py").write_text("print()\n")
    result = home.run("install", source=source)
    assert result.returncode == 3 and "tools/new_tool.py" in result.stderr
    assert home.snapshot() == before


@pytest.mark.mutates
def test_changes_outside_the_release_files_do_not_block_the_install(home, source):
    """Tests, caches and CR files are not in the release, so changing them does not make the tree dirty."""
    (source / "docs/cr").mkdir()
    (source / "docs/cr/X-001.md").write_text("cr\n")
    (source / "tools/agent-session/tests/test_x.py").write_text("x\n")
    (source / "tools/agent-session/__pycache__").mkdir()
    (source / "tools/agent-session/__pycache__/x.pyc").write_bytes(b"\0")
    assert home.run("install", source=source).returncode == 0


def test_a_source_that_is_not_a_git_work_tree_is_refused(home, tmp_path_factory):
    plain = home.root / "plain"
    plain.mkdir()
    (plain / "VERSION").write_text("1.0.0\n")
    before = home.snapshot()
    result = home.run("install", source=plain)
    assert result.returncode == 3 and "source_not_git" in result.stderr
    assert home.snapshot() == before


def test_commands_that_need_an_installation_refuse_without_one(home):
    for command in ("rollback", "uninstall"):
        before = home.snapshot()
        result = home.run(command)
        assert result.returncode == 3 and "not_installed" in result.stderr
        assert home.snapshot() == before
    assert home.run("check").returncode == 1


@pytest.mark.mutates
def test_install_of_another_release_is_pointed_to_upgrade(home, source):
    installed(home, source)
    commit_change(source, "1.1.0")
    before = home.snapshot()
    result = home.run("install", source=source)
    assert result.returncode == 3 and "upgrade" in result.stderr and home.snapshot() == before


def test_upgrade_to_the_current_release_changes_nothing(home, source):
    installed(home, source)
    before = home.snapshot()
    result = home.run("upgrade", source=source)
    assert result.returncode == 0 and home.snapshot() == before


@pytest.mark.mutates
def test_upgrade_after_rollback_reuses_the_existing_release(home, source):
    first, second = two_releases(home, source)
    assert home.run("upgrade", source=source).returncode == 0
    assert home.run("rollback").returncode == 0
    before = home.snapshot()
    result = home.run("upgrade", source=source)
    assert result.returncode == 0, result.stderr
    assert_changes(before, home.snapshot(), modified={LIB + "/current", LIB + "/install.json"})
    assert os.readlink(home.path(LIB + "/current")) == "releases/" + second


@pytest.mark.mutates
def test_a_user_replaced_current_is_not_swapped(home, source):
    installed(home, source)
    commit_change(source, "1.1.0")
    link = home.path(LIB + "/current")
    link.unlink()
    (home.root / "mine").mkdir()
    link.symlink_to(home.root / "mine")
    before = home.snapshot()
    for command in ("upgrade", "rollback"):
        result = home.run(command, source=source)
        assert result.returncode == 3 and "current_changed" in result.stderr
    assert home.snapshot() == before


# ---------------------------------------------------------------- check

def test_check_fails_for_a_missing_owned_path_and_for_a_broken_block(home, source):
    installed(home, source)
    home.path(SHIMS[1]).unlink()
    result = home.run("check")
    assert result.returncode == 1 and "~/" + SHIMS[1] in result.stdout
    home.path(SHIMS[1]).symlink_to(os.readlink(home.path(SHIMS[0])).replace("agent-session", "project-item"))
    assert home.run("check").returncode == 0
    home.path(".tmux.conf").write_bytes(b"")
    result = home.run("check")
    assert result.returncode == 1 and "block" in result.stdout


def test_check_reports_a_missing_textual_as_a_notice_not_a_failure(home, source, tmp_path):
    installed(home, source)
    result = home.run("check", "--json")
    value = json.loads(result.stdout)
    assert result.returncode == 0 and value["ok"] is True
    wanted = (source / "tools/project-board/requirements.txt").read_text().split("==")[1].split()[0]
    code = subprocess.run([sys.executable, "-c", "import importlib.metadata as m; print(m.version('textual'))"],
                          capture_output=True, text=True, env=home.env)
    notices = [item for item in value["notes"] if "textual" in item]
    assert bool(notices) == (code.stdout.strip() != wanted)


def test_the_options_are_those_of_the_contract(home):
    result = home.run("uninstall", "--force")
    assert result.returncode == 2 and "--force" in result.stderr
    assert OLD                # the harness constant is part of the shared interface


def test_a_provider_skills_directory_that_is_a_symlink_gets_the_links_where_it_points(home, source, name):
    """Contract section 2, rule 4 (this workstation's `~/.claude/skills`): the links go into the directory it
    points to, the record and the output say `~/…`, and uninstall removes them from there."""
    import shutil
    registry(home)
    target = home.root / "shared-skills"
    shutil.move(str(home.path(".claude/skills")), str(target))
    home.path(".claude/skills").symlink_to(target)
    before = home.snapshot()
    result = installed(home, source)
    assert (target / "project-team").is_symlink() and (target / "project-item").is_symlink()
    assert str(target) in result.stdout
    after = home.snapshot()
    # The snapshot does not follow symlinks, so the links in `shared-skills` are checked above, not in the diff.
    assert_changes(before, after, created=install_paths(name, draft=False, claude=False) | {".tmux.conf"},
                   trees=[tree(name)])
    assert home.run("check").returncode == 0
    assert home.run("uninstall").returncode == 0
    assert not (target / "project-team").exists() and home.path(".claude/skills").is_symlink()
    assert (target / "other-skill" / "SKILL.md").read_bytes() == b"other skill\n"
