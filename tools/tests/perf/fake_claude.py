#!/usr/bin/env python3
"""A stand-in for the `claude` executable, put in front of PATH so that the product's own Claude provider code runs
unchanged against it (PERF-001). It speaks only what agent-session uses:

  claude --version                 prints a version line
  claude agents --json ...         prints []
  claude mcp serve                 an MCP server on stdin/stdout: initialize, tools/list, tools/call ListAgents and
                                   SendMessage. Like the real one it keeps running when its stdin closes, so the
                                   product's MCPClient.close waits its second and then terminates it.
  claude [--session-id|--resume ID] --settings FILE [-n NAME] [prompt]
                                   the interactive CLI: lists itself as a peer, runs the SessionStart hook of the
                                   settings file, then the Stop hook (an idle turn), then waits on stdin. SIGTERM runs
                                   the SessionEnd hook and exits with 143, as Claude 2.1.317 does.

Peers are files in $PERF_PEERS (one JSON per session: pid, name, ref, tmux locator); the environment builder writes
one for every synthetic slot. A row is listed while its pid lives. Not modelled: the real CLI's boot time (node start,
seconds), its model turns and its network use; the benchmark measures the product, not the provider.
"""
import json
import os
import signal
import subprocess
import sys
import time

PEERS = os.environ.get("PERF_PEERS", "")


def peers():
    rows = []
    for name in sorted(os.listdir(PEERS)) if PEERS and os.path.isdir(PEERS) else []:
        try:
            with open(os.path.join(PEERS, name), encoding="utf-8") as stream:
                row = json.load(stream)
            os.kill(row["pid"], 0)
        except (OSError, ValueError, KeyError):
            continue
        rows.append(row)
    return rows


def listing():
    rows = peers()
    lines = [f"{r['name']} [{r['ref']}] idle · tmux {r['tmux']}" for r in rows]
    return {"listing": "\n".join(lines), "sections": [{"kind": "sessions", "rows": [
        {"name": r["name"], "ref": r["ref"], "status": "idle"} for r in rows]}]}


def mcp_serve():
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    tools = [{"name": "ListAgents", "inputSchema": {"type": "object", "properties": {}}},
             {"name": "SendMessage", "inputSchema": {"type": "object", "required": ["to", "message"], "properties": {
                 "to": {"type": "string"}, "summary": {"type": "string"}, "message": {"type": "string"}}}}]
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        if "id" not in request:
            continue
        method, params = request.get("method"), request.get("params") or {}
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "claude", "version": "2.1.319"}}
        elif method == "tools/list":
            result = {"tools": tools}
        elif method == "tools/call" and params.get("name") == "ListAgents":
            result = {"content": [{"type": "text", "text": "listing"}], "structuredContent": listing()}
        elif method == "tools/call" and params.get("name") == "SendMessage":
            log = os.path.join(PEERS, "..", "messages.jsonl") if PEERS else os.devnull
            with open(log, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(params.get("arguments", {}), ensure_ascii=False) + "\n")
            result = {"structuredContent": {"success": True}}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32601, "message": "unsupported"}}),
                  flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
    while True:                                  # stdin closed: the real server stays until it is terminated
        time.sleep(60)


def hook(settings, event, payload):
    entries = settings.get("hooks", {}).get(event, [])
    for entry in entries:
        for item in entry.get("hooks", []):
            subprocess.run(item["command"], shell=True, input=json.dumps(payload), text=True, capture_output=True,
                           timeout=item.get("timeout", 30))


def interactive(args):
    options, rest = {}, []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in ("--session-id", "--resume", "--settings", "-n", "--name", "--append-system-prompt-file", "--model",
                   "--effort", "--permission-mode"):
            options[arg] = args[index + 1]
            index += 2
        else:
            rest.append(arg)
            index += 1
    resume = "--resume" in options
    session_id = options.get("--resume") or options.get("--session-id")
    with open(options["--settings"], encoding="utf-8") as stream:
        settings = json.load(stream)
    pane = os.environ.get("TMUX_PANE", "")
    locator = subprocess.run([os.environ["PERF_REAL_TMUX"], "display-message", "-p", "-t", pane,
                              "#{session_name}:#{window_id}.#{pane_id}"], capture_output=True, text=True).stdout.strip()
    name = options.get("-n") or options.get("--name") or "claude"
    os.makedirs(PEERS, exist_ok=True)
    row = {"pid": os.getpid(), "name": name, "ref": session_id.replace("-", "")[:6], "tmux": locator}
    with open(os.path.join(PEERS, f"{os.getpid()}.json"), "w", encoding="utf-8") as stream:
        json.dump(row, stream)
    base = {"session_id": session_id, "cwd": os.getcwd()}

    def terminate(*_):
        try:
            hook(settings, "SessionEnd", {**base, "hook_event_name": "SessionEnd", "reason": "other"})
        finally:
            os._exit(143)
    signal.signal(signal.SIGTERM, terminate)
    hook(settings, "SessionStart", {**base, "hook_event_name": "SessionStart", "source": "resume" if resume else "startup"})
    hook(settings, "Stop", {**base, "hook_event_name": "Stop", "background_tasks": [], "session_crons": []})
    for _ in sys.stdin:
        pass
    while True:
        time.sleep(60)


def main():
    args = sys.argv[1:]
    if args[:1] == ["--version"]:
        print("2.1.319 (Claude Code)")
    elif args[:1] == ["agents"]:
        print("[]")
    elif args[:2] == ["mcp", "serve"]:
        mcp_serve()
    else:
        interactive(args)


if __name__ == "__main__":
    main()
