"""User interactions and displayed project facts in the terminal Board."""
import asyncio
import datetime as dt
import html
import json
import os
import re
import signal
import threading

import pytest

from board_testing import Board, Frames, WORKER_IDS, click_socket, leader, session, wait_until
from project_board import model
from project_board.tui import CRPopupApp, CSVScreen, PopupApp, SidebarApp, _seat_text, format_elapsed
from textual.widgets import Button, DataTable, Markdown, Static, TextArea


# 2h 30m after the worker sessions (08:00) and 1d 01h 30m after the Leader session (Nov 4 09:00).
NOW = dt.datetime(2026, 11, 5, 10, 30, tzinfo=dt.timezone.utc)


def _rendered_left_column(svg: str, label: str) -> int:
    """Read the visible cell offset from Textual's exported screen."""
    for match in re.finditer(r'<text\b[^>]*\bx="([^"]+)"[^>]*>(.*?)</text>', svg, re.S):
        displayed = html.unescape(match.group(2)).replace("\xa0", " ")
        if label in displayed:
            assert float(match.group(1)) == 0
            return displayed.index(label)
    raise AssertionError(f"{label!r} is absent from the rendered screen")


def _make_sidebar_board(tmp_path):
    board = Board(tmp_path)
    falcon = board.project("Falcon2", seats=3)
    board.cr(falcon, "open", "CPU-001")
    board.cr(falcon, "open", "CPU-002")
    board.cr(falcon, "todo", "CPU-003")
    board.cr(falcon, "in-progress", "CPU-012")
    board.decide(falcon, "open", "D-20261107-01")
    board.decide(falcon, "open", "D-20261107-02")
    board.state(falcon, {
        "leader": leader(reviewing="CPU-012"),
        "0": {"job_id": "CPU-012", "git_hash": None, "session": session(0)},
        "1": {"job_id": None, "git_hash": None, "session": None},
        "2": {"job_id": None, "git_hash": None, "session": None},
    })
    other = board.project("ProjectB", seats=2)
    board.cr(other, "todo", "GPU-001")
    board.cr(other, "todo", "GPU-002")
    board.cr(other, "todo", "GPU-003")
    board.decide(other, "open", "D-20261107-03")
    board.state(other, {
        "leader": None,
        "0": {"job_id": None, "git_hash": None, "session": None},
        "1": {"job_id": None, "git_hash": None, "session": None},
    })
    return board


def test_sidebar_shows_every_project_and_mouse_opens_the_right_project(tmp_path):
    board = _make_sidebar_board(tmp_path)
    projects = []
    decisions = []
    crs = []
    seats = []
    app = SidebarApp(
        str(board.config), poll=False,
        on_project=lambda project: projects.append(project),
        on_decision=lambda project, item: decisions.append((project, item)),
        on_cr=lambda project, state: crs.append((project, state)),
        on_seat=lambda project, seat: seats.append((project, seat)),
    )

    async def check():
        async with app.run_test(size=(25, 25)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config, now=NOW))
            await pilot.pause()
            assert [str(item.label) for item in app.query(".project-name")] == ["Falcon2", "ProjectB"]
            svg = app.export_screenshot()
            assert _rendered_left_column(svg, "Falcon2") == 0
            for label in ("O:2", "D:2"):
                assert _rendered_left_column(svg, label) <= 1
            assert app.query_one("#project-0-D", Button).region.y < app.query_one("#project-0-O", Button).region.y
            assert app.query_one("#project-0-seats", Button).region.right <= 25
            assert not app.query("#project-0-seat-0")
            assert str(app.query_one("#project-0-O", Button).label) == "O:2"
            assert str(app.query_one("#project-0-T", Button).label) == "T:1"
            assert str(app.query_one("#project-0-I", Button).label) == "I:1"
            assert str(app.query_one("#project-0-D", Button).label) == "D:2"
            await pilot.click("#project-0-seats")
            await pilot.pause()
            assert str(app.query_one("#project-0-seats", Button).label) == "▾"
            assert app.query_one("#project-0-seats", Button).tooltip == "좌석 접기"
            assert not app.query("#project-1-seat-0")
            assert str(app.query_one("#project-0-seat-0", Button).label) == "R 0 CPU-012 2h 30m"
            empty = app.query_one("#project-0-seat-1", Button)
            assert str(empty.label) == "  1 -" and empty.disabled
            assert empty.tooltip == "1 -"
            await pilot.click("#project-1-name")
            await pilot.click("#project-1-D")
            await pilot.click("#project-0-seat-0")
            await pilot.pause()
            assert projects == ["ProjectB"]
            assert decisions == [("ProjectB", None)]
            assert seats == [("Falcon2", 0)]
            await pilot.click("#project-0-O")
            await pilot.pause()
            assert crs == [("Falcon2", "open")]
            assert [str(item.label) for item in app.query(".project-name")] == ["Falcon2", "ProjectB"]

    asyncio.run(check())


@pytest.mark.parametrize("seconds, text", [
    (0, "0m"), (59, "0m"), (60, "1m"), (59 * 60, "59m"), (59 * 60 + 59, "59m"),
    (3600, "1h 00m"), (3 * 3600 + 5 * 60, "3h 05m"), (23 * 3600 + 59 * 60, "23h 59m"),
    (24 * 3600, "1d 00h 00m"), (2 * 86400 + 3600, "2d 01h 00m"), (12 * 86400 + 5 * 3600 + 9 * 60, "12d 05h 09m"),
    (-30, "0m"), (None, None),
])
def test_elapsed_time_drops_zero_leading_units(seconds, text):
    assert format_elapsed(seconds) == text


def test_seat_row_ends_with_the_session_time_only_when_known():
    assert _seat_text({"index": 0, "job_id": "TOOL-001", "elapsed": 11 * 3600 + 120}) == "  0 TOOL-001 11h 02m"
    assert _seat_text({"index": 0, "job_id": "TOOL-001", "elapsed": None}) == "  0 TOOL-001"
    assert _seat_text({"index": 1, "job_id": None, "elapsed": None}) == "  1 -"


def _leader_rows(app):
    return [str(row.render()) for row in app.query(".leader")]


def test_sidebar_shows_leader_and_worker_time_and_redraws_only_when_the_minute_changes(tmp_path):
    board = _make_sidebar_board(tmp_path)
    app = SidebarApp(str(board.config), poll=False)

    async def check():
        async with app.run_test(size=(40, 25)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config, now=NOW))
            await pilot.pause()
            await pilot.click("#project-0-seats")
            await wait_until(pilot, lambda: app.query(".leader"))
            assert _leader_rows(app) == ["  Leader 1d 01h 30m"]
            assert str(app.query_one("#project-0-seat-0", Button).label) == "R 0 CPU-012 2h 30m"
            assert str(app.query_one("#project-0-seat-1", Button).label) == "  1 -"
            svg = app.export_screenshot()
            assert _rendered_left_column(svg, "Leader 1d 01h 30m") <= 2
            assert _rendered_left_column(svg, "CPU-012 2h 30m") <= 6
            worker = app.query_one("#project-0-seat-0", Button)
            # Another poll within the same minute keeps the same widgets (no redraw, no flicker).
            await app.apply_snapshot(model.snapshot(board.config, now=NOW + dt.timedelta(seconds=40)))
            await pilot.pause()
            assert app.query_one("#project-0-seat-0", Button) is worker
            # The next minute redraws both rows.
            await app.apply_snapshot(model.snapshot(board.config, now=NOW + dt.timedelta(seconds=60)))
            await pilot.pause()
            assert _leader_rows(app) == ["  Leader 1d 01h 31m"]
            assert str(app.query_one("#project-0-seat-0", Button).label) == "R 0 CPU-012 2h 31m"

    asyncio.run(check())


def test_sidebar_shows_no_time_for_old_state_without_connected_at_or_without_a_session(tmp_path):
    board = Board(tmp_path)
    project = board.project("Falcon2", seats=2)
    board.state(project, {
        "leader": leader(connected_at=None),
        "0": {"job_id": "CPU-012", "git_hash": None, "session": session(0, connected_at=None)},
        "1": {"job_id": "CPU-013", "git_hash": None, "session": None},
    })
    app = SidebarApp(str(board.config), poll=False)

    async def check():
        async with app.run_test(size=(40, 25)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config, now=NOW))
            await pilot.pause()
            await pilot.click("#project-0-seats")
            await wait_until(pilot, lambda: app.query("#project-0-seat-0"))
            assert _leader_rows(app) == []
            assert str(app.query_one("#project-0-seat-0", Button).label) == "  0 CPU-012"
            assert str(app.query_one("#project-0-seat-1", Button).label) == "대기 1 CPU-013"

    asyncio.run(check())


