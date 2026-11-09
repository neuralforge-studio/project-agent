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
from .tmux import check_owner


class FileLock:
    """An OS lock on a file that stays in place after release.

    `with` holds it for the block. `release` and `acquire` let a holder step out while it waits for
    another process to act under the same lock; `release` of a lock that is not held does nothing."""

    def __init__(self, path, timeout=600, blocking=True):
        self.path = Path(path)
        self.timeout = timeout
        self.blocking = blocking
        self._fd = None

    def acquire(self, timeout=None, blocking=None):
        timeout = self.timeout if timeout is None else timeout
        blocking = self.blocking if blocking is None else blocking
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except OSError as exc:
            raise SessionError("lock_unavailable", "Cannot open the command lock.", 5,
                               {"path": str(self.path)}) from exc
        deadline = time.monotonic() + max(0, timeout)
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EINTR):
                        raise SessionError("lock_unavailable", "Cannot acquire the command lock.", 5,
                                           {"path": str(self.path)}) from exc
                    if not blocking:
                        raise SessionError("control_busy", "The target is controlled by another command.", 3,
                                           {"path": str(self.path)}) from None
                    if time.monotonic() >= deadline:
                        raise SessionError("lock_timeout", "Timed out waiting for the command lock.", 4,
                                           {"path": str(self.path)}) from None
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd

    def release(self):
        if self._fd is not None:
            fd, self._fd = self._fd, None
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    @property
    def held(self):
        return self._fd is not None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc_info):
        self.release()


def locked(path, timeout=600, blocking=True):
    """Acquire an OS lock. The lock file stays in place after release."""
    return FileLock(path, timeout, blocking)


def control_lock(project, slot, timeout=600, blocking=True):
    """The target control lock of a slot (`leader` or `seat-N`): the one place that names its file."""
    return locked(project.runtime_path / "control" / f"{slot}.lock", timeout, blocking)


def empty_state(project):
    return {"leader": None, **{str(n): {"job_id": None, "git_hash": None, "session": None}
                               for n in range(len(project.seats))}}


_CONNECTED_AT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def utc_now():
    """The connection time format: UTC, whole seconds."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def bound(previous, session, leader=False):
    """A republished conversation keeps its connection time and review; a new one starts both."""
    if previous and previous.get("session_id") == session["session_id"]:
        return {**previous, **session}
    fresh = {**session, "connected_at": utc_now()}
    if leader:
        fresh["reviewing"] = None
    return fresh


_RUN_IDENTITY = ("run_id", "window_id", "pane_id", "job_id", "remote_seat", "remote_native")


def _slot_session(value, slot):
    return value["leader"] if slot == "leader" else value[slot[len("seat-"):]]["session"]


def _current_run(project, tmux, meta):
    """The slot's current run when it is still `meta`'s run, JOB, window and pane and this project's, else None."""
    current = tmux.get_current(project.project_id, meta["target"])
    if not current or any(current.get(key) != meta.get(key) for key in _RUN_IDENTITY):
        return None
    check_owner(project, meta["target"], None, current)
    return current


def _finished(run_id, session):
    """The window options of a finished publication, written in one tmux update."""
    return {"run_id": run_id, "session_id": session["session_id"], "registered": True,
            **({"message_to": session["message_to"]} if "message_to" in session else {}),
            "publishing": None, "ready": True, "start_error": None}


def publish_session(project, tmux, store, meta, session):
    """Publish a run's connection: the one writer of a local run's state session.

    The caller holds the target control lock. The slot's current run must still be `meta`'s run, JOB,
    window and pane, and this project's; otherwise `target_changed` and nothing is written. Steps: the
    window records what it will publish (`publishing`); the state write is the commit; the window then
    becomes registered and ready in one update. A failure before the commit publishes nothing. A failure
    after it puts the slot's previous session back, under the same lock, so a failed publication leaves
    nothing published. A process that ends between the commit and the window update leaves the intent and
    the committed state for `complete_publication`."""
    slot = meta["target"]
    current = _current_run(project, tmux, meta)
    if current is None:
        raise SessionError("target_changed", "The run is no longer the slot's current execution.")
    window, run_id = current["window_id"], current["run_id"]
    before = []
    written = []

    def commit(value):
        if slot == "leader":
            before.append(value["leader"])
            value["leader"] = bound(value["leader"], session, leader=True)
            written.append(value["leader"])
        else:
            row = value[slot[len("seat-"):]]
            if row["job_id"] != current["job_id"]:
                raise SessionError("target_changed", "The JOB changed before binding publication.")
            before.append(row["session"])
            row["session"] = bound(row["session"], session)
            written.append(row["session"])

    def put_back(value):
        if _slot_session(value, slot) == written[0]:
            if slot == "leader":
                value["leader"] = before[0]
            else:
                value[slot[len("seat-"):]]["session"] = before[0]

    tmux.write_meta(window, {"run_id": run_id, "publishing": session})
    try:
        store.update(commit)
    except BaseException:
        _clear_intent(tmux, window, run_id)
        raise
    try:
        return tmux.write_meta(window, _finished(run_id, session))
    except BaseException:
        try:
            store.timeout = max(store.timeout, 3)
            store.update(put_back)
            _clear_intent(tmux, window, run_id)
        except SessionError:
            pass                                   # the intent stays: the committed state is finished later
        raise


