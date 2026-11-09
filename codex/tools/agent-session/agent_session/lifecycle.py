"""Project session commands, Git preparation, and confirmed slot release."""

import json
import os
import shlex
import sys
import time
import uuid
from pathlib import Path

from . import api, background, git_ops, jobs, process, workspace
from .config import RemoteSeat, current_project, load_registry
from .errors import SessionError
from .providers import get_provider
from .state import StateStore, locked, utc_now
from .suspend import SuspendMixin, SuspendStore
from .tmux import Tmux, check_owner
from .util import write_json

HOST_SECONDS = 8                                   # wait for the provider's background listing
SWEEP_SECONDS = 30                                 # after this, a cleanup leaves later windows to the next sweep
DIALOG_SCREEN_SECONDS = 1                          # how often an unregistered start reads its pane for a dialog
REUSE_REFUSED = ("target_changed", "tmux_owner_mismatch", "target_running", "window_unreusable")
PARKED_ALIVE = "The parked JOB still has a run; stop it before starting the JOB again."


def _bound(previous, session, leader=False):
    """A republished conversation keeps its connection time and review; a new one starts both."""
    if previous and previous.get("session_id") == session["session_id"]:
        return {**previous, **session}
    fresh = {**session, "connected_at": utc_now()}
    if leader:
        fresh["reviewing"] = None
    return fresh


def _completed(result_file):
    try:
        return json.loads(Path(result_file).read_text(encoding="utf-8"))["data"]["completed"] is True
    except (OSError, ValueError, KeyError, TypeError):
        return False


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


