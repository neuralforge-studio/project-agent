"""Acceptance tests T36~T42 of install-contract.md section 8.2: the release holds the Rust sidebar source and the
binary the installer built from it (BOARD-018).

Most cases give the installer a fake cargo (harness.FAKE_CARGO), which makes the program a real cargo would
make; T42 runs the real cargo once.
"""

import json
import os
import shutil
import subprocess

import pytest

from harness import (LIB, REAL_CARGO, REPO, assert_changes, commit_change, install_paths, release_name)

BINARY = "tools/project-board/bin/project-board-sidebar"
CRATE_FILES = ("Cargo.toml", "Cargo.lock", ".cargo/config.toml", "src/main.rs")


def tree(name):
    return LIB + "/releases/" + name


def run_ok(home, *args, source=None, env=None):
    result = home.run(*args, source=source, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def sidebar(home, release):
    """The release's sidebar program, run as `check` runs it."""
    return subprocess.run([str(home.path(tree(release) + "/" + BINARY)), "--version"], capture_output=True, text=True)


def leftovers(home):
    """Directories a build may leave behind: a temporary release or a build directory under TMPDIR."""
    temporary = [path.name for path in home.path(LIB + "/releases").glob(".tmp-*")] if home.path(LIB).exists() else []
    scratch = [path.name for path in home.path("tmp").iterdir()]
    return temporary + scratch


# ---------------------------------------------------------------- T36: install

def test_t36_install_builds_the_sidebar_into_the_release_and_installs_the_source(home, source, name):
    before = home.snapshot()
    result = run_ok(home, "install", source=source)
    assert_changes(before, home.snapshot(), created=install_paths(name) | {".tmux.conf"}, trees=[tree(name)])
    release = home.path(tree(name))
    for relative in CRATE_FILES:
        assert (release / "tools/project-board/rust" / relative).is_file(), relative
    assert not (release / "tools/project-board/rust/target").exists()
    binary = release / BINARY
    assert binary.is_file() and os.access(binary, os.X_OK)
    version = sidebar(home, name)
    assert version.returncode == 0 and version.stdout.startswith("project-board-sidebar ")
    assert not (REPO / BINARY).exists()                                       # the repository holds no binary
    assert os.readlink(home.path(LIB + "/current")) == "releases/" + name
    assert home.run("check").returncode == 0
    assert "cargo" in result.stdout                                           # the output says what was built
    assert leftovers(home) == []                                               # no build directory is left


def test_t36_the_build_runs_offline_and_locked_in_the_crate_of_the_release(home, source, name):
    run_ok(home, "install", source=source)
    calls = home.cargo_calls()
    assert len(calls) == 1
    assert " build --release --offline --locked --target-dir " in calls[0]
    cwd = calls[0].split("cwd=")[1].split(" cargo_home=")[0]
    assert cwd.endswith("/releases/.tmp-%s/tools/project-board/rust" % name)    # built from the copy that is shipped
    assert "Cargo.toml" in calls[0].split("files=")[1] and "Cargo.lock" in calls[0].split("files=")[1]
    cargo_home = calls[0].split("cargo_home=")[1].split(" args=")[0]
    assert cargo_home.startswith(str(home.path("tmp/project-agent-build-")))    # the build directory, not the user's ~/.cargo
    assert not home.path(".cargo").exists()


def test_t36_a_failed_build_leaves_the_home_as_it_was(home, source):
    before = home.snapshot()
    result = home.run("install", source=source, env={"FAKE_CARGO_MODE": "fail"})
    assert result.returncode == 4
    assert "FAKE-CARGO-REASON: no space left" in result.stderr and "101" in result.stderr
    assert home.snapshot() == before
    assert not home.path(LIB).exists()


# ---------------------------------------------------------------- T37, T38: upgrade

@pytest.mark.mutates
def test_t37_upgrade_builds_the_new_release_and_then_switches_current(home, source):
    run_ok(home, "install", source=source)
    first = release_name(source)
    commit_change(source, "1.1.0")
    second = release_name(source)
    before = home.snapshot()
    run_ok(home, "upgrade", source=source)
    assert_changes(before, home.snapshot(), created={tree(second)}, modified={LIB + "/current", LIB + "/install.json"},
                   trees=[tree(second)])
    assert os.readlink(home.path(LIB + "/current")) == "releases/" + second
    assert sidebar(home, second).returncode == 0
    assert sidebar(home, first).returncode == 0                                # the old release keeps its own program
    assert len(home.cargo_calls()) == 2
    assert home.run("check").returncode == 0
    assert leftovers(home) == []


@pytest.mark.mutates
def test_t38_a_failed_build_on_upgrade_changes_nothing(home, source):
    run_ok(home, "install", source=source)
    first = release_name(source)
    commit_change(source, "1.1.0")
    second = release_name(source)
    before = home.snapshot()
    result = home.run("upgrade", source=source, env={"FAKE_CARGO_MODE": "fail"})
    assert result.returncode == 4
    assert "FAKE-CARGO-REASON: no space left" in result.stderr             # the reason is shown
    assert home.snapshot() == before                                       # `current`, the record, every release as they were
    assert os.readlink(home.path(LIB + "/current")) == "releases/" + first
    assert not home.path(tree(second)).exists() and leftovers(home) == []  # no half release
    assert home.run("check").returncode == 0
    run_ok(home, "upgrade", source=source)                                 # the next run, with a working cargo, succeeds
    assert os.readlink(home.path(LIB + "/current")) == "releases/" + second


@pytest.mark.mutates
def test_t38_a_build_that_makes_no_program_is_a_failure_too(home, source):
    run_ok(home, "install", source=source)
    commit_change(source, "1.1.0")
    before = home.snapshot()
    result = home.run("upgrade", source=source, env={"FAKE_CARGO_MODE": "nobinary"})
    assert result.returncode == 4 and "made no project-board-sidebar" in result.stderr
    assert home.snapshot() == before


@pytest.mark.mutates
def test_t37_rollback_and_a_repeated_upgrade_do_not_build(home, source):
    run_ok(home, "install", source=source)
    commit_change(source, "1.1.0")
    run_ok(home, "upgrade", source=source)
    calls = len(home.cargo_calls())
    run_ok(home, "rollback", env={"PROJECT_AGENT_CARGO": "/nonexistent/cargo"})     # needs no cargo at all
    run_ok(home, "upgrade", source=source)                                           # the release exists: pointed at, not built
    assert len(home.cargo_calls()) == calls


def test_t37_installing_the_current_release_again_needs_no_cargo(home, source):
    run_ok(home, "install", source=source)
    before = home.snapshot()
    result = run_ok(home, "install", source=source, env={"PROJECT_AGENT_CARGO": "/nonexistent/cargo"})
    assert "Nothing to change" in result.stdout and home.snapshot() == before


# ---------------------------------------------------------------- T39: dry-run

@pytest.mark.mutates
def test_t39_dry_run_does_not_build_and_says_what_it_would_build(home, source):
    before = home.snapshot()
    result = run_ok(home, "install", "--dry-run", source=source)
    assert home.cargo_calls() == [] and home.snapshot() == before
    assert str(home.fake_cargo) in result.stdout and str(home.vendor) in result.stdout
    assert "builds project-board-sidebar" in result.stdout
    run_ok(home, "install", source=source)
    commit_change(source, "1.1.0")
    calls = len(home.cargo_calls())
    upgrade = run_ok(home, "upgrade", "--dry-run", source=source)
    assert len(home.cargo_calls()) == calls and "builds project-board-sidebar" in upgrade.stdout
    assert str(home.fake_cargo) in upgrade.stdout


def test_t39_dry_run_lists_the_changes_of_the_real_run(home, source):
    dry = json.loads(run_ok(home, "install", "--dry-run", "--json", source=source).stdout)["changes"]
    assert home.cargo_calls() == []
    real = json.loads(run_ok(home, "install", "--json", source=source).stdout)["changes"]
    assert dry == real


# ---------------------------------------------------------------- T40: check

@pytest.mark.parametrize("damage", ["missing", "not-runnable", "wrong-program"])
def test_t40_check_reports_a_missing_or_unrunnable_sidebar(home, source, name, damage):
    run_ok(home, "install", source=source)
    assert home.run("check").returncode == 0
    binary = home.path(tree(name) + "/" + BINARY)
    binary.parent.chmod(0o755)
    binary.chmod(0o755)
    if damage == "missing":
        binary.unlink()
    elif damage == "not-runnable":
        binary.write_bytes(b"\x7fELF not a program")
    else:
        binary.write_text("#!/bin/sh\necho something else 1.0\n")
    before = home.snapshot()
    result = home.run("check")
    assert result.returncode == 1
    assert "project-board-sidebar" in result.stdout and "FAIL" in result.stdout
    assert home.snapshot() == before                                         # `check` reads only


# ---------------------------------------------------------------- T41: no toolchain

def test_t41_without_cargo_nothing_is_changed_and_the_message_names_the_variable(home, source):
    before = home.snapshot()
    result = home.run("install", source=source, env={"PROJECT_AGENT_CARGO": str(home.root / "absent" / "cargo")})
    assert result.returncode == 3 and "cargo_missing" in result.stderr and "PROJECT_AGENT_CARGO" in result.stderr
    assert home.snapshot() == before
    dry = home.run("install", "--dry-run", source=source, env={"PROJECT_AGENT_CARGO": str(home.root / "absent" / "cargo")})
    assert dry.returncode == 3 and "cargo_missing" in dry.stderr                 # dry-run checks the toolchain too


def test_t41_cargo_is_looked_up_in_order_variable_then_inhouse_then_path(home, source, tmp_path):
    """Without the variable the installer finds cargo in the in-house location or PATH; with the variable set to
    something unusable it does not fall back."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shutil.copy2(home.fake_cargo, bin_dir / "cargo")
    result = home.run("install", "--dry-run", "--json", source=source,
                      env={"PROJECT_AGENT_CARGO": "", "PATH": str(bin_dir) + os.pathsep + home.env["PATH"]})
    assert result.returncode == 0
    notes = " ".join(json.loads(result.stdout)["notes"])
    inhouse = "/primehome/tools/Inhouse/Rust/latest/bin/cargo"
    assert (inhouse if os.access(inhouse, os.X_OK) else str(bin_dir / "cargo")) in notes   # an empty variable is not set


def test_t41_a_missing_vendored_directory_refuses_and_names_it(home, source):
    before = home.snapshot()
    absent = home.root / "no-vendor"
    result = home.run("install", source=source, env={"PROJECT_AGENT_RUST_VENDOR": str(absent)})
    assert result.returncode == 3 and "vendor_missing" in result.stderr and str(absent) in result.stderr
    assert "PROJECT_AGENT_RUST_VENDOR" in result.stderr and home.snapshot() == before
    assert home.cargo_calls() == []


def test_t41_the_vendored_directory_comes_from_the_crate_config_unless_the_variable_overrides_it(home, source):
    config = (REPO / "tools/project-board/rust/.cargo/config.toml").read_text()
    committed = [line.split('"')[1] for line in config.splitlines() if line.startswith("directory")][0]
    run_ok(home, "install", source=source)                                       # the variable: passed to cargo
    assert '--config source.vendored-sources.directory="%s"' % home.vendor in home.cargo_calls()[0]
    if not os.path.isdir(committed):                                              # a host without the in-house crates
        refused = home.run("install", "--dry-run", source=source, env={"PROJECT_AGENT_RUST_VENDOR": ""})
        assert refused.returncode == 3 and committed in refused.stderr
    else:
        home.run("uninstall")
        run_ok(home, "install", source=source, env={"PROJECT_AGENT_RUST_VENDOR": ""})
        assert "--config" not in home.cargo_calls()[1]                           # the crate's own config is used


# ---------------------------------------------------------------- T42: the real cargo

@pytest.mark.slow
@pytest.mark.skipif(not (os.path.isfile(REAL_CARGO) and os.access(REAL_CARGO, os.X_OK)),
                    reason="the in-house cargo is not on this host")
def test_t42_the_real_cargo_builds_a_sidebar_that_runs(home, source, name):
    env = {"PROJECT_AGENT_CARGO": REAL_CARGO, "PROJECT_AGENT_RUST_VENDOR": ""}
    before = home.snapshot()
    # a real build takes 40 s on a quiet host and 5 minutes on a loaded one (host load above 60)
    result = home.run("install", source=source, env=env, timeout=1800)
    assert result.returncode == 0, result.stdout + result.stderr
    assert_changes(before, home.snapshot(), created=install_paths(name) | {".tmux.conf"}, trees=[tree(name)])
    version = sidebar(home, name)
    assert version.returncode == 0 and version.stdout.startswith("project-board-sidebar "), version
    assert home.run("check", env=env).returncode == 0
    assert not home.path(".cargo").exists() and leftovers(home) == []
