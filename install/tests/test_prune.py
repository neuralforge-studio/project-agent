"""INSTALL-004: `upgrade` and `rollback` refuse a release whose format versions differ from a run that is up,
and `prune` removes the releases nothing uses (install-contract.md 7.1, 7.1.1 and 8.2 T24-T27).

The runs are real `agent-session` runs of the installed release on a private tmux server (harness.Runs); the
expectations are written from the contract, not read from the install record.
"""

import json
import signal

import pytest

from harness import LIB, REPO, assert_changes, commit_change, release_name, stop_at

pytestmark = pytest.mark.skipif(not __import__("shutil").which("tmux"), reason="tmux is unavailable")


def tree(name):
    return LIB + "/releases/" + name


def install(home, source):
    result = home.run("install", source=source)
    assert result.returncode == 0, result.stderr


def release(source, version, **formats):
    """Commit a new release of `source` whose format versions are the given ones (the others stay 1)."""
    declared = json.loads((source / "tools/formats.json").read_text())
    declared.update(formats)
    (source / "tools/formats.json").write_text(json.dumps(declared, indent=4) + "\n")
    commit_change(source, version)
    return release_name(source)


def socket_env(runs):
    return {"AGENT_SESSION_SOCKET": str(runs.socket)}


def record(home):
    return json.loads(home.read(LIB + "/install.json"))


def upgrade(home, source, runs):
    return home.run("upgrade", source=source, env=socket_env(runs))


# ---------------------------------------------------------------- T24: upgrade refuses another format

@pytest.mark.mutates
def test_t24_upgrade_to_another_format_is_refused_while_a_run_is_up(home, source, runs):
    install(home, source)
    runs.start_leader()
    release(source, "2.0.0", agent_session=2)
    before = home.snapshot()
    for extra in ((), ("--dry-run",)):
        result = home.run("upgrade", *extra, source=source, env=socket_env(runs))
        assert result.returncode == 3 and "formats_differ" in result.stderr, result.stderr
        assert "run %s leader (alive)" % runs.PROJECT in result.stderr
        assert "agent_session 1 (target 2)" in result.stderr and "restart" in result.stderr
        assert home.snapshot() == before


@pytest.mark.mutates
def test_t24_an_unknown_run_counts_as_up(home, source, runs):
    install(home, source)
    runs.start_leader()
    runs.kill_server()                                # no run in tmux any more: the state still names one
    release(source, "2.0.0", item_files=2)
    before = home.snapshot()
    result = upgrade(home, source, runs)
    assert result.returncode == 3 and "run %s leader (unknown)" % runs.PROJECT in result.stderr, result.stderr
    assert "item_files 1 (target 2)" in result.stderr
    assert home.snapshot() == before


@pytest.mark.mutates
def test_t24_another_format_goes_through_without_a_run_that_is_up(home, source, runs):
    install(home, source)
    runs.start_leader()
    runs.stop_leader()
    second = release(source, "2.0.0", tmux_options=2)
    before = home.snapshot()
    result = upgrade(home, source, runs)
    assert result.returncode == 0, result.stderr
    assert_changes(before, home.snapshot(), created={tree(second)}, modified={LIB + "/current", LIB + "/install.json"},
                   trees=[tree(second)])


@pytest.mark.mutates
def test_t24_the_same_formats_go_through_while_a_run_is_up(home, source, runs):
    install(home, source)
    runs.start_leader()
    second = release(source, "1.1.0")
    result = upgrade(home, source, runs)
    assert result.returncode == 0, result.stderr
    assert record(home)["current"] == second


@pytest.mark.mutates
def test_t24_a_target_without_a_format_declaration_cannot_be_judged(home, source, runs):
    install(home, source)
    runs.start_leader()
    (source / "tools/formats.json").unlink()
    commit_change(source, "1.1.0")
    before = home.snapshot()
    result = upgrade(home, source, runs)
    assert result.returncode == 3 and "formats_unreadable" in result.stderr, result.stderr
    assert home.snapshot() == before


# ---------------------------------------------------------------- T24: rollback refuses another format

