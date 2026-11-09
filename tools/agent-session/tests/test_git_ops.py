"""Git preparation against local origin repos, including ignored file guards."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_session import git_ops
from agent_session.errors import SessionError
from agent_session.state import StateStore


def git(path, *args):
    result = subprocess.run(["git", "-C", str(path), *args], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def identity(path):
    git(path, "config", "user.name", "Fixture")
    git(path, "config", "user.email", "fixture@example.invalid")


def file_snapshot(path):
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, path.read_bytes())


@pytest.fixture
def repo(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(origin)], check=True, capture_output=True)
    source = tmp_path / "source"
    git(tmp_path, "clone", str(origin), str(source))
    identity(source)
    (source / ".gitignore").write_text("private.txt\n")
    (source / "data.txt").write_text("first\n")
    git(source, "add", ".gitignore", "data.txt")
    git(source, "commit", "-m", "Initial data")
    git(source, "push", "origin", "main")
    initial = git(source, "rev-parse", "HEAD")
    seat = tmp_path / "seat"
    git(tmp_path, "clone", str(origin), str(seat))
    identity(seat)
    return source, seat, initial


@pytest.fixture
def cr_bases(monkeypatch):
    """Record the CR Base header writes instead of a project-item CR file."""
    from agent_session import jobs
    written = []
    monkeypatch.setattr(jobs, "set_base", lambda project, job_id, base: written.append(base))
    return written


def setup_job(tmp_path, seat, mode="write", base=None):
    root = tmp_path / "base"
    root.mkdir(exist_ok=True)
    project = SimpleNamespace(base=root, provider="codex", seats=(seat,),
                              state_path=root / "agent/state.json", runtime_path=root / "agent")
    store = StateStore(project)
    job = {"job_id": "TOOL-001", "mode": mode, "branch": "cr/TOOL-001" if mode == "write" else None, "base": base}
    store.update(lambda state: state["0"].update(job_id=job["job_id"], git_hash=None))
    context = {"seat": 0, "seat_root": str(seat), "job": job}
    return context, store, project


def advance(source, text="upstream\n"):
    (source / "data.txt").write_text(text)
    git(source, "add", "data.txt")
    git(source, "commit", "-m", "Update upstream data")
    git(source, "push", "origin", "main")
    return git(source, "rev-parse", "HEAD")


def test_first_preparation_records_synced_revision_and_cr_branch(tmp_path, repo, cr_bases):
    source, seat, _ = repo
    expected = advance(source)
    context, store, project = setup_job(tmp_path, seat)
    baseline = git_ops.prepare(context, project, store)
    assert baseline == {"base_hash": expected, "base_commit_time": git(source, "show", "-s", "--format=%cI", expected)}
    assert cr_bases == [baseline]
    assert store.read()["0"]["git_hash"] == expected
    assert git(seat, "branch", "--show-current") == "cr/TOOL-001"


def test_retry_preserves_base_and_unfinished_work(tmp_path, repo, cr_bases):
    source, seat, expected = repo
    context, store, project = setup_job(tmp_path, seat)
    first = git_ops.prepare(context, project, store)
    advance(source)
    (seat / "data.txt").write_text("unfinished local work\n")
    retry = {**context, "job": {**context["job"], "base": first}}
    assert git_ops.prepare(retry, project, store) == first
    assert cr_bases == [first]
    assert store.read()["0"]["git_hash"] == expected
    assert (seat / "data.txt").read_text() == "unfinished local work\n"
    assert git(seat, "rev-parse", "HEAD") == expected


def test_read_only_preparation_syncs_main_without_a_branch(tmp_path, repo, cr_bases):
    source, seat, _ = repo
    updated = advance(source)
    context, store, project = setup_job(tmp_path, seat, "read-only")
    assert git_ops.prepare(context, project, store)["base_hash"] == updated
    assert git(seat, "branch", "--show-current") == "main"
    assert store.read()["0"]["git_hash"] == updated


def test_non_git_seat_is_refused(tmp_path, cr_bases):
    seat = tmp_path / "plain"
    seat.mkdir()
    context, store, project = setup_job(tmp_path, seat)
    with pytest.raises(SessionError) as error:
        git_ops.prepare(context, project, store)
    assert error.value.code == "seat_unavailable"
    assert cr_bases == [] and store.read()["0"]["git_hash"] is None


def test_lost_cr_base_is_restored_from_the_state(tmp_path, repo, monkeypatch):
    source, seat, initial = repo
    from agent_session import jobs
    context, store, project = setup_job(tmp_path, seat)
    calls = []

    def lose_first_write(project, job_id, base):
        calls.append(base)
        if len(calls) == 1:
            raise SessionError("fixture_write_failure", "The CR write failed.", 5)

    monkeypatch.setattr(jobs, "set_base", lose_first_write)
    with pytest.raises(SessionError, match="CR write failed"):
        git_ops.prepare(context, project, store)
    assert store.read()["0"]["git_hash"] == initial
    advance(source)
    git_ops.prepare(context, project, store)
    assert calls[-1]["base_hash"] == initial
    assert git(seat, "rev-parse", "HEAD") == initial
    assert git(seat, "branch", "--show-current") == "cr/TOOL-001"


def test_parked_write_cr_continues_the_published_branch(tmp_path, repo, cr_bases):
    source, seat, initial = repo
    other = tmp_path / "other"
    git(tmp_path, "clone", str(tmp_path / "origin.git"), str(other))
    identity(other)
    git(other, "switch", "-c", "cr/TOOL-001", initial)
    (other / "data.txt").write_text("parked work\n")
    git(other, "commit", "-am", "Parked work")
    git(other, "push", "origin", "cr/TOOL-001")
    parked = git(other, "rev-parse", "HEAD")
    advance(source)
    base = {"base_hash": initial, "base_commit_time": git(source, "show", "-s", "--format=%cI", initial)}
    context, store, project = setup_job(tmp_path, seat, base=base)
    assert git_ops.prepare(context, project, store) == base
    assert cr_bases == []
    assert git(seat, "branch", "--show-current") == "cr/TOOL-001"
    assert git(seat, "rev-parse", "HEAD") == parked
    assert store.read()["0"]["git_hash"] == initial


def test_parked_read_only_cr_prepares_again_from_main(tmp_path, repo, cr_bases):
    source, seat, initial = repo
    updated = advance(source)
    old = {"base_hash": initial, "base_commit_time": "2026-11-04T00:00:00+00:00"}
    context, store, project = setup_job(tmp_path, seat, "read-only", base=old)
    assert git_ops.prepare(context, project, store)["base_hash"] == updated
    assert cr_bases[-1]["base_hash"] == updated


@pytest.mark.parametrize("branch_location", ["local", "remote", "both"])
def test_read_only_to_write_fast_forwards_the_old_cr_branch(tmp_path, repo, cr_bases, branch_location):
    source, seat, initial = repo
    branch = "cr/TOOL-001"
    if branch_location != "remote":
        git(seat, "branch", branch, initial)
    if branch_location != "local":
        git(source, "push", "origin", f"{initial}:refs/heads/{branch}")
    git(seat, "branch", "unrelated", initial)
    expected = advance(source)
    context, store, project = setup_job(tmp_path, seat, "read-only")
    base = git_ops.prepare(context, project, store)
    assert base["base_hash"] == expected

    # The read-only assignment was released; the same CR now has write permission.
    context, store, project = setup_job(tmp_path, seat, base=base)
    files = [seat / "notes.txt", seat / "private.txt"]
    for path in files:
        path.write_text("keep this user file\n")
    before = [file_snapshot(path) for path in files]
    advance(source, "newer than the recorded Base\n")
    assert git_ops.prepare(context, project, store) == base
    assert git(seat, "branch", "--show-current") == branch
    assert git(seat, "rev-parse", "HEAD") == expected
    assert git(seat, "rev-parse", "main") == expected
    assert git(seat, "rev-parse", "unrelated") == initial
    if branch_location != "local":
        assert git(source, "ls-remote", "origin", f"refs/heads/{branch}").split()[0] == initial
    assert [file_snapshot(path) for path in files] == before
    assert store.read()["0"]["git_hash"] == expected
    assert cr_bases == [base]

    (seat / "data.txt").write_text("unfinished write work\n")
    assert git_ops.prepare(context, project, store) == base
    assert (seat / "data.txt").read_text() == "unfinished write work\n"
    assert git(seat, "rev-parse", "HEAD") == expected


def test_reused_cr_branch_divergence_is_preserved_and_refused(tmp_path, repo, cr_bases):
    source, seat, initial = repo
    branch = "cr/TOOL-001"
    git(seat, "switch", "-c", branch)
    (seat / "work.txt").write_text("unmerged CR work\n")
    git(seat, "add", "work.txt")
    git(seat, "commit", "-m", "Unmerged CR work")
    tip = git(seat, "rev-parse", "HEAD")
    git(seat, "push", "origin", branch)
    git(seat, "switch", "main")
    advance(source)
    context, store, project = setup_job(tmp_path, seat, "read-only")
    base = git_ops.prepare(context, project, store)
    context, store, project = setup_job(tmp_path, seat, base=base)
    (seat / "private.txt").write_text("keep this user file\n")
    with pytest.raises(SessionError) as error:
        git_ops.prepare(context, project, store)
    assert error.value.code == "git_failed"
    assert git(seat, "rev-parse", branch) == tip
    assert git(source, "ls-remote", "origin", f"refs/heads/{branch}").split()[0] == tip
    assert (seat / "work.txt").read_text() == "unmerged CR work\n"
    assert (seat / "private.txt").read_text() == "keep this user file\n"
    assert store.read()["0"]["git_hash"] is None
    assert cr_bases == [base]


def test_reused_cr_fast_forward_retries_a_lost_state_write(tmp_path, repo, cr_bases, monkeypatch):
    source, seat, initial = repo
    branch = "cr/TOOL-001"
    git(seat, "branch", branch, initial)
    git(source, "push", "origin", f"{initial}:refs/heads/{branch}")
    expected = advance(source)
    context, store, project = setup_job(tmp_path, seat, "read-only")
    base = git_ops.prepare(context, project, store)
    context, store, project = setup_job(tmp_path, seat, base=base)
    original = store.update
    calls = []

    def lose_first_write(update):
        if not calls:
            calls.append(True)
            raise SessionError("fixture_write_failure", "The state write failed.", 5)
        return original(update)

    monkeypatch.setattr(store, "update", lose_first_write)
    with pytest.raises(SessionError) as error:
        git_ops.prepare(context, project, store)
    assert error.value.code == "fixture_write_failure"
    assert git(seat, "rev-parse", branch) == expected
    assert store.read()["0"]["git_hash"] is None
    advance(source, "newer than the recorded Base\n")
    assert git_ops.prepare(context, project, store) == base
    assert git(seat, "rev-parse", "HEAD") == expected
    assert git(source, "ls-remote", "origin", f"refs/heads/{branch}").split()[0] == initial
    assert store.read()["0"]["git_hash"] == expected
    assert cr_bases == [base]


@pytest.mark.parametrize("unmerged", ["local", "remote"])
def test_reused_cr_mismatched_unmerged_branches_are_refused(tmp_path, repo, cr_bases, unmerged):
    source, seat, initial = repo
    branch = "cr/TOOL-001"
    git(seat, "switch", "-c", "unmerged")
    (seat / "work.txt").write_text("unmerged work\n")
    git(seat, "add", "work.txt")
    git(seat, "commit", "-m", "Unmerged work")
    tip = git(seat, "rev-parse", "HEAD")
    published = initial if unmerged == "local" else tip
    git(seat, "push", "origin", f"{published}:refs/heads/{branch}")
    git(seat, "switch", "main")
    expected = advance(source)
    context, store, project = setup_job(tmp_path, seat, "read-only")
    base = git_ops.prepare(context, project, store)
    local = tip if unmerged == "local" else expected
    git(seat, "branch", branch, local)
    context, store, project = setup_job(tmp_path, seat, base=base)
    with pytest.raises(SessionError) as error:
        git_ops.prepare(context, project, store)
    assert error.value.code == "branch_mismatch"
    assert git(seat, "rev-parse", branch) == local
    assert git(source, "ls-remote", "origin", f"refs/heads/{branch}").split()[0] == published
    assert git(seat, "branch", "--show-current") == "main"
    assert store.read()["0"]["git_hash"] is None
    assert cr_bases == [base]


@pytest.mark.parametrize("filename", ["notes.txt", "private.txt"])
def test_reused_cr_fast_forward_refuses_user_file_collision(tmp_path, repo, cr_bases, filename):
    source, seat, initial = repo
    branch = "cr/TOOL-001"
    git(seat, "branch", branch, initial)
    git(source, "push", "origin", f"{initial}:refs/heads/{branch}")
    (source / filename).write_text("tracked upstream\n")
    git(source, "add", "-f", filename)
    git(source, "commit", "-m", "Track the collision path")
    git(source, "push", "origin", "main")
    expected = git(source, "rev-parse", "HEAD")
    base = {"base_hash": expected, "base_commit_time": git(source, "show", "-s", "--format=%cI", expected)}
    context, store, project = setup_job(tmp_path, seat, base=base)
    path = seat / filename
    path.write_text("preserve this user file\n")
    before = file_snapshot(path)
    with pytest.raises(SessionError) as error:
        git_ops.prepare(context, project, store)
    assert error.value.code == "git_failed"
    assert error.value.details["operation"][0] == "merge"
    assert file_snapshot(path) == before
    assert git(seat, "rev-parse", branch) == initial
    assert git(source, "ls-remote", "origin", f"refs/heads/{branch}").split()[0] == initial
    assert store.read()["0"]["git_hash"] is None
    assert cr_bases == []


@pytest.mark.parametrize("collision", ["local-main", "remote-main"])
def test_preparation_preserves_ignored_file_collision(tmp_path, repo, cr_bases, collision):
    source, seat, initial = repo
    if collision == "local-main":
        (seat / "private.txt").write_text("tracked on local main\n")
        git(seat, "add", "-f", "private.txt")
        git(seat, "commit", "-m", "Track a path on main")
        git(seat, "checkout", "-b", "previous", initial)
    else:
        (source / "private.txt").write_text("tracked on remote main\n")
        git(source, "add", "-f", "private.txt")
        git(source, "commit", "-m", "Track a path upstream")
        git(source, "push", "origin", "main")
    (seat / "private.txt").write_text("preserve this ignored user file\n")
    context, store, project = setup_job(tmp_path, seat)
    with pytest.raises(SessionError):
        git_ops.prepare(context, project, store)
    assert (seat / "private.txt").read_text() == "preserve this ignored user file\n"
    assert git(seat, "rev-parse", "HEAD") == initial
    assert store.read()["0"]["git_hash"] is None
    assert cr_bases == []


def test_read_only_reassignment_recovers_a_lost_cr_base_without_syncing_again(tmp_path, repo, monkeypatch):
    """B2: the new Base reached the state but not the CR; the retry keeps the same Base."""
    source, seat, initial = repo
    from agent_session import jobs
    updated = advance(source)
    old = {"base_hash": initial, "base_commit_time": "2026-11-04T00:00:00+00:00"}
    context, store, project = setup_job(tmp_path, seat, "read-only", base=old)
    calls = []

    def lose_first_write(project, job_id, base):
        calls.append(base)
        if len(calls) == 1:
            raise SessionError("fixture_write_failure", "The CR write failed.", 5)

    monkeypatch.setattr(jobs, "set_base", lose_first_write)
    with pytest.raises(SessionError, match="CR write failed"):
        git_ops.prepare(context, project, store)
    assert store.read()["0"]["git_hash"] == updated
    advance(source, "newer\n")
    retry = {**context, "job": {**context["job"], "base": old}}
    assert git_ops.prepare(retry, project, store)["base_hash"] == updated
    assert calls[-1]["base_hash"] == updated
    assert git(seat, "rev-parse", "HEAD") == updated


@pytest.fixture
def submodule_repo(tmp_path, repo, monkeypatch):
    """Origin main carries two submodules; the seat has initialized only the first at the old gitlink."""
    for key, value in (("protocol.file.allow", "always"),):          # fixture-only: local path submodules
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", key)
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", value)
    source, seat, _ = repo
    libs = {}
    for name in ("liba", "libb"):
        lib = tmp_path / name
        subprocess.run(["git", "init", "--initial-branch=main", str(lib)], check=True, capture_output=True)
        identity(lib)
        (lib / "lib.txt").write_text("v1\n")
        git(lib, "add", "lib.txt")
        git(lib, "commit", "-m", "Library v1")
        git(source, "submodule", "add", str(lib), f"external/{name}")
        libs[name] = lib
    git(source, "commit", "-m", "Add submodules")
    git(source, "push", "origin", "main")
    git(seat, "pull", "--ff-only")
    git(seat, "submodule", "update", "--init", "external/liba")
    return source, seat, libs


def bump(source, lib, name):
    (lib / "lib.txt").write_text("v2\n")
    git(lib, "commit", "-am", "Library v2")
    git(source / "external" / name, "pull", "--ff-only", str(lib), "main")
    git(source, "add", f"external/{name}")
    git(source, "commit", "-m", f"Bump {name}")
    git(source, "push", "origin", "main")
    return git(lib, "rev-parse", "HEAD")


@pytest.mark.parametrize("mode", ["write", "read-only"])
def test_start_aligns_initialized_and_uninitialized_submodules_with_main(tmp_path, submodule_repo, cr_bases, mode):
    source, seat, libs = submodule_repo
    new = bump(source, libs["liba"], "liba")
    context, store, project = setup_job(tmp_path, seat, mode)
    git_ops.prepare(context, project, store)
    assert git(seat, "-C", "external/liba", "rev-parse", "HEAD") == new
    assert (seat / "external/libb/lib.txt").read_text() == "v1\n"       # was never initialized
    assert git(seat, "status", "--porcelain", "--untracked-files=all") == ""


def test_reassigned_write_cr_realigns_submodules_with_its_branch(tmp_path, submodule_repo, cr_bases):
    source, seat, libs = submodule_repo
    context, store, project = setup_job(tmp_path, seat)
    first = git_ops.prepare(context, project, store)
    git(seat, "switch", "main")                  # parked: the seat later returns to another HEAD
    new = bump(source, libs["liba"], "liba")
    git(seat, "pull", "--ff-only")               # main moved; the parked branch stays at Base
    git(seat, "-C", "external/liba", "checkout", "--quiet", new)
    context, store, project = setup_job(tmp_path, seat, base=first)
    git_ops.prepare(context, project, store)
    assert git(seat, "branch", "--show-current") == "cr/TOOL-001"
    assert git(seat, "-C", "external/liba", "rev-parse", "HEAD") != new
    assert git(seat, "status", "--porcelain", "--untracked-files=all") == ""


def test_untouched_submodules_do_not_block_release(tmp_path, submodule_repo, cr_bases):
    from agent_session import workspace
    source, seat, libs = submodule_repo
    bump(source, libs["liba"], "liba")
    context, store, project = setup_job(tmp_path, seat)
    git_ops.prepare(context, project, store)
    meta = {"seat": 0, "seat_root": str(seat)}
    assert workspace.check_release(project, meta, ("done", "fixed")) == {"allowed": True, "reasons": []}


def test_submodule_failure_stops_the_preparation_as_git_failed(tmp_path, submodule_repo, cr_bases):
    source, seat, libs = submodule_repo
    bump(source, libs["liba"], "liba")
    import shutil
    shutil.rmtree(libs["liba"])
    context, store, project = setup_job(tmp_path, seat)
    with pytest.raises(SessionError) as error:
        git_ops.prepare(context, project, store)
    assert error.value.code == "git_failed"
    assert store.read()["0"]["git_hash"] is not None             # Git baseline stays recorded for the retry


def hold_index_lock_hook(seat, tmp_path):
    """A pre-commit hook that keeps `git commit <path>` holding .git/index.lock; returns the files it writes."""
    seen, pid = tmp_path / "lock-seen", tmp_path / "hook.pid"
    hook = seat / ".git/hooks/pre-commit"
    hook.write_text(f'#!/bin/sh\n[ -e "$GIT_DIR/index.lock" ] || [ -e .git/index.lock ] && echo held > {seen}\n'
                    f"echo $$ > {pid}\nexec sleep 30\n")
    hook.chmod(0o755)
    return seen, pid


def test_timed_out_git_releases_its_lock_and_reports_the_interruption(tmp_path, repo):
    import os
    import signal
    _, seat, _ = repo
    seen, pid = hold_index_lock_hook(seat, tmp_path)
    (seat / "data.txt").write_text("edited\n")
    try:
        with pytest.raises(SessionError) as error:
            git_ops.git(seat, "commit", "-m", "slow", "data.txt", timeout=2)
    finally:
        if pid.exists():
            try:
                os.kill(int(pid.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
    assert seen.exists(), "the hook must have run while Git held index.lock"
    assert not (seat / ".git/index.lock").exists()
    assert git_ops.index_lock(seat) is None
    err = error.value
    assert (err.code, err.exit_code) == ("git_failed", 5)
    assert err.details == {"operation": ["commit", "-m", "slow", "data.txt"], "timeout_seconds": 2,
                           "interrupted": "SIGTERM", "index_lock": None, "index_lock_left": False}
    assert "timed out after 2 s" in err.message and "SIGTERM" in err.message


def test_git_that_ignores_sigterm_is_killed_and_a_left_lock_is_reported(tmp_path, repo, monkeypatch):
    import shutil
    _, seat, _ = repo
    real = shutil.which("git")
    fake = tmp_path / "bin/git"
    fake.parent.mkdir()
    fake.write_text(f'#!/bin/sh\ncase "$*" in *rev-parse*) exec {real} "$@";; esac\ntrap "" TERM\nsleep 3\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake.parent}:/usr/bin:/bin")
    monkeypatch.setattr(git_ops, "TERM_GRACE", 0.5)
    (seat / ".git/index.lock").write_text("")
    with pytest.raises(SessionError) as error:
        git_ops.git(seat, "status", timeout=1)
    details = error.value.details
    assert details["interrupted"] == "SIGKILL"
    assert details["index_lock_left"] is True and details["index_lock"] == str(seat / ".git/index.lock")
    assert f"{seat / '.git/index.lock'} was left behind" in error.value.message


def test_left_index_lock_is_named_by_the_checks_and_the_preparation(tmp_path, repo, cr_bases):
    from agent_session import workspace
    source, seat, _ = repo
    lock = seat / ".git/index.lock"
    lock.write_text("")
    project = SimpleNamespace(base=source, seats=(seat,))
    reasons = workspace.check_seat(project, seat, {"branch": None})["reasons"]
    assert any("index.lock left by an interrupted Git command" in reason for reason in reasons)
    released = workspace.check_release(project, {"seat": 0, "seat_root": str(seat)}, ("done", "fixed"))
    assert released["allowed"] is False
    assert any("index.lock left by an interrupted Git command" in reason for reason in released["reasons"])
    context, store, prep_project = setup_job(tmp_path, seat)
    with pytest.raises(SessionError) as error:
        git_ops.prepare(context, prep_project, store)
    assert error.value.code == "workspace_dirty"
    assert str(lock) in error.value.message and "interrupted Git command" in error.value.message
    assert lock.exists()                                  # the tool never clears it
    assert cr_bases == []


def test_remote_preparation_runs_git_in_the_remote_tree_and_keeps_canonical_base(tmp_path, repo, cr_bases, monkeypatch):
    from pathlib import PurePosixPath
    from agent_session.config import RemoteSeat
    from agent_session import remote

    source, local_fixture, _ = repo
    expected = advance(source)
    seat = RemoteSeat("macbook-worker", PurePosixPath(str(tmp_path / "remote-seat")))
    context, store, project = setup_job(tmp_path, seat)
    calls = []
    local_git = git_ops.git

    def remote_git(target, operation, payload, timeout=120):
        assert target == seat
        calls.append((operation, payload))
        if operation == "is_git":
            return True
        if operation == "index_lock":
            return None
        assert operation == "git"
        return local_git(local_fixture, *payload["args"], timeout=timeout)

    monkeypatch.setattr(remote, "call", remote_git)
    baseline = git_ops.prepare(context, project, store)
    assert baseline["base_hash"] == expected
    assert cr_bases == [baseline]
    assert store.read()["0"]["git_hash"] == expected
    assert git(local_fixture, "branch", "--show-current") == "cr/TOOL-001"
    assert ("git", {"args": ["submodule", "update", "--init", "--recursive"]}) in calls
    assert not Path(str(seat)).exists()


@pytest.mark.parametrize("locked", [False, True])
def test_remote_lock_inspection_runs_on_the_remote_host(repo, monkeypatch, locked):
    from agent_session import remote, remote_runtime, workspace
    from agent_session.config import RemoteSeat

    source, fixture, _ = repo
    seat = RemoteSeat("macbook-worker", "/remote/seat")
    lock = fixture / ".git/index.lock"
    if locked:
        lock.write_text("")
    calls = []

    def dispatch(target, operation, payload, timeout=120):
        assert target == seat
        calls.append(operation)
        return remote_runtime.dispatch(str(fixture), operation, payload, None)

    monkeypatch.setattr(remote, "call", dispatch)
    assert git_ops.index_lock(seat) == (lock if locked else None)
    assert "index_lock" in calls
    project = SimpleNamespace(base=source, seats=(seat,))
    checked = workspace.check_seat(project, seat, {"branch": None})
    released = workspace.check_release(project, {"seat": 0, "seat_root": str(seat)}, ("done", "fixed"))
    for result in (checked, released):
        assert result["allowed"] is not locked
        assert any("index.lock left by an interrupted Git command" in reason
                   for reason in result["reasons"]) is locked
