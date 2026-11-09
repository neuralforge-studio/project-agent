"""Project session commands, Git preparation, and confirmed slot release."""

from contextlib import contextmanager
import datetime
import os
import shlex
import sys
import time
import uuid
from pathlib import Path

from . import api, background, ended, git_ops, handoff, jobs, launch_artifacts, process, windows, workspace
from .config import RemoteSeat, current_project, load_registry
from .errors import SessionError
from .providers import get_provider
from .state import StateStore, complete_publication, control_lock, locked, publish_session
from .suspend import SuspendMixin, SuspendStore
from .watch import WatchMixin
from .tmux import Tmux, check_owner
from .util import write_json

HOST_SECONDS = 8                                   # wait for the provider's background listing
DIALOG_SCREEN_SECONDS = 1                          # how often an unregistered start reads its pane for a dialog
REGAIN_SECONDS = 5                                 # wait to take the control lock again after waiting for a registration
FINISH_LOCK_SECONDS = 5                            # a run that ended itself waits this long for a busy control lock
FINISH_END_SECONDS = 15                            # and this long for its process group to drain before it is not confirmed
PARKED_ALIVE = "The parked JOB still has a run; stop it before starting the JOB again."


def _unregistered_ended(meta, pane):
    """A run that tried to launch its CLI but never registered, whose CLI is confirmed gone.

    The pane is dead and the recorded CLI process (PID and birth) no longer runs. A run without those
    records, or one that never attempted a launch, is not confirmed."""
    return (not meta.get("registered") and meta.get("provider_launch_attempted") is not False
            and not meta.get("remote_seat") and background.cli_state(meta, pane) == "ended")


def check_start_arguments(job, prompt_file=None, seat=None):
    """The start rules that need no project: a prompt file is for the Leader, a seat for a Worker JOB.

    The one owner of these two rules. `Manager.start` applies them, and the CLI applies them before it
    builds a Manager, so a bad request gets the same error whether or not the project resolves."""
    leader = job == "leader"
    if prompt_file is not None and not leader:
        raise SessionError("invalid_arguments", "--prompt-file is only valid for --job leader.", 2)
    if leader and seat is not None:
        raise SessionError("invalid_arguments", "--seat is only valid for a Worker JOB.", 2)


