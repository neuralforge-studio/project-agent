"""Popup terminal UIs of the Project Board (decision and CR readers).

The snapshot and answer modules own project facts and permission checks. This
module renders them and keeps blocking reads away from Textual's UI loop. The
sidebar is the `project-board-sidebar` binary (tools/project-board/rust).
"""
from __future__ import annotations

import asyncio
import csv
import datetime as dt
import io
import os
import re
import webbrowser
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlsplit

from textual.app import App, ComposeResult
from textual.content import Content
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Markdown, Static, TextArea

from . import answer, model, window_link

SnapshotReader = Callable[[str | None], dict]
LinkMarker = Callable[[str], bool]

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


def _visible_decisions(project: dict) -> list[dict]:
    return [item for item in project.get("decide") or [] if item.get("display_state") != "완료"]


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


def cr_head(source: str, minimum: int = 30) -> str | None:
    """The head of a long CR for a first screen: the lines before the first section heading (`## `) that
    comes at or after line `minimum`, outside a code fence. None when the CR is short or has no such heading.
    It ends where a section ends, so it is whole blocks and shows as the document does."""
    lines = source.split("\n")
    if len(lines) < minimum * 2:
        return None
    fenced = False
    for number, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced and number >= minimum and line.startswith("## "):
            return "\n".join(lines[:number]).rstrip("\n") + "\n"
    return None


READING = "읽는 중…"
READING_DECISIONS = "결정 항목을 읽는 중…"
READING_PROJECTS = "◀▶로 이동할 다른 project의 결정 항목을 읽는 중…"
READING_CR = "CR 목록을 읽는 중…"
CR_GROUPS = (("open", "Open"), ("todo", "Todo"), ("in-progress", "In-Progress"), ("done", "Done"))