def _marked(app):
    """Which rows of the sidebar carry the current-window highlight."""
    rows = [str(button.label) for button in app.query(".project-active")]
    rows += [str(widget.id or widget.renderable) for widget in app.query(".slot-active")]
    return rows


def _context_app(board, context):
    value = {"active": context}
    reads = []

    def reader():
        reads.append(1)
        if isinstance(value["active"], Exception):
            raise value["active"]
        return value["active"]

    app = SidebarApp(str(board.config), poll=False, context_reader=reader)
    return app, value, reads


def test_sidebar_highlights_the_project_and_slot_of_the_managed_window_being_shown(tmp_path):
    board = _make_sidebar_board(tmp_path)
    app, value, reads = _context_app(board, {"project_id": "Falcon2", "slot": "leader"})

    async def check():
        async with app.run_test(size=(40, 25)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config, now=NOW))
            await pilot.pause()
            assert _marked(app) == []                       # nothing read yet: nothing marked
            await app.refresh_context()
            await pilot.pause()
            # Folded: the project name and the fold button (no slot row to mark), never ProjectB.
            assert str(app.query_one("#project-0-name", Button).label) == "▶ Falcon2"
            assert str(app.query_one("#project-1-name", Button).label) == "ProjectB"
            assert _marked(app) == ["▶ Falcon2", "project-0-seats"]
            assert "현재 창: Leader" in str(app.query_one("#project-0-seats", Button).tooltip)
            await pilot.click("#project-0-seats")
            await wait_until(pilot, lambda: app.query(".leader"))
            # Expanded: the Leader row carries the slot mark and the fold button no longer does.
            assert [w.has_class("slot-active") for w in app.query(".leader")] == [True]
            assert not app.query_one("#project-0-seats", Button).has_class("slot-active")
            assert not app.query_one("#project-0-seat-0", Button).has_class("slot-active")
            # A seat window: only that seat's row is marked, and the Leader row is not.
            value["active"] = {"project_id": "Falcon2", "slot": "seat-0"}
            await app.refresh_context()
            await pilot.pause()
            assert [w.has_class("slot-active") for w in app.query(".leader")] == [False]
            assert app.query_one("#project-0-seat-0", Button).has_class("slot-active")
            assert not app.query_one("#project-0-seat-1", Button).has_class("slot-active")
            svg = app.export_screenshot()
            assert "▶ Falcon2" in html.unescape(svg).replace("\xa0", " ")
            # The other project's seat number does not match this project.
            value["active"] = {"project_id": "ProjectB", "slot": "seat-0"}
            await app.refresh_context()
            await pilot.pause()
            assert str(app.query_one("#project-0-name", Button).label) == "Falcon2"
            assert str(app.query_one("#project-1-name", Button).label) == "▶ ProjectB"
            assert not app.query_one("#project-0-seat-0", Button).has_class("slot-active")
            # An unmanaged window, an unregistered project and a slot without a row.
            value["active"] = None
            await app.refresh_context()
            await pilot.pause()
            assert _marked(app) == []
            value["active"] = {"project_id": "NoSuchProject", "slot": "leader"}
            await app.refresh_context()
            await pilot.pause()
            assert _marked(app) == []
            value["active"] = {"project_id": "Falcon2", "slot": "seat-7"}
            await app.refresh_context()
            await pilot.pause()
            assert _marked(app) == ["▶ Falcon2"]
            value["active"] = {"project_id": "Falcon2", "slot": None}
            await app.refresh_context()
            await pilot.pause()
            assert _marked(app) == ["▶ Falcon2"]

    asyncio.run(check())


def test_the_highlight_is_kept_when_the_read_fails_and_not_read_while_hidden(tmp_path):
    board = _make_sidebar_board(tmp_path)
    app, value, reads = _context_app(board, {"project_id": "Falcon2", "slot": None})

    async def check():
        async with app.run_test(size=(40, 25)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config, now=NOW))
            await app.refresh_context()
            await pilot.pause()
            assert _marked(app) == ["▶ Falcon2"]
            value["active"] = RuntimeError("tmux is busy")
            await app.refresh_context()
            await pilot.pause()
            assert _marked(app) == ["▶ Falcon2"]            # unknown is not "no window"
            count = len(reads)
            value["active"] = None
            app.set_visible(False)
            await app.refresh_context()
            assert len(reads) == count                      # hidden: no read
            app.set_visible(True)                           # shown again: read at once, mark follows
            await wait_until(pilot, lambda: _marked(app) == [])
            assert len(reads) == count + 1

    asyncio.run(check())


def test_the_highlight_is_redrawn_only_when_it_changes(tmp_path):
    board = _make_sidebar_board(tmp_path)
    app, value, reads = _context_app(board, {"project_id": "Falcon2", "slot": "leader"})

    async def check():
        async with app.run_test(size=(40, 25)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config, now=NOW))
            await app.refresh_context()
            await pilot.pause()
            name = app.query_one("#project-0-name", Button)
            value["active"] = {"project_id": "Falcon2", "slot": "leader"}   # equal value, new object
            await app.refresh_context()
            await pilot.pause()
            assert app.query_one("#project-0-name", Button) is name

    asyncio.run(check())


def test_empty_seat_shows_index_and_dash():
    assert _seat_text({"index": 1, "job_id": None}) == "  1 -"


def test_a_seat_waiting_for_release_is_marked():
    assert _seat_text({"index": 0, "job_id": "TOOL-001", "status": "release_pending"}) == "반납대기 0 TOOL-001"


def test_remote_seat_names_its_host_before_the_job():
    assert _seat_text({"index": 2, "job_id": "TOOL-001", "host": "macbook-worker"}) == (
        "  2@macbook-worker TOOL-001")


def test_remote_seat_keeps_its_host_and_click_target_when_execution_is_unknown(tmp_path):
    board = _make_sidebar_board(tmp_path)
    calls = []
    app = SidebarApp(str(board.config), poll=False,
                     on_seat=lambda project, seat: calls.append((project, seat)))

    async def check():
        async with app.run_test(size=(50, 25)) as pilot:
            snapshot = model.snapshot(board.config)
            seat = snapshot["projects"][0]["seats"][0]
            seat.update(host="macbook-worker", path="/Users/swain/Agent/remote-seat")
            await app.apply_snapshot(snapshot)
            await pilot.pause()
            await pilot.click("#project-0-seats")
            await pilot.pause()
            await app.apply_liveness({
                "Falcon2": {"0": {"session_id": seat["session_id"], "state": "unknown"}}
            })
            await pilot.pause()
            button = app.query_one("#project-0-seat-0", Button)
            assert "0@macbook-worker" in str(button.label)
            assert "macbook-worker" in str(button.tooltip)
            assert "/Users/swain/Agent/remote-seat" in str(button.tooltip)
            assert "실행 확인 불가" in str(button.tooltip)
            assert button.has_class("seat-unknown")
            assert not button.disabled
            await pilot.click("#project-0-seat-0")
            await pilot.pause()
            assert calls == [("Falcon2", 0)]

            seat["host"] = "replacement-worker"
            await app.apply_snapshot(snapshot)
            await pilot.pause()
            assert "replacement-worker" in str(app.query_one("#project-0-seat-0", Button).label)

    asyncio.run(check())


def test_seat_fold_keeps_each_project_state_through_refresh_and_keyboard(tmp_path):
    board = _make_sidebar_board(tmp_path)
    app = SidebarApp(str(board.config), poll=False)

    async def check():
        async with app.run_test(size=(25, 18)) as pilot:
            snapshot = model.snapshot(board.config)
            await app.apply_snapshot(snapshot)
            await pilot.pause()
            assert not app.query(".seat")
            await pilot.click("#project-0-seats")
            await pilot.pause()
            assert len(app.query("#project-0-seat-0")) == 1
            assert not app.query("#project-1-seat-0")
            await app.apply_snapshot(model.snapshot(board.config))
            await app.apply_liveness({
                "Falcon2": {"0": {"session_id": snapshot["projects"][0]["seats"][0]["session_id"],
                                   "state": "stopped"}}
            })
            await pilot.pause()
            assert app.query_one("#project-0-seat-0", Button).has_class("seat-stopped")
            assert not app.query("#project-1-seat-0")
            app.query_one("#project-0-seats", Button).focus()
            await pilot.press("enter")
            await pilot.pause()
            assert not app.query("#project-0-seat-0")
            assert str(app.query_one("#project-0-seats", Button).label) == "▸"
            assert app.query_one("#project-0-seats", Button).tooltip == "좌석 펼치기"

    asyncio.run(check())