class Manager(SuspendMixin, WatchMixin):
    def __init__(self, cwd=None, config_path=None, socket_name=None, socket_path=None, timeout=600):
        self.project = current_project(cwd, config_path)
        self.timeout = timeout
        self.end = time.monotonic() + timeout
        self.store = StateStore(self.project, timeout=timeout)
        self.socket = {"socket_name": socket_name, "socket_path": socket_path}
        self.tmux = Tmux(**self.socket)
        self.provider = get_provider(self.project.provider)
        self._held = {}                            # slot -> the control lock this command holds

    def remaining(self):
        value = self.end - time.monotonic()
        if value <= 0:
            raise SessionError("timeout", "The command's total wait limit expired.", 4)
        self.store.timeout = value
        return value

    @contextmanager
    def _lock(self, slot, blocking=True):
        lock = control_lock(self.project, slot, self.remaining(), blocking)
        with lock:
            self._held[slot] = lock
            try:
                yield
            finally:
                del self._held[slot]

    @contextmanager
    def _unlocked(self, slot):
        """Step out of this command's control lock on `slot` while another process acts under it.

        The registration of a run takes the lock to publish it, so a command that waits for that
        registration must not hold it. Without a held lock this does nothing."""
        lock = self._held.get(slot)
        if lock is None:
            yield
            return
        lock.release()
        yield                                      # after an error the lock stays released; the exit of `_lock` has nothing to do
        try:
            lock.acquire(self.remaining(), blocking=True)   # even a lock first taken without waiting
        except SessionError:
            pass                                   # what the wait found stands; `_regain` takes the lock for what needs it

    def _regain(self, slot):
        """Hold this command's control lock on `slot` again, after a wait left it; at most a few seconds."""
        lock = self._held.get(slot)
        if lock is not None and not lock.held:
            lock.acquire(REGAIN_SECONDS, blocking=True)

    def _authorize(self, operation, slot):
        actor, identity = api.caller(self.project, self.tmux, self.store)
        if actor == "unmanaged-agent":
            if operation == "start" and slot == "leader":
                return actor, identity
            raise SessionError("caller_unbound", "This agent is not a registered member of this project.")
        if operation in ("shutdown", "resume") and actor != "operator":
            raise SessionError("role_denied", f"Only the operator may {operation} the project sessions.")
        if operation == "watch" and actor not in ("operator", "leader"):
            raise SessionError("role_denied", "Only the operator or this project's Leader may watch the project sessions.")
        if operation == "send_project" and (actor != "leader" or not identity):
            raise SessionError("role_denied", "Only this project's Leader may send to another project.")
        if actor == "leader" or actor.startswith("seat-"):
            api.require_live(self.project, actor, identity, self.tmux)
        if actor.startswith("seat-"):
            if operation == "start" or (slot != actor and not (operation == "send" and slot == "leader")):
                raise SessionError("role_denied", "A Worker may report to the Leader or control its own execution.")
        return actor, identity

    def _context(self, slot, job=None, run_id=None):
        seat = None if slot == "leader" else int(slot[5:])
        root = self.project.base if seat is None else self.project.seats[seat]
        remote = isinstance(root, RemoteSeat)
        path = root.path if remote else root
        cwd = path if job is None else (path / job["cwd"])
        cwd = cwd if remote else cwd.resolve()
        if not cwd.is_relative_to(path) or (remote and ".." in cwd.parts):
            raise SessionError("cwd_unavailable", "The JOB directory must be inside its seat.", 2)
        context = {
            "base": str(self.project.base), "project_id": self.project.project_id,
            "provider": self.project.provider, "config_path": str(self.project.config_path),
            "target": slot, "seat": seat, "seat_root": str(root), "cwd": str(cwd),
            "job": job, "job_id": job["job_id"] if job else None,
            "role": "leader" if job is None else "worker", "run_id": run_id or uuid.uuid4().hex,
            "python": sys.executable, "library_path": str(launch_artifacts.library_path()),
            "timeout": self.remaining(), "allow_daemon_start": True,
        }
        if remote:
            context["remote_seat"] = {"host": root.host, "path": str(root.path), "python": root.python}
        return context

    def _new_window(self, context, resume=None, ending=None):
        """A run and its window. With `resume`, the run reopens that conversation instead of a new one.

        `ending` is the run that this restart's own controller just ended (see `windows.reusable`)."""
        context = context if context.get("remote_seat") else self.provider.prepare_context(context)
        if resume:
            context.update(session_id=resume, expected_session_id=resume, resume=True)
        context["window_name"] = windows.window_name(self.project.project_id, context)
        return windows.open_window(self.tmux, self.project, context, self._reusable(context["target"], ending))

    def _reusable(self, target, ending=None):
        return windows.reusable(self.tmux, self.project, target, self._observe, ending)
    def _target(self, job=None, seat=None, recovery=False):
        """The slot's current run. A run whose conversation moved to the background is refused unless it ended;
        with `recovery`, stop and restart may then replace it, and an unknown end is `execution_unknown`."""
        if (job is None) == (seat is None):
            raise SessionError("target_required", "Specify exactly one of --job and --seat.", 2)
        state = self.store.read()
        if job == "leader":
            slot = "leader"
        elif seat is not None:
            if isinstance(seat, bool) or not isinstance(seat, int) or not 0 <= seat < len(self.project.seats):
                raise SessionError("seat_invalid", "The seat number is outside the registry.", 2)
            slot = f"seat-{seat}"
            if state[str(seat)]["job_id"] is None:
                raise SessionError("job_not_assigned", "This seat has no assigned JOB.")
        else:
            seats = [key for key, entry in state.items() if key != "leader" and entry["job_id"] == job]
            if len(seats) != 1:
                raise SessionError("job_not_assigned", "The JOB has no unique current seat.")
            slot = f"seat-{seats[0]}"
        meta = self.tmux.get_current(self.project.project_id, slot)
        if not meta:
            raise SessionError("execution_unknown", "The target has no current execution evidence.", 4)
        if slot != "leader":
            number = slot[5:]
            if state[number]["job_id"] != meta.get("job_id"):
                raise SessionError("target_changed", "The JOB differs from the managed execution.")
        owned = self._owned(meta, slot, state)
        self._refuse_moved(owned, recovery)
        return owned

    def _refuse_moved(self, meta, recovery):
        """Raise for a run whose conversation moved to the background, unless that run is confirmed ended."""
        record = self._moved_record(meta)
        if record:
            observed = self._moved_observation(meta, record, self.tmux.pane_info(meta["pane_id"]))
            if not observed["stopped"]:
                raise self._moved_error(observed["moved"], recovery)

    def _moved_record(self, meta, listed=None):
        """The record of a move to a background session, or None. A new one is recorded on the run's window.

        Without a record, the run's transcript must end with the move and the provider's listing must no
        longer show the managed pane (`listed` False, else looked up here)."""
        record = meta.get("moved_to_background")
        if record or meta.get("remote_seat") or not meta.get("registered") or not meta.get("session_id"):
            return record or None
        if not self.provider.moved_to(meta["session_id"]):
            return None
        if listed is None:
            context = self._provider_context(meta, self.tmux.pane_info(meta["pane_id"]))
            try:
                observed = self.provider.observe(self._session(meta), context, context["meta"],
                                                 timeout=self.remaining())
                listed = observed.get("listed") is not False
            except SessionError as error:
                if error.code != "session_not_bound":
                    raise
                listed = False
        if listed:
            return None
        record = background.record_of(self.provider, meta["session_id"], None, meta["cwd"],
                                      min(self.remaining(), HOST_SECONDS))
        if record:
            meta["moved_to_background"] = record
            self.tmux.write_meta(meta["window_id"], {"run_id": meta["run_id"], "moved_to_background": record})
        return record

    def _moved_observation(self, meta, record, pane):
        """The observation of a moved run: stopped only when its conversation and its CLI both ended."""
        judged = background.judge(self.provider, meta, record, pane, min(self.remaining(), HOST_SECONDS))
        if judged["record"] != record:
            meta["moved_to_background"] = judged["record"]
            self.tmux.write_meta(meta["window_id"], {"run_id": meta["run_id"], "moved_to_background": judged["record"]})
        ended = judged["state"] == "ended"
        return {"known": True, "terminal": ended, "active_turn": False if ended else None, "pending": [],
                "background": [], "idle": ended, "stopped": ended, "pane": pane,
                "cli_alive": judged["cli"] == "alive", "group_alive": False, "tracked_alive": False,
                "moved": background.details(meta, judged["record"], judged)}

    @staticmethod
    def _moved_error(moved, recovery):
        """`conversation_backgrounded`; with `recovery`, an end that cannot be confirmed is `execution_unknown`."""
        if recovery and moved["state"] == "unknown":
            return SessionError("execution_unknown", "The conversation moved to a background session and its end "
                                "cannot be confirmed.", 4, moved)
        return SessionError("conversation_backgrounded", "The managed conversation moved to a background session "
                            "with a new session ID. Stop that conversation and the CLI, then run start or restart "
                            "again.", 4, moved)

    @staticmethod
    def _provider_context(meta, pane):
        return {**meta, "pane_dead": pane["pane_dead"], "meta": {**meta, "pane_dead": pane["pane_dead"]}}

    def _same(self, selected, published=True):
        """Re-read the selected run under its control lock. Before publication, compare only its base and slot."""
        current = self.tmux.get_current(self.project.project_id, selected["target"])
        keys = ("run_id", "window_id", "pane_id", "job_id", "session_id", "remote_seat", "remote_native")
        if not current or any(current.get(key) != selected.get(key) for key in keys):
            raise SessionError("target_changed", "The command target changed before control.")
        return self._owned(current, selected["target"], self.store.read() if published else None)

    def _owned(self, meta, slot, state=None):
        """Adopt only this base's run of the slot and, with a state, the conversation it names there."""
        session = None
        if state is not None and meta.get("session_id"):
            # A run without a conversation, such as a failed restart's waiting pane, has none to misdirect.
            session = state["leader"] if slot == "leader" else state[slot[5:]]["session"]
        check_owner(self.project, slot, session, meta)
        return meta

    def _adopted(self, meta, slot):
        """Start may handle an existing run only as this base's run of the slot.

        A run that is not published yet is compared by base and slot only; a published run
        must also be the conversation the state names.
        """
        return self._owned(meta, slot, self.store.read(missing_ok=True) if meta.get("ready") else None)

    @staticmethod
    def _session(meta):
        if not meta.get("registered") or not meta.get("session_id"):
            raise SessionError("session_unbound", "The provider conversation has not registered.", 4)
        if meta["provider"] == "codex":
            return {"session_id": meta["session_id"], "endpoint": meta["endpoint"]}
        return {"session_id": meta["session_id"], "message_to": meta["message_to"]}

    def _observe(self, meta):
        if meta.get("remote_seat") and meta.get("provider_launch_attempted") is not False:
            from .remote import observe
            return observe(meta, timeout=self.remaining())
        pane = self.tmux.pane_info(meta["pane_id"])
        if not meta.get("registered"):
            if _unregistered_ended(meta, pane):
                return {"known": True, "terminal": True, "active_turn": False, "pending": [], "background": [],
                        "idle": True, "cli_alive": False, "group_alive": False, "tracked_alive": False,
                        "stopped": True, "pane": pane}
            return process.unlaunched_observation(meta, pane)
        if pane["pane_dead"] and ended.confirms(self.project, meta):
            # The end was confirmed when the run ended itself (`finish_ended`); a dead pane and the same CLI.
            return {"known": True, "terminal": True, "active_turn": False, "pending": [], "background": [],
                    "idle": True, "cli_alive": False, "group_alive": False, "tracked_alive": False,
                    "stopped": True, "pane": pane}
        context = self._provider_context(meta, pane)
        session = self._session(meta)
        moved = meta.get("moved_to_background")
        if not moved:
            failure = None
            try:
                observed = self.provider.observe(session, context, context["meta"], timeout=self.remaining())
            except SessionError as error:
                if error.code != "session_not_bound":
                    raise
                observed, failure = None, error
            if observed is None or observed.get("listed") is False:
                moved = self._moved_record(meta, listed=False)
            if not moved and failure:
                raise failure
        if moved:
            return self._moved_observation(meta, moved, pane)
        self._record_background_clear(meta, observed)
        live, group_live, extra_live = self._process_facts(meta, pane)
        stopped = bool(pane["pane_dead"] and not live and not group_live and not extra_live
                       and observed.get("known") and observed.get("terminal")
                       and not observed.get("active_turn") and not observed.get("pending")
                       and not observed.get("background"))
        return {**observed, "stopped": stopped, "pane": pane, "cli_alive": live,
                "group_alive": group_live, "tracked_alive": extra_live}

    @staticmethod
    def _process_facts(meta, pane):
        """Whether the run's CLI, its process group, and its tracked background PIDs still live."""
        live = process.alive(int(meta["cli_pid"]), meta.get("cli_birth")) if meta.get("cli_pid") else not pane["pane_dead"]
        group = meta.get("process_group")
        group_live = bool(group and process.group_alive(int(group)))
        extra_live = any(process.alive(int(item["pid"]), item.get("birth"))
                         for item in meta.get("background_pids", []))
        return live, group_live, extra_live

    def _record_background_clear(self, meta, observed):
        if meta.get("provider") != "codex" or observed.get("background_source") == "last_loaded_clear":
            return
        clear = bool(observed.get("known") and observed.get("terminal")
                     and not observed.get("active_turn") and not observed.get("pending")
                     and not observed.get("background") and observed.get("background_known", True))
        evidence = {"session_id": meta["session_id"], "run_id": meta["run_id"],
                    "latest_turn_id": observed.get("latest_turn_id")} if clear else None
        if meta.get("last_background_clear") != evidence:
            self.tmux.write_meta(meta["window_id"], {"run_id": meta["run_id"], "last_background_clear": evidence})
            meta["last_background_clear"] = evidence

    def _prepare_launch(self, context, request=None):
        return launch_artifacts.prepare(self.project, self.provider, context, request, self.remaining)

    def _handoff_path(self, meta):
        return handoff.path(self.project, meta)

    def _fresh_handoff(self, meta):
        return handoff.fresh(self.project, meta, self.remaining())

    def _require_handoff(self, meta):
        return handoff.require(self.project, meta, self.remaining())
    def _launch(self, context, request=None):
        if context.get("remote_seat"):
            from .remote_lifecycle import launch
            return launch(self, context)
        if not Path(context["cwd"]).is_dir():
            raise SessionError("cwd_unavailable", "The CR Cwd does not exist in the prepared seat.", 2,
                               {"cwd": context["cwd"]})
        prepared, launch = self._prepare_launch(context, request)
        self.tmux.write_meta(context["window_id"], {
            "provider_name": prepared.get("provider_name"),
            "launch_file": str(launch_artifacts.run_directory(self.project, context["run_id"]) / "launch.sh"),
            "stopping": False,
        })
        script = launch_artifacts.write_launch_script(self.project, context, launch)
        try:
            # Before the CLI exists, so that even an immediate exit is seen. Without it the dead pane stays
            # as before and `stop` still ends the run.
            self.tmux.install_exit_hook(context["python"], context["library_path"])
        except SessionError:
            pass
        context = self.tmux.launch(context["window_id"], context["cwd"], script)
        result = self._wait_ready(context)
        return {**result, "cleanup": self._sweep_regained(context["target"])}

    def _sweep_regained(self, target):
        """Sweep under the control lock; a lock that cannot be had leaves the sweep to the next start."""
        try:
            self._regain(target)
        except SessionError as error:
            return {"closed": [], "kept": [{"window_id": None, "reason": error.code}]}
        return self._sweep(target)

    def _sweep(self, target, owner=None):
        return windows.sweep(self.tmux, self.project, target, self._observe, owner)

    def sweep_after_result(self, target, owner):
        """The self-controller's last cleanup, serialized with the slot's other commands."""
        try:
            with control_lock(self.project, target, self.remaining(), blocking=False):
                return self._sweep(target, owner=owner)
        except SessionError as error:
            # A busy slot's command sweeps when it finishes; nothing is closed without the lock.
            return {"closed": [], "kept": [{"window_id": None, "reason": error.code}]}
    def _wait_ready(self, context):
        """Wait until the run is published or fails, and report it. A local run is published by its own
        registration (`internal._register`), so this command holds no control lock while it waits."""
        if context.get("remote_seat"):
            return self._observe_ready(context)
        with self._unlocked(context["target"]):
            self._observe_ready(context)
        # Whatever happened while the lock was out of hand, report the run as it is now.
        current = self.tmux.get_current(self.project.project_id, context["target"])
        if not current or current.get("run_id") != context["run_id"]:
            raise SessionError("target_changed", "Another execution replaced this run while its start waited.")
        if current.get("stopping"):
            raise SessionError("target_stopping", "This execution is stopping.")
        return self._result(current, ready=True)

    def _observe_ready(self, context):
        screened = 0.0
        while True:
            self.remaining()
            meta = self.tmux.get_current(self.project.project_id, context["target"])
            if not meta or meta.get("run_id") != context["run_id"]:
                raise SessionError("target_changed", "Another execution replaced this startup.")
            if not meta.get("remote_seat") and not meta.get("ready"):
                meta = self._local_publication(meta)
            if meta.get("remote_seat"):
                from .remote_lifecycle import poll
                meta = poll(self, meta)
                if meta.get("registered") and not meta.get("ready"):
                    # The registration ran on the remote host, so no registration function of this host
                    # publishes it; this controller does, while its caller holds the control lock.
                    meta = publish_session(self.project, self.tmux, self.store, meta, self._session(meta))
            if meta.get("ready"):
                return self._result(meta, ready=True)
            failure = meta.get("start_error")
            if isinstance(failure, dict):
                # The registration recorded why it failed; the run's CLI stays alive, so nothing else ends this wait.
                raise SessionError("registration_failed", "The provider's registration was rejected: "
                                   f"{failure.get('message')}", 4,
                                   {**self._result(meta), "hook_error": failure})
            if not meta.get("remote_seat") and self.tmux.pane_info(meta["pane_id"])["pane_dead"]:
                raise SessionError("provider_exited", "The CLI exited before registering its conversation.", 4,
                                   self._result(meta))
            if time.monotonic() - screened >= DIALOG_SCREEN_SECONDS:
                screened = time.monotonic()
                dialog = self.provider.startup_dialog(self.tmux.capture_pane(meta["pane_id"]))
                if dialog:
                    raise SessionError("needs_user_action", f"The CLI waits at its {dialog} dialog. Answer it in "
                                       "the window; the registration then publishes it.", 3,
                                       {**self._result(meta), "dialog": dialog})
            time.sleep(min(0.1, self.remaining()))

    def _local_publication(self, meta):
        """What a waiting start does about a local run that is not published yet.

        Registration publishes, so there is normally nothing to do. Two leftovers are handled. A run whose
        registration committed its state but ended before its window update is finished under the control
        lock (it decides nothing new). A run that is registered but not ready was left by an earlier release,
        and only its registration could have checked its binding, so it is reported, never published."""
        if meta.get("registered"):
            job = meta.get("job_id") or "leader"
            raise SessionError("registration_incomplete", "The run registered but its conversation was never "
                               f"published (an earlier release left it). Stop or restart it: agent-session stop "
                               f"--job {job} or agent-session restart --job {job}.", 4,
                               {**self._result(meta), "resolution": ["stop", "restart"]})
        if meta.get("publishing"):
            with control_lock(self.project, meta["target"], self.remaining()):
                finished = complete_publication(self.project, self.tmux, self.store, meta)
            return finished or meta
        return meta

    def _result(self, meta, **extra):
        return {"project": self.project.project_id, "seat": meta.get("seat"), "job_id": meta.get("job_id"),
                "run_id": meta.get("run_id"), "window_id": meta.get("window_id"),
                "pane_id": meta.get("pane_id"), "cwd": meta.get("cwd"),
                "session": self._session(meta) if meta.get("registered") else None,
                **({"host": meta["remote_seat"]["host"], "remote_native": meta.get("remote_native")}
                   if meta.get("remote_seat") else {}), **extra}

    def _retire_name(self, meta):
        windows.retire_name(self.tmux, self.project.project_id, meta)
    def _start_existing(self, meta, request=None):
        self._authorize("start", meta["target"])
        if meta.get("control_pending"):
            raise SessionError("control_busy", "This run has an accepted control request.", 4)
        # A JOB parked in todo/ resumes only in a new run, so its live run must stop first.
        parked = bool(meta.get("job_id")) and jobs.lookup(self.project, meta["job_id"])["state"] == "todo"
        if meta.get("registered"):
            observed = self._observe(meta)
            if not observed["stopped"]:
                if observed.get("moved"):
                    raise self._moved_error(observed["moved"], True)
                if meta.get("stopping"):
                    raise SessionError("target_stopping", "This execution is stopping.")
                if parked:
                    raise SessionError("assignment_mismatch", PARKED_ALIVE, 3)
                if meta.get("remote_seat") and self.tmux.pane_info(meta["pane_id"])["pane_dead"]:
                    from .remote_lifecycle import attach
                    meta = attach(self, meta)
                return self._wait_ready(meta)
            return self._replace_ended(meta)
        if not meta.get("remote_seat") and _unregistered_ended(meta, self.tmux.pane_info(meta["pane_id"])):
            return self._replace_ended(meta)       # its CLI ended before registering
        if meta.get("provider_launch_attempted") is not False:
            if parked:
                raise SessionError("assignment_mismatch", PARKED_ALIVE, 3)
            if meta.get("remote_seat"):
                from .remote_lifecycle import launch
                return launch(self, meta)
            return self._wait_ready(meta)
        if meta.get("job"):
            meta["job"] = jobs.claim(self.project, meta["job_id"])
            self._prepare_launch(meta)
            git_ops.prepare(meta, self.project, self.store)
            self.tmux.write_meta(meta["window_id"], {"job": meta["job"]})
        else:
            self.store.update(lambda value: value)
            request = request if request is not None else meta.get("leader_request")
            self._prepare_launch(meta, request)
        return self._launch(meta, request)

    def _replace_ended(self, meta):
        """A new conversation in the slot of a run whose end is confirmed; the CR, seat, and branch stay."""
        job = jobs.claim(self.project, meta["job_id"]) if meta.get("job_id") else None
        carried = self._fresh_handoff(meta)
        self._retire_name(meta)
        context = self._context(meta["target"], job)
        context["handoff_file"] = handoff.existing_file(carried)
        context = self._new_window(context)
        return self._launch(context)

    def start(self, job, prompt_file=None, seat=None):
        leader = job == "leader"
        check_start_arguments(job, prompt_file, seat)
        if seat is not None and (isinstance(seat, bool) or not isinstance(seat, int)
                                 or not 0 <= seat < len(self.project.seats)):
            raise SessionError("seat_invalid", "The seat number is outside the registry.", 2)
        request = Path(prompt_file).read_text(encoding="utf-8") if prompt_file else None
        if leader:
            self._authorize("start", "leader")
            with self._lock("leader"):
                current = self.tmux.get_current(self.project.project_id, "leader")
                if current:
                    self._adopted(current, "leader")
                    observed = self._observe(current) if current.get("registered") else None
                    if observed and observed["stopped"]:
                        self._retire_name(current)
                    elif current.get("registered") and not current.get("ready") and not current.get("stopping"):
                        return self._wait_ready(current)
                    elif current.get("provider_launch_attempted") is False:
                        return self._start_existing(current, request)
                    elif _unregistered_ended(current, self.tmux.pane_info(current["pane_id"])):
                        self._retire_name(current)         # its CLI ended before registering; a new run replaces it
                    elif (not current.get("registered") and not current.get("stopping")
                          and not self.tmux.pane_info(current["pane_id"])["pane_dead"]):
                        return self._wait_ready(current)   # e.g. a start that waited at a startup dialog
                    elif observed and observed.get("moved"):
                        raise self._moved_error(observed["moved"], True)
                    else:
                        raise SessionError("leader_exists", "The current Leader is alive or its exit is unconfirmed.")
                context = self._context("leader")
                context["leader_request"] = request
                context = self._new_window(context)
                self.store.update(lambda value: value)
                self._prepare_launch(context, request)
                result = self._launch(context, request)
                SuspendStore(self.project, self.remaining()).forget_before("leader", result["run_id"])   # a new conversation ends the record
                return result
        item = jobs.lookup(self.project, job)
        self._authorize("start", "worker")
        suspended = False
        with locked(self.project.runtime_path / "allocation.lock", self.remaining()):
            state = self.store.read(missing_ok=True)
            assigned = [key for key, value in state.items() if key != "leader" and value["job_id"] == item["job_id"]]
            item = jobs.lookup(self.project, job)
            if assigned:
                if item["state"] not in ("todo", "in-progress"):
                    raise SessionError("assignment_mismatch", "A reserved CR must be in todo or in-progress.", 3)
                number = int(assigned[0])
                if seat is not None and seat != number:
                    raise SessionError("assignment_mismatch", "The JOB is already reserved on another seat.", 3,
                                       {"seat": number, "requested_seat": seat})
                slot = f"seat-{number}"
                context = self.tmux.get_current(self.project.project_id, slot)
                # A shutdown's record is the evidence that a slot without a run was ended on purpose.
                suspended = not context and self.is_suspended(slot, item)
                if not suspended and (not context or context.get("job_id") != item["job_id"]):
                    raise SessionError("execution_unknown", "The reserved JOB has no matching run evidence.", 4)
            elif item["state"] != "todo":
                raise SessionError("cr_not_assignable", "An unassigned CR must be in todo; "
                                   f"{item['job_id']} is in {item['state']}.", 3)
            else:
                number = None
                guard = None
                reasons = {}
                candidates = enumerate(self.project.seats) if seat is None else ((seat, self.project.seats[seat]),)
                for index, root in candidates:
                    if state[str(index)]["job_id"] is not None:
                        reasons[str(index)] = ["JOB assigned"]
                        continue
                    slot = f"seat-{index}"
                    candidate_guard = self._lock(slot, blocking=False)
                    try:
                        candidate_guard.__enter__()
                    except SessionError as error:
                        if error.code != "control_busy":
                            raise
                        reasons[str(index)] = ["target control is busy"]
                        continue
                    selected_guard = False
                    try:
                        if workspace.ensure_seat(self.project, root) and not isinstance(root, RemoteSeat):
                            self.provider.trust_new_seat(root)
                        checked = workspace.check_seat(self.project, root, item)
                        if not checked.get("allowed"):
                            reasons[str(index)] = checked.get("reasons", [])
                            continue
                        try:
                            prior = self.tmux.get_current(self.project.project_id, slot)
                        except SessionError as error:
                            if error.code != "execution_evidence_missing":
                                raise
                            reasons[str(index)] = ["previous execution evidence is missing"]
                            continue
                        if prior:
                            self._adopted(prior, slot)
                        if prior and not self._observe(prior)["stopped"]:
                            reasons[str(index)] = ["previous execution termination is unconfirmed"]
                            continue
                        candidate = self._context(slot, item)
                        item = jobs.claim(self.project, item["job_id"])
                        candidate["job"] = item
                        context = None
                        try:
                            context = self._new_window(candidate)
                            def reserve(value):
                                if value[str(index)]["job_id"] is not None:
                                    raise SessionError("target_changed", "Another JOB reserved the seat.")
                                value[str(index)] = {"job_id": item["job_id"], "git_hash": None, "session": None}
                            self.store.update(reserve)
                        except BaseException:
                            if context is not None:
                                windows.discard_placeholder(self.tmux, self.project, context, self._observe, self.remaining)
                            jobs.unclaim(self.project, item["job_id"])
                            raise
                        number, guard, selected_guard = index, candidate_guard, True
                        break
                    finally:
                        if not selected_guard:
                            candidate_guard.__exit__(*sys.exc_info())
                if number is None:
                    raise SessionError("no_available_seat", "No seat passed the allocation checks.", details={"seats": reasons})
        if assigned and suspended:
            return self.start_suspended(slot, item)
        if assigned:
            with self._lock(slot):
                current = self.tmux.get_current(self.project.project_id, slot)
                if (not current or current.get("run_id") != context["run_id"]
                        or self.store.read()[str(number)]["job_id"] != item["job_id"]):
                    raise SessionError("target_changed", "The JOB changed before its startup retry.")
                self._adopted(current, slot)
                return self._start_existing(current)
        try:
            self._prepare_launch(context)
            git_ops.prepare(context, self.project, self.store)
            self.tmux.write_meta(context["window_id"], {"job": context["job"]})
            return self._launch(context)
        finally:
            guard.__exit__(*sys.exc_info())

    def send(self, job=None, seat=None, message=None, file=None, project=None):
        if (message is None) == (file is None):
            raise SessionError("invalid_input", "Specify one message or --file.", 2)
        body = Path(file).read_text(encoding="utf-8") if file is not None else message
        if not isinstance(body, str) or not body.strip() or len(body.encode("utf-8")) > 32768:
            raise SessionError("message_too_large", "Use a nonempty UTF-8 message of at most 32768 bytes.", 2)
        if project is None or project == self.project.project_id:
            return self._send(self, job, seat, body)
        if job != "leader" or seat is not None:
            raise SessionError("invalid_input", "Another project accepts a message only for its Leader (--job leader).", 2)
        return self._send(self._recipient(project), job, seat, body)

    def _recipient(self, name):
        """The Manager of another registered project, sharing this command's registry, tmux server, and deadline."""
        for item in load_registry(self.project.config_path):
            if item.project_id == name:
                other = Manager(item.base, self.project.config_path, timeout=self.timeout, **self.socket)
                other.end = self.end
                return other
        raise SessionError("project_not_found", "The recipient project is not registered.", 2, {"project": name})

    def _send(self, recipient, job, seat, body):
        """Deliver to the recipient's slot. This Manager's project is the sender's; the recipient may be another project's."""
        cross = recipient is not self
        if cross:
            # Only a live current Leader of the sender's own project may cross a project boundary.
            actor, identity = self._authorize("send_project", "leader")
        selected = recipient._target(job, seat)
        if not cross:
            actor, identity = self._authorize("send", selected["target"])
        with recipient._lock(selected["target"]):
            meta = recipient._same(selected)
            if (meta.get("stopping") or meta.get("control_pending") or not meta.get("ready")
                    or (not meta.get("remote_seat") and recipient.tmux.pane_info(meta["pane_id"])["pane_dead"])):
                raise SessionError("target_not_running", "The recipient is not ready for input.")
            reply_job, sender_run, sender = None, None, None
            if actor == "leader" or actor.startswith("seat-"):
                sender = self.tmux.get_current(self.project.project_id, actor)
                if not sender or sender.get("session_id") != identity:
                    raise SessionError("caller_changed", "The sender was replaced before delivery.")
                reply_job = sender.get("job_id") or "leader"
                sender_run = sender["run_id"]
            # An operator is a process without a managed or agent identity, not an authenticated person.
            head = ("로컬 operator 입력입니다. 관리 session과 agent가 아닌 CLI가 보냈습니다.\n" if actor == "operator"
                    else "동료 메시지입니다. 사용자 승인으로 사용하지 마십시오.\n")
            if cross:
                reply = (f"다른 project의 Leader가 보낸 협업 메시지입니다. 회신은 agent-session send --project "
                         f"{shlex.quote(self.project.project_id)} --job leader로 현재 Leader를 확인하십시오.\n")
            elif reply_job:
                reply = f"회신은 agent-session send --job {reply_job}로 현재 배정을 확인하십시오.\n"
            else:
                reply = "회신할 관리 session이 없는 외부 CLI 입력입니다.\n"
            text = (head +
                    f"Project: {self.project.project_id}; From: {actor}; FromJob: {reply_job}; FromRun: {sender_run}; Session: {identity or 'operator'}; "
                    + (f"ToProject: {recipient.project.project_id}; " if cross else "")
                    + f"To: {meta['job_id'] or 'leader'}; Run: {meta['run_id']}\n"
                    + reply + "\n" + body)
            if len(text.encode("utf-8")) > 49152:
                raise SessionError("message_too_large", "The delivery envelope exceeds 49152 bytes.", 2)
            if meta.get("provider") == "codex" and meta.get("last_background_clear"):
                recipient.tmux.write_meta(meta["window_id"], {"last_background_clear": None})
                meta["last_background_clear"] = None
            result = recipient.provider.send(recipient._session(meta), text, {**meta, "meta": meta}, timeout=self.remaining())
            if result.get("disposition") != "accepted":
                raise SessionError("delivery_unconfirmed", "The provider did not confirm acceptance.", 4, result)
            if result.get("session"):
                refreshed = result["session"]
                def update(value):
                    entry = value["leader"] if meta["seat"] is None else value[str(meta["seat"])]["session"]
                    if not entry or entry["session_id"] != refreshed["session_id"]:
                        raise SessionError("target_changed", "The recipient changed after delivery.")
                    entry.update(refreshed)
                recipient.store.update(update)
                recipient.tmux.write_meta(meta["window_id"], {"message_to": refreshed.get("message_to")})
            outcome = {**recipient._result(meta), **result}
            self._note_message(recipient, meta, actor, sender)
            if actor == "leader" and meta.get("job_id"):
                # Feedback returns the JOB to its Worker; a later Leader's review stays.
                try:
                    self._clear_review(meta["job_id"], leader_session_id=identity)
                except SessionError as error:
                    # The message was accepted; reporting a failure here would invite a duplicate send.
                    outcome["review_clear_error"] = error.as_dict()
            return outcome

    @staticmethod
    def _note_message(recipient, meta, actor, sender):
        """Record an accepted message on both windows for `watch`: when the recipient last received one and
        who sent it, and when the sender last sent one and to whom. The message is already delivered, so a
        failed record changes nothing and is not an error."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            recipient.tmux.write_meta(meta["window_id"], {"run_id": meta["run_id"],
                                                          "last_received": {"from": actor, "at": now}})
            if sender:
                recipient.tmux.write_meta(sender["window_id"], {"run_id": sender["run_id"], "last_sent": {
                    "to": "leader" if meta.get("job_id") is None else meta["job_id"], "at": now}})
        except SessionError:
            pass

    def _clear_review(self, job_id, leader_session_id=None):
        def clear(value):
            leader = value["leader"]
            if (leader and leader.get("reviewing") == job_id
                    and (leader_session_id is None or leader["session_id"] == leader_session_id)):
                leader["reviewing"] = None
        if (self.store.read()["leader"] or {}).get("reviewing") == job_id:
            self.store.update(clear)

    def review(self, job=None, clear=False):
        """Mark the JOB the Leader is reviewing now, or clear the mark."""
        if (job is None) == (not clear):
            raise SessionError("invalid_input", "Specify --job or --clear.", 2)
        if job == "leader":
            raise SessionError("invalid_input", "The Leader reviews a Worker JOB.", 2)
        actor, identity = self._authorize("review", "leader")
        leader = self.store.read(missing_ok=True)["leader"]
        if not leader:
            raise SessionError("session_unbound", "The project has no bound Leader conversation.", 4)
        expected = leader["session_id"]
        if actor == "leader" and identity != expected:
            raise SessionError("caller_changed", "The calling Leader was replaced.")
        if not clear:
            self._refuse_moved_review(job)

        def mark(value):
            current = value["leader"]
            if not current or current["session_id"] != expected:
                raise SessionError("target_changed", "The Leader changed before the review mark.")
            if clear:
                current["reviewing"] = None
                return
            seats = [key for key, entry in value.items() if key != "leader" and entry["job_id"] == job]
            if len(seats) != 1:
                raise SessionError("job_not_assigned", "The JOB has no unique current seat.")
            if value[seats[0]]["session"] is None:
                raise SessionError("session_unbound", "The JOB's Worker has no bound conversation.", 4)
            current["reviewing"] = job
        state = self.store.update(mark)
        return {"project": self.project.project_id, "reviewing": state["leader"]["reviewing"]}

    def _refuse_moved_review(self, job):
        """A review needs the Leader and the JOB's Worker to be reachable, not moved to a background session."""
        state = self.store.read(missing_ok=True)
        slots = ["leader"] + [f"seat-{key}" for key, entry in state.items() if key != "leader" and entry["job_id"] == job]
        for slot in slots:
            try:
                meta = self.tmux.get_current(self.project.project_id, slot)
            except SessionError as error:
                if error.code != "execution_evidence_missing":
                    raise
                continue
            if meta:
                self._refuse_moved(meta, False)

    def control(self, operation, job=None, seat=None, expected_run=None, allow_self=True, defer_cleanup=False):
        """Stop or restart one run. A self-controller defers window cleanup until it saved its result."""
        if operation not in ("stop", "restart"):
            raise SessionError("invalid_input", "Use stop or restart.", 2)
        selected = self._target(job, seat, recovery=True)
        actor, _ = self._authorize(operation, selected["target"])
        if expected_run and selected["run_id"] != expected_run:
            raise SessionError("target_changed", "This controller belongs to an old run.")
        if allow_self and actor == selected["target"]:
            return self._self_control(operation, selected, job, seat)
        with self._lock(selected["target"]):
            meta = self._same(selected)
            if meta.get("control_pending") and expected_run is None:
                raise SessionError("control_busy", "This run has an accepted control request.", 4)
            carried = self._require_handoff(meta) if operation == "restart" else None
            if not meta.get("registered") and meta.get("provider_launch_attempted") is False and operation == "stop":
                self.tmux.request_placeholder_stop(meta["window_id"])
                exit_sent = True
            else:
                session = self._session(meta)
                observed = self.provider.request_stop(session, meta, meta, timeout=self.remaining())
                self._record_background_clear(meta, observed)
                exit_sent = False
            self.tmux.write_meta(meta["window_id"], {"stopping": True})
            last = None
            try:
                while True:
                    try:
                        observed = self._observe(meta)
                    except SessionError as error:
                        # After the exit request, leaving the provider's listing is part of the end.
                        # Keep watching the same CLI and pane until the wait limit expires.
                        if not exit_sent or error.code != "session_not_bound":
                            raise
                        observed = None
                    if observed is not None:
                        last = observed
                        if observed["stopped"]:
                            break
                        if observed.get("idle") and not exit_sent:
                            self.provider.request_exit(meta, self.tmux)
                            exit_sent = True
                    time.sleep(min(0.1, self.remaining()))
            except BaseException as error:
                self._restore_stopping(meta, error)
                _note_exit_wait(error, exit_sent, last)
                raise
            self._retire_name(meta)
            if meta.get("remote_native"):
                from .remote_lifecycle import detach
                detach(self, meta)
            if operation == "restart":
                current_job = jobs.lookup(self.project, meta["job_id"], ("in-progress",)) if meta.get("job_id") else None
                context = self._context(meta["target"], current_job)
                context["handoff_file"] = handoff.existing_file(carried)
                context = self._new_window(context, ending=meta)
                result = self._launch(context)
                if result["session"]["session_id"] == meta["session_id"]:
                    raise SessionError("conversation_reused", "Restart must create a new conversation.")
                result = {**result, "previous_session": self._session(meta), "restarted": True}
                # _launch already swept once the new run became current; a self-controller sweeps again
                # after it saved its result, when its own pending window may close.
                return {**result, "deferred_cleanup": meta["target"]} if defer_cleanup else result
            return self._settle(meta, defer_cleanup)

    def _settle(self, meta, defer_cleanup=False):
        """What follows the confirmed end of a run, under its control lock: release or hold the slot, then clean up.

        `stop` and the wrap-up of a run that ended itself (`finish_ended`) both end here."""
        cr_state = jobs.state_of(self.project, meta["job_id"]) if meta.get("job_id") else (None, None)
        check, pointer_kept = self._release(meta, cr_state)
        if not check.get("allowed") and meta.get("job_id"):
            self._clear_review(meta["job_id"])
            if cr_state[0] == "in-progress":
                # The CR's move out of in-progress finishes this release (finish_release).
                self._hold_release(meta, check["reasons"])
        result = self._result(meta, stopped=True, released=bool(check.get("allowed")),
                              reasons=check.get("reasons", []))
        return self._finish_control(result, meta, defer_cleanup, pointer_kept)

    def finish_ended(self, run_id, target, pane_id):
        """Wrap up a run whose CLI ended by itself (`/exit`, a crash, a signal), with no command from anyone.

        The tmux server starts this when the managed pane dies. It does what `stop` does after it confirmed the
        end: record the end (`ended`), then release the slot or hold the release for a CR still in progress, and
        clean up the window. Only a published, local run that is still the slot's current one is wrapped up;
        anything else is `{"finished": False, "reason": ...}` and nothing changes. Such a run is left to
        `stop`/`start`: one a command is controlling (stopping, a pending or running controller, a held control
        lock), one that a shutdown ended (it is resumed), and one whose end cannot be confirmed."""
        try:
            with control_lock(self.project, target, min(FINISH_LOCK_SECONDS, self.remaining())):
                meta = self.tmux.get_current(self.project.project_id, target)
                if not meta or meta.get("run_id") != run_id or meta.get("pane_id") != pane_id:
                    return {"finished": False, "reason": "not_current"}
                if meta.get("remote_seat") or not (meta.get("registered") and meta.get("ready")):
                    return {"finished": False, "reason": "not_published"}
                controller = meta.get("controller_pid")
                if (meta.get("stopping") or meta.get("control_pending")
                        or (controller and process.alive(int(controller), meta.get("controller_birth")))):
                    return {"finished": False, "reason": "control_active"}
                state = self.store.read()
                if target != "leader" and state[target[5:]]["job_id"] != meta.get("job_id"):
                    return {"finished": False, "reason": "target_changed"}
                self._owned(meta, target, state)
                basis = self._ended_basis(meta)
                if basis is None:
                    return {"finished": False, "reason": "termination_unconfirmed"}
                ended.write(self.project, meta, basis)
                self.tmux.write_meta(meta["window_id"], {"run_id": meta["run_id"], "stopping": True})
                self._retire_name(meta)
                return {"finished": True, "basis": basis, **self._settle(meta)}
        except SessionError as error:
            return {"finished": False, "reason": error.code}

    def _ended_basis(self, meta):
        """How the end of a run whose pane died is confirmed, or None: `provider` as `stop` confirms it, or `process`.

        `process`: Claude reports the end of a conversation only through its SessionEnd hook, which a killed
        CLI never runs. When the pane is dead and neither the CLI, its process group, nor its tracked PIDs
        live, nothing is left that could work (the same ground that confirms a forced shutdown). A moved
        conversation is never confirmed this way. A process group that is still draining is waited for."""
        limit = time.monotonic() + min(FINISH_END_SECONDS, self.remaining())
        while True:
            pane = self.tmux.pane_info(meta["pane_id"])
            if not pane["pane_dead"]:
                return None
            if self._observe(meta)["stopped"]:
                return "provider"
            if (self.project.provider == "claude" and not meta.get("moved_to_background")
                    and not any(self._process_facts(meta, pane))):
                return "process"
            if time.monotonic() >= limit:
                return None
            time.sleep(0.2)

    def _release(self, meta, cr_state):
        """Release the stopped run's slot when the release check allows it: (check, kept pointers)."""
        check = workspace.check_release(self.project, meta, cr_state)
        pointer_kept = []
        if check.get("allowed"):
            def release(value):
                if meta["seat"] is None:
                    if value["leader"] and value["leader"]["session_id"] != meta["session_id"]:
                        raise SessionError("target_changed", "The Leader changed before release.")
                    value["leader"] = None
                else:
                    key = str(meta["seat"])
                    if value[key]["job_id"] != meta["job_id"]:
                        raise SessionError("target_changed", "The JOB changed before release.")
                    value[key] = {"job_id": None, "git_hash": None, "session": None}
                    if value["leader"] and value["leader"].get("reviewing") == meta["job_id"]:
                        value["leader"]["reviewing"] = None
            self.store.update(release)
            # The released run is no longer current; its window becomes a retired window.
            try:
                self.tmux.clear_current(self.project.project_id, meta["target"], meta["run_id"])
            except SessionError as error:
                # Release stands; the pointer and its window stay and the result names them.
                pointer_kept.append({"window_id": meta["window_id"], "reason": error.code})
        return check, pointer_kept

    def _hold_release(self, meta, reasons):
        """Record on the stopped run's window that its release waits for the CR to leave in-progress.

        The state keeps the assignment; this record is only the execution evidence that finish_release
        and the displays read. A repeated hold keeps the first time."""
        since = (meta.get("release_pending") or {}).get("since") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.tmux.write_meta(meta["window_id"], {"release_pending": {"since": since, "reasons": list(reasons)}})

    def finish_release(self, job):
        """Finish the release that a stop left pending, once the CR is out of in-progress.

        None when the JOB has no pending release. Otherwise the release check decides as it does in
        stop: released true frees the seat; false keeps the assignment and returns the reasons."""
        state = self.store.read(missing_ok=True)
        seats = [key for key, entry in state.items() if key != "leader" and entry["job_id"] == job]
        if len(seats) != 1:
            return None
        slot = f"seat-{seats[0]}"
        with self._lock(slot):
            try:
                meta = self.tmux.get_current(self.project.project_id, slot)
            except SessionError as error:
                if error.code == "execution_evidence_missing":
                    return None
                raise
            if not meta or meta.get("job_id") != job or not meta.get("release_pending") or not meta.get("stopping"):
                return None
            self._owned(meta, slot, self.store.read())
            check, kept = self._release(meta, jobs.state_of(self.project, job))
            result = {"job_id": job, "seat": int(seats[0]), "released": bool(check.get("allowed")),
                      "reasons": check.get("reasons", [])}
            if not check.get("allowed"):
                self._hold_release(meta, check["reasons"])
                return result
            cleanup = self._sweep(slot)
            return {**result, "cleanup": {**cleanup, "kept": kept + cleanup["kept"]}}

    def pending_releases(self):
        """JOB ID -> {seat, since, reasons} for each assigned seat whose stopped run waits for release."""
        state = self.store.read(missing_ok=True)
        found = {}
        for key, entry in state.items():
            if key == "leader" or not entry["job_id"]:
                continue
            try:
                meta = self.tmux.get_current(self.project.project_id, f"seat-{key}")
            except SessionError:
                continue                           # unknown evidence is not a pending release
            pending = meta and meta.get("job_id") == entry["job_id"] and meta.get("release_pending")
            if pending:
                found[entry["job_id"]] = {"seat": int(key), **pending}
        return found

    def _restore_stopping(self, meta, error):
        """After a control that failed before the end, unblock the run only while its same CLI lives."""
        pid, birth = meta.get("cli_pid"), meta.get("cli_birth")
        try:
            if pid and birth and process.alive(int(pid), birth):
                self.tmux.write_meta(meta["window_id"], {"run_id": meta["run_id"], "stopping": False})
                note = {"stopping_restored": True}
            else:
                note = {"stopping_restored": False, "stopping_kept": "cli_unconfirmed"}
        except SessionError as failure:
            note = {"stopping_restored": False, "stopping_kept": failure.code}
        if isinstance(error, SessionError):
            error.details = {**error.details, **note}

    def _finish_control(self, result, meta, defer_cleanup, kept=()):
        if defer_cleanup:
            extra = {"cleanup": {"closed": [], "kept": list(kept)}} if kept else {}
            return {**result, **extra, "deferred_cleanup": meta["target"]}
        cleanup = self._sweep(meta["target"])
        return {**result, "cleanup": {**cleanup, "kept": list(kept) + cleanup["kept"]}}

    def _self_control(self, operation, meta, job, seat):
        directory = launch_artifacts.run_directory(self.project, meta["run_id"])
        request_file = directory / "control-request.json"
        result_file = directory / "control-result.json"
        request = {"operation": operation, "job": job, "seat": seat, "run_id": meta["run_id"],
                   "window_id": meta["window_id"],
                   "base": str(self.project.base), "config_path": str(self.project.config_path),
                   "socket_path": meta["socket_path"], "timeout": self.remaining(),
                   "requester_pid": os.getpid(), "requester_birth": process.birth(os.getpid()),
                   "result_file": str(result_file)}
        with self._lock(meta["target"]):
            current = self._same(meta)
            if current.get("control_pending"):
                if current.get("control_operation") != operation:
                    raise SessionError("control_busy", "A different control request is pending for this run.", 4)
                return {"accepted": True, "completed": False, "result_file": str(result_file)}
            if operation == "restart":
                self._require_handoff(current)
            write_json(request_file, request)
            write_json(result_file, {"ok": True, "data": {"accepted": True, "completed": False}, "error": None})
            script = launch_artifacts.write_controller_script(directory, request_file)
            self.tmux.write_meta(meta["window_id"], {"control_pending": True, "control_operation": operation})
            try:
                self.tmux.run_controller(script, self.project.base)
            except SessionError as error:
                self.tmux.write_meta(meta["window_id"], {"control_pending": False})
                write_json(result_file, {"ok": False, "data": {"completed": True}, "error": error.as_dict()})
                raise
        return {"accepted": True, "completed": False, "result_file": str(result_file)}


