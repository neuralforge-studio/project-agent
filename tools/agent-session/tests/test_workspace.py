"""Check creation and recovery of Worker seats against a local Git origin."""

import subprocess
from types import SimpleNamespace

import pytest

from agent_session import workspace
from agent_session.errors import SessionError


def git(root, *args, allow_file=False):
    command = ["git"] + (["-c", "protocol.file.allow=always"] if allow_file else [])
    result = subprocess.run([*command, "-C", str(root), *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture
def project(tmp_path):
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin))
    source = tmp_path / "source"
    git(tmp_path, "clone", str(origin), str(source))
    git(source, "config", "user.name", "Fixture")
    git(source, "config", "user.email", "fixture@example.invalid")
    (source / "tracked.txt").write_text("seat contents\n")
    git(source, "add", "tracked.txt")
    git(source, "commit", "-m", "Add tracked content")
    git(source, "push", "origin", "main")
    base = tmp_path / "base"
    git(tmp_path, "clone", str(origin), str(base))
    return SimpleNamespace(base=base), origin


def test_new_seat_is_clean_and_independent(tmp_path, project):
    project, origin = project
    seat = tmp_path / "seats" / "seat-0"
    assert workspace.ensure_seat(project, seat) is True
    assert git(seat, "rev-parse", "HEAD") == git(origin, "rev-parse", "refs/heads/main")
    assert git(seat, "status", "--porcelain", "--untracked-files=all") == ""
    assert (seat / "tracked.txt").read_text() == "seat contents\n"
    assert not (seat / ".git" / "objects" / "info" / "alternates").exists()


def test_existing_seat_preserves_unfinished_changes(tmp_path, project):
    project, _ = project
    seat = tmp_path / "seat"
    git(tmp_path, "clone", git(project.base, "remote", "get-url", "origin"), str(seat))
    (seat / "tracked.txt").write_text("unfinished work\n")
    assert workspace.ensure_seat(project, seat) is False
    assert (seat / "tracked.txt").read_text() == "unfinished work\n"


def test_new_seat_defers_submodule_initialization(tmp_path, project):
    project, _ = project
    library = tmp_path / "library"
    git(tmp_path, "init", "--initial-branch=main", str(library))
    git(library, "config", "user.name", "Fixture")
    git(library, "config", "user.email", "fixture@example.invalid")
    (library / "module.txt").write_text("library contents\n")
    git(library, "add", "module.txt")
    git(library, "commit", "-m", "Add library content")
    git(project.base, "config", "user.name", "Fixture")  # the run's HOME has no global identity (TEST-014)
    git(project.base, "config", "user.email", "fixture@example.invalid")
    git(project.base, "submodule", "add", str(library), "external/library", allow_file=True)
    git(project.base, "commit", "-m", "Add library submodule")
    git(project.base, "push", "origin", "main")

    seat = tmp_path / "seat"
    assert workspace.ensure_seat(project, seat) is True
    assert git(seat, "submodule", "status").startswith("-")
    git(seat, "submodule", "update", "--init", "--recursive", allow_file=True)
    assert (seat / "external/library/module.txt").read_text() == "library contents\n"
    assert git(seat, "status", "--porcelain", "--untracked-files=all") == ""


@pytest.mark.parametrize("failure_phase", ["clone", "checkout", "verify"])
def test_failed_new_seat_reports_phase_and_can_retry(tmp_path, project, monkeypatch, failure_phase):
    project, origin = project
    seat = tmp_path / "seat"
    real_git = workspace.git
    failed = False

    def fail_once(root, *args, **kwargs):
        nonlocal failed
        if not failed and failure_phase == "verify" and args[:2] == ("status", "--porcelain"):
            failed = True
            return " D tracked.txt"
        if not failed and ((failure_phase == "clone" and args[0] == "clone") or
                           (failure_phase == "checkout" and args[0] == "restore")):
            failed = True
            if failure_phase == "clone":
                real_git(root, *args, **kwargs)
            raise SessionError("git_failed", "Injected Git failure.", 3,
                               {"operation": list(args), "returncode": 128})
        return real_git(root, *args, **kwargs)

    monkeypatch.setattr(workspace, "git", fail_once)
    with pytest.raises(SessionError) as error:
        workspace.ensure_seat(project, seat)
    assert error.value.code == "seat_clone_failed"
    assert error.value.details["phase"] == failure_phase
    assert error.value.details["cause"]["code"] == ("seat_dirty" if failure_phase == "verify" else "git_failed")
    if failure_phase == "verify":
        assert error.value.details["cause"]["details"]["status"] == " D tracked.txt"
    assert not seat.exists()
    assert workspace.ensure_seat(project, seat) is True
    assert git(seat, "rev-parse", "HEAD") == git(origin, "rev-parse", "refs/heads/main")
    assert git(seat, "status", "--porcelain", "--untracked-files=all") == ""


def test_ssh_loss_never_allows_remote_seat_release(project, monkeypatch):
    from pathlib import PurePosixPath
    from agent_session.config import RemoteSeat
    from agent_session import remote

    project, _ = project
    # The same path is a clean published local clone. Its facts cannot release a remote seat.
    seat = RemoteSeat("macbook-worker", PurePosixPath(str(project.base)))
    project.seats = (seat,)
    calls = []

    def disconnected(target, operation, payload, timeout=120):
        calls.append((target, operation))
        raise SessionError("remote_unavailable", "SSH transport disconnected.", 4)

    monkeypatch.setattr(remote, "call", disconnected)
    result = workspace.check_release(project, {"seat": 0, "seat_root": str(seat)}, ("done", "fixed"))
    assert result["allowed"] is False
    assert any("remote_unavailable" in reason for reason in result["reasons"])
    assert calls == [(seat, "index_lock")]


def test_remote_clone_uses_the_base_origin_without_a_local_reference(tmp_path, project, monkeypatch):
    from pathlib import PurePosixPath
    from agent_session.config import RemoteSeat
    from agent_session import remote

    project, origin = project
    seat = RemoteSeat("macbook-worker", PurePosixPath("/Users/worker/seat"))
    calls = []

    def create_remote(target, operation, payload, timeout=120):
        calls.append((target, operation, payload, timeout))
        return True

    monkeypatch.setattr(remote, "call", create_remote)
    assert workspace.ensure_seat(project, seat) is True
    assert calls == [(seat, "ensure_seat", {"origin": str(origin)}, 3600)]