def test_seat_fold_survives_sidebar_recreation_and_syncs_other_pane(tmp_path):
    board = _make_sidebar_board(tmp_path)
    expanded = set()

    def read_expanded():
        return set(expanded)

    def toggle_expanded(project_id):
        if project_id in expanded:
            expanded.remove(project_id)
        else:
            expanded.add(project_id)
        return set(expanded)

    def app():
        sidebar = SidebarApp(str(board.config), poll=False)
        sidebar.expanded_reader = read_expanded
        sidebar.expanded_toggler = toggle_expanded
        return sidebar

    async def check():
        first = app()
        async with first.run_test(size=(25, 18)) as pilot:
            await first.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            await pilot.click("#project-0-seats")
            await pilot.pause(0.1)
            assert first.query("#project-0-seat-0")
            assert not first.query("#project-1-seat-0")

            second = app()
            async with second.run_test(size=(25, 18)) as other_pilot:
                await second.apply_snapshot(model.snapshot(board.config))
                await other_pilot.pause()
                assert second.query("#project-0-seat-0")
                assert not second.query("#project-1-seat-0")
                await other_pilot.click("#project-1-seats")
                await other_pilot.pause(0.1)
                await first.apply_snapshot(model.snapshot(board.config))
                assert first.query("#project-0-seat-0")
                assert first.query("#project-1-seat-0")

        recreated = app()
        async with recreated.run_test(size=(25, 18)):
            await recreated.apply_snapshot(model.snapshot(board.config))
            assert recreated.query("#project-0-seat-0")
            assert recreated.query("#project-1-seat-0")

    asyncio.run(check())


