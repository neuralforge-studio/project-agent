"""Read-only probe of the user's real registry and tmux server: the Board model's snapshot and liveness reads,
timed, with the number of tmux and other processes each starts (PERF-001 verification 2).

It only reads: `model.snapshot` and `model.liveness` write nothing (the registry, state files and tmux options are
read). usage: python real_server_probe.py [REPETITIONS]   (default registry; the default tmux server)
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parents[1]
LOG = HERE / ".real-probe-spawns.log"


def main():
    repetitions = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    if os.environ.get("PERF_REAL_PROBE") != "1":                      # re-run with the spawn counters loaded
        env = {**os.environ, "PERF_REAL_PROBE": "1", "PYTHONPATH": str(HERE / "site"), "PERF_SPAWN_LOG": str(LOG)}
        LOG.unlink(missing_ok=True)
        try:
            return subprocess.run([sys.executable, __file__, *sys.argv[1:]], env=env).returncode
        finally:
            LOG.unlink(missing_ok=True)
    sys.path.insert(0, str(TOOLS / "project-board"))
    from project_board import model

    def spawns():
        counts = {}
        for line in LOG.read_text().splitlines():
            parts = line.split("\t")
            if parts[0] == "spawn":
                counts[parts[1]] = counts.get(parts[1], 0) + 1
        return counts

    for name, read in (("snapshot", model.snapshot), ("liveness", model.liveness)):
        for rep in range(1, repetitions + 1):
            before, started = spawns(), time.perf_counter()
            result = read()
            seconds = time.perf_counter() - started
            after = spawns()
            delta = {k: after.get(k, 0) - before.get(k, 0) for k in after if after.get(k, 0) != before.get(k, 0)}
            slots = (sum(len(rows) for rows in result.values()) if name == "liveness"
                     else sum(len(p["seats"]) + (1 if p["leader"] else 0) for p in result["projects"]))
            print(json.dumps({"read": name, "rep": rep, "seconds": round(seconds, 3), "spawns": delta, "slots": slots,
                              "load": float(Path("/proc/loadavg").read_text().split()[0])}))


if __name__ == "__main__":
    sys.exit(main())
