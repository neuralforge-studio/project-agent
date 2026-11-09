"""The three principles of install-contract.md section 2, rule 5, proved at the command line.

A. The only source of a path is the installer. A journal or record that names a path (or a temporary file) of its
   own is refused; every temporary file is found and removed by the next run.
B. Undo and removal touch a path only when it is in the state the installer made. A file the user made in the
   meantime stays.
C. The user's tmux file is, at every moment, the bytes from before or the bytes from after.

Every test here ran first against the installer before the refactoring (3462c8a) and failed there.
"""

import json
import os
import signal

import pytest

from harness import BLOCK, LIB, REGISTRY_DRAFT, commit_change, plant_at, release_name, stop_at

DRAFT = {".config", ".config/project-agent", REGISTRY_DRAFT}
ROOT_CANNOT = pytest.mark.skipif(os.getuid() == 0, reason="permissions do not stop root")
JOURNAL = ".project-agent-install-journal.json"
SKILL_TARGET = "/.local/lib/project-agent/current/skills/project-team"


def installed(home, source, **env):
    result = home.run("install", source=source, env=env)
    assert result.returncode == 0, result.stderr
    return result


def plan_index(home, source, command, path):
    """The number of the step that changes `path` (HOME-relative) in the plan of `command`."""
    value = json.loads(home.run(command, "--dry-run", "--json", source=source).stdout)
    return [change["path"] for change in value["changes"]].index("~/" + path)


def runtime_links(home):
    """Skill links of the remote runtime that the install takes over (swapped through a temporary link)."""
    targets = {}
    for skill in ("project-team", "project-item"):
        target = home.path(".cache/agent-session/runtime/%s/guidance/skills/%s" % ("a" * 64, skill))
        target.mkdir(parents=True)
        targets[skill] = str(target)
        home.path(".codex/skills/" + skill).symlink_to(target)
    home.write(".cache/agent-session/skills.json", json.dumps(targets).encode())


# ---------------------------------------------------------------- A. one source of paths

def forged(home, document):
    home.path(LIB + "/" + JOURNAL).write_text(json.dumps(document))


OLD_FORMAT = {
    "foreign-temp": lambda h, name: {"format": 1, "command": "install", "mode": "undo", "specs": [
        {"op": "rmtree", "path": str(h.path(LIB + "/releases/" + name)), "temp": str(h.path(".claude/skills/other-skill"))}]},
    "foreign-previous": lambda h, name: {"format": 1, "command": "upgrade", "mode": "undo", "specs": [
        {"op": "relink", "path": str(h.path(LIB + "/current")), "previous": str(h.path(".claude/skills")),
         "new": "releases/" + name}]},
    "foreign-drop": lambda h, name: {"format": 1, "command": "uninstall", "mode": "redo", "specs": [
        {"op": "drop_journal", "path": str(h.path(".bashrc"))}]},
}
NEW_FORMAT = {
    "id-with-dotdot": [{"op": "link", "id": "shim:../../.claude/skills/other-skill", "target": "x"}],
    "free-path-key": [{"op": "dir", "id": "lib", "path": "/etc"}],
    "unknown-op": [{"op": "shell", "id": "lib"}],
    "release-name-dotdot": [{"op": "release", "id": "release:../x", "digest": "0" * 64}],
    "foreign-skill-provider": [{"op": "link", "id": "skill:other:project-team", "target": "x"}],
}


@pytest.mark.parametrize("variant", sorted(OLD_FORMAT) + sorted(NEW_FORMAT))
def test_a_journal_that_carries_its_own_paths_is_refused_by_every_command(home, source, variant):
    installed(home, source)
    name = release_name(source)
    if variant in OLD_FORMAT:
        document = OLD_FORMAT[variant](home, name)
    else:
        document = {"format": 2, "command": "install", "mode": "undo", "homes": {}, "specs": NEW_FORMAT[variant]}
    forged(home, document)
    before = home.snapshot()
    for command in ("uninstall", "install", "upgrade", "rollback"):
        result = home.run(command, source=source)
        assert result.returncode == 3 and "journal_invalid" in result.stderr, (command, result.stderr)
        assert home.snapshot() == before, command


