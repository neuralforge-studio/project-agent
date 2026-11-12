"""The Rust sidebar moves a tmux client to a project or a Worker pane as Python does (BOARD-018).

A click on a project name or a seat used to start `project-board switch-project|switch-seat`, a Python process.
The Rust sidebar does the same itself (`rust/src/data/jump.rs`). Each case here builds one tmux server with
managed windows (as agent-session writes them), asks Python (`tmux_control.switch_project`, `switch_seat`) and
the Rust binary (`switch-project`, `switch-seat`) to move the same client, and requires the same outcome: the
same client position afterwards on success, the same message on failure. The Python result is the expected value.

Known difference: none in what a client sees. Python reports `error["message"]`; the Rust binary prints it as
`project-board: <message>` on stderr and exits 1, and the test compares the two messages.
"""
import json
import os
import shutil
import stat
import subprocess
import textwrap
import time
import uuid

import pytest

import board_testing
from board_testing import ENDPOINT, Board, attached, leader, release_clients, tmux as run_tmux
import rust_binary
from wait_limit import command_timeout
import tmux_test_server
from project_board import model, tmux_control  # noqa: E402  (puts agent_session on the path)
from agent_session.tmux import Tmux  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")


@pytest.fixture(scope="session")
def sidebar_bin():
    try:
        binary = rust_binary.sidebar_binary()
    except rust_binary.RustBinaryError as error:
        pytest.fail(f"the Rust sidebar binary is not available: {error}", pytrace=False)
    probe = subprocess.run([str(binary), "switch-project"], capture_output=True, text=True)
    if probe.returncode != 2 or "usage" not in probe.stderr:
        pytest.fail(f"the Rust sidebar binary has no switch-project command: {probe.stderr}", pytrace=False)
    return binary


@pytest.fixture(autouse=True)
def fresh_python_model():
    for cache in (model._cache, model._unchanged_cache, model._registry_cache, model._releases):
        cache.clear()


def worker(index):
    return {"session_id": str(uuid.UUID(int=0xA000 + index)), "endpoint": ENDPOINT}


def window_meta(base, seat, session_id, remote=None):
    meta = {"base": str(base), "target": f"seat-{seat}", "run_id": uuid.uuid4().hex, "session_id": session_id}
    if remote:
        meta["remote_seat"] = remote
    return meta


