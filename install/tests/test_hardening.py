"""The installer runs in other people's HOME, so two things are proved here (Leader review of INSTALL-001):

* what the installer did not make is never changed or removed, whatever the install record or the journal says
  and however a write fails;
* wherever a run is cut off (a failure, SIGINT/SIGTERM/SIGHUP, SIGKILL), the next command leaves the HOME in a
  defined state: the one before the run, or (uninstall) the finished removal.

Each test was first run against the installer as it was before the fix (`PROJECT_AGENT_INSTALLER`) to see it fail.
"""

import json
import os
import signal
import sys
from pathlib import Path

import pytest

from harness import BLOCK, INSTALLER, LIB, REGISTRY_DRAFT, commit_change, release_name, stop_at

sys.path.insert(0, str(INSTALLER.parent))
from project_agent_install import actions, commands  # noqa: E402
from project_agent_install.layout import Env, InstallerError  # noqa: E402
try:
    from project_agent_install import journal  # noqa: E402
except ImportError:                       # an installer from before the journal (to show the tests fail on it)
    journal = None

DRAFT = {".config", ".config/project-agent", REGISTRY_DRAFT}
ROOT_CANNOT = pytest.mark.skipif(os.getuid() == 0, reason="permissions do not stop root")


def tree(name):
    return LIB + "/releases/" + name


def installed(home, source, **env):
    result = home.run("install", source=source, env=env)
    assert result.returncode == 0, result.stderr
    return result


# ---------------------------------------------------------------- 1. the install record is not trusted blindly

def record_of(home):
    return json.loads(home.read(LIB + "/install.json"))


def tamper(home, change):
    record = record_of(home)
    change(record, str(home.home))
    home.path(LIB + "/install.json").write_text(json.dumps(record))


def owned(record, path):
    return next(entry for entry in record["owned"] if entry["path"].endswith(path))


MUTATIONS = {
    "directory-of-the-user": lambda r, h: owned(r, "/releases/" + r["current"]).update(path="~/.claude/skills/other-skill"),
    "dotdot-out-of-releases": lambda r, h: owned(r, "/releases/" + r["current"]).update(
        path="~/.local/lib/project-agent/releases/../../../../.claude/skills/other-skill"),
    "file-of-the-user": lambda r, h: owned(r, "/tmux.conf").update(path="~/.bashrc"),
    "symlink-place-of-the-user": lambda r, h: owned(r, "/bin/agent-session").update(path="~/.bashrc"),
    "symlink-target": lambda r, h: owned(r, "/bin/agent-session").update(target="/etc/passwd"),
    "created-dir-user-directory": lambda r, h: r["created_dirs"].append("~/.claude"),
    "created-dir-home": lambda r, h: r["created_dirs"].append(h),
    "tmux-file-not-a-candidate": lambda r, h: r["tmux"].update(file="~/.bashrc"),
    "tmux-backup-outside": lambda r, h: r["tmux"].update(backup="~/.bashrc"),
    "release-name": lambda r, h: r.update(current="../../.claude", releases=["../../.claude"]),
}


@pytest.mark.parametrize("mutation", sorted(MUTATIONS))
def test_a_record_that_names_what_the_installer_does_not_make_is_refused_by_every_command(home, source, mutation):
    home.write(".tmux.conf", b"set -g mouse on\n")
    installed(home, source)
    tamper(home, MUTATIONS[mutation])
    before = home.snapshot()
    for command in ("uninstall", "upgrade", "rollback", "check", "install"):
        result = home.run(command, source=source)
        assert result.returncode in (1, 3), (command, result.stdout, result.stderr)
        assert home.snapshot() == before, command
    assert "record_invalid" in home.run("uninstall").stderr


# ---------------------------------------------------------------- 2. removing the tmux block

def inject(monkeypatch, name, limit=2, fail_on=None):
    """Replace actions.<name> (raw_write or raw_pwrite) by a version that writes at most `limit` bytes per call
    and raises OSError on call number `fail_on`."""
    real, calls = getattr(actions, name), []

    def fake(fd, data, *offset):
        calls.append(1)
        if fail_on is not None and len(calls) == fail_on:
            raise OSError(5, "injected write failure")
        return real(fd, bytes(data[:limit]), *offset)
    monkeypatch.setattr(actions, name, fake)
    return calls


def tmux_file(home, content, mtime=1_600_000_000_000_000_000):
    path = home.write(".tmux.conf", content)
    os.utime(path, ns=(mtime, mtime))
    return path


