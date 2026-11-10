"""How many tmux processes a read or a command starts (SESSION-010).

The product asked tmux for the same facts of one server (session list, owner marker, current pointer, window
options, pane facts, server identity) again for every slot and every call, so one Board refresh and one
command grew with the projects, the seats and the lookups. These tests count the `tmux` processes the
product starts, so that cannot happen again. The numbers are fixed, not ratios: a read of the server starts
the same few processes for 2 and for 6 projects and seats, and a command starts the few its own steps need.

Before the fix the same calls started 27 (one project of 2 seats; 63 of 6 seats) and 4496 (Board liveness,
16 projects x 16 seats) tmux processes, and `review` 24, `review --clear` 8, `send` 43, `stop` 69.
"""

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from agent_session_fixture import session_env  # noqa: E402,F401
from agent_session import api, config, internal, providers, tmux as tmux_module  # noqa: E402
from agent_session.errors import SessionError  # noqa: E402
from agent_session.tmux import Tmux  # noqa: E402
from fleet import build_fleet, count_tmux, start_server  # noqa: E402
import tmux_test_server  # noqa: E402

# A read of the server for one project or for all: the server's sessions, windows and panes in one tmux
# process, then the window options of the current runs in one more (the names of the options are learned).
SERVER_READ = 2
# A registration after the interpreter (finding the run, the binding check's look at the slot, the publication):
# 10 tmux processes measured for 2, 6 and 16 seats alike. It is a number of steps, not of seats.
REGISTRATION = 10
# A command starts what its own steps need; `start` waits for the provider to register in a loop, so its
# number follows the wait and is not limited here.
COMMANDS = {"review": 8, "review --clear": 3, "send": 16, "stop": 30}


@pytest.fixture
def fleet_socket(monkeypatch):
    name = tmux_test_server.claim("fleet-test")
    socket = start_server(name)
    monkeypatch.setenv("AGENT_SESSION_SOCKET", socket)
    # The names of the window options that a read asks for are learned and kept for the process: start each
    # test from the names the product itself writes, so the count does not depend on the tests that ran before.
    monkeypatch.setattr(tmux_module, "_META_KEYS", frozenset(tmux_module._IDENTITY) | frozenset(tmux_module._RUN_VALUES)
                        | tmux_module._WAITING_KEYS)
    yield socket
    tmux_test_server.release(name)


@pytest.mark.parametrize("projects, seats", [(2, 2), (6, 6)])
def test_one_server_view_judges_every_project_in_a_constant_number_of_tmux_processes(
        tmp_path, monkeypatch, fleet_socket, projects, seats):
    loaded = config.load_registry(build_fleet(tmp_path, fleet_socket, projects, seats))
    calls = count_tmux(monkeypatch)
    view = api.server_view(loaded)
    verdicts = {project.project_id: api.project_liveness(project, view=view) for project in loaded}
    holds = {project.project_id: api.project_pending_releases(project, view=view) for project in loaded}
    assert len(calls) <= SERVER_READ, calls
    assert all(len(result) == seats + 1 for result in verdicts.values())
    assert all(entry["state"] == "alive" for result in verdicts.values() for entry in result.values())
    assert all(list(hold) == ["TOOL-001"] for hold in holds.values())


@pytest.mark.parametrize("seats", [2, 6])
def test_the_liveness_of_one_project_starts_a_constant_number_of_tmux_processes(
        tmp_path, monkeypatch, fleet_socket, seats):
    project = config.load_registry(build_fleet(tmp_path, fleet_socket, 3, seats))[0]
    calls = count_tmux(monkeypatch)
    assert len(api.project_liveness(project)) == seats + 1
    assert len(calls) <= SERVER_READ, calls
    calls.clear()
    assert list(api.project_pending_releases(project)) == ["TOOL-001"]
    assert len(calls) <= SERVER_READ, calls


def test_commands_start_few_tmux_processes(session_env, monkeypatch):
    env = session_env
    calls = count_tmux(monkeypatch)
    counts = {}

    def counted(label, command):
        calls.clear()
        result = command()
        counts[label] = len(calls)
        return result

    leader = env.manager().start("leader")
    cr = env.cr()
    env.manager().start(cr)
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", leader["session"]["session_id"])
        counted("review", lambda: env.manager().review(job=cr))
        counted("review --clear", lambda: env.manager().review(clear=True))
        counted("send", lambda: env.manager().send(job=cr, message="A note."))
    counted("stop", lambda: env.manager().control("stop", job=cr))
    assert {label: number for label, number in counts.items() if number > COMMANDS[label]} == {}, counts


