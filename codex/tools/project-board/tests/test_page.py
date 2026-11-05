"""Page behavior in a real browser against a real server (skipped where Playwright is unavailable)."""
import json
import stat
import threading

import pytest

from board_testing import Board, leader
from project_board import server as board_server

sync_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def browser():
    with sync_api.sync_playwright() as pw:
        try:
            launched = pw.chromium.launch()
        except Exception as error:                       # no browser binary on this machine
            pytest.skip(f"Chromium is unavailable: {error}")
        yield launched
        launched.close()


def serve(board, monkeypatch, tmp_path, delay=0):
    record = tmp_path / "sent.json"
    stub = tmp_path / "agent-session"
    stub.write_text("#!/usr/bin/env python3\n"
                    "import json, sys, time\n"
                    "args = sys.argv[1:]\n"
                    "body = open(args[args.index('--file') + 1], encoding='utf-8').read()\n"
                    f"time.sleep({delay})\n"
                    f"json.dump({{'body': body}}, open({str(record)!r}, 'w'), ensure_ascii=False)\n"
                    "print(json.dumps({'ok': True, 'data': {'disposition': 'accepted'}, 'error': None}))\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(board_server, "AGENT_SESSION", stub)
    httpd = board_server.BoardServer(0, str(board.config))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, record


def project(board, name, decide_id):
    base = board.project(name, seats=1)
    board.state(base, {"leader": leader(), "0": {"job_id": None, "git_hash": None, "session": None}})
    board.decide(base, "open", decide_id, f"{name} 질문")


def test_project_names_that_are_object_properties_render_and_open(browser, tmp_path, monkeypatch):
    # Codex implementation review B3: any nonempty unique name is a valid project.
    board = Board(tmp_path)
    for index, name in enumerate(("constructor", "toString", "__proto__", "plain")):
        project(board, name, f"D-20261105-0{index + 1}")
    httpd, _ = serve(board, monkeypatch, tmp_path)
    try:
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"http://127.0.0.1:{httpd.server_address[1]}/")
        page.wait_for_selector('article.room[aria-label="plain"] .wb-decide')
        page.wait_for_timeout(2500)                      # one more board poll redraws every room
        names = page.locator("article.room").evaluate_all("rooms => rooms.map(r => r.getAttribute('aria-label'))")
        assert names == ["constructor", "toString", "__proto__", "plain"] and errors == []
        room = page.locator('article.room[aria-label="constructor"]')
        room.locator(".wb-decide").click()
        page.wait_for_timeout(400)
        assert room.locator(".wb-decide").get_attribute("aria-expanded") == "true"
        assert room.locator(".decide-card").count() == 1 and "constructor 질문" in room.locator(".decide-card").inner_text()
        assert page.locator('article.room[aria-label="toString"] .wb-decide').get_attribute("aria-expanded") == "false"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_text_edited_while_an_answer_is_sent_stays_as_an_unsent_draft(browser, tmp_path, monkeypatch):
    # Codex implementation review B2: an accepted send clears only the text it sent.
    board = Board(tmp_path)
    project(board, "alpha", "D-20261105-01")
    httpd, record = serve(board, monkeypatch, tmp_path, delay=2)
    try:
        page = browser.new_page()
        page.goto(f"http://127.0.0.1:{httpd.server_address[1]}/")
        room = page.locator('article.room[aria-label="alpha"]')
        room.locator(".wb-decide").click()
        area = room.locator("textarea")
        area.fill("A로 진행합니다.")
        room.locator("[data-send]").click()
        assert room.locator("[data-send]").inner_text() == "보내는 중…"
        area.fill("B로 바꿉니다.")
        page.wait_for_function("() => document.querySelector('.send-status').textContent.includes('전송했습니다')",
                               timeout=30000)
        assert area.input_value() == "B로 바꿉니다."
        assert "전송 중에 고친 내용은 보내지 않았습니다" in room.locator(".send-status").inner_text()
        assert json.loads(record.read_text(encoding="utf-8"))["body"].endswith("답변:\nA로 진행합니다.")
        page.wait_for_timeout(2500)                      # a redraw keeps the unsent draft
        assert area.input_value() == "B로 바꿉니다."
        room.locator("[data-send]").click()              # an unchanged answer is cleared after acceptance
        page.wait_for_function("() => document.querySelector('textarea').value === ''", timeout=30000)
        assert json.loads(record.read_text(encoding="utf-8"))["body"].endswith("답변:\nB로 바꿉니다.")
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_status_motion_runs_even_when_the_os_asks_for_reduced_motion(browser, tmp_path, monkeypatch):
    # User decision 2026-11-05 (plan 4.5): motion shows the state, so the board ignores the OS setting.
    from board_testing import WORKER_IDS, session
    board = Board(tmp_path)
    base = board.project("alpha", seats=1)
    board.cr(base, "in-progress", "TOOL-001")
    board.state(base, {"leader": leader(), "0": {"job_id": "TOOL-001", "git_hash": None, "session": session(0)}})
    monkeypatch.setattr(board_server.model.api, "liveness", lambda cwd, config_path=None: {
        "leader": {"session_id": leader()["session_id"], "state": "alive"},
        "0": {"session_id": WORKER_IDS[0], "state": "alive"}})
    httpd, _ = serve(board, monkeypatch, tmp_path)
    try:
        page = browser.new_context(reduced_motion="reduce").new_page()
        page.goto(f"http://127.0.0.1:{httpd.server_address[1]}/")
        page.wait_for_selector(".worker.working")
        assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches") is True
        names = page.evaluate("""() => ['.worker.working', '.leader.working', '.desk .typing i']
            .map(s => getComputedStyle(document.querySelector(s)).animationName)""")
        assert names == ["bob", "sway", "type"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_rooms_sit_in_two_columns_and_seats_in_rows_of_four(browser, tmp_path, monkeypatch):
    # BOARD-002 (plan 4.1): 2 columns wide enough for 4 seats; 1~4 seats make 1 row, 5~8 two, 9~12 three.
    # Only registered seats get a desk, and nothing scrolls sideways.
    from board_testing import session
    board = Board(tmp_path)
    counts = {"p2": 2, "p3": 3, "p4": 4, "p5": 5, "p9": 9}
    for name, seats in counts.items():
        base = board.project(name, seats=seats)
        state = {"leader": leader()}
        for index in range(seats):
            state[str(index)] = {"job_id": None, "git_hash": None, "session": None}
        state["0"] = {"job_id": "TOOL-001", "git_hash": None, "session": session(0)}
        board.cr(base, "in-progress", "TOOL-001")
        board.state(base, state)
    httpd, _ = serve(board, monkeypatch, tmp_path)
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"http://127.0.0.1:{httpd.server_address[1]}/")
        page.wait_for_selector('article.room[aria-label="p9"] .desk')

        def rooms():
            return page.evaluate("""() => [...document.querySelectorAll('article.room')].map(room => {
                const box = e => e.getBoundingClientRect(), floor = room.querySelector('.floor'), f = box(floor);
                const desks = [...room.querySelectorAll('.floor > .desk:not(.lead)')];
                const inside = [...room.querySelectorAll('.floor > *')].every(e => {
                    const b = box(e); return b.left >= f.left - 1 && b.right <= f.right + 1 && b.bottom <= f.bottom + 1; });
                const rows = {}; desks.forEach(d => { const t = d.style.top; rows[t] = (rows[t] || 0) + 1; });
                return { name: room.getAttribute('aria-label'), left: box(room).left, top: box(room).top, desks: desks.length,
                         perRow: Object.values(rows), inside,
                         scrolls: room.querySelector('.floor-scroll').scrollWidth > room.querySelector('.floor-scroll').clientWidth };
            })""")

        wide = {r["name"]: r for r in rooms()}
        assert {n: r["desks"] for n, r in wide.items()} == counts                       # no empty desks beyond the registered seats
        assert {n: len(r["perRow"]) for n, r in wide.items()} == {"p2": 1, "p3": 1, "p4": 1, "p5": 2, "p9": 3}
        assert all(max(r["perRow"]) <= 4 and r["inside"] and not r["scrolls"] for r in wide.values())
        assert wide["p5"]["perRow"] == [4, 1] and wide["p9"]["perRow"] == [4, 4, 1]
        assert wide["p2"]["top"] == wide["p3"]["top"] and wide["p2"]["left"] < wide["p3"]["left"]      # 2 columns, registration order
        assert wide["p4"]["top"] > wide["p2"]["top"] and wide["p4"]["left"] == wide["p2"]["left"]
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")

        room = page.locator('article.room[aria-label="p5"]')
        room.locator(".station").click()                                                 # the drawer opens as before
        page.wait_for_timeout(400)
        assert room.locator(".station").get_attribute("aria-expanded") == "true"
        assert room.locator('[data-panel="seat"]').is_visible() and "TOOL-001" in room.locator('[data-panel="seat"]').inner_text()

        page.set_viewport_size({"width": 900, "height": 900})                            # narrow: back to one column
        page.wait_for_timeout(300)
        narrow = rooms()
        assert len({r["left"] for r in narrow}) == 1 and all(r["inside"] and not r["scrolls"] for r in narrow)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    finally:
        httpd.shutdown()
        httpd.server_close()
