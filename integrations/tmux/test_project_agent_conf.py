"""Read project-agent.conf into isolated tmux servers and check what it leaves in them.

Every server is private (`tmux -L <unique name> -f /dev/null`) and is ended by `tmux_test_server` at the
end of the test (or when pytest dies), so the user's default server never gets a binding or a hook.
"""

import ast
import contextlib
import fcntl
import os
from pathlib import Path
import pty
import re
import shutil
import struct
import subprocess
import sys
import termios
import time

import pytest

TMUX_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TMUX_DIR.parents[1] / "tools" / "tests"))  # tmux_test_server, shared by every tool's tests
import tmux_test_server  # noqa: E402
FILES = ("project-agent.conf", "project-agent-main.conf", "project_agent_bind.sh", "project_agent_run.sh", "project_board_visibility.sh", "tmux_project_board.sh", "tmux_decide_status.sh", "tmux_decide_status.py")
LAUNCHER = TMUX_DIR.parents[1] / "tools" / "python-launcher.sh"
PRODUCT_PREFIX = "tmux_project_board.sh toggle"
PRODUCT_MOUSE = "tmux_project_board.sh click"
MOUSE_DEFAULT = r"select-pane -t = \; send-keys -M"

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")

# The user's cache and settings are not an input of these tests: tmux_decide_status.sh prints a valid view
# file of the user's status line without running the interpreter. Every tmux server below runs with these
# empty directories instead (set by the autouse fixture `empty_user_dirs`).
USER_DIRS = {}


@pytest.fixture(autouse=True)
def empty_user_dirs(tmp_path, monkeypatch):
    for name, variable in (("user-home", "HOME"), ("user-cache", "XDG_CACHE_HOME")):
        (tmp_path / name).mkdir()
        monkeypatch.setitem(USER_DIRS, variable, str(tmp_path / name))
    for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(variable, raising=False)


