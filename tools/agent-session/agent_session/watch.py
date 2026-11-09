"""Wake a Worker that rests with its CR in progress, and tell the Leader.

`WatchMixin` is the one-target judgement of a project's `Manager`. `Watch` is the command: it selects
projects from the registry and runs the judgement for every Worker seat once. The operator runs it by
hand; the Leader runs it for its own project from its own session cron (spec 7, watch).

A Worker rests when its turn has ended (or only a background shell runs), no input arrived since, and
it is not waiting for the Leader. Watch then sends the Worker one message with the evidence (CR, last
turn end, last report, background tasks, child processes with their commands, age and CPU) so the
Worker checks and decides for itself, and sends the Leader the same evidence. It never signals a
process or changes the state, the CR or the Git work. A Worker whose child processes use CPU is working
and is left alone.

The judgement reads only facts the tools already keep: the CR state, the provider's turn status, the
last Stop hook, the send records on the windows (`last_sent`, `last_received`) and the CLI's child
processes. What watch sent is recorded in the window option `watch`.

Dependency direction as in `suspend`: `lifecycle` imports this module and `Manager` inherits
`WatchMixin`; this module never imports `lifecycle`. `Watch` gets the `Manager` class from the code that
assembles it (`cli._default_watch`).
"""

import datetime as dt
import time

from . import jobs, process
from .errors import SessionError
from .state import locked
from .suspend import Fleet

DEFAULT_MINUTES = 30      # how long a Worker may rest before watch acts
IDLE_CPU_RATE = 0.02      # child processes that used less than this share of one core between two looks are not working.
                          # A `pgrep -f` loop that sleeps 1 s measured 5.6 % on a loaded workstation, one that sleeps 5 s about 1 %;
                          # a wrongly woken Worker only reads a message, a missed one stays stuck, so the bar is low.
RESIDENT_GRACE = 120      # seconds after the CLI starts in which its helper processes (MCP servers) start
COMMAND_CHARS = 160       # command line length in a message
LISTED = 8                # most background tasks or child processes named in a message

WORKER_NOTICE = (
    "[agent-session watch] 자동 점검 메시지입니다. {job} CR이 in-progress인데 이 세션은 {minutes}분 넘게 "
    "turn이 끝난 채 새 입력과 보고가 없습니다. 아래 근거를 보고 작업이 실제로 진행 중인지 확인하십시오. "
    "멈춘 대기(예: 자기 shell과도 맞아 끝나지 않는 `pgrep -f` loop)이면 원인을 풀고 이어서 진행하십시오. "
    "제출했다면 `agent-session send --job leader`로 보고하고, 막혔다면 이유를 Leader에게 보고하십시오. "
    "같은 상태에서는 이 메시지를 다시 보내지 않습니다.\n{evidence}")
LEADER_NOTICE = (
    "[agent-session watch] seat {seat}의 {job} Worker가 {minutes}분째 쉬고 있습니다(CR in-progress, turn 종료, "
    "새 입력·보고 없음). {delivery} 강제로 끊지 않았습니다. 계속되면 Worker 상태를 확인해 주십시오.\n{evidence}")


def _parse(value):
    try:
        return dt.datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return None


def _iso(seconds):
    return dt.datetime.fromtimestamp(seconds, dt.timezone.utc).isoformat()


