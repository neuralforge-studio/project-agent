"""The one wait limit of every tool's tests (TEST-003, TEST-013, TEST-016).

A test that waits for something it expects to happen (a command to return, a window to appear, a
process to exit) waits at most ``command_timeout()`` and takes no number of its own. The limit is a
ceiling for what never finishes, so a hung test fails instead of stalling the run; it asserts no
speed, and a wait that succeeds returns at once, so a long ceiling costs nothing.

A test that checks the limit itself (it expects ``timeout``) may take a short one of its own. It says
why on the same line, ``# short limit: <why>``, and keeps its result independent of the host's load
(``tools/test_wait_limits.py`` fails a numeric limit with no such reason).

A fixture command runs a real tmux pane and a Python child that imports agent_session, so its time
follows the host's load. Measured on this workstation:
- TEST-003: with three ``-n 8`` suites at once on a host at load 75-100 on 64 cores, one command took
  p50 9.8 s, p99 29.8 s and at most 38.0 s over 1350 commands, so 15 s failed about 95 of 704 tests.
- TEST-013: with ``-n 8`` agent-session and ``-n 8`` install tests at once at load 50-100, a ``start``
  took p50 24.6 s, p99 61.0 s and at most 80.3 s over 386 starts, and a two-slot ``resume`` 43 s, which
  shares one limit across its slots. 120 s left 1.5 times the maximum, and the 0.9.0 gate (load 92-143)
  passed it.
240 s is three times the TEST-013 maximum.
"""

import os

DEFAULT_TIMEOUT = 240


def command_timeout():
    """The wait limit in seconds; AGENT_SESSION_TEST_TIMEOUT overrides it."""
    return float(os.environ.get("AGENT_SESSION_TEST_TIMEOUT", DEFAULT_TIMEOUT))
