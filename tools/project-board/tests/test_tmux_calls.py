"""How many tmux processes one Board run-fact refresh starts (SESSION-010).

The refresh (`model.liveness`) judges every registered project. It used to start tmux for each slot, 4496 times
for 16 projects of 16 seats (more than a minute on a loaded host); it now reads the server once for all of them. The
number must not depend on the number of projects or seats. The fleet of live runs is built by agent-session's
test helper `fleet.py`.
"""
import sys

import pytest

from board_testing import TOOL
from project_board import model  # noqa: E402  (puts agent_session on the path)
sys.path.insert(0, str(TOOL.parent / "agent-session" / "tests"))
import fleet  # noqa: E402
import tmux_test_server  # noqa: E402
from agent_session import tmux as tmux_module  # noqa: E402

# The server's sessions, windows and panes in one tmux process, then the window options of the current runs
# in one more. The names of those options are asked for from what the product writes (`tmux._META_KEYS`).
REFRESH = 2


@pytest.mark.parametrize("projects, seats", [(2, 2), (6, 6)])
def test_a_refresh_starts_the_same_few_tmux_processes_for_any_number_of_projects_and_seats(
        tmp_path, monkeypatch, projects, seats):
    name = tmux_test_server.claim("board-fleet-test")
    try:
        socket = fleet.start_server(name)
        monkeypatch.setenv("AGENT_SESSION_SOCKET", socket)
        monkeypatch.setattr(tmux_module, "_META_KEYS", frozenset(tmux_module._IDENTITY)
                            | frozenset(tmux_module._RUN_VALUES) | tmux_module._WAITING_KEYS)
        registry = fleet.build_fleet(tmp_path, socket, projects, seats)
        calls = fleet.count_tmux(monkeypatch)
        result = model.liveness(registry)
        assert len(calls) <= REFRESH, calls
        assert sorted(result) == sorted(f"p{n}" for n in range(projects))
        assert all(entry["state"] == "alive" for slots in result.values() for entry in slots.values())
        assert all(len(slots) == seats + 1 for slots in result.values())
        assert all(list(model._releases[project]) == ["TOOL-001"] for project in result)
    finally:
        tmux_test_server.release(name)
