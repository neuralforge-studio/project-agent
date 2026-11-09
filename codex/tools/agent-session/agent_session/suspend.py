"""Shut down and resume the Claude sessions of registered projects around a server restart.

`SuspendStore` is the per-project record of what a shutdown ended. `SuspendMixin` holds the
one-target steps that need a project's `Manager`. `Fleet` is the operator command: it selects
projects from the registry, runs all targets under one deadline, and sounds the alarms.

Dependency direction: `lifecycle` imports this module (`Manager` inherits `SuspendMixin`); this
module never imports `lifecycle`. `Fleet` gets the `Manager` class from the code that assembles
it (`cli._default_fleet`) as `manager_factory`.
"""

import datetime as dt
import json
import shlex
import threading
import time

from . import jobs, process
from .config import RemoteSeat, load_registry
from .errors import SessionError
from .providers.claude import transcript_files
from .state import StateStore, locked, utc_now
from .tmux import Tmux
from .util import write_json

EXIT_GRACE = 30          # seconds after the deadline to confirm an exit that was already requested
POLL_SECONDS = 1.0       # how often a waiting shutdown observes its target; each look starts one MCP host
WARN_LEAD = 60           # seconds before the deadline of the second alarm
ALARM_MILLISECONDS = 10000
LOCK_SLACK = 120         # extra seconds for control locks and the record, past the deadline and its grace
SUPPORTED_PROVIDER = "claude"

RESUME_PROMPT = ("이 실행은 `claude --resume`으로 같은 대화를 재개합니다. 최초 prompt를 보내지 않고, "
                 "등록이 끝나면 agent-session이 재개 메시지를 한 번 보냅니다.\n")
NEW_CONVERSATION = ("서버를 내리기 전의 대화를 재개하지 못해 같은 seat에서 새 대화로 시작했습니다. "
                    "seat의 작업 파일·branch와 CR의 `## Result`를 확인하고 이어서 작업하십시오.")


def resume_text(slot, forced, resumed=(), failed=(), lost=False):
    """The one message a resumed conversation gets. The Leader's also names the other targets."""
    text = ("서버를 내리는 shutdown으로 이 대화의 CLI가 종료됐다가 같은 대화로 재개됐습니다. "
            "그 전에 실행하던 background 작업과 monitor는 모두 끝났습니다. 상태를 확인하고 하던 일을 이어 가십시오.")
    if lost:
        text = ("서버가 shutdown 없이 내려가(정전·crash 등) 이 대화의 CLI가 재부팅과 함께 종료됐다가 같은 대화로 재개됐습니다. "
                "그 전에 실행하던 background 작업과 monitor는 모두 끝났고, 실행 중이던 명령은 중간에 끊겨 결과가 없으니 "
                "다시 확인하십시오. 상태를 확인하고 하던 일을 이어 가십시오.")
    elif forced:
        text += (" shutdown이 제한 시간 안에 쉬지 않아 CLI를 강제 종료했습니다. 그때 실행 중이던 명령은 "
                 "중간에 끊겨 결과가 없으니 다시 확인하십시오.")
    if slot == "leader":
        text += "\n재개한 Worker: " + (", ".join(resumed) or "없음")
        text += "\n재개하지 못한 대상: " + (", ".join(failed) or "없음")
        text += ("\nWorker의 상태는 `<base>/agent/state.json`과 `project-item ls`로 확인하고, "
                 "재개하지 못한 Worker는 `agent-session start --job <CR>`로 새 대화를 시작할지 판단하십시오.")
    return text


