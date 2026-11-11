"""User interactions and displayed project facts in the terminal Board."""
import asyncio
import datetime as dt
import threading

import pytest

from board_testing import Board, leader, session, wait_until
from project_board import model
from project_board.tui import CRPopupApp, CSVScreen, PopupApp
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














