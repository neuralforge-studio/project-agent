"""BOARD-025: the line between a click and an open Board window, as a client in another language sees it.

docs/project-board-tui-plan.md ("열려 있는 창에 새 내용 알리기") is the contract. The client here is written
from that text with a plain socket and plain JSON, and imports nothing of `window_link`, so a change of the
Python message that the Rust sidebar could not follow fails here.
"""
import asyncio
import json
import os
import socket
import stat
import threading

import pytest

from board_testing import Board, click_socket, wait_until
from project_board import model
from project_board.tui import CRPopupApp, PopupApp
from textual.widgets import Static, TextArea


def ask(path, line: bytes):
    """What a client does: connect, write one line, read one line."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(5)
        connection.connect(path)
        connection.sendall(line)
        reply = b""
        while not reply.endswith(b"\n"):
            block = connection.recv(4096)
            assert block, "the window closed the connection without a reply line"
            reply += block
    assert reply.count(b"\n") == 1
    return json.loads(reply)


def board(tmp_path):
    board = Board(tmp_path)
    alpha = board.project("Alpha", seats=0)
    board.cr(alpha, "open", "AAA-001", "alpha open")
    board.decide(alpha, "open", "D-20261107-01", "alpha question")
    gamma = board.project("Gamma", seats=0)
    board.cr(gamma, "in-progress", "GGG-001", "gamma working")
    board.decide(gamma, "open", "D-20261107-03", "gamma question")
    return board


def test_the_socket_of_a_window_is_for_its_owner_only(tmp_path, request):
    link = click_socket(request)
    app = CRPopupApp(str(board(tmp_path).config), "Alpha", "open", load=False, link=link)

    async def check():
        async with app.run_test(size=(90, 30)) as pilot:
            await wait_until(pilot, lambda: os.path.exists(link))
            info = os.lstat(link)
            assert stat.S_ISSOCK(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600 and info.st_uid == os.getuid()

    asyncio.run(check())


def test_a_cr_window_follows_the_documented_request_and_reply(tmp_path, request):
    data = board(tmp_path)
    link = click_socket(request)
    app = CRPopupApp(str(data.config), "Alpha", "open", load=False, link=link)

    async def check():
        async with app.run_test(size=(90, 30)) as pilot:
            await wait_until(pilot, lambda: os.path.exists(link))
            line = b'{"kind": "cr", "project": "Gamma", "state": "in-progress", "client": "/dev/pts/3"}\n'
            assert await asyncio.to_thread(ask, link, line) == {"ok": True}
            await wait_until(pilot, lambda: app.project_id == "Gamma" and app.selected_id == "GGG-001")
            assert str(app.query_one("#cr-project", Static).content) == "Gamma"
            # a client that names no tmux client is served as well (it is informational)
            assert await asyncio.to_thread(ask, link, b'{"kind":"cr","project":"Alpha","state":"open"}\n') == {"ok": True}
            await wait_until(pilot, lambda: app.project_id == "Alpha")
            for bad in (b'{"kind": "decision", "project": "Alpha", "decision": null}\n',   # the other kind
                        b'{"kind": "cr", "project": "Alpha", "state": "done"}\n',
                        b'{"kind": "cr", "project": "Alpha", "state": "open", "client": 5}\n',
                        b'[1]\n', b'not json\n'):
                reply = await asyncio.to_thread(ask, link, bad)
                assert reply["ok"] is False and reply["code"] == "invalid" and isinstance(reply["message"], str), bad
            assert app.project_id == "Alpha" and app.is_running

    asyncio.run(check())
    assert not os.path.exists(link)                       # the window removes its socket when it ends


def test_a_decision_window_follows_the_documented_request_and_reply(tmp_path, request):
    data = board(tmp_path)
    link = click_socket(request)
    release, sent = threading.Event(), []

    def sender(*args):
        sent.append(args)
        release.wait(10)
        return {"ok": False, "error": {"message": "x"}}
    app = PopupApp(str(data.config), "Alpha", load=False, link=link, answer_sender=sender)

    async def check():
        async with app.run_test(size=(100, 36)) as pilot:
            await wait_until(pilot, lambda: os.path.exists(link))
            await app.apply_snapshot(model.snapshot(data.config))
            line = b'{"kind": "decision", "project": "Gamma", "decision": null, "client": "/dev/pts/3"}\n'
            assert await asyncio.to_thread(ask, link, line) == {"ok": True}
            await wait_until(pilot, lambda: app.project_id == "Gamma" and app.decide_id == "D-20261107-03")
            line = b'{"kind": "decision", "project": "Alpha", "decision": "D-20261107-01", "client": "/dev/pts/3"}\n'
            assert await asyncio.to_thread(ask, link, line) == {"ok": True}
            await wait_until(pilot, lambda: app.project_id == "Alpha" and app.decide_id == "D-20261107-01"
                             and "D-20261107-01" in app.decisions)
            for bad in (b'{"kind": "cr", "project": "Alpha", "state": "open"}\n',
                        b'{"kind": "decision", "project": "Alpha", "decision": 7}\n'):
                reply = await asyncio.to_thread(ask, link, bad)
                assert reply["ok"] is False and reply["code"] == "invalid"
            # while an answer is being sent the window keeps what it shows and says so
            app.query_one("#answer", TextArea).text = "A"
            app.action_send()
            await wait_until(pilot, lambda: bool(sent))
            reply = await asyncio.to_thread(ask, link, b'{"kind": "decision", "project": "Gamma", "decision": null}\n')
            assert reply["ok"] is False and reply["code"] == "busy" and app.project_id == "Alpha"
            release.set()

    try:
        asyncio.run(check())
    finally:
        release.set()
    assert not os.path.exists(link)