def test_a_record_whose_skill_link_is_not_under_a_provider_home_is_refused(home, source):
    """A link that points where ours would, in a place that is not `<provider home>/skills/<name>`, is the user's."""
    installed(home, source)
    link = home.path("Documents/skills/project-team")
    link.parent.mkdir(parents=True)
    link.symlink_to(str(home.home) + SKILL_TARGET)
    record = json.loads(home.read(LIB + "/install.json"))
    record["owned"].append({"kind": "symlink", "path": "~/Documents/skills/project-team", "provider": "claude",
                            "target": str(home.home) + SKILL_TARGET})
    home.path(LIB + "/install.json").write_text(json.dumps(record))
    before = home.snapshot()
    result = home.run("uninstall")
    assert result.returncode == 3 and "record_invalid" in result.stderr
    assert home.snapshot() == before and link.is_symlink()


def test_sigkill_right_after_each_temporary_file_of_an_install_is_undone(home, source):
    runtime_links(home)
    home.write(".tmux.conf", b"set -g mouse on")
    before = home.snapshot()
    points = 0
    for index in range(40):
        result = home.run("install", source=source, env=stop_at(home, "temp", index))
        if result.returncode == 0:
            break
        assert result.returncode == -signal.SIGKILL
        points += 1
        again = home.run("rollback")                    # the next command: it undoes the run first
        assert again.returncode == 3 and "not_installed" in again.stderr, again.stderr
        assert home.snapshot() == before, "left behind after a kill at temporary file %d" % index
    assert points >= 8, "the hook saw %d temporary files" % points
    assert home.run("check").returncode == 0


@pytest.mark.mutates
def test_sigkill_right_after_each_temporary_file_of_an_upgrade_is_undone(home, source):
    installed(home, source)
    commit_change(source, "1.1.0")
    before = home.snapshot()
    points = 0
    for index in range(20):
        result = home.run("upgrade", source=source, env=stop_at(home, "temp", index))
        if result.returncode == 0:
            break
        assert result.returncode == -signal.SIGKILL
        points += 1
        again = home.run("rollback")
        assert again.returncode == 3 and "no_previous" in again.stderr, again.stderr
        assert home.snapshot() == before, "left behind after a kill at temporary file %d" % index
    assert points >= 3, points
    assert home.run("check").returncode == 0


def test_sigkill_right_after_each_temporary_file_of_an_uninstall_is_finished_by_the_next_uninstall(home, source):
    home.write(".tmux.conf", b"set -g mouse on\n")
    points = 0
    for index in range(10):
        installed(home, source)
        with_block = home.read(".tmux.conf")
        result = home.run("uninstall", env=stop_at(home, "temp", index))
        if result.returncode == 0:
            break
        assert result.returncode == -signal.SIGKILL
        points += 1
        assert home.read(".tmux.conf") in (with_block, b"set -g mouse on\n"), "neither the bytes before nor after"
        assert home.run("uninstall").returncode == 0
        assert home.read(".tmux.conf") == b"set -g mouse on\n"
        leftovers = [path for path in home.snapshot() if path.startswith(".local") or ".pi-tmp" in path]
        assert not leftovers, leftovers
    assert points >= 1, points


# ---------------------------------------------------------------- B. only what the installer made

@pytest.mark.parametrize("planted", [REGISTRY_DRAFT, ".tmux.conf"])
def test_a_file_that_appears_after_the_plan_is_neither_overwritten_nor_removed_by_a_failed_install(home, source, planted):
    index = plan_index(home, source, "install", planted)
    before = home.snapshot()
    result = home.run("install", source=source, env=plant_at(home, "before", index, planted, "mine\n"))
    assert result.returncode == 4, result.stdout + result.stderr
    assert home.read(planted) == b"mine\n"
    after = home.snapshot()
    assert not [path for path in after if path.startswith(".local") or ".pi-tmp" in path or path == JOURNAL]
    created = set(after) - set(before)
    assert created <= DRAFT | {".tmux.conf"}, created