def _minutes(seconds):
    return max(1, int(seconds // 60))


class WatchMixin:
    """One-target watch of a project's Manager.

    The mixin relies on these members of the `lifecycle.Manager` it is mixed into:
    - attributes: `project`, `store`, `tmux`, `provider`
    - `remaining()`, `_owned`, `_session`, `_provider_context`, `send`
    """

    def watch_target(self, slot, threshold, now=None, tell_leader=True):
        """Judge one Worker seat and act once. Return what was seen and done.

        With `tell_leader` False the caller is the Leader, who gets the evidence in the result instead of
        a message to itself."""
        now = time.time() if now is None else now
        state = self.store.read()
        job_id = state[slot[len("seat-"):]]["job_id"]
        outcome = {"slot": slot, "job_id": job_id, "status": "skipped", "reason": None, "actions": []}
        if jobs.state_of(self.project, job_id)[0] != "in-progress":
            return {**outcome, "reason": "cr_not_in_progress"}
        meta = self.tmux.get_current(self.project.project_id, slot)
        if not meta or not meta.get("ready") or meta.get("stopping") or meta.get("control_pending"):
            return {**outcome, "reason": "not_ready"}
        if meta.get("remote_seat"):
            return {**outcome, "reason": "remote_seat"}
        if meta.get("moved_to_background"):
            return {**outcome, "reason": "moved_to_background"}
        self._owned(meta, slot, state)
        pane = self.tmux.pane_info(meta["pane_id"])
        if pane["pane_dead"] or not process.cli_alive(meta, pane):
            return {**outcome, "reason": "not_running"}
        context = self._provider_context(meta, pane)
        observed = self.provider.observe(self._session(meta), context, context["meta"], timeout=self.remaining())
        record = dict(meta.get("watch") or {})
        record.setdefault("first_seen_at", now)
        # Claude reports "shell" while only a background shell runs: its turn has ended.
        if observed.get("idle") or observed.get("runtime_status") == "shell":
            outcome.update(self._judge_rest(state, meta, observed, record, threshold, now, job_id, slot,
                                                tell_leader))
        else:
            record["busy_seen_at"] = now
            outcome.update(status="busy")
        if record != (meta.get("watch") or {}):
            try:
                self.tmux.write_meta(meta["window_id"], {"run_id": meta["run_id"], "watch": record})
            except SessionError as error:
                outcome["actions"].append({"record": "failed", "error": error.as_dict()})
        return outcome

    @staticmethod
    def _hook_time(meta):
        """When the last turn ended: the later of the current conversation's Stop and StopFailure hooks."""
        seen = [_parse(item.get("observed_at")) for name, item in (meta.get("hook_observations") or {}).items()
                if name in ("Stop", "StopFailure") and isinstance(item, dict)
                and item.get("session_id") == meta.get("session_id")]
        return max((value for value in seen if value is not None), default=None)

    def _judge_rest(self, state, meta, observed, record, threshold, now, job_id, slot, tell_leader=True):
        children = self._children(meta)
        before = (record.get("children"), record.get("children_at"))     # the last look, before this one replaces it
        working = self._working(children, before, now)
        record["children"] = {f"{item['pid']}:{item['birth']}": item["cpu"] for item in children or ()}
        record["children_at"] = now
        sent, received = meta.get("last_sent") or {}, meta.get("last_received") or {}
        sent_at, received_at = _parse(sent.get("at")), _parse(received.get("at"))
        reviewing = (state["leader"] or {}).get("reviewing") == job_id
        # A Worker that reported or asked the Leader and has no answer yet is waiting for the Leader, not resting.
        answered = received_at is not None and (sent_at is None or received_at > sent_at)
        if reviewing or (sent.get("to") == "leader" and not answered):
            return {"status": "awaiting_leader", "reason": "reviewing" if reviewing else "reported"}
        # The turn's end, the last input, and the last time watch saw it busy bound the rest from below.
        # Without any of them (Codex has no Stop hook) the first look at this run starts the clock.
        ended = self._hook_time(meta)
        marks = [value for value in (ended, received_at, record.get("busy_seen_at")) if value]
        resting_since = max(marks) if marks else record["first_seen_at"]
        if now - resting_since < threshold:
            return {"status": "idle", "reason": None}
        if working is None:
            return {"status": "observing", "reason": "children_not_measured"}
        if working:
            return {"status": "working", "reason": "children_use_cpu"}
        resting = record.get("resting") or {}
        nudged = _parse(resting.get("nudged_at"))
        if nudged is not None and ((sent_at or 0) > nudged or (received.get("from") == "leader"
                                                              and (received_at or 0) > nudged)):
            resting = {}                   # the Worker reported or the Leader answered since: a new episode
        minutes = _minutes(now - resting_since)
        evidence = self._evidence(job_id, ended, received_at, sent_at, observed, children, before, now)
        actions = []
        told = False
        if not resting.get("nudged_at"):
            # The first look at an episode wakes the Worker once; later looks only remind the Leader.
            told = self._deliver(actions, job_id, WORKER_NOTICE.format(job=job_id, minutes=minutes, evidence=evidence))
            if told:
                resting["nudged_at"] = _iso(now)
        delivery = ("Worker에게 점검 메시지를 보냈습니다." if told else
                    "Worker에게는 이미 점검 메시지를 보냈으므로 다시 보내지 않았습니다." if resting.get("nudged_at")
                    else "Worker에게 점검 메시지를 보내지 못했습니다.")
        if not tell_leader:
            record["resting"] = resting
            return {"status": "resting", "reason": None, "actions": actions, "evidence": evidence}
        record["resting"] = self._notify_leader(actions, resting, now, threshold, LEADER_NOTICE.format(
            seat=slot[len("seat-"):], job=job_id, minutes=minutes, delivery=delivery, evidence=evidence))
        return {"status": "resting", "reason": None, "actions": actions}

    # Child processes

    @staticmethod
    def _children(meta):
        """The CLI's child processes without its helper processes, or None when they cannot be read."""
        try:
            tree = process.tree(int(meta["cli_pid"]))
            began = process.started(int(meta["cli_pid"]))
        except (SessionError, KeyError, TypeError, ValueError):
            return None
        return [item for item in tree if began is None or item["started"] > began + RESIDENT_GRACE]

    @staticmethod
    def _working(children, before, now):
        """Whether the children used CPU since the last look: True or False, or None before there is a look
        to compare with. Without children nothing works. The CPU of a child includes the children it
        reaped, so a build's `make` shows its compilers and a shell loop shows only its own small cost."""
        if not children:
            return False
        cpu, at = before
        if cpu is None or at is None:
            return None
        used = sum(item["cpu"] - cpu.get(f"{item['pid']}:{item['birth']}", 0.0) for item in children)
        return used >= IDLE_CPU_RATE * max(now - at, 1)

    def _evidence(self, job_id, ended, received_at, sent_at, observed, children, before, now):
        def when(value):
            return _iso(value) if value else "기록 없음"
        lines = [f"근거: CR {job_id} in-progress / 마지막 turn 종료 {when(ended)} / 마지막 입력 {when(received_at)} / "
                 f"마지막 보고(Leader에게 send) {when(sent_at)}"]
        background = observed.get("background") or []
        for item in background[:LISTED]:
            item = item if isinstance(item, dict) else {"command": str(item)}
            lines.append(f"- background {item.get('type', '')} {item.get('id', '')}: "
                         f"{str(item.get('command') or item.get('description') or '')[:COMMAND_CHARS]}")
        if children is None:
            lines.append("- 자식 process: 읽지 못했습니다.")
        for item in (children or [])[:LISTED]:
            earlier = (before[0] or {}).get(f"{item['pid']}:{item['birth']}")
            recent = (f", 직전 점검 뒤 CPU {item['cpu'] - earlier:.1f}초/{_minutes(now - before[1])}분"
                      if earlier is not None and before[1] else "")
            lines.append(f"- 자식 process pid {item['pid']}, 실행 {_minutes(now - item['started'])}분, "
                         f"CPU 누적 {item['cpu']:.1f}초{recent}: {item['args'][:COMMAND_CHARS]}")
        if not background and not children:
            lines.append("- background 작업과 자식 process가 없습니다.")
        return "\n".join(lines)

    # Messages

    def _deliver(self, actions, job, text):
        """Send one message to the Leader (`job` "leader") or a Worker. Return whether the provider accepted it;
        a failure is reported in `actions`, not raised."""
        try:
            self.send(job=job, message=text)
        except SessionError as error:
            actions.append({"send": job, "ok": False, "error": error.as_dict()})
            return False
        actions.append({"send": job, "ok": True})
        return True

    def _notify_leader(self, actions, episode, now, threshold, text):
        """Tell the Leader about an episode: at its first look, then again after each further `threshold`."""
        notified = _parse(episode.get("notified_at"))
        if notified is None or now - notified >= threshold:
            if self._deliver(actions, "leader", text):
                episode = {**episode, "notified_at": _iso(now)}
        return episode


class Watch(Fleet):
    """The watch over registered projects: the operator's over any, a Leader's over its own project."""

    def _authorize(self, registry, selected, operation):
        """Return "operator" or "leader", whoever may watch the selection.

        The operator needs no managed or agent caller in any registered project (`Fleet`). A Leader passes
        only for the one project it leads; a Worker, another project's agent and `--all` over several
        projects keep the operator's refusal."""
        try:
            super()._authorize(registry, selected, operation)
        except SessionError as error:
            if error.code not in ("role_denied", "caller_unbound") or len(selected) != 1:
                raise
        if len(selected) != 1:
            return "operator"                  # a Leader of any project made `Fleet` refuse several projects
        actor, _ = self._manager(selected[0], 30)._authorize(operation, "leader")
        return actor

    def run(self, project=None, everything=False, minutes=DEFAULT_MINUTES):
        registry, selected = self._select(project, everything)
        tell_leader = self._authorize(registry, selected, "watch") != "leader"
        threshold = minutes * 60
        results = []
        for item in selected:
            manager = self._manager(item, self.timeout)
            outcome = {"project": item.project_id, "targets": []}
            try:
                with locked(item.runtime_path / "watch.lock", self.timeout, blocking=False):
                    state = manager.store.read(missing_ok=True)
                    for key, row in state.items():
                        if key == "leader" or row["job_id"] is None or row["session"] is None:
                            continue
                        outcome["targets"].append(self._target(manager, f"seat-{key}", row["job_id"], threshold,
                                                                  tell_leader))
            except SessionError as error:
                # Another watch of this project is running, or its state cannot be read.
                outcome["error"] = error.as_dict()
            results.append(outcome)
        return {"threshold_minutes": minutes, "projects": results}

    @staticmethod
    def _target(manager, slot, job_id, threshold, tell_leader):
        try:
            return manager.watch_target(slot, threshold, tell_leader=tell_leader)
        except SessionError as error:
            return {"slot": slot, "job_id": job_id, "status": "error", "error": error.as_dict()}
        except Exception as error:         # a bug in one target must not hide the others
            return {"slot": slot, "job_id": job_id, "status": "error",
                    "error": {"code": "internal_error", "message": type(error).__name__, "details": {}}}
