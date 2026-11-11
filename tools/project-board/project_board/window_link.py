"""The line between a click and a Board window that is already open (BOARD-025).

A Board window (the CR list or the decisions) is a process that takes seconds to start on a loaded host.
Opening another item while it is open must not start it again, so the window listens on a local socket
and the click sends it what to show: one JSON object and a newline each way. `tmux_control` is the client,
`tui` the server; this module owns the message so that the two cannot drift.

Request: `{"kind": "cr" | "decision", "project": ID, "state": ..., "decision": ..., "client": NAME}`; `state`
(a CR state) belongs to a CR window and `decision` (an ID or null) to a decision window; `client` is the tmux
client that clicked (informational).
Reply: `{"ok": true}` or `{"ok": false, "code": ..., "message": ...}`; `code` is `busy` while the window
cannot change what it shows (an answer is being sent) and `invalid` for a request it does not understand.

Other languages (the Rust sidebar) use the same line; the contract, with the pane options that name the socket,
is docs/project-board-tui-plan.md, "열려 있는 창에 새 내용 알리기", and test_window_protocol.py keeps to it
without importing this module.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket as unix_socket
import stat
from typing import Awaitable, Callable

SOCKET_ENV = "PROJECT_BOARD_WINDOW_SOCKET"     # where a Board window listens (set by tmux_control when it starts one)
KINDS = ("cr", "decision")
TIMEOUT = 2
MAX_LINE = 4096

Handler = Callable[[dict], "dict | Awaitable[dict]"]


def reply(ok: bool = True, code: str | None = None, message: str | None = None) -> dict:
    return {"ok": True} if ok else {"ok": False, "code": code, "message": message}


def send(path: str, request: dict, timeout: float = TIMEOUT) -> dict:
    """Send `request` to the window that listens on `path`. OSError when nothing listens there."""
    info = os.lstat(path)
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise OSError("the Board window socket is not private")
    payload = json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n"
    with unix_socket.socket(unix_socket.AF_UNIX, unix_socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(path)
        connection.sendall(payload)
        response = b""
        while b"\n" not in response and len(response) < MAX_LINE:
            block = connection.recv(MAX_LINE)
            if not block:
                break
            response += block
    try:
        return json.loads(response.split(b"\n", 1)[0])
    except ValueError as error:
        raise OSError(f"the Board window gave no reply: {error}") from error


async def serve(path: str, handler: Handler) -> asyncio.AbstractServer:
    """Listen on `path` (owner only); `handler(request)` returns the reply (it may be a coroutine)."""

    async def receive(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            try:
                request = json.loads(await reader.readline())
                if not isinstance(request, dict):
                    raise ValueError("a request is an object")
                result = handler(request)
                if asyncio.iscoroutine(result):
                    result = await result
            except (UnicodeError, ValueError) as error:
                result = reply(False, "invalid", str(error))
            writer.write((json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))
            await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_unix_server(receive, path=path, limit=MAX_LINE)
    os.chmod(path, 0o600)
    return server


def stop(server: asyncio.AbstractServer | None, path: str | None) -> None:
    if server is not None:
        server.close()
    if path:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