class Manager(SuspendMixin):
    def __init__(self, cwd=None, config_path=None, socket_name=None, socket_path=None, timeout=600):
        self.project = current_project(cwd, config_path)
        self.timeout = timeout
        self.end = time.monotonic() + timeout
        self.store = StateStore(self.project, timeout=timeout)
        self.socket = {"socket_name": socket_name, "socket_path": socket_path}
        self.tmux = Tmux(**self.socket)
        self.provider = get_provider(self.project.provider)

    def remaining(self):
        value = self.end - time.monotonic()
        if value <= 0:
            raise SessionError("timeout", "The command's total wait limit expired.", 4)
        self.store.timeout = value
        return value

    def _lock(self, slot):
        return locked(self.project.runtime_path / "control" / f"{slot}.lock", self.remaining())

    def _authorize(self, operation, slot):
        actor, identity = api.caller(self.project, self.tmux, self.store)
        if actor == "unmanaged-agent":
            if operation == "start" and slot == "leader":
                return actor, identity
            raise SessionError("caller_unbound", "This agent is not a registered member of this project.")
        if operation in ("shutdown", "resume") and actor != "operator":
            raise SessionError("role_denied", f"Only the operator may {operation} the project sessions.")
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
            "python": sys.executable, "library_path": str(Path(__file__).resolve().parents[1]),
            "timeout": self.remaining(), "allow_daemon_start": True,
        }
        if remote:
            context["remote_seat"] = {"host": root.host, "path": str(root.path), "python": root.python}
        return context

    def _window_name(self, meta):
        if meta["seat"] is None:
            return f"{self.project.project_id}-leader"
        return f"{self.project.project_id}-seat{meta['seat']}-{meta['job_id']}"

    def _new_window(self, context, resume=None, ending=None):
        """A run and its window. With `resume`, the run reopens that conversation instead of a new one.

        The slot's retired window is handed to the run when `_reusable` accepts it, so the panes that a
        person added stay beside the new CLI. `ending` is the run that this restart's own controller just
        ended; it is the one run whose pending control does not keep its window from the new run.
        """
        context = context if context.get("remote_seat") else self.provider.prepare_context(context)
        if resume:
            context.update(session_id=resume, expected_session_id=resume, resume=True)
        name = self._window_name(context)
        context["window_name"] = name
        # The waiting pane starts in the seat root; the launch script enters the CR's Cwd after Git preparation.
        cwd = context["cwd"]
        physical_root = str(self.project.base) if context.get("remote_seat") else context["seat_root"]
        retired = self._reusable(context["target"], ending)
        reused = None
        if retired is not None:
            try:
                reused = self.tmux.reuse_window(self.project.project_id, name, physical_root, context, retired)
            except SessionError as error:
                if error.code not in REUSE_REFUSED:
                    raise                          # the window may have changed; its state is the caller's to read
        context = reused or self.tmux.create_window(self.project.project_id, name, physical_root, context)
        if context["cwd"] != cwd:
            context = self.tmux.write_meta(context["window_id"], {"cwd": cwd})
        self.tmux.set_current(self.project.project_id, context["target"], context)
        if context["seat"] is None:
            self.tmux.command("select-window", "-t", self.project.project_id + ":" + context["window_id"])
        return context

    def _reusable(self, target, ending=None):
        """The retired window that the slot's next run takes over, or None to open a new window.

        With a current pointer, only its window counts. Without one (after a release), the window of the
        slot's most recent run counts; recency is the time of the run's launch script. The window must
        be one `_sweep` would accept as ended, except that a person's panes in it do not matter.
        """
        try:
            meta = self.tmux.get_current(self.project.project_id, target)
            if meta is None:
                runs = self.project.runtime_path / "runs"
                found = []
                for window_id in self.tmux.managed_windows(self.project.project_id, target):
                    candidate = self.tmux.read_meta(window_id)
                    script = runs / str(candidate.get("run_id")) / "launch.sh"
                    found.append((script.stat().st_mtime if script.is_file() else 0.0, candidate))
                if not found:
                    return None
                meta = max(found, key=lambda item: item[0])[1]
            own = ending is not None and meta.get("run_id") == ending.get("run_id")
            return meta if self._retained(meta, controller=own) is None else None
        except SessionError:
            return None

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

    def _write_prompt(self, context, request=None):
        code = ("import sys; sys.path.insert(0,sys.argv[1]); "
                "from agent_session.internal import register_current; "
                "register_current(run_id=sys.argv[2],config_path=sys.argv[3],"
                "socket_path=sys.argv[4],endpoint=sys.argv[5])")
        command = shlex.join([context["python"], "-c", code, context["library_path"],
                              context["run_id"], context["config_path"], context["socket_path"],
                              context.get("endpoint") or ""])
        if context.get("resume"):
            return request                 # the conversation exists; the resume message is sent after registration
        role = "Leader" if context["seat"] is None else "Worker"
        text = "$project-team을 사용하십시오. 현재 프로젝트의 " + role + " 역할입니다.\n"
        if self.project.provider == "codex":
            text += ("첫 도구 호출에서 다음 내부 등록을 실행하십시오. 작업 디렉토리는 " + context["cwd"]
                     + "입니다. 등록 성공 전에는 일반 작업을 시작하지 마십시오.\n\n" + command + "\n\n")
        else:
            text += "SessionStart 내부 등록이 실패하면 작업을 시작하지 마십시오.\n\n"
        if context.get("handoff_file"):
            path = Path(context["handoff_file"])
            text += "이전 대화는 보존됐습니다. 다음 인계로 같은 작업을 이어받으십시오.\n" + path.read_text(encoding="utf-8") + "\n"
        job = context.get("job")
        if job:
            base = (job.get("base") or {}).get("base_hash") or "준비 중"
            text += ("배정 CR: " + job["job_id"] + " (" + job["title"] + ")\n"
                     + "CR 파일: " + job["path"] + "\n"
                     + "Seat: " + context["seat_root"] + "\n"
                     + "작업 디렉토리: " + context["cwd"] + "\n"
                     + "Mode: " + job["mode"] + "\n"
                     + "Branch: " + (job.get("branch") or "없음(read-only)") + "\n"
                     + "Base: " + base + "\n\n"
                     + "작업 전에 위 CR 파일을 읽고, 그 본문이 link한 지침 문서도 읽으십시오. "
                     + "범위·구현·검증 기준의 원본은 CR 파일입니다.\n\n")
        text += request or (
            "인계 문서와 프로젝트 지침을 읽고 승인된 미완료 작업을 계속하십시오." if context.get("handoff_file") else
            "프로젝트 지침과 `project-item ls`의 결정 대기·CR을 확인하고 사용자 작업 지시를 기다리십시오. "
            "사용자에게 묻는 결정은 결정 항목으로 남기고, 위임 범위의 판정은 근거와 함께 CR에 기록하십시오(project-team skill)."
            if job is None else
            "CR의 범위에서 작업하고 검증하십시오. 제출 commit과 검증 결과를 CR 파일의 `## Result`에 쓰고 "
            "`agent-session send --job leader`로 보고하십시오.")
        if len(text.encode("utf-8")) > 65536:
            raise SessionError("prompt_too_large", "Initial JOB and handoff exceed 65536 UTF-8 bytes.", 2)
        return text

    def _prepare_launch(self, context, request=None):
        if context.get("remote_seat"):
            return {}, {}
        if self.project.provider == "codex" and context["target"] == "leader":
            self.provider.trust_base(self.project.base)
        context["timeout"] = self.remaining()
        directory = self.project.runtime_path / "runs" / context["run_id"]
        directory.mkdir(parents=True, exist_ok=True)
        hooks = self.provider.registration_hooks(context)
        prepared = self._session_input(context, hooks, self._write_prompt(context, request))
        prepared.setdefault("env", {}).update({
            "AGENT_SESSION_CONFIG": context["config_path"],
            "AGENT_SESSION_SOCKET": context["socket_path"],
            "AGENT_SESSION_BASE": context["base"],
        })
        if context.get("upstream"):
            prepared["env"].update(AGENT_SESSION_UPLINK=context["upstream"],
                                   PYTHONPATH=context["library_path"],
                                   PATH=context["upstream_bin"] + os.pathsep + os.environ.get("PATH", ""))
        launch = self.provider.launch_spec(context, prepared)
        return prepared, launch

    def _session_input(self, context, hooks, prompt):
        """Provider input from the common prompt and the project's launch args for this role."""
        directory = self.project.runtime_path / "runs" / context["run_id"]
        path = directory / "prompt.md"
        path.write_text(prompt, encoding="utf-8")
        role = "leader" if context["target"] == "leader" else "worker"
        prepared = {"prompt_file": str(path), "provider_args": list(self.project.args_for(role)),
                    "env": {}, "unset_env": [], "settings_file": None}
        if self.project.provider == "claude":
            settings = {"crossSessionInbound": "accept", "hooks": hooks}
            settings_path = directory / "settings.json"
            write_json(settings_path, settings)
            prepared.update(settings_file=str(settings_path), provider_name=context.get("window_name"))
        return prepared

    def _handoff_path(self, meta):
        return self.project.runtime_path / "handoff" / f"{meta['target']}.md"

    def _fresh_handoff(self, meta):
        """The slot's handoff file when it changed after this run's launch, else None."""
        if meta.get("remote_seat"):
            from .remote import run_call
            handoff = run_call(meta, "handoff", timeout=self.remaining())
            if handoff.get("fresh"):
                path = self._handoff_path(meta)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(handoff["text"], encoding="utf-8")
                return str(path)
            return None
        path = self._handoff_path(meta)
        launched = self.project.runtime_path / "runs" / meta["run_id"] / "launch.sh"
        if path.is_file() and launched.is_file() and path.stat().st_mtime > launched.stat().st_mtime:
            return str(path)
        return None

    def _require_handoff(self, meta):
        handoff = self._fresh_handoff(meta)
        if handoff is None:
            raise SessionError("handoff_required", "Write the slot's handoff file during this run before restart.",
                               3, {"path": str(self._handoff_path(meta)), "run_id": meta["run_id"]})
        return handoff

    def _discard_placeholder(self, meta):
        """End the unlaunched waiting pane of a start that failed before its reservation held."""
        try:
            self.tmux.request_placeholder_stop(meta["window_id"])
            current = self.tmux.get_current(self.project.project_id, meta["target"])
            while not self._observe(current)["stopped"]:
                time.sleep(min(0.1, self.remaining()))
            self._retire_name(current)
        except SessionError:
            pass                                   # the original failure is the result

    def _launch(self, context, request=None):
        if context.get("remote_seat"):
            from .remote_lifecycle import launch
            return launch(self, context)
        if not Path(context["cwd"]).is_dir():
            raise SessionError("cwd_unavailable", "The CR Cwd does not exist in the prepared seat.", 2,
                               {"cwd": context["cwd"]})
        directory = self.project.runtime_path / "runs" / context["run_id"]
        prepared, launch = self._prepare_launch(context, request)
        self.tmux.write_meta(context["window_id"], {
            "provider_name": prepared.get("provider_name"), "launch_file": str(directory / "launch.sh"),
            "stopping": False,
        })
        code = ("import sys;sys.path.insert(0,sys.argv[1]);from agent_session.internal import mark_process;"
                "mark_process(sys.argv[2],sys.argv[3],sys.argv[4],int(sys.argv[5]))")
        marker = shlex.join([context["python"], "-c", code, context["library_path"], context["run_id"],
                             context["config_path"], context["socket_path"]]) + ' "$$"'
        clean = [key for key in os.environ if key.startswith("CLAUDE_CODE_MESSAGING_") or key.startswith("AGENT_SESSION_")]
        clean += ["CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"] + launch.get("unset_env", [])
        lines = ["#!/bin/bash", "set -e",
                 'for name in ${!CLAUDE_CODE_MESSAGING_@} ${!AGENT_SESSION_@}; do unset "$name"; done',
                 "unset " + " ".join(shlex.quote(key) for key in sorted(set(clean))),
                 "cd " + shlex.quote(context["cwd"]), marker]
        for name, value in launch.get("env", {}).items():
            lines.append("export " + name + "=" + shlex.quote(value))
        lines.append("exec " + shlex.join(launch["argv"]))
        script = directory / "launch.sh"
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        context = self.tmux.launch(context["window_id"], context["cwd"], script)
        result = self._wait_ready(context)
        return {**result, "cleanup": self._sweep(context["target"])}

    def _pointer_run(self, target):
        try:
            current = self.tmux.get_current(self.project.project_id, target)
        except SessionError as error:
            if error.code == "execution_evidence_missing":
                return error.details.get("run_id")
            raise
        return current.get("run_id") if current else None

    def _retained(self, meta, owner=None, controller=False):
        """Why a retired window must stay, or None when its run ended without pending control.

        With `controller`, this process may be the controller that is restarting the run: then the run's
        own pending control and controller record do not count. Any other pending control does.
        """
        if not meta.get("base") or Path(meta["base"]).resolve() != self.project.base or not meta.get("pane_id"):
            return "foreign_window"
        pid, birth = meta.get("controller_pid"), meta.get("controller_birth")
        mine = bool(controller and meta.get("control_pending") and meta.get("control_operation") == "restart"
                    and pid == os.getpid() and birth == process.birth(os.getpid()))
        if not mine:
            if meta.get("control_pending"):
                return "control_pending"
            if pid and process.alive(int(pid), birth):
                # The finishing self-controller may close its own run after it saved the completed result.
                own = (owner is not None and owner["run_id"] == meta.get("run_id")
                       and owner["pid"] == int(pid) and owner["birth"] == birth
                       and _completed(owner["result_file"]))
                if not own:
                    return "controller_running"
        if not self._observe(meta)["stopped"]:
            return "termination_unconfirmed"
        return None

    def _sweep(self, target, owner=None):
        """Close the slot's retired windows; the current pointer's run and unsure windows stay.

        The caller holds the slot's control lock, so the current pointer cannot change meanwhile.
        """
        closed, kept = [], []
        deadline = time.monotonic() + SWEEP_SECONDS
        try:
            current = self._pointer_run(target)
            handles = self.tmux.managed_windows(self.project.project_id, target)
        except SessionError as error:
            return {"closed": closed, "kept": [{"window_id": None, "reason": error.code}]}
        for window_id in handles:
            try:
                meta = self.tmux.read_meta(window_id)
                if meta.get("run_id") == current:
                    continue
                if time.monotonic() >= deadline:
                    reason = "cleanup_budget"
                else:
                    reason = self._retained(meta, owner)
                    if reason is None:
                        self.tmux.close_window(window_id, meta)
                        closed.append(window_id)
                        continue
            except SessionError as error:
                reason = error.code
            kept.append({"window_id": window_id, "reason": reason})
        return {"closed": closed, "kept": kept}

    def sweep_after_result(self, target, owner):
        """The self-controller's last cleanup, serialized with the slot's other commands."""
        try:
            with locked(self.project.runtime_path / "control" / f"{target}.lock", self.remaining(),
                        blocking=False):
                return self._sweep(target, owner=owner)
        except SessionError as error:
            # A busy slot's command sweeps when it finishes; nothing is closed without the lock.
            return {"closed": [], "kept": [{"window_id": None, "reason": error.code}]}

    def _wait_ready(self, context):
        screened = 0.0
        while True:
            self.remaining()
            meta = self.tmux.get_current(self.project.project_id, context["target"])
            if not meta or meta.get("run_id") != context["run_id"]:
                raise SessionError("target_changed", "Another execution replaced this startup.")
            if meta.get("remote_seat"):
                from .remote_lifecycle import poll
                meta = poll(self, meta)
            if meta.get("registered"):
                if not meta.get("ready"):
                    session = self._session(meta)
                    self._same(meta, published=False)
                    def publish(value):
                        if meta["seat"] is None:
                            value["leader"] = _bound(value["leader"], session, leader=True)
                        else:
                            key = str(meta["seat"])
                            if value[key]["job_id"] != meta["job_id"]:
                                raise SessionError("target_changed", "The JOB changed before binding publication.")
                            value[key]["session"] = _bound(value[key]["session"], session)
                    self.store.update(publish)
                    meta = self.tmux.write_meta(meta["window_id"], {"ready": True, "start_error": None})
                return self._result(meta, ready=True)
            failure = meta.get("start_error")
            if isinstance(failure, dict):
                # The registration hook recorded why it failed; the run's CLI stays alive, so nothing else ends this wait.
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
                                       "the window, then run the same start again.", 3,
                                       {**self._result(meta), "dialog": dialog})
            time.sleep(min(0.1, self.remaining()))

    def _result(self, meta, **extra):
        return {"project": self.project.project_id, "seat": meta.get("seat"), "job_id": meta.get("job_id"),
                "run_id": meta.get("run_id"), "window_id": meta.get("window_id"),
                "pane_id": meta.get("pane_id"), "cwd": meta.get("cwd"),
                "session": self._session(meta) if meta.get("registered") else None,
                **({"host": meta["remote_seat"]["host"], "remote_native": meta.get("remote_native")}
                   if meta.get("remote_seat") else {}), **extra}

    def _retire_name(self, meta):
        self.tmux.command("rename-window", "-t", meta["window_id"],
                          self._window_name(meta) + "-exited-" + meta["run_id"][:8])

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
        handoff = self._fresh_handoff(meta)
        self._retire_name(meta)
        context = self._context(meta["target"], job)
        context["handoff_file"] = _handoff(handoff)
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
                SuspendStore(self.project, self.remaining()).forget("leader")   # a new conversation ends the record
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
                    candidate_guard = locked(self.project.runtime_path / "control" / f"{slot}.lock",
                                             self.remaining(), blocking=False)
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
                                self._discard_placeholder(context)
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
            reply_job, sender_run = None, None
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
            if actor == "leader" and meta.get("job_id"):
                # Feedback returns the JOB to its Worker; a later Leader's review stays.
                try:
                    self._clear_review(meta["job_id"], leader_session_id=identity)
                except SessionError as error:
                    # The message was accepted; reporting a failure here would invite a duplicate send.
                    outcome["review_clear_error"] = error.as_dict()
            return outcome

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
            handoff = self._require_handoff(meta) if operation == "restart" else None
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
                context["handoff_file"] = _handoff(handoff)
                context = self._new_window(context, ending=meta)
                result = self._launch(context)
                if result["session"]["session_id"] == meta["session_id"]:
                    raise SessionError("conversation_reused", "Restart must create a new conversation.")
                result = {**result, "previous_session": self._session(meta), "restarted": True}
                # _launch already swept once the new run became current; a self-controller sweeps again
                # after it saved its result, when its own pending window may close.
                return {**result, "deferred_cleanup": meta["target"]} if defer_cleanup else result
            check = workspace.check_release(self.project, meta, jobs.state_of(self.project, meta["job_id"])
                                            if meta.get("job_id") else (None, None))
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
            elif meta.get("job_id"):
                self._clear_review(meta["job_id"])
            result = self._result(meta, stopped=True, released=bool(check.get("allowed")),
                                  reasons=check.get("reasons", []))
            return self._finish_control(result, meta, defer_cleanup, pointer_kept)

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
        return {**result, "cleanup": {"closed": cleanup["closed"], "kept": list(kept) + cleanup["kept"]}}

    def _self_control(self, operation, meta, job, seat):
        directory = self.project.runtime_path / "runs" / meta["run_id"]
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
            code = "import sys;sys.path.insert(0,sys.argv[1]);from agent_session.internal import run_controller;run_controller(sys.argv[2])"
            command = shlex.join([sys.executable, "-c", code, str(Path(__file__).resolve().parents[1]), str(request_file)])
            script = directory / "controller.sh"
            script.write_text("#!/bin/bash\nset -e\nunset CODEX_THREAD_ID CLAUDE_CODE_SESSION_ID TMUX TMUX_PANE\nexec " + command + "\n", encoding="utf-8")
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


def _handoff(value):
    if isinstance(value, dict):
        value = value.get("handoff_file") or value.get("path")
    if value is None:
        return None
    path = Path(value).resolve()
    if not path.is_file():
        raise SessionError("handoff_missing", "The project handoff document is unavailable.")
    return str(path)
