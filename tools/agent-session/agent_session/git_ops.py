"""Git preparation of a CR assignment and its retries (see prepare)."""

import contextlib
import contextvars
import subprocess
from pathlib import Path

from .config import RemoteSeat
from .errors import SessionError


GIT_TIMEOUT = 600      # merge, checkout, status and fetch alike: seats are large NFS work trees
TERM_GRACE = 10        # seconds a timed-out Git gets to release its locks after SIGTERM


def _argv(root, *args):
    return ["git", "-c", "submodule.recurse=false", "-C", str(root), *args]


def _interrupt(proc):
    """Stop a timed-out Git. SIGTERM lets it remove its own lock files; SIGKILL only if it stays."""
    proc.terminate()
    try:
        proc.wait(TERM_GRACE)
        return "SIGTERM"
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return "SIGKILL"


def index_lock(root):
    """Path of the seat's index.lock when it exists, else None."""
    if isinstance(root, RemoteSeat):
        from . import remote
        found = remote.call(root, "index_lock", {})
        return Path(found) if found else None
    try:
        found = subprocess.run(_argv(root, "rev-parse", "--git-path", "index.lock"),
                               capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if found.returncode or not found.stdout.strip():
        return None
    path = Path(root) / found.stdout.strip()
    return path if path.exists() else None


def lock_reason(root):
    """Why a seat is unusable when an interrupted Git command left index.lock, else None."""
    path = index_lock(root)
    if path is None:
        return None
    return (f"seat has {path} left by an interrupted Git command; "
            "clear it by the operator procedure for interrupted Git steps (spec section 7)")


_steps = contextvars.ContextVar("git_steps", default=None)


@contextlib.contextmanager
def observing(observer):
    """Run `observer(args)` before each Git command of the calling thread; it returns a context manager
    that wraps the command. A caller with a deadline refuses the next step there: a Git command that has
    started is never cut short by it (that would leave a half-applied work tree)."""
    token = _steps.set(observer)
    try:
        yield
    finally:
        _steps.reset(token)


def git(root, *args, timeout=GIT_TIMEOUT):
    observer = _steps.get()
    with observer(args) if observer else contextlib.nullcontext():
        return _git(root, args, timeout)


def _git(root, args, timeout):
    if isinstance(root, RemoteSeat):
        from . import remote
        return remote.call(root, "git", {"args": list(args)}, timeout=timeout)
    try:
        proc = subprocess.Popen(_argv(root, *args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError as exc:
        raise SessionError("git_failed", str(exc), 5) from exc
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        interrupted = _interrupt(proc)
        proc.stdout.close()
        proc.stderr.close()
        lock = index_lock(root)
        message = (f"git {' '.join(args)} timed out after {timeout} s and was stopped with {interrupted}; "
                   "its work tree may be half applied")
        if lock:
            message += f"; {lock} was left behind"
        raise SessionError("git_failed", message, 5,
                           {"operation": list(args), "timeout_seconds": timeout, "interrupted": interrupted,
                            "index_lock": str(lock) if lock else None, "index_lock_left": lock is not None}) from exc
    if proc.returncode:
        raise SessionError("git_failed", err.strip() or out.strip(), 3,
                           {"operation": list(args), "returncode": proc.returncode})
    return out.strip()


def is_git(root):
    if isinstance(root, RemoteSeat):
        from . import remote
        return remote.call(root, "is_git", {})
    return (Path(root) / ".git").exists()


ALIGNED_REF = "refs/agent-session/aligned"


def _aligned(root):
    """The commit whose submodule gitlinks the seat's submodules are aligned to while a preparation is
    unfinished, else None."""
    return git(root, "for-each-ref", "--format=%(objectname)", ALIGNED_REF) or None


def _begin(root):
    """Start of a preparation: record the HEAD the seat is aligned to, unless an unfinished one already did.

    The preparation switches HEAD and aligns the submodules afterwards (`submodule update`). A preparation
    that ends in between (a start timeout) leaves submodules at this commit's gitlinks while HEAD points at
    others. The record is how `dirty` tells that trace from a person moving a submodule: the submodule must
    still be exactly at this commit's gitlink."""
    if _aligned(root) is None:
        git(root, "update-ref", ALIGNED_REF, "HEAD")


def _finish(root):
    git(root, "update-ref", "-d", ALIGNED_REF)


def _left_by_preparation(root, entry):
    """True for an unstaged change of a submodule that differs only by its checked-out commit, where
    that commit is the one the unfinished preparation left (its recorded commit's gitlink)."""
    fields = entry.split(" ", 8)
    if len(fields) < 9 or fields[0] != "1" or fields[1] != ".M" or fields[2] != "SC..":
        return False
    aligned = _aligned(root)
    if aligned is None:
        return False
    path = fields[8]
    recorded = git(root, "ls-tree", "-z", aligned, "--", path).split("\t")[0].split(" ")
    if recorded[:2] != ["160000", "commit"]:
        return False
    return git(root, "-C", path, "rev-parse", "HEAD") == recorded[2]


def dirty(root):
    """The seat's changes that are not the trace of an unfinished preparation, one per line; empty when clean.

    The one definition of "the seat has changes" (preparation, assignment and release checks). A submodule
    left at its old commit by a preparation that ended before `submodule update` is not a change."""
    entries = git(root, "status", "--porcelain=v2", "-z", "--untracked-files=all").split("\0")
    return "\n".join(entry for entry in entries if entry and not _left_by_preparation(root, entry))


def sync_main(root):
    """Bring the seat to the latest origin/main and leave HEAD detached on it, with local main there too.

    A work tree update costs a walk of every file (a large NFS seat takes minutes per walk), so this does
    exactly one: the detached switch. It is also the only guard against overwriting ignored files. Everything
    else is a ref update. `merge --ff-only` semantics are kept: local main may only move forward."""
    if dirty(root):
        raise SessionError("workspace_dirty", "Keep existing changes before preparing main.")
    git(root, "fetch", "origin", "main")
    upstream = git(root, "rev-parse", "--verify", "refs/remotes/origin/main^{commit}")
    # A seat without a local main gets one from origin/main, tracking it, as `switch main` did.
    tip = git(root, "rev-parse", "--verify", "refs/heads/main^{commit}") if git(root, "branch", "--list", "main") else None
    if tip is None or _is_ancestor(root, tip, upstream):
        target = upstream
    elif _is_ancestor(root, upstream, tip):
        target = tip                       # already up to date (or ahead): nothing to fast-forward
    else:
        raise SessionError("git_failed", "Not possible to fast-forward main to origin/main.", 3,
                           {"operation": ["merge", "--ff-only", "origin/main"], "returncode": 128})
    git(root, "switch", "--quiet", "--no-overwrite-ignore", "--detach", target)
    if tip is None:
        git(root, "branch", "--track", "main", "refs/remotes/origin/main")
    elif target != tip:
        git(root, "branch", "--force", "main", target)


def _attach(root, branch):
    """Put HEAD on `branch`, which is at HEAD's commit: the tree and index already match, so no walk."""
    git(root, "symbolic-ref", "HEAD", f"refs/heads/{branch}")


def _baseline(root):
    return {"base_hash": git(root, "rev-parse", "HEAD"),
            "base_commit_time": git(root, "show", "-s", "--format=%cI", "HEAD")}


def _first(context, project, store, root):
    """First preparation: latest main, Base, CR branch."""
    from . import jobs
    job = context["job"]
    sync_main(root)
    if job["mode"] == "read-only":
        _attach(root, "main")
    baseline = _baseline(root)
    _save_hash(store, str(context["seat"]), job["job_id"], baseline["base_hash"])
    jobs.set_base(project, job["job_id"], baseline)
    if job["mode"] == "write":
        git(root, "check-ref-format", "--branch", job["branch"])
        git(root, "branch", job["branch"], baseline["base_hash"])
        _attach(root, job["branch"])
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
            git(root, "fetch", "--quiet", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
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
        git(root, "fetch", "--quiet", "origin")
        git(root, "cat-file", "-e", f"{base_hash}^{{commit}}")
        git(root, "switch", "--no-overwrite-ignore", "-c", branch, base_hash)
    if published_first and _is_ancestor(root, "HEAD", base_hash):
        git(root, "merge", "--ff-only", "--no-overwrite-ignore", base_hash)
    git(root, "merge-base", "--is-ancestor", base_hash, "HEAD")


def prepare(context, project, store):
    """Prepare the seat's Git state, then align its submodules with the HEAD gitlinks."""
    baseline = _prepare_git(context, project, store)
    root = _root(context, project)
    git(root, "submodule", "update", "--init", "--recursive")
    _finish(root)
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
    locked = lock_reason(root)
    if locked:
        raise SessionError("workspace_dirty", locked, 3, {"index_lock": str(index_lock(root))})
    _begin(root)
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
