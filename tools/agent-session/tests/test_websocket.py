import base64
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import socket
import struct
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_session.errors import SessionError
from agent_session.providers.websocket import WebSocketRPC
from wait_limit import command_timeout


class Wire:
    def __init__(self, conn):
        self.conn = conn
        self.pending = bytearray()

    def read(self, size):
        while len(self.pending) < size:
            data = self.conn.recv(65536)
            if not data:
                raise EOFError
            self.pending.extend(data)
        output = bytes(self.pending[:size])
        del self.pending[:size]
        return output

    def accept(self, bad_accept=False):
        while b"\r\n\r\n" not in self.pending:
            self.pending.extend(self.conn.recv(4096))
        request, remaining = self.pending.split(b"\r\n\r\n", 1)
        self.pending[:] = remaining
        headers = dict(line.split(": ", 1) for line in request.decode().split("\r\n")[1:])
        assert headers["Upgrade"] == "websocket"
        key = headers["Sec-WebSocket-Key"]
        assert len(base64.b64decode(key)) == 16
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        if bad_accept:
            accept = "wrong"
        self.conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + accept + "\r\n\r\n").encode())

    def frame(self):
        first, second = self.read(2)
        assert second & 128, "All client frames must be masked"
        length = second & 127
        if length == 126:
            length = struct.unpack("!H", self.read(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self.read(8))[0]
        mask = self.read(4)
        data = self.read(length)
        return first & 15, bytes(value ^ mask[index % 4] for index, value in enumerate(data))

    def message(self):
        opcode, data = self.frame()
        assert opcode == 1
        return json.loads(data)

    def send(self, data, *, opcode=1, fin=True):
        if isinstance(data, dict):
            data = json.dumps(data).encode()
        length = len(data)
        header = bytes(((128 if fin else 0) | opcode,))
        if length < 126:
            header += bytes((length,))
        elif length <= 65535:
            header += b"\x7e" + struct.pack("!H", length)
        else:
            header += b"\x7f" + struct.pack("!Q", length)
        self.conn.sendall(header + data)

    def initialize(self):
        message = self.message()
        assert message["method"] == "initialize"
        assert message["params"]["capabilities"]["experimentalApi"] is True
        self.send({"id": message["id"], "result": {"userAgent": "fixture"}})
        assert self.message() == {"method": "initialized"}


@contextmanager
def server(tmp_path, handler):
    path = tmp_path / "rpc.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen()
    listener.settimeout(command_timeout())
    errors = []

    def worker():
        try:
            conn, _ = listener.accept()
            with conn:
                conn.settimeout(command_timeout())
                handler(Wire(conn))
        except Exception as error:
            errors.append(error)
        finally:
            listener.close()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        yield "unix://" + str(path)
    finally:
        thread.join(command_timeout())
        assert not thread.is_alive(), "The fixture did not finish"
        if errors:
            raise errors[0]


def test_masked_initialize_and_fragmented_response_with_ping(tmp_path):
    def handler(wire):
        wire.accept()
        wire.initialize()
        request = wire.message()
        assert request["method"] == "thread/read"
        result = json.dumps({"id": request["id"], "result": {"thread": {"id": "expected"}}}).encode()
        wire.send(result[:13], fin=False)
        wire.send(b"check", opcode=9)
        assert wire.frame() == (10, b"check")
        wire.send(result[13:], opcode=0)
        assert wire.frame()[0] == 8

    with server(tmp_path, handler) as endpoint:
        with WebSocketRPC(endpoint, 2) as rpc:
            assert rpc.call("thread/read", {"threadId": "expected"}) == {"thread": {"id": "expected"}}


def test_pagination_reads_every_page(tmp_path):
    def handler(wire):
        wire.accept()
        wire.initialize()
        first = wire.message()
        assert first["params"]["cursor"] is None
        wire.send({"id": first["id"], "result": {"data": [{"id": "one"}], "nextCursor": "next"}})
        second = wire.message()
        assert second["params"]["cursor"] == "next"
        wire.send({"id": second["id"], "result": {"data": [{"id": "two"}], "nextCursor": None}})
        assert wire.frame()[0] == 8

    with server(tmp_path, handler) as endpoint:
        with WebSocketRPC(endpoint, 2) as rpc:
            assert rpc.pages("thread/queue/list", {"threadId": "same"}) == [{"id": "one"}, {"id": "two"}]


def test_repeated_cursor_is_an_error(tmp_path):
    def handler(wire):
        wire.accept()
        wire.initialize()
        for _ in range(2):
            request = wire.message()
            wire.send({"id": request["id"], "result": {"data": [], "nextCursor": "same"}})
        assert wire.frame()[0] == 8

    with server(tmp_path, handler) as endpoint:
        with pytest.raises(SessionError, match="pagination"):
            with WebSocketRPC(endpoint, 2) as rpc:
                rpc.pages("thread/queue/list", {"threadId": "same"})


def test_rejects_bad_handshake(tmp_path):
    def handler(wire):
        wire.accept(bad_accept=True)
        # The client closes its rejected connection without sending JSON-RPC.
        try:
            assert wire.frame()[0] == 8
        except EOFError:
            pass

    with server(tmp_path, handler) as endpoint:
        with pytest.raises(SessionError, match="accept"):
            with WebSocketRPC(endpoint, 2):
                pytest.fail("An invalid handshake was accepted")


@pytest.mark.parametrize("mode", ["large", "continuation", "masked", "truncated"])
def test_rejects_invalid_or_truncated_frames(tmp_path, mode):
    def handler(wire):
        wire.accept()
        wire.initialize()
        wire.message()
        if mode == "large":
            wire.conn.sendall(b"\x81\x7f" + struct.pack("!Q", WebSocketRPC.MAX_MESSAGE + 1))
        elif mode == "continuation":
            wire.send(b"{}", opcode=0)
        elif mode == "masked":
            wire.conn.sendall(b"\x81\x82xxxxxx")
        else:
            wire.conn.sendall(b"\x81\x05ab")
            return
        try:
            wire.frame()
        except (EOFError, ConnectionResetError):
            pass

    with server(tmp_path, handler) as endpoint:
        with pytest.raises(SessionError):
            with WebSocketRPC(endpoint, 2) as rpc:
                rpc.call("thread/read", {"threadId": "same"})


def test_rpc_error_is_not_an_empty_success(tmp_path):
    def handler(wire):
        wire.accept()
        wire.initialize()
        request = wire.message()
        wire.send({"id": request["id"], "error": {"code": -32601, "message": "Not supported"}})
        assert wire.frame()[0] == 8

    with server(tmp_path, handler) as endpoint:
        with pytest.raises(SessionError) as caught:
            with WebSocketRPC(endpoint, 2) as rpc:
                rpc.call("thread/backgroundTerminals/list", {"threadId": "same"})
        assert caught.value.code == "provider_rpc_error"
        assert caught.value.details["method"] == "thread/backgroundTerminals/list"


def test_rejects_non_unix_endpoint():
    with pytest.raises(SessionError) as caught:
        WebSocketRPC("ws://localhost:1234")
    assert caught.value.exit_code == 2