class SuspendStore:
    """`<base>/agent/suspend.json`: the targets a shutdown ended, keyed by slot.

    The state file owns assignments and connections. A record only lets a resume check that the state
    still names the conversation the shutdown ended, and lets start run a slot that has no tmux evidence."""

    def __init__(self, project, timeout=600):
        self.path = project.runtime_path / "suspend.json"
        self.lock_path = project.runtime_path / "suspend.lock"
        self.timeout = timeout

    def read(self):
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeError, ValueError) as exc:
            raise SessionError("suspend_invalid", "Cannot read the shutdown record. Preserve the file.", 5,
                               {"path": str(self.path), "reason": str(exc)}) from exc
        if not isinstance(value, dict):
            raise SessionError("suspend_invalid", "The shutdown record must be an object.", 5, {"path": str(self.path)})
        for slot, entry in value.items():
            if (not isinstance(entry, dict) or not isinstance(slot, str)
                    or not (slot == "leader" or (slot.startswith("seat-") and slot[5:].isdigit()))
                    or set(entry) - {"lost"} != {"job_id", "run_id", "session_id", "suspended_at", "forced"}
                    or not isinstance(entry.get("lost", {}), dict)
                    or not all(isinstance(entry[key], str) and entry[key] for key in ("run_id", "session_id", "suspended_at"))
                    or not (entry["job_id"] is None or isinstance(entry["job_id"], str))
                    or not isinstance(entry["forced"], bool)):
                raise SessionError("suspend_invalid", "The shutdown record has an invalid entry.", 5,
                                   {"path": str(self.path), "slot": slot})
        return value

    def update(self, mutator):
        with locked(self.lock_path, timeout=self.timeout):
            value = self.read()
            mutator(value)
            write_json(self.path, value)
            return value

    def record(self, slot, job_id, run_id, session_id, forced, lost=None):
        """Record a slot. `lost` is the evidence of a `resume --lost` judgement; such a record is forced."""
        entry = {"job_id": job_id, "run_id": run_id, "session_id": session_id,
                 "suspended_at": utc_now(), "forced": bool(forced)}
        if lost is not None:
            entry["lost"] = lost
        self.update(lambda value: value.__setitem__(slot, entry))
        return entry

    def forget(self, slot, run_id=None):
        """Drop a slot's record; with a run, only the record of that run."""
        def drop(value):
            if slot in value and (run_id is None or value[slot]["run_id"] == run_id):
                del value[slot]
        if slot in self.read():
            self.update(drop)


