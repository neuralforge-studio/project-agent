"""One process of the benchmark: import the Board model of the tools tree PERF_TOOLS, then time snapshot / liveness /
context reads. The per-read spawn counts come from the PATH shims' log (counting pass only).
usage: python board_model_probe.py CONFIG"""
import json, os, resource, sys, time
sys.path.insert(0, os.path.join(os.environ["PERF_TOOLS"], "project-board"))
LOG = os.environ.get("PERF_SPAWN_LOG")        # set in the counting pass only

def counts():
    c = {}
    for line in (open(LOG).read().splitlines() if LOG and os.path.exists(LOG) else []):
        p = line.split("\t")
        if p[0] == "spawn":
            c[p[1]] = c.get(p[1], 0) + 1
    return c

def cpu():
    """user+sys of this process and of the children it has waited for."""
    own, kids = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return own.ru_utime + own.ru_stime + kids.ru_utime + kids.ru_stime

def lap(name, fn, *a):
    before = counts(); c0 = cpu(); t = time.perf_counter(); r = fn(*a); d = time.perf_counter() - t
    c1 = cpu()
    after = counts()
    delta = {k: after.get(k, 0) - before.get(k, 0) for k in after if after.get(k, 0) != before.get(k, 0)}
    out[name] = {"s": round(d, 3), "cpu": round(c1 - c0, 4), "spawns": delta}
    return r

out = {}
t0, c0 = time.perf_counter(), cpu()
from project_board import model, tmux_control
out["import"] = round(time.perf_counter() - t0, 3)
out["import_cpu"] = round(cpu() - c0, 4)
config = sys.argv[1]
for i in (1, 2):                      # the first read parses every file, the second finds them unchanged
    lap(f"snapshot{i}", model.snapshot, config)
live = lap("liveness1", model.liveness, config)       # once: it takes minutes in a large environment
out["slots_alive"] = sum(1 for p in live.values() for v in p.values() if isinstance(v, dict) and v.get("state") == "alive")
lap("context", tmux_control.active_context)
lap("visible", tmux_control.board_visible)
print(json.dumps(out))
