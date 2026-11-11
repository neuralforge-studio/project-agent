"""What the Leader has to do: the judgement behind `agent-session check` (SESSION-015, spec 7 `check`).

The project's crontab job runs `agent-session check --project NAME` every 30 minutes. The command is
`watch.Watch.run(check=True)`: the stalled Workers are woken as `watch` does, and the Leader is judged by the
findings below instead of by the CRs in progress. `CheckMixin.leader_findings` is that list. It only reads:
the project-item state of the CRs and decisions, `state.json` and the tmux facts of each seat. The caller
(`WatchMixin.watch_target`) tells the Leader once per rest, and only when the Leader's conversation has been
still for the threshold, so a Leader that is working is not interrupted and the same state is not repeated.

Every group is judged on its own. A group that cannot be read becomes a finding too: when the judgement is
uncertain it errs toward telling the Leader.

Dependency direction as in `watch`: `lifecycle` imports this module and `Manager` inherits `CheckMixin`; this
module never imports `lifecycle`.
"""

from . import jobs, process
from .errors import SessionError

LISTED = 8       # most IDs named per group


def _names(ids):
    shown = ", ".join(ids[:LISTED])
    return shown + (f" 외 {len(ids) - LISTED}건" if len(ids) > LISTED else "")


class CheckMixin:
    """The Leader's findings of a project's Manager.

    The mixin relies on these members of the `lifecycle.Manager` it is mixed into: `project`, `tmux`, and
    `pending_releases()`."""

    def leader_findings(self, state):
        """Lines that name what is left to the Leader, empty when nothing is. `state` is the project's state."""
        found = []
        for group in (self._review_waits, self._release_waits, self._free_seats, self._answered_decisions,
                      self._lost_workers):
            try:
                found += group(state)
            except Exception as error:                  # a group that cannot be judged is told, not skipped
                code = error.code if isinstance(error, SessionError) else type(error).__name__
                found.append(f"{group.__name__.lstrip('_')} 점검을 판정하지 못했습니다({code}). 직접 확인하십시오.")
        return found

    def _review_waits(self, state):
        waiting = jobs.waiting_review(self.project)
        return [f"review 대기 CR(제출한 hash를 Disposition이 아직 인용하지 않음): {_names(waiting)}"] if waiting else []

    def _release_waits(self, state):
        pending = sorted(self.pending_releases())
        return [f"반납 대기 seat(CR이 in-progress에 남아 있음): {_names(pending)}"] if pending else []

    def _free_seats(self, state):
        free = [key for key, row in state.items() if key != "leader" and row["job_id"] is None]
        if not free:
            return []
        assigned = {row["job_id"] for key, row in state.items() if key != "leader"}
        todo = [item for item in jobs.todo_ids(self.project) if item not in assigned]
        if not todo:
            return []
        return [f"빈 seat {_names(free)}가 있고 배정할 수 있는 todo CR이 있습니다: {_names(todo)}"]

    def _answered_decisions(self, state):
        answered = jobs.answered_decisions(self.project)
        return [f"답을 받고 아직 끝내지 않은 결정 항목: {_names(answered)}"] if answered else []

    def _lost_workers(self, state):
        """Workers that hold a CR and a conversation but whose window or CLI is gone."""
        lost = []
        waiting = set(self.pending_releases())          # a stopped Worker that waits for its release is a finding already
        for key, row in state.items():
            if key == "leader" or row["job_id"] is None or row["session"] is None or row["job_id"] in waiting:
                continue
            meta = self.tmux.get_current(self.project.project_id, f"seat-{key}")
            if meta and (meta.get("remote_seat") or meta.get("stopping")):
                continue                                # a remote seat is not judged here; a stop is on purpose
            if not meta:
                lost.append(f"{row['job_id']}(seat {key}: window 없음)")
                continue
            pane = self.tmux.pane_info(meta["pane_id"])
            if pane["pane_dead"] or not process.cli_alive(meta, pane):
                lost.append(f"{row['job_id']}(seat {key}: CLI 종료)")
        return [f"window나 CLI가 사라진 Worker: {_names(lost)}"] if lost else []