def _outcome(read):
    """The run a slot read names (`run:<run id>`), None for no run, or the code of the error it gave."""
    try:
        meta = read()
    except SessionError as error:
        return error.code
    return None if meta is None else "run:" + meta["run_id"]


def test_a_server_view_judges_each_slot_as_a_live_read_does(tmp_path, fleet_socket):
    """Every verdict of a view equals what `get_current` (one live read per slot) says, errors included."""
    project = config.load_registry(build_fleet(tmp_path, fleet_socket, 2, 5))[0]
    control = Tmux(socket_path=fleet_socket)
    other = "p1"
    slots = ["leader", *(f"seat-{n}" for n in range(5))]
    # seat-1: its window is gone, the pointer stays; seat-2: the window holds another run than the pointer
    # names; seat-3: the pointer is not JSON; seat-4: it names a window by a text that is no window handle;
    # the other project's session is marked as from another server.
    meta = control.get_current(project.project_id, "seat-1")
    control.command("kill-window", "-t", meta["window_id"])
    meta = control.get_current(project.project_id, "seat-2")
    control.command("set-option", "-w", "-t", meta["window_id"], "@agent_session_run_id", json.dumps("another-run"))
    control.command("set-option", "-t", project.project_id, "@agent_session_current_seat_3", "not json")
    control.command("set-option", "-t", project.project_id, "@agent_session_current_seat_4",
                    json.dumps({"window_id": "@1' ; kill-server ; '"}))
    owner = json.loads(control.command("show-options", "-qv", "-t", other, "@agent_session_owner"))
    owner["server_pid"] += 1
    control.command("set-option", "-t", other, "@agent_session_owner", json.dumps(owner))
    view = control.server_view([project.project_id, other], slots)
    outcomes = {}
    for name in (project.project_id, other, "no-such-project"):
        for slot in slots:
            outcomes[name, slot] = _outcome(lambda: control.get_current(name, slot))
            assert _outcome(lambda: view.current(name, slot)) == outcomes[name, slot], (name, slot)
    assert outcomes[project.project_id, "leader"].startswith("run:")
    assert outcomes[project.project_id, "seat-0"].startswith("run:")
    assert outcomes[project.project_id, "seat-1"] == "execution_evidence_missing"
    assert outcomes[project.project_id, "seat-2"] == "target_changed"
    assert outcomes[project.project_id, "seat-3"] == "tmux_metadata_invalid"
    assert outcomes[project.project_id, "seat-4"] == "execution_evidence_missing"
    assert {outcomes[other, slot] for slot in slots} == {"tmux_owner_mismatch"}
    assert {outcomes["no-such-project", slot] for slot in slots} == {None}


def test_an_option_name_the_read_did_not_expect_costs_one_more_process_once(tmp_path, monkeypatch, fleet_socket):
    project = config.load_registry(build_fleet(tmp_path, fleet_socket, 2, 2))[0]
    control = Tmux(socket_path=fleet_socket)
    window = control.get_current(project.project_id, "seat-0")["window_id"]
    control.command("set-option", "-w", "-t", window, "@agent_session_a_new_option", json.dumps({"x": 1}))
    calls = count_tmux(monkeypatch)
    assert {slot: entry["state"] for slot, entry in api.project_liveness(project).items()} == {
        "leader": "alive", "0": "alive", "1": "alive"}
    assert len(calls) == SERVER_READ + 1                       # the listing named an option the request lacked
    assert control.read_meta(window)["a_new_option"] == {"x": 1}
    calls.clear()
    api.project_liveness(project)
    assert len(calls) == SERVER_READ                            # and it is asked for from then on


def test_a_window_that_vanishes_during_a_batch_read_is_reported_alone(tmp_path, fleet_socket):
    config.load_registry(build_fleet(tmp_path, fleet_socket, 3, 6))
    control = Tmux(socket_path=fleet_socket)
    few = [control.get_current("p0", slot)["window_id"] for slot in ("leader", "seat-0", "seat-1")]
    many = [control.get_current(name, slot)["window_id"] for name in ("p0", "p1", "p2")
            for slot in ("leader", *(f"seat-{n}" for n in range(6)))]
    # A few windows go in one command line, many go in through `source-file` (a failing line does not stop the rest).
    for windows in (few, many):
        ids = [windows[0], "@9999", *windows[1:]]
        found = control._read_metas(ids)
        assert set(found) == set(ids)
        assert isinstance(found["@9999"], SessionError) and found["@9999"].details["reason"] == "no such window: @9999"
        assert all(found[window]["window_id"] == window for window in windows)