class Server:
    def __init__(self, binary="tmux"):
        self.binary = binary
        self.name = tmux_test_server.claim("pa-conf")
        self.run("new-session", "-d", "-s", "home", "sleep", "300")

    def run(self, *args, check=True):
        env = {**{key: value for key, value in os.environ.items() if key != "TMUX"}, **USER_DIRS}
        proc = subprocess.run([self.binary, "-L", self.name, "-f", "/dev/null", *args], env=env,
                              capture_output=True, text=True, timeout=20)
        if check and proc.returncode:
            raise AssertionError("tmux %s: %s" % (" ".join(args), proc.stderr))
        return proc.stdout.rstrip("\n") if check else proc

    def read(self, conf):
        self.run("source-file", str(conf))

    def option(self, name):
        return self.run("show-options", "-gqv", name)

    def key(self, table, key):
        proc = self.run("list-keys", "-T", table, key, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else ""

    def hooks(self):
        """Every hook that is set, in session scope (-g) and window scope (-gw)."""
        lines = self.run("show-hooks", "-g").splitlines() + self.run("show-hooks", "-gw", check=False).stdout.splitlines()   # tmux 2.x has no -w
        return [line for line in lines if " " in line]

    def state(self):
        return (self.run("list-keys"), self.hooks(), self.option("@project_agent_board_skipped"))

    def kill(self):
        if self.binary != "tmux":      # the cleanup of tmux_test_server speaks to the server with PATH's tmux, which an older server refuses
            subprocess.run([self.binary, "-L", self.name, "kill-server"], capture_output=True, timeout=10)
        tmux_test_server.release(self.name)


@pytest.fixture
def server():
    created = []

    def make(binary="tmux"):
        created.append(Server(binary))
        return created[-1]

    yield make
    for item in created:
        item.kill()


@pytest.fixture(params=["checkout", "installed"])
def conf(request, tmp_path):
    """The integration file as read from the development checkout and from an installed `current`."""
    if request.param == "checkout":
        return TMUX_DIR / "project-agent.conf"
    release = make_release(tmp_path / "releases" / "r1", "r1", tmp_path / "log")
    (tmp_path / "current").symlink_to(release)
    return tmp_path / "current" / "integrations" / "tmux" / "project-agent.conf"


def make_release(root, tag, log):
    """A release layout whose Board entry point and installed interpreter only record their calls.

    tools/python.env names the release's own interpreter, as the installer writes it. The decision
    wrapper must run the decision script with that interpreter.
    """
    target = root / "integrations" / "tmux"
    target.mkdir(parents=True)
    for name in FILES:
        shutil.copy2(TMUX_DIR / name, target / name)
    board = root / "tools" / "project-board" / "bin" / "project-board"
    board.parent.mkdir(parents=True)
    board.write_text('#!/bin/sh\necho "%s board $*" >> "%s"\n' % (tag, log))
    shutil.copy2(LAUNCHER, root / "tools")
    python = root / "installed-python"
    python.write_text('#!/bin/sh\necho "%s decide-python $1 $(basename "$2") nousersite=$PYTHONNOUSERSITE" >> "%s"\n' % (tag, log))
    (root / "tools" / "python.env").write_text("PROJECT_AGENT_PYTHON=%s\nPROJECT_AGENT_PYTHONPATH=\n" % python)
    for path in (board, python):
        path.chmod(0o755)
    return root


class Client:
    """A client of the server on a pty: what it types, and what tmux draws on it."""

    def __init__(self, master):
        self.master = master

    def send(self, data):
        os.write(self.master, data)

    def screen(self):
        data = b""
        while True:
            try:
                chunk = os.read(self.master, 65536)
            except BlockingIOError:
                return data.decode(errors="replace")
            if not chunk:
                return data.decode(errors="replace")
            data += chunk


@contextlib.contextmanager
def attached(tmux):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    os.set_blocking(master, False)
    env = {**os.environ, "TERM": "xterm-256color"}
    env.pop("TMUX", None)
    client = subprocess.Popen(["tmux", "-L", tmux.name, "-f", "/dev/null", "attach-session", "-t", "home"],
                              stdin=slave, stdout=slave, stderr=slave, start_new_session=True, env=env)
    os.close(slave)
    try:
        yield Client(master)
    finally:
        client.terminate()
        os.close(master)


def assert_no_view(tmux, *panes):
    """No pane shows the output of a job: not in view mode, and nothing is in its mode buffer."""
    for target in panes:
        assert tmux.run("display-message", "-p", "-t", target, "#{pane_mode}") == ""
        assert tmux.run("capture-pane", "-M", "-p", "-t", target).strip() == ""


def wait_for(path, text, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists() and text in path.read_text():
            return
        time.sleep(0.1)
    raise AssertionError("%r not in %s: %s" % (text, path, path.read_text() if path.exists() else ""))


def test_without_user_bindings_the_keys_are_the_product_bindings(server, conf):
    tmux = server()
    assert tmux.key("root", "MouseDown1Pane").endswith(MOUSE_DEFAULT)
    assert tmux.key("prefix", "B") == ""
    tmux.read(conf)
    assert PRODUCT_PREFIX in tmux.key("prefix", "B")
    assert PRODUCT_MOUSE in tmux.key("root", "MouseDown1Pane")
    assert tmux.option("@project_agent_board_skipped") == ""


def test_user_bindings_stay_and_are_reported(server, conf):
    tmux = server()
    tmux.run("bind-key", "B", "display-message", "user-prefix")
    tmux.run("bind-key", "-T", "root", "MouseDown1Pane", "display-message", "user-mouse")
    before = (tmux.key("prefix", "B"), tmux.key("root", "MouseDown1Pane"))
    tmux.read(conf)
    assert (tmux.key("prefix", "B"), tmux.key("root", "MouseDown1Pane")) == before
    assert "user-prefix" in before[0] and "user-mouse" in before[1]
    assert tmux.option("@project_agent_board_skipped").split() == ["prefix:B", "root:MouseDown1Pane"]


def test_only_the_user_bound_key_is_skipped(server, conf):
    tmux = server()
    tmux.run("bind-key", "B", "display-message", "user-prefix")
    tmux.read(conf)
    assert "user-prefix" in tmux.key("prefix", "B")
    assert PRODUCT_MOUSE in tmux.key("root", "MouseDown1Pane")
    assert tmux.option("@project_agent_board_skipped") == "prefix:B"


def test_the_tmux_default_mouse_binding_is_replaced(server, conf):
    tmux = server()
    assert tmux.key("root", "MouseDown1Pane").endswith(MOUSE_DEFAULT)
    tmux.read(conf)
    assert PRODUCT_MOUSE in tmux.key("root", "MouseDown1Pane")


def test_a_click_on_the_board_leaves_no_output_in_the_active_pane(server, tmp_path):
    """BOARD-006: a failing click job (a click on no item) must not show up in the pane that is active.

    A click on the Board pane does not select it, so the pane that run-shell reports to is another one.
    """
    log = tmp_path / "log"
    release = make_release(tmp_path / "releases" / "r1", "r1", log)
    board = release / "tools" / "project-board" / "bin" / "project-board"
    board.write_text('#!/bin/sh\necho "board $*" >> "%s"\necho no item to click >&2\nexit 1\n' % log)
    tmux = server()
    tmux.read(release / "integrations" / "tmux" / "project-agent.conf")
    tmux.run("set-option", "-g", "mouse", "on")
    work = tmux.run("display-message", "-p", "#{pane_id}")
    pane = tmux.run("split-window", "-d", "-h", "-b", "-l", "20", "-P", "-F", "#{pane_id}", "sleep", "300")
    tmux.run("set-option", "-w", "@project_board_pane", pane)

    with attached(tmux) as client:
        time.sleep(1.0)
        client.send(b"\x1b[<0;5;5M\x1b[<0;5;5m")               # press and release inside the Board pane
        wait_for(log, "board click --client")
        time.sleep(1.0)                                         # run-shell reports when the job ends
        assert tmux.run("display-message", "-p", "#{pane_id}") == work   # the click did not select the Board
        assert_no_view(tmux, work, pane)


RUN_SHELL = re.compile(r"""run-shell(?P<flags>(?: -[a-zA-Z]+)*) (?P<quote>['"])(?P<job>[^'"]*)(?P=quote)""")   # tmux shows what it keeps with """


def failing_release(tmp_path, log):
    """A release whose Board entry point fails at every call, as a Board that cannot reach its session does."""
    release = make_release(tmp_path / "releases" / "r1", "r1", log)
    board = release / "tools" / "project-board" / "bin" / "project-board"
    board.write_text('#!/bin/sh\necho "board $*" >> "%s"\necho Board cannot reach its session >&2\nexit 1\n' % log)
    return release


def test_every_run_shell_job_goes_through_the_run_script(server, conf):
    """BOARD-010: a `run-shell` job shows its output and a nonzero exit in the user's active pane, so the
    job of the integration (a shell command, `run-shell -C` is a tmux command) starts with project_agent_run.sh."""
    shell_jobs = 0
    for path in sorted(TMUX_DIR.glob("*.conf")) + sorted(TMUX_DIR.glob("*.sh")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if line.lstrip().startswith("#") or "run-shell" not in line:
                continue
            found = RUN_SHELL.search(line)
            assert found, "%s:%d: a run-shell the rule cannot read: %s" % (path.name, number, line)
            if " -C" in found["flags"]:
                continue
            shell_jobs += 1
            assert re.match(r"#\{q:@project_agent_tmux_dir\}/project_agent_run\.sh (hook|key|drop) ", found["job"]) \
                or path.name == "project_agent_bind.sh" and found["job"].startswith("$RUN "), \
                "%s:%d: a run-shell job outside project_agent_run.sh: %s" % (path.name, number, line)
    assert shell_jobs >= 14
    # What the server keeps says the same, with the mode each kind of job needs.
    tmux = server()
    tmux.read(conf)
    shell_hooks = [found for line in tmux.hooks() for found in RUN_SHELL.finditer(line) if " -C" not in found["flags"]]
    assert shell_hooks and all("project_agent_run.sh hook " in found["job"].replace("\\", "") for found in shell_hooks)
    assert "project_agent_run.sh key " in tmux.key("prefix", "B").replace("\\", "")
    assert "project_agent_run.sh drop " in tmux.key("root", "MouseDown1Pane").replace("\\", "")


PRODUCT_ROOT = TMUX_DIR.parents[1]


def product_files(root):
    """The product code under `root`: every file but the tests and the caches."""
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(PRODUCT_ROOT).parts
        if path.is_file() and "__pycache__" not in relative and "tests" not in relative \
                and not path.name.startswith(("test_", "conftest")):
            yield path


def run_shell_functions(path):
    """For each place a Python file writes a `run-shell` (a string with the word; docstrings only describe),
    the function that holds it, and whether that function builds its job with `quiet_shell`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    docstrings = {node.body[0].value for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "run-shell" in node.value \
                and node not in docstrings:
            holder = node
            while holder in parents and not isinstance(holder, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                holder = parents[holder]
            names = {n.id for n in ast.walk(holder) if isinstance(n, ast.Name)}
            yield path, node.lineno, getattr(holder, "name", "<module>"), "quiet_shell" in names


def test_every_run_shell_the_product_makes_leaves_nothing_in_the_work_pane():
    """BOARD-011: the rule of BOARD-010 holds for the whole product, not only the integration files. Every
    `run-shell` that `tools/**` or `integrations/**` can leave in a user's tmux server is a job of the integration
    (the test above) or one that the tools build with `agent_session.tmux.quiet_shell` (output discarded, exit 0,
    the failure recorded in `@project_agent_last_error`, shown to a person's client)."""
    found = []
    for root in (PRODUCT_ROOT / "tools", PRODUCT_ROOT / "integrations"):
        for path in product_files(root):
            if path.suffix == ".py":
                found.extend(run_shell_functions(path))
            elif root.name == "tools":
                assert "run-shell" not in path.read_text(encoding="utf-8", errors="replace"), \
                    "%s: a run-shell the rule cannot read" % path.relative_to(PRODUCT_ROOT)
    assert found, "the scan found no run-shell in the tools: the check cannot see the product"
    for path, number, function, quiet in found:
        assert quiet, "%s:%d: %s() writes a run-shell without quiet_shell" % (path.relative_to(PRODUCT_ROOT), number, function)


def test_the_error_record_of_the_tools_is_the_option_the_integration_writes():
    """`quiet_shell` and project_agent_run.sh record a failure in one option, which the contract names."""
    sys.path.insert(0, str(PRODUCT_ROOT / "tools" / "agent-session"))
    from agent_session.tmux import LAST_ERROR_OPTION

    assert LAST_ERROR_OPTION in (TMUX_DIR / "project_agent_run.sh").read_text()
    assert LAST_ERROR_OPTION in (PRODUCT_ROOT / "docs/project-team/install-contract.md").read_text()


def test_a_failing_hook_job_leaves_nothing_in_the_active_pane_and_is_recorded(server, tmp_path):
    """BOARD-010: the hooks run at every window change, so a failure that repeats must not cover the work pane."""
    log = tmp_path / "log"
    release = failing_release(tmp_path, log)
    tmux = server()
    tmux.read(release / "integrations" / "tmux" / "project-agent.conf")
    tmux.run("set-option", "-g", "@project_board_enabled", "1")   # the Board is on and this window has no Board pane: sync runs
    work = tmux.run("display-message", "-p", "#{pane_id}")
    with attached(tmux):
        time.sleep(1.0)
        tmux.run("new-window", "-d")                              # window-created runs sync, which fails
        wait_for(log, "board sync")
        time.sleep(1.0)                                           # run-shell reports when the job ends
        assert_no_view(tmux, work)
    assert re.fullmatch(r"\S+ \S+ tmux_project_board.sh failed \(exit 1\): Board cannot reach its session",
                        tmux.option("@project_agent_last_error"))


def test_a_failing_board_key_tells_the_user_without_covering_a_pane(server, tmp_path):
    log = tmp_path / "log"
    release = failing_release(tmp_path, log)
    tmux = server()
    tmux.read(release / "integrations" / "tmux" / "project-agent.conf")
    work = tmux.run("display-message", "-p", "#{pane_id}")
    with attached(tmux) as client:
        time.sleep(1.0)
        client.screen()
        client.send(b"\x02B")                                    # prefix, then the Board key
        wait_for(log, "board toggle")
        time.sleep(1.0)
        screen = client.screen()
        assert_no_view(tmux, work)
    assert "project-agent: tmux_project_board.sh failed (exit 1): Board cannot" in screen   # the status line is 80 columns wide
    assert "tmux_project_board.sh failed (exit 1)" in tmux.option("@project_agent_last_error")


def run_script(*args, socket="/nonexistent/socket"):
    return subprocess.run([str(TMUX_DIR / "project_agent_run.sh"), *args[:1], socket, *args[1:]],
                          capture_output=True, text=True, timeout=20)


def test_the_run_script_prints_nothing_and_exits_zero_whatever_the_job_does():
    for mode in ("hook", "key", "drop"):
        for job in (["true"], ["sh", "-c", "echo out; echo err >&2; exit 7"], ["/nonexistent/job"]):
            proc = run_script(mode, *job)
            assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", ""), (mode, job)


def test_the_run_script_rejects_a_call_the_integration_does_not_make():
    assert run_script("loud", "true").returncode == 2
    assert subprocess.run([str(TMUX_DIR / "project_agent_run.sh"), "hook"], capture_output=True).returncode == 2


def test_a_drop_job_records_nothing_and_a_hook_job_records_its_first_line(server):
    tmux = server()
    socket = tmux.run("display-message", "-p", "#{socket_path}")
    assert run_script("drop", "sh", "-c", "echo gone >&2; exit 1", socket=socket).returncode == 0
    assert tmux.option("@project_agent_last_error") == ""
    assert run_script("hook", "sh", "-c", "printf '\\n  first #{x}\\nsecond\\n'; exit 4", socket=socket).returncode == 0
    assert re.fullmatch(r"\S+ \S+ sh failed \(exit 4\): first #\{x\}", tmux.option("@project_agent_last_error"))


def test_board_key_option_selects_the_prefix_key(server, conf):
    tmux = server()
    tmux.run("set-option", "-g", "@project_agent_board_key", "X")
    tmux.read(conf)
    assert PRODUCT_PREFIX in tmux.key("prefix", "X")
    assert tmux.key("prefix", "B") == ""
    assert tmux.option("@project_agent_board_skipped") == ""


def test_reading_twice_leaves_the_same_state(server, conf):
    tmux = server()
    tmux.read(conf)
    once = tmux.state()
    tmux.read(conf)
    assert tmux.state() == once
    tmux = server()
    tmux.run("bind-key", "B", "display-message", "user-prefix")
    tmux.read(conf)
    once = tmux.state()
    tmux.read(conf)
    assert tmux.state() == once


def test_user_hooks_stay_and_no_generic_board_hook_is_left(server, conf):
    tmux = server()
    user = {
        "client-attached": "display-message user-index0",
        "client-attached[mine]": "display-message user-named",
        "client-attached[7]": "display-message user-index7",
        "pane-died[board-of-mine]": "display-message user-died",
    }
    for name, command in user.items():
        tmux.run("set-hook", "-g", name, command)
    tmux.read(conf)
    hooks = tmux.hooks()
    for name, command in user.items():
        key = name if "[" in name else name + "[0]"
        assert "%s %s" % (key, command) in hooks
    assert not [line for line in hooks if "[board]" in line]
    events = ("client-attached", "client-detached", "client-session-changed",
              "session-window-changed", "window-created", "window-closed",
              "after-resize-pane", "pane-died")
    assert all(any(line.startswith("%s[project-agent] " % event) for line in hooks) for event in events)


def test_a_window_change_starts_sync_only_when_the_window_lacks_its_board_pane(server, tmp_path):
    """BOARD-002: sync costs a process start, so an event that has nothing to do must not start it."""
    log = tmp_path / "log"
    release = make_release(tmp_path / "releases" / "r1", "r1", log)
    tmux = server()
    tmux.read(release / "integrations" / "tmux" / "project-agent.conf")
    tmux.run("new-window", "-d")
    with_board, without_board = tmux.run("list-windows", "-F", "#{window_id}").split()
    pane = tmux.run("split-window", "-d", "-h", "-t", with_board, "-P", "-F", "#{pane_id}", "sleep", "300")
    tmux.run("set-option", "-w", "-t", with_board, "@project_board_pane", pane)
    tmux.run("set-option", "-g", "@project_board_width", tmux.run("display-message", "-p", "-t", pane, "#{pane_width}"))

    def syncs():
        return log.read_text().count("board sync") if log.exists() else 0

    def move(window):
        tmux.run("select-window", "-t", window)
        time.sleep(1.0)                      # a hook runs as a background job: give it the time it would need

    move(without_board)
    assert syncs() == 0                      # the Board is off: nothing to reconcile
    tmux.run("set-option", "-g", "@project_board_enabled", "1")
    tmux.run("set-option", "-p", "-t", pane, "@project_board_managed", "1")
    move(with_board)
    assert syncs() == 0                      # the window shows its Board pane at the saved width
    # The same event ran the visibility script: no client is attached, so no client shows the pane.
    assert tmux.run("show-options", "-pqv", "-t", pane, "@project_board_visible") == "0"
    move(without_board)
    wait_for(log, "board sync")              # no Board pane here yet
    assert syncs() == 1
    tmux.run("set-option", "-g", "@project_board_width", "99")
    move(with_board)
    wait_for_count = time.time() + 10
    while syncs() < 2 and time.time() < wait_for_count:
        time.sleep(0.1)
    assert syncs() == 2                      # a width other than the saved one is reconciled


def test_visibility_script_wakes_only_the_ready_panes_whose_window_state_changed(server, tmp_path):
    """BOARD-002: a Board pane nobody watches stops reading; the hook tells it with SIGUSR1."""
    tmux = server()
    tmux.run("new-session", "-d", "-s", "two", "sleep", "300")
    windows = {name: tmux.run("display-message", "-p", "-t", name, "#{window_id}") for name in ("home", "two")}
    # A "Board" that counts the signals it gets; the third pane has not marked itself ready.
    command = 'trap "echo got >> %s/$0" USR1; while :; do sleep 0.1; done'
    panes = {}
    for key, window in (("home", windows["home"]), ("two", windows["two"]), ("late", windows["two"])):
        panes[key] = tmux.run("split-window", "-d", "-t", window, "-P", "-F", "#{pane_id}", "sh", "-c", command % tmp_path, key)
        tmux.run("set-option", "-p", "-t", panes[key], "@project_board_managed", "1")
        if key != "late":
            tmux.run("set-option", "-p", "-t", panes[key], "@project_board_ready", "1")
    time.sleep(0.5)                                            # the shells install their trap

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    env = {**os.environ, "TERM": "xterm-256color"}
    env.pop("TMUX", None)
    client = subprocess.Popen(["tmux", "-L", tmux.name, "-f", "/dev/null", "attach-session", "-t", "home"],
                              stdin=slave, stdout=slave, stderr=slave, start_new_session=True, env=env)
    os.close(slave)
    try:
        time.sleep(1.0)
        socket = tmux.run("display-message", "-p", "#{socket_path}")
        script = TMUX_DIR / "project_board_visibility.sh"

        def run():
            subprocess.run([str(script), "--socket", socket], check=True, timeout=20)
            time.sleep(0.6)                                    # a signal is handled by the shell between sleeps

        def got(key):
            path = tmp_path / key
            return path.read_text().count("got") if path.exists() else 0

        def option(pane, name):
            return tmux.run("show-options", "-pqv", "-t", pane, name)

        run()
        assert option(panes["home"], "@project_board_visible") == ""        # shown, as an unset pane is assumed to be
        assert option(panes["two"], "@project_board_visible") == "0"
        assert option(panes["late"], "@project_board_visible") == "0"        # recorded even though not signalled
        assert tmux.run("show-options", "-wqv", "-t", windows["home"], "@project_board_seen").isdigit()
        assert tmux.run("show-options", "-wqv", "-t", windows["two"], "@project_board_seen") == ""
        assert (got("home"), got("two"), got("late")) == (0, 1, 0)
        run()
        assert (got("home"), got("two"), got("late")) == (0, 1, 0)           # nothing changed: nobody is woken
        tmux.run("switch-client", "-c", tmux.run("list-clients", "-F", "#{client_name}"), "-t", "two")
        run()
        assert option(panes["home"], "@project_board_visible") == "0"
        assert option(panes["two"], "@project_board_visible") == "1"
        assert (got("home"), got("two"), got("late")) == (1, 2, 0)
    finally:
        client.terminate()
        os.close(master)


def test_installed_link_is_kept_and_the_next_call_follows_an_upgrade(server, tmp_path):
    log = tmp_path / "log"
    first = make_release(tmp_path / "releases" / "r1", "r1", log)
    second = make_release(tmp_path / "releases" / "r2", "r2", log)
    current = tmp_path / "current"
    current.symlink_to(first)
    tmux = server()
    tmux.read(current / "integrations" / "tmux" / "project-agent.conf")
    assert tmux.option("@project_agent_tmux_dir") == str(current / "integrations" / "tmux")

    # The hook and the key binding run the helper that sits next to the conf that was read.
    # A hook runs sync only while the Board is on and the window has no Board pane yet.
    tmux.run("set-option", "-g", "@project_board_enabled", "1")
    tmux.run("new-window", "-d")
    wait_for(log, "r1 board sync --socket")
    command = tmux.key("prefix", "B").split(None, 4)[4]
    tmux.run("run-shell", "-C", command)
    wait_for(log, "r1 board toggle --socket")

    current.unlink()
    current.symlink_to(second)
    tmux.run("new-window", "-d")
    wait_for(log, "r2 board sync --socket")


@pytest.mark.parametrize("user_view", [False, True], ids=["no-user-view", "valid-user-view"])
def test_decide_status_entry_expands_to_the_decision_script(server, tmp_path, monkeypatch, user_view):
    """A valid view in the user's cache (`$XDG_CACHE_HOME`) does not make the status line skip the interpreter."""
    if user_view:
        cache = tmp_path / "planted-cache"
        cache.mkdir()
        (cache / "tmux-decide-status.view").write_text("%d\nUSER-STATUS-LINE" % (time.time() + 3600))
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    log = tmp_path / "log"
    release = make_release(tmp_path / "releases" / "r1", "r1", log)
    (tmp_path / "current").symlink_to(release)
    tmux = server()
    tmux.read(tmp_path / "current" / "integrations" / "tmux" / "project-agent.conf")
    tmux.run("set-option", "-g", "status-right", "#{E:@project_agent_decide_status}")
    tmux.run("set-option", "-g", "status-interval", "1")
    # A client that renders status-right is what runs `#()` jobs.
    deadline = time.time() + 10
    attach = subprocess.Popen(["script", "-qc", "tmux -L %s attach-session -t home" % tmux.name, "/dev/null"],
                              stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for(log, "r1 decide-python -S tmux_decide_status.py nousersite=1", timeout=max(1, deadline - time.time()))
    finally:
        attach.kill()
        attach.wait()


# ---------------------------------------------------------------- the minimum tmux version (contract 3.2)

MINIMUM = re.compile(r"^set-option -g @project_agent_tmux_min '(.+)'$", re.MULTILINE)
REFUSAL = re.compile(r"project-agent needs tmux (\S+) or newer: put (\S+) first in PATH")


def read_collecting_errors(tmux, conf):
    proc = tmux.run("source-file", str(conf), check=False)
    return proc.stdout + proc.stderr


def with_minimum(tmp_path, version):
    """A copy of the integration files whose minimum tmux version is `version`."""
    target = tmp_path / "copy"
    target.mkdir()
    for name in FILES:
        shutil.copy2(TMUX_DIR / name, target / name)
    conf = target / "project-agent.conf"
    conf.write_text(MINIMUM.sub("set-option -g @project_agent_tmux_min '%s'" % version, conf.read_text()))
    return conf


def leaves_nothing(tmux, before):
    assert tmux.state() == before
    assert tmux.option("@project_agent_tmux_min") == "" and tmux.option("@project_agent_tmux_dir") == ""
    assert tmux.option("@project_agent_decide_status") == ""


def test_a_tmux_older_than_the_minimum_gets_one_line_and_binds_nothing(server, tmp_path):
    tmux = server()
    tmux.run("bind-key", "B", "display-message", "user-prefix")
    before = tmux.state()
    output = read_collecting_errors(tmux, with_minimum(tmp_path, "99.0"))
    assert output.strip().count("\n") == 0
    assert REFUSAL.search(output) is None or REFUSAL.search(output).group(1) == "3.8"   # the line is the file's own text
    leaves_nothing(tmux, before)


def test_a_tmux_that_is_the_minimum_reads_the_integration(server, tmp_path):
    tmux = server()
    version = tmux.run("display-message", "-p", "#{version}")
    tmux.read(with_minimum(tmp_path, version))
    assert PRODUCT_PREFIX in tmux.key("prefix", "B")
    assert tmux.option("@project_agent_tmux_min") == ""


def test_the_refusal_names_the_minimum_and_the_company_tmux():
    conf = (TMUX_DIR / "project-agent.conf").read_text()
    minimum = MINIMUM.search(conf).group(1)
    found = REFUSAL.search(conf)
    assert found and found.group(1) == minimum
    assert found.group(2) == "/primehome/tools/Inhouse/tmux/latest/bin"


def old_tmux():
    """Any tmux of this host that is older than the minimum, to read the real file with."""
    minimum = MINIMUM.search((TMUX_DIR / "project-agent.conf").read_text()).group(1)
    for candidate in ("/usr/bin/tmux", "/usr/local/bin/tmux", "/bin/tmux"):
        if not os.access(candidate, os.X_OK):
            continue
        word = subprocess.run([candidate, "-V"], capture_output=True, text=True).stdout.split()[-1]
        found = re.match(r"(?:next-)?(\d+)\.(\d+)", word)
        if found and (int(found.group(1)), int(found.group(2))) < tuple(int(part) for part in minimum.split(".")[:2]):
            return candidate
    return None


@pytest.mark.skipif(old_tmux() is None, reason="this host has no tmux older than the minimum")
def test_an_installed_old_tmux_reads_the_real_file_without_a_parse_error(server):
    tmux = server(old_tmux())
    before = tmux.state()
    output = read_collecting_errors(tmux, TMUX_DIR / "project-agent.conf")
    assert REFUSAL.search(output) and output.strip().count("\n") == 0
    leaves_nothing(tmux, before)