MIDDLE = b"set -g mouse on\n" + BLOCK + b"set -g status off\n"
AT_END = b"set -g mouse on\n" + BLOCK


def cut(path, original, created=False):
    return actions.remove_block(path, BLOCK, created, original)


def test_removing_a_block_in_the_middle_survives_short_writes(home, monkeypatch):
    path = tmux_file(home, MIDDLE)
    calls = inject(monkeypatch, "raw_pwrite", limit=2)
    cut(path, MIDDLE).do()
    assert path.read_bytes() == b"set -g mouse on\nset -g status off\n" and len(calls) > 1


def test_a_write_failure_while_removing_restores_the_file_byte_for_byte(home, monkeypatch):
    path = tmux_file(home, MIDDLE)
    before = os.stat(path)
    inject(monkeypatch, "raw_pwrite", limit=3, fail_on=2)
    with pytest.raises(OSError):
        cut(path, MIDDLE).do()
    assert path.read_bytes() == MIDDLE and os.stat(path).st_mtime_ns == before.st_mtime_ns


def test_a_block_at_the_end_is_cut_by_one_truncate_and_a_failure_changes_nothing(home, monkeypatch):
    path = tmux_file(home, AT_END)
    writes = inject(monkeypatch, "raw_pwrite")
    cut(path, AT_END).do()
    assert path.read_bytes() == b"set -g mouse on\n" and not writes          # no byte was rewritten
    path = tmux_file(home, AT_END)
    monkeypatch.setattr(actions, "raw_ftruncate", lambda fd, size: (_ for _ in ()).throw(OSError(5, "injected")))
    with pytest.raises(OSError):
        cut(path, AT_END).do()
    assert path.read_bytes() == AT_END


def test_a_file_that_changed_after_the_plan_is_not_touched(home):
    path = tmux_file(home, MIDDLE)
    step = cut(path, MIDDLE)
    changed = MIDDLE + b"# added after the plan\n"
    path.write_bytes(changed)
    with pytest.raises(actions.Changed):
        step.do()
    assert path.read_bytes() == changed


def test_uninstall_refused_by_a_changed_tmux_file_changes_nothing(home, source, monkeypatch):
    """The plan reads the file, the run re-reads it: a change in between (here: made by the plan's own caller)
    stops the run before the first removal."""
    installed(home, source)
    before = home.snapshot()
    monkeypatch.setenv("HOME", str(home.home))
    env = Env()
    monkeypatch.setattr(commands.runs, "run_slots", lambda *args, **kwargs: [])
    plan = commands.plan_uninstall(env, Path("."))
    home.path(".tmux.conf").write_bytes(BLOCK + b"set -g mouse on\n")
    with pytest.raises(InstallerError) as error:
        journal.execute(env, plan)
    assert error.value.code == "changed_since_plan"
    after = home.snapshot()
    assert {path: entry for path, entry in after.items() if path != ".tmux.conf"} == {
        path: entry for path, entry in before.items() if path != ".tmux.conf"}
    assert journal.find(env) is None


# ---------------------------------------------------------------- 3. appending the block and its backup

def append_plan(home, original):
    env = Env()
    path = home.path(".tmux.conf")
    home.path(LIB + "/backup").mkdir(parents=True, exist_ok=True)
    backup = home.path(LIB + "/backup/20261109T000000Z-.tmux.conf")
    steps = [actions.backup_file(backup, path, original),
             actions.append_block(path, BLOCK, original, os.lstat(path))]
    return env, commands.Plan("install", steps, journal_path=home.path(".pi-journal")), backup


@pytest.mark.parametrize("original", [b"set -g mouse on\n", b"set -g mouse on", b""])
def test_append_survives_short_writes_and_the_backup_is_the_original(home, monkeypatch, original):
    monkeypatch.setenv("HOME", str(home.home))
    path = tmux_file(home, original)
    env, plan, backup = append_plan(home, original)
    inject(monkeypatch, "raw_write", limit=3)
    journal.execute(env, plan)
    assert path.read_bytes() == original + BLOCK and backup.read_bytes() == original


@pytest.mark.parametrize("original", [b"set -g mouse on\n", b"set -g mouse on", b""])
def test_a_failed_append_restores_the_file_and_removes_the_backup(home, monkeypatch, original):
    monkeypatch.setenv("HOME", str(home.home))
    path = tmux_file(home, original)
    before = os.stat(path)
    env, plan, backup = append_plan(home, original)
    inject(monkeypatch, "raw_write", limit=3, fail_on=2)
    with pytest.raises(InstallerError):
        journal.execute(env, plan)
    assert path.read_bytes() == original and os.stat(path).st_mtime_ns == before.st_mtime_ns
    assert not backup.exists()