def _registration(tmp_path, fleet_socket, seats):
    """(registry, project, the run of the project's last seat) of a fleet of 3 projects."""
    registry = build_fleet(tmp_path, fleet_socket, 3, seats)
    project = config.load_registry(registry)[1]
    return registry, project, Tmux(socket_path=fleet_socket).get_current(project.project_id, f"seat-{seats - 1}")


@pytest.mark.parametrize("seats", [2, 6, 16])
def test_finding_the_run_of_a_hook_starts_two_tmux_processes_whatever_the_seats(
        tmp_path, monkeypatch, fleet_socket, seats):
    """SESSION-011. The hook and `mark_process` found their run by reading every slot of the project: two tmux
    processes per slot (4 for 2 seats, 34 for 16), and the hook did it twice."""
    registry, project, run = _registration(tmp_path, fleet_socket, seats)
    calls = count_tmux(monkeypatch)
    found, control, context = internal._run(run["run_id"], str(registry), fleet_socket, cwd=project.base)
    assert found.project_id == project.project_id and context["target"] == f"seat-{seats - 1}"
    assert context["run_id"] == run["run_id"] and context["seat"] == seats - 1
    assert len(calls) <= SERVER_READ, calls


@pytest.mark.parametrize("seats", [2, 6, 16])
def test_a_registration_starts_the_same_tmux_processes_whatever_the_seats(
        tmp_path, monkeypatch, fleet_socket, seats):
    """The whole of a hook's registration after the interpreter: finding the run, the binding check, the publication."""
    registry, project, run = _registration(tmp_path, fleet_socket, seats)
    session_id = "11111111-2222-3333-4444-555555555555"

    class Provider:
        def verify_binding(self, session, context, meta, timeout=30):
            return session
    monkeypatch.setattr(providers, "get_provider", lambda name: Provider())
    endpoint = "unix:///tmp/fleet.sock"             # the fleet is a Codex fleet: a conversation has an endpoint
    Tmux(socket_path=fleet_socket).write_meta(run["window_id"], {"run_id": run["run_id"], "endpoint": endpoint})
    calls = count_tmux(monkeypatch)
    resolved = internal._run(run["run_id"], str(registry), fleet_socket, cwd=project.base)
    internal._register(run["run_id"], str(registry), fleet_socket, session_id, endpoint, cwd=run["cwd"],
                       resolved=resolved)
    assert len(calls) <= REGISTRATION, calls
    assert Tmux(socket_path=fleet_socket).get_current(project.project_id, f"seat-{seats - 1}")["session_id"] == session_id


def test_the_run_of_a_hook_is_found_among_the_slots_that_name_it(tmp_path, fleet_socket):
    """`current_with_run` names the slot whose pointer holds the run; another run, an unreadable pointer, a gone
    window and a project without a session are no match, and a pointer of another slot is never an error."""
    registry, project, _ = _registration(tmp_path, fleet_socket, 4)
    control = Tmux(socket_path=fleet_socket)
    slots = ["leader", *(f"seat-{n}" for n in range(4))]
    runs = {slot: control.get_current(project.project_id, slot)["run_id"] for slot in slots}
    meta = control.get_current(project.project_id, "seat-1")
    control.command("kill-window", "-t", meta["window_id"])                       # seat-1: the window is gone
    control.command("set-option", "-t", project.project_id, "@agent_session_current_seat_2", "not json")
    def found(run_id, name=project.project_id):
        return [meta["target"] for meta in control.current_with_run(name, run_id, slots)]
    assert found(runs["seat-3"]) == ["seat-3"]
    assert found(runs["leader"]) == ["leader"]
    assert found(runs["seat-1"]) == [] and found(runs["seat-2"]) == []
    assert found("no-such-run") == [] and found(runs["seat-3"], "no-such-project") == []
    assert found(runs["seat-3"], "p0") == []                                      # another project's slots hold other runs
