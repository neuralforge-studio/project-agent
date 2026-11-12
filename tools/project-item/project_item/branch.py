"""The `cr/<ID>` branch of an integrated Write CR: what `project-item move ... done --outcome fixed` and
`project-item drop-branch` do with it in the base repository.

The rule (when a branch goes, when it stays, what a failure leaves) is owned by
skills/project-item/references/cr.md, section "`cr/<ID>` branch의 수명". This module only runs it.
The seat side of the rule (a seat's local branches) is `agent_session.git_ops.prune_integrated`.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

GIT_TIMEOUT = 120      # seconds per Git command; the remote ones can wait on the network


class GitFailed(Exception):
    """A Git command failed or timed out; the message says which and why."""


def _git(base: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", str(base), *args], capture_output=True, text=True,
                              timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired as error:
        raise GitFailed(f"git {args[0]} timed out after {GIT_TIMEOUT} s") from error
    except OSError as error:
        raise GitFailed(str(error)) from error


def _run(base: Path, *args: str) -> str:
    result = _git(base, *args)
    if result.returncode:
        raise GitFailed(f"git {args[0]} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def fetch_main(base: Path) -> None:
    """Bring refs/remotes/origin/main of the base up to date."""
    _run(base, "fetch", "--quiet", "origin", "main")


def on_origin_main(base: Path, commit: str) -> bool:
    """True when refs/remotes/origin/main (as last fetched) holds the commit."""
    return _git(base, "merge-base", "--is-ancestor", commit, "refs/remotes/origin/main").returncode == 0


def _local(base: Path, branch: str) -> tuple[str, str | None]:
    """Delete the base's own `cr/<ID>` when it only holds commits of origin/main. Returns (status, reason)."""
    if not _run(base, "branch", "--list", branch):
        return "absent", None
    if not on_origin_main(base, f"refs/heads/{branch}"):
        return "kept", f"local {branch} has commits that are not on origin/main"
    result = _git(base, "branch", "-D", branch)      # the check above is the merge check; -d would test HEAD
    if result.returncode:
        return "kept", f"local {branch} was not deleted: {result.stderr.strip()}"
    return "deleted", None


def drop_integrated(base: Path, cr_id: str) -> dict:
    """Delete `origin`'s `cr/<ID>` of an integrated CR when its tip is on origin/main, and the base's own
    `cr/<ID>` likewise. Nothing is deleted on a failure to prove that.

    Returns {"branch", "remote", "local", "reasons"}. "remote" is one of:
      deleted  the branch was on origin and is gone
      absent   origin has no such branch
      kept     the tip has commits that origin/main lacks (a push after the accepted commit)
      failed   a Git command failed; "reasons" says which. The caller keeps the CR as it is and tells how to retry
    "local" is deleted, absent or kept, or None when origin/main could not be read."""
    branch = f"cr/{cr_id}"
    ref = f"refs/heads/{branch}"
    outcome = {"branch": branch, "remote": "failed", "local": None, "reasons": []}
    try:
        fetch_main(base)
        listed = _run(base, "ls-remote", "--heads", "origin", ref)
        if not listed:
            outcome["remote"] = "absent"
        else:
            tip = listed.split()[0]
            _run(base, "fetch", "--quiet", "origin", f"+{ref}:refs/remotes/origin/{branch}")
            if not on_origin_main(base, tip):
                outcome["remote"] = "kept"
                outcome["reasons"].append(f"origin/{branch} ({tip}) has commits that are not on origin/main; "
                                          "it is kept")
            else:
                # The lease makes the delete refuse when someone pushed after the check above.
                _run(base, "push", "--quiet", f"--force-with-lease={ref}:{tip}", "origin", f":{ref}")
                outcome["remote"] = "deleted"
    except GitFailed as error:
        outcome["reasons"].append(str(error))
        return outcome
    try:
        outcome["local"], reason = _local(base, branch)
    except GitFailed as error:
        outcome["local"], reason = "kept", str(error)
    if reason:
        outcome["reasons"].append(reason)
    return outcome
