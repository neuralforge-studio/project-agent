"""The measured operations of the performance benchmark (PERF-001).

Each function measures one executable on one environment and appends rows to `Recorder`. A row is one
command (or one read of a probe) with its wall time, its Popen counts by program, the seconds it slept
(time.sleep) and the Popen counts of the processes that its tmux server started for it (a Worker's
registration). Groups: startup, readonly, board_cli, lifecycle, steady. `perf_bench.run` interleaves the
executables (ABAB) around these functions.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import bench_env
from bench_env import HERE, SITE, TOOLS, cpu_seconds, count_spawns, load_average, read_spawn_log, run_command

BODY = "## Symptom\nfixture\n\n## Evidence\n`server.py:1`\n\n## Contract\nfixture\n"
CR_TAIL = "\n\n## Implementation\nChange server.py.\n\n## Verification\npython -m py_compile server.py\n"

GROUPS = ("startup", "readonly", "board_cli", "lifecycle", "steady")


class Recorder:
    def __init__(self, path):
        self.path = Path(path)
        self.rows = []

    def add(self, row):
        self.rows.append(row)
        with self.path.open("a") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        spawns = " ".join(f"{k}:{v}" for k, v in sorted(row.get("spawns", {}).items()))
        print(f"{row['scale']:6s} {row['mode']:4s} {row['exe']:10s} rep{row['rep']} {row['op']:28s} {row['wall']:8.2f}s "
              f"load {row['load']:5.1f} [{spawns}]" + ("" if row["rc"] == 0 else f"  !! rc={row['rc']}"), flush=True)


class Bench:
    """Runs the operations of one environment. `mode` is "warm" (back to back) or "cold" (after an idle gap)."""

    def __init__(self, env, recorder):
        self.env, self.recorder = env, recorder
        self.log = env.root / "cmd-spawns.log"
        self.pane_log = env.root / "pane-spawns.log"
        self.mode, self.rep = "warm", 0
        self.client = None

    # ------------------------------------------------------------------ one command
    def pane_lines(self):
        return self.pane_log.read_text().splitlines() if self.pane_log.exists() else []

    def row(self, exe, op, wall, rc, spawns=None, sleep=0.0, waited=None, pane=None, **extra):
        self.recorder.add({"exe": exe.name, "scale": self.env.scale, "mode": self.mode, "rep": self.rep, "op": op,
                           "wall": round(wall, 4), "rc": rc, "load": round(load_average(), 2), "spawns": spawns or {},
                           "sleep": sleep, "spawn_wait": waited or {}, "pane_spawns": pane or {}, **extra})

    def cmd(self, exe, op, argv, identity=("p00", "leader"), stdin=None, expect_ok=True, spawn_log=True, extra_env=None):
        self.log.unlink(missing_ok=True)
        env = self.env.command_env(exe, self.log if spawn_log else None, identity, extra_env)
        before = len(self.pane_lines())
        wall, rc, out, err = run_command(argv, env, self.env.base, stdin=stdin)
        counts, slept, waited = read_spawn_log(self.log)
        self.row(exe, op, wall, rc, counts, slept, waited, count_spawns(self.pane_lines()[before:]))
        if expect_ok and rc != 0:
            raise SystemExit(f"{exe.name} {op} failed (rc {rc}): {(out + err)[:1500]}")
        return out, err

    def agent(self, exe, op, *args, **kw):
        return self.cmd(exe, op, [exe.bin("agent-session"), "--config", self.env.info["config"], "--socket-path",
                                  self.env.info["socket_path"], *args], **kw)

    def item(self, exe, op, *args, **kw):
        return self.cmd(exe, op, [exe.bin("project-item"), *args, "--config", self.env.info["config"]], **kw)

    def board(self, exe, op, *args, **kw):
        return self.cmd(exe, op, [exe.bin("project-board"), "--config", self.env.info["config"], *args], **kw)

    def python(self, exe, op, code, **kw):
        return self.cmd(exe, op, [str(self.env.python), "-c", code], identity=None, **kw)

    # ------------------------------------------------------------------ startup
    def startup(self, exe):
        """Interpreter start, import time and launcher cost: what every command pays before it does anything."""
        tools = exe.tools
        self.python(exe, "startup_python", "pass")
        self.python(exe, "import_agent_session",
                    f"import sys; sys.path.insert(0, '{tools / 'agent-session'}'); import agent_session.lifecycle")
        self.python(exe, "import_project_item",
                    f"import sys; sys.path.insert(0, '{tools / 'project-item'}'); import project_item.cli")
        self.python(exe, "import_project_board",
                    f"import sys; sys.path.insert(0, '{tools / 'project-board'}'); import project_board.tui")
        self.cmd(exe, "bin_agent_session_help", [exe.bin("agent-session"), "--help"], identity=None)
        self.cmd(exe, "bin_project_item_help", [exe.bin("project-item"), "--help"], identity=None)

    # ------------------------------------------------------------------ read-only operations
    def readonly(self, exe, ops=None):
        want = (lambda name: ops is None or name in ops)
        if want("project_item_ls"):
            self.item(exe, "project_item_ls", "ls")
        if want("project_item_check"):
            self.item(exe, "project_item_check", "check")
        if want("agent_review_clear"):
            self.agent(exe, "agent_review_clear", "review", "--clear")
        if want("agent_watch"):
            self.agent(exe, "agent_watch", "watch", "--project", "p00")
        if want("status_script"):
            self.status(exe)
        if want("board_model"):
            self.board_model(exe)

    def status(self, exe):
        cache = self.env.root / "home" / ".cache" / "tmux-decide-status.json"
        cache.unlink(missing_ok=True)
        self.cmd(exe, "status_no_cache", [str(exe.status_script)], identity=None)
        self.cmd(exe, "status_cache_valid", [str(exe.status_script)], identity=None)
        old = time.time() - 600
        os.utime(cache, (old, old))
        self.cmd(exe, "status_cache_expired", [str(exe.status_script)], identity=None)

    def board_model(self, exe):
        """snapshot, liveness and the Board pane's context reads in one process, each read as its own row."""
        pane = self.env.tmux("list-panes", "-t", "p00", "-F", "#{pane_id}").splitlines()[0]
        self.log.unlink(missing_ok=True)
        env = self.env.command_env(exe, self.log, None, {"TMUX_PANE": pane, "PERF_TOOLS": str(exe.tools)})
        wall, rc, out, err = run_command([str(self.env.python), str(HERE / "board_model_probe.py"), self.env.info["config"]],
                                         env, self.env.base)
        if rc:
            raise SystemExit(f"{exe.name} board_model failed: {err[-1500:]}")
        probe = json.loads(out.strip().splitlines()[-1])
        self.row(exe, "board_import", probe["import"], 0)
        names = {"snapshot1": "board_snapshot_first", "snapshot2": "board_snapshot_warm", "liveness1": "board_liveness",
                 "context": "board_context", "visible": "board_visible"}
        for key, name in names.items():
            self.row(exe, name, probe[key]["s"], 0, probe[key]["spawns"])

    # ------------------------------------------------------------------ board commands that need a client
    def attach(self, session="p00"):
        self.detach()
        self.client = subprocess.Popen([sys.executable, str(HERE / "pty_client.py"), self.env.info["socket_path"], session],
                                       start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if self.env.tmux("list-clients", "-F", "#{client_name}"):
                return
            time.sleep(0.1)
        raise SystemExit("the benchmark's tmux client did not attach")

    def detach(self):
        if self.client:
            try:
                os.killpg(self.client.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.client.wait()
            self.client = None
            time.sleep(0.5)

    def board_cli(self, exe):
        self.attach("p00")
        try:
            self.board_cli_commands(exe)
        finally:
            self.detach()

    def board_cli_commands(self, exe):
        socket = self.env.info["socket_path"]
        self.env.tmux("set-option", "-g", "@project_board_enabled", "0", check=False)
        self.board(exe, "board_toggle_on", "toggle", "--socket", socket, identity=None)
        self.wait_board_ready()
        self.board(exe, "board_sync_nochange", "sync", "--socket", socket, identity=None)
        self.cmd(exe, "board_visibility_sh", [str(exe.visibility_script), "--socket", socket], identity=None, spawn_log=False)
        self.board(exe, "board_toggle_off", "toggle", "--socket", socket, identity=None)
        time.sleep(1)
        self.cmd(exe, "board_visibility_sh_off", [str(exe.visibility_script), "--socket", socket], identity=None, spawn_log=False)
        self.board(exe, "board_sync_off", "sync", "--socket", socket, identity=None)
        self.pane_ready(exe, "board_popup_ready", [exe.bin("project-board"), "--config", self.env.info["config"], "popup",
                                                   "--project", "p00"])
        self.pane_ready(exe, "board_sidebar_ready", [exe.bin("project-board"), "--config", self.env.info["config"],
                                                     "sidebar"])

    def wait_board_ready(self, seconds=30):
        end = time.time() + seconds
        while time.time() < end:
            if "1" in self.env.tmux("list-panes", "-a", "-F", "#{@project_board_ready}").split():
                return
            time.sleep(0.2)

    def pane_ready(self, exe, op, argv, seconds=90):
        """Seconds from `new-window` until the TUI has drawn its first screen (the pane has text)."""
        env = self.env.command_env(exe)
        import shlex
        started = time.perf_counter()
        window = self.env.tmux("new-window", "-d", "-P", "-F", "#{window_id}", "-t", "harness:", "-e", "PROJECT_BOARD_CLICK_SOCKET=",
                               " ".join(f"{k}={shlex.quote(v)}" for k, v in {"PYTHONPATH": env["PYTHONPATH"],
                                        "PROJECT_AGENT_PYTHON": env["PROJECT_AGENT_PYTHON"], "PERF_FAKE": "1",
                                        "PERF_FIXTURES": env["PERF_FIXTURES"], "PROJECT_BOARD_SOCKET": env["PROJECT_BOARD_SOCKET"],
                                        "HOME": env["HOME"], "TMUX": env["TMUX"],
                                        "AGENT_SESSION_SOCKET": env["AGENT_SESSION_SOCKET"]}.items())
                               + " " + " ".join(shlex.quote(part) for part in argv))
        rc, ready = 1, False
        while time.perf_counter() - started < seconds:
            text = self.env.tmux("capture-pane", "-p", "-t", window, check=False)
            if "p00" in text:
                rc, ready = 0, True
                break
            time.sleep(0.1)
        wall = time.perf_counter() - started
        self.env.tmux("kill-window", "-t", window, check=False)
        self.row(exe, op, wall, rc, ready=ready)

    # ------------------------------------------------------------------ lifecycle
    def new_cr(self, exe, title):
        out, _ = self.item(exe, "project_item_new", "new", "cr", "--area", "PERF", "--title", title, "--body-file", "-",
                           stdin=BODY)
        cr_id = "-".join(out.split("opened ")[1].split("/")[-1].split("-")[0:2])
        path = next((Path(self.env.base) / "docs" / "cr" / "open").glob(f"{cr_id}-*.md"))
        path.write_text(path.read_text().rstrip("\n") + CR_TAIL)          # the sections a CR needs before todo (setup)
        return cr_id

    def cr_path(self, cr_id, state):
        return next((Path(self.env.base) / "docs" / "cr" / state).glob(f"{cr_id}-*.md"))

    def lifecycle(self, exe):
        env, spare = self.env, self.env.spare
        seed = env.info["seed_hash"]
        cr_id = self.new_cr(exe, f"perf {exe.name} {self.rep}")
        self.item(exe, "project_item_move_todo", "move", cr_id, "todo", "--by", "Leader", "--note", "perf approved")
        self.agent(exe, "agent_start_worker", "start", "--job", cr_id)
        self.agent(exe, "agent_send_to_worker", "send", "--job", cr_id, "perf message to the worker")
        self.agent(exe, "agent_send_to_leader", "send", "--job", "leader", "perf report", identity=("p00", f"seat-{spare}"))
        self.agent(exe, "agent_review", "review", "--job", cr_id)
        self.agent(exe, "agent_review_clear_after", "review", "--clear")
        handoff = Path(env.base) / "agent" / "handoff" / f"seat-{spare}.md"
        handoff.parent.mkdir(parents=True, exist_ok=True)
        handoff.write_text("perf handoff\n")
        self.agent(exe, "agent_restart_worker", "restart", "--job", cr_id)
        path = self.cr_path(cr_id, "in-progress")
        path.write_text(path.read_text() + f"\n## Result\n- 제출 commit: {seed}\n- 검증: perf\n")
        self.item(exe, "project_item_accept", "accept", cr_id, "--commit", seed, "--note", "perf")
        self.agent(exe, "agent_stop_worker", "stop", "--job", cr_id)
        self.item(exe, "project_item_move_done", "move", cr_id, "done", "--outcome", "fixed", "--by", "Leader", "--note", seed)
        # The CLI ends by itself: the wrap-up that the pane-died hook runs (internal.finish_ended), started by hand
        # with the hook removed so that the fake provider replaces the real Claude and the spawns are counted.
        cr_end = self.new_cr(exe, f"perf end {exe.name} {self.rep}")
        self.item(exe, "project_item_move_todo", "move", cr_end, "todo", "--by", "Leader", "--note", "perf approved")
        self.agent(exe, "agent_start_worker", "start", "--job", cr_end)
        meta = env.worker_window()
        env.tmux("set-hook", "-gu", "pane-died[agent-session]")
        os.kill(int(meta["cli_pid"]), signal.SIGKILL)
        for _ in range(500):
            if env.tmux("display-message", "-p", "-t", meta["pane_id"], "#{pane_dead}", check=False) == "1":
                break
            time.sleep(0.02)
        self.log.unlink(missing_ok=True)
        run_env = env.command_env(exe, self.log, None, {"PYTHONPATH": f"{SITE}:{exe.tools / 'agent-session'}"})
        wall, rc, out, err = run_command([str(env.python), "-m", "agent_session.internal", "finish-ended",
                                          env.info["socket_path"], meta["window_id"], meta["pane_id"]], run_env, env.base)
        counts, slept, waited = read_spawn_log(self.log)
        result = Path(env.base) / "agent" / "runs" / meta["run_id"] / "finish-result.json"
        ok = bool(result.exists() and json.loads(result.read_text()).get("ok"))
        self.row(exe, "agent_finish_ended", wall, 0 if rc == 0 and ok else 1, counts, slept, waited)
        self.agent(exe, "agent_stop_ended_worker", "stop", "--job", cr_end)
        self.item(exe, "project_item_move_done_waived", "move", cr_end, "done", "--outcome", "waived", "--by", "Leader",
                  "--note", "perf")

    # ------------------------------------------------------------------ steady cost
    def steady(self, exe, panes, seconds):
        """CPU seconds and Popen counts over `seconds` with `panes` Board panes, one client, status-interval 1."""
        env, socket, config = self.env, self.env.info["socket_path"], self.env.info["config"]
        self.attach("p00")
        env.tmux("set-option", "-g", "@project_board_enabled", "0", check=False)
        env.tmux("set-option", "-g", "status-interval", "1")
        runs = env.root / "status-runs.log"
        runs.unlink(missing_ok=True)
        wrapper = env.root / "status_wrap.sh"
        wrapper.write_text('#!/bin/bash\nstart=$(date +%s.%N)\nTIMEFORMAT="%U %S"\n'
                           f'cpu=$( {{ time {exe.status_script} >/dev/null; }} 2>&1 )\n'
                           f'echo "$start $(date +%s.%N) $cpu" >> {runs}\n')
        wrapper.chmod(0o755)
        env.tmux("set-option", "-g", "status-right", f"#({wrapper})")
        cmd_env = env.command_env(exe)
        subprocess.run([exe.bin("project-board"), "--config", config, "toggle", "--socket", socket], env=cmd_env,
                       capture_output=True, text=True)
        windows = env.tmux("list-windows", "-t", "p00", "-F", "#{window_id}").splitlines()
        extra = ("import sys; sys.path.insert(0, sys.argv[1]); from project_board import tmux_control as tc; "
                 "control = tc._control(sys.argv[2]); [tc._create(control, w, sys.argv[3], 40) for w in sys.argv[4:]]")
        if panes > 1:
            subprocess.run([str(env.python), "-c", extra, str(exe.tools / "project-board"), socket, config,
                            *windows[1:panes]], env=cmd_env, check=True, capture_output=True)
        time.sleep(8)                                    # the TUIs start and settle
        listing = env.tmux("list-panes", "-a", "-F", "#{pane_id} #{pane_pid} #{@project_board_managed}")
        board = [(line.split()[0], int(line.split()[1])) for line in listing.splitlines() if line.split()[-1] == "1"]
        before_lines = len(self.pane_lines())
        before_runs = len(runs.read_text().splitlines()) if runs.exists() else 0
        cpu0 = {pid: cpu_seconds(pid) for _, pid in board}
        started = time.time()
        time.sleep(seconds)
        elapsed = time.time() - started
        used = [round(cpu_seconds(pid) - cpu0[pid], 2) for _, pid in board]
        spawns = count_spawns(self.pane_lines()[before_lines:])
        status = [line.split() for line in (runs.read_text().splitlines()[before_runs:] if runs.exists() else [])]
        status_cpu = sum(float(f[2]) + float(f[3]) for f in status if len(f) >= 4)
        env.tmux("set-option", "-g", "@project_board_enabled", "0")
        subprocess.run([exe.bin("project-board"), "--config", config, "sync", "--socket", socket], env=cmd_env, capture_output=True)
        for pane, _ in board:
            env.tmux("kill-pane", "-t", pane, check=False)
        env.tmux("set-option", "-gu", "status-right", check=False)
        self.detach()
        self.row(exe, f"steady_board_{panes}", elapsed, 0, spawns, board_panes=len(board), board_cpu=round(sum(used), 2),
                 board_cpu_each=used, status_runs=len(status), status_cpu=round(status_cpu, 2))
