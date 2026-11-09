"""Isolated environments and process helpers of the performance benchmark (PERF-001).

An environment is N projects x S live seats (+ each Leader) on a tmux server of its own. Every slot has
a live managed window whose "CLI" is a `sleep` pane process; the window metadata and state.json are what
a started and registered run leaves (internal.mark_process and _register). Project 0 has one more
registered seat that has no run: the seat on which the lifecycle operations start a Worker.

The environment is built with this checkout's agent_session and project_item (the formats are versioned by
tools/formats.json, so the executables under comparison read the same state and window options). Every
command of the benchmark names the environment through `Environment.command_env`, which always sets TMUX,
AGENT_SESSION_SOCKET, HOME and XDG_CACHE_HOME, so no command can reach the user's tmux server.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parents[1]                    # this checkout's tools/
REPOSITORY = TOOLS.parent
SITE = HERE / "site"                       # sitecustomize: spawn and sleep counters, fake provider
for _part in (TOOLS / "agent-session", TOOLS / "project-item", TOOLS / "tests"):
    if str(_part) not in sys.path:
        sys.path.insert(0, str(_part))

import tmux_test_server  # noqa: E402
from agent_session import process  # noqa: E402
from agent_session.config import load_registry  # noqa: E402
from agent_session.state import StateStore  # noqa: E402
from agent_session.tmux import Tmux  # noqa: E402
from project_item import store as item_store  # noqa: E402
from project_item.kinds import CR, DECIDE  # noqa: E402

TICKS = os.sysconf("SC_CLK_TCK")
DONE_CRS = 40                              # per project, like a project that has run for weeks
DECISIONS = 12


@dataclass(frozen=True)
class Executable:
    """One product tree under comparison: a checkout or an installed release directory (it holds tools/)."""
    name: str
    root: Path

    @property
    def tools(self):
        return self.root / "tools"

    def bin(self, tool):
        return str(self.tools / tool / "bin" / tool)

    @property
    def fixtures(self):
        return self.tools / "agent-session" / "tests" / "fixtures"

    @property
    def status_script(self):
        return self.root / "integrations" / "tmux" / "tmux_decide_status.sh"

    @property
    def visibility_script(self):
        return self.root / "integrations" / "tmux" / "project_board_visibility.sh"

    def check(self):
        for path in (self.bin("agent-session"), self.bin("project-item"), self.bin("project-board"),
                     self.status_script, self.fixtures / "agent_session_fake_provider.py"):
            if not Path(path).exists():
                raise SystemExit(f"{self.name}: {path} does not exist (an executable needs a full tree with tests/fixtures)")


def parse_executable(text):
    name, separator, path = text.partition("=")
    if not separator or not name or not path:
        raise SystemExit(f"--exe wants NAME=PATH, not {text!r}")
    exe = Executable(name, Path(path).expanduser().resolve())
    exe.check()
    return exe


def load_average():
    return float(Path("/proc/loadavg").read_text().split()[0])


def git(root, *args):
    result = subprocess.run(["git", "-c", "submodule.recurse=false", "-C", str(root), *args], capture_output=True, text=True,
                            env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    if result.returncode:
        raise SystemExit(result.stderr)
    return result.stdout.strip()


def _git_template(directory):
    remote, seed, clone = directory / "origin.git", directory / "seed", directory / "clone"
    remote.mkdir(parents=True)
    git(remote, "init", "--bare", "--template=", "--initial-branch=main")
    seed.mkdir()
    git(seed, "init", "--template=", "--initial-branch=main")
    git(seed, "config", "user.name", "Fixture")
    git(seed, "config", "user.email", "fixture@example.invalid")
    (seed / "server.py").write_text("VALUE = 1\n")
    (seed / ".gitignore").write_text("/agent/\n")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "Seed fixture main")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-u", "origin", "main")
    git(directory, "clone", "--template=", str(remote), str(clone))
    git(clone, "config", "user.name", "Fixture")
    git(clone, "config", "user.email", "fixture@example.invalid")
    return remote, clone, git(seed, "rev-parse", "HEAD")


def in_progress_text(cr_id, base_hash, submitted=None):
    result = f"\n## Result\n- 제출 commit: {submitted}\n- 검증: fixture\n" if submitted else ""
    return (f"# {cr_id}: Fixture work item\n\n- Opened: 2026-11-10\n- Scope: fixture\n- Severity: S3\n- Mode: write\n"
            f"- Base: {base_hash} 2026-11-10T08:00:00+09:00\n\n## Symptom\nFixture.\n\n## Evidence\n`server.py:1`\n\n"
            "## Contract\nFixture.\n\n## Disposition\n- 2026-11-10 Leader: approved fixture.\n\n"
            f"## Implementation\nChange server.py.\n\n## Verification\npython -m py_compile server.py\n{result}")


def _fill_items(base, seats, seed_hash):
    cr = base / "docs" / "cr"
    for state in CR.states:
        (cr / state).mkdir(parents=True, exist_ok=True)
    real = REPOSITORY / "docs" / "cr"                # this repository's own CRs give the real size distribution
    done = sorted((real / "done").glob("*.md"))[:DONE_CRS]
    for path in done:
        shutil.copyfile(path, cr / "done" / path.name)
    for index in range(len(done), DONE_CRS):
        (cr / "done" / f"OLD-{index + 1:03}-fixture.md").write_text(in_progress_text(f"OLD-{index + 1:03}", seed_hash))
    for path in sorted((real / "open").glob("*.md"))[:2]:
        shutil.copyfile(path, cr / "open" / path.name)
    jobs = []
    for n in range(seats):
        cr_id = f"WORK-{n + 1:03}"
        jobs.append(cr_id)
        (cr / "in-progress" / f"{cr_id}-fixture-work-item.md").write_text(
            in_progress_text(cr_id, seed_hash, seed_hash if n % 4 == 0 else None), encoding="utf-8")
    decide = base / "agent" / "decide"
    for n in range(DECISIONS):
        item_store.new_decide(decide, lambda item_id, n=n: DECIDE.fmt.TEMPLATE.format(
            item_id=item_id, title=f"Fixture decision {n}", opened="2026-11-10 08:00", urgency="normal", extra="",
            body=DECIDE.fmt.EMPTY_BODY))
    return jobs


class Environment:
    """One scale (projects x seats): its directory, tmux server and registry."""

    def __init__(self, workdir, projects, seats):
        self.projects, self.seats = projects, seats
        self.scale = f"{projects}x{seats}"
        self.root = Path(workdir) / self.scale
        self.python = self.root / "py"
        self.info = None

    # ------------------------------------------------------------------ build
    def build(self):
        if self.root.exists():
            raise SystemExit(f"{self.root} exists; choose a new --workdir")
        started = time.time()
        (self.root / "home" / ".cache").mkdir(parents=True)
        (self.root / "home" / ".config" / "project-agent").mkdir(parents=True)
        name = tmux_test_server.claim(f"perf-{self.scale}")            # removed when this process ends
        socket_path = str(tmux_test_server.socket_path(name))
        remote_template, clone_template, seed_hash = _git_template(self.root / "tpl")
        registry, listing = {}, []
        for i in range(self.projects):
            pid = f"p{i:02}"
            count = self.seats + (1 if i == 0 else 0)
            work = self.root / "work" / pid
            work.mkdir(parents=True)
            remote = work / "origin.git"
            shutil.copytree(remote_template, remote, symlinks=True)
            paths = [work / f"{pid}.main"] + [work / f"{pid}.seat{n}" for n in range(count)]
            for path in paths:
                shutil.copytree(clone_template, path, symlinks=True)
                git(path, "remote", "set-url", "origin", str(remote))
            base, seats = paths[0], paths[1:]
            (base / "agent").mkdir()
            jobs = _fill_items(base, self.seats, seed_hash)
            registry[str(base)] = {"project": pid, "provider": "claude", "seats": [str(p) for p in seats],
                                   "path_cr": "docs/cr", "path_decide": "agent/decide"}
            listing.append({"id": pid, "base": str(base), "seats": [str(p) for p in seats], "jobs": jobs})
        config = self.root / "project.json"
        config.write_text(json.dumps(registry, indent=1))
        (self.root / "home" / ".config" / "project-agent" / "project.json").symlink_to(config)   # the status script's registry
        self.info = {"scale": self.scale, "socket_name": name, "socket_path": socket_path, "config": str(config),
                     "seed_hash": seed_hash, "list": listing}
        (self.root / "env.json").write_text(json.dumps(self.info, indent=1))
        self.python.write_text(
            "#!/bin/bash\n# PROJECT_AGENT_PYTHON of the benchmark: the interpreter of the run plus the harness's sitecustomize,\n"
            "# which project-item's and project-board's launchers would hide by resetting PYTHONPATH.\n"
            f'export PYTHONPATH="${{PYTHONPATH:+$PYTHONPATH:}}{SITE}"\nexec {sys.executable} "$@"\n')
        self.python.chmod(self.python.stat().st_mode | stat.S_IXUSR)
        self._start_server()
        self._populate(registry)
        return time.time() - started

    def _start_server(self):
        # The server starts with the harness environment, so that its panes (the fake CLI's registration, a Board
        # pane) load the instrumentation too; their spawns go to pane-spawns.log, apart from a measured command's.
        env = self._base_env(spawn_log=self.root / "pane-spawns.log")
        subprocess.run(["tmux", "-L", self.info["socket_name"], "-f", os.devnull, "new-session", "-d", "-s", "harness",
                        "sleep", "86400"], check=True, capture_output=True, env=env)

    def _populate(self, registry):
        socket_path = self.info["socket_path"]
        tmux = Tmux(socket_path=socket_path)
        loaded = {p.project_id: p for p in load_registry(self.info["config"])}
        seed_hash = self.info["seed_hash"]
        for entry in self.info["list"]:
            project = loaded[entry["id"]]
            state = {"leader": None}
            slots = [("leader", None, project.base)] + [(f"seat-{n}", n, project.seats[n]) for n in range(self.seats)]
            for slot, n, cwd in slots:
                job = None if n is None else entry["jobs"][n]
                session_id, run_id = str(uuid.uuid4()), uuid.uuid4().hex
                values = {"base": str(project.base), "run_id": run_id, "target": slot, "seat": n, "job_id": job,
                          "provider": "claude", "config_path": self.info["config"], "session_id": session_id,
                          "expected_session_id": session_id, "role": "leader" if n is None else "worker",
                          "seat_root": str(cwd)}
                window = f"{project.project_id}-leader" if n is None else f"{project.project_id}-seat{n}-{job}"
                meta = tmux.create_window(project.project_id, window, cwd, values)
                pid = meta["placeholder_pid"]
                tmux.write_meta(meta["window_id"], {
                    "cli_pid": pid, "cli_birth": process.birth(pid), "process_group": os.getpgid(pid),
                    "provider_launch_attempted": True, "registered": True, "ready": True, "publishing": None,
                    "stopping": False, "message_to": f"{slot} [{session_id[:6]}]", "socket_path": socket_path,
                    "start_error": None})
                tmux.set_current(project.project_id, slot, meta)
                binding = {"session_id": session_id, "message_to": f"{slot} [{session_id[:6]}]",
                           "connected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                if n is None:
                    state["leader"] = binding
                else:
                    state[str(n)] = {"job_id": job, "git_hash": seed_hash, "session": binding}
            if len(project.seats) > self.seats:
                state[str(self.seats)] = {"job_id": None, "git_hash": None, "session": None}
            store = StateStore(project)
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.update(lambda value, state=state: state)

    def teardown(self):
        if self.info:
            tmux_test_server.release(self.info["socket_name"])
        shutil.rmtree(self.root, ignore_errors=True)

    # ------------------------------------------------------------------ commands
    @property
    def base(self):
        return self.info["list"][0]["base"]

    @property
    def spare(self):
        return self.seats                  # index of project 0's seat that has no run

    def _base_env(self, spawn_log=None):
        home = self.root / "home"
        env = {k: v for k, v in os.environ.items()
               if k not in ("TMUX", "TMUX_PANE", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "AGENT_SESSION_BASE",
                            "AGENT_SESSION_CONFIG", "PYTHONPATH", "PROJECT_BOARD_SOCKET")}
        env.update({"HOME": str(home), "XDG_CACHE_HOME": str(home / ".cache"),
                    "TMUX": f"{self.info['socket_path']},0,0", "AGENT_SESSION_SOCKET": self.info["socket_path"],
                    "PROJECT_BOARD_SOCKET": self.info["socket_path"], "AGENT_SESSION_CONFIG": self.info["config"],
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
                    "PERF_FAKE": "1", "PYTHONPATH": str(SITE), "PROJECT_AGENT_PYTHON": str(self.python)})
        if spawn_log:
            env["PERF_SPAWN_LOG"] = str(spawn_log)
        return env

    def command_env(self, exe, spawn_log=None, identity=None, extra=None):
        """The environment of one measured command. `identity` is (project id, slot): the caller is that slot's live conversation."""
        env = self._base_env(spawn_log)
        env["PERF_FIXTURES"] = str(exe.fixtures)
        if identity:
            env["CLAUDE_CODE_SESSION_ID"] = self.session_of(*identity)
        env.update(extra or {})
        return env

    def session_of(self, project_id, slot):
        entry = next(p for p in self.info["list"] if p["id"] == project_id)
        state = json.loads((Path(entry["base"]) / "agent" / "state.json").read_text())
        return state["leader"]["session_id"] if slot == "leader" else state[slot[5:]]["session"]["session_id"]

    def state(self):
        return json.loads((Path(self.base) / "agent" / "state.json").read_text())

    def tmux(self, *args, check=True):
        result = subprocess.run(["tmux", "-S", self.info["socket_path"], *args], capture_output=True, text=True)
        if check and result.returncode:
            raise SystemExit(f"tmux {args}: {result.stderr}")
        return result.stdout.strip()

    def worker_window(self):
        return Tmux(socket_path=self.info["socket_path"]).get_current("p00", f"seat-{self.spare}")


