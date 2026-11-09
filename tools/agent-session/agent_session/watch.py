"""Wake an instance whose conversation has not moved, and tell the Leader.

`WatchMixin` is the one-target judgement of a project's `Manager`. `Watch` is the command: it selects
projects from the registry and runs the judgement for every Worker seat and the Leader once. The operator
runs it by hand; the Leader runs it for its own project from its own session cron (spec 7, watch).

A stall is judged by the conversation record alone, whatever the cause: the newest record of the
provider's conversation file (`provider.last_record`) is older than `--minutes`. A turn that runs keeps
appending records; an instance that waits for a child process, for the Leader, or for nothing does not.
Nothing from an earlier look is compared. Watch then sends the Worker one message with the evidence (CR,
last turn end, last report, background tasks, child processes with their commands and age) so the Worker
checks and decides for itself, and tells the Leader. A stalled Leader gets one message that names the CRs
in progress. It never signals a process or changes the state, the CR or the Git work.

The judgement reads that record time and, for the evidence only, facts the tools already keep: the CR
state, the provider's turn status, the last Stop hook, the send records on the windows and the CLI's child
processes. What watch sent is recorded in the window option `watch` so that one stall wakes an instance once.

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

DEFAULT_MINUTES = 30      # how old the newest conversation record may be before watch acts
RESIDENT_GRACE = 120      # seconds after the CLI starts in which its helper processes (MCP servers) start
COMMAND_CHARS = 160       # command line length in a message
LISTED = 8                # most background tasks, child processes or CRs named in a message
LEADER = "leader"

WORKER_NOTICE = (
    "[agent-session watch] 자동 점검 메시지입니다. {job} CR이 in-progress인데 이 세션의 대화 기록이 {minutes}분 넘게 "
    "갱신되지 않았습니다. 아래 근거를 보고 작업이 실제로 진행 중인지 확인하십시오. "
    "제출해서 Leader 회신을 기다리는 중이면 `agent-session send --job leader`로 Leader에게 CR ID와 제출 commit을 "
    "짧게 다시 알리십시오. 멈춘 대기(예: 자기 shell과도 맞아 끝나지 않는 `pgrep -f` loop)이면 원인을 풀고 이어서 "
    "진행하고, 막혔다면 이유를 Leader에게 보고하십시오. 같은 정체 상태에서는 이 메시지를 다시 보내지 않습니다.\n{evidence}")
WORKER_LEADER_NOTICE = (
    "[agent-session watch] seat {seat}의 {job} Worker의 대화 기록이 {minutes}분째 갱신되지 않았습니다(CR in-progress). "
    "{delivery} 강제로 끊지 않았습니다. 제출 뒤 review를 기다리는 중일 수 있으니 `## Result`의 제출 hash가 "
    "Disposition에 없는 CR이면 review하고, 아니면 Worker 상태를 확인해 주십시오.\n{evidence}")
LEADER_NOTICE = (
    "[agent-session watch] 자동 점검 메시지입니다. Leader의 대화 기록이 {minutes}분 넘게 갱신되지 않았는데 in-progress CR이 "
    "있습니다. `project-item ls`로 review 대기 CR(`## Result`의 제출 hash가 Disposition에 없는 것)을 먼저 처리하고, "
    "그 밖에 Worker 보고·결정 항목·빈 seat를 확인하십시오. 같은 정체 상태에서는 이 메시지를 다시 보내지 않습니다.\n{evidence}")


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
        """Judge one seat (a Worker's, or the Leader's with `slot` "leader") and act once. Return what was seen
        and done.

        With `tell_leader` False the caller is the Leader, who gets the evidence in the result instead of
        a message to itself."""
        now = time.time() if now is None else now
        state = self.store.read()
        leader = slot == LEADER
        working = self._in_progress(state)
        if leader:
            job_id = None
            outcome = {"slot": slot, "job_id": None, "status": "skipped", "reason": None, "actions": []}
            if not working:
                return {**outcome, "reason": "no_cr_in_progress"}        # nothing for a Leader to have forgotten
        else:
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
        last = self.provider.last_record(meta.get("session_id"))
        at = last["at"]
        if at is None:
            return {**outcome, "reason": last["reason"]}                 # no record to judge by: not a stall
        record = {"resting": (meta.get("watch") or {}).get("resting") or {}}
        nudged = _parse(record["resting"].get("nudged_at"))
        if nudged is not None and at > nudged:
            record["resting"] = {}                                      # the conversation moved since: a new state
        if now - at < threshold:
            outcome.update(status="active")
        elif leader:
            outcome.update(self._judge_leader_stall(working, record, at, now, threshold))
        else:
            outcome.update(self._judge_stall(meta, pane, record, at, now, threshold, job_id, slot, tell_leader))
        if record != (meta.get("watch") or {}):
            try:
                self.tmux.write_meta(meta["window_id"], {"run_id": meta["run_id"], "watch": record})
            except SessionError as error:
                outcome["actions"].append({"record": "failed", "error": error.as_dict()})
        return outcome

    def _in_progress(self, state):
        """The (seat number, CR) pairs whose Worker has a session and whose CR is in progress."""
        return [(key, row["job_id"]) for key, row in state.items()
                if key != LEADER and row["job_id"] and row["session"]
                and jobs.state_of(self.project, row["job_id"])[0] == "in-progress"]

    @staticmethod
    def _hook_time(meta):
        """When the last turn ended: the later of the current conversation's Stop and StopFailure hooks."""
        seen = [_parse(item.get("observed_at")) for name, item in (meta.get("hook_observations") or {}).items()
                if name in ("Stop", "StopFailure") and isinstance(item, dict)
                and item.get("session_id") == meta.get("session_id")]
        return max((value for value in seen if value is not None), default=None)

    def _judge_stall(self, meta, pane, record, at, now, threshold, job_id, slot, tell_leader=True):
        try:
            context = self._provider_context(meta, pane)
            observed = self.provider.observe(self._session(meta), context, context["meta"], timeout=self.remaining())
        except SessionError:
            observed = {}                  # the evidence lacks the turn status; the stall stands
        children = self._children(meta)
        sent, received = meta.get("last_sent") or {}, meta.get("last_received") or {}
        sent_at, received_at = _parse(sent.get("at")), _parse(received.get("at"))
        resting = record.get("resting") or {}
        minutes = _minutes(now - at)
        evidence = self._evidence(job_id, self._hook_time(meta), received_at, sent_at, at, observed, children, now)
        actions = []
        told = False
        if not resting.get("nudged_at"):
            # The first look at a stall wakes the Worker once; later looks only remind the Leader.
            told = self._deliver(actions, job_id, WORKER_NOTICE.format(job=job_id, minutes=minutes, evidence=evidence))
            if told:
                resting["nudged_at"] = _iso(now)
        delivery = ("Worker에게 점검 메시지를 보냈습니다." if told else
                    "Worker에게는 이미 점검 메시지를 보냈으므로 다시 보내지 않았습니다." if resting.get("nudged_at")
                    else "Worker에게 점검 메시지를 보내지 못했습니다.")
        if not tell_leader:
            record["resting"] = resting
            return {"status": "resting", "reason": None, "actions": actions, "evidence": evidence}
        record["resting"] = self._notify_leader(actions, resting, now, threshold, WORKER_LEADER_NOTICE.format(
            seat=slot[len("seat-"):], job=job_id, minutes=minutes, delivery=delivery, evidence=evidence))
        return {"status": "resting", "reason": None, "actions": actions}

    def _judge_leader_stall(self, working, record, at, now, threshold):
        """Wake a stalled Leader once per stall with the CRs in progress."""
        resting = record.get("resting") or {}
        actions = []
        if not resting.get("nudged_at"):
            evidence = "근거: in-progress CR " + ", ".join(f"{job}(seat {key})" for key, job in working[:LISTED])
            if self._deliver(actions, LEADER, LEADER_NOTICE.format(minutes=_minutes(now - at), evidence=evidence)):
                resting["nudged_at"] = _iso(now)
        record["resting"] = resting
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
    def _evidence(job_id, ended, received_at, sent_at, at, observed, children, now):
        def when(value):
            return _iso(value) if value else "기록 없음"
        lines = [f"근거: CR {job_id} in-progress / 마지막 turn 종료 {when(ended)} / 마지막 입력 {when(received_at)} / "
                 f"마지막 보고(Leader에게 send) {when(sent_at)} / 대화 기록 마지막 {when(at)}"]
        background = observed.get("background") or []
        for item in background[:LISTED]:
            item = item if isinstance(item, dict) else {"command": str(item)}
            lines.append(f"- background {item.get('type', '')} {item.get('id', '')}: "
                         f"{str(item.get('command') or item.get('description') or '')[:COMMAND_CHARS]}")
        if children is None:
            lines.append("- 자식 process: 읽지 못했습니다.")
        for item in (children or [])[:LISTED]:
            lines.append(f"- 자식 process pid {item['pid']}, 실행 {_minutes(now - item['started'])}분, "
                         f"CPU 누적 {item['cpu']:.1f}초: {item['args'][:COMMAND_CHARS]}")
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
                    if tell_leader and state.get(LEADER):
                        # A Leader that runs this command is not stalled, so only the operator judges the Leader.
                        outcome["targets"].append(self._target(manager, LEADER, None, threshold, tell_leader))
                    for key, row in state.items():
                        if key == LEADER or row["job_id"] is None or row["session"] is None:
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