class Scene:
    """A tmux server with two attached clients and several registered projects in different conditions."""

    def __init__(self, tmp_path):
        self.board = Board(tmp_path)
        self.name = tmux_test_server.claim("board-switch")
        self.clients = []
        run_tmux(self.name, "-f", "/dev/null", "new-session", "-d", "-s", "home", "sleep", "300")
        self.control = Tmux(socket_name=self.name)
        self.socket = run_tmux(self.name, "display-message", "-p", "#{socket_path}")
        self.windows = {}
        self.build()
        self.clients = [attached(self.name, "home"), attached(self.name, "home")]
        self.first, self.second = self.clients[0][2], self.clients[1][2]

    def managed(self, project, base, seat, session_id, remote=None):
        meta = self.control.create_window(project, f"worker-{seat}", base, window_meta(base, seat, session_id, remote))
        self.windows.setdefault(project, {})[seat] = meta
        return meta

    def build(self):
        board = self.board
        # alpha: seat 0 runs, seat 1 has a session but no window, seat 2 has no session, seat 3 is remote.
        alpha = board.project("alpha", seats=4)
        board.registry[str(alpha)]["seats"][3] = {"host": "macbook-worker", "path": "/Users/swain/Agent/remote-seat"}
        board.state(alpha, {"leader": leader(), "0": {"job_id": "TOOL-001", "git_hash": None, "session": worker(0)},
                            "1": {"job_id": "TOOL-002", "git_hash": None, "session": worker(1)},
                            "2": {"job_id": "TOOL-003", "git_hash": None, "session": None},
                            "3": {"job_id": "TOOL-004", "git_hash": None, "session": worker(3)}})
        self.managed("alpha", alpha, 0, worker(0)["session_id"])
        self.managed("alpha", alpha, 3, worker(3)["session_id"],
                     remote={"host": "macbook-worker", "path": "/Users/swain/Agent/remote-seat", "python": "python3"})
        # dup: two windows of the same base hold the same conversation.
        dup = board.project("dup", seats=1)
        board.state(dup, {"leader": leader(), "0": {"job_id": "TOOL-001", "git_hash": None, "session": worker(0)}})
        self.managed("dup", dup, 0, worker(0)["session_id"])
        self.control.create_window("dup", "worker-again", dup, window_meta(dup, 0, worker(0)["session_id"]))
        # foreign: the session belongs to another project base.
        foreign = board.project("foreign", seats=1)
        board.state(foreign, {"leader": leader(), "0": {"job_id": "TOOL-001", "git_hash": None, "session": worker(0)}})
        self.managed("foreign", foreign, 0, worker(0)["session_id"])
        owner = json.loads(run_tmux(self.name, "show-options", "-qv", "-t", "foreign", "@agent_session_owner"))
        owner["base"] = "/somewhere/else"
        run_tmux(self.name, "set-option", "-t", "foreign", "@agent_session_owner", json.dumps(owner))
        # nostate: a tmux session, no state file.
        nostate = board.project("nostate", seats=1)
        self.managed("nostate", nostate, 0, worker(0)["session_id"])
        # badmeta: a window whose options are not valid JSON.
        badmeta = board.project("badmeta", seats=1)
        board.state(badmeta, {"leader": leader(), "0": {"job_id": "TOOL-001", "git_hash": None, "session": worker(0)}})
        meta = self.managed("badmeta", badmeta, 0, worker(0)["session_id"])
        run_tmux(self.name, "set-option", "-w", "-t", meta["window_id"], "@agent_session_cwd", "{not json")
        # nosession: registered, with a Worker in the state, and no tmux session at all.
        nosession = board.project("nosession", seats=1)
        board.state(nosession, {"leader": leader(), "0": {"job_id": "TOOL-001", "git_hash": None, "session": worker(0)}})
        # wrongowner: a tmux session that agent-session never marked.
        board.project("unmarked", seats=1)
        run_tmux(self.name, "new-session", "-d", "-s", "unmarked", "sleep", "300")
        board.state(board.root / "unmarked/main", {"leader": leader(), "0": {"job_id": "TOOL-001", "git_hash": None, "session": worker(0)}})
        board.config.write_text(json.dumps(board.registry), encoding="utf-8")

    def rows(self):
        """Where each client is: `{client: (session name, window, pane)}`."""
        lines = run_tmux(self.name, "list-clients", "-F", "#{client_name}\t#{session_name}\t#{window_id}\t#{pane_id}").splitlines()
        return {row.split("\t")[0]: tuple(row.split("\t")[1:]) for row in lines}

    def reset(self):
        for client in self.rows():
            run_tmux(self.name, "switch-client", "-c", client, "-t", "home")

    def close(self):
        release_clients(self.clients)
        tmux_test_server.release(self.name)


@pytest.fixture
def scene(tmp_path):
    scene = Scene(tmp_path)
    try:
        yield scene
    finally:
        scene.close()


def python_switch(scene, kind, project, seat, client, config=None, socket=None):
    config = str(scene.board.config) if config is None else config
    socket = scene.socket if socket is None else socket
    if kind == "project":
        result = tmux_control.switch_project(config, project, client, socket)
    else:
        result = tmux_control.switch_seat(config, project, seat, client, socket)
    return None if result["ok"] else result["error"]["message"]


def rust_switch(scene, binary, kind, project, seat, client, config=None, socket=None):
    config = str(scene.board.config) if config is None else config
    socket = scene.socket if socket is None else socket
    command = [str(binary), f"switch-{kind}", "--config", config, "--project", project]
    if kind == "seat":
        command += ["--seat", str(seat)]
    if client is not None:
        command += ["--client", client]
    # The sidebar's tmux is PROJECT_BOARD_SOCKET; AGENT_SESSION_SOCKET points at nothing and must not be used.
    env = {**os.environ, "PROJECT_BOARD_SOCKET": socket, "AGENT_SESSION_SOCKET": "/nonexistent/agent-session.sock"}
    result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=command_timeout())
    if result.returncode == 0:
        assert result.stderr == ""
        return None
    assert result.returncode == 1, result.stderr
    assert result.stderr.startswith("project-board: ") and result.stderr.endswith("\n")
    return result.stderr[len("project-board: "):-1]


