"""Terminal UI for the Project Board.

The snapshot and answer modules own project facts and permission checks. This
module renders them and keeps blocking reads away from Textual's UI loop.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
import signal
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlsplit

from textual.app import App, ComposeResult
from textual.content import Content
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.errors import NoWidget
from textual.screen import Screen
from textual.widgets import Button, DataTable, Markdown, Static, TextArea

from . import answer, model

SnapshotReader = Callable[[str | None], dict]
LivenessReader = Callable[[str | None], dict]
DecisionCallback = Callable[..., object]
CrCallback = Callable[..., object]
SeatCallback = Callable[..., object]
ProjectCallback = Callable[..., object]
ExpandedReader = Callable[[], set[str]]
ExpandedToggler = Callable[[str], set[str]]
ContextReader = Callable[[], "dict | None"]

CSV_FENCE = re.compile(r"(?ms)^\s*```csv\s*\n(.*?)^\s*```\s*$")


def _csv_rows(source: str) -> list[list[str]]:
    return [row for row in csv.reader(io.StringIO(source)) if any(cell.strip() for cell in row)]


def _csv_table(source: str, *, id: str | None = None) -> DataTable:
    rows = _csv_rows(source)
    table = DataTable(id=id, classes="csv-table")
    if not rows:
        table.add_column("(empty CSV)")
        return table
    width = max(len(row) for row in rows)
    header = rows[0] + [f"Column {n + 1}" for n in range(len(rows[0]), width)]
    table.add_columns(*header)
    table.add_rows([row + [""] * (width - len(row)) for row in rows[1:]])
    table.zebra_stripes = True
    return table


def _body_widgets(body: str) -> list:
    """Keep Markdown order while rendering fenced CSV as a real table."""
    widgets = []
    offset = 0
    for match in CSV_FENCE.finditer(body):
        before = body[offset:match.start()].strip()
        if before:
            widgets.append(Markdown(before, open_links=False))
        widgets.append(_csv_table(match.group(1)))
        offset = match.end()
    after = body[offset:].strip()
    if after:
        widgets.append(Markdown(after, open_links=False))
    return widgets


def _count(project: dict, state: str) -> str:
    crs = project.get("crs")
    if crs is None:
        return "!" if any(error.get("source") == "cr" for error in project.get("errors", [])) else "-"
    return str(len(crs.get(state, [])))


def _decide_count(project: dict) -> str:
    decisions = project.get("decide")
    if decisions is None:
        return "!" if any(error.get("source") == "decide" for error in project.get("errors", [])) else "-"
    return str(sum(item.get("state") == "open" for item in decisions))


def _visible_decisions(project: dict) -> list[dict]:
    return [item for item in project.get("decide") or [] if item.get("display_state") != "완료"]


def _decide_stages(project: dict) -> tuple[int, int, int, int]:
    decisions = project.get("decide") or []
    return tuple(sum(item.get("display_state") == stage for item in decisions)
                 for stage in ("결정 대기", "답변 접수", "반영 중", "완료"))


# Popup list rows (docs/project-board-tui-plan.md, "Popup 목록 행과 선택 표시"). The status is the
# short form of the snapshot's `display_state`; an unknown stage is shown in full.
STATUS_STYLE = {"결정 대기": ("대기", "#ffcf70"), "답변 접수": ("접수", "#8fd0ff"), "반영 중": ("반영", "#9be28f")}
REVIEW_STATUS = ("검토", "#ffcf70")
LIST_ITEM_CSS = """
Button.list-item { width: 100%; height: 1; min-width: 0; border: none; padding: 0 1;
                   content-align: left middle; text-align: left; text-style: none;
                   text-wrap: nowrap; text-overflow: ellipsis;
                   background: #17222f; color: #c9dbed; }
Button.list-item:hover { background: #22344a; }
Button.list-item:focus { background: #2b3d52; text-style: none; }
Button.list-item.selected { background: #2f6db3; color: #ffffff; text-style: bold; }
Button.list-item.selected:focus { background: #3a7bc8; text-style: bold; }
"""


def _adjacent(order: list[str], current: str, step: int, allowed: set[str]) -> str | None:
    """The project `step` (1 or -1) places from `current` in `order` that is in `allowed`, wrapping at the ends.
    None when there is no other such project (or `current` is not in `order`)."""
    if current not in order:
        return None
    for turn in range(1, len(order)):
        candidate = order[(order.index(current) + step * turn) % len(order)]
        if candidate in allowed:
            return candidate
    return None


def _set_nav(previous: Button, following: Button, order: list[str], current: str, allowed: set[str]) -> dict:
    """Aim the ◀▶ buttons at the neighbouring projects and say where each goes in its tooltip."""
    targets = {}
    for button, step, word in ((previous, -1, "이전"), (following, 1, "다음")):
        target = _adjacent(order, current, step, allowed)
        targets[step] = target
        button.disabled = target is None
        button.tooltip = f"{word} project: {target}" if target else None
    return targets


NAV_CSS = """
.nav-row { height: 1; padding: 0 1; }
.nav-row Button { height: 1; width: 3; min-width: 3; border: none; padding: 0; }
.nav-row Static { width: auto; padding: 0 1; text-style: bold; color: #f3f6ff; }
"""


def _item_label(selected: bool, item_id: str, status: tuple[str, str] | None, title: str) -> Content:
    """`▶ ID 상태 제목` on one line. CSS cuts the end of the line, so only the title is shortened."""
    parts: list = ["▶ " if selected else "  ", item_id, " "]
    if status:
        parts += [(status[0], status[1]), " "]
    parts.append(title.replace("\n", " "))
    return Content.assemble(*parts)


def _decision_status(item: dict) -> tuple[str, str] | None:
    stage = item.get("display_state")
    return STATUS_STYLE.get(stage, (stage, "#c9dbed")) if stage else None


def _cr_status(item: dict) -> tuple[str, str] | None:
    return REVIEW_STATUS if item.get("review_wait") else None


def format_elapsed(seconds: int | None) -> str | None:
    """`2d 01h 00m`, `3h 05m`, `12m`: whole minutes, without leading zero units. The rule is owned by
    docs/project-board-tui-plan.md section 3 (BOARD-008)."""
    if seconds is None:
        return None
    days, rest = divmod(max(0, seconds) // 60, 24 * 60)
    hours, minutes = divmod(rest, 60)
    if days:
        return f"{days}d {hours:02d}h {minutes:02d}m"
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def _seat_text(seat: dict) -> str:
    if seat.get("status") == "reviewing":
        prefix = "R "
    elif seat.get("status") == "pending":
        prefix = "대기 "
    elif seat.get("status") == "release_pending":
        prefix = "반납대기 "
    else:
        prefix = "  "
    host = "@" + seat["host"] if seat.get("host") else ""
    text = f"{prefix}{seat['index']}{host} {seat.get('job_id') or '-'}"
    elapsed = format_elapsed(seat.get("elapsed"))
    return f"{text} {elapsed}" if elapsed else text


class SidebarApp(App):
    """One scrolling view of every registered project."""

    CSS = """
    Screen { background: #111c28; }
    #projects { height: 1fr; width: 100%; overflow-x: auto; }
    #board-error { height: auto; color: #ffb86c; }
    .project { width: auto; min-width: 100%; height: auto; margin-bottom: 1; }
    .project-name { height: 1; width: auto; min-width: 100%; border: none; padding: 0;
                    text-align: left; content-align: left middle; background: transparent;
                    text-style: bold; color: #e6f0ff; }
    .counts { height: 1; width: auto; min-width: 100%; }
    .counts Button { width: auto; min-width: 0; height: 1; border: none; padding: 0;
                     background: transparent; color: #d6e5f5; }
    .counts .cr-count { padding-right: 1; }
    .project-name:hover, .counts Button:hover, .decision:hover, .seat:hover { background: #34506d; }
    .decision, .seat { width: auto; min-width: 100%; height: 1; border: none;
                       padding: 0; text-align: left;
                       content-align: left middle; background: transparent; }
    .decision { color: #ffd479; }
    .decision-open { color: #ff8f8f; }
    .seat { color: #c7dbf1; }
    .seat-empty { color: #778596; }
    .seat-pending, .seat-release-pending { color: #ffcb84; }
    .seat-stopped { color: #ff8f8f; }
    .seat-unknown { color: #ffcb84; }
    .project-error { height: auto; color: #ff8f8f; }
    .project-name.project-active, .slot-active { background: #2f6db3; color: #ffffff; text-style: bold; }
    .counts Button.slot-active { background: #2f6db3; color: #ffffff; }
    """
    def __init__(
        self,
        config: str | None = None,
        *,
        on_project: ProjectCallback | None = None,
        on_decision: DecisionCallback | None = None,
        on_cr: CrCallback | None = None,
        on_seat: SeatCallback | None = None,
        snapshot_reader: SnapshotReader | None = None,
        liveness_reader: LivenessReader | None = None,
        poll: bool = True,
        click_socket: str | None = None,
        expanded_reader: ExpandedReader | None = None,
        expanded_toggler: ExpandedToggler | None = None,
        mark_ready: Callable[[], bool] | None = None,
        visibility_reader: Callable[[], bool] | None = None,
        context_reader: ContextReader | None = None,
    ):
        super().__init__()
        self.config = config
        self.on_project = on_project
        self.on_decision = on_decision
        self.on_cr = on_cr
        self.on_seat = on_seat
        self.snapshot_reader = snapshot_reader or model.snapshot
        self.liveness_reader = liveness_reader or model.liveness
        self.poll = poll
        self.click_socket = click_socket
        self.expanded_reader = expanded_reader
        self.expanded_toggler = expanded_toggler
        self.mark_ready = mark_ready
        self.visibility_reader = visibility_reader
        self.context_reader = context_reader
        self._active: dict | None = None      # the managed project and slot of this pane's window
        self._context_busy = False
        self._visible = True
        self.snapshot_data: dict = {"projects": [], "error": None}
        self.live_data: dict = {}
        self._actions: dict[str, tuple] = {}
        self._expanded_projects: set[str] = set()
        self._expansion_lock = asyncio.Lock()
        self._signature = None
        self._blocks: list[Vertical] = []     # the mounted block of each project, in order
        self._shapes: list[tuple] = []        # the rows (`_shape`) each mounted block was built with
        self._widgets: list[dict] = []        # the widgets of each mounted block by role, written by `_update_block`
        self._render_lock = asyncio.Lock()
        self._pool: ThreadPoolExecutor | None = None
        self._tasks: set[asyncio.Task] = set()
        self._snapshot_busy = False
        self._live_busy = False
        self._stopping = False
        self._tooltip_expiry = None
        self._click_server: asyncio.AbstractServer | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="board-error")
        yield VerticalScroll(id="projects")

    def on_mount(self) -> None:
        if self.click_socket:
            self._queue(self._start_click_server())
        if not self.poll:
            return
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="project-board")
        self._queue(self.refresh_snapshot())
        self._queue(self.refresh_liveness())
        self.set_interval(2, lambda: self._queue(self.refresh_snapshot()))
        self.set_interval(10, lambda: self._queue(self.refresh_liveness()))
        if self.context_reader is not None:
            self._queue(self.refresh_context())
            self.set_interval(10, lambda: self._queue(self.refresh_context()))
        self._watch_visibility()

    def _watch_visibility(self) -> None:
        """Stop reading while no client shows this pane's window (BOARD-002).

        tmux hooks send SIGUSR1 when this pane's window is shown or hidden
        (integrations/tmux/project_board_visibility.sh); the pane asks tmux which one it is.
        `mark_ready` comes after the handler exists, because the signal's default action ends
        the process, and tells the hook that it may signal this pane.
        """
        if self.mark_ready is None or self.visibility_reader is None:
            return
        try:
            asyncio.get_running_loop().add_signal_handler(
                signal.SIGUSR1, lambda: self._queue(self.sync_visibility(self.visibility_reader)))
        except (NotImplementedError, RuntimeError, ValueError):
            return                                   # not the main thread: keep refreshing
        self._queue(self.sync_visibility(self.mark_ready))

    async def sync_visibility(self, reader: Callable[[], bool]) -> None:
        try:
            visible = await asyncio.to_thread(reader)
        except Exception:                            # unknown is not hidden: keep refreshing
            visible = True
        if not self._stopping:
            self.set_visible(visible)

    def set_visible(self, visible: bool) -> None:
        shown = visible and not self._visible
        self._visible = visible
        if shown:                                    # a window shown again is read at once
            self._queue(self.refresh_snapshot())
            self._queue(self.refresh_liveness())
            self._queue(self.refresh_context())

    # A hover tooltip is hidden only by the next mouse move over this pane. When tmux moves focus to
    # another pane, or the mouse leaves with focus unchanged, no such event follows and the tooltip
    # would stay (BOARD-005). Focus loss hides it at once; otherwise it expires this long after the
    # last mouse motion. The value is owned by docs/project-board-tui-plan.md section 3.
    TOOLTIP_IDLE = 5.0

    def _hide_tooltip(self) -> None:
        screen = self.screen
        if screen._tooltip_timer is not None:      # a tooltip still waiting for its delay
            screen._tooltip_timer.stop()
        screen._clear_tooltip()

    def on_app_blur(self, event) -> None:
        self._hide_tooltip()

    def on_mouse_move(self, event) -> None:
        if self._tooltip_expiry is not None:
            self._tooltip_expiry.stop()
        self._tooltip_expiry = self.set_timer(self.TOOLTIP_IDLE, self._hide_tooltip)

    def on_unmount(self) -> None:
        self._stopping = True
        if self.mark_ready is not None:
            try:
                asyncio.get_running_loop().remove_signal_handler(signal.SIGUSR1)
            except (NotImplementedError, RuntimeError, ValueError):
                pass
        if self._click_server is not None:
            self._click_server.close()
            if self.click_socket:
                try:
                    os.unlink(self.click_socket)
                except FileNotFoundError:
                    pass
        for task in self._tasks:
            task.cancel()
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)

    def _queue(self, coroutine) -> None:
        if self._stopping:
            coroutine.close()
            return
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _start_click_server(self) -> None:
        if self.click_socket is None:
            return
        if os.path.lexists(self.click_socket):
            self.query_one("#board-error", Static).update("Board 클릭 socket 경로가 이미 사용 중입니다.")
            return
        try:
            self._click_server = await asyncio.start_unix_server(
                self._receive_client_click, path=self.click_socket, limit=4096)
            os.chmod(self.click_socket, 0o600)
        except OSError as error:
            self.query_one("#board-error", Static).update(f"Board 클릭 socket 오류: {error}")

    async def _receive_client_click(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
    ) -> None:
        try:
            raw = await reader.readline()
            if len(raw) > 4096:
                raise ValueError("click message too large")
            message = json.loads(raw)
            result = self.dispatch_client_click(message.get("client"), message.get("x"), message.get("y"))
        except (UnicodeError, ValueError, TypeError, AttributeError) as error:
            result = {"ok": False, "data": None,
                      "error": {"code": "invalid_click", "message": str(error)}}
        writer.write((json.dumps(result) + "\n").encode("utf-8"))
        try:
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    def dispatch_client_click(self, client: str, x: int, y: int) -> dict:
        """Activate the button at a tmux client's pane-relative cell position."""
        if not isinstance(client, str) or not client:
            raise ValueError("client is required")
        if type(x) is not int or type(y) is not int or x < 0 or y < 0:
            raise ValueError("x and y must be nonnegative integers")
        try:
            widget, _ = self.screen.get_widget_at(x, y)
        except NoWidget:
            return {"ok": False, "data": None,
                    "error": {"code": "no_widget", "message": "이 위치에는 조작할 항목이 없습니다."}}
        while widget is not None and not isinstance(widget, Button):
            widget = widget.parent
        if widget is None:
            return {"ok": False, "data": None,
                    "error": {"code": "not_clickable", "message": "이 항목은 클릭할 수 없습니다."}}
        target = self._actions.get(widget.id or "")
        if widget.disabled:
            if target is not None and target[0] in ("cr", "decision", "seat"):
                return {"ok": True, "data": {"widget": widget.id}, "error": None}
            return {"ok": False, "data": None,
                    "error": {"code": "not_clickable", "message": "이 항목은 클릭할 수 없습니다."}}
        if target is not None:
            self._activate(target, client=client)
        else:
            widget.press()
        return {"ok": True, "data": {"widget": widget.id}, "error": None}

    async def refresh_snapshot(self) -> None:
        if self._snapshot_busy or self._stopping or not self._visible:
            return
        self._snapshot_busy = True
        try:
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(self._pool, self.snapshot_reader, self.config)
            if not self._stopping:
                await self.apply_snapshot(data)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if not self._stopping:
                self.query_one("#board-error", Static).update(str(error))
        finally:
            self._snapshot_busy = False

    async def refresh_liveness(self) -> None:
        if self._live_busy or self._stopping or not self._visible:
            return
        self._live_busy = True
        try:
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(self._pool, self.liveness_reader, self.config)
            if not self._stopping:
                await self.apply_liveness(data)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if not self._stopping:
                self.query_one("#board-error", Static).update(str(error))
        finally:
            self._live_busy = False

    async def refresh_context(self) -> None:
        """Read which managed window this pane is in (BOARD-009). A failed read keeps the last mark."""
        if self.context_reader is None or self._context_busy or self._stopping or not self._visible:
            return
        self._context_busy = True
        try:
            active = await asyncio.to_thread(self.context_reader)
            if not self._stopping and active != self._active:
                self._active = active
                await self._render_projects()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        finally:
            self._context_busy = False

    async def apply_snapshot(self, data: dict) -> None:
        self.snapshot_data = data
        if self.expanded_reader is not None:
            async with self._expansion_lock:
                self._expanded_projects = await asyncio.to_thread(self.expanded_reader)
        await self._render_projects()

    async def apply_liveness(self, data: dict) -> None:
        self.live_data = data
        await self._render_projects()

    def _seat_liveness(self, project: dict, seat: dict) -> str | None:
        row = self.live_data.get(project["id"], {}).get(str(seat["index"]), {})
        if row.get("session_id") != seat.get("session_id"):
            return None
        return row.get("state")

    def _is_active(self, project: dict) -> bool:
        return bool(self._active) and self._active.get("project_id") == project["id"]

    def _active_slot(self, project: dict) -> str | None:
        """The slot of this pane's window in `project`; None for another project or a window without a slot."""
        return self._active.get("slot") if self._is_active(project) else None

    def _project_signature(self, project: dict) -> tuple:
        """What `_project_block` shows of one project. The seat rows exist only while the project is expanded,
        so a folded project's seats (and their minute counters) are not part of it. The Leader time is on the
        name line, so it is part of it folded or not."""
        expanded = project["id"] in self._expanded_projects
        seats = tuple((seat.get("index"), seat.get("job_id"), seat.get("status"),
                       seat.get("session_id"), seat.get("host"), seat.get("path"),
                       self._seat_liveness(project, seat), _seat_text(seat))
                      for seat in project.get("seats", [])) if expanded else ()
        errors = tuple((error.get("source"), error.get("message")) for error in project.get("errors", []))
        leader = format_elapsed((project.get("leader") or {}).get("elapsed"))
        return (project["id"], expanded, self._is_active(project), self._active_slot(project),
                tuple(_count(project, state) for state in model.CR_STATES),
                _decide_count(project), _decide_stages(project), seats, errors, leader)

    def _shape(self, project: dict) -> tuple:
        """Which rows `_project_block` has for one project. A change of shape replaces the block (inside one
        batch); any other change of what is shown is written into the widgets that are already mounted."""
        expanded = project["id"] in self._expanded_projects
        seats = tuple(seat["index"] for seat in project.get("seats", [])) if expanded else ()
        return expanded, seats, len(project.get("errors", []))

    def _register_actions(self, number: int, project: dict) -> None:
        """The click targets of one project's block, keyed by widget id (`project-<number>-...`)."""
        prefix = f"project-{number}-"
        for button_id in [key for key in self._actions if key.startswith(prefix)]:
            del self._actions[button_id]
        for short, state in (("O", "open"), ("T", "todo"), ("I", "in-progress")):
            self._actions[f"{prefix}{short}"] = ("cr", project, state)
        self._actions[f"{prefix}D"] = ("decision", project["id"])
        self._actions[f"{prefix}name"] = ("project", project["id"])
        self._actions[f"{prefix}seats"] = ("seats", project["id"])
        if project["id"] in self._expanded_projects:
            for seat in project.get("seats", []):
                self._actions[f"{prefix}seat-{seat['index']}"] = ("seat", project["id"], seat["index"])

    @staticmethod
    def _show(widget: Button, label: str, *, disabled: bool | None = None, tooltip: str | None = None,
              classes: dict[str, bool] | None = None) -> None:
        """Write what a mounted (or not yet mounted) button shows; a value that is already shown is not set again."""
        if str(widget.label) != label:
            widget.label = label
        if disabled is not None and widget.disabled != disabled:
            widget.disabled = disabled
        if tooltip is not None and widget.tooltip != tooltip:
            widget.tooltip = tooltip
        for name, on in (classes or {}).items():
            widget.set_class(on, name)

    def _fill_summary(self, widgets: dict, project: dict) -> None:
        """Name, decision, counters and fold button of a project, in the block's widgets."""
        for short, state in (("O", "open"), ("T", "todo"), ("I", "in-progress")):
            label = _count(project, state)
            self._show(widgets[short], f"{short}:{label}",
                       disabled=label in ("-", "!", "0"))
        decision_count = _decide_count(project)
        stages = _decide_stages(project)
        self._show(widgets["D"], f"D:{decision_count}",
                   disabled=not _visible_decisions(project),
                   tooltip=" · ".join(f"{stage} {count}" for stage, count in
                                      zip(("결정 대기", "답변 접수", "반영 중", "완료"), stages)),
                   classes={"decision-open": decision_count not in ("-", "!", "0")})
        active, slot = self._is_active(project), self._active_slot(project)
        leader_time = format_elapsed((project.get("leader") or {}).get("elapsed"))
        self._show(widgets["name"],
                   ("▶ " if active else "") + project["id"] + (f" {leader_time}" if leader_time else ""),
                   tooltip=project["id"] + (" · Leader session이 게시된 뒤 지난 시간" if leader_time else ""),
                   classes={"project-active": active})
        expanded = project["id"] in self._expanded_projects
        tooltip = "좌석 접기" if expanded else "좌석 펼치기"
        slot_hidden = slot not in (None, "leader") and not expanded      # the seat's own row is folded away
        if slot_hidden:
            tooltip += " · 현재 창: " + slot.replace("-", " ")
        self._show(widgets["seats"], "▾" if expanded else "▸",
                   tooltip=tooltip, classes={"slot-active": slot_hidden})

    def _fill_rows(self, widgets: dict, project: dict) -> None:
        """Seat rows and error rows of a project whose shape is the block's, in its widgets."""
        expanded = project["id"] in self._expanded_projects
        slot = self._active_slot(project)
        for seat in (project.get("seats", []) if expanded else []):
            button = widgets[f"seat-{seat['index']}"]
            live = self._seat_liveness(project, seat)
            tooltip = (f"{seat['job_id']}: {seat['title']}" if seat.get("title") else
                       seat.get("job_id") or f"{seat['index']} -")
            if seat.get("host"):
                tooltip += f" · 호스트: {seat['host']} · {seat['path']}"
            if seat.get("status") == "pending":
                tooltip += " · 시작 대기"
            elif seat.get("status") == "release_pending":
                tooltip += " · 반납 대기: Worker는 끝났고 CR이 in-progress에 있습니다. CR을 옮기면 반납됩니다"
            if live == "stopped":
                tooltip += " · 실행 종료"
            elif live == "unknown":
                tooltip += " · 실행 확인 불가"
            self._show(button, _seat_text(seat), tooltip=tooltip,
                       disabled=seat.get("job_id") is None or seat.get("session_id") is None,
                       classes={"slot-active": slot == f"seat-{seat['index']}",
                                "seat-empty": seat.get("job_id") is None,
                                "seat-pending": seat.get("job_id") is not None and seat.get("status") == "pending",
                                "seat-release-pending": (seat.get("job_id") is not None
                                                         and seat.get("status") == "release_pending"),
                                "seat-stopped": live == "stopped", "seat-unknown": live == "unknown"})
        for number, item in enumerate(project.get("errors", [])):
            row = widgets[f"error-{number}"]
            text = f"{item.get('source')}: {item.get('message')}"
            if str(row.content) != text:
                row.update(text)

    def _project_block(self, number: int, project: dict) -> Vertical:
        """A new block with the widgets of one project, and its click targets in `_actions`
        (ids are `project-<number>-...`). Values are written by `_fill_summary` and `_fill_rows`,
        the same code that updates a block that is already mounted."""
        prefix = f"project-{number}-"
        widgets = {short: Button("", id=f"{prefix}{short}", classes="cr-count") for short in ("O", "T", "I")}
        widgets["seats"] = Button("", id=f"{prefix}seats")
        widgets["name"] = name = Button("", id=f"{prefix}name", classes="project-name")
        name.styles.line_pad = 0
        widgets["D"] = Button("", id=f"{prefix}D", classes="decision")
        children = [name, widgets["D"],
                    Horizontal(*(widgets[key] for key in ("O", "T", "I", "seats")), classes="counts")]
        expanded = project["id"] in self._expanded_projects
        for seat in (project.get("seats", []) if expanded else []):
            widgets[f"seat-{seat['index']}"] = button = Button("", id=f"{prefix}seat-{seat['index']}", classes="seat")
            children.append(button)
        for index, _ in enumerate(project.get("errors", [])):
            widgets[f"error-{index}"] = row = Static("", classes="project-error")
            children.append(row)
        self._fill_summary(widgets, project)
        self._fill_rows(widgets, project)
        self._register_actions(number, project)
        if number < len(self._widgets):
            self._widgets[number] = widgets
        else:
            self._widgets.append(widgets)
        return Vertical(*children, classes="project")

    def _update_block(self, number: int, project: dict) -> None:
        """Write the changed values into the project's mounted widgets; nothing is mounted or removed."""
        self._fill_summary(self._widgets[number], project)
        self._fill_rows(self._widgets[number], project)
        self._register_actions(number, project)

    async def _render_projects(self) -> None:
        """Draw what changed. A project whose signature is unchanged keeps its widgets (BOARD-013). A changed
        value is written into the mounted widget. Rows that appear or disappear, and a changed project list,
        are applied inside one `batch_update`, so the screen only ever shows the state before or after the
        change (BOARD-017). The lock keeps two renders from interleaving their awaits."""
        async with self._render_lock:
            projects = self.snapshot_data.get("projects", [])
            error = self.snapshot_data.get("error")
            signature = (error.get("message") if error else None,
                         tuple(self._project_signature(project) for project in projects))
            old = self._signature
            if signature == old:
                return
            self._signature = signature
            scroll = self.query_one("#projects", VerticalScroll)
            previous_y = scroll.scroll_y
            focused_id = self.focused.id if self.focused else None
            same_list = (old is not None and projects and len(old[1]) == len(signature[1])
                         and all(before[0] == after[0] for before, after in zip(old[1], signature[1])))
            with self.batch_update():
                self.query_one("#board-error", Static).update(signature[0] or "")
                if same_list:
                    for number, project in enumerate(projects):
                        if old[1][number] == signature[1][number]:
                            continue
                        shape = self._shape(project)
                        if shape == self._shapes[number]:
                            self._update_block(number, project)
                            continue
                        stale = self._blocks[number]
                        self._blocks[number] = block = self._project_block(number, project)
                        self._shapes[number] = shape
                        await scroll.mount(block, before=stale)      # the list never gets shorter, so its scroll position stays
                        await stale.remove()
                else:
                    await scroll.remove_children()
                    self._actions.clear()
                    self._widgets = []
                    self._blocks = [self._project_block(number, project) for number, project in enumerate(projects)]
                    self._shapes = [self._shape(project) for project in projects]
                    await scroll.mount(*(self._blocks or [Static("등록된 project가 없습니다.")]))

            def restore() -> None:
                scroll.scroll_to(y=previous_y, animate=False)
                if focused_id:
                    selected = self.query(f"#{focused_id}")
                    if selected:
                        selected.first().focus()

            self.call_after_refresh(restore)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        target = self._actions.get(event.button.id or "")
        if target is None:
            return
        self._activate(target)

    def _activate(self, target: tuple, *, client: str | None = None) -> None:
        kind = target[0]
        if kind == "seats":
            _, project_id = target
            if self.expanded_toggler is not None:
                self._queue(self._toggle_expanded(project_id))
            else:
                if project_id in self._expanded_projects:
                    self._expanded_projects.remove(project_id)
                else:
                    self._expanded_projects.add(project_id)
                self._queue(self._render_projects())
        elif kind == "project" and self.on_project is not None:
            _, project_id = target
            self._queue(self._call_external(self.on_project, project_id,
                                            **({"client": client} if client else {})))
        elif kind == "cr" and self.on_cr is not None:
            _, project, state = target
            self._queue(self._call_external(self.on_cr, project["id"], state,
                                            **({"client": client} if client else {})))
        elif kind == "decision" and self.on_decision is not None:
            _, project_id = target
            self._queue(self._call_external(self.on_decision, project_id, None,
                                            **({"client": client} if client else {})))
        elif kind == "seat" and self.on_seat is not None:
            _, project_id, seat_index = target
            self._queue(self._call_external(self.on_seat, project_id, seat_index,
                                            **({"client": client} if client else {})))

    async def _toggle_expanded(self, project_id: str) -> None:
        try:
            async with self._expansion_lock:
                self._expanded_projects = await asyncio.to_thread(self.expanded_toggler, project_id)
            if not self._stopping:
                await self._render_projects()
        except Exception as error:
            if not self._stopping:
                self.notify(str(error), severity="error")

    async def _call_external(self, callback, *args, **kwargs) -> None:
        try:
            result = await asyncio.to_thread(callback, *args, **kwargs)
            if isinstance(result, dict) and not result.get("ok", False):
                error = result.get("error") or {}
                self.notify(error.get("message") or error.get("code") or "tmux 동작 실패", severity="error")
        except Exception as error:
            self.notify(str(error), severity="error")


class CSVScreen(Screen):
    CSS = """
    CSVScreen { background: #111c28; }
    #csv-heading { height: auto; text-style: bold; }
    #csv-view { height: 1fr; }
    #csv-close { height: 1; min-width: 0; border: none; }
    """
    BINDINGS = [("escape", "back", "돌아가기")]

    def __init__(self, title: str, contents: str):
        super().__init__()
        self.title = title
        self.contents = contents

    def compose(self) -> ComposeResult:
        yield Static(self.title, id="csv-heading")
        yield _csv_table(self.contents, id="csv-view")
        yield Button("돌아가기", id="csv-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "csv-close":
            self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()


CR_GROUPS = (("open", "Open"), ("todo", "Todo"), ("in-progress", "In-Progress"), ("done", "Done"))


class CRPopupApp(App):
    """A read-only CR reader in a client-local tmux popup. One window shows the four states as foldable
    groups and ◀▶ moves between the registered projects (BOARD-021)."""

    CSS = """
    Screen { background: #111c28; }
    #cr-title { height: 1; padding: 0 1; text-style: bold; }
    #cr-main { height: 1fr; }
    #cr-items { width: 40%; min-width: 30; max-width: 46; border-right: solid #536474; }
    #cr-detail { width: 1fr; padding: 0 1; }
    #cr-actions { height: 2; }
    #cr-actions Button { height: 1; width: auto; min-width: 0; border: none; margin-right: 1; }
    Button.group-header { width: 100%; height: 1; min-width: 0; border: none; padding: 0 1;
                          content-align: left middle; text-align: left; text-style: bold;
                          background: #22344a; color: #ffe1a0; }
    Button.group-header:focus { background: #2b3d52; text-style: bold; }
    .group-empty { color: #8097ad; padding: 0 1; }
    #cr-show-list { display: none; }
    .narrow #cr-show-list { display: block; }
    .narrow #cr-items { display: none; }
    .narrow.list-open #cr-items { display: block; width: 100%; max-width: 100%; }
    .narrow.list-open #cr-detail { display: none; }
    """ + NAV_CSS + LIST_ITEM_CSS
    BINDINGS = [("escape", "quit", "닫기")]

    def __init__(self, config: str | None, project_id: str, state: str, *, load: bool = True):
        super().__init__()
        self.config = config
        self.project_id = project_id
        self.focus_state: str | None = state      # the group to show first; only the first load uses it
        self.load = load
        self.project: dict | None = None
        self.order: list[str] = []
        self.items: list[dict] = []
        self.selected_id: str | None = None
        self.collapsed: set[str] = {"done"}      # BOARD-026: the many done CRs start folded
        self._targets: dict[int, str | None] = {}
        self._load_generation = 0
        self._title_task: asyncio.Task | None = None
        self._closing = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="nav-row"):
            yield Button("◀", id="cr-prev", disabled=True)
            yield Static(self.project_id, id="cr-project")
            yield Button("▶", id="cr-next", disabled=True)
        yield Static("", id="cr-title")
        with Horizontal(id="cr-main"):
            yield VerticalScroll(id="cr-items")
            yield VerticalScroll(id="cr-detail")
        with Horizontal(id="cr-actions"):
            yield Button("목록", id="cr-show-list")
            yield Button("닫기", id="cr-close")

    def on_mount(self) -> None:
        if self.load:
            asyncio.create_task(self.refresh_items())

    def on_unmount(self) -> None:
        self._closing = True
        self._load_generation += 1
        if self._title_task is not None:
            self._title_task.cancel()

    async def refresh_items(self) -> None:
        project_id = self.project_id
        try:
            data = await asyncio.to_thread(model.popup_snapshot, self.config, project_id, True)
            if not self._closing and project_id == self.project_id:
                await self.apply_snapshot(data)
        except Exception as error:
            if not self._closing:
                await self._show_message(f"CR 목록을 읽을 수 없습니다: {error}")

    def _groups(self) -> dict[str, list[dict]]:
        crs = (self.project or {}).get("crs") or {}
        return {state: crs.get(state, []) for state, _ in CR_GROUPS}

    async def apply_snapshot(self, data: dict) -> None:
        projects = data.get("projects", [])
        self.order = data.get("order") or [item["id"] for item in projects]
        self.project = next((item for item in projects if item["id"] == self.project_id), None)
        self.query_one("#cr-project", Static).update(self.project_id)
        self._targets = _set_nav(self.query_one("#cr-prev", Button), self.query_one("#cr-next", Button),
                                 self.order, self.project_id, set(self.order))
        listing = self.query_one("#cr-items", VerticalScroll)
        await listing.remove_children()
        groups = self._groups()
        self.items = [item for state, _ in CR_GROUPS for item in groups[state]]
        counts = ", ".join(f"{label} {len(groups[state])}" for state, label in CR_GROUPS)
        self.query_one("#cr-title", Static).update(counts)
        if self.project is None:
            await listing.mount(Static("Project를 찾을 수 없습니다."))
            await self._show_message("Project를 찾을 수 없습니다.")
            return
        widgets, index = [], 0
        for state, label in CR_GROUPS:
            widgets.append(Button(self._group_label(state), id=f"cr-group-{state}", classes="group-header"))
            for item in groups[state]:
                row = Button(self._row_label(item), id=f"cr-item-{index}", classes="list-item")
                row.display = state not in self.collapsed
                widgets.append(row)
                index += 1
            if not groups[state]:
                empty = Static("  없음", id=f"cr-empty-{state}", classes="group-empty")
                empty.display = state not in self.collapsed
                widgets.append(empty)
        await listing.mount(*widgets)
        if not any(item["id"] == self.selected_id for item in self.items):
            first = next((item for item in groups.get(self.focus_state, [])), None) or next(iter(self.items), None)
            self.selected_id = first["id"] if first else None
        self._mark_selected()
        if self.items:
            await self._show_cr()
        else:
            await self._show_message("CR이 없습니다.")
        if self._title_task is not None:
            self._title_task.cancel()
        self._title_task = asyncio.create_task(self._fill_done_titles(self.items))
        focus, self.focus_state = self.focus_state, None
        if focus is not None:
            self.call_after_refresh(listing.scroll_to_widget, self.query_one(f"#cr-group-{focus}"),
                                    animate=False, top=True)
        else:
            listing.scroll_home(animate=False)

    async def _fill_done_titles(self, items: list[dict]) -> None:
        """The done list shows file-name titles at once; the real titles replace them one file at a time."""
        for index, item in enumerate(items):
            if item["state"] != "done":
                continue
            try:
                title = await asyncio.to_thread(model.done_title, item)
            except (OSError, UnicodeError):
                continue
            if self._closing or items is not self.items:
                return
            if title:
                item["title"] = title
                self.query_one(f"#cr-item-{index}", Button).label = self._row_label(item)

    def _group_label(self, state: str) -> str:
        label = dict(CR_GROUPS)[state]
        return f"{label} {'▶' if state in self.collapsed else '▼'}"

    def _row_label(self, item: dict) -> Content:
        return _item_label(item["id"] == self.selected_id, item["id"], _cr_status(item), item["title"])

    def _mark_selected(self) -> None:
        for index, item in enumerate(self.items):
            button = self.query_one(f"#cr-item-{index}", Button)
            button.label = self._row_label(item)
            button.set_class(item["id"] == self.selected_id, "selected")

    def _fold(self, state: str) -> None:
        self.collapsed ^= {state}
        self.query_one(f"#cr-group-{state}", Button).label = self._group_label(state)
        for index, item in enumerate(self.items):
            if item["state"] == state:
                self.query_one(f"#cr-item-{index}", Button).display = state not in self.collapsed
        for empty in self.query(f"#cr-empty-{state}"):
            empty.display = state not in self.collapsed

    async def _show_message(self, message: str) -> None:
        self._load_generation += 1
        detail = self.query_one("#cr-detail", VerticalScroll)
        await detail.remove_children()
        await detail.mount(Static(message))

    async def _show_cr(self) -> None:
        item = next((row for row in self.items if row["id"] == self.selected_id), None)
        if item is None or self.project is None:
            return
        self._load_generation += 1
        generation = self._load_generation
        try:
            source = await asyncio.to_thread(model.read_cr_markdown, self.project, item, item["state"])
        except (OSError, UnicodeError, ValueError) as error:
            source = None
            message = f"{item['id']} 파일을 읽을 수 없습니다: {error}"
        if self._closing or generation != self._load_generation:
            return
        detail = self.query_one("#cr-detail", VerticalScroll)
        await detail.remove_children()
        await detail.mount(Markdown(source, open_links=False) if source is not None else Static(message))
        detail.scroll_home(animate=False)

    async def _move(self, step: int) -> None:
        target = self._targets.get(step)
        if target is None:
            return
        self.project_id = target
        self.selected_id = None
        await self.refresh_items()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("cr-item-"):
            index = int(button_id.removeprefix("cr-item-"))
            self.selected_id = self.items[index]["id"]
            self._mark_selected()
            await self._show_cr()
            self.remove_class("list-open")
        elif button_id.startswith("cr-group-"):
            self._fold(button_id.removeprefix("cr-group-"))
        elif button_id in ("cr-prev", "cr-next"):
            await self._move(-1 if button_id == "cr-prev" else 1)
        elif button_id == "cr-show-list":
            self.toggle_class("list-open")
        elif button_id == "cr-close":
            self.exit()

    def on_resize(self, event) -> None:
        narrow = event.size.width < 70
        self.set_class(narrow, "narrow")
        if not narrow:
            self.remove_class("list-open")


class AnswerArea(TextArea):
    """The answer box: Ctrl+J (LF from the terminal) inserts a newline like Enter."""

    async def _on_key(self, event) -> None:
        if event.key == "ctrl+j" and not self.read_only:
            event.stop()
            event.prevent_default()
            self._replace_via_keyboard("\n", *self.selection)
            return
        await super()._on_key(event)


class PopupApp(App):
    """Focused decision reader with a multiline answer editor."""

    CSS = """
    Screen { background: #101923; }
    #popup-heading { height: 1; padding: 0 1; text-style: bold; color: #f3f6ff; }
    #popup-main { height: 1fr; }
    #decision-list { width: 40%; min-width: 30; max-width: 46; border-right: solid #536474; }
    #decision-detail { width: 1fr; padding: 0 1; }
    .decision-meta { height: auto; color: #c9dbed; }
    .section-title { height: auto; text-style: bold; color: #ffe1a0; }
    .csv-table { height: auto; min-height: 4; max-height: 18; width: 100%; }
    .evidence-toggle { height: 1; min-width: 0; width: auto; border: none; padding: 0; }
    #answer-label { height: 1; color: #ffe1a0; }
    #answer { height: 5; border: solid #536474; }
    #popup-actions { height: 2; }
    #popup-actions Button { height: 1; min-width: 0; width: auto; border: none; margin-right: 1; }
    #show-list { display: none; }
    .narrow #show-list { display: block; }
    #popup-message { height: auto; min-height: 1; max-height: 3; color: #ffcb84; }
    .narrow #decision-list { display: none; }
    .narrow.list-open #decision-list { display: block; width: 100%; max-width: 100%; }
    .narrow.list-open #decision-detail { display: none; }
    """ + NAV_CSS + LIST_ITEM_CSS
    BINDINGS = [("escape", "quit", "닫기"), ("ctrl+s", "send", "전송")]

    def __init__(
        self,
        config: str | None,
        project_id: str,
        decide_id: str | None = None,
        *,
        snapshot_reader: SnapshotReader | None = None,
        navigation_reader: SnapshotReader | None = None,
        answer_sender: Callable[[str | None, str, str, str], dict] | None = None,
        load: bool = True,
    ):
        super().__init__()
        self.config = config
        self.project_id = project_id
        self.decide_id = decide_id
        self.snapshot_reader = snapshot_reader or self._read_project
        self.navigation_reader = navigation_reader or model.snapshot
        self.answer_sender = answer_sender or answer.submit_answer
        self.load = load
        self.project: dict | None = None
        self.decisions: dict[str, dict] = {}
        self._sending = False
        self._closing = False
        self._evidence_open = False
        self._drafts: dict[tuple[str, str], str] = {}   # (project ID, decision ID) -> unsent answer
        self._last_selected: dict[str, str] = {}        # project ID -> the decision shown when it was left
        self.order: list[str] = []
        self.eligible: set[str] = set()                 # projects whose decisions the popup shows (the sidebar's `D`)
        self._navigation_loaded = False
        self._targets: dict[int, str | None] = {}
        self._switched = False                          # a project change waits for its decisions to load
        self._tasks: set[asyncio.Task] = set()

    def _read_project(self, config: str | None) -> dict:
        return model.popup_snapshot(config, self.project_id)

    def compose(self) -> ComposeResult:
        with Horizontal(classes="nav-row"):
            yield Button("◀", id="popup-prev", disabled=True)
            yield Static(self.project_id, id="popup-project")
            yield Button("▶", id="popup-next", disabled=True)
        yield Static("결정 항목을 읽는 중…", id="popup-heading")
        with Horizontal(id="popup-main"):
            yield VerticalScroll(id="decision-list")
            yield VerticalScroll(id="decision-detail")
        yield Static("답변", id="answer-label")
        yield AnswerArea(id="answer", placeholder="결정 내용을 읽고 답변을 입력하세요.")
        with Horizontal(id="popup-actions"):
            yield Button("목록", id="show-list")
            yield Button("전송", id="send")
            yield Button("닫기", id="close")
        yield Static("", id="popup-message")

    def on_mount(self) -> None:
        if self.load:
            self._queue(self.refresh_decisions())

    def on_unmount(self) -> None:
        self._closing = True
        for task in self._tasks:
            task.cancel()

    def _queue(self, coroutine) -> None:
        if self._closing:
            coroutine.close()
            return
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def refresh_decisions(self) -> None:
        project_id = self.project_id
        try:
            data = await asyncio.to_thread(self.snapshot_reader, self.config)
            if not self._closing and project_id == self.project_id:
                await self.apply_snapshot(data)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.query_one("#popup-message", Static).update(str(error))

    async def apply_snapshot(self, data: dict) -> None:
        projects = data.get("projects", [])
        self.project = next((item for item in projects if item["id"] == self.project_id), None)
        self.query_one("#popup-project", Static).update(self.project_id)
        self._learn_projects(data)
        if not self._navigation_loaded and len(projects) < 2:
            self._navigation_loaded = True
            self._queue(self._load_navigation())
        if self.project is None:
            self.query_one("#popup-heading", Static).update(f"{self.project_id}: project를 찾을 수 없습니다.")
            return
        items = _visible_decisions(self.project)
        self.decisions = {item["id"]: item for item in items}
        if self.decide_id not in self.decisions or self._switched:
            if self.decide_id not in self.decisions:
                self.decide_id = items[0]["id"] if items else None
            self._switched = False
            self.query_one("#answer", TextArea).text = (
                self._drafts.get((self.project_id, self.decide_id), "")
                if self.decisions.get(self.decide_id, {}).get("state") == "open" else "")
            self._evidence_open = False
        listing = self.query_one("#decision-list", VerticalScroll)
        await listing.remove_children()
        if items:
            await listing.mount(*[Button(self._row_label(item), id=f"decision-{index}", classes="list-item")
                                  for index, item in enumerate(items)])
        else:
            await listing.mount(Static("결정 항목이 없습니다."))
        await self._show_decision()

    def _learn_projects(self, data: dict) -> None:
        """Take the project order and which projects have decisions to show from a snapshot. A snapshot of one
        project only updates that project; the others are learned by `_load_navigation`."""
        projects = data.get("projects", [])
        self.order = data.get("order") or [item["id"] for item in projects] or self.order
        for item in projects:
            # the projects the sidebar's `D` opens: the ones with a decision that is not complete
            (self.eligible.add if _visible_decisions(item) else self.eligible.discard)(item["id"])
        if len(projects) > 1:
            self._navigation_loaded = True
        self._targets = _set_nav(self.query_one("#popup-prev", Button), self.query_one("#popup-next", Button),
                                 self.order, self.project_id, self.eligible)

    async def _load_navigation(self) -> None:
        """The other projects are read after the window is up: reading every project is slow on a cold start."""
        try:
            data = await asyncio.to_thread(self.navigation_reader, self.config)
            if not self._closing:
                self._learn_projects({"projects": data.get("projects", []), "order": self.order})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.query_one("#popup-message", Static).update(f"project 이동 목록을 읽을 수 없습니다: {error}")

    def _row_label(self, item: dict) -> Content:
        return _item_label(item["id"] == self.decide_id, item["id"], _decision_status(item), item["title"])

    def _mark_selected(self) -> None:
        for index, item in enumerate(self.decisions.values()):
            button = self.query_one(f"#decision-{index}", Button)
            button.label = self._row_label(item)
            button.set_class(item["id"] == self.decide_id, "selected")

    def _sync_answer_controls(self) -> None:
        item = self.decisions.get(self.decide_id)
        editable = item is not None and item.get("state") == "open"
        self.query_one("#answer", TextArea).disabled = not editable
        self.query_one("#send", Button).disabled = not editable or self._sending

    async def _show_decision(self) -> None:
        self._mark_selected()
        detail = self.query_one("#decision-detail", VerticalScroll)
        await detail.remove_children()
        item = self.decisions.get(self.decide_id)
        if item is None:
            self.query_one("#popup-heading", Static).update("결정 없음")
            self._sync_answer_controls()
            return
        position = list(self.decisions).index(item["id"]) + 1
        self.query_one("#popup-heading", Static).update(
            f"결정 {position}/{len(self.decisions)} · {item['id']} · {item['display_state']}")
        meta = "\n".join(filter(None, [
            item["title"],
            f"상태: {item['display_state']}",
            f"긴급도: {item.get('urgency', 'normal')}",
            f"막는 일: {item['blocks']}" if item.get("blocks") else "",
            f"관련: {item['related']}" if item.get("related") else "",
        ]))
        widgets = [Static(meta, classes="decision-meta")]
        for section in item.get("sections", []):
            name = section["name"]
            if name == "Evidence":
                widgets.append(Button("Evidence 펼치기" if not self._evidence_open else "Evidence 접기",
                                      id="evidence-toggle", classes="evidence-toggle"))
                evidence = Vertical(*_body_widgets(section["body"]), id="evidence-body")
                evidence.display = self._evidence_open
                widgets.append(evidence)
            else:
                widgets.append(Static(name, classes="section-title"))
                widgets.extend(_body_widgets(section["body"]))
        await detail.mount(*widgets)
        detail.scroll_home(animate=False)
        self._sync_answer_controls()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("decision-"):
            index = int(button_id.removeprefix("decision-"))
            if index >= len(self.decisions):            # a project change is still loading
                return
            self._keep_draft()
            self.decide_id = list(self.decisions)[index]
            self.query_one("#answer", TextArea).text = (
                self._drafts.get((self.project_id, self.decide_id), "")
                if self.decisions[self.decide_id].get("state") == "open" else "")
            self._evidence_open = False
            await self._show_decision()
            self.remove_class("list-open")
        elif button_id in ("popup-prev", "popup-next"):
            self._move(-1 if button_id == "popup-prev" else 1)
        elif button_id == "evidence-toggle":
            self._evidence_open = not self._evidence_open
            evidence = self.query_one("#evidence-body", Vertical)
            evidence.display = self._evidence_open
            event.button.label = "Evidence 접기" if self._evidence_open else "Evidence 펼치기"
        elif button_id == "show-list":
            self.toggle_class("list-open")
        elif button_id == "send":
            self.action_send()
        elif button_id == "close":
            self.exit()

    def _keep_draft(self) -> None:
        if self.decide_id is not None and self.decisions.get(self.decide_id, {}).get("state") == "open":
            self._drafts[(self.project_id, self.decide_id)] = self.query_one("#answer", TextArea).text

    def _move(self, step: int) -> None:
        """Show the neighbouring project in this window. The unsent answer stays with its decision."""
        target = self._targets.get(step)
        if target is None or self._sending:
            return
        self._keep_draft()
        self._last_selected[self.project_id] = self.decide_id
        self.project_id = target
        self.decide_id = self._last_selected.get(target)
        self.decisions = {}
        self._switched = True
        self._queue(self.refresh_decisions())

    def on_resize(self, event) -> None:
        narrow = event.size.width < 70
        self.set_class(narrow, "narrow")
        if not narrow:
            self.remove_class("list-open")

    def action_send(self) -> None:
        item = self.decisions.get(self.decide_id)
        if self._sending or item is None or item.get("state") != "open" or isinstance(self.screen, CSVScreen):
            return
        draft = self.query_one("#answer", TextArea).text
        self._sending = True
        self._queue(self._send(draft, self.decide_id))

    async def _send(self, draft: str, decide_id: str) -> None:
        send = self.query_one("#send", Button)
        send.disabled = True
        self.query_one("#popup-message", Static).update("전송 중…")
        try:
            result = await asyncio.to_thread(self.answer_sender, self.config, self.project_id, decide_id, draft)
            if self._closing:
                return
            accepted = result.get("ok") and (result.get("data") or {}).get("accepted")
            if accepted:
                item = self.decisions.get(decide_id)
                if item is not None:
                    item["state"] = "answered"
                    item["display_state"] = "답변 접수"
                self._drafts.pop((self.project_id, decide_id), None)
                editor = self.query_one("#answer", TextArea)
                if self.decide_id == decide_id:
                    editor.text = ""
                await self.refresh_decisions()
                notification = (result.get("data") or {}).get("notification") or {}
                status = notification.get("status")
                if status == "sent":
                    message = "답변 접수 · Leader 알림 완료"
                elif status == "unconfirmed":
                    message = "답변 접수 · Leader 알림 결과 불명. 접수 기록은 저장됐습니다."
                else:
                    message = "답변 접수 · Leader 알림 실패. 접수 기록은 저장됐습니다."
                if (result.get("data") or {}).get("page_error"):
                    message += " 결정 페이지 갱신에 실패했습니다."
                self.query_one("#popup-message", Static).update(message)
            else:
                error = result.get("error") or {}
                self.query_one("#popup-message", Static).update(
                    error.get("message") or error.get("code") or "답변 접수를 확인하지 못했습니다.")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if not self._closing:
                self.query_one("#popup-message", Static).update(str(error))
        finally:
            self._sending = False
            if not self._closing:
                self._sync_answer_controls()

    def on_markdown_link_clicked(self, event: Markdown.LinkClicked) -> None:
        href = event.href
        parts = urlsplit(href)
        if parts.scheme in ("http", "https"):
            self._queue(asyncio.to_thread(webbrowser.open, href))
            return
        decoded_path = unquote(parts.path)
        if parts.scheme or parts.netloc or not decoded_path.lower().endswith(".csv"):
            self.notify("CSV 파일 링크만 TUI 표로 열 수 있습니다.", severity="warning")
            return
        item = self.decisions.get(self.decide_id)
        if item is None or self.project is None or not item.get("path"):
            return
        base = Path(self.project["base"]).resolve()
        path = (Path(item["path"]).parent / decoded_path).resolve()
        if not path.is_relative_to(base):
            self.notify("Project 밖의 CSV 파일은 열 수 없습니다.", severity="error")
            return
        self._queue(self._open_csv(path))

    async def _open_csv(self, path: Path) -> None:
        try:
            contents = await asyncio.to_thread(path.read_text, encoding="utf-8-sig")
            if not self._closing:
                self.push_screen(CSVScreen(path.name, contents))
        except OSError as error:
            if not self._closing:
                self.notify(str(error), severity="error")


def run_sidebar(
    config: str | None = None,
    *,
    on_project: ProjectCallback | None = None,
    on_decision: DecisionCallback | None = None,
    on_cr: CrCallback | None = None,
    on_seat: SeatCallback | None = None,
    click_socket: str | None = None,
    expanded_reader: ExpandedReader | None = None,
    expanded_toggler: ExpandedToggler | None = None,
    mark_ready: Callable[[], bool] | None = None,
    visibility_reader: Callable[[], bool] | None = None,
    context_reader: ContextReader | None = None,
) -> int:
    SidebarApp(config, on_project=on_project, on_decision=on_decision, on_cr=on_cr, on_seat=on_seat,
               click_socket=click_socket or os.environ.get("PROJECT_BOARD_CLICK_SOCKET"),
               expanded_reader=expanded_reader, expanded_toggler=expanded_toggler,
               mark_ready=mark_ready, visibility_reader=visibility_reader,
               context_reader=context_reader).run()
    return 0


def run_cr_popup(config: str | None, project_id: str, state: str) -> int:
    CRPopupApp(config, project_id, state).run()
    return 0


def run_popup(config: str | None, project_id: str, decide_id: str | None = None) -> int:
    PopupApp(config, project_id, decide_id).run()
    return 0
