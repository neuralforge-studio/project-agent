"""Prepare a job once and preserve its recorded Git baseline on retry."""

import datetime as dt
import subprocess
from pathlib import Path

from .errors import SessionError


def git(root, *args, timeout=120):
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
    return (Path(root) / ".git").exists()


def dirty(root):
    return git(root, "status", "--porcelain", "--untracked-files=all")


def sync_main(root):
    if dirty(root):
        raise SessionError("workspace_dirty", "Keep existing changes before preparing main.")
    git(root, "switch", "--no-overwrite-ignore", "main")
    git(root, "fetch", "origin", "main")
    git(root, "merge", "--ff-only", "--no-overwrite-ignore", "origin/main")


def prepare(context, adapter, store):
    root = Path(context["seat_root"])
    job = context["job"]
    seat = str(context["seat"])
    baseline = job.get("baseline")
    current_hash = store.read()[seat]["git_hash"]
    if not is_git(root):
        if baseline or current_hash:
            raise SessionError("baseline_mismatch", "A Git baseline exists for a non-Git seat.")
        adapter.record_baseline(context, None)
        return None
    if baseline:
        base_hash = baseline["base_hash"]
        if current_hash not in (None, base_hash):
            raise SessionError("baseline_mismatch", "JOB and state use different baselines.")
        git(root, "cat-file", "-e", f"{base_hash}^{{commit}}")
        if job["mode"] == "write":
            branch = job["branch"]
            existing = git(root, "branch", "--list", branch)
            head = git(root, "rev-parse", "HEAD")
            if not existing:
                if head != base_hash or dirty(root):
                    raise SessionError("baseline_mismatch", "Cannot resume JOB branch creation.")
                git(root, "switch", "--no-overwrite-ignore", "-c", branch, base_hash)
            if git(root, "branch", "--show-current") != branch:
                raise SessionError("branch_mismatch", "The seat is not on its JOB branch.")
            git(root, "merge-base", "--is-ancestor", base_hash, "HEAD")
        elif git(root, "rev-parse", "HEAD") != base_hash:
            raise SessionError("baseline_mismatch", "The read-only baseline has moved.")
        _save_hash(store, seat, job["job_id"], base_hash)
        adapter.record_baseline(context, baseline)
        return baseline

    if current_hash:
        raise SessionError("baseline_mismatch", "State has a baseline absent from its JOB.")
    policy = adapter.prepare_workspace(context, "before_sync") or {}
    if job["mode"] == "write" or policy.get("sync_main"):
        sync_main(root)
        adapter.prepare_workspace(context, "after_sync")
    base_hash = git(root, "rev-parse", "HEAD")
    baseline = {
        "base_hash": base_hash,
        "base_commit_time": git(root, "show", "-s", "--format=%cI", "HEAD"),
        "synced_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "branch": job["branch"] if job["mode"] == "write" else None,
    }
    adapter.record_baseline(context, baseline)
    _save_hash(store, seat, job["job_id"], base_hash)
    if job["mode"] == "write":
        git(root, "check-ref-format", "--branch", job["branch"])
        git(root, "switch", "--no-overwrite-ignore", "-c", job["branch"], base_hash)
        adapter.record_baseline(context, baseline)
    job["baseline"] = baseline
    return baseline


def _save_hash(store, seat, job_id, base_hash):
    def update(state):
        if state[seat]["job_id"] != job_id:
            raise SessionError("target_changed", "The seat's JOB changed during Git preparation.")
        if state[seat]["git_hash"] not in (None, base_hash):
            raise SessionError("baseline_mismatch", "The seat's Git baseline changed.")
        state[seat]["git_hash"] = base_hash
    store.update(update)