def same_outcome(scene, binary, kind, project, seat=None, client="first", **options):
    """Python and Rust leave the clients where the other did, or fail with the same message; returns the message."""
    if client in ("first", "second"):
        client = scene.first if client == "first" else scene.second
    scene.reset()
    start = scene.rows()
    expected_message = python_switch(scene, kind, project, seat, client, **options)
    expected_rows = scene.rows()
    scene.reset()
    message = rust_switch(scene, binary, kind, project, seat, client, **options)
    assert message == expected_message
    assert scene.rows() == expected_rows
    assert (expected_rows != start) == (expected_message is None)
    return expected_message, expected_rows


def test_a_project_click_moves_only_the_selected_client_to_the_project_session(scene, sidebar_bin):
    message, rows = same_outcome(scene, sidebar_bin, "project", "alpha")
    assert message is None
    assert rows[scene.first][0] == "alpha" and rows[scene.second][0] == "home"


@pytest.mark.parametrize("project, expected", [
    ("ghost", "The project is not registered."),
    ("nosession", "The project tmux session is unavailable."),
])
def test_a_project_that_cannot_be_shown_fails_with_the_same_message(scene, sidebar_bin, project, expected):
    assert same_outcome(scene, sidebar_bin, "project", project)[0] == expected


@pytest.mark.parametrize("seat, expected", [
    (0, None),
    (3, None),                                              # a remote seat: its local display window
    (1, "The Worker window is unavailable."),
    (2, "The seat has no Worker session."),
    (9, "The seat does not exist in this project."),
])
def test_a_seat_click_moves_the_client_to_the_verified_worker_pane(scene, sidebar_bin, seat, expected):
    message, rows = same_outcome(scene, sidebar_bin, "seat", "alpha", seat)
    assert message == expected
    if expected is None:
        assert rows[scene.first][2] == scene.windows["alpha"][seat]["pane_id"] and rows[scene.second][0] == "home"


@pytest.mark.parametrize("project, expected", [
    ("ghost", "The project is not registered."),
    ("dup", "The provider session matches more than one managed window."),
    ("foreign", "The tmux session belongs to another project base."),
    ("nostate", "The project state has not been initialized."),
    ("badmeta", "The managed window has invalid runtime metadata."),
    ("nosession", "The Worker window is unavailable."),
    ("unmarked", "The Worker window is unavailable."),
])
def test_a_seat_whose_window_cannot_be_verified_fails_with_the_same_message(scene, sidebar_bin, project, expected):
    message, rows = same_outcome(scene, sidebar_bin, "seat", project, 0)
    # `unmarked` has a tmux session without agent-session's owner marker: the owner check refuses it.
    assert message == ("The named tmux session is not managed by agent-session." if project == "unmarked" else expected)
    assert rows[scene.first][0] == "home"


@pytest.mark.parametrize("kind, project, seat", [("project", "alpha", None), ("seat", "alpha", 0)])
@pytest.mark.parametrize("client, expected", [
    ("second", None),
    (None, "Select a tmux client when none or several are attached"),         # two clients, none selected
    ("/dev/pts/9999", "The selected tmux client is not attached"),
    ("", "The selected tmux client is not attached"),
])
def test_the_client_is_checked_first(scene, sidebar_bin, kind, project, seat, client, expected):
    assert same_outcome(scene, sidebar_bin, kind, project, seat, client)[0] == expected


@pytest.mark.parametrize("kind, project, seat", [("project", "alpha", None), ("seat", "alpha", 0)])
def test_the_only_attached_client_is_used_when_none_is_selected(scene, sidebar_bin, kind, project, seat):
    release_clients(scene.clients[1:])
    scene.clients = scene.clients[:1]
    deadline = time.monotonic() + command_timeout()
    while len(scene.rows()) != 1 and time.monotonic() < deadline:
        time.sleep(0.1)
    assert list(scene.rows()) == [scene.first]
    assert same_outcome(scene, sidebar_bin, kind, project, seat, None)[0] is None