def _clear_intent(tmux, window, run_id):
    try:
        tmux.write_meta(window, {"run_id": run_id, "publishing": None})
    except SessionError:
        pass                                       # the original error is the one to report


def complete_publication(project, tmux, store, meta):
    """Finish the window update of a publication whose state write committed; the caller holds the lock.

    Only for a run that is the slot's current run, is not ready, and whose `publishing` session is what the
    state names for the slot. It decides nothing new: the commit was made by the registration. Returns the
    window metadata after the update, or None when the run has nothing to finish."""
    current = _current_run(project, tmux, meta)
    intent = current and current.get("publishing")
    if not isinstance(intent, dict) or current.get("ready"):
        return None
    session = _slot_session(store.read(missing_ok=True), meta["target"])
    if not session or any(session.get(key) != value for key, value in intent.items()):
        return None
    return tmux.write_meta(current["window_id"], _finished(current["run_id"], intent))


def binding_identity(session, provider):
    """The fields that name one native connection; other session fields may change in place."""
    if session is None:
        return None
    if provider == "claude":
        return (session["session_id"],)
    return (session["session_id"], session["endpoint"])


def select_target(state, target):
    """The (seat number or None, session) a --job target names: "leader" or the seat holding that JOB."""
    if target == "leader":
        return None, state["leader"]
    matches = [int(key) for key, item in state.items()
               if key != "leader" and item["job_id"] == target]
    if len(matches) != 1:
        raise SessionError("job_not_assigned", "JOB has no unique current seat.")
    seat = matches[0]
    return seat, state[str(seat)]["session"]


def _connected_at(value):
    if not isinstance(value, str) or _CONNECTED_AT.fullmatch(value) is None:
        return False
    try:
        time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _session(value, provider, leader=False):
    """A connection has exact transport fields; connected_at and the Leader's reviewing are optional."""
    if value is None:
        return True
    if not isinstance(value, dict):
        return False
    fields = {"session_id", "message_to" if provider == "claude" else "endpoint"}
    optional = {"connected_at", "reviewing"} if leader else {"connected_at"}
    if not fields <= set(value) or not set(value) <= fields | optional:
        return False
    if not all(isinstance(value[key], str) and bool(value[key].strip()) for key in fields):
        return False
    if "connected_at" in value and not _connected_at(value["connected_at"]):
        return False
    reviewing = value.get("reviewing")
    return reviewing is None or (isinstance(reviewing, str) and bool(reviewing.strip()) and reviewing != "leader")


def _unassigned(row):
    return row == {"job_id": None, "git_hash": None, "session": None}


def _fit_seats(project, value):
    """Fit the seat rows to the registry: add missing rows as unassigned, drop only unassigned extra rows."""
    if not isinstance(value, dict) or "leader" not in value:
        raise SessionError("state_invalid", "The state root or leader connection does not match the registry.")
    count = len(value) - 1
    if set(value) != {"leader", *(str(n) for n in range(count))}:
        raise SessionError("state_invalid", "The state seat keys must be consecutive numbers from 0.")
    wanted = len(project.seats)
    for n in range(wanted, count):
        if not _unassigned(value[str(n)]):
            raise SessionError("state_invalid", "A seat removed from the registry is still assigned.",
                               details={"seat": n})
    return {"leader": value["leader"],
            **{str(n): value[str(n)] if n < count else {"job_id": None, "git_hash": None, "session": None}
               for n in range(wanted)}}


def validate_state(project, value):
    """Return the state fitted to the registered seat count; the input is not changed."""
    value = _fit_seats(project, value)
    if not _session(value["leader"], project.provider, leader=True):
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
    reviewing = (value["leader"] or {}).get("reviewing")
    if reviewing is not None and reviewing not in jobs:
        raise SessionError("state_invalid", "The Leader reviews a JOB that no seat holds.",
                           details={"job_id": reviewing})
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
            value = validate_state(self.project, value)
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