@pytest.mark.mutates
def test_t24_rollback_to_another_format_is_refused_while_a_run_is_up(home, source, runs):
    install(home, source)
    first = release_name(source)
    release(source, "2.0.0", agent_session=2)
    assert upgrade(home, source, runs).returncode == 0           # no run yet
    runs.start_leader()                                          # on the new release (format 2)
    before = home.snapshot()
    result = home.run("rollback", env=socket_env(runs))
    assert result.returncode == 3 and "formats_differ" in result.stderr, result.stderr
    assert "run %s leader (alive)" % runs.PROJECT in result.stderr and first in result.stderr
    assert home.snapshot() == before
    runs.stop_leader()
    assert home.run("rollback", env=socket_env(runs)).returncode == 0
    assert record(home)["current"] == first


@pytest.mark.mutates
def test_t24_rollback_to_the_same_formats_goes_through_while_a_run_is_up(home, source, runs):
    install(home, source)
    first = release_name(source)
    release(source, "1.1.0")
    assert upgrade(home, source, runs).returncode == 0
    runs.start_leader()
    result = home.run("rollback", env=socket_env(runs))
    assert result.returncode == 0, result.stderr
    assert record(home)["current"] == first


# ---------------------------------------------------------------- T25: a run that is not from a release

@pytest.mark.mutates
def test_t25_the_frozen_copy_is_format_1_and_does_not_block_the_first_release(home, source, runs):
    runs.start_leader_from(REPO)                      # a checkout of the product, not a release
    install(home, source)                             # `install` and the next `upgrade` go through ...
    second = release(source, "1.1.0")
    result = upgrade(home, source, runs)
    assert result.returncode == 0, result.stderr
    assert record(home)["current"] == second


@pytest.mark.mutates
def test_t25_the_frozen_copy_is_refused_for_a_release_of_another_format(home, source, runs):
    runs.start_leader_from(REPO)
    install(home, source)
    release(source, "2.0.0", agent_session=2)
    before = home.snapshot()
    result = upgrade(home, source, runs)
    assert result.returncode == 3 and "formats_differ" in result.stderr, result.stderr
    assert "a copy that is not a release" in result.stderr and "agent_session 1 (target 2)" in result.stderr
    assert home.snapshot() == before


# ---------------------------------------------------------------- T26: prune

def three_releases(home, source, runs=None):
    """Install A, upgrade to B and C: current C, previous B, A is unused."""
    install(home, source)
    names = [release_name(source)]
    for version in ("1.1.0", "1.2.0"):
        commit_change(source, version)
        names.append(release_name(source))
        result = home.run("upgrade", source=source, env=socket_env(runs) if runs else None)
        assert result.returncode == 0, result.stderr
    return names


def prune(home, runs, *args):
    return home.run("prune", *args, env=socket_env(runs))


