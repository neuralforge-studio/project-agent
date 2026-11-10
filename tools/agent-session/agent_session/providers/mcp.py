"""On-demand Claude MCP calls without a persistent relay."""

import json
import os
import select
import selectors
import subprocess

from ..errors import SessionError
from .common import clean_env, deadline


class MCPClient:
    MAX_LINE = 8 * 1024 * 1024

    def __init__(self, argv, timeout=30):
        self.argv = [str(part) for part in argv]
        self.limit = deadline(timeout)
        self.process = None
        self.selector = None
        self.pending = bytearray()
        self.counter = 0
        self.schemas = {}
        self.unreaped_pid = None
        self.grace = 1                 # seconds `close` waits for the server to end after its input closes

    def __enter__(self):
        try:
            self.process = subprocess.Popen(
                self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=clean_env(), start_new_session=True,
                bufsize=0,
            )
            os.set_blocking(self.process.stdin.fileno(), False)
            self.selector = selectors.DefaultSelector()
            self.selector.register(self.process.stdout, selectors.EVENT_READ)
            self.call("initialize", {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "agent-session", "version": "1"},
            })
            self._write({"jsonrpc": "2.0", "method": "notifications/initialized"})
            result = self.call("tools/list", {})
            tools = result.get("tools")
            if not isinstance(tools, list):
                raise SessionError("provider_protocol_error", "Claude MCP did not return tools.", 4)
            self.schemas = {tool["name"]: tool.get("inputSchema", {}) for tool in tools if isinstance(tool, dict) and isinstance(tool.get("name"), str)}
            if not {"ListAgents", "SendMessage"}.issubset(self.schemas):
                raise SessionError("provider_protocol_unsupported", "Claude MCP lacks cross-session tools.", 4)
            return self
        except SessionError as error:
            self.close()
            self._note_unreaped(error)
            raise
        except OSError as error:
            self.close()
            failure = SessionError("provider_command_failed", "Cannot start Claude MCP.", 5)
            self._note_unreaped(failure)
            raise failure from error

    def __exit__(self, kind, error, trace):
        self.close()
        if isinstance(error, SessionError):
            self._note_unreaped(error)

    def _note_unreaped(self, error):
        if self.unreaped_pid is not None:
            error.details.setdefault("unreaped_pid", self.unreaped_pid)

    def close(self):
        if self.selector is not None:
            self.selector.close()
        if self.process is not None:
            if self.process.stdin and not self.process.stdin.closed:
                self.process.stdin.close()
            try:
                self.process.wait(timeout=self.grace)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    try:
                        self.process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        # Cleanup must not replace the error that ended the call; keep the pid as evidence.
                        self.unreaped_pid = self.process.pid
            if self.process.stdout:
                self.process.stdout.close()
            self.process = None

    def _write(self, message):
        self.limit.remaining()
        try:
            value = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
            offset = 0
            fd = self.process.stdin.fileno()
            while offset < len(value):
                if not select.select([], [fd], [], self.limit.remaining())[1]:
                    raise SessionError("provider_timeout", "Claude MCP did not read before the deadline.", 4)
                try:
                    offset += os.write(fd, value[offset:])
                except BlockingIOError:
                    continue
        except (OSError, BrokenPipeError) as error:
            raise SessionError("provider_connection_closed", "Claude MCP closed its input.", 4) from error

    def _line(self):
        while b"\n" not in self.pending:
            if not self.selector.select(self.limit.remaining()):
                raise SessionError("provider_timeout", "Claude MCP did not reply before the deadline.", 4)
            value = os.read(self.process.stdout.fileno(), 65536)
            if not value:
                raise SessionError("provider_connection_closed", "Claude MCP closed before replying.", 4)
            self.pending.extend(value)
            if len(self.pending) > self.MAX_LINE:
                raise SessionError("provider_protocol_error", "Claude MCP reply is too large.", 4)
        line, remaining = self.pending.split(b"\n", 1)
        self.pending[:] = remaining
        try:
            value = json.loads(line)
        except (ValueError, UnicodeError) as error:
            raise SessionError("provider_protocol_error", "Invalid JSON from Claude MCP.", 4) from error
        if not isinstance(value, dict):
            raise SessionError("provider_protocol_error", "Claude MCP reply is not an object.", 4)
        return value

    def call(self, method, params):
        self.counter += 1
        request_id = self.counter
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            reply = self._line()
            if reply.get("id") != request_id:
                if "id" in reply and "method" in reply:
                    self._write({"jsonrpc": "2.0", "id": reply["id"], "error": {"code": -32601, "message": "Unsupported client request."}})
                continue
            if "error" in reply:
                raise SessionError("provider_rpc_error", "Claude MCP rejected the request.", 4, {"method": method})
            result = reply.get("result")
            if not isinstance(result, dict):
                raise SessionError("provider_protocol_error", "Invalid Claude MCP result.", 4)
            return result

    def tool(self, name, arguments):
        schema = self.schemas.get(name)
        if not isinstance(schema, dict):
            raise SessionError("provider_protocol_unsupported", f"Claude MCP lacks {name}.", 4)
        properties = schema.get("properties", {})
        if not set(schema.get("required", [])).issubset(arguments):
            raise SessionError("provider_protocol_unsupported", f"Unsupported {name} input contract.", 4)
        if schema.get("additionalProperties") is False and not set(arguments).issubset(properties):
            raise SessionError("provider_protocol_unsupported", f"Unsupported {name} input fields.", 4)
        for key, value in arguments.items():
            expected = properties.get(key, {}).get("type")
            if expected == "string" and not isinstance(value, str):
                raise SessionError("invalid_provider_input", f"Invalid {name} field {key}.", 2)
        result = self.call("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise SessionError("provider_tool_rejected", f"Claude rejected {name}.", 4)
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        blocks = result.get("content", [])
        text = "\n".join(block.get("text", "") for block in blocks if isinstance(block, dict) and block.get("type") == "text")
        try:
            value = json.loads(text)
        except ValueError:
            return {"message": text}
        if not isinstance(value, dict):
            raise SessionError("provider_protocol_error", "Claude MCP tool result is not an object.", 4)
        return value
