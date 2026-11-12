"""The three readers of the tmux record give the same answer (TMUX-004).

`tools/tmux.env` of a release names the tmux that project-agent runs. The rule that reads it (an environment value
wins per name, a missing file is a checkout, a file without a program names none) is written three times because
three kinds of program need it: Python (`agent_session/tmux_program.py`, the owner), the shell scripts of
`integrations/tmux` (`tools/tmux-launcher.sh`) and the Rust sidebar (`rust/src/tmuxprog.rs`). The product map
records the duplication (docs/project-team/README.md). This test runs the same cases through all three.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import board_testing  # noqa: F401  (adds the tools to sys.path)
import sys
sys.path.insert(0, str(Path(board_testing.TOOL).parent / "agent-session"))
from agent_session import tmux_program
from agent_session.errors import SessionError
from rust_binary import sidebar_binary
from wait_limit import command_timeout

TOOLS = Path(board_testing.TOOL).parent
NONE = "no tmux"            # the record names none: Python refuses, the shell script gets an empty TMUX_BIN, Rust an empty program
BOTH = "PROJECT_AGENT_TMUX=/a/tmux\nPROJECT_AGENT_TMUX_LD_LIBRARY_PATH=/l1:/l2\n"
P, L = "PROJECT_AGENT_TMUX", "PROJECT_AGENT_TMUX_LD_LIBRARY_PATH"

CASES = [
    ("a checkout has no record and runs tmux in PATH", None, {}, ("tmux", "")),
    ("the program and the library", BOTH, {}, ("/a/tmux", "/l1:/l2")),
    ("a last line without a newline", "PROJECT_AGENT_TMUX=/a/tmux", {}, ("/a/tmux", "")),
    ("the value is the rest of the line, never expanded", "PROJECT_AGENT_TMUX=/a b/$HOME/`x`/tmux \n",
     {}, ("/a b/$HOME/`x`/tmux ", "")),
    ("the last line of a name wins", "PROJECT_AGENT_TMUX=/first\nPROJECT_AGENT_TMUX=/second\n", {}, ("/second", "")),
    ("other names and a longer name are ignored", "OTHER=1\nPROJECT_AGENT_TMUXX=/no\nPROJECT_AGENT_TMUX=/a/tmux\n",
     {}, ("/a/tmux", "")),
    ("a program that is empty", "PROJECT_AGENT_TMUX=\nPROJECT_AGENT_TMUX_LD_LIBRARY_PATH=/l1\n", {}, NONE),
    ("an empty file", "", {}, NONE),
    ("the environment program wins and the library stays", BOTH, {P: "/e/tmux"}, ("/e/tmux", "/l1:/l2")),
    ("the environment library wins and the program stays", BOTH, {L: "/e/lib"}, ("/a/tmux", "/e/lib")),
    ("an environment program without a record", None, {P: "/e/tmux"}, ("/e/tmux", "")),
    ("an environment program over a record that names none", "PROJECT_AGENT_TMUX=\n", {P: "/e/tmux"}, ("/e/tmux", "")),
    ("an empty environment value is no value", BOTH, {P: "", L: ""}, ("/a/tmux", "/l1:/l2")),
]
IDS = [case[0] for case in CASES]


def _environment(variables):
    return {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/"), **variables}


def _write(directory, text):
    if text is not None:
        (directory / "tmux.env").write_text(text)


@pytest.mark.parametrize("name, text, variables, expected", CASES, ids=IDS)
def test_python(name, text, variables, expected, tmp_path, monkeypatch):
    for key in (P, L):
        monkeypatch.delenv(key, raising=False)
    for key, value in variables.items():
        monkeypatch.setenv(key, value)
    _write(tmp_path, text)
    monkeypatch.setattr(tmux_program, "RECORD", tmp_path / "tmux.env")
    tmux_program._record.cache_clear()
    try:
        if expected == NONE:
            with pytest.raises(SessionError) as error:
                tmux_program.settings()
            assert error.value.code == "tmux_unavailable"
        else:
            assert tmux_program.settings() == expected
    finally:
        tmux_program._record.cache_clear()


@pytest.mark.parametrize("shell", ["sh", "bash"])
@pytest.mark.parametrize("name, text, variables, expected", CASES, ids=IDS)
def test_shell_launcher(shell, name, text, variables, expected, tmp_path):
    _write(tmp_path, text)
    script = ('. "$1/tmux-launcher.sh"; project_agent_select_tmux "$2"; '
              'printf "%s\\n%s\\n%s" "$TMUX_BIN" "$PROJECT_AGENT_TMUX_LD_LIBRARY_PATH" "${LD_LIBRARY_PATH:-}"')
    done = subprocess.run([shell, "-c", script, shell, str(TOOLS), str(tmp_path)], env=_environment(variables),
                          capture_output=True, text=True, timeout=command_timeout())
    assert done.returncode == 0, done.stderr
    program, library, ld_path = done.stdout.split("\n")
    if expected == NONE:
        assert program == ""
    else:
        assert (program, library) == expected
        assert ld_path == library                       # the library directories lead LD_LIBRARY_PATH (it was empty)


@pytest.mark.parametrize("name, text, variables, expected", CASES, ids=IDS)
def test_rust_sidebar(name, text, variables, expected, tmp_path):
    """The binary reads `tools/tmux.env` from its own place: `tools/project-board/bin/<binary>`."""
    binary = tmp_path / "tools" / "project-board" / "bin" / "project-board-sidebar"
    binary.parent.mkdir(parents=True)
    shutil.copy2(sidebar_binary(), binary)
    _write(tmp_path / "tools", text)
    done = subprocess.run([str(binary), "tmux-program"], env=_environment(variables), capture_output=True, text=True,
                          timeout=command_timeout())
    assert done.returncode == 0, done.stderr
    found = json.loads(done.stdout)
    if expected == NONE:
        assert found["program"] == ""
    else:
        assert (found["program"], found["library"]) == expected
