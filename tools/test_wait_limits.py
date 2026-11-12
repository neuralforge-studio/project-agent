"""No test waits for success with a number of its own (TEST-016).

``tools/tests/wait_limit.py`` owns the wait limit. A test that expects something to happen waits at most
``command_timeout()``; a number it picked fails when the host is loaded (a 20 s ``restart`` failed at
load 80-90 while the limit's measured need was 80 s). This test reads every test file of the five
verification commands and names the places where a number is a wait limit:

- a ``timeout=``, ``limit=`` or ``seconds=`` argument that is a number, and such a parameter of a polling
  function (one that reads a clock) whose default is a number;
- a number added to a clock read (``time.monotonic() + 10``), the deadline of a polling loop;
- a number passed to ``.wait()``, ``.join()``, ``.communicate()`` or ``.settimeout()``.

A test that checks the limit itself may keep a short one if the same line says why:
``# short limit: <why>``. Such a test expects ``timeout`` and stays correct under any load. A number that is
data and no wait (a value the test passes on and then compares) says ``# not a wait: <why>``.
"""

import ast
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEST_TREES = ("tools/agent-session/tests", "tools/project-item/tests", "tools/project-board/tests",
              "install/tests")
SHARED = ("tools/test_*.py", "integrations/tmux/test_*.py", "tools/conftest.py", "tools/tests/*.py")     # tools/tests/perf is a development tool; integrations/tmux's other .py files are product
LIMIT_PARAMETERS = {"timeout", "limit", "seconds"}
CLOCKS = {"monotonic", "time", "perf_counter"}
WAITERS = {"wait", "join", "communicate", "settimeout"}
REASON = re.compile(r"#\s*(short limit|not a wait):\s*\S")


def is_number(node):
    if isinstance(node, ast.UnaryOp):
        node = node.operand
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool)


def is_clock_read(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in CLOCKS
            and not node.args)


def numeric_limits(tree):
    """Yield (node, what) for each place where a number is a wait limit."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in LIMIT_PARAMETERS and is_number(keyword.value):
                    yield keyword.value, "%s=%s" % (keyword.arg, ast.unparse(keyword.value))
            if (isinstance(node.func, ast.Attribute) and node.func.attr in WAITERS and node.args
                    and is_number(node.args[0])):
                yield node.args[0], ".%s(%s)" % (node.func.attr, ast.unparse(node.args[0]))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            if (is_clock_read(node.left) and is_number(node.right)) or (is_clock_read(node.right) and is_number(node.left)):
                yield node, ast.unparse(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            reads = {n.id for statement in node.body for n in ast.walk(statement) if isinstance(n, ast.Name)}
            polls = any(is_clock_read(n) for statement in node.body for n in ast.walk(statement))
            positional = node.args.posonlyargs + node.args.args
            defaults = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)
            pairs = list(zip(positional, defaults)) + list(zip(node.args.kwonlyargs, node.args.kw_defaults))
            for argument, default in pairs:
                if (argument.arg in LIMIT_PARAMETERS and default is not None and is_number(default)
                        and argument.arg in reads and polls):
                    yield default, "%s=%s" % (argument.arg, ast.unparse(default))


def unexplained(source):
    """Return "line: what" for each numeric wait limit in ``source`` with no ``# short limit:`` reason."""
    lines = source.splitlines()
    found = []
    for node, what in numeric_limits(ast.parse(source)):
        span = lines[node.lineno - 1:getattr(node, "end_lineno", node.lineno)]
        if not any(REASON.search(line) for line in span):
            found.append("%d: %s" % (node.lineno, what))
    return sorted(set(found), key=lambda item: int(item.split(":")[0]))


def scanned_files():
    paths = [path for tree in TEST_TREES for path in (ROOT / tree).rglob("*.py")]
    paths += [path for pattern in SHARED for path in ROOT.glob(pattern)]
    return sorted({path for path in paths if "__pycache__" not in path.parts})


def test_scanned_files_cover_the_verification_commands():
    scanned = {path.relative_to(ROOT).as_posix() for path in scanned_files()}
    assert {"tools/agent-session/tests/test_lifecycle.py", "tools/project-board/tests/test_sidebar_binary.py",
            "install/tests/harness.py", "integrations/tmux/test_project_agent_conf.py",
            "tools/test_wait_limits.py", "tools/tests/wait_limit.py"} <= scanned


@pytest.mark.parametrize("path", [pytest.param(path, id=path.relative_to(ROOT).as_posix()) for path in scanned_files()])
def test_a_wait_limit_is_the_one_wait_limit_or_says_why_it_is_short(path):
    found = unexplained(path.read_text(encoding="utf-8"))
    assert not found, (
        "%s: a number is a wait limit. A wait that expects success takes command_timeout() "
        "(tools/tests/wait_limit.py); a check of the limit itself says `# short limit: <why>` on the line:\n  %s"
        % (path.relative_to(ROOT), "\n  ".join(found)))


@pytest.mark.parametrize("source, expected", [
    ("env.manager(timeout=20).start('x')", ["1: timeout=20"]),
    ("env.manager(timeout=command_timeout()).start('x')", []),
    ("deadline = time.monotonic() + 10", ["1: time.monotonic() + 10"]),
    ("deadline = time.monotonic() + command_timeout()", []),
    ("deadline = time.time() + 5", ["1: time.time() + 5"]),
    ("child.wait(timeout=5)", ["1: timeout=5"]),
    ("child.wait(5)", ["1: .wait(5)"]),
    ("thread.join(2)", ["1: .join(2)"]),
    ("def wait(self, timeout=10):\n    end = time.monotonic() + timeout\n    return end", ["1: timeout=10"]),
    ("def wait(self, timeout=10):\n    return poll(timeout)", []),
    ("def observe(self, session, timeout=30):\n    return None", []),
    ("def wait(self, timeout=None):\n    return poll(timeout)", []),
    ("m.control(timeout=2)  # short limit: stop must time out", []),
    ("m.control(timeout=2)  # short limit:", ["1: timeout=2"]),
    ("send(text, timeout=11)  # not a wait: the value the provider must forward", []),
    ("m.control(\n    timeout=2)  # short limit: the stop never ends", []),
    ("x = time.monotonic() - started < 3", []),
    ("subprocess.run(command, timeout=60)", ["1: timeout=60"]),
])
def test_the_scan_names_a_numeric_wait_limit_and_accepts_a_stated_reason(source, expected):
    assert unexplained(source) == expected
