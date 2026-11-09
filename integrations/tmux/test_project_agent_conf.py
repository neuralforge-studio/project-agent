"""Read project-agent.conf into isolated tmux servers and check what it leaves in them.

Every server is private (`tmux -L <unique name> -f /dev/null`) and is ended by `tmux_test_server` at the
end of the test (or when pytest dies), so the user's default server never gets a binding or a hook.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

TMUX_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TMUX_DIR.parents[1] / "tools" / "tests"))  # tmux_test_server, shared by every tool's tests
import tmux_test_server  # noqa: E402
FILES = ("project-agent.conf", "project_agent_bind.sh", "tmux_project_board.sh", "tmux_decide_status.sh", "tmux_decide_status.py")
LAUNCHER = TMUX_DIR.parents[1] / "tools" / "python-launcher.sh"
PRODUCT_PREFIX = "tmux_project_board.sh toggle"
PRODUCT_MOUSE = "tmux_project_board.sh click"
MOUSE_DEFAULT = r"select-pane -t = \; send-keys -M"

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")


class Server:
    def __init__(self):
        self.name = tmux_test_server.claim("pa-conf")
        self.run("new-session", "-d", "-s", "home", "sleep", "300")

    def run(self, *args, check=True):
        env = {key: value for key, value in os.environ.items() if key != "TMUX"}
        proc = subprocess.run(["tmux", "-L", self.name, "-f", "/dev/null", *args], env=env,
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
        lines = self.run("show-hooks", "-g").splitlines() + self.run("show-hooks", "-gw").splitlines()
        return [line for line in lines if " " in line]

    def state(self):
        return (self.run("list-keys"), self.hooks(), self.option("@project_agent_board_skipped"))

    def kill(self):
        tmux_test_server.release(self.name)


@pytest.fixture
def server():
    created = []

    def make():
        created.append(Server())
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
    python.write_text('#!/bin/sh\necho "%s decide-python $(basename "$1") nousersite=$PYTHONNOUSERSITE" >> "%s"\n' % (tag, log))
    (root / "tools" / "python.env").write_text("PROJECT_AGENT_PYTHON=%s\nPROJECT_AGENT_PYTHONPATH=\n" % python)
    for path in (board, python):
        path.chmod(0o755)
    return root


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
    tmux.run("new-window", "-d")
    wait_for(log, "r1 board sync --socket")
    command = tmux.key("prefix", "B").split(None, 4)[4]
    tmux.run("run-shell", "-C", command)
    wait_for(log, "r1 board toggle --socket")

    current.unlink()
    current.symlink_to(second)
    tmux.run("new-window", "-d")
    wait_for(log, "r2 board sync --socket")


def test_decide_status_entry_expands_to_the_decision_script(server, tmp_path):
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
        wait_for(log, "r1 decide-python tmux_decide_status.py nousersite=1", timeout=max(1, deadline - time.time()))
    finally:
        attach.kill()
        attach.wait()