def run_command(argv, env, cwd, stdin=None, timeout=900):
    """One real subprocess: (seconds, return code, stdout, stderr)."""
    start = time.perf_counter()
    result = subprocess.run(argv, env=env, cwd=cwd, input=stdin, capture_output=True, text=True, timeout=timeout)
    return time.perf_counter() - start, result.returncode, result.stdout, result.stderr


def read_spawn_log(path):
    """({name: spawn count}, sleep seconds, {name: seconds waited}) of a log written by site/sitecustomize.py."""
    counts, sleep, waited = {}, 0.0, {}
    path = Path(path)
    if path.exists():
        for line in path.read_text().splitlines():
            parts = line.split("\t")
            if parts[0] == "spawn":
                counts[parts[1]] = counts.get(parts[1], 0) + 1
            elif parts[0] == "wait":
                waited[parts[1]] = waited.get(parts[1], 0.0) + float(parts[2])
            elif parts[0] == "sleep":
                sleep += float(parts[1])
    return counts, round(sleep, 3), {k: round(v, 3) for k, v in waited.items()}


def count_spawns(lines):
    counts = {}
    for line in lines:
        parts = line.split("\t")
        if parts[0] == "spawn":
            counts[parts[1]] = counts.get(parts[1], 0) + 1
    return counts


def cpu_seconds(pid):
    """utime+stime+cutime+cstime of a process and its live descendants (reaped children included)."""
    total, stack, seen = 0, [pid], set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            fields = Path(f"/proc/{current}/stat").read_text().rsplit(")", 1)[1].split()
            total += sum(int(fields[i]) for i in (11, 12, 13, 14))
            stack += [int(child) for child in Path(f"/proc/{current}/task/{current}/children").read_text().split()]
        except OSError:
            pass
    return total / TICKS