@pytest.mark.mutates
def test_t26_prune_removes_what_is_not_current_previous_or_in_use(home, source, runs):
    first, second, third = three_releases(home, source, runs)
    assert record(home)["current"] == third and record(home)["previous"] == second
    before = home.snapshot()
    dry = prune(home, runs, "--dry-run", "--json")
    assert dry.returncode == 0, dry.stderr
    assert home.snapshot() == before
    result = prune(home, runs, "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(dry.stdout)["changes"] == json.loads(result.stdout)["changes"] != []
    assert [change["path"] for change in json.loads(result.stdout)["changes"]] == ["~/" + tree(first)]
    assert_changes(before, home.snapshot(), removed={tree(first)}, modified={LIB + "/install.json"},
                   trees=[tree(first)])
    after = record(home)
    assert sorted(after["releases"]) == sorted([second, third]) and after["current"] == third
    assert not [entry for entry in after["owned"] if first in entry["path"]]
    assert home.run("check").returncode == 0
    again = prune(home, runs)
    assert again.returncode == 0 and "No release to remove" in again.stdout


@pytest.mark.mutates
def test_t26_prune_keeps_the_release_of_a_run_that_is_up_and_removes_it_once_it_ended(home, source, runs):
    install(home, source)
    first = release_name(source)
    runs.start_leader()                               # on A
    for version in ("1.1.0", "1.2.0"):
        commit_change(source, version)
        assert upgrade(home, source, runs).returncode == 0
    before = home.snapshot()
    kept = prune(home, runs)
    assert kept.returncode == 0 and "Kept release %s (used by %s/leader)" % (first, runs.PROJECT) in kept.stdout
    assert home.snapshot() == before
    runs.stop_leader()
    assert prune(home, runs).returncode == 0
    assert not home.path(tree(first)).exists() and first not in record(home)["releases"]


@pytest.mark.mutates
def test_t26_prune_keeps_what_an_unknown_run_may_use(home, source, runs):
    install(home, source)
    first = release_name(source)
    runs.start_leader()
    runs.kill_server()                                # `unknown`: tmux names no run, the run directory does
    for version in ("1.1.0", "1.2.0"):
        commit_change(source, version)
        assert upgrade(home, source, runs).returncode == 0
    before = home.snapshot()
    result = prune(home, runs)
    assert result.returncode == 0 and "Kept release %s" % first in result.stdout, result.stdout
    assert home.snapshot() == before


@pytest.mark.mutates
def test_t26_prune_keeps_a_release_that_is_not_as_the_installer_made_it(home, source, runs):
    first, _, _ = three_releases(home, source, runs)
    home.path(tree(first)).chmod(0o755)
    home.write(tree(first) + "/mine.txt", b"my file\n")
    before = home.snapshot()
    result = prune(home, runs)
    assert result.returncode == 0 and "Kept release %s" % first in result.stdout and "changed by you" in result.stdout
    assert home.snapshot() == before


@pytest.mark.mutates
def test_t26_prune_keeps_the_previous_release_after_a_rollback(home, source, runs):
    first, second, third = three_releases(home, source, runs)
    assert home.run("rollback", env=socket_env(runs)).returncode == 0          # current B, previous C
    result = prune(home, runs)
    assert result.returncode == 0, result.stderr
    assert not home.path(tree(first)).exists()
    assert home.path(tree(second)).is_dir() and home.path(tree(third)).is_dir()


@pytest.mark.mutates
def test_t26_prune_says_when_project_board_is_on(home, source, runs):
    three_releases(home, source, runs)
    runs.tmux("set-option", "-g", "@project_board_enabled", "1")
    result = prune(home, runs, "--dry-run")
    assert result.returncode == 0 and "Project Board is on" in result.stdout
    runs.tmux("set-option", "-g", "@project_board_enabled", "0")
    assert "Project Board is on" not in prune(home, runs, "--dry-run").stdout


def test_t26_prune_needs_an_installation(home, runs):
    result = prune(home, runs)
    assert result.returncode == 3 and "not_installed" in result.stderr


# ---------------------------------------------------------------- T27: a prune cut off

@pytest.mark.mutates
@pytest.mark.parametrize("point", [("before", 0), ("after", 0)], ids=lambda point: "%s-%d" % point)
def test_t27_a_cut_off_prune_is_finished_by_the_next_prune(home, source, runs, point):
    first, second, third = three_releases(home, source, runs)
    position, index = point
    killed = home.run("prune", env={**socket_env(runs), **stop_at(home, position, index)})
    assert killed.returncode == -signal.SIGKILL
    assert home.run("check").returncode == 1                          # the journal is still there
    other = home.run("upgrade", source=source, env=socket_env(runs))
    assert other.returncode == 3 and "prune_interrupted" in other.stderr
    assert prune(home, runs, "--dry-run").returncode == 3
    finished = prune(home, runs)
    assert finished.returncode == 0 and "interrupted prune was finished" in finished.stdout, finished.stderr
    assert not home.path(tree(first)).exists() and first not in record(home)["releases"]
    assert home.path(tree(second)).is_dir() and home.path(tree(third)).is_dir()
    assert home.run("check").returncode == 0
    leftovers = [path for path in home.snapshot() if path.rsplit("/", 1)[-1].startswith((".tmp-", ".project-agent-install"))]
    assert not leftovers, leftovers
