"""User interactions and displayed project facts in the terminal Board."""
import asyncio
import html
import json
import os
import re
import threading
import uuid

from board_testing import Board, leader, session
from project_board import model
from project_board.tui import CRPopupApp, CSVScreen, PopupApp, SidebarApp
from textual.widgets import Button, DataTable, Markdown, Static, TextArea


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
        async with app.run_test(size=(50, 25)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            assert [str(item.label) for item in app.query(".project-name")] == ["Falcon2", "ProjectB"]
            svg = app.export_screenshot()
            assert _rendered_left_column(svg, "Falcon2") == 0
            for label in ("O:2", "D:2", "R 0 CPU-012"):
                assert _rendered_left_column(svg, label) <= 1
            assert _rendered_left_column(svg, "1 Seat1") <= 3
            assert str(app.query_one("#project-0-O", Button).label) == "O:2"
            assert str(app.query_one("#project-0-T", Button).label) == "T:1"
            assert str(app.query_one("#project-0-I", Button).label) == "I:1"
            assert str(app.query_one("#project-0-D", Button).label) == "D:2"
            assert str(app.query_one("#project-0-seat-0", Button).label) == "R 0 CPU-012"
            empty = app.query_one("#project-0-seat-1", Button)
            assert str(empty.label) == "  1 Seat1" and empty.disabled
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


def test_cr_list_opens_in_its_own_popup(tmp_path):
    board = _make_sidebar_board(tmp_path)
    app = CRPopupApp(str(board.config), "Falcon2", "open", load=False)

    async def check():
        async with app.run_test(size=(70, 20)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            assert [str(item.content) for item in app.query(".cr-item")] == [
                "CPU-001\nCR title", "CPU-002\nCR title",
            ]
            await pilot.click("#cr-close")

    asyncio.run(check())


def test_ipc_click_routes_the_originating_client(tmp_path):
    board = _make_sidebar_board(tmp_path)
    calls = []
    socket = f"/tmp/project-board-ui-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
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


def test_empty_cr_and_decision_clicks_do_nothing_for_mouse_and_ipc(tmp_path):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    calls = []
    notifications = []
    socket = f"/tmp/project-board-ui-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    app = SidebarApp(
        str(board.config), poll=False, click_socket=socket,
        on_cr=lambda project, state, client=None: calls.append((project, state, client)),
        on_decision=lambda project, item, client=None: calls.append((project, item, client)),
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
            for selector in ("#project-0-O", "#project-0-T", "#project-0-I", "#project-0-D"):
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


def test_sidebar_ignores_liveness_for_an_old_session(tmp_path):
    board = _make_sidebar_board(tmp_path)
    app = SidebarApp(str(board.config), poll=False)

    async def check():
        async with app.run_test() as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
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


def test_popup_renders_markdown_and_csv_and_preserves_a_new_draft(tmp_path):
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
        return {"ok": True, "data": {}, "error": None}

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
            await pilot.pause(0.1)
            assert sent == [("Falcon2", "D-20261107-01", "처음 보낸 답")]
            assert editor.text == "새 초안"
            assert "전송했습니다" in str(app.query_one("#popup-message", Static).content)

    try:
        asyncio.run(check())
    finally:
        release.set()


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
            await pilot.pause(0.1)
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