def test_a_file_that_changed_after_the_plan_gets_neither_a_backup_nor_the_block(home, monkeypatch):
    monkeypatch.setenv("HOME", str(home.home))
    path = tmux_file(home, b"set -g mouse on\n")
    env, plan, backup = append_plan(home, b"set -g mouse on\n")
    path.write_bytes(b"set -g mouse off\n")
    with pytest.raises(InstallerError):
        journal.execute(env, plan)
    assert path.read_bytes() == b"set -g mouse off\n" and not backup.exists()


# ---------------------------------------------------------------- 4. removal errors are errors

@ROOT_CANNOT
@pytest.mark.parametrize("locked", [".local/bin", LIB + "/releases"])
def test_a_removal_that_fails_is_reported_keeps_the_record_and_a_second_run_finishes(home, source, locked):
    name = release_name(source)
    before = home.snapshot()
    installed(home, source)
    home.path(locked).chmod(0o555)
    try:
        result = home.run("uninstall")
        assert result.returncode == 4, result.stdout
        assert "Nothing was undone" in result.stderr and "changes made so far were undone" not in result.stderr
        assert home.path(LIB + "/install.json").exists()
    finally:
        home.path(locked).chmod(0o755)
    result = home.run("uninstall")
    assert result.returncode == 0, result.stderr
    after = home.snapshot()
    assert set(after) - set(before) == DRAFT and set(before) <= set(after)
    assert not home.path(tree(name)).exists()


def test_a_symlink_is_never_removed_as_a_tree(home):
    target = home.root / "precious"
    target.mkdir()
    (target / "file").write_text("mine")
    link = home.root / "link"
    link.symlink_to(target)
    with pytest.raises(OSError):
        actions.force_rmtree(link)
    assert (target / "file").read_text() == "mine" and link.is_symlink()


# ---------------------------------------------------------------- 5. interruption

def step_count(home, *command, source=None):
    result = home.run(*command, "--dry-run", "--json", source=source)
    return len(json.loads(result.stdout)["changes"])


def same_installation(first, second):
    """Equal entries (the user's files keep their times; made files may differ in mtime)."""
    assert set(first) == set(second)
    assert {path: entry[:4] for path, entry in first.items()} == {path: entry[:4] for path, entry in second.items()}


INSTALL_POINTS = [("before", 0), ("after", 0), ("after", 1), ("after", 2), ("after", 3), ("after", 5), ("after", 8),
                  ("after", 11), ("after", 14), ("after", 17), ("after", 20), ("after", 24), ("after", -1)]


@pytest.mark.parametrize("point", INSTALL_POINTS, ids=lambda point: "%s-%d" % point)
def test_sigkill_during_install_is_undone_by_the_next_command_and_install_then_succeeds(home, source, point):
    home.write(".tmux.conf", b"set -g mouse on")
    before = home.snapshot()
    count = step_count(home, "install", source=source)
    position, index = point
    index = count - 1 if index < 0 else min(index, count - 1)
    killed = home.run("install", source=source, env=stop_at(home, position, index))
    assert killed.returncode == -signal.SIGKILL
    again = home.run("rollback")                        # the next command: it undoes the run first
    assert again.returncode == 3 and "not_installed" in again.stderr, again.stderr
    assert home.snapshot() == before
    installed(home, source)
    assert home.run("check").returncode == 0
    reference = home.snapshot()
    assert home.run("uninstall").returncode == 0
    assert home.read(".tmux.conf") == b"set -g mouse on" and set(reference) > set(before)


@pytest.mark.parametrize("signal_name", ["SIGTERM", "SIGINT", "SIGHUP"])
def test_a_catchable_signal_during_install_undoes_the_run_at_once(home, source, signal_name):
    home.write(".tmux.conf", b"set -g mouse on\n")
    before = home.snapshot()
    result = home.run("install", source=source, env=stop_at(home, "after", 9, signal_name))
    assert result.returncode == 4 and "interrupted" in result.stderr and "undone" in result.stderr
    assert home.snapshot() == before


@pytest.mark.mutates
@pytest.mark.parametrize("point", [("before", 0), ("after", 0), ("after", 1), ("after", 2)],
                         ids=lambda point: "%s-%d" % point)
