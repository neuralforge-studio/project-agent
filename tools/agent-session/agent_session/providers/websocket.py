"""A bounded Unix-socket WebSocket client for the Codex app server."""

import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import struct

from ..errors import SessionError
from .common import deadline


class WebSocketRPC:
    MAX_HEADERS = 16384
    MAX_MESSAGE = 8 * 1024 * 1024

    def __init__(self, endpoint, timeout=30, *, client_name="agent-session"):
        if not isinstance(endpoint, str) or not endpoint.startswith("unix:///"):
            raise SessionError("invalid_endpoint", "Codex requires an absolute Unix socket endpoint.", 2)
        self.path = str(Path(endpoint[len("unix://"):]).resolve())
        self.limit = deadline(timeout)
        self.client_name = client_name
        self.sock = None
        self.pending = bytearray()
        self.request_id = 0
        self.upgraded = False

    def __enter__(self):
        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(self.limit.remaining())
            self.sock.connect(self.path)
            self._upgrade()
            self.call("initialize", {
                "clientInfo": {"name": self.client_name, "version": "1"},
                "capabilities": {"experimentalApi": True},
            })
            self.notify("initialized")
            return self
        except SessionError:
            self.close()
            raise
        except (OSError, UnicodeError, ValueError) as error:
            self.close()
            raise SessionError("provider_connection_failed", "Cannot connect to the Codex app server.", 4) from error

    def __exit__(self, *unused):
        self.close()

    def close(self):
        if self.sock is not None:
            try:
                if self.upgraded:
                    self._send_frame(b"", 8)
            except (OSError, SessionError):
                pass
            self.sock.close()
            self.sock = None

    def _send_bytes(self, value):
        self.sock.settimeout(self.limit.remaining())
        try:
            self.sock.sendall(value)
        except (OSError, TimeoutError) as error:
            raise SessionError("provider_connection_failed", "The Codex connection failed while sending.", 4) from error

    def _read_more(self):
        self.sock.settimeout(self.limit.remaining())
        try:
            value = self.sock.recv(65536)
        except (OSError, TimeoutError) as error:
            raise SessionError("provider_connection_failed", "The Codex connection failed while receiving.", 4) from error
        if not value:
            raise SessionError("provider_connection_closed", "The Codex connection closed before its reply.", 4)
        self.pending.extend(value)

    def _exact(self, size):
        while len(self.pending) < size:
            self._read_more()
        value = bytes(self.pending[:size])
        del self.pending[:size]
        return value

    def _upgrade(self):
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            "GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\nSec-WebSocket-Key: " + key
            + "\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self._send_bytes(request.encode("ascii"))
        while b"\r\n\r\n" not in self.pending:
            self._read_more()
            if len(self.pending) > self.MAX_HEADERS:
                raise SessionError("provider_protocol_error", "WebSocket headers are too large.", 4)
        header, rest = bytes(self.pending).split(b"\r\n\r\n", 1)
        self.pending[:] = rest
        if len(header) > self.MAX_HEADERS:
            raise SessionError("provider_protocol_error", "WebSocket headers are too large.", 4)
        lines = header.decode("ascii").split("\r\n")
        if not lines[0].startswith("HTTP/1.1 101 "):
            raise SessionError("provider_protocol_error", "The app server rejected WebSocket upgrade.", 4)
        fields = {}
        for line in lines[1:]:
            if ":" not in line:
                raise SessionError("provider_protocol_error", "Invalid WebSocket response headers.", 4)
            name, value = line.split(":", 1)
            fields[name.lower().strip()] = value.strip()
        expected = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
        ).digest()).decode("ascii")
        if fields.get("sec-websocket-accept") != expected:
            raise SessionError("provider_protocol_error", "Invalid WebSocket accept value.", 4)
        if fields.get("upgrade", "").lower() != "websocket":
            raise SessionError("provider_protocol_error", "Missing WebSocket upgrade header.", 4)
        if "upgrade" not in {part.strip().lower() for part in fields.get("connection", "").split(",")}:
            raise SessionError("provider_protocol_error", "Missing WebSocket connection header.", 4)
        if fields.get("sec-websocket-extensions"):
            raise SessionError("provider_protocol_error", "Unrequested WebSocket extension.", 4)
        self.upgraded = True

    def _send_frame(self, data, opcode=1):
        size = len(data)
        if size > self.MAX_MESSAGE:
            raise SessionError("provider_protocol_error", "The WebSocket message is too large.", 4)
        if opcode >= 8 and size > 125:
            raise SessionError("provider_protocol_error", "Invalid WebSocket control frame.", 4)
        if size < 126:
            header = bytes((0x80 | opcode, 0x80 | size))
        elif size <= 65535:
            header = bytes((0x80 | opcode, 0xFE)) + struct.pack("!H", size)
        else:
            header = bytes((0x80 | opcode, 0xFF)) + struct.pack("!Q", size)
        mask = os.urandom(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
        self._send_bytes(header + mask + masked)

    def _receive(self):
        chunks = bytearray()
        started = False
        while True:
            first, second = self._exact(2)
            fin = bool(first & 0x80)
            opcode = first & 0x0F
            if first & 0x70 or second & 0x80:
                raise SessionError("provider_protocol_error", "Invalid WebSocket frame flags.", 4)
            size = second & 0x7F
            if size == 126:
                size = struct.unpack("!H", self._exact(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self._exact(8))[0]
            if opcode < 8 and size + len(chunks) > self.MAX_MESSAGE:
                raise SessionError("provider_protocol_error", "The WebSocket response is too large.", 4)
            if opcode >= 8 and (not fin or size > 125):
                raise SessionError("provider_protocol_error", "Invalid WebSocket control frame.", 4)
            data = self._exact(size)
            if opcode == 9:
                self._send_frame(data, 10)
                continue
            if opcode == 10:
                continue
            if opcode == 8:
                self._send_frame(data, 8)
                raise SessionError("provider_connection_closed", "The Codex server closed its connection.", 4)
            if opcode == 1 and not started:
                started = True
            elif opcode != 0 or not started:
                raise SessionError("provider_protocol_error", "Invalid WebSocket message fragmentation.", 4)
            chunks.extend(data)
            if fin:
                try:
                    result = json.loads(chunks.decode("utf-8"))
                except (UnicodeError, ValueError) as error:
                    raise SessionError("provider_protocol_error", "Invalid JSON in the WebSocket response.", 4) from error
                if not isinstance(result, dict):
                    raise SessionError("provider_protocol_error", "The WebSocket response is not an object.", 4)
                return result

    def notify(self, method, params=None):
        message = {"method": method}
        if params is not None:
            message["params"] = params
        self._send_frame(json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def call(self, method, params):
        self.request_id += 1
        request_id = self.request_id
        request = {"id": request_id, "method": method, "params": params}
        self._send_frame(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        while True:
            reply = self._receive()
            if reply.get("id") != request_id:
                if "id" in reply and "method" in reply:
                    refusal = {"id": reply["id"], "error": {"code": -32601, "message": "This control client cannot approve requests."}}
                    self._send_frame(json.dumps(refusal, separators=(",", ":")).encode("utf-8"))
                continue
            if "error" in reply:
                error = reply["error"]
                raise SessionError("provider_rpc_error", "The Codex app server rejected the request.", 4,
                                   {"method": method, "rpc_code": error.get("code") if isinstance(error, dict) else None})
            result = reply.get("result")
            if not isinstance(result, dict):
                raise SessionError("provider_protocol_error", "The Codex result is not an object.", 4, {"method": method})
            return result

    def pages(self, method, params):
        output = []
        cursor = None
        seen = set()
        while True:
            page = self.call(method, {**params, "limit": 100, "cursor": cursor})
            if not isinstance(page.get("data"), list) or "nextCursor" not in page:
                raise SessionError("provider_protocol_error", "Invalid paginated Codex result.", 4, {"method": method})
            output.extend(page["data"])
            cursor = page["nextCursor"]
            if cursor is None:
                return output
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise SessionError("provider_protocol_error", "Invalid Codex pagination cursor.", 4, {"method": method})
            seen.add(cursor)
