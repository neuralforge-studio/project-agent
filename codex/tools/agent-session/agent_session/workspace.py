"""Seat creation and the common workspace and release checks (no project code)."""

import shutil
from pathlib import Path

from .config import RemoteSeat
from .errors import SessionError
from .git_ops import git, is_git, lock_reason


def _origin(root):
    return git(root, "remote", "get-url", "origin")


def ensure_seat(project, root):
    """Clone the base's origin into a missing seat. Git and SSH settings of the user apply as for
    any clone; the tool adds none."""
    if isinstance(root, RemoteSeat):
        from . import remote
        return remote.call(root, "ensure_seat", {"origin": _origin(project.base)}, timeout=3600)
    root = Path(root)
    if root.exists():
        return False
    if not is_git(project.base):
        raise SessionError("seat_unavailable", "Only a Git base can create a missing seat.", 2,
                           {"seat": str(root)})
    root.parent.mkdir(parents=True, exist_ok=True)
    # Claim only a new path, so failure cleanup cannot remove an existing seat.
    try:
        root.mkdir()
    except FileExistsError:
        return False
    phase = "clone"
    try:
        git(project.base, "clone", "--no-recurse-submodules", "--no-checkout", "--reference",
            str(project.base), "--dissociate", _origin(project.base), str(root), timeout=3600)
        phase = "checkout"
        git(root, "restore", "--source=HEAD", "--staged", "--worktree", ":/")
        phase = "verify"
        status = git(root, "status", "--porcelain", "--untracked-files=all")
        if status:
            raise SessionError("seat_dirty", "The new seat checkout is not clean.", 3,
                               {"status": status})
    except SessionError as error:
        details = {"seat": str(root), "phase": phase, "cause": error.as_dict()}
        try:
            shutil.rmtree(root)
        except OSError as cleanup_error:
            details["cleanup_error"] = str(cleanup_error)
            raise SessionError("seat_clone_failed", f"New seat {phase} failed: {error.message}; "
                               f"cleanup failed: {cleanup_error}", 5, details) from error
        raise SessionError("seat_clone_failed", f"New seat {phase} failed: {error.message}",
                           error.exit_code, details) from error
    return True


def _contained_in_origin(root, commit="HEAD"):
    """True when an origin ref contains the commit. Other remotes do not count."""
    return bool(git(root, "for-each-ref", "--contains", commit, "--format=%(refname)", "refs/remotes/origin/"))


def _status_reasons(root, reasons):
    locked = lock_reason(root)
    if locked:
        reasons.append(locked)
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        reasons.append("seat has uncommitted or untracked files")


def check_seat(project, root, job):
    """A seat may take the JOB when it is a clean clone of the same origin, its HEAD is
    published, and a local CR branch (if any) equals the published one."""
    root = root if isinstance(root, RemoteSeat) else Path(root)
    reasons = []
    try:
        if not is_git(root):
            return {"allowed": False, "reasons": ["seat is not a Git work tree"]}
        if _origin(root) != _origin(project.base):
            reasons.append("seat origin differs from the base")
        _status_reasons(root, reasons)
        if not _contained_in_origin(root):
            reasons.append("seat HEAD has commits that are not on origin")
        branch = job.get("branch")
        if branch and git(root, "branch", "--list", branch):
            remote = f"refs/remotes/origin/{branch}"
            try:
                published = git(root, "rev-parse", "--verify", remote)
            except SessionError:
                published = None
            if published != git(root, "rev-parse", branch):
                reasons.append(f"local {branch} differs from origin/{branch}")
    except SessionError as error:
        reasons.append(f"{error.code}: {error.message}")
    return {"allowed": not reasons, "reasons": reasons}


def check_release(project, meta, cr_state):
    """Release a Worker seat when its CR left in-progress and the seat keeps nothing local:
    a fixed CR is on origin/main; any other end keeps its HEAD on an origin ref."""
    if meta.get("seat") is None:
        return {"allowed": True, "reasons": []}
    state, outcome = cr_state
    seat = project.seats[meta["seat"]]
    root = seat if isinstance(seat, RemoteSeat) else Path(meta["seat_root"])
    reasons = []
    if state == "in-progress":
        reasons.append("the CR is still in-progress; move it to done, todo, open or deferred first")
    try:
        _status_reasons(root, reasons)
        if state == "done" and outcome == "fixed":
            git(root, "fetch", "--quiet", "origin", "main")
            try:
                git(root, "merge-base", "--is-ancestor", "HEAD", "refs/remotes/origin/main")
            except SessionError:
                reasons.append("the fixed result is not on origin/main")
        elif not _contained_in_origin(root):
            reasons.append("seat HEAD is not published on any origin ref")
    except SessionError as error:
        reasons.append(f"{error.code}: {error.message}")
    return {"allowed": not reasons, "reasons": reasons}
