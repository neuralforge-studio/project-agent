"""One process of the benchmark: import the Board model of the tools tree PERF_TOOLS, then time snapshot / liveness /
context reads. The per-read spawn counts come from the spawn log (site/sitecustomize.py).
usage: python board_model_probe.py CONFIG"""
import json, os, sys, time
sys.path.insert(0, os.path.join(os.environ["PERF_TOOLS"], "project-board"))
LOG = os.environ["PERF_SPAWN_LOG"]

def counts():
    c = {}
    for line in open(LOG).read().splitlines():
        p = line.split("\t")
        if p[0] == "spawn":
            c[p[1]] = c.get(p[1], 0) + 1
    return c

def lap(name, fn, *a):
    before = counts(); t = time.perf_counter(); r = fn(*a); d = time.perf_counter() - t
    after = counts()
    delta = {k: after.get(k, 0) - before.get(k, 0) for k in after if after.get(k, 0) != before.get(k, 0)}
    out[name] = {"s": round(d, 3), "spawns": delta}
    return r

out = {}
t0 = time.perf_counter()
from project_board import model, tmux_control
out["import"] = round(time.perf_counter() - t0, 3)
config = sys.argv[1]
for i in (1, 2, 3):
    lap(f"snapshot{i}", model.snapshot, config)
for i in (1, 2, 3):
    live = lap(f"liveness{i}", model.liveness, config)
out["slots_alive"] = sum(1 for p in live.values() for v in p.values() if isinstance(v, dict) and v.get("state") == "alive")
lap("context", tmux_control.active_context)
lap("visible", tmux_control.board_visible)
print(json.dumps(out))
