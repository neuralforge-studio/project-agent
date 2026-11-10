"""Real Claude provider cost, read-only: `claude --version` and one `claude mcp serve` session
(initialize + tools/list, ListAgents, close), through the product's own MCPClient. No message is sent.
usage: python provider_probe.py REPETITIONS   (uses this checkout's tools/agent-session; needs the claude CLI)"""
import json, os, sys, time, statistics
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "agent-session"))
from agent_session.providers.common import run, executable
from agent_session.providers.mcp import MCPClient
cli = executable("claude")
rows = []
for rep in range(int(sys.argv[1])):
    t = time.perf_counter(); run([cli, "--version"], 60); v = time.perf_counter() - t
    t0 = time.perf_counter()
    client = MCPClient([cli, "mcp", "serve"], 60)
    client.__enter__(); t1 = time.perf_counter()
    result = client.tool("ListAgents", {}); t2 = time.perf_counter()
    client.__exit__(None, None, None); t3 = time.perf_counter()
    rows.append({"version": round(v, 2), "mcp_open": round(t1 - t0, 2), "list_agents": round(t2 - t1, 2), "mcp_close": round(t3 - t2, 2),
                 "total": round(t3 - t0, 2), "load": open("/proc/loadavg").read().split()[0]})
    print(json.dumps(rows[-1]), flush=True)
for key in ("version", "mcp_open", "list_agents", "mcp_close", "total"):
    print(key, "median", statistics.median(r[key] for r in rows), "max", max(r[key] for r in rows))
