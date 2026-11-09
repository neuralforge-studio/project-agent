"""Acceptance tests T20 and T21 of install-contract.md section 8.2: the installed tmux.conf read by a server.

The server is private (`-S` socket in a short temporary directory) and runs with the isolated HOME, so its
`~` is the test HOME and the user's server never sees a binding or a hook.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from harness import LIB
import tmux_test_server  # noqa: E402  (harness puts tools/tests on sys.path)

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
MOUSE_DEFAULT = r"select-pane -t = \; send-keys -M"


class Server:
    def __init__(self, home):
        self.home = home
        self.directory = Path(tempfile.mkdtemp(prefix="pi-t"))
        self.socket = self.directory / "s"
        tmux_test_server.watch_path(self.socket)
        self.run("new-session", "-d", "-s", "home", "sleep", "300")

    def run(self, *args, check=True):
        result = subprocess.run(["tmux", "-S", str(self.socket), "-f", "/dev/null", *args], capture_output=True,
                                text=True, timeout=30, env=self.home.env)
        assert not check or result.returncode == 0, result.stderr
        return result.stdout.strip()

    def key(self, table, key):
        return self.run("list-keys", "-T", table, key, check=False)

    def read_installed(self):
        self.run("source-file", str(self.home.path(LIB + "/tmux.conf")))

    def close(self):
        tmux_test_server.release_path(self.socket)
        shutil.rmtree(self.directory, ignore_errors=True)


@pytest.fixture
def server(home):
    created = Server(home)
    yield created
    created.close()


def check(home, server):
    return home.run("check", env={"AGENT_SESSION_SOCKET": str(server.socket)})


def test_t20_user_bindings_are_kept_and_reported_as_skipped(home, source, server):
    server.run("bind-key", "-T", "prefix", "B", "display-message", "mine")
    server.run("bind-key", "-T", "root", "MouseDown1Pane", "display-message", "mine too")
    assert home.run("install", source=source).returncode == 0
    server.read_installed()
    assert "display-message mine" in server.key("prefix", "B") and "tmux_project_board" not in server.key("prefix", "B")
    assert "display-message" in server.key("root", "MouseDown1Pane")
    assert "tmux_project_board" not in server.key("root", "MouseDown1Pane")
    result = check(home, server)
    assert result.returncode == 0, result.stdout
    assert "binding 건너뜀" in result.stdout and "prefix:B" in result.stdout and "root:MouseDown1Pane" in result.stdout


def test_t20_without_user_bindings_both_keys_are_the_product_bindings(home, source, server):
    assert MOUSE_DEFAULT in server.key("root", "MouseDown1Pane")
    assert home.run("install", source=source).returncode == 0
    server.read_installed()
    assert "tmux_project_board.sh toggle" in server.key("prefix", "B")
    assert "tmux_project_board.sh click" in server.key("root", "MouseDown1Pane")
    result = check(home, server)
    assert result.returncode == 0 and "binding 건너뜀" not in result.stdout


def test_t21_the_board_key_follows_the_option_set_before_reading(home, source, server):
    assert home.run("install", source=source).returncode == 0
    server.run("set-option", "-g", "@project_agent_board_key", "X")
    server.read_installed()
    assert "tmux_project_board.sh toggle" in server.key("prefix", "X")
    assert server.key("prefix", "B") == ""


def test_t20_the_server_reads_the_helpers_through_current(home, source, server):
    """The directory the server keeps is the `current` path, so an upgrade changes what the next call runs."""
    assert home.run("install", source=source).returncode == 0
    server.read_installed()
    kept = server.run("show-options", "-gqv", "@project_agent_tmux_dir")
    assert kept == str(home.path(LIB + "/current/integrations/tmux"))


def test_uninstall_prints_the_commands_that_undo_the_server_state_and_they_work(home, source, server):
    assert home.run("install", source=source).returncode == 0
    server.read_installed()
    server.run("bind-key", "-T", "prefix", "B", "display-message", "mine")        # a user key the product skipped
    server.read_installed()
    server.run("set-hook", "-g", "pane-died[agent-session]", "run-shell true")       # what agent-session writes at a launch
    result = home.run("uninstall", env={"AGENT_SESSION_SOCKET": str(server.socket)})
    assert result.returncode == 0, result.stderr
    commands = [line.strip() for line in result.stdout.splitlines() if line.strip().startswith("tmux ")]
    assert "tmux unbind-key -T prefix B" not in commands                          # skipped keys are not undone
    assert any("set-hook -gu 'client-attached[project-agent]'" in line for line in commands)
    assert "tmux set-hook -gwu 'pane-died[agent-session]'" in commands
    assert len([line for line in commands if "set-hook" in line]) == 9
    for line in commands:
        import shlex
        server.run(*shlex.split(line)[1:])
    assert "display-message mine" in server.key("prefix", "B")
    assert MOUSE_DEFAULT in server.key("root", "MouseDown1Pane")
    assert not server.run("show-hooks", "-g").count("[project-agent]")
    assert "[agent-session]" not in server.run("show-hooks", "-g", "pane-died")
    assert "project-agent" not in server.run("show-hooks", "-gw")


def test_uninstall_undoes_the_hook_name_that_agent_session_writes():
    import re
    from harness import REPO

    def constant(path, name):
        return re.search(r'^%s = "([^"]+)"' % name, (REPO / path).read_text(), re.MULTILINE).group(1)

    assert (constant("tools/agent-session/agent_session/tmux.py", "EXIT_HOOK")
            == constant("install/project_agent_install/commands.py", "AGENT_SESSION_HOOK"))