@pytest.mark.parametrize("planted", [REGISTRY_DRAFT, ".tmux.conf"])
def test_a_file_that_the_user_makes_after_a_kill_is_left_by_the_recovery(home, source, planted):
    index = plan_index(home, source, "install", planted)
    killed = home.run("install", source=source, env=stop_at(home, "before", index - 1))
    assert killed.returncode == -signal.SIGKILL
    home.write(planted, b"mine\n")
    recovery = home.run("rollback")
    assert recovery.returncode == 3, recovery.stderr
    assert home.read(planted) == b"mine\n"
    assert not [path for path in home.snapshot() if path.startswith(".local") or ".pi-tmp" in path or path == JOURNAL]
    assert installed(home, source).returncode == 0


# ---------------------------------------------------------------- C. the user's tmux file

def test_a_tmux_file_with_a_second_hard_link_is_not_rewritten(home, source, name):
    home.write("dotfiles/tmux.conf", b"set -g mouse on\n")
    os.link(home.path("dotfiles/tmux.conf"), home.path(".tmux.conf"))
    result = installed(home, source)
    assert home.read(".tmux.conf") == b"set -g mouse on\n" == home.read("dotfiles/tmux.conf")
    assert "source-file -q ~/.local/lib/project-agent/tmux.conf" in result.stdout
    assert os.stat(home.path(".tmux.conf")).st_nlink == 2
    checked = home.run("check")
    assert checked.returncode == 0 and "수동 연결 필요" in checked.stdout


@pytest.mark.parametrize("mode", [0o600, 0o644])
def test_the_tmux_file_keeps_its_permissions_through_install_and_uninstall(home, source, mode):
    home.write(".tmux.conf", b"set -g mouse on\n", mode=mode)
    installed(home, source)
    assert os.stat(home.path(".tmux.conf")).st_mode & 0o777 == mode
    assert home.run("uninstall").returncode == 0
    assert os.stat(home.path(".tmux.conf")).st_mode & 0o777 == mode


def test_a_user_edit_after_a_kill_during_install_is_kept_and_nothing_is_blocked(home, source):
    original = b"set -g mouse on\n"
    home.write(".tmux.conf", original)
    index = plan_index(home, source, "install", ".tmux.conf")
    killed = home.run("install", source=source, env=stop_at(home, "after", index))
    assert killed.returncode == -signal.SIGKILL
    assert home.read(".tmux.conf") == original + BLOCK
    home.path(".tmux.conf").write_bytes(original + BLOCK + b"\n")          # the user added a blank line
    recovery = home.run("rollback")
    assert recovery.returncode == 3, recovery.stderr
    assert home.read(".tmux.conf") == original + BLOCK + b"\n"             # not cut, not mistaken for the block
    assert "not_installed" in recovery.stderr
    assert installed(home, source).returncode == 0                          # and the next install is not blocked


def test_a_user_edit_after_a_kill_during_uninstall_is_kept_and_the_uninstall_goes_on(home, source):
    home.write(".tmux.conf", b"set -g mouse on\n")
    installed(home, source)
    killed = home.run("uninstall", env=stop_at(home, "before", 0))
    assert killed.returncode == -signal.SIGKILL
    edited = home.read(".tmux.conf") + b"set -g status off\n"
    home.path(".tmux.conf").write_bytes(edited)
    result = home.run("uninstall")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stderr and ".tmux.conf" in result.stdout
    assert home.read(".tmux.conf") == edited                               # the user's file was not touched
    assert not home.path(LIB).exists()


# ---------------------------------------------------------------- follow-up of the third review

