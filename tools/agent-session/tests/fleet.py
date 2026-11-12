"""A fleet of projects with live tmux runs, and a counter of the tmux processes a call starts (SESSION-010).

`build_fleet` lays out `projects` registered projects with `seats` Worker seats each, on one private tmux
server: every slot (Leader and seats) holds a managed window with a real pane and the run metadata a started
run has, and the project's state binds a conversation to it. It writes the windows with one tmux command
per project, not one per option, so a fleet of 16 projects x 16 seats builds in seconds. `count_tmux` then
records each `tmux` process the product starts.
"""

import json
import os
from pathlib import Path
import subprocess
import uuid

from agent_session import process, tmux as tmux_module
from agent_session.tmux import Tmux
import tmux_test_server
from wait_limit import command_timeout

PREFIX = tmux_module._PREFIX
# What a started run keeps in its window: the identity, the waiting pane, and the values a run adds.
RUN_VALUES = {key: value for key, value in tmux_module._RUN_VALUES.items()}


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _tmux(socket_path, *arguments):
    result = subprocess.run(["tmux", "-S", socket_path, "-f", os.devnull, *map(str, arguments)],
                            capture_output=True, text=True, timeout=command_timeout())
    if result.returncode:
        raise AssertionError(f"tmux {arguments[:2]}: {result.stderr}")
    return result.stdout.rstrip("\n")


def start_server(socket_name):
    """Start a private tmux server (ended by `tmux_test_server.release(socket_name)`) and return its socket path."""
    tmux_test_server.watch(socket_name)
    subprocess.run(["tmux", "-L", socket_name, "-f", os.devnull, "new-session", "-d", "-s", "harness",
                    "sleep", "86400"], check=True, capture_output=True)
    return str(tmux_test_server.socket_path(socket_name).resolve())


def build_fleet(root, socket_path, projects, seats):
    """Register `projects` projects of `seats` seats under `root`; return the registry file."""
    root = Path(root)
    control = Tmux(socket_path=socket_path)
    server = control.server_identity()
    names = [f"p{number}" for number in range(projects)]
    slots = ["leader", *(f"seat-{seat}" for seat in range(seats))]
    for name in names:
        _tmux(socket_path, "new-session", "-d", "-s", name, "-n", "leader", "-c", root, "sleep", "86400")
    handles = dict(line.split("\t") for line in
                   _tmux(socket_path, "list-sessions", "-F", "#{session_name}\t#{session_id}").splitlines())
    for name in names:                                       # one window per seat; the session made the Leader's
        arguments = []
        for slot in slots[1:]:
            arguments += ["new-window", "-d", "-t", handles[name] + ":", "-n", slot, "-c", root, "sleep", "86400", ";"]
        if arguments:
            _tmux(socket_path, *arguments[:-1])
    rows = [line.split("\t") for line in _tmux(
        socket_path, "list-panes", "-a", "-F",
        "#{session_name}\t#{window_name}\t#{window_id}\t#{pane_id}\t#{pane_pid}").splitlines()]
    panes = {(session, window): (window_id, pane_id, int(pid))
             for session, window, window_id, pane_id, pid in rows if session in names}
    registry = {}
    for name in names:
        base = root / f"{name}.main"
        seat_paths = [root / f"{name}.seat{seat}" for seat in range(seats)]
        (base / "agent").mkdir(parents=True)
        for path in seat_paths:
            path.mkdir()
        registry[str(base)] = {"project": name, "provider": "codex", "seats": [str(path) for path in seat_paths]}
        state = {"leader": None, **{str(seat): {"job_id": None, "git_hash": None, "session": None}
                                    for seat in range(seats)}}
        _tmux(socket_path, "set-option", "-t", handles[name], PREFIX + "owner",
              _json({"base": str(base), "project_id": name, **server}))
        for slot in slots:
            window_id, pane_id, pid = panes[(name, "leader" if slot == "leader" else slot)]
            session_id = str(uuid.uuid4())
            job_id = None if slot == "leader" else f"TOOL-{int(slot[5:]) + 1:03}"
            identity = {"base": str(base), "target": slot, "job_id": job_id, "run_id": uuid.uuid4().hex,
                        "project_id": name, "window_id": window_id, "pane_id": pane_id, **server}
            values = {**RUN_VALUES, **identity, "cwd": str(root), "provider_launch_attempted": True,
                      "registered": True, "ready": True, "publishing": None, "stopping": False,
                      "placeholder_pid": pid, "placeholder_birth": process.birth(pid),
                      "placeholder_process_group": pid, "cli_pid": pid, "cli_birth": process.birth(pid),
                      "process_group": pid, "session_id": session_id, "message_to": None,
                      "provider_name": "codex", "launch_file": str(root / "launch.sh")}
            if slot == "seat-0":
                values["release_pending"] = {"since": "2026-11-10T00:00:00Z", "reasons": ["cr_in_progress"]}
            commands = []                                    # one tmux command per slot: a longer one is "too long"
            for key, value in values.items():
                commands += [";", "set-option", "-w", "-t", window_id, PREFIX + key, _json(value)]
            commands += [";", "set-option", "-t", handles[name], PREFIX + "current_" + slot.replace("-", "_"),
                         _json({key: values[key] for key in tmux_module._IDENTITY})]
            _tmux(socket_path, *commands[1:])
            session = {"session_id": session_id, "endpoint": "unix:///tmp/fleet.sock"}
            if slot == "leader":
                state["leader"] = session
            else:
                state[slot[5:]] = {"job_id": job_id, "git_hash": None, "session": session}
        (base / "agent" / "state.json").write_text(json.dumps(state), encoding="utf-8")
    registry_file = root / "registry.json"
    registry_file.write_text(json.dumps(registry), encoding="utf-8")
    return registry_file


def count_tmux(monkeypatch):
    """Record every `tmux` process the product starts from now on; return the list of its argument vectors."""
    calls = []
    original = subprocess.run

    def counted(argv, *args, **kwargs):
        if argv and argv[0] == "tmux":
            calls.append(list(argv))
        return original(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", counted)
    return calls
