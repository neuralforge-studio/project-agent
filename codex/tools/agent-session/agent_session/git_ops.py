"""Git preparation of a CR assignment and its retries (see prepare)."""

import subprocess
from pathlib import Path

from .config import RemoteSeat
from .errors import SessionError


def git(root, *args, timeout=120):
    if isinstance(root, RemoteSeat):
        from . import remote
        return remote.call(root, "git", {"args": list(args)}, timeout=timeout)
    try:
        result = subprocess.run(
            ["git", "-c", "submodule.recurse=false", "-C", str(root), *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SessionError("git_failed", str(exc), 5) from exc
    if result.returncode:
        raise SessionError("git_failed", result.stderr.strip() or result.stdout.strip(), 3,
                           {"operation": list(args), "returncode": result.returncode})
    return result.stdout.strip()


def is_git(root):
    if isinstance(root, RemoteSeat):
        from . import remote
        return remote.call(root, "is_git", {})
    return (Path(root) / ".git").exists()


def dirty(root):
    return git(root, "status", "--porcelain", "--untracked-files=all")


def sync_main(root):
    if dirty(root):
        raise SessionError("workspace_dirty", "Keep existing changes before preparing main.")
    git(root, "switch", "--no-overwrite-ignore", "main")
    git(root, "fetch", "origin", "main")
    git(root, "merge", "--ff-only", "--no-overwrite-ignore", "origin/main")


def _baseline(root):
    return {"base_hash": git(root, "rev-parse", "HEAD"),
            "base_commit_time": git(root, "show", "-s", "--format=%cI", "HEAD")}


def _first(context, project, store, root):
    """First preparation: latest main, Base, CR branch."""
    from . import jobs
    job = context["job"]
    sync_main(root)
    baseline = _baseline(root)
    _save_hash(store, str(context["seat"]), job["job_id"], baseline["base_hash"])
    jobs.set_base(project, job["job_id"], baseline)
    if job["mode"] == "write":
        git(root, "check-ref-format", "--branch", job["branch"])
        git(root, "switch", "--no-overwrite-ignore", "-c", job["branch"], baseline["base_hash"])
    return baseline


def _is_ancestor(root, ancestor, descendant):
    try:
        git(root, "merge-base", "--is-ancestor", ancestor, descendant)
    except SessionError as error:
        if error.code == "git_failed" and error.details.get("returncode") == 1:
            return False
        raise
    return True


def _resume_branch(root, job, base_hash, published_first):
    """Switch to the CR branch: the published branch on a new assignment, else the local one, else
    create it from Base when HEAD is still the clean Base."""
    branch = job["branch"]
    remote = None
    if published_first:
        # A Base recorded by a read-only assignment may not exist in this seat yet.
        try:
            git(root, "cat-file", "-e", f"{base_hash}^{{commit}}")
        except SessionError:
            git(root, "fetch", "--quiet", "origin", timeout=600)
            git(root, "cat-file", "-e", f"{base_hash}^{{commit}}")
        try:
            git(root, "fetch", "--quiet", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}", timeout=600)
            remote = git(root, "rev-parse", "--verify", f"refs/remotes/origin/{branch}")
        except SessionError:
            remote = None
    if git(root, "branch", "--list", branch):
        local = git(root, "rev-parse", branch)
        if remote and local != remote:
            # A fast-forward may have completed before its state write failed.
            if local != base_hash or not _is_ancestor(root, remote, base_hash):
                raise SessionError("branch_mismatch", f"Local {branch} differs from origin/{branch}.")
        git(root, "switch", "--no-overwrite-ignore", branch)
    elif remote:
        git(root, "switch", "--no-overwrite-ignore", "-c", branch, f"refs/remotes/origin/{branch}")
    else:
        if dirty(root):
            raise SessionError("baseline_mismatch", "Cannot create the CR branch over local changes.")
        git(root, "fetch", "--quiet", "origin", timeout=600)
        git(root, "cat-file", "-e", f"{base_hash}^{{commit}}")
        git(root, "switch", "--no-overwrite-ignore", "-c", branch, base_hash)
    if published_first and _is_ancestor(root, "HEAD", base_hash):
        git(root, "merge", "--ff-only", "--no-overwrite-ignore", base_hash)
    git(root, "merge-base", "--is-ancestor", base_hash, "HEAD")


def prepare(context, project, store):
    """Prepare the seat's Git state, then align its submodules with the HEAD gitlinks."""
    baseline = _prepare_git(context, project, store)
    git(_root(context, project), "submodule", "update", "--init", "--recursive", timeout=600)
    return baseline


def _root(context, project):
    seat = project.seats[context["seat"]]
    return seat if isinstance(seat, RemoteSeat) else Path(context["seat_root"])


def _prepare_git(context, project, store):
    """Git preparation of a Worker seat. The CR Base header is the preparation record:

    - no Base: first preparation (latest main, Base, branch)
    - Base and the same assignment in state: retry; keep Base and branch, never sync main again
    - Base and a new assignment (parked CR assigned again): write continues the published
      cr/<ID> branch from Base; read-only prepares again from the latest main
    """
    from . import jobs
    root = _root(context, project)
    job = context["job"]
    seat = str(context["seat"])
    if not is_git(root):
        raise SessionError("seat_unavailable", "A Worker seat must be a Git work tree.", 2)
    state_hash = store.read()[seat]["git_hash"]
    base = job.get("base")
    if base is None and state_hash:
        base = {"base_hash": state_hash, "base_commit_time": git(root, "show", "-s", "--format=%cI", state_hash)}
        jobs.set_base(project, job["job_id"], base)       # the CR write was lost after the state write
    if (base is not None and state_hash and state_hash != base["base_hash"] and job["mode"] == "read-only"
            and git(root, "rev-parse", "HEAD") == state_hash):
        # A read-only preparation wrote the new Base to the state and lost the CR write.
        base = {"base_hash": state_hash, "base_commit_time": git(root, "show", "-s", "--format=%cI", state_hash)}
        jobs.set_base(project, job["job_id"], base)
    if base is None:
        baseline = _first(context, project, store, root)
    elif state_hash is None and job["mode"] == "read-only":
        baseline = _first(context, project, store, root)
    else:
        if state_hash not in (None, base["base_hash"]):
            raise SessionError("baseline_mismatch", "The CR Base differs from the seat's recorded baseline.")
        if job["mode"] == "write":
            _resume_branch(root, job, base["base_hash"], published_first=state_hash is None)
        elif git(root, "rev-parse", "HEAD") != base["base_hash"]:
            raise SessionError("baseline_mismatch", "The read-only baseline has moved.")
        _save_hash(store, seat, job["job_id"], base["base_hash"])
        baseline = base
    job["base"] = baseline
    return baseline


def _save_hash(store, seat, job_id, base_hash):
    def update(state):
        if state[seat]["job_id"] != job_id:
            raise SessionError("target_changed", "The seat's JOB changed during Git preparation.")
        if state[seat]["git_hash"] not in (None, base_hash):
            raise SessionError("baseline_mismatch", "The seat's Git baseline changed.")
        state[seat]["git_hash"] = base_hash
    store.update(update)