@pytest.mark.parametrize("kind, project, seat", [("project", "alpha", None), ("seat", "alpha", 0)])
def test_no_attached_client_is_an_error_for_both(scene, sidebar_bin, kind, project, seat):
    release_clients(scene.clients)
    scene.clients = []
    deadline = time.monotonic() + command_timeout()
    while scene.rows() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert same_outcome(scene, sidebar_bin, kind, project, seat, None)[0] == "Select a tmux client when none or several are attached"
    assert same_outcome(scene, sidebar_bin, kind, project, seat, "/dev/pts/1")[0] == "The selected tmux client is not attached"


@pytest.mark.parametrize("kind, seat", [("project", None), ("seat", 0)])
def test_registry_problems_come_after_the_client_check(scene, sidebar_bin, tmp_path, kind, seat):
    missing = str(tmp_path / "missing.json")
    assert same_outcome(scene, sidebar_bin, kind, "alpha", seat, config=missing)[0] == "The selected project registry is unavailable."
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    assert same_outcome(scene, sidebar_bin, kind, "alpha", seat, config=str(broken))[0] == "Cannot read a valid project registry."
    assert same_outcome(scene, sidebar_bin, kind, "alpha", seat, client="/dev/pts/9999", config=str(broken))[0] \
        == "The selected tmux client is not attached"


@pytest.mark.parametrize("kind, seat", [("project", None), ("seat", 0)])
@pytest.mark.parametrize("socket, expected", [
    ("/nonexistent/no-server.sock", "Tmux rejected the operation."),
    ("relative.sock", "A tmux socket path must be absolute."),
])
def test_a_tmux_that_cannot_be_read_gives_the_same_message(scene, sidebar_bin, kind, seat, socket, expected):
    assert same_outcome(scene, sidebar_bin, kind, "alpha", seat, client="/dev/pts/1", socket=socket)[0] == expected


# ------------------------------------------------------------------ how many tmux processes a click starts
SHIM = """\
#!/bin/sh
echo "$@" >> '{log}'
exec '{real}' "$@"
"""


def count_with_shim(scene, tmp_path, name, run):
    """The tmux processes `run(env)` starts: a shim ahead of tmux on PATH logs each call and runs the real tmux."""
    real = shutil.which("tmux")
    directory = tmp_path / name
    directory.mkdir()
    log = directory / "calls.log"
    shim = directory / "tmux"
    shim.write_text(SHIM.format(log=log, real=real), encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    scene.reset()
    run({**os.environ, "PATH": f"{directory}:{os.environ['PATH']}"})
    return len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0


def test_a_click_starts_few_tmux_processes_however_many_windows_there_are(scene, sidebar_bin, tmp_path):
    for number in range(8):                                  # more windows to read: the count must not follow
        scene.control.create_window("alpha", f"extra-{number}", scene.board.root / "alpha/main",
                                    window_meta(scene.board.root / "alpha/main", 2, str(uuid.uuid4())))
    command = [str(sidebar_bin), "--config", str(scene.board.config), "--project", "alpha"]

    def rust(kind, *extra):
        def run(env):
            result = subprocess.run([command[0], f"switch-{kind}", *command[1:], *extra, "--client", scene.first],
                                    capture_output=True, text=True, timeout=command_timeout(),
                                    env={**env, "PROJECT_BOARD_SOCKET": scene.socket})
            assert result.returncode == 0, result.stderr
        return run

    def python(kind, *extra):
        def run(env):
            old = os.environ.copy()
            os.environ.update(env)
            try:
                call = tmux_control.switch_project if kind == "project" else tmux_control.switch_seat
                result = call(str(scene.board.config), "alpha", *extra, scene.first, scene.socket)
                assert result["ok"], result
            finally:
                os.environ.clear()
                os.environ.update(old)
        return run

    project_rust = count_with_shim(scene, tmp_path, "rust-project", rust("project"))
    seat_rust = count_with_shim(scene, tmp_path, "rust-seat", rust("seat", "--seat", "0"))
    project_python = count_with_shim(scene, tmp_path, "python-project", python("project"))
    seat_python = count_with_shim(scene, tmp_path, "python-seat", python("seat", 0))
    # The clients and sessions in one process, the project's window options in one, and the switch itself.
    assert project_rust == 2 and seat_rust == 3
    assert project_rust < project_python and seat_rust < seat_python