def test_many_projects_scroll_and_ipc_fold_the_clicked_project(tmp_path):
    board = Board(tmp_path)
    for number in range(12):
        board.project(f"Project{number:02d}", seats=1)
    app = SidebarApp(str(board.config), poll=False)

    async def check():
        async with app.run_test(size=(25, 12)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause(0.1)
            scroll = app.query_one("#projects")
            assert scroll.max_scroll_y > 0
            assert len(app.query(".project-name")) == 12
            assert len(app.query("#project-11-seats")) == 1
            target = app.query_one("#project-11-seats", Button)
            scroll.scroll_to(y=scroll.max_scroll_y, animate=False)
            await pilot.pause()
            assert 0 <= target.region.y < 12
            result = app.dispatch_client_click("client-b", target.region.x + 1, target.region.y)
            assert result["ok"], (result, target.region, scroll.scroll_y)
            await pilot.pause()
            assert len(app.query("#project-11-seat-0")) == 1
            assert not app.query("#project-10-seat-0")
            await pilot.click("#project-11-seats")
            await pilot.pause()
            assert not app.query("#project-11-seat-0")

    asyncio.run(check())


def test_long_project_name_has_tooltip_and_horizontal_scroll(tmp_path):
    board = Board(tmp_path)
    project_id = "VeryLongProjectNameThatExceedsTwentyFiveColumns"
    board.project(project_id, seats=1)
    short_base = board.project("Short", seats=1)
    long_job_id = "JOB-VERY-LONG-IDENTIFIER-001"
    board.cr(short_base, "in-progress", long_job_id)
    board.state(short_base, {
        "leader": None,
        "0": {"job_id": long_job_id, "git_hash": None, "session": session(0)},
    })
    app = SidebarApp(str(board.config), poll=False)

    async def check():
        async with app.run_test(size=(25, 12)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            name = app.query_one("#project-0-name", Button)
            assert name.tooltip == project_id
            scroll = app.query_one("#projects")
            assert scroll.max_scroll_x > 0
            await pilot.click("#project-1-seats")
            await pilot.pause()
            seat = app.query_one("#project-1-seat-0", Button)
            assert long_job_id in str(seat.tooltip)
            assert seat.region.width > 25
            scroll.scroll_to(x=scroll.max_scroll_x, animate=False)
            await pilot.pause()
            assert scroll.scroll_x == scroll.max_scroll_x

    asyncio.run(check())


def test_cr_list_opens_in_its_own_popup(tmp_path):
    board = _make_sidebar_board(tmp_path)
    app = CRPopupApp(str(board.config), "Falcon2", "open", load=False)

    async def check():
        async with app.run_test(size=(70, 20)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            assert [str(item.label) for item in app.query(".list-item")] == [
                "▶ CPU-001 CR title", "  CPU-002 CR title",
            ]
            assert any("The **contract** of CPU-001." in widget.source for widget in app.query(Markdown))
            await pilot.click("#cr-close")

    asyncio.run(check())


def test_cr_popup_opens_selected_cr_markdown(tmp_path):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    first = board.cr(base, "open", "CPU-001")
    second = board.cr(base, "open", "CPU-002")
    app = CRPopupApp(str(board.config), "Falcon2", "open", load=False)

    async def check():
        async with app.run_test(size=(90, 24)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.click(".list-item")
            await pilot.pause()
            assert any(first.read_text(encoding="utf-8") == widget.source for widget in app.query(Markdown))
            await pilot.click("#cr-item-1")
            await wait_until(pilot, lambda: any(second.read_text(encoding="utf-8") == widget.source
                                                for widget in app.query(Markdown)))
            assert any(second.read_text(encoding="utf-8") == widget.source for widget in app.query(Markdown))

    asyncio.run(check())


@pytest.mark.parametrize("state", ("open", "todo", "in-progress"))
def test_cr_popup_keyboard_selection_and_narrow_list_return(tmp_path, state):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    board.cr(base, state, "CPU-001")
    second = board.cr(base, state, "CPU-002")
    app = CRPopupApp(str(board.config), "Falcon2", state, load=False)

    async def check():
        async with app.run_test(size=(55, 20)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            assert app.has_class("narrow")
            assert not app.query_one("#cr-items").display
            assert app.query_one("#cr-detail").display
            await pilot.click("#cr-show-list")
            assert app.query_one("#cr-items").display
            assert not app.query_one("#cr-detail").display
            app.query_one("#cr-item-1", Button).focus()
            await pilot.press("enter")
            await pilot.pause()
            assert app.query_one("#cr-detail").display
            assert not app.query_one("#cr-items").display
            assert [widget.source for widget in app.query(Markdown)] == [second.read_text(encoding="utf-8")]
            await pilot.click("#cr-show-list")
            assert app.query_one("#cr-items").display

    asyncio.run(check())


@pytest.mark.parametrize("change", ("move", "delete"))
def test_cr_popup_keeps_open_when_selected_file_disappears(tmp_path, change):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    board.cr(base, "open", "CPU-001")
    second = board.cr(base, "open", "CPU-002")
    app = CRPopupApp(str(board.config), "Falcon2", "open", load=False)

    async def check():
        async with app.run_test(size=(90, 20)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            if change == "move":
                second.rename(base / "agent/cr/todo" / second.name)
            else:
                second.unlink()
            await pilot.click("#cr-item-1")
            await pilot.pause()
            assert "CPU-002 파일을 읽을 수 없습니다" in str(app.query_one("#cr-detail > Static").content)
            await pilot.click("#cr-item-0")
            await pilot.pause()
            assert "The **contract** of CPU-001." in app.query_one("#cr-detail Markdown", Markdown).source

    asyncio.run(check())


def test_cr_popup_shows_read_error_and_empty_list(tmp_path, monkeypatch):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    board.cr(base, "open", "CPU-001")
    app = CRPopupApp(str(board.config), "Falcon2", "open", load=False)

    async def check():
        async with app.run_test(size=(90, 20)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            with monkeypatch.context() as patch:
                patch.setattr(model, "read_cr_markdown", lambda *_: (_ for _ in ()).throw(PermissionError("denied")))
                await pilot.click("#cr-item-0")
                await pilot.pause()
                assert "denied" in str(app.query_one("#cr-detail > Static").content)
            await app.apply_snapshot({"projects": [{"id": "Falcon2", "crs": {"open": []}}]})
            assert "CR이 없습니다." in str(app.query_one("#cr-detail > Static").content)
            assert app.query_one("#cr-close", Button)

    asyncio.run(check())


def test_cr_markdown_reader_rejects_unlisted_paths(tmp_path):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    listed = board.cr(base, "open", "CPU-001")
    outside = tmp_path / "CPU-001-secret.md"
    outside.write_text("private", encoding="utf-8")
    project = model.snapshot(board.config)["projects"][0]
    item = project["crs"]["open"][0]
    with pytest.raises(ValueError, match="목록 밖"):
        model.read_cr_markdown(project, {**item, "path": str(outside)}, "open")
    with pytest.raises(ValueError, match="유효하지"):
        model.read_cr_markdown(project, item, "todo")
    listed.unlink()
    listed.symlink_to(outside)
    with pytest.raises(ValueError, match="목록 밖"):
        model.read_cr_markdown(project, item, "open")


def test_ipc_click_routes_the_originating_client(tmp_path, request):
    board = _make_sidebar_board(tmp_path)
    calls = []
    socket = click_socket(request)
    app = SidebarApp(
        str(board.config), poll=False, click_socket=socket,
        on_project=lambda project, client=None: calls.append((project, client)),
        on_decision=lambda project, item, client=None: calls.append((project, item, client)),
    )

    async def check():
        async with app.run_test(size=(50, 25)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            button = app.query_one("#project-1-name", Button)
            reader, writer = await asyncio.open_unix_connection(socket)
            writer.write((json.dumps({
                "client": "client-a", "x": button.region.x + 1, "y": button.region.y,
            }) + "\n").encode())
            await writer.drain()
            result = json.loads(await reader.readline())
            writer.close()
            await writer.wait_closed()
            await pilot.pause()
            assert result["ok"] and calls == [("ProjectB", "client-a")]
        assert not os.path.exists(socket)

    asyncio.run(check())


def test_empty_cr_and_decision_clicks_do_nothing_for_mouse_and_ipc(tmp_path, request):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=1)
    calls = []
    notifications = []
    socket = click_socket(request)
    app = SidebarApp(
        str(board.config), poll=False, click_socket=socket,
        on_cr=lambda project, state, client=None: calls.append((project, state, client)),
        on_decision=lambda project, item, client=None: calls.append((project, item, client)),
        on_seat=lambda project, seat, client=None: calls.append((project, seat, client)),
    )
    app.notify = lambda message, **kwargs: notifications.append((message, kwargs))

    async def send_click(button):
        reader, writer = await asyncio.open_unix_connection(socket)
        writer.write((json.dumps({
            "client": "client-a", "x": button.region.x + 1, "y": button.region.y,
        }) + "\n").encode())
        await writer.drain()
        result = json.loads(await reader.readline())
        writer.close()
        await writer.wait_closed()
        return result

    async def check():
        async with app.run_test(size=(50, 20)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            await pilot.click("#project-0-seats")
            await pilot.pause()
            for selector in ("#project-0-O", "#project-0-T", "#project-0-I", "#project-0-D",
                             "#project-0-seat-0"):
                button = app.query_one(selector, Button)
                assert button.disabled
                await pilot.click(selector)
                result = await send_click(button)
                assert result["ok"] and result["error"] is None
            await pilot.pause()
            assert calls == [] and notifications == []

            board.cr(base, "open", "CPU-001")
            board.decide(base, "open", "D-20261107-01")
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            await pilot.click("#project-0-O")
            result = await send_click(app.query_one("#project-0-D", Button))
            await pilot.pause()
            assert result["ok"] and calls == [
                ("Falcon2", "open", None), ("Falcon2", None, "client-a"),
            ]
            assert notifications == []
            assert app.dispatch_client_click("client-a", 1000, 1000)["error"]["code"] == "no_widget"

    asyncio.run(check())


def test_pending_seats_wait_without_clicking_and_running_seat_still_opens(tmp_path, request):
    board = Board(tmp_path)
    haroo = board.project("haroo", seats=3)
    agent = board.project("agent", seats=1)
    for index in range(3):
        board.cr(haroo, "in-progress", f"HAR-{index + 1:03d}")
    board.state(haroo, {
        "leader": None,
        **{str(index): {"job_id": f"HAR-{index + 1:03d}", "git_hash": None,
                        "session": None} for index in range(3)},
    })
    board.cr(agent, "in-progress", "AG-001")
    board.state(agent, {
        "leader": None,
        "0": {"job_id": "AG-001", "git_hash": None, "session": session(0)},
    })
    calls = []
    notifications = []
    socket = click_socket(request)
    app = SidebarApp(
        str(board.config), poll=False, click_socket=socket,
        on_seat=lambda project, seat, client=None: calls.append((project, seat, client)),
    )
    app.notify = lambda message, **kwargs: notifications.append((message, kwargs))

    async def send_click(button):
        reader, writer = await asyncio.open_unix_connection(socket)
        writer.write((json.dumps({
            "client": "client-a", "x": button.region.x + 1, "y": button.region.y,
        }) + "\n").encode())
        await writer.drain()
        result = json.loads(await reader.readline())
        writer.close()
        await writer.wait_closed()
        return result

    async def check():
        async with app.run_test(size=(50, 25)) as pilot:
            snapshot = model.snapshot(board.config, now=NOW)
            assert [seat["status"] for seat in snapshot["projects"][0]["seats"]] == ["pending"] * 3
            assert snapshot["projects"][1]["seats"][0]["status"] == "working"
            await app.apply_snapshot(snapshot)
            await pilot.pause()
            await pilot.click("#project-0-seats")
            await pilot.click("#project-1-seats")
            await pilot.pause()
            for index in range(3):
                selector = f"#project-0-seat-{index}"
                button = app.query_one(selector, Button)
                assert str(button.label) == f"대기 {index} HAR-{index + 1:03d}"
                assert button.disabled
                await pilot.click(selector)
                result = await send_click(button)
                assert result["ok"] and result["error"] is None
            assert calls == [] and notifications == []

            running = app.query_one("#project-1-seat-0", Button)
            assert str(running.label) == "  0 AG-001 2h 30m" and not running.disabled
            await pilot.click("#project-1-seat-0")
            result = await send_click(running)
            await pilot.pause()
            assert result["ok"] and calls == [("agent", 0, None), ("agent", 0, "client-a")]
            assert notifications == []

    asyncio.run(check())


def test_decision_count_color_tracks_open_count_and_missing_or_error_state(tmp_path):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    app = SidebarApp(str(board.config), poll=False)

    async def check():
        async with app.run_test(size=(50, 20)) as pilot:
            async def verify(label, color, disabled):
                await app.apply_snapshot(model.snapshot(board.config))
                await pilot.pause()
                button = app.query_one("#project-0-D", Button)
                assert str(button.label) == label
                assert button.styles.color.hex.lower() == color
                assert color in str(button.rich_style).lower()
                assert button.disabled is disabled
                if disabled:
                    result = app.dispatch_client_click("client-a", button.region.x + 1, button.region.y)
                    assert result["ok"] and result["error"] is None

            await verify("D:0", "#ffd479", True)
            first = board.decide(base, "open", "D-20261107-01")
            await verify("D:1", "#ff8f8f", False)
            second = board.decide(base, "open", "D-20261107-02")
            await verify("D:2", "#ff8f8f", False)
            first.unlink()
            second.unlink()
            await verify("D:0", "#ffd479", True)

            snapshot = model.snapshot(board.config)
            snapshot["projects"][0]["decide"] = None
            await app.apply_snapshot(snapshot)
            await pilot.pause()
            button = app.query_one("#project-0-D", Button)
            assert str(button.label) == "D:-" and button.disabled
            assert button.styles.color.hex.lower() == "#ffd479"
            assert app.dispatch_client_click("client-a", button.region.x + 1, button.region.y)["ok"]

            snapshot["projects"][0]["errors"].append({"source": "decide", "message": "read failed"})
            await app.apply_snapshot(snapshot)
            await pilot.pause()
            button = app.query_one("#project-0-D", Button)
            assert str(button.label) == "D:!" and button.disabled
            assert button.styles.color.hex.lower() == "#ffd479"
            assert app.dispatch_client_click("client-a", button.region.x + 1, button.region.y)["ok"]

    asyncio.run(check())


@pytest.mark.parametrize("state, related", (("answered", None), ("done", "SESSION-020")))
def test_unfinished_decision_remains_accessible_without_open_decisions(tmp_path, state, related):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    decision = board.decide(base, state, "D-20261107-01", "진행 중인 질문", related=related)
    if related:
        cr = board.cr(base, "in-progress", related)
    calls = []
    app = SidebarApp(str(board.config), poll=False,
                     on_decision=lambda project, item: calls.append((project, item)))

    async def check():
        async with app.run_test(size=(50, 20)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            button = app.query_one("#project-0-D", Button)
            assert str(button.label) == "D:0"
            assert not button.disabled
            assert not button.has_class("decision-open")
            await pilot.click("#project-0-D")
            await pilot.pause()
            assert calls == [("Falcon2", None)]
            if related:
                cr.rename(base / "agent/cr/done" / cr.name)
            else:
                decision.rename(base / "agent/decide/done" / decision.name)
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            button = app.query_one("#project-0-D", Button)
            assert str(button.label) == "D:0" and button.disabled

    asyncio.run(check())


def test_sidebar_completed_decisions_do_not_open_popup(tmp_path):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    board.decide(base, "done", "D-20261107-01", "완료된 질문")
    calls = []
    app = SidebarApp(str(board.config), poll=False,
                     on_decision=lambda *args, **kwargs: calls.append((args, kwargs)))

    async def check():
        async with app.run_test(size=(50, 20)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            button = app.query_one("#project-0-D", Button)
            assert str(button.label) == "D:0"
            assert button.disabled
            await pilot.click("#project-0-D")
            assert app.dispatch_client_click("client-a", button.region.x + 1, button.region.y)["ok"]
            await pilot.pause()
            assert calls == []

    asyncio.run(check())


def test_popup_completed_decisions_show_empty_view(tmp_path):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    board.decide(base, "done", "D-20261107-01", "완료된 질문")
    app = PopupApp(str(board.config), "Falcon2", "D-20261107-01", load=False)

    async def check():
        async with app.run_test(size=(100, 36)) as pilot:
            snapshot = model.snapshot(board.config)
            assert len(snapshot["projects"][0]["decide"]) == 1
            await app.apply_snapshot(snapshot)
            await pilot.pause()
            assert app.decisions == {} and app.decide_id is None
            assert not app.query("#decision-list Button")
            assert "결정 없음" in str(app.query_one("#popup-heading", Static).content)
            assert not app.query_one("#decision-detail").children
            assert app.query_one("#answer", TextArea).disabled
            assert app.query_one("#send", Button).disabled
            await pilot.press("escape")

    asyncio.run(check())


def test_popup_labels_stages_and_disables_answer_for_non_open_decisions(tmp_path):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    board.decide(base, "open", "D-20261107-01", "기다리는 질문")
    board.decide(base, "answered", "D-20261107-02", "접수된 질문")
    board.decide(base, "done", "D-20261107-03", "반영 중인 질문", related="SESSION-020")
    board.decide(base, "done", "D-20261107-04", "완료된 질문")
    board.cr(base, "in-progress", "SESSION-020")
    sidebar = SidebarApp(str(board.config), poll=False)
    sent = []
    app = PopupApp(str(board.config), "Falcon2", load=False,
                   answer_sender=lambda *args: sent.append(args))

    async def check():
        snapshot = model.snapshot(board.config)
        assert len(snapshot["projects"][0]["decide"]) == 4
        async with sidebar.run_test(size=(50, 20)) as pilot:
            await sidebar.apply_snapshot(snapshot)
            await pilot.pause()
            button = sidebar.query_one("#project-0-D", Button)
            assert str(button.label) == "D:1" and not button.disabled
        async with app.run_test(size=(100, 36)) as pilot:
            await app.apply_snapshot(snapshot)
            await pilot.pause()
            assert [str(button.label) for button in app.query("#decision-list Button")] == [
                "▶ D-20261107-01 대기 기다리는 질문",
                "  D-20261107-02 접수 접수된 질문",
                "  D-20261107-03 반영 반영 중인 질문",
            ]
            assert "D-20261107-04" not in app.decisions
            editor = app.query_one("#answer", TextArea)
            send = app.query_one("#send", Button)
            assert not editor.disabled and not send.disabled
            for index, stage in ((1, "답변 접수"), (2, "반영 중")):
                await pilot.click(f"#decision-{index}")
                assert stage in str(app.query_one("#popup-heading", Static).content)
                assert editor.disabled and send.disabled
                app.action_send()
                assert sent == []
            await pilot.click("#decision-0")
            assert not editor.disabled and not send.disabled

    asyncio.run(check())


def test_popup_refresh_replaces_completed_selection_and_clears_empty_view(tmp_path):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    first = board.decide(base, "open", "D-20261107-01", "첫 질문")
    selected = board.decide(base, "open", "D-20261107-02", "선택한 질문")
    board.decide(base, "done", "D-20261107-03", "반영 중인 질문", related="SESSION-020")
    related = board.cr(base, "in-progress", "SESSION-020")
    app = PopupApp(str(board.config), "Falcon2", "D-20261107-02", load=False)

    async def check():
        async with app.run_test(size=(100, 36)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            editor = app.query_one("#answer", TextArea)
            editor.text = "완료된 질문의 초안"
            selected.rename(base / "agent/decide/done" / selected.name)
            await app.apply_snapshot(model.snapshot(board.config))
            assert list(app.decisions) == ["D-20261107-01", "D-20261107-03"]
            assert app.decide_id == "D-20261107-01"
            assert editor.text == "" and not editor.disabled
            assert "첫 질문" in str(app.query_one(".decision-meta", Static).content)
            first.rename(base / "agent/decide/done" / first.name)
            await app.apply_snapshot(model.snapshot(board.config))
            assert app.decide_id == "D-20261107-03"
            assert editor.disabled
            related.rename(base / "agent/cr/done" / related.name)
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            assert app.decisions == {} and app.decide_id is None
            assert not app.query_one("#decision-detail").children
            assert editor.text == "" and editor.disabled
            assert app.query_one("#send", Button).disabled
            assert "결정 없음" in str(app.query_one("#popup-heading", Static).content)

    asyncio.run(check())


@pytest.mark.parametrize("kind", ("cr", "decision"))
@pytest.mark.parametrize("initial_width", (69, 70))
def test_popup_list_button_tracks_width_and_resize(tmp_path, kind, initial_width):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    if kind == "cr":
        board.cr(base, "open", "CPU-001", "첫 CR")
        board.cr(base, "open", "CPU-002", "둘째 CR")
        app = CRPopupApp(str(board.config), "Falcon2", "open", load=False)
        button, listing, detail, second = "#cr-show-list", "#cr-items", "#cr-detail", "#cr-item-1"
    else:
        board.decide(base, "open", "D-20261107-01", "첫 질문")
        board.decide(base, "open", "D-20261107-02", "둘째 질문")
        app = PopupApp(str(board.config), "Falcon2", load=False)
        button, listing, detail, second = "#show-list", "#decision-list", "#decision-detail", "#decision-1"

    async def check():
        async with app.run_test(size=(initial_width, 28)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            assert app.query_one(button).display is (initial_width < 70)
            assert app.query_one(listing).display is (initial_width >= 70)
            assert app.query_one(detail).display
            await pilot.resize_terminal(69, 28)
            await pilot.pause()
            assert app.query_one(button).display
            await pilot.click(button)
            assert app.query_one(listing).display and not app.query_one(detail).display
            await pilot.resize_terminal(70, 28)
            await pilot.pause()
            assert not app.query_one(button).display
            assert app.query_one(listing).display and app.query_one(detail).display
            await pilot.resize_terminal(69, 28)
            await pilot.pause()
            assert app.query_one(button).display
            assert not app.query_one(listing).display and app.query_one(detail).display
            await pilot.click(button)
            app.query_one(second, Button).focus()
            await pilot.press("enter")
            await pilot.pause()
            assert not app.query_one(listing).display and app.query_one(detail).display
            if kind == "cr":
                assert app.selected_id == "CPU-002"
            else:
                assert app.decide_id == "D-20261107-02"
                assert not app.query_one("#answer", TextArea).disabled
            await pilot.click(button)
            assert app.query_one(listing).display
            await pilot.pause(app.query_one(button, Button).active_effect_duration)
            await pilot.click(button)
            assert app.query_one(detail).display
            await pilot.click("#cr-close" if kind == "cr" else "#close")

    asyncio.run(check())


def test_sidebar_ignores_liveness_for_an_old_session(tmp_path):
    board = _make_sidebar_board(tmp_path)
    app = SidebarApp(str(board.config), poll=False)

    async def check():
        async with app.run_test() as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            await pilot.click("#project-0-seats")
            await pilot.pause()
            await app.apply_liveness({
                "Falcon2": {"0": {"session_id": "old-session", "state": "stopped"}}
            })
            assert not app.query_one("#project-0-seat-0", Button).has_class("seat-stopped")
            await app.apply_liveness({
                "Falcon2": {"0": {"session_id": app.snapshot_data["projects"][0]["seats"][0]["session_id"],
                                    "state": "stopped"}}
            })
            assert app.query_one("#project-0-seat-0", Button).has_class("seat-stopped")
            await pilot.pause()

    asyncio.run(check())


def test_slow_refresh_keeps_clicks_responsive_and_does_not_overlap(tmp_path):
    board = _make_sidebar_board(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    calls = []
    decisions = []

    def slow_snapshot(config):
        calls.append(config)
        entered.set()
        release.wait(timeout=5)
        return model.snapshot(config)

    app = SidebarApp(str(board.config), poll=False, snapshot_reader=slow_snapshot,
                     on_decision=lambda project, item: decisions.append((project, item)))

    async def check():
        async with app.run_test(size=(50, 25)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            first = asyncio.create_task(app.refresh_snapshot())
            assert await asyncio.to_thread(entered.wait, 2)
            await pilot.click("#project-0-D")
            await pilot.pause()
            assert decisions == [("Falcon2", None)]
            await app.refresh_snapshot()
            assert len(calls) == 1
            release.set()
            await first

    try:
        asyncio.run(check())
    finally:
        release.set()


def test_a_sidebar_nobody_watches_reads_nothing_until_it_is_shown(tmp_path):
    board = _make_sidebar_board(tmp_path)
    reads = []
    lives = []

    def snapshot(config):
        reads.append(config)
        return model.snapshot(config)

    def liveness(config):
        lives.append(config)
        return {}

    app = SidebarApp(str(board.config), poll=False, snapshot_reader=snapshot, liveness_reader=liveness)

    async def check():
        async with app.run_test(size=(25, 25)) as pilot:
            await app.refresh_snapshot()
            await app.refresh_liveness()
            assert (len(reads), len(lives)) == (1, 1)
            app.set_visible(False)
            await app.refresh_snapshot()
            await app.refresh_liveness()
            assert (len(reads), len(lives)) == (1, 1)             # hidden: no read
            app.set_visible(True)                                   # shown again: one read of each at once
            await wait_until(pilot, lambda: (len(reads), len(lives)) == (2, 2))
            app.set_visible(True)                                   # already shown: nothing more
            await pilot.pause(0.1)
            assert (len(reads), len(lives)) == (2, 2)

    asyncio.run(check())


def test_sigusr1_makes_a_sidebar_ask_tmux_whether_its_window_is_shown(tmp_path):
    board = _make_sidebar_board(tmp_path)
    shown = {"value": True}
    marked = []
    reads = []

    def snapshot(config):
        reads.append(config)
        return model.snapshot(config)

    app = SidebarApp(str(board.config), snapshot_reader=snapshot, liveness_reader=lambda config: {},
                     mark_ready=lambda: marked.append(True) or shown["value"],
                     visibility_reader=lambda: shown["value"])

    async def check():
        async with app.run_test(size=(25, 25)) as pilot:
            await wait_until(pilot, lambda: marked and reads)        # ready, and read once while shown
            shown["value"] = False
            os.kill(os.getpid(), signal.SIGUSR1)
            await wait_until(pilot, lambda: not app._visible)
            count = len(reads)
            await app.refresh_snapshot()
            assert len(reads) == count
            shown["value"] = True
            os.kill(os.getpid(), signal.SIGUSR1)
            await wait_until(pilot, lambda: app._visible and len(reads) > count)

    asyncio.run(check())
    assert signal.getsignal(signal.SIGUSR1) in (signal.SIG_DFL, None)   # the handler leaves with the app


def test_popup_renders_markdown_and_csv_and_closes_editor_after_acceptance(tmp_path):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=1)
    decision_path = board.decide(base, "open", "D-20261107-01", "설계를 선택하세요")
    decision_path.write_text(
        decision_path.read_text(encoding="utf-8")
        + "\n## Data\n\n```csv\nOption,Cost\nA,2\nB,3\n```\n",
        encoding="utf-8",
    )
    started = threading.Event()
    release = threading.Event()
    sent = []

    def sender(config, project, decision, draft):
        sent.append((project, decision, draft))
        started.set()
        release.wait(timeout=5)
        decision_path.rename(base / "agent/decide/answered" / decision_path.name)
        return {"ok": True, "data": {"accepted": True, "notification": {"status": "sent"}}, "error": None}

    app = PopupApp(str(board.config), "Falcon2", load=False, answer_sender=sender)

    async def check():
        async with app.run_test(size=(100, 36)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            assert "결정 1/1" in str(app.query_one("#popup-heading", Static).content)
            assert any("| 선택지 | 내용 |" in widget.source for widget in app.query(Markdown))
            tables = list(app.query(DataTable))
            assert len(tables) == 1 and tables[0].row_count == 2
            assert not app.query_one("#evidence-body").display
            await pilot.click("#evidence-toggle")
            assert app.query_one("#evidence-body").display
            editor = app.query_one("#answer", TextArea)
            editor.text = "처음 보낸 답"
            await pilot.click("#send")
            await asyncio.to_thread(started.wait, 2)
            await pilot.click("#send")
            editor.text = "새 초안"
            release.set()
            await wait_until(pilot, lambda: "답변 접수 ·" in str(app.query_one("#popup-message", Static).content))
            assert sent == [("Falcon2", "D-20261107-01", "처음 보낸 답")]
            assert editor.text == "" and editor.disabled
            assert "답변 접수" in str(app.query_one("#popup-message", Static).content)

    try:
        asyncio.run(check())
    finally:
        release.set()


@pytest.mark.parametrize("notification, page_error, phrase", [
    ("sent", None, "알림 완료"), ("failed", None, "알림 실패"),
    ("unconfirmed", None, "결과 불명"), ("sent", "render failed", "결정 페이지 갱신에 실패"),
])
def test_accepted_answer_closes_editor_even_when_notification_is_uncertain(tmp_path, notification, page_error, phrase):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    source = board.decide(base, "open", "D-20261107-01")
    sent = []

    def sender(config, project, decision, draft):
        sent.append(draft)
        source.rename(base / "agent/decide/answered" / source.name)
        return {"ok": True, "data": {"accepted": True, "notification": {"status": notification},
                                      "page_error": page_error},
                "error": None}

    app = PopupApp(str(board.config), "Falcon2", load=False, answer_sender=sender)

    async def check():
        async with app.run_test(size=(100, 36)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            editor = app.query_one("#answer", TextArea)
            editor.text = "A\n두 번째 줄"
            await pilot.click("#send")
            await wait_until(pilot, lambda: phrase in str(app.query_one("#popup-message", Static).content))
            assert sent == ["A\n두 번째 줄"]
            assert editor.text == "" and editor.disabled
            assert app.query_one("#send", Button).disabled
            assert "답변 접수" in str(app.query_one("#popup-heading", Static).content)
            assert phrase in str(app.query_one("#popup-message", Static).content)
            app.action_send()
            assert sent == ["A\n두 번째 줄"]

    asyncio.run(check())


def test_unconfirmed_acceptance_response_keeps_the_draft(tmp_path):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    board.decide(base, "open", "D-20261107-01")
    app = PopupApp(str(board.config), "Falcon2", load=False,
                   answer_sender=lambda *_: {"ok": True, "data": {}, "error": None})

    async def check():
        async with app.run_test(size=(100, 36)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            editor = app.query_one("#answer", TextArea)
            editor.text = "검증되지 않은 답"
            await pilot.click("#send")
            await wait_until(pilot, lambda: "접수를 확인하지 못했습니다" in str(app.query_one("#popup-message", Static).content))
            assert editor.text == "검증되지 않은 답" and not editor.disabled
            assert "접수를 확인하지 못했습니다" in str(app.query_one("#popup-message", Static).content)

    asyncio.run(check())


def test_percent_encoded_local_csv_link_opens_a_table(tmp_path):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=1)
    decision_path = board.decide(base, "open", "D-20261107-01")
    decision_path.write_text(
        decision_path.read_text(encoding="utf-8")
        + "\n## Data\n\n[비용표](my%20data.csv)\n",
        encoding="utf-8",
    )
    decision_path.with_name("my data.csv").write_text("Item,Cost\nA,10\n", encoding="utf-8")
    app = PopupApp(str(board.config), "Falcon2", load=False)

    async def check():
        async with app.run_test(size=(100, 36)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            widget = next(item for item in app.query(Markdown) if "my%20data.csv" in item.source)
            app.on_markdown_link_clicked(Markdown.LinkClicked(widget, "my%20data.csv"))
            await wait_until(pilot, lambda: isinstance(app.screen, CSVScreen)
                             and app.screen.query(DataTable))
            assert isinstance(app.screen, CSVScreen)
            assert app.screen.query_one(DataTable).row_count == 1

    asyncio.run(check())


def test_switching_decisions_keeps_each_unsent_draft(tmp_path):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=1)
    board.decide(base, "open", "D-20261107-01", "첫 질문")
    board.decide(base, "open", "D-20261107-02", "둘째 질문")
    app = PopupApp(str(board.config), "Falcon2", load=False)

    async def check():
        async with app.run_test(size=(100, 36)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            editor = app.query_one("#answer", TextArea)
            editor.text = "첫 답변 초안"
            await pilot.click("#decision-1")
            assert app.decide_id == "D-20261107-02" and editor.text == ""
            editor.text = "둘째 답변 초안"
            await pilot.click("#decision-0")
            assert app.decide_id == "D-20261107-01" and editor.text == "첫 답변 초안"

    asyncio.run(check())


def test_hover_tooltip_does_not_outlive_pane_focus(tmp_path):
    """BOARD-005: a tooltip shown or about to show when tmux moves focus away must not stay."""
    from textual import events
    from textual.widgets._tooltip import Tooltip

    board = Board(tmp_path)
    board.cr(board.project("Falcon2", seats=1), "open", "CPU-001")
    app = SidebarApp(str(board.config), poll=False)

    async def check():
        async with app.run_test(size=(25, 25), tooltips=True) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            tooltip = app.screen.get_child_by_type(Tooltip)
            await pilot.hover("#project-0-name")
            await wait_until(pilot, lambda: tooltip.display)
            app.post_message(events.AppBlur())
            await wait_until(pilot, lambda: not tooltip.display)
            await pilot.pause(app.TOOLTIP_DELAY + 0.2)
            assert not tooltip.display
            # Focus lost before the delay ends: the pending tooltip must not appear afterwards.
            await pilot.hover("#project-0-seats")
            app.post_message(events.AppBlur())
            await pilot.pause(app.TOOLTIP_DELAY + 0.3)
            assert not tooltip.display
            # Focus back and a new hover shows the tooltip again.
            app.post_message(events.AppFocus())
            await pilot.hover("#project-0-name")
            await wait_until(pilot, lambda: tooltip.display)

    asyncio.run(check())


def test_hover_tooltip_expires_after_the_mouse_stops_moving(tmp_path):
    """BOARD-005: the mouse leaving the pane sends tmux no event, so the tooltip must expire by itself."""
    from textual.widgets._tooltip import Tooltip

    board = Board(tmp_path)
    board.cr(board.project("Falcon2", seats=1), "open", "CPU-001")
    app = SidebarApp(str(board.config), poll=False)
    app.TOOLTIP_IDLE = 1.0

    async def check():
        async with app.run_test(size=(25, 25), tooltips=True) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            tooltip = app.screen.get_child_by_type(Tooltip)
            await pilot.hover("#project-0-name")
            await wait_until(pilot, lambda: tooltip.display)
            # Motion restarts the idle time: still shown after more than one idle period of moving.
            for _ in range(3):
                await pilot.pause(0.5)
                await pilot.hover("#project-0-seats")
                await pilot.hover("#project-0-name")
            await wait_until(pilot, lambda: tooltip.display)
            # No more motion (the mouse is over another pane): it goes away by itself, and stays away.
            await wait_until(pilot, lambda: not tooltip.display, timeout=app.TOOLTIP_IDLE + 2)
            await pilot.pause(app.TOOLTIP_DELAY + 0.3)
            assert not tooltip.display

    asyncio.run(check())


def _list_rows(app, selector):
    return [(str(button.label), button.has_class("selected"), button.region.height) for button in app.query(selector)]


@pytest.mark.parametrize("width", (80, 120))
def test_cr_popup_rows_are_one_line_and_mark_the_selected_item(tmp_path, width):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    long_title = "아주 긴 한글 제목입니다 " * 6 + "[not markup]"
    board.cr(base, "in-progress", "CPU-001", "Short", mode="write")
    board.cr(base, "in-progress", "CPU-002", long_title)
    app = CRPopupApp(str(board.config), "Falcon2", "in-progress", load=False)

    async def check():
        async with app.run_test(size=(width, 24)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            rows = _list_rows(app, ".list-item")
            assert [row[2] for row in rows] == [1, 1]  # a long title does not wrap
            assert [row[1] for row in rows] == [True, False]
            assert rows[0][0] == "▶ CPU-001 Short" and rows[1][0].startswith("  CPU-002 아주")
            assert app.query_one("#cr-items").region.width == (32 if width == 80 else 46)  # 40%, 30..46
            await pilot.click("#cr-item-1")
            await pilot.pause()
            rows = _list_rows(app, ".list-item")
            assert [row[1] for row in rows] == [False, True]
            assert rows[0][0].startswith("  CPU-001") and rows[1][0].startswith("▶ CPU-002")
            assert "[not markup]" in rows[1][0]

    asyncio.run(check())


def test_popup_marks_selected_decision_and_keeps_id_and_status_when_title_is_long(tmp_path):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    board.decide(base, "open", "D-20261107-01", "A very long decision title " * 8)
    board.decide(base, "answered", "D-20261107-02", "접수된 질문")
    app = PopupApp(str(board.config), "Falcon2", load=False)

    async def check():
        async with app.run_test(size=(80, 30)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            rows = _list_rows(app, "#decision-list Button")
            assert [row[1:] for row in rows] == [(True, 1), (False, 1)]
            assert rows[0][0].startswith("▶ D-20261107-01 대기 A very")
            screen_lines = [line.text for line in app.screen._compositor.render_strips()]
            assert any("D-20261107-01 대기 A very" in line and "…" in line for line in screen_lines)
            await pilot.click("#decision-1")
            await pilot.pause()
            rows = _list_rows(app, "#decision-list Button")
            assert [row[1] for row in rows] == [False, True]
            assert rows[1][0] == "▶ D-20261107-02 접수 접수된 질문"

    asyncio.run(check())


def test_cr_popup_row_marks_review_wait(tmp_path):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    board.cr(base, "in-progress", "CPU-001", "Submitted", result="- 제출 commit: " + "a" * 40 + "\n")
    board.cr(base, "in-progress", "CPU-002", "Working")
    snapshot = model.snapshot(board.config)
    app = CRPopupApp(str(board.config), "Falcon2", "in-progress", load=False)

    async def check():
        async with app.run_test(size=(80, 24)) as pilot:
            await app.apply_snapshot(snapshot)
            await pilot.pause()
            assert [row[0] for row in _list_rows(app, ".list-item")] == [
                "▶ CPU-001 검토 Submitted", "  CPU-002 Working"]

    asyncio.run(check())


def _count_draws(monkeypatch):
    """`built`: blocks created (a new block is mounted); `written`: blocks updated in the widgets already mounted."""
    built, written = [], []
    block, update = SidebarApp._project_block, SidebarApp._update_block

    def counted_block(self, number, project):
        built.append(number)
        return block(self, number, project)

    def counted_update(self, number, project):
        written.append(number)
        return update(self, number, project)
    monkeypatch.setattr(SidebarApp, "_project_block", counted_block)
    monkeypatch.setattr(SidebarApp, "_update_block", counted_update)
    return built, written


def test_a_refresh_that_changes_nothing_shown_draws_nothing_and_a_change_writes_only_its_project(tmp_path, monkeypatch):
    board = _make_sidebar_board(tmp_path)                       # Falcon2 has a Worker and a Leader; ProjectB is folded
    app = SidebarApp(str(board.config), poll=False)
    built, written = _count_draws(monkeypatch)

    async def check():
        async with app.run_test(size=(40, 25)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config, now=NOW))
            await pilot.pause()
            assert built == [0, 1] and written == []
            built.clear()
            names = [app.query_one(f"#project-{n}-name", Button) for n in (0, 1)]
            # The same state again, and a later minute: the seats are folded, so no minute counter is on screen.
            await app.apply_snapshot(model.snapshot(board.config, now=NOW))
            await app.apply_snapshot(model.snapshot(board.config, now=NOW + dt.timedelta(minutes=5)))
            await pilot.pause()
            assert built == [] and written == []
            # A CR is added to ProjectB only: its widgets are written, no widget is replaced, Falcon2 is not touched.
            board.cr(tmp_path / "ProjectB" / "main", "open", "OTH-001")
            await app.apply_snapshot(model.snapshot(board.config, now=NOW))
            await pilot.pause()
            assert built == [] and written == [1]
            assert [app.query_one(f"#project-{n}-name", Button) for n in (0, 1)] == names
            assert str(app.query_one("#project-1-O", Button).label) == "O:1"
            assert not app.query_one("#project-1-O", Button).disabled
            assert [str(button.label) for button in app.query(".project-name")] == ["Falcon2", "ProjectB"]
            # A project that appears changes the list: everything is drawn again, in order.
            built.clear()
            board.project("ProjectC", seats=1)
            await app.apply_snapshot(model.snapshot(board.config, now=NOW))
            await pilot.pause()
            assert built == [0, 1, 2]
            assert [str(button.label) for button in app.query(".project-name")] == ["Falcon2", "ProjectB", "ProjectC"]

    asyncio.run(check())


def test_the_minute_of_an_expanded_project_is_written_into_its_widgets(tmp_path, monkeypatch):
    board = _make_sidebar_board(tmp_path)
    app = SidebarApp(str(board.config), poll=False)
    built, written = _count_draws(monkeypatch)

    async def check():
        async with app.run_test(size=(40, 25)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config, now=NOW))
            await pilot.pause()
            await pilot.click("#project-0-seats")
            await wait_until(pilot, lambda: app.query(".leader"))
            other = app.query_one("#project-1-name", Button)
            leader_row = app.query_one(".leader", Static)
            seat = app.query_one("#project-0-seat-0", Button)
            built.clear()
            written.clear()
            await app.apply_snapshot(model.snapshot(board.config, now=NOW + dt.timedelta(seconds=60)))
            await pilot.pause()
            assert built == [] and written == [0]
            assert _leader_rows(app) == ["  Leader 1d 01h 31m"]
            assert str(seat.label) == "R 0 CPU-012 2h 31m"
            assert app.query_one(".leader", Static) is leader_row
            assert app.query_one("#project-0-seat-0", Button) is seat
            assert app.query_one("#project-1-name", Button) is other

    asyncio.run(check())


def _seat_state(base, *, second=None):
    seats = {"0": {"job_id": "CPU-012", "git_hash": None, "session": session(0)},
             "1": {"job_id": None, "git_hash": None, "session": None},
             "2": {"job_id": None, "git_hash": None, "session": None}}
    if second:
        seats["1"] = {"job_id": second, "git_hash": None, "session": session(1)}
    Board.state(base, {"leader": leader(), **seats})


def test_the_sidebar_never_draws_a_state_between_the_one_before_a_change_and_the_one_after_it(tmp_path):
    """BOARD-017 (a)(b)(c): opening, changing a value, and rows that appear or disappear. The screen is tall
    enough for every row, so only the rows of the Board change (not Textual's scrollbar)."""
    board = _make_sidebar_board(tmp_path)
    falcon, other = tmp_path / "Falcon2" / "main", tmp_path / "ProjectB" / "main"
    expanded, context = {"Falcon2"}, {"project_id": "Falcon2", "slot": "seat-0"}

    def toggle(project_id):
        expanded.symmetric_difference_update({project_id})
        return set(expanded)

    app = SidebarApp(str(board.config), poll=False, expanded_reader=lambda: set(expanded),
                     expanded_toggler=toggle, context_reader=lambda: dict(context))
    live = {"Falcon2": {"0": {"session_id": WORKER_IDS[0], "state": "running"}}}
    snapshot = lambda seconds=0: model.snapshot(board.config, now=NOW + dt.timedelta(seconds=seconds))

    async def check():
        frames = Frames(app)
        async with app.run_test(size=(30, 40)) as pilot:
            # (a) opening: the snapshot, then liveness, then the managed window arrive one after another.
            await frames.assert_only_before_or_after(pilot, lambda: app.apply_snapshot(snapshot()), "snapshot")
            live["Falcon2"]["0"]["state"] = "stopped"
            await frames.assert_only_before_or_after(pilot, lambda: app.apply_liveness(live), "liveness")
            await frames.assert_only_before_or_after(pilot, app.refresh_context, "managed window")
            # (b) values of the expanded project: its minute, a seat that gets a job, the shown window.
            await frames.assert_only_before_or_after(pilot, lambda: app.apply_snapshot(snapshot(60)), "minute")
            board.cr(falcon, "in-progress", "CPU-013")
            _seat_state(falcon, second="CPU-013")
            await frames.assert_only_before_or_after(pilot, lambda: app.apply_snapshot(snapshot(61)), "seat job")
            context["slot"] = "leader"
            await frames.assert_only_before_or_after(pilot, app.refresh_context, "shown window")
            # (c) rows appear and disappear: fold, unfold, a project, an error row.
            await frames.assert_only_before_or_after(pilot, lambda: app._toggle_expanded("Falcon2"), "fold")
            await frames.assert_only_before_or_after(pilot, lambda: app._toggle_expanded("Falcon2"), "unfold")
            board.project("ProjectC", seats=1)
            await frames.assert_only_before_or_after(pilot, lambda: app.apply_snapshot(snapshot(62)), "project added")
            (other / "agent/cr").rename(other / "agent/cr-gone")
            await frames.assert_only_before_or_after(pilot, lambda: app.apply_snapshot(snapshot(63)), "error row added")
            (other / "agent/cr-gone").rename(other / "agent/cr")
            await frames.assert_only_before_or_after(pilot, lambda: app.apply_snapshot(snapshot(64)), "error row removed")

    asyncio.run(check())


def test_a_value_written_in_place_keeps_click_target_scroll_and_focus(tmp_path):
    board = Board(tmp_path)
    for number in range(8):
        base = board.project(f"Project{number:02d}", seats=1)
        board.cr(base, "open", f"P{number:02d}-001")
    clicked = []
    app = SidebarApp(str(board.config), poll=False,
                     on_cr=lambda project_id, state, **kwargs: clicked.append((project_id, state)))

    async def check():
        async with app.run_test(size=(25, 12)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause(0.1)
            scroll = app.query_one("#projects")
            scroll.scroll_to(y=scroll.max_scroll_y, animate=False)
            await pilot.pause()
            app.query_one("#project-7-name", Button).focus()
            await pilot.pause()
            y = scroll.scroll_y
            assert y > 0
            counter = app.query_one("#project-7-O", Button)
            board.cr(tmp_path / "Project07" / "main", "open", "P07-002")       # a value of the last project changes
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause(0.1)
            assert app.query_one("#project-7-O", Button) is counter
            assert str(counter.label) == "O:2"
            assert scroll.scroll_y == y
            assert app.focused is app.query_one("#project-7-name", Button)
            await pilot.click("#project-7-O")
            await pilot.pause()
            assert clicked == [("Project07", "open")]

    asyncio.run(check())


def test_renders_that_overlap_leave_one_block_per_project(tmp_path):
    board = _make_sidebar_board(tmp_path)
    app = SidebarApp(str(board.config), poll=False)

    async def check():
        async with app.run_test(size=(40, 25)) as pilot:
            await asyncio.gather(app.apply_snapshot(model.snapshot(board.config, now=NOW)),
                                 app.apply_liveness({}), app.apply_snapshot(model.snapshot(board.config, now=NOW)))
            await pilot.pause()
            assert [str(button.label) for button in app.query(".project-name")] == ["Falcon2", "ProjectB"]
            assert len(app.query(".project")) == 2

    asyncio.run(check())