class _ListWindow(App):
    """The frame of a read-only Board window that lists items on the left and shows the selected one on the right,
    under `◀ project ▶` (the CR window, the cron window). The widget IDs keep the `cr-` prefix of the first of them.

    The window listens on `link` for a click that tells it what to show next (BOARD-025); a subclass answers the
    request (`_on_request`) and reads and shows its items (`refresh_items`)."""

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
    reading_list = ""                             # what the right side says while the list is read

    def __init__(self, config: str | None, project_id: str, *, load: bool = True,
                 link: str | None = None, mark_link: LinkMarker | None = None):
        super().__init__()
        self.config = config
        self.link = link                          # the socket on which a click tells this window what to show next
        self.mark_link = mark_link
        self._server: asyncio.AbstractServer | None = None
        self._tasks: set[asyncio.Task] = set()
        self.project_id = project_id
        self.load = load
        self.order: list[str] = []
        self.items: list[dict] = []
        self.selected_id: str | None = None
        self._targets: dict[int, str | None] = {}
        self._load_generation = 0
        self._closing = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="nav-row"):
            yield Button("◀", id="cr-prev", disabled=True)
            yield Static(self.project_id, id="cr-project")
            yield Button("▶", id="cr-next", disabled=True)
        yield Static(READING, id="cr-title")
        with Horizontal(id="cr-main"):
            yield VerticalScroll(id="cr-items")
            with VerticalScroll(id="cr-detail"):
                yield Static(self.reading_list)
        with Horizontal(id="cr-actions"):
            yield Button("목록", id="cr-show-list")
            yield Button("닫기", id="cr-close")

    def on_mount(self) -> None:
        if self.link:
            self._queue(self._listen())
        if self.load:
            self._queue(self.refresh_items())

    def on_unmount(self) -> None:
        self._closing = True
        self._load_generation += 1
        window_link.stop(self._server, self.link)

    def _queue(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _listen(self) -> None:
        """Take what a click asks this window to show (BOARD-025), then say so: a click that finds no
        listener, or one that fails, starts the window again."""
        try:
            self._server = await window_link.serve(self.link, self._on_request)
        except OSError:
            pass
        if self.mark_link is not None:
            await asyncio.to_thread(self.mark_link, self.link)

    def _on_request(self, request: dict) -> dict:
        raise NotImplementedError

    async def refresh_items(self) -> None:
        raise NotImplementedError

    async def _reload(self) -> None:
        """Show that the list is being read, then read it."""
        self.query_one("#cr-title", Static).update(READING)
        await self._show_message(self.reading_list)
        await self.refresh_items()

    async def _show_message(self, message: str) -> None:
        self._load_generation += 1
        detail = self.query_one("#cr-detail", VerticalScroll)
        await detail.remove_children()
        await detail.mount(Static(message))

    async def _move(self, step: int) -> None:
        target = self._targets.get(step)
        if target is None:
            return
        self.project_id = target
        self.selected_id = None
        await self.refresh_items()

    async def _pressed(self, button_id: str) -> None:
        """A button that is not the frame's own (a list row, a group header)."""

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id in ("cr-prev", "cr-next"):
            await self._move(-1 if button_id == "cr-prev" else 1)
        elif button_id == "cr-show-list":
            self.toggle_class("list-open")
        elif button_id == "cr-close":
            self.exit()
        else:
            await self._pressed(button_id)

    def on_resize(self, event) -> None:
        narrow = event.size.width < 70
        self.set_class(narrow, "narrow")
        if not narrow:
            self.remove_class("list-open")


class CRPopupApp(_ListWindow):
    """A read-only CR reader in a client-local tmux popup. One window shows the four states as foldable
    groups and ◀▶ moves between the registered projects (BOARD-021)."""

    reading_list = READING_CR

    def __init__(self, config: str | None, project_id: str, state: str, *, load: bool = True,
                 link: str | None = None, mark_link: LinkMarker | None = None):
        super().__init__(config, project_id, load=load, link=link, mark_link=mark_link)
        self._warmed = False                      # the other projects' CRs were read ahead (`_warm`)
        self._unmounted: set[str] = set()         # folded groups whose rows are not mounted yet
        self.focus_state: str | None = state      # the group to show first; only the first load uses it
        self.project: dict | None = None
        self.collapsed: set[str] = {"done"}      # BOARD-026: the many done CRs start folded
        self._title_task: asyncio.Task | None = None

    def on_unmount(self) -> None:
        if self._title_task is not None:
            self._title_task.cancel()
        super().on_unmount()

    def _on_request(self, request: dict) -> dict:
        project, state = request.get("project"), request.get("state")
        if (request.get("kind") != "cr" or not isinstance(project, str) or state not in model.CR_STATES
                or not isinstance(request.get("client", ""), str)):
            return window_link.reply(False, "invalid", "CR 창이 받을 수 없는 요청입니다.")
        if self._closing:
            return window_link.reply(False, "closing", "CR 창이 닫히는 중입니다.")
        self.project_id = project
        self.focus_state = state
        self.selected_id = None
        self.query_one("#cr-project", Static).update(project)
        self._queue(self._reload())
        return window_link.reply()

    async def refresh_items(self) -> None:
        project_id = self.project_id
        try:
            data = await asyncio.to_thread(model.popup_snapshot, self.config, project_id, True, model.ONLY_CRS)
            if not self._closing and project_id == self.project_id:
                await self.apply_snapshot(data)
                if not self._warmed:
                    self._warmed = True
                    self._queue(self._warm(data.get("order") or []))
        except Exception as error:
            if not self._closing:
                await self._show_message(f"CR 목록을 읽을 수 없습니다: {error}")

    async def _warm(self, order: list[str]) -> None:
        """Read the other projects' CRs once the window is up, one project at a time. The files are kept by `model`
        (`_cached`), so a click that shows another project later finds them read: reading a project of dozens of CRs
        cold is seconds on a loaded host, and the new item must appear at once (BOARD-025)."""
        for project_id in order:
            if self._closing:
                return
            if project_id == self.project_id:
                continue
            try:
                await asyncio.to_thread(model.popup_snapshot, self.config, project_id, True, model.ONLY_CRS)
            except Exception:
                pass                                  # the window reads it again, and reports it, when it is shown

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
        self._unmounted = set()
        for state, label in CR_GROUPS:
            widgets.append(Button(self._group_label(state), id=f"cr-group-{state}", classes="group-header"))
            if state in self.collapsed and groups[state]:
                # A folded group shows nothing, and each row is a widget to lay out: 1500 done CRs took 2.5 s
                # (measured). Its rows are mounted when it is unfolded (`_mount_rows`).
                self._unmounted.add(state)
                index += len(groups[state])
                continue
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
        self._start_titles()
        focus, self.focus_state = self.focus_state, None
        if focus is not None:
            self.call_after_refresh(listing.scroll_to_widget, self.query_one(f"#cr-group-{focus}"),
                                    animate=False, top=True)
        else:
            listing.scroll_home(animate=False)

    def _start_titles(self) -> None:
        """Read the done titles of the list as it is now, once its Done rows are on the screen. Folded, nobody
        sees them and each is a file read (1500 files took 19 s on a loaded host): unfolding starts it."""
        if self._title_task is not None:
            self._title_task.cancel()
            self._title_task = None
        if "done" not in self._unmounted and any(item["state"] == "done" for item in self.items):
            self._title_task = asyncio.create_task(self._fill_done_titles(self.items))

    async def _fill_done_titles(self, items: list[dict]) -> None:
        """The done list shows file-name titles at once; the real titles replace them one file at a time."""
        for index, item in enumerate(items):
            if item["state"] != "done" or item.get("title_read"):
                continue
            try:
                title = await asyncio.to_thread(model.done_title, item)
            except (OSError, UnicodeError):
                continue
            if self._closing or items is not self.items:
                return
            item["title_read"] = True
            if title:
                item["title"] = title
                for row in self.query(f"#cr-item-{index}"):
                    row.label = self._row_label(item)

    def _group_label(self, state: str) -> str:
        label = dict(CR_GROUPS)[state]
        return f"{label} {'▶' if state in self.collapsed else '▼'}"

    def _row_label(self, item: dict) -> Content:
        return _item_label(item["id"] == self.selected_id, item["id"], _cr_status(item), item["title"])

    def _rows(self) -> dict[str, Button]:
        """The mounted list rows by id (one pass over the list: a query per row is quadratic in a long list)."""
        return {row.id: row for row in self.query("#cr-items .list-item") if isinstance(row, Button)}

    def _mark_selected(self) -> None:
        rows = self._rows()
        for index, item in enumerate(self.items):
            button = rows.get(f"cr-item-{index}")
            if button is None:                                       # the row of a folded group is not mounted yet
                continue
            button.label = self._row_label(item)
            button.set_class(item["id"] == self.selected_id, "selected")

    async def _fold(self, state: str) -> None:
        self.collapsed ^= {state}
        header = self.query_one(f"#cr-group-{state}", Button)
        header.label = self._group_label(state)
        if state in self._unmounted and state not in self.collapsed:
            await self._mount_rows(state, header)
        else:
            rows = self._rows()
            for index, item in enumerate(self.items):
                if item["state"] == state and f"cr-item-{index}" in rows:
                    rows[f"cr-item-{index}"].display = state not in self.collapsed
        for empty in self.query(f"#cr-empty-{state}"):
            empty.display = state not in self.collapsed
        if state == "done" and state not in self.collapsed:
            self._start_titles()

    async def _mount_rows(self, state: str, header: Button) -> None:
        """Mount the rows of a group that was folded when the list was made, right after its header."""
        rows = []
        for index, item in enumerate(self.items):
            if item["state"] == state:
                rows.append(Button(self._row_label(item), id=f"cr-item-{index}", classes="list-item"))
        self._unmounted.discard(state)
        await self.query_one("#cr-items", VerticalScroll).mount(*rows, after=header)
        self._mark_selected()

    async def _painted(self) -> None:
        """Return once the screen has been refreshed with what was mounted, so that it is drawn before the next
        long layout starts."""
        done = asyncio.Event()
        self.call_after_refresh(done.set)
        try:
            await asyncio.wait_for(done.wait(), 1)
        except asyncio.TimeoutError:
            pass
        await asyncio.sleep(0.02)

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
        head = cr_head(source) if source is not None else None
        if head is not None:
            # A long CR is a few hundred widgets and laying them out takes seconds on a loaded host (about 2 s
            # for 180 lines, measured): the first screen is shown at once and the whole document replaces it.
            await detail.mount(Markdown(head, open_links=False))
            await self._painted()
            if self._closing or generation != self._load_generation:
                return
            await detail.remove_children()
        await detail.mount(Markdown(source, open_links=False) if source is not None else Static(message))
        detail.scroll_home(animate=False)

    async def _pressed(self, button_id: str) -> None:
        if button_id.startswith("cr-item-"):
            index = int(button_id.removeprefix("cr-item-"))
            self.selected_id = self.items[index]["id"]
            self._mark_selected()
            await self._show_cr()
            self.remove_class("list-open")
        elif button_id.startswith("cr-group-"):
            await self._fold(button_id.removeprefix("cr-group-"))


READING_CRON = "cron 작업을 읽는 중…"
LAST_RUN_FAILED = ("실패", "#ff8f8f")


def _local_minute(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M")


def cron_detail(job: dict) -> Content:
    """The selected job as plain text (a description or a result may hold `[`, which is not markup here): ID,
    description, schedule, next run with the time left, the last run, and the whole command."""
    following = job.get("next_run")
    if following:
        left = f" ({job['remaining']} 뒤)" if job.get("remaining") else ""
        next_text = f"{_local_minute(dt.datetime.fromisoformat(following))}{left}"
    else:
        next_text = "없음"
    last = job.get("last_run")
    parts: list = [(job["id"], "bold"), "\n", job["description"], "\n\n",
                   ("일정      ", "bold"), job["schedule"], "\n",
                   ("다음 실행  ", "bold"), next_text, "\n",
                   ("마지막 실행 ", "bold")]
    if last:
        at = dt.datetime.fromisoformat(str(last["at"]).replace("Z", "+00:00")).astimezone()
        parts += [_local_minute(at), " ", ("성공", "#9be28f") if last["ok"] else LAST_RUN_FAILED]
        if last.get("result"):
            parts += ["\n", ("결과      ", "bold"), str(last["result"])]
        if last.get("code"):
            parts += ["\n", ("오류 코드  ", "bold"), str(last["code"])]
    else:
        parts.append("아직 없음")
    parts += ["\n\n", ("명령", "bold"), "\n", job["command"]]
    return Content.assemble(*parts)


class CronPopupApp(_ListWindow):
    """A read-only list of a project's cron jobs (BOARD-027): each job's schedule, next and last run, and command.
    Jobs are added and removed with `agent-session cron add|rm`. ◀▶ moves between every registered project; the
    jobs are read when the window opens and when it changes project."""

    reading_list = READING_CRON

    def _on_request(self, request: dict) -> dict:
        project = request.get("project")
        if (request.get("kind") != "cron" or not isinstance(project, str)
                or not isinstance(request.get("client", ""), str)):
            return window_link.reply(False, "invalid", "cron 창이 받을 수 없는 요청입니다.")
        if self._closing:
            return window_link.reply(False, "closing", "cron 창이 닫히는 중입니다.")
        self.project_id = project
        self.selected_id = None
        self.query_one("#cr-project", Static).update(project)
        self._queue(self._reload())
        return window_link.reply()

    async def refresh_items(self) -> None:
        project_id = self.project_id
        try:
            data = await asyncio.to_thread(model.cron_view, self.config, project_id)
            if not self._closing and project_id == self.project_id:
                await self.apply_view(data)
        except Exception as error:
            if not self._closing:
                await self._show_message(f"cron을 읽을 수 없습니다: {error}")

    async def apply_view(self, data: dict) -> None:
        self.order = data.get("order") or []
        self.query_one("#cr-project", Static).update(self.project_id)
        self._targets = _set_nav(self.query_one("#cr-prev", Button), self.query_one("#cr-next", Button),
                                 self.order, self.project_id, set(self.order))
        listing = self.query_one("#cr-items", VerticalScroll)
        await listing.remove_children()
        self.items = data.get("jobs") or []
        error = data.get("error")
        title = "cron을 읽을 수 없습니다" if error else f"cron {len(self.items)}개"
        self.query_one("#cr-title", Static).update(title)
        if error:
            await self._show_message(f"cron을 읽을 수 없습니다: {error}")
            return
        if not self.items:
            await self._show_message("작업 없음")
            return
        await listing.mount(*[Button(self._row_label(item), id=f"cr-item-{index}", classes="list-item")
                              for index, item in enumerate(self.items)])
        if not any(item["id"] == self.selected_id for item in self.items):
            self.selected_id = self.items[0]["id"]
        self._mark_selected()
        await self._show_job()
        listing.scroll_home(animate=False)

    def _row_label(self, item: dict) -> Content:
        last = item.get("last_run")
        failed = LAST_RUN_FAILED if last and not last.get("ok") else None
        return _item_label(item["id"] == self.selected_id, item["id"], failed, item["description"])

    def _mark_selected(self) -> None:
        for index, item in enumerate(self.items):
            for button in self.query(f"#cr-item-{index}"):
                button.label = self._row_label(item)
                button.set_class(item["id"] == self.selected_id, "selected")

    async def _show_job(self) -> None:
        item = next((row for row in self.items if row["id"] == self.selected_id), None)
        if item is None:
            return
        self._load_generation += 1
        detail = self.query_one("#cr-detail", VerticalScroll)
        await detail.remove_children()
        await detail.mount(Static(cron_detail(item)))
        detail.scroll_home(animate=False)

    async def _pressed(self, button_id: str) -> None:
        if button_id.startswith("cr-item-"):
            self.selected_id = self.items[int(button_id.removeprefix("cr-item-"))]["id"]
            self._mark_selected()
            await self._show_job()
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
        link: str | None = None,
        mark_link: LinkMarker | None = None,
    ):
        super().__init__()
        self.config = config
        self.link = link                                # the socket on which a click tells this window what to show next
        self.mark_link = mark_link
        self._server: asyncio.AbstractServer | None = None
        self.project_id = project_id
        self.decide_id = decide_id
        self.snapshot_reader = snapshot_reader or self._read_project
        self.navigation_reader = navigation_reader or model.decision_snapshot
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
        return model.popup_snapshot(config, self.project_id, only=model.ONLY_DECISIONS)

    def compose(self) -> ComposeResult:
        with Horizontal(classes="nav-row"):
            yield Button("◀", id="popup-prev", disabled=True)
            yield Static(self.project_id, id="popup-project")
            yield Button("▶", id="popup-next", disabled=True)
        yield Static(READING_DECISIONS, id="popup-heading")
        with Horizontal(id="popup-main"):
            yield VerticalScroll(id="decision-list")
            with VerticalScroll(id="decision-detail"):
                yield Static(READING)
        yield Static("답변", id="answer-label")
        yield AnswerArea(id="answer", placeholder="결정 내용을 읽고 답변을 입력하세요.")
        with Horizontal(id="popup-actions"):
            yield Button("목록", id="show-list")
            yield Button("전송", id="send")
            yield Button("닫기", id="close")
        yield Static("", id="popup-message")

    def on_mount(self) -> None:
        if self.link:
            self._queue(self._listen())
        if self.load:
            self._queue(self.refresh_decisions())

    def on_unmount(self) -> None:
        self._closing = True
        for task in self._tasks:
            task.cancel()
        window_link.stop(self._server, self.link)

    async def _listen(self) -> None:
        """Take what a click asks this window to show (BOARD-025), then say so: a click that finds no
        listener, or one that fails, starts the window again."""
        try:
            self._server = await window_link.serve(self.link, self._on_request)
        except OSError:
            pass
        if self.mark_link is not None:
            await asyncio.to_thread(self.mark_link, self.link)

    def _on_request(self, request: dict) -> dict:
        """Show another project's decisions (`decision` None: its first), as ◀▶ does. An unsent answer stays with its decision."""
        project, decision = request.get("project"), request.get("decision")
        if (request.get("kind") != "decision" or not isinstance(project, str)
                or not (decision is None or isinstance(decision, str)) or not isinstance(request.get("client", ""), str)):
            return window_link.reply(False, "invalid", "결정 창이 받을 수 없는 요청입니다.")
        if self._closing:
            return window_link.reply(False, "closing", "결정 창이 닫히는 중입니다.")
        if self._sending:
            return window_link.reply(False, "busy", "답변을 전송하는 중입니다. 끝난 뒤 다시 여십시오.")
        if isinstance(self.screen, CSVScreen):
            self.pop_screen()
        self._keep_draft()
        self.project_id = project
        self.decide_id = decision
        self.decisions = {}
        self._switched = True
        self.query_one("#popup-project", Static).update(project)
        self._queue(self._reload())
        return window_link.reply()

    async def _reload(self) -> None:
        """Show that the decisions are being read, then read them."""
        self.query_one("#popup-heading", Static).update(READING_DECISIONS)
        detail = self.query_one("#decision-detail", VerticalScroll)
        await detail.remove_children()
        await detail.mount(Static(READING))
        await self.refresh_decisions()

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
        """The other projects are read after the window is up: reading every project is slow on a cold start.
        Until it is done ◀▶ are off, and the window says why."""
        message = self.query_one("#popup-message", Static)
        message.update(READING_PROJECTS)
        try:
            data = await asyncio.to_thread(self.navigation_reader, self.config)
            if not self._closing:
                self._learn_projects({"projects": data.get("projects", []), "order": self.order})
                if str(message.content) == READING_PROJECTS:
                    message.update("")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            message.update(f"project 이동 목록을 읽을 수 없습니다: {error}")

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


def run_cr_popup(config: str | None, project_id: str, state: str, mark_link: LinkMarker | None = None) -> int:
    CRPopupApp(config, project_id, state, link=os.environ.get(window_link.SOCKET_ENV), mark_link=mark_link).run()
    return 0


def run_cron_popup(config: str | None, project_id: str, mark_link: LinkMarker | None = None) -> int:
    CronPopupApp(config, project_id, link=os.environ.get(window_link.SOCKET_ENV), mark_link=mark_link).run()
    return 0


def run_popup(config: str | None, project_id: str, decide_id: str | None = None,
              mark_link: LinkMarker | None = None) -> int:
    PopupApp(config, project_id, decide_id, link=os.environ.get(window_link.SOCKET_ENV), mark_link=mark_link).run()
    return 0