_COMMAND_SUMMARY = 120


def _task_summary(item):
    """A background task as the provider reported it, reduced to its identity and a short command."""
    if not isinstance(item, dict):
        return str(item)[:_COMMAND_SUMMARY]
    entry = {key: item[key] for key in ("id", "processId", "type") if key in item}
    if isinstance(item.get("command"), str):
        entry["command"] = item["command"][:_COMMAND_SUMMARY]
    return entry


def _note_exit_wait(error, exit_requested, observed):
    """Name in the error what the last observation still waited for; no conversation content.

    Only a SessionError carries details. The facts are the provider's last report and the run's
    process state, so the Leader can tell a Worker's own background task from a stuck CLI.
    """
    if not isinstance(error, SessionError):
        return
    wait = {"exit_requested": exit_requested, "observed": observed is not None}
    if observed is not None:
        tasks = [_task_summary(item) for item in observed.get("background") or []]
        wait.update({"provider_status": observed.get("runtime_status"), "idle": observed.get("idle"),
                     "background": tasks if observed.get("background") is not None else None,
                     "cli_alive": observed.get("cli_alive"), "pane_dead": (observed.get("pane") or {}).get("pane_dead"),
                     "group_alive": observed.get("group_alive"), "tracked_alive": observed.get("tracked_alive")})
    error.details = {**error.details, "exit_wait": wait}