class SuspendMixin:
    """One-target shutdown and resume steps of a project's Manager.

    The mixin relies on these members of the `lifecycle.Manager` it is mixed into; changing one of
    them there changes this contract:
    - attributes: `project`, `store`, `tmux`, `provider`
    - lock and deadline: `_lock(slot)`, `remaining()`
    - run evidence: `_owned`, `_observe`, `_session`, `_process_facts`, `_retire_name`,
      `_restore_stopping`
    - starting a conversation: `_context`, `_new_window`, `_launch`
    - messaging: `send`
    """

    def _slot_entry(self, slot, state):
        """The state's conversation and JOB of a slot."""
        if slot == "leader":
            return state["leader"], None
        row = state[slot[5:]]
        return row["session"], row["job_id"]

    def suspend_target(self, slot, deadline, force, progress):
        """End one slot's CLI for a shutdown and record it. `deadline` is a monotonic time.

        Return {"status": "recorded", ...}. A target that did not rest by the deadline raises
        target_busy (its stop block is lifted) or, with the exit unconfirmed, another SessionError."""
        state = self.store.read(missing_ok=True)
        session, job_id = self._slot_entry(slot, state)
        if not session:
            raise SessionError("session_unbound", "The slot has no bound conversation.", 4)
        with self._lock(slot):
            current = self.tmux.get_current(self.project.project_id, slot)
            if not current:
                raise SessionError("execution_unknown", "The target has no current execution evidence.", 4)
            if slot != "leader" and current.get("job_id") != job_id:
                raise SessionError("target_changed", "The JOB differs from the managed execution.")
            meta = self._owned(current, slot, state)
            progress.update(window_id=meta["window_id"], pane_id=meta["pane_id"])
            if meta.get("control_pending"):
                raise SessionError("control_busy", "This run has an accepted control request.", 4)
            if not meta.get("registered"):
                raise SessionError("session_unbound", "The provider conversation has not registered.", 4)
            forced = False
            if not self._observe(meta)["stopped"]:
                forced = self._end_for_shutdown(meta, deadline, force)
            try:
                self._retire_name(meta)
            except SessionError:
                pass                       # the name is only a label
            SuspendStore(self.project, self.remaining()).record(slot, job_id, meta["run_id"],
                                                                session["session_id"], forced)
            return {"status": "recorded", "job_id": job_id, "run_id": meta["run_id"],
                    "session_id": session["session_id"], "forced": forced}

    def _end_for_shutdown(self, meta, deadline, force):
        """Wait for the CLI to rest, ask it to end once, and confirm the end. Return whether it was forced.

        A CLI rests when it is idle with no background task (the provider's `terminal`). Without `force`
        one that is still working, or still has a background task, at the deadline is left running.
        With it, only the recorded CLI process whose birth matches gets SIGTERM; request_exit checks that
        identity. The provider's last report of background tasks cannot change after the CLI dies, so a
        forced end is confirmed from the processes: dead pane, CLI, process group, and tracked PIDs."""
        session = self._session(meta)
        self.provider.request_stop(session, meta, meta, timeout=self.remaining())
        self.tmux.write_meta(meta["window_id"], {"stopping": True})
        asked, forced = None, False
        try:
            while True:
                try:
                    observed = self._observe(meta)
                except SessionError as error:
                    # After the exit request, leaving the provider's listing is part of the end.
                    if asked is None or error.code != "session_not_bound":
                        raise
                    observed = None
                if observed is not None:
                    if observed["stopped"]:
                        return forced
                    if observed.get("idle") and observed.get("terminal") and asked is None:
                        self.provider.request_exit(meta, self.tmux)
                        asked = time.monotonic()
                if forced and self._processes_ended(meta):
                    return forced
                now = time.monotonic()
                if asked is None and now >= deadline:
                    if not force:
                        raise SessionError("target_busy", "The CLI was still working at the deadline.", 4)
                    self.provider.request_exit(meta, self.tmux)
                    asked, forced = now, True
                if asked is not None and now >= max(deadline, asked + EXIT_GRACE):
                    raise SessionError("exit_unconfirmed", "The CLI did not end after the exit request.", 4)
                time.sleep(max(0.05, min(POLL_SECONDS, (deadline if asked is None else
                                                        max(deadline, asked + EXIT_GRACE)) - now)))
        except BaseException as error:
            self._restore_stopping(meta, error)
            raise

    def _processes_ended(self, meta):
        """The pane is dead and neither the CLI, its process group, nor its tracked PIDs live."""
        pane = self.tmux.pane_info(meta["pane_id"])
        return bool(pane["pane_dead"] and not any(self._process_facts(meta, pane)))

    def relaunch(self, slot, record):
        """Start the recorded conversation again, in a new run and window, with `claude --resume`."""
        state = self.store.read()
        session, job_id = self._slot_entry(slot, state)
        if not session or session["session_id"] != record["session_id"] or job_id != record["job_id"]:
            raise SessionError("target_changed", "The state no longer names the conversation the shutdown ended.")
        with self._lock(slot):
            try:
                pointer = self.tmux.get_current(self.project.project_id, slot)
            except SessionError as error:
                if error.code != "execution_evidence_missing":
                    raise
                pointer = None             # the recorded run's window is gone; its new run replaces the pointer
            if pointer:
                self._owned(pointer, slot, state)
                if pointer["run_id"] != record["run_id"]:
                    raise SessionError("target_changed", "A newer run replaced the one the shutdown ended.")
                if not self._observe(pointer)["stopped"]:
                    raise SessionError("target_changed", "The run the shutdown ended is running again.")
                self._retire_name(pointer)
            try:
                job = None if slot == "leader" else jobs.lookup(self.project, job_id, ("in-progress",))
            except SessionError as error:
                if error.code != "cr_not_assignable":
                    raise
                raise SessionError("target_changed", "The Worker's CR is no longer in progress.", 3,
                                   {"job_id": job_id}) from error
            context = self._new_window(self._context(slot, job), resume=record["session_id"])
            try:
                result = self._launch(context, RESUME_PROMPT)
            except SessionError:
                self._abandon(context)
                raise
            SuspendStore(self.project, self.remaining()).forget(slot, record["run_id"])
            return result

    def _abandon(self, context):
        """After a failed resume launch whose CLI is gone and never registered, drop its pointer.

        The slot then has no tmux evidence and a record, so start can open a new conversation."""
        try:
            meta = self.tmux.get_current(self.project.project_id, context["target"])
            if (meta and meta.get("run_id") == context["run_id"] and not meta.get("registered")
                    and self.tmux.pane_info(meta["pane_id"])["pane_dead"]):
                self.tmux.clear_current(self.project.project_id, context["target"], context["run_id"])
                self._retire_name(meta)
        except SessionError:
            pass                           # the launch failure is the result

    def record_lost(self, slot):
        """Judge a slot that has a conversation and no shutdown record, and record it when a reboot ended it.

        The record is the one a forced shutdown leaves, plus the evidence of the judgement under `lost`, so the
        resume and start paths that follow need no other case. All of these must hold, and each one that does
        not is reported: no current execution pointer of the slot; the system booted after the conversation
        record was last written; no process names the conversation ID; a last run of the conversation exists.
        A check that cannot be made counts as not held. Raise lost_not_confirmed with `reasons` and `evidence`
        when any check fails; nothing is changed then. Return the record."""
        with self._lock(slot):
            state = self.store.read(missing_ok=True)
            session, job_id = self._slot_entry(slot, state)
            if not session:
                raise SessionError("session_unbound", "The slot has no bound conversation.", 4)
            conversation = session["session_id"]
            evidence, reasons, seconds = {}, [], {}

            def check(name, probe):
                try:
                    evidence.update(probe())
                except SessionError as error:
                    reasons.append({"check": name, "code": error.code, "message": error.message})

            def pointer():
                try:
                    current = self.tmux.get_current(self.project.project_id, slot)
                except SessionError as error:
                    if error.code != "execution_evidence_missing":
                        raise
                    raise SessionError("execution_present", "The slot's execution pointer remains; its window is gone.") from error
                if current:
                    raise SessionError("execution_present", "The slot has a current execution pointer.")
                return {"execution_pointer": None}

            def boot():
                seconds["boot"] = process.boot_time()
                return {"boot_time": _iso(seconds["boot"])}

            def transcript():
                root = self.project.base if slot == "leader" else self.project.seats[int(slot[5:])]
                if isinstance(root, RemoteSeat):
                    raise SessionError("remote_seat", "The conversation record of an SSH seat is on another host.")
                cwds = [root]
                if slot != "leader":
                    try:
                        cwds.append(self._context(slot, jobs.lookup(self.project, job_id, ("in-progress",)))["cwd"])
                    except SessionError as error:
                        raise SessionError("target_changed", "The Worker's CR is no longer in progress.") from error
                files = transcript_files(cwds, conversation)
                if not files:
                    raise SessionError("transcript_missing", "The conversation record file was not found.")
                latest = max(files, key=lambda path: path.stat().st_mtime)
                seconds["transcript"] = latest.stat().st_mtime
                return {"transcript": str(latest), "transcript_updated": _iso(seconds["transcript"])}

            def holders():
                found = process.session_holders(conversation)
                if found:
                    raise SessionError("cli_alive", "A process names the conversation ID.", 4, {"pids": found})
                return {"processes": []}

            def last_run():
                found = self._last_run(conversation)
                if not found:
                    raise SessionError("run_unknown", "No run of this conversation was found.")
                return {"run_id": found}

            for name, probe in (("pointer", pointer), ("boot", boot), ("transcript", transcript),
                                ("processes", holders), ("run", last_run)):
                check(name, probe)
            if "boot" in seconds and "transcript" in seconds and seconds["transcript"] >= seconds["boot"]:
                reasons.append({"check": "transcript", "code": "updated_after_boot",
                                "message": "The conversation record changed at or after the system boot."})
            if reasons:
                raise SessionError("lost_not_confirmed", "The slot is not confirmed as lost to a reboot.", 4,
                                   {"reasons": reasons, "evidence": evidence})
            lost = {"checked_at": utc_now(), **{key: value for key, value in evidence.items() if key != "run_id"}}
            return SuspendStore(self.project, self.remaining()).record(
                slot, job_id, evidence["run_id"], conversation, True, lost=lost)

    def _last_run(self, conversation):
        """The newest run whose launch script names the conversation, or None."""
        newest, found = -1.0, None
        for script in (self.project.runtime_path / "runs").glob("*/launch.sh"):
            try:
                if conversation in script.read_text(encoding="utf-8") and script.stat().st_mtime > newest:
                    newest, found = script.stat().st_mtime, script.parent.name
            except (OSError, UnicodeError):
                continue
        return found

    def is_suspended(self, slot, item):
        """Whether a shutdown record, and nothing else, names this slot's JOB and conversation."""
        record = SuspendStore(self.project, self.remaining()).read().get(slot)
        session, job_id = self._slot_entry(slot, self.store.read(missing_ok=True))
        return bool(record and session and record["session_id"] == session["session_id"]
                    and record["job_id"] == job_id == item["job_id"])

    def start_suspended(self, slot, item):
        """Open a new conversation in a slot that has a shutdown record and no run."""
        with self._lock(slot):
            if self.tmux.get_current(self.project.project_id, slot) is not None or not self.is_suspended(slot, item):
                raise SessionError("target_changed", "The slot's shutdown evidence changed before its start.")
            job = jobs.claim(self.project, item["job_id"])
            context = self._new_window(self._context(slot, job))
            result = self._launch(context, NEW_CONVERSATION)
            SuspendStore(self.project, self.remaining()).forget(slot)
            return result

    def notify_resumed(self, slot, text):
        """Send the resume message once through the common send path."""
        if slot == "leader":
            return self.send(job="leader", message=text)
        return self.send(seat=int(slot[5:]), message=text)


