"""User interactions and displayed project facts in the terminal Board."""
import asyncio
import datetime as dt
import os
import re
import threading

import pytest

from board_testing import Board, click_socket, cron_run, cron_section, isolate_crontab, leader, session, wait_until
from wait_limit import command_timeout
from project_board import model, window_link
from project_board.tui import CRPopupApp, CronPopupApp, CSVScreen, PopupApp
from textual.widgets import Button, DataTable, Markdown, Static, TextArea


# 2h 30m after the worker sessions (08:00) and 1d 01h 30m after the Leader session (Nov 4 09:00).
NOW = dt.datetime(2026, 11, 5, 10, 30, tzinfo=dt.timezone.utc)




def _make_falcon_board(tmp_path):
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








































def test_cr_list_opens_in_its_own_popup(tmp_path):
    board = _make_falcon_board(tmp_path)
    app = CRPopupApp(str(board.config), "Falcon2", "open", load=False)

    async def check():
        async with app.run_test(size=(70, 20)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            assert [str(item.label) for item in app.query(".list-item")] == [
                "▶ CPU-001 CR title", "  CPU-002 CR title", "  CPU-003 CR title", "  CPU-012 CR title",
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
    sent = []
    app = PopupApp(str(board.config), "Falcon2", load=False,
                   answer_sender=lambda *args: sent.append(args))

    async def check():
        snapshot = model.snapshot(board.config)
        assert len(snapshot["projects"][0]["decide"]) == 4
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
        release.wait(timeout=command_timeout())
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


def test_answer_box_ctrl_j_inserts_a_newline_like_enter_and_keeps_ctrl_s(tmp_path):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    board.decide(base, "open", "D-20261107-01")
    sent = []
    app = PopupApp(str(board.config), "Falcon2", load=False,
                   answer_sender=lambda *args: sent.append(args) or {"ok": False, "error": {"message": "x"}})

    async def check():
        async with app.run_test(size=(100, 36)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            editor = app.query_one("#answer", TextArea)
            editor.focus()
            await pilot.press("a", "ctrl+j", "b", "enter", "c")
            assert editor.text == "a\nb\nc"
            editor.move_cursor((0, 1))
            await pilot.press("ctrl+j")
            assert editor.text == "a\n\nb\nc" and editor.cursor_location == (1, 0)
            await pilot.press("ctrl+s")
            await wait_until(pilot, lambda: sent)
            assert sent == [(str(board.config), "Falcon2", "D-20261107-01", "a\n\nb\nc")]
            await pilot.press("escape")

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














# BOARD-021: one CR window with four foldable groups, and ◀▶ between projects in the CR and decision windows.
# BOARD-026: the window opens with the Done group folded.

def _four_state_board(tmp_path, open_count=2):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    for number in range(open_count):
        board.cr(base, "open", f"CPU-{number + 1:03d}", f"open {number}")
    board.cr(base, "todo", "CPU-101", "todo one")
    board.cr(base, "in-progress", "CPU-201", "working one")
    board.cr(base, "in-progress", "CPU-202", "working two")
    done = [board.cr(base, "done", f"CPU-30{number}", f"done {number}") for number in range(3)]
    board.cr(base, "deferred", "CPU-400", "deferred one")
    return board, base, done


def _group_headers(app):
    return [str(button.label) for button in app.query(".group-header")]


@pytest.mark.parametrize("state", ("open", "todo", "in-progress"))
def test_cr_window_shows_four_groups_with_counts_for_any_pressed_state(tmp_path, state):
    board, _, _ = _four_state_board(tmp_path)
    app = CRPopupApp(str(board.config), "Falcon2", state, load=False)

    async def check():
        async with app.run_test(size=(90, 40)) as pilot:
            await app.apply_snapshot(model.popup_snapshot(board.config, "Falcon2", True))
            await pilot.pause()
            assert str(app.query_one("#cr-title", Static).content) == "Open 2, Todo 1, In-Progress 2, Done 3"
            assert _group_headers(app) == ["Open ▼", "Todo ▼", "In-Progress ▼", "Done ▶"]
            # only Done starts folded, and the rows of a folded group are not mounted until it is unfolded (BOARD-025)
            assert [(str(row.label)[2:9], row.display) for row in app.query(".list-item")] == [
                ("CPU-001", True), ("CPU-002", True), ("CPU-101", True), ("CPU-201", True), ("CPU-202", True)]
            assert "CPU-400" not in str(app.query_one("#cr-items").children)      # deferred stays hidden
            await pilot.click("#cr-group-done")
            await wait_until(pilot, lambda: len(app.query(".list-item")) == 8)
            assert [(str(row.label)[2:9], row.display) for row in app.query(".list-item")] == [
                ("CPU-001", True), ("CPU-002", True), ("CPU-101", True), ("CPU-201", True), ("CPU-202", True),
                ("CPU-300", True), ("CPU-301", True), ("CPU-302", True)]          # after its header, in list order
            assert _group_headers(app) == ["Open ▼", "Todo ▼", "In-Progress ▼", "Done ▼"]
            first = {"open": "CPU-001", "todo": "CPU-101", "in-progress": "CPU-201"}[state]
            assert app.selected_id == first

    asyncio.run(check())


def test_cr_window_scrolls_to_the_pressed_group_first(tmp_path):
    board, base, _ = _four_state_board(tmp_path, open_count=12)
    for number in range(10):
        board.cr(base, "in-progress", f"CPU-5{number:02d}", f"more working {number}")
    app = CRPopupApp(str(board.config), "Falcon2", "in-progress", load=False)

    async def check():
        async with app.run_test(size=(90, 14)) as pilot:
            await app.apply_snapshot(model.popup_snapshot(board.config, "Falcon2", True))
            await pilot.pause()
            listing = app.query_one("#cr-items")
            header = app.query_one("#cr-group-in-progress")
            await wait_until(pilot, lambda: listing.scroll_y > 0)    # the scroll follows the refresh
            assert header.region.y == listing.region.y            # the group starts at the top of the list
            assert app.selected_id == "CPU-201"

    asyncio.run(check())


def test_cr_window_folds_and_unfolds_each_group_and_reads_done(tmp_path):
    board, _, done = _four_state_board(tmp_path)
    app = CRPopupApp(str(board.config), "Falcon2", "open", load=False)

    async def check():
        async with app.run_test(size=(90, 40)) as pilot:
            await app.apply_snapshot(model.popup_snapshot(board.config, "Falcon2", True))
            await pilot.pause()
            await pilot.click("#cr-group-todo")
            await pilot.pause()
            assert _group_headers(app) == ["Open ▼", "Todo ▶", "In-Progress ▼", "Done ▶"]
            assert [str(row.label)[2:9] for row in app.query(".list-item") if row.display] == [
                "CPU-001", "CPU-002", "CPU-201", "CPU-202"]
            # the counts line does not change when a group is folded
            assert str(app.query_one("#cr-title", Static).content) == "Open 2, Todo 1, In-Progress 2, Done 3"
            await pilot.pause(app.query_one("#cr-group-done", Button).active_effect_duration)
            await pilot.click("#cr-group-done")
            await pilot.pause()
            assert _group_headers(app)[3] == "Done ▼"
            assert [str(row.label)[2:9] for row in app.query(".list-item") if row.display] == [
                "CPU-001", "CPU-002", "CPU-201", "CPU-202", "CPU-300", "CPU-301", "CPU-302"]
            await wait_until(pilot, lambda: str(app.query_one("#cr-item-5", Button).label).endswith("done 0"))
            await pilot.click("#cr-item-6")                       # a done CR opens its Markdown
            await wait_until(pilot, lambda: any(done[1].read_text(encoding="utf-8") == widget.source
                                                for widget in app.query(Markdown)))

    asyncio.run(check())


def test_cr_window_empty_group_and_sidebar_snapshot_has_no_done(tmp_path):
    board = Board(tmp_path)
    base = board.project("Falcon2", seats=0)
    board.cr(base, "open", "CPU-001")
    assert "done" not in model.snapshot(board.config)["projects"][0]["crs"]
    app = CRPopupApp(str(board.config), "Falcon2", "open", load=False)

    async def check():
        async with app.run_test(size=(90, 30)) as pilot:
            await app.apply_snapshot(model.popup_snapshot(board.config, "Falcon2", True))
            await pilot.pause()
            assert str(app.query_one("#cr-title", Static).content) == "Open 1, Todo 0, In-Progress 0, Done 0"
            await pilot.click("#cr-group-todo")
            assert not app.query_one("#cr-empty-todo").display

    asyncio.run(check())


def test_model_reads_done_cr_only_from_its_done_directory(tmp_path):
    board, base, done = _four_state_board(tmp_path)
    data = model.popup_snapshot(board.config, "Falcon2", True)
    project = data["projects"][0]
    assert [item["id"] for item in project["crs"]["done"]] == ["CPU-300", "CPU-301", "CPU-302"]
    assert project["crs"]["done"][0]["title"] == "item"                   # from the file name; the file is not opened
    assert data["order"] == ["Falcon2"] and [item["id"] for item in data["projects"]] == ["Falcon2"]
    assert model.read_cr_markdown(project, project["crs"]["done"][0], "done") == done[0].read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="유효하지"):
        model.read_cr_markdown(project, project["crs"]["done"][0], "deferred")
    with pytest.raises(ValueError, match="유효하지"):
        model.read_cr_markdown(project, project["crs"]["open"][0], "done")


def _three_projects(tmp_path):
    board = Board(tmp_path)
    first = board.project("Alpha", seats=0)
    board.cr(first, "open", "AAA-001", "alpha open")
    board.decide(first, "open", "D-20261107-01", "alpha question")
    second = board.project("Beta", seats=0)
    board.cr(second, "todo", "BBB-001", "beta todo")
    board.decide(second, "done", "D-20261107-02", "beta finished")        # no decision to show
    third = board.project("Gamma", seats=0)
    board.cr(third, "in-progress", "GGG-001", "gamma working")
    board.cr(third, "done", "GGG-002", "gamma done")
    board.decide(third, "open", "D-20261107-03", "gamma question")
    return board


def test_cr_window_moves_between_every_project_in_the_same_window_and_wraps(tmp_path):
    board = _three_projects(tmp_path)
    app = CRPopupApp(str(board.config), "Alpha", "open", load=False)

    async def project():
        return str(app.query_one("#cr-project", Static).content)

    async def check():
        async with app.run_test(size=(90, 30), tooltips=True) as pilot:
            await app.apply_snapshot(model.popup_snapshot(board.config, "Alpha", True))
            await pilot.pause()
            previous, following = app.query_one("#cr-prev", Button), app.query_one("#cr-next", Button)
            assert str(previous.tooltip) == "이전 project: Gamma"           # wraps to the other end
            assert str(following.tooltip) == "다음 project: Beta"
            await pilot.click("#cr-next")
            await wait_until(pilot, lambda: app.project_id == "Beta" and app.selected_id == "BBB-001")
            assert await project() == "Beta" and str(following.tooltip) == "다음 project: Gamma"
            assert str(previous.tooltip) == "이전 project: Alpha"
            assert str(app.query_one("#cr-title", Static).content) == "Open 0, Todo 1, In-Progress 0, Done 0"
            await pilot.click("#cr-next")
            await wait_until(pilot, lambda: app.project_id == "Gamma" and app.selected_id == "GGG-001")
            assert str(app.query_one("#cr-title", Static).content) == "Open 0, Todo 0, In-Progress 1, Done 1"
            assert [str(row.label)[2:9] for row in app.query(".list-item")] == ["GGG-001"]    # its Done is folded
            await pilot.click("#cr-next")                                     # past the last project: the first
            await wait_until(pilot, lambda: app.project_id == "Alpha" and app.selected_id == "AAA-001")
            await pilot.click("#cr-prev")                                     # before the first: the last
            await wait_until(pilot, lambda: app.project_id == "Gamma")
            assert app.is_running

    asyncio.run(check())


def test_cr_window_keeps_done_unfolded_when_moving_between_projects(tmp_path):
    board = _three_projects(tmp_path)
    app = CRPopupApp(str(board.config), "Alpha", "open", load=False)

    async def check():
        async with app.run_test(size=(90, 30)) as pilot:
            await app.apply_snapshot(model.popup_snapshot(board.config, "Alpha", True))
            await pilot.pause()
            await pilot.click("#cr-group-done")
            await pilot.pause()
            assert _group_headers(app)[3] == "Done ▼"
            await pilot.click("#cr-prev")                                     # Alpha → Gamma, which has a done CR
            await wait_until(pilot, lambda: app.project_id == "Gamma" and app.selected_id == "GGG-001")
            assert _group_headers(app)[3] == "Done ▼"
            assert [row.display for row in app.query(".list-item")] == [True, True]

    asyncio.run(check())


def test_cr_window_with_one_project_has_no_move_target(tmp_path):
    board = Board(tmp_path)
    base = board.project("Alpha", seats=0)
    board.cr(base, "open", "AAA-001")
    app = CRPopupApp(str(board.config), "Alpha", "open", load=False)

    async def check():
        async with app.run_test(size=(90, 20)) as pilot:
            await app.apply_snapshot(model.popup_snapshot(board.config, "Alpha", True))
            await pilot.pause()
            assert app.query_one("#cr-prev", Button).disabled and app.query_one("#cr-next", Button).disabled

    asyncio.run(check())


def test_decision_window_moves_only_between_projects_with_decisions_and_keeps_drafts(tmp_path):
    board = _three_projects(tmp_path)
    app = PopupApp(str(board.config), "Alpha", load=False)

    async def check():
        async with app.run_test(size=(100, 36), tooltips=True) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.pause()
            previous, following = app.query_one("#popup-prev", Button), app.query_one("#popup-next", Button)
            # Beta has only a finished decision, so it is skipped like the sidebar's disabled D button
            assert str(following.tooltip) == "다음 project: Gamma"
            assert str(previous.tooltip) == "이전 project: Gamma"
            editor = app.query_one("#answer", TextArea)
            editor.text = "alpha 초안"
            await pilot.click("#popup-next")
            await wait_until(pilot, lambda: app.project_id == "Gamma" and "D-20261107-03" in app.decisions)
            assert str(app.query_one("#popup-project", Static).content) == "Gamma"
            assert editor.text == "" and not editor.disabled
            assert [str(button.label) for button in app.query("#decision-list Button")] == [
                "▶ D-20261107-03 대기 gamma question"]
            editor.text = "gamma 초안"
            await pilot.click("#popup-prev")
            await wait_until(pilot, lambda: app.project_id == "Alpha" and "D-20261107-01" in app.decisions)
            assert editor.text == "alpha 초안"
            await pilot.click("#popup-next")
            await wait_until(pilot, lambda: app.project_id == "Gamma" and "D-20261107-03" in app.decisions)
            assert editor.text == "gamma 초안"
            assert app.is_running

    asyncio.run(check())


def test_decision_window_send_uses_the_project_it_is_showing(tmp_path):
    board = _three_projects(tmp_path)
    sent = []
    app = PopupApp(str(board.config), "Alpha", load=False,
                   answer_sender=lambda *args: sent.append(args) or {"ok": False, "error": {"message": "x"}})

    async def check():
        async with app.run_test(size=(100, 36)) as pilot:
            await app.apply_snapshot(model.snapshot(board.config))
            await pilot.click("#popup-next")
            await wait_until(pilot, lambda: app.project_id == "Gamma" and app.decide_id == "D-20261107-03")
            app.query_one("#answer", TextArea).text = "A"
            app.action_send()
            await wait_until(pilot, lambda: bool(sent))
            assert sent == [(str(board.config), "Gamma", "D-20261107-03", "A")]

    asyncio.run(check())


def test_decision_window_learns_the_other_projects_after_it_is_up(tmp_path):
    board = _three_projects(tmp_path)
    reads = []

    def navigation(config):
        reads.append(config)
        return model.snapshot(config)
    app = PopupApp(str(board.config), "Alpha", load=False, navigation_reader=navigation)

    async def check():
        async with app.run_test(size=(100, 36), tooltips=True) as pilot:
            await app.apply_snapshot(model.popup_snapshot(board.config, "Alpha"))      # the project alone
            await wait_until(pilot, lambda: str(app.query_one("#popup-next", Button).tooltip) == "다음 project: Gamma")
            assert reads == [str(board.config)]
            assert [item for item in app.eligible] and app.eligible == {"Alpha", "Gamma"}

    asyncio.run(check())


# BOARD-025: a click on an item while a Board window is open tells that window what to show.
def _tell(link, **request):
    return asyncio.to_thread(window_link.send, link, request)


def test_an_open_cr_window_shows_another_project_and_state_when_told(tmp_path, request):
    board = _three_projects(tmp_path)
    link, marked = click_socket(request), []
    app = CRPopupApp(str(board.config), "Alpha", "open", load=False, link=link, mark_link=marked.append)

    async def check():
        async with app.run_test(size=(90, 30)) as pilot:
            await wait_until(pilot, lambda: marked == [link])             # it says it listens once it does
            assert str(app.query_one("#cr-title", Static).content) == "읽는 중…"      # before the first read
            await app.apply_snapshot(model.popup_snapshot(board.config, "Alpha", True))
            assert app.project_id == "Alpha" and app.selected_id == "AAA-001"
            assert await _tell(link, kind="cr", project="Gamma", state="in-progress") == {"ok": True}
            await wait_until(pilot, lambda: app.project_id == "Gamma" and app.selected_id == "GGG-001")
            assert str(app.query_one("#cr-project", Static).content) == "Gamma"
            assert str(app.query_one("#cr-title", Static).content) == "Open 0, Todo 0, In-Progress 1, Done 1"
            assert app.is_running
            assert [str(row.label)[2:9] for row in app.query(".list-item")] == ["GGG-001"]    # its Done is folded

    asyncio.run(check())
    assert not os.path.exists(link)                                        # the socket goes with the window


def test_an_open_cr_window_shows_that_it_is_reading_until_the_list_arrives(tmp_path, request, monkeypatch):
    board = _three_projects(tmp_path)
    link, release = click_socket(request), threading.Event()
    app = CRPopupApp(str(board.config), "Alpha", "open", link=link)
    read = model.popup_snapshot

    def slow(*args):
        release.wait(command_timeout())
        return read(*args)

    async def check():
        async with app.run_test(size=(90, 30)) as pilot:
            await wait_until(pilot, lambda: os.path.exists(link))
            await _tell(link, kind="cr", project="Beta", state="todo")
            await wait_until(pilot, lambda: app.project_id == "Beta")
            await wait_until(pilot, lambda: str(app.query_one("#cr-title", Static).content) == "읽는 중…")
            release.set()
            await wait_until(pilot, lambda: app.selected_id == "BBB-001")

    monkeypatch.setattr(model, "popup_snapshot", slow)
    try:
        asyncio.run(check())
    finally:
        release.set()


@pytest.mark.parametrize("request_", [
    {"kind": "decision", "project": "Alpha", "decision": None},       # a decision request to a CR window
    {"kind": "cr", "project": "Alpha", "state": "done"},              # not a state a click names
    {"kind": "cr", "project": 3, "state": "open"},
])
def test_a_cr_window_refuses_what_it_cannot_show(tmp_path, request, request_):
    board = _three_projects(tmp_path)
    link = click_socket(request)
    app = CRPopupApp(str(board.config), "Alpha", "open", load=False, link=link)

    async def check():
        async with app.run_test(size=(90, 30)) as pilot:
            await wait_until(pilot, lambda: os.path.exists(link))
            result = await _tell(link, **request_)
            assert result["ok"] is False and result["code"] == "invalid"
            assert app.project_id == "Alpha"

    asyncio.run(check())


def test_an_open_decision_window_shows_another_project_when_told_and_keeps_the_draft(tmp_path, request):
    board = _three_projects(tmp_path)
    link, marked = click_socket(request), []
    app = PopupApp(str(board.config), "Alpha", load=False, link=link, mark_link=marked.append)

    async def check():
        async with app.run_test(size=(100, 36)) as pilot:
            await wait_until(pilot, lambda: marked == [link])
            await app.apply_snapshot(model.snapshot(board.config))
            editor = app.query_one("#answer", TextArea)
            editor.text = "alpha 초안"
            assert await _tell(link, kind="decision", project="Gamma", decision=None) == {"ok": True}
            await wait_until(pilot, lambda: app.project_id == "Gamma" and "D-20261107-03" in app.decisions)
            assert str(app.query_one("#popup-project", Static).content) == "Gamma" and editor.text == ""
            assert app.decide_id == "D-20261107-03"
            await _tell(link, kind="decision", project="Alpha", decision="D-20261107-01")
            await wait_until(pilot, lambda: app.project_id == "Alpha" and "D-20261107-01" in app.decisions)
            assert editor.text == "alpha 초안"                           # an unsent answer stays with its decision
            assert app.is_running

    asyncio.run(check())
    assert not os.path.exists(link)


def test_a_decision_window_does_not_change_what_it_shows_while_an_answer_is_sent(tmp_path, request):
    board = _three_projects(tmp_path)
    link, release, sent = click_socket(request), threading.Event(), []

    def sender(*args):
        sent.append(args)
        release.wait(command_timeout())
        return {"ok": False, "error": {"message": "x"}}
    app = PopupApp(str(board.config), "Alpha", load=False, link=link, answer_sender=sender)

    async def check():
        async with app.run_test(size=(100, 36)) as pilot:
            await wait_until(pilot, lambda: os.path.exists(link))
            await app.apply_snapshot(model.snapshot(board.config))
            app.query_one("#answer", TextArea).text = "A"
            app.action_send()
            await wait_until(pilot, lambda: bool(sent))
            result = await _tell(link, kind="decision", project="Gamma", decision=None)
            assert result["ok"] is False and result["code"] == "busy"
            assert app.project_id == "Alpha"
            release.set()

    try:
        asyncio.run(check())
    finally:
        release.set()
    assert sent == [(str(board.config), "Alpha", "D-20261107-01", "A")]


def test_a_decision_window_refuses_what_it_cannot_show(tmp_path, request):
    board = _three_projects(tmp_path)
    link = click_socket(request)
    app = PopupApp(str(board.config), "Alpha", load=False, link=link)

    async def check():
        async with app.run_test(size=(100, 36)) as pilot:
            await wait_until(pilot, lambda: os.path.exists(link))
            for bad in ({"kind": "cr", "project": "Alpha", "state": "open"},
                        {"kind": "decision", "project": "Alpha", "decision": 7}):
                result = await _tell(link, **bad)
                assert result["ok"] is False and result["code"] == "invalid"
            assert app.project_id == "Alpha"

    asyncio.run(check())


def test_a_cr_window_reads_the_other_projects_once_it_is_up_so_the_next_item_is_found_read(tmp_path, monkeypatch):
    board = _three_projects(tmp_path)
    calls, read = [], model.popup_snapshot

    def record(config, project_id=None, done=False, only=None):
        calls.append((project_id, done, only))
        return read(config, project_id, done, only)
    monkeypatch.setattr(model, "popup_snapshot", record)
    app = CRPopupApp(str(board.config), "Alpha", "open")

    async def check():
        async with app.run_test(size=(90, 30)) as pilot:
            await wait_until(pilot, lambda: len(calls) == 3)
            await pilot.pause(0.2)
            assert app.project_id == "Alpha" and app.selected_id == "AAA-001"

    asyncio.run(check())
    # the window's own project first (the list it shows), then the others once each; only the CRs, with done
    assert calls == [("Alpha", True, model.ONLY_CRS), ("Beta", True, model.ONLY_CRS), ("Gamma", True, model.ONLY_CRS)]


def test_cr_head_is_whole_sections_of_a_long_cr_and_none_for_a_short_one():
    from project_board.tui import cr_head
    section = "## Part\n\n" + "line\n\n" * 12
    source = "# T\n\n- Opened: x\n\n" + section * 6
    head = cr_head(source)
    assert head is not None and head.startswith("# T") and source.startswith(head) and head.endswith("\n")
    assert len(head.splitlines()) >= 29 and source[len(head):].lstrip("\n").startswith("## Part")
    assert cr_head("# T\n\n## Part\n\ntext\n") is None
    fenced = "# T\n\n" + "```\n" + "## not a heading\n" * 40 + "```\n\n" + "text\n" * 40
    assert cr_head(fenced) is None                                    # a heading inside a fence is not a section


def test_a_long_cr_shows_its_first_screen_before_the_whole_document(tmp_path):
    board = Board(tmp_path)
    base = board.project("Alpha", seats=0)
    path = board.cr(base, "open", "AAA-001", "alpha open")
    body = "".join(f"## Part {number}\n\n" + "line\n\n" * 12 for number in range(8))
    path.write_text(path.read_text(encoding="utf-8") + "\n" + body, encoding="utf-8")
    source = path.read_text(encoding="utf-8")
    app = CRPopupApp(str(board.config), "Alpha", "open", load=False)
    seen = []
    painted = app._painted

    async def record():
        seen.append([widget.source for widget in app.query(Markdown)])
        await painted()
    app._painted = record

    async def check():
        async with app.run_test(size=(100, 30)) as pilot:
            await app.apply_snapshot(model.popup_snapshot(board.config, "Alpha", True))
            await wait_until(pilot, lambda: [widget.source for widget in app.query(Markdown)] == [source])
            assert len(seen) == 1 and len(seen[0]) == 1 and 0 < len(seen[0][0]) < len(source)
            assert source.startswith(seen[0][0])                       # the first screen was the head of the document

    asyncio.run(check())


def test_done_rows_and_their_titles_are_not_made_until_the_done_group_is_unfolded(tmp_path, monkeypatch):
    """BOARD-025: a folded group costs no widgets, and nobody reads the title of a done CR that nobody sees."""
    board, base, done = _four_state_board(tmp_path)
    read = []
    original = model.done_title
    monkeypatch.setattr(model, "done_title", lambda item: read.append(item["id"]) or original(item))
    app = CRPopupApp(str(board.config), "Falcon2", "open", load=False)

    async def check():
        async with app.run_test(size=(90, 40)) as pilot:
            await app.apply_snapshot(model.popup_snapshot(board.config, "Falcon2", True))
            await pilot.pause(0.3)
            assert read == [] and len(app.query(".list-item")) == 5
            await pilot.click("#cr-group-done")
            await wait_until(pilot, lambda: sorted(read) == ["CPU-300", "CPU-301", "CPU-302"])
            await pilot.click("#cr-item-5")                                    # a done row opens its CR
            await wait_until(pilot, lambda: app.selected_id == "CPU-300")
            await pilot.click("#cr-group-done")                                # fold again: the rows stay, hidden
            await wait_until(pilot, lambda: [row.display for row in app.query(".list-item")][-3:] == [False, False, False])
            await pilot.pause(0.6)                                             # not a double click of the header
            await pilot.click("#cr-group-done")
            await wait_until(pilot, lambda: [row.display for row in app.query(".list-item")][-3:] == [True, True, True])
            assert sorted(read) == ["CPU-300", "CPU-301", "CPU-302"]            # each title was read once

    asyncio.run(check())


# BOARD-027: the cron window
def _cron_board(tmp_path, monkeypatch):
    """Falcon2 with two jobs (one ran well, one failed), Beta without a section, Gamma with one job never run."""
    board = Board(tmp_path)
    falcon, _beta, gamma = (board.project(name, seats=0) for name in ("Falcon2", "Beta", "Gamma"))
    crontab = isolate_crontab(tmp_path, monkeypatch)
    crontab.write_text(
        "0 23 * * * /home/user/nightly.sh\n"
        + cron_section("Falcon2", ("check", "정체 점검 [30분]", "13,43 * * * *", "/r/bin/agent-session check --project Falcon2 >/dev/null 2>&1"),
                       ("report", "평일 보고", "0 9 * * 1-5", "/r/bin/report --all 100\\%"))
        + cron_section("Gamma", ("sweep", "청소", "*/10 * * * *", "/r/bin/sweep")))
    cron_run(falcon, "check", "2026-11-12T01:13:20Z", True, "점검했습니다")
    cron_run(falcon, "report", "2026-11-12T00:00:00Z", False, "Leader가 없습니다", code="leader_unavailable")
    return board, crontab


def _detail(app):
    found = list(app.query("#cr-detail Static"))
    return str(found[0].content) if found else ""


async def _press(pilot, selector):
    """Click a button once its last press has finished: Textual ignores a click for 0.2 s after one (its `-active`
    effect), and a project without jobs is read faster than that."""
    await wait_until(pilot, lambda: not pilot.app.query_one(selector, Button).has_class("-active"))
    await pilot.click(selector)


def _title(app):
    return str(app.query_one("#cr-title", Static).content)


def test_the_cron_window_lists_the_jobs_and_shows_the_selected_one_whole(tmp_path, monkeypatch):
    board, _ = _cron_board(tmp_path, monkeypatch)
    app = CronPopupApp(str(board.config), "Falcon2")

    async def check():
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_until(pilot, lambda: bool(app.items))
            await wait_until(pilot, lambda: _detail(app).startswith("check\n") and app.selected_id == "check")
            assert _title(app) == "cron 2개"
            rows = _list_rows(app, ".list-item")
            assert [row[2] for row in rows] == [1, 1]
            assert rows[0][:2] == ("▶ check 정체 점검 [30분]", True)
            assert rows[1][0].startswith("  report 실패 평일 보고") and rows[1][1] is False   # the last run failed
            first = _detail(app)
            assert first.startswith("check\n정체 점검 [30분]\n")
            assert "일정      13,43 * * * *\n" in first
            following = model.cron_view(board.config, "Falcon2")["jobs"][0]
            # the time left is read at the window's own moment, so only its form is fixed here (the rule: test_model)
            assert re.search(rf"다음 실행  {following['next_run'][:10]} {following['next_run'][11:16]} \(\d+[mhd] 뒤\)\n", first)
            at = dt.datetime.fromisoformat("2026-11-12T01:13:20+00:00").astimezone().strftime("%Y-%m-%d %H:%M")
            assert f"마지막 실행 {at} 성공\n결과      점검했습니다\n" in first
            assert first.endswith("\n\n명령\n/r/bin/agent-session check --project Falcon2 >/dev/null 2>&1")
            await pilot.click("#cr-item-1")
            await wait_until(pilot, lambda: app.selected_id == "report")
            second = _detail(app)
            assert second.startswith("report\n평일 보고\n") and "일정      0 9 * * 1-5\n" in second
            assert " 실패\n결과      Leader가 없습니다\n오류 코드  leader_unavailable\n" in second
            assert second.endswith("/r/bin/report --all 100%")                    # the whole command, `%` unescaped
            assert [row[1] for row in _list_rows(app, ".list-item")] == [False, True]

    asyncio.run(check())


def test_the_cron_window_says_when_a_job_has_not_run_and_has_no_next_run(tmp_path, monkeypatch):
    board, _ = _cron_board(tmp_path, monkeypatch)
    app = CronPopupApp(str(board.config), "Gamma")
    view = model.cron_view(board.config, "Gamma")
    view["jobs"][0]["next_run"] = None                                         # a schedule that never matches

    async def check():
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_until(pilot, lambda: app.is_running and app.query_one("#cr-title", Static) is not None)
            await app.apply_view(view)
            assert _title(app) == "cron 1개"
            assert "다음 실행  없음\n마지막 실행 아직 없음\n\n명령\n/r/bin/sweep" in _detail(app)

    asyncio.run(check())


def test_the_cron_window_shows_one_line_for_a_project_without_jobs(tmp_path, monkeypatch):
    board, _ = _cron_board(tmp_path, monkeypatch)
    app = CronPopupApp(str(board.config), "Beta")

    async def check():
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_until(pilot, lambda: _detail(app) == "작업 없음")
            assert _title(app) == "cron 0개" and not list(app.query(".list-item"))
            assert not app.query_one("#cr-next", Button).disabled and app.is_running

    asyncio.run(check())


def test_the_cron_window_moves_between_every_project_and_wraps(tmp_path, monkeypatch):
    board, _ = _cron_board(tmp_path, monkeypatch)
    app = CronPopupApp(str(board.config), "Falcon2")

    async def check():
        async with app.run_test(size=(100, 30), tooltips=True) as pilot:
            await wait_until(pilot, lambda: app.selected_id == "check")
            previous, following = app.query_one("#cr-prev", Button), app.query_one("#cr-next", Button)
            assert str(previous.tooltip) == "이전 project: Gamma" and str(following.tooltip) == "다음 project: Beta"
            await _press(pilot, "#cr-next")                                       # Beta has no job: still a stop
            await wait_until(pilot, lambda: app.project_id == "Beta" and _detail(app) == "작업 없음")
            assert str(app.query_one("#cr-project", Static).content) == "Beta"
            await _press(pilot, "#cr-next")
            await wait_until(pilot, lambda: app.project_id == "Gamma" and app.selected_id == "sweep")
            assert _title(app) == "cron 1개"
            await _press(pilot, "#cr-next")                                       # past the last project: the first
            await wait_until(pilot, lambda: app.project_id == "Falcon2" and app.selected_id == "check")
            await _press(pilot, "#cr-prev")
            await wait_until(pilot, lambda: app.project_id == "Gamma")

    asyncio.run(check())


def test_the_cron_window_reads_again_only_when_it_opens_and_when_the_project_changes(tmp_path, monkeypatch):
    board, crontab = _cron_board(tmp_path, monkeypatch)
    app = CronPopupApp(str(board.config), "Falcon2")
    log = tmp_path / "crontab-calls"
    monkeypatch.setenv("FAKE_CRONTAB_LOG", str(log))

    async def check():
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_until(pilot, lambda: app.selected_id == "check")
            await pilot.pause(0.5)
            assert log.read_text().splitlines() == ["-l"]                      # the one read of the opening
            await pilot.click("#cr-next")
            await wait_until(pilot, lambda: app.project_id == "Beta")
            await pilot.pause(0.5)
            assert log.read_text().splitlines() == ["-l", "-l"]

    asyncio.run(check())


def test_the_cron_window_reports_a_crontab_it_cannot_read_and_keeps_moving(tmp_path, monkeypatch):
    board, crontab = _cron_board(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_CRONTAB_FAIL", "read")
    app = CronPopupApp(str(board.config), "Falcon2")

    async def check():
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_until(pilot, lambda: _detail(app).startswith("cron을 읽을 수 없습니다: "))
            assert _title(app) == "cron을 읽을 수 없습니다" and "simulated failure" in _detail(app)
            assert not list(app.query(".list-item"))
            assert not app.query_one("#cr-next", Button).disabled              # the registry is still read
            monkeypatch.delenv("FAKE_CRONTAB_FAIL")
            await pilot.click("#cr-next")
            await wait_until(pilot, lambda: app.project_id == "Beta" and _detail(app) == "작업 없음")
            assert app.is_running

    asyncio.run(check())


def test_a_damaged_section_of_one_project_does_not_hide_the_others(tmp_path, monkeypatch):
    board, crontab = _cron_board(tmp_path, monkeypatch)
    crontab.write_text("# >>> project-agent: Falcon2 >>>\n" + cron_section("Gamma", ("sweep", "청소", "*/10 * * * *", "/x")))
    app = CronPopupApp(str(board.config), "Falcon2")

    async def check():
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_until(pilot, lambda: "section" in _detail(app))
            assert _title(app) == "cron을 읽을 수 없습니다"
            await pilot.click("#cr-prev")                                      # Falcon2 → Gamma
            await wait_until(pilot, lambda: app.project_id == "Gamma" and app.selected_id == "sweep")

    asyncio.run(check())


def test_the_cron_window_switches_between_the_list_and_the_job_when_narrow(tmp_path, monkeypatch):
    board, _ = _cron_board(tmp_path, monkeypatch)
    app = CronPopupApp(str(board.config), "Falcon2")

    async def check():
        async with app.run_test(size=(55, 20)) as pilot:
            await wait_until(pilot, lambda: app.selected_id == "check")
            assert app.has_class("narrow") and not app.query_one("#cr-items").display
            assert app.query_one("#cr-detail").display
            await pilot.click("#cr-show-list")
            assert app.query_one("#cr-items").display and not app.query_one("#cr-detail").display
            app.query_one("#cr-item-1", Button).focus()
            await pilot.press("enter")
            await wait_until(pilot, lambda: app.selected_id == "report")
            assert app.query_one("#cr-detail").display and not app.query_one("#cr-items").display
            assert _detail(app).startswith("report\n")

    asyncio.run(check())


def test_the_cron_window_closes_with_the_button_and_escape(tmp_path, monkeypatch):
    board, _ = _cron_board(tmp_path, monkeypatch)

    async def check(close):
        app = CronPopupApp(str(board.config), "Falcon2")
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_until(pilot, lambda: app.selected_id == "check")
            await close(pilot)
            await pilot.pause()
        assert not app.is_running

    async def button(pilot):
        await pilot.click("#cr-close")

    async def escape(pilot):
        await pilot.press("escape")

    asyncio.run(check(button))
    asyncio.run(check(escape))


def test_an_open_cron_window_shows_another_project_when_told(tmp_path, request, monkeypatch):
    board, _ = _cron_board(tmp_path, monkeypatch)
    link, marked = click_socket(request), []
    app = CronPopupApp(str(board.config), "Falcon2", link=link, mark_link=marked.append)

    async def check():
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_until(pilot, lambda: marked == [link] and app.selected_id == "check")
            assert await _tell(link, kind="cron", project="Gamma", client="/dev/pts/3") == {"ok": True}
            await wait_until(pilot, lambda: app.project_id == "Gamma" and app.selected_id == "sweep")
            assert str(app.query_one("#cr-project", Static).content) == "Gamma" and _title(app) == "cron 1개"
            assert await _tell(link, kind="cron", project="Beta") == {"ok": True}
            await wait_until(pilot, lambda: app.project_id == "Beta" and _detail(app) == "작업 없음")

    asyncio.run(check())
    assert not os.path.exists(link)


@pytest.mark.parametrize("request_", [
    {"kind": "cr", "project": "Falcon2", "state": "open"},            # a CR request to a cron window
    {"kind": "decision", "project": "Falcon2", "decision": None},
    {"kind": "cron", "project": 3},
    {"kind": "cron", "project": "Falcon2", "client": 5},
])
def test_a_cron_window_refuses_what_it_cannot_show(tmp_path, request, monkeypatch, request_):
    board, _ = _cron_board(tmp_path, monkeypatch)
    link = click_socket(request)
    app = CronPopupApp(str(board.config), "Falcon2", load=False, link=link)

    async def check():
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_until(pilot, lambda: os.path.exists(link))
            result = await _tell(link, **request_)
            assert result["ok"] is False and result["code"] == "invalid"
            assert app.project_id == "Falcon2"

    asyncio.run(check())


def test_the_cr_and_decision_windows_refuse_a_cron_request(tmp_path, request):
    board = _three_projects(tmp_path)
    link = click_socket(request)
    cr = CRPopupApp(str(board.config), "Alpha", "open", load=False, link=link)

    async def check_cr():
        async with cr.run_test(size=(90, 30)) as pilot:
            await wait_until(pilot, lambda: os.path.exists(link))
            result = await _tell(link, kind="cron", project="Gamma")
            assert result["ok"] is False and result["code"] == "invalid" and cr.project_id == "Alpha"

    asyncio.run(check_cr())
    link = click_socket(request)
    decision = PopupApp(str(board.config), "Alpha", load=False, link=link)

    async def check_decision():
        async with decision.run_test(size=(100, 36)) as pilot:
            await wait_until(pilot, lambda: os.path.exists(link))
            result = await _tell(link, kind="cron", project="Gamma")
            assert result["ok"] is False and result["code"] == "invalid" and decision.project_id == "Alpha"

    asyncio.run(check_decision())
