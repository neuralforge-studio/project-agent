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


class Adapter:
    def __init__(self, sync=False):
        self.sync = sync
        self.records = []

    def prepare_workspace(self, context, phase):
        return {"sync_main": self.sync}

    def record_baseline(self, context, baseline):
        self.records.append(baseline)
        context["job"]["baseline"] = baseline


def setup_job(tmp_path, seat, mode="write"):
    base = tmp_path / "base"
    base.mkdir()
    project = SimpleNamespace(base=base, provider="codex", seats=(seat,),
                              state_path=base / "agent/state.json", runtime_path=base / "agent")
    store = StateStore(project)
    job = {"job_id": "J-20261103-01", "mode": mode,
           "branch": "job/J-20261103-01" if mode == "write" else None, "baseline": None}
    store.update(lambda state: state["0"].update(job_id=job["job_id"]))
    context = {"seat": 0, "seat_root": str(seat), "job": job}
    return context, store


def advance(source, text="upstream\n"):
    (source / "data.txt").write_text(text)
    git(source, "add", "data.txt")
    git(source, "commit", "-m", "Update upstream data")
    git(source, "push", "origin", "main")
    return git(source, "rev-parse", "HEAD")


def test_first_preparation_records_synced_revision_and_job_branch(tmp_path, repo):
    source, seat, _ = repo
    expected = advance(source)
    context, store = setup_job(tmp_path, seat)
    adapter = Adapter()
    baseline = git_ops.prepare(context, adapter, store)
    assert baseline["base_hash"] == expected
    assert baseline["base_commit_time"] == git(source, "show", "-s", "--format=%cI", expected)
    assert store.read()["0"]["git_hash"] == expected
    assert git(seat, "branch", "--show-current") == context["job"]["branch"]
    assert adapter.records == [baseline, baseline]


def test_retry_preserves_baseline_and_unfinished_work(tmp_path, repo):
    source, seat, expected = repo
    context, store = setup_job(tmp_path, seat)
    adapter = Adapter()
    first = git_ops.prepare(context, adapter, store)
    advance(source)
    (seat / "data.txt").write_text("unfinished local work\n")
    assert git_ops.prepare(context, adapter, store) == first
    assert store.read()["0"]["git_hash"] == expected
    assert (seat / "data.txt").read_text() == "unfinished local work\n"
    assert git(seat, "rev-parse", "HEAD") == expected


@pytest.mark.parametrize("sync", [False, True])
def test_readonly_policy_has_no_job_branch(tmp_path, repo, sync):
    source, seat, initial = repo
    updated = advance(source)
    context, store = setup_job(tmp_path, seat, "read-only")
    expected = updated if sync else initial
    baseline = git_ops.prepare(context, Adapter(sync), store)
    assert baseline["base_hash"] == expected
    assert baseline["branch"] is None
    assert git(seat, "branch", "--show-current") == "main"
    assert store.read()["0"]["git_hash"] == expected


def test_non_git_seat_does_not_invoke_git(tmp_path, monkeypatch):
    seat = tmp_path / "plain"
    seat.mkdir()
    context, store = setup_job(tmp_path, seat)
    adapter = Adapter()
    def forbidden(*args, **kwargs):
        pytest.fail("Git must not run for a non-Git seat")
    monkeypatch.setattr(git_ops, "git", forbidden)
    assert git_ops.prepare(context, adapter, store) is None
    assert adapter.records == [None]
    assert store.read()["0"]["git_hash"] is None


def test_retry_recovers_domain_baseline_before_state_write(tmp_path, repo, monkeypatch):
    source, seat, initial = repo
    context, store = setup_job(tmp_path, seat)
    adapter = Adapter()
    original = store.update
    def failure(mutator):
        raise SessionError("fixture_write_failure", "State write failed.", 5)
    monkeypatch.setattr(store, "update", failure)
    with pytest.raises(SessionError, match="State write failed"):
        git_ops.prepare(context, adapter, store)
    assert context["job"]["baseline"]["base_hash"] == initial
    advance(source)
    monkeypatch.setattr(store, "update", original)
    git_ops.prepare(context, adapter, store)
    assert git(seat, "rev-parse", "HEAD") == initial
    assert store.read()["0"]["git_hash"] == initial


@pytest.mark.parametrize("collision", ["local-main", "remote-main"])
def test_initializer_preserves_ignored_file_collision(tmp_path, repo, collision):
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
    context, store = setup_job(tmp_path, seat)
    adapter = Adapter()
    with pytest.raises(SessionError):
        git_ops.prepare(context, adapter, store)
    assert (seat / "private.txt").read_text() == "preserve this ignored user file\n"
    assert git(seat, "rev-parse", "HEAD") == initial
    assert store.read()["0"]["git_hash"] is None
    assert adapter.records == []