def _iso(seconds):
    return dt.datetime.fromtimestamp(seconds, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Alarm:
    """Tell every attached tmux client, and flag the windows that have not rested."""

    def __init__(self, tmux, command, force, clock):
        self.tmux, self.command, self.force, self.clock = tmux, command, force, clock
        self.log = []

    def fire(self, event, targets, total, deadline_text):
        # A finished thread can leave its CLI busy or its exit unconfirmed.
        pending = [target for target in targets if (target["outcome"] or {}).get("status") != "recorded"]
        names = ", ".join(f"{target['project']}:{target['slot']}" for target in pending) or "없음"
        if event == "start":
            text = (f"agent shutdown: 대상 {total}, 강제 종료 시각 {deadline_text}" if self.force else
                    f"agent shutdown: 대상 {total}, 대기 마감 시각 {deadline_text} (--force 없음, 강제 종료하지 않음)")
        else:
            action = ("마감에 강제 종료합니다." if self.force and event == "warn" else
                      "강제 종료합니다." if self.force else
                      f"강제 종료하려면 `{self.command} --force`를 다시 실행하십시오.")
            lead = f"{WARN_LEAD}초 뒤 마감합니다. " if event == "warn" else "마감했습니다. "
            text = f"agent shutdown: {lead}남은 대상 {len(pending)}: {names}. {action}"
        entry = {"event": event, "text": text, "clients": None, "bells": 0, "errors": []}
        try:
            entry["clients"] = self.tmux.notify(text, ALARM_MILLISECONDS)
        except SessionError as error:
            entry["errors"].append(error.code)
        if event != "start":
            for target in pending:
                if not target.get("pane_id"):
                    continue
                try:
                    self.tmux.ring_bell(target["pane_id"])
                    entry["bells"] += 1
                except SessionError as error:
                    entry["errors"].append(error.code)
        self.log.append(entry)


class Fleet:
    """The operator's shutdown and resume over registered projects."""

    def __init__(self, manager_factory, config_path=None, socket_name=None, socket_path=None, timeout=600):
        self.manager_factory = manager_factory      # called as (base, config_path, timeout=, socket_name=, socket_path=)
        self.config_path = config_path
        self.socket = {"socket_name": socket_name, "socket_path": socket_path}
        self.timeout = timeout
        self.tmux = Tmux(**self.socket)

    def _select(self, name, everything):
        registry = load_registry(self.config_path)
        if everything:
            return registry, list(registry)
        chosen = [project for project in registry if project.project_id == name]
        if not chosen:
            raise SessionError("project_not_found", "The project is not registered.", 2, {"project": name})
        return registry, chosen

    def _manager(self, project, seconds):
        return self.manager_factory(project.base, project.config_path, timeout=seconds, **self.socket)

    def _authorize(self, registry, selected, operation):
        """Only an operator may run these. A managed or agent caller of any registered project is refused
        before anything is touched."""
        for project in registry:
            try:
                self._manager(project, 30)._authorize(operation, "leader")
            except SessionError as error:
                if error.code in ("role_denied", "caller_unbound") or project in selected:
                    raise                  # an unreadable project that is not selected cannot name the caller

    def _command(self, name, everything, operation):
        parts = ["agent-session"]
        if self.config_path:
            parts += ["--config", str(self.config_path)]
        if self.socket["socket_name"]:
            parts += ["--socket-name", self.socket["socket_name"]]
        if self.socket["socket_path"]:
            parts += ["--socket-path", self.socket["socket_path"]]
        parts += [operation, "--all"] if everything else [operation, "--project", name]
        return shlex.join(parts)

    @staticmethod
    def _skipped(project):
        return {"project": project.project_id, "provider": project.provider, "targets": [],
                "skipped": [{"slot": None, "reason": "provider_not_supported",
                             "message": "Only Claude projects are shut down and resumed."}]}

    # shutdown

    def _plan(self, project):
        if project.provider != SUPPORTED_PROVIDER:
            return self._skipped(project)
        manager = self._manager(project, self.timeout + EXIT_GRACE + LOCK_SLACK)
        state = manager.store.read(missing_ok=True)
        plan = {"project": project.project_id, "provider": project.provider, "targets": [], "skipped": []}
        slots = [("leader", state["leader"])] + [(f"seat-{key}", row["session"]) for key, row in state.items()
                                                  if key != "leader" and row["job_id"] is not None]
        for slot, session in slots:
            if slot == "leader" and not session:
                continue
            if not session:
                plan["skipped"].append({"slot": slot, "reason": "no_conversation",
                                        "message": "The seat is reserved but its conversation never registered."})
                continue
            target = {"project": project.project_id, "slot": slot, "done": False, "outcome": None,
                      "window_id": None, "pane_id": None, "_project": project}
            try:
                meta = manager.tmux.get_current(project.project_id, slot)
                if meta:
                    target.update(window_id=meta.get("window_id"), pane_id=meta.get("pane_id"))
            except SessionError:
                pass                       # the target thread reports why its run is unavailable
            plan["targets"].append(target)
        return plan

    def _run_target(self, target, deadline, force):
        started = time.monotonic()
        try:
            manager = self._manager(target["_project"], deadline + EXIT_GRACE + LOCK_SLACK - started)
            outcome = manager.suspend_target(target["slot"], deadline, force, target)
        except SessionError as error:
            outcome = {"status": "busy" if error.code == "target_busy" else "unknown", "error": error.as_dict()}
        except Exception as error:         # a bug in one target must not hide the others
            outcome = {"status": "unknown", "error": {"code": "internal_error", "message": type(error).__name__,
                                                      "details": {}}}
        target["outcome"] = outcome
        target["done"] = True

    def _run_project(self, plan, deadline, force):
        workers = [t for t in plan["targets"] if t["slot"] != "leader"]
        threads = [threading.Thread(target=self._run_target, args=(t, deadline, force)) for t in workers]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        for target in plan["targets"]:
            if target["slot"] == "leader":
                self._run_target(target, deadline, force)   # the Leader rests only after its Workers

    def shutdown(self, project=None, everything=False, force=False):
        registry, selected = self._select(project, everything)
        self._authorize(registry, selected, "shutdown")
        started = time.monotonic()
        deadline = started + self.timeout
        plans = [self._plan(item) for item in selected]
        targets = [target for plan in plans for target in plan["targets"]]
        deadline_text = time.strftime("%H:%M:%S", time.localtime(time.time() + self.timeout))
        alarm = Alarm(self.tmux, self._command(project, everything, "shutdown"), force, deadline_text)
        threads = [threading.Thread(target=self._run_project, args=(plan, deadline, force)) for plan in plans
                   if plan["targets"]]
        for thread in threads:
            thread.start()
        events = []
        if targets:
            events.append(("start", started))
            if self.timeout > WARN_LEAD:
                events.append(("warn", deadline - WARN_LEAD))
            events.append(("deadline", deadline))
        while any(thread.is_alive() for thread in threads):
            while events and time.monotonic() >= events[0][1]:
                alarm.fire(events.pop(0)[0], targets, len(targets), deadline_text)
            time.sleep(0.2)
        for thread in threads:
            thread.join()
        return self._shutdown_result(plans, force, alarm, project, everything)

    def _shutdown_result(self, plans, force, alarm, project, everything):
        projects, remaining = [], 0
        for plan in plans:
            row = {"project": plan["project"], "provider": plan["provider"], "recorded": [], "busy": [],
                   "unknown": [], "skipped": plan["skipped"]}
            for target in plan["targets"]:
                outcome = {"slot": target["slot"], **target["outcome"]}
                status = outcome.pop("status")
                row[status].append(outcome)
            remaining += len(row["busy"]) + len(row["unknown"])
            projects.append(row)
        result = {"force": force, "projects": projects, "alarms": alarm.log}
        if remaining:
            result["rerun"] = self._command(project, everything, "shutdown") + ("" if force else " --force")
            raise SessionError("shutdown_incomplete", f"{remaining} target(s) did not end; no record was made "
                               "for them.", 4, result)
        return result

    # resume

    def _judge_lost(self, project, end, records, outcome):
        """For `resume --lost`: add a record for each slot with a conversation, no record, and a reboot behind it.

        The slots that fail the judgement go to `outcome["rejected"]` with their reasons and keep their assignment."""
        state = self._manager(project, max(1.0, end - time.monotonic())).store.read(missing_ok=True)
        slots = [("leader", state["leader"], None)] + [(f"seat-{key}", row["session"], row["job_id"])
                                                        for key, row in state.items()
                                                        if key != "leader" and row["job_id"] is not None]
        for slot, session, job_id in slots:
            if slot in records or (slot == "leader" and not session):
                continue
            if not session:
                outcome.setdefault("skipped", []).append({
                    "slot": slot, "reason": "no_conversation",
                    "message": "The seat is reserved but its conversation never registered."})
                continue
            try:
                manager = self._manager(project, max(1.0, end - time.monotonic()))
                manager.end = end
                records[slot] = manager.record_lost(slot)
            except SessionError as error:
                outcome.setdefault("rejected", []).append({"slot": slot, "job_id": job_id,
                                                           "session_id": session["session_id"],
                                                           "error": error.as_dict()})
            except Exception as error:
                outcome.setdefault("rejected", []).append({
                    "slot": slot, "job_id": job_id, "session_id": session["session_id"],
                    "error": {"code": "internal_error", "message": type(error).__name__, "details": {}}})

    def _resume_project(self, project, end, outcome, judge_lost=False):
        if project.provider != SUPPORTED_PROVIDER:
            outcome.update(self._skipped(project))
            return
        seconds = max(1.0, end - time.monotonic())
        records = SuspendStore(project, seconds).read()
        if judge_lost:
            self._judge_lost(project, end, records, outcome)
        slots = sorted(records, key=lambda slot: (slot != "leader", int(slot[5:]) if slot != "leader" else 0))
        resumed, failed = [], []
        for slot in slots:
            record = records[slot]
            row = {"slot": slot, "job_id": record["job_id"], "session_id": record["session_id"],
                   "forced": record["forced"]}
            if "lost" in record:
                row["lost"] = record["lost"]
            try:
                manager = self._manager(project, max(1.0, end - time.monotonic()))
                manager.end = end
                result = manager.relaunch(slot, record)
                row.update(status="resumed", run_id=result["run_id"], window_id=result["window_id"])
                resumed.append((slot, manager, row))
            except SessionError as error:
                row.update(status="failed", error=error.as_dict(),
                           fallback=None if slot == "leader" else f"agent-session start --job {record['job_id']}")
                failed.append(row)
            except Exception as error:
                row.update(status="failed", error={"code": "internal_error", "message": type(error).__name__,
                                                   "details": {}})
                failed.append(row)
            if row["status"] == "failed":
                outcome.setdefault("rows", []).append(row)
        # Workers hear first; the Leader's message then names who is back and who is not.
        worker_names = [f"{slot}({row['job_id']})" for slot, _, row in resumed if slot != "leader"]
        lost = [f"{row['slot']}({row['job_id']}): {row['error']['code']}" for row in failed if row["slot"] != "leader"]
        for slot, manager, row in sorted(resumed, key=lambda item: item[0] == "leader"):
            text = resume_text(slot, row["forced"], worker_names, lost, "lost" in row)
            try:
                manager.notify_resumed(slot, text)
                row["message"] = "sent"
            except SessionError as error:
                row["message"] = error.as_dict()
            outcome.setdefault("rows", []).append(row)

    def resume(self, project=None, everything=False, lost=False):
        registry, selected = self._select(project, everything)
        self._authorize(registry, selected, "resume")
        end = time.monotonic() + self.timeout
        outcomes = [{"project": item.project_id, "provider": item.provider} for item in selected]

        def run(item, outcome):
            try:
                self._resume_project(item, end, outcome, lost)
            except SessionError as error:
                outcome["error"] = error.as_dict()
            except Exception as error:
                outcome["error"] = {"code": "internal_error", "message": type(error).__name__, "details": {}}

        threads = [threading.Thread(target=run, args=(item, outcome)) for item, outcome in zip(selected, outcomes)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        projects, problems = [], 0
        for outcome in outcomes:
            rows = outcome.get("rows", [])
            row = {"project": outcome["project"], "provider": outcome["provider"],
                   "resumed": [r for r in rows if r["status"] == "resumed"],
                   "failed": [r for r in rows if r["status"] == "failed"],
                   "skipped": outcome.get("skipped", [])}
            if lost:
                row["rejected"] = outcome.get("rejected", [])
                problems += len(row["rejected"])
            if "error" in outcome:
                row["error"] = outcome["error"]
                problems += 1
            problems += len(row["failed"])
            projects.append(row)
        result = {"projects": projects}
        if problems:
            raise SessionError("resume_incomplete", f"{problems} target(s) were not resumed; their records "
                               "and assignments remain.", 4, result)
        return result
