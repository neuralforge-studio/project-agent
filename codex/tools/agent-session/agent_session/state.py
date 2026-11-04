"""Keep the per-project assignment file strict and atomically replaceable."""

from contextlib import contextmanager
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
import time

from .errors import SessionError


@contextmanager
def locked(path, timeout=600, blocking=True):
    """Acquire an OS lock. The lock file stays in place after release."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError as exc:
        raise SessionError("lock_unavailable", "Cannot open the command lock.", 5,
                           {"path": str(path)}) from exc
    deadline = time.monotonic() + max(0, timeout)
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EINTR):
                    raise SessionError("lock_unavailable", "Cannot acquire the command lock.", 5,
                                       {"path": str(path)}) from exc
                if not blocking:
                    raise SessionError("control_busy", "The target is controlled by another command.", 3,
                                       {"path": str(path)}) from None
                if time.monotonic() >= deadline:
                    raise SessionError("lock_timeout", "Timed out waiting for the command lock.", 4,
                                       {"path": str(path)}) from None
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        yield
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def empty_state(project):
    return {"leader": None, **{str(n): {"job_id": None, "git_hash": None, "session": None}
                               for n in range(len(project.seats))}}


def _session(value, provider):
    if value is None:
        return True
    fields = {"session_id", "message_to" if provider == "claude" else "endpoint"}
    return (isinstance(value, dict) and set(value) == fields
            and all(isinstance(item, str) and bool(item.strip()) for item in value.values()))


def validate_state(project, value):
    expected = {"leader", *(str(n) for n in range(len(project.seats)))}
    if not isinstance(value, dict) or set(value) != expected or not _session(value.get("leader"), project.provider):
        raise SessionError("state_invalid", "The state root or leader connection does not match the registry.")
    jobs = set()
    for n in range(len(project.seats)):
        row = value[str(n)]
        if not isinstance(row, dict) or set(row) != {"job_id", "git_hash", "session"}:
            raise SessionError("state_invalid", "A seat record has invalid fields.", details={"seat": n})
        job, git_hash, session = row["job_id"], row["git_hash"], row["session"]
        if job is not None and (not isinstance(job, str) or not job.strip() or job == "leader"):
            raise SessionError("state_invalid", "The seat JOB ID is invalid.", details={"seat": n})
        if git_hash is not None and (not isinstance(git_hash, str)
                                     or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", git_hash) is None):
            raise SessionError("state_invalid", "The seat Git hash must be a full commit hash.", details={"seat": n})
        if not _session(session, project.provider):
            raise SessionError("state_invalid", "The seat provider connection is invalid.", details={"seat": n})
        if job is None and (git_hash is not None or session is not None):
            raise SessionError("state_invalid", "An unassigned seat must not retain a Git hash or connection.",
                               details={"seat": n})
        if job is not None:
            if job in jobs:
                raise SessionError("state_invalid", "A JOB is assigned to more than one seat.", details={"job_id": job})
            jobs.add(job)
    return value


def _object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"Duplicate state key: {key}")
        out[key] = value
    return out


class StateStore:
    def __init__(self, project, timeout=600):
        self.project = project
        self.path = project.state_path
        self.lock_path = self.path.with_name("state.lock")
        self.timeout = timeout

    def _check_path(self):
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise SessionError("state_invalid", "The per-project state path must not be a symbolic link.")

    def read(self, missing_ok=False):
        """Read an atomic snapshot without creating files or taking a lock."""
        self._check_path()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"), object_pairs_hook=_object)
        except FileNotFoundError:
            if missing_ok:
                return empty_state(self.project)
            raise SessionError("state_not_found", "The project state has not been initialized.",
                               details={"path": str(self.path)}) from None
        except (OSError, UnicodeError, ValueError) as exc:
            raise SessionError("state_invalid", "Cannot read a valid project state. Preserve the file.",
                               details={"path": str(self.path), "reason": str(exc)}) from exc
        return validate_state(self.project, value)

    def update(self, mutator):
        """Merge one short mutation into the latest state and save it atomically."""
        self._check_path()
        with locked(self.lock_path, timeout=self.timeout):
            value = self.read(missing_ok=True)
            changed = mutator(value)
            if changed is not None:
                value = changed
            validate_state(self.project, value)
            temporary = None
            try:
                fd, temporary = tempfile.mkstemp(prefix=".state.", suffix=".tmp", dir=self.path.parent)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(value, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                temporary = None
                directory = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            except OSError as exc:
                raise SessionError("state_write_failed", "Cannot save the project state atomically.", 5,
                                   {"path": str(self.path)}) from exc
            finally:
                if temporary is not None:
                    Path(temporary).unlink(missing_ok=True)
            return value