@pytest.mark.parametrize("where", ["release-root", "bytecode-directory", "backup-directory"])
def test_uninstall_leaves_a_release_or_backup_directory_that_holds_the_users_files(home, source, name, where):
    """B for removal: a release goes only if it is exactly what was built; `backup/` loses only the recorded backup."""
    home.write(".tmux.conf", b"set -g mouse on\n")
    installed(home, source)
    release = home.path(LIB + "/releases/" + name)
    if where == "release-root":
        mine = release / "mine.txt"
    elif where == "bytecode-directory":
        mine = release / "tools/agent-session/agent_session/__pycache__/mine.txt"
    else:
        mine = home.path(LIB + "/backup/mine.txt")
    os.chmod(mine.parent, 0o755)                          # a release is read-only; the user makes it writable
    mine.write_text("mine")
    result = home.run("uninstall")
    assert result.returncode == 0, result.stderr
    assert mine.read_text() == "mine", "the user's file was deleted"
    assert "left as it is" in result.stdout
    assert not home.path(LIB + "/install.json").exists() and not home.path(".local/bin/agent-session").exists()
    if where == "backup-directory":
        assert sorted(os.listdir(home.path(LIB + "/backup"))) == ["mine.txt"]       # the recorded backup is gone
        assert home.path(LIB + "/releases/" + name).exists() is False
    else:
        assert home.path(LIB + "/releases/" + name).is_dir()
        assert not home.path(LIB + "/backup").exists()


@ROOT_CANNOT
def test_a_read_only_tmux_file_is_not_rewritten(home, source):
    home.write(".tmux.conf", b"set -g mouse on\n", mode=0o444)
    before = home.snapshot()
    result = installed(home, source)
    assert home.read(".tmux.conf") == b"set -g mouse on\n"
    assert os.stat(home.path(".tmux.conf")).st_mode & 0o777 == 0o444
    assert not home.path(LIB + "/backup").exists()
    assert "read-only" in result.stdout and "source-file -q ~/.local/lib/project-agent/tmux.conf" in result.stdout
    assert home.snapshot()[".tmux.conf"] == before[".tmux.conf"]
    checked = home.run("check")
    assert checked.returncode == 0 and "수동 연결 필요" in checked.stdout


def test_a_tmux_file_with_extended_attributes_is_not_rewritten(home, source):
    path = home.write(".tmux.conf", b"set -g mouse on\n")
    try:
        os.setxattr(path, "user.note", b"mine")
    except OSError:
        pytest.skip("this file system has no user extended attributes")
    result = installed(home, source)
    assert home.read(".tmux.conf") == b"set -g mouse on\n" and os.getxattr(path, "user.note") == b"mine"
    assert "extended attributes" in result.stdout


@pytest.mark.parametrize("mode", [0o600, 0o640, 0o644])
def test_the_backup_has_the_mode_of_the_original(home, source, mode):
    home.write(".tmux.conf", b"set -g mouse on\n", mode=mode)
    installed(home, source)
    backups = [name for name in os.listdir(home.path(LIB + "/backup"))]
    assert len(backups) == 1
    assert os.stat(home.path(LIB + "/backup/" + backups[0])).st_mode & 0o777 == mode


def test_a_corrupt_base64_value_in_a_journal_is_refused_without_a_traceback(home, source):
    installed(home, source)
    bad = {"format": 2, "command": "install", "mode": "undo", "homes": {}, "specs": [
        {"op": "record", "previous": "!!not base64!!", "before_sha": None, "after_sha": "0" * 64, "mtime_ns": None}]}
    worse = {"format": 2, "command": "install", "mode": "undo", "homes": {}, "specs": [
        {"op": "tmux", "id": "tmux:0", "before_bytes": "@@@", "before_sha": "0" * 64, "after_sha": "1" * 64,
         "mtime_ns": None}]}
    for document in (bad, worse):
        forged(home, document)
        before = home.snapshot()
        for command in ("uninstall", "install", "rollback"):
            result = home.run(command, source=source)
            assert result.returncode == 3 and "journal_invalid" in result.stderr, (command, result.stderr)
            assert "Traceback" not in result.stderr
            assert home.snapshot() == before
        home.path(LIB + "/" + JOURNAL).unlink()