def test_sigkill_during_upgrade_is_undone_and_upgrade_then_succeeds(home, source, point):
    installed(home, source)
    commit_change(source, "1.1.0")
    before = home.snapshot()
    position, index = point
    killed = home.run("upgrade", source=source, env=stop_at(home, position, index))
    assert killed.returncode == -signal.SIGKILL
    again = home.run("rollback")                        # recovers, then finds no previous release
    assert again.returncode == 3 and "no_previous" in again.stderr, again.stderr
    assert home.snapshot() == before
    assert home.run("upgrade", source=source).returncode == 0
    assert home.run("check").returncode == 0


UNINSTALL_POINTS = [("before", 0), ("after", 0), ("after", 2), ("after", 5), ("after", 9), ("after", 12),
                    ("after", 14), ("after", -1)]


@pytest.mark.parametrize("point", UNINSTALL_POINTS, ids=lambda point: "%s-%d" % point)
def test_sigkill_during_uninstall_blocks_other_commands_and_the_next_uninstall_finishes(home, source, point):
    before = home.snapshot()
    installed(home, source)
    count = step_count(home, "uninstall")
    position, index = point
    index = count - 1 if index < 0 else min(index, count - 1)
    killed = home.run("uninstall", env=stop_at(home, position, index))
    assert killed.returncode == -signal.SIGKILL
    middle = home.snapshot()
    pending = [place for place in (LIB, ".local/lib", ".local", ".") if home.path(place + "/" + journal.NAME).exists()]
    if pending:                                 # cut off before the journal went: only `uninstall` may go on
        other = home.run("install", source=source)
        assert other.returncode == 3 and "uninstall_interrupted" in other.stderr
        assert home.snapshot() == middle
        assert home.run("check").returncode == 1
    else:                                       # cut off after it: nothing is left to finish, and nothing blocks
        assert not home.path(LIB + "/install.json").exists()
    finished = home.run("uninstall")
    assert finished.returncode in (0, 3), finished.stderr
    after = home.snapshot()
    assert set(after) - set(before) <= DRAFT | {".local", ".local/lib", LIB} and all(path in after for path in before)
    assert not [path for path in after if path.startswith(LIB + "/")]
    assert home.run("install", source=source).returncode == 0           # not blocked afterwards


def test_a_dry_run_does_not_recover_and_says_so(home, source):
    installed(home, source)
    killed = home.run("uninstall", env=stop_at(home, "after", 3))
    assert killed.returncode == -signal.SIGKILL
    before = home.snapshot()
    result = home.run("uninstall", "--dry-run")
    assert result.returncode == 3 and "run_interrupted" in result.stderr
    assert home.snapshot() == before


def test_a_journal_that_names_a_path_of_the_user_is_refused(home, source):
    installed(home, source)
    killed = home.run("uninstall", env=stop_at(home, "after", 3))
    assert killed.returncode == -signal.SIGKILL
    path = home.path(LIB + "/" + journal.NAME)
    document = json.loads(path.read_text())
    document["specs"].append({"op": "rm_tree", "path": str(home.path(".claude/skills/other-skill"))})
    path.write_text(json.dumps(document))
    before = home.snapshot()
    result = home.run("uninstall")
    assert result.returncode == 3 and "journal_invalid" in result.stderr
    assert home.snapshot() == before and home.path(".claude/skills/other-skill/SKILL.md").exists()


def test_a_failed_atomic_write_leaves_no_temporary_file(home, monkeypatch):
    target = home.root / "record.json"
    monkeypatch.setattr(actions, "write_all", lambda *arguments, **keywords: (_ for _ in ()).throw(OSError(5, "x")))
    with pytest.raises(OSError):
        actions._write_atomic(target, b"data")
    assert sorted(path.name for path in home.root.iterdir() if path.name.startswith(".record")) == []


# ---------------------------------------------------------------- 6. no bytecode in the checkout

@pytest.mark.mutates
def test_the_installer_and_the_product_it_imports_write_no_bytecode_into_the_checkout(home, source):
    installer = source / "install" / "project-agent-install"
    home.write(REGISTRY_DRAFT, json.dumps({str(home.home / "p"): {"project": "x", "provider": "codex",
                                                                    "seats": []}}).encode())
    (home.home / "p").mkdir()
    assert home.run("install", source=source, installer=installer).returncode == 0
    result = home.run("uninstall", "--dry-run", installer=installer)
    assert result.returncode == 0, result.stderr
    assert not list(source.rglob("__pycache__"))
