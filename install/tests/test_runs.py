"""Acceptance tests T7, T10 and T19 of install-contract.md section 8.2: the installation next to managed runs.

The runs are real `agent-session` runs of the installed release on a private tmux server; only the provider
CLI is a fake (see harness.Runs).
"""

import json
import re
import subprocess
import sys

import pytest

from harness import LIB, REPO, assert_changes, changes, commit_change, release_name

pytestmark = pytest.mark.skipif(not __import__("shutil").which("tmux"), reason="tmux is unavailable")


def tree(name):
    return LIB + "/releases/" + name


def install(home, source):
    result = home.run("install", source=source)
    assert result.returncode == 0, result.stderr


def uninstall(home, runs, *args):
    return home.run("uninstall", *args, env={"AGENT_SESSION_SOCKET": str(runs.socket)})


def release_in(text):
    found = re.findall(r"/releases/([^/\s'\"]+)/", text)
    assert found, text[:200]
    return set(found)


# ---------------------------------------------------------------- T10: uninstall refuses while a run lives

def test_t10_alive_run_refuses_uninstall_and_changes_nothing(home, source, runs):
    install(home, source)
    runs.start_leader()
    before = home.snapshot()
    result = uninstall(home, runs)
    assert result.returncode == 3 and "runs_alive" in result.stderr
    assert "%s leader (alive)" % runs.PROJECT in result.stderr
    after = home.snapshot()
    assert after == before
    assert home.path(LIB + "/releases").is_dir()
    forced = uninstall(home, runs, "--force")
    assert forced.returncode == 2 and home.snapshot() == before


def test_t10_unknown_run_refuses_uninstall(home, source, runs):
    """The state names a conversation but tmux has no run for it (the server was restarted)."""
    install(home, source)
    runs.start_leader()
    runs.kill_server()
    before = home.snapshot()
    result = uninstall(home, runs)
    assert result.returncode == 3 and "%s leader (unknown)" % runs.PROJECT in result.stderr
    assert home.snapshot() == before


def test_t10_a_stopped_run_with_a_shutdown_record_refuses_and_without_it_passes(home, source, runs):
    install(home, source)
    started = runs.start_leader()
    runs.kill_cli()
    dry = uninstall(home, runs, "--dry-run")
    assert dry.returncode == 0, dry.stderr                     # stopped alone does not refuse
    state = json.loads((runs.base / "agent/state.json").read_text())
    record = {"leader": {"job_id": None, "run_id": started["run_id"], "session_id": state["leader"]["session_id"],
                         "suspended_at": "2026-11-09T00:00:00Z", "forced": False}}
    (runs.base / "agent/suspend.json").write_text(json.dumps(record))
    before = home.snapshot()
    result = uninstall(home, runs)
    assert result.returncode == 3 and "%s leader (suspended)" % runs.PROJECT in result.stderr
    assert home.snapshot() == before


def test_t10_an_unreadable_registry_refuses(home, source):
    install(home, source)
    home.write(".config/project-agent/project.json", b"{not json")
    before = home.snapshot()
    result = home.run("uninstall")
    assert result.returncode == 3 and "registry_unreadable" in result.stderr
    assert home.snapshot() == before


def test_uninstall_goes_through_when_every_run_is_stopped(home, source, runs, name):
    install(home, source)
    runs.start_leader()
    runs.stop_leader()
    result = uninstall(home, runs)
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------- T7: upgrade next to a live run

@pytest.mark.mutates
def test_t7_upgrade_keeps_the_release_of_a_live_run_and_new_runs_use_the_new_one(home, source, runs, monkeypatch):
    install(home, source)
    first = release_name(source)
    started = runs.start_leader()
    launch = runs.base / "agent/runs" / started["run_id"] / "launch.sh"
    old_text = launch.read_text()
    assert release_in(old_text) == {first}
    commit_change(source, "1.1.0")
    second = release_name(source)
    before = home.snapshot()
    result = home.run("upgrade", source=source)
    assert result.returncode == 0, result.stderr
    assert_changes(before, home.snapshot(), created={tree(second)},
                   modified={LIB + "/current", LIB + "/install.json"}, trees=[tree(second)])
    assert launch.read_text() == old_text and home.path(tree(first) + "/tools/agent-session").is_dir()
    # The live run's own command still runs from the old release.
    library = home.path(tree(first) + "/tools/agent-session")
    ran = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
                          "import agent_session.internal", str(library)], capture_output=True, env=home.env)
    assert ran.returncode == 0, ran.stderr
    # The installer knows which release the live run uses (the function that release cleanup will reuse).
    sys.path.insert(0, str(REPO / "install"))
    from project_agent_install import runs as installer_runs
    from project_agent_install.layout import Env
    for variable in ("AGENT_SESSION_CONFIG", "AGENT_SESSION_SOCKET", "AGENT_SESSION_BASE", "TMUX"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("HOME", str(home.home))
    slots = installer_runs.run_slots(Env(), REPO, socket=str(runs.socket))
    assert [(item["project"], item["slot"], item["state"]) for item in slots] == [(runs.PROJECT, "leader", "alive")]
    assert installer_runs.releases_in_use(Env(), slots) == {first: ["%s/leader" % runs.PROJECT]}
    # A run that starts after the upgrade uses the new release.
    runs.stop_leader()
    restarted = runs.start_leader()
    newest = runs.base / "agent/runs" / restarted["run_id"] / "launch.sh"
    assert newest != launch and release_in(newest.read_text()) == {second}
    assert release_in(launch.read_text()) == {first}


# ---------------------------------------------------------------- T19: what the product writes while it runs

def test_t19_the_running_product_writes_only_where_section_5_says(home, source, runs):
    install(home, source)
    before = home.snapshot()
    runs.start_leader()
    created = runs.call("project-item", "new", "cr", "--area", "TEST", "--title", "a change")
    assert created.returncode == 0, created.stderr
    synced = runs.call("project-board", "sync", "--socket", str(runs.socket))
    assert synced.returncode == 0, synced.stderr
    runs.stop_leader()
    created_paths, removed, modified = changes(before, home.snapshot())
    base = "proj/base/"
    # Section 5.2: the registered project's agent/ files (state, locks, runs, controls, items, decide.html).
    # Section 5.1: the project-item lock file under ~/.cache/project-item/locks.
    # Section 5.1: the crontab lock under ~/.cache/agent-session (the crontab itself is outside HOME, section 5.4).
    allowed = (re.compile(r"^%sagent(/|$)" % re.escape(base)),
               re.compile(r"^\.cache(/project-item(/locks(/[0-9a-f]+\.lock)?)?)?$"),
               re.compile(r"^\.cache(/agent-session(/crontab\.lock)?)?$"))
    outside = sorted(path for path in created_paths | removed | modified if not any(rule.match(path) for rule in allowed))
    assert not outside, outside
    assert not removed - {path for path in removed if path.startswith(base + "agent/")}
    assert any(path.startswith(base + "agent/state.json") for path in created_paths)
    assert (runs.base / "agent/cr").is_dir()
    # Section 5.4: the Leader's start put the project's check job in the crontab, in the project's section only.
    crontab = runs.crontab.read_text()
    assert crontab.startswith("# >>> project-agent: pifx >>>\n") and crontab.endswith("# <<< project-agent: pifx <<<\n")
    assert crontab.count("\n") == 4 and " check --project pifx >/dev/null 2>&1" in crontab
    # The installation itself is untouched by running it.
    after = home.snapshot()
    for path, entry in before.items():
        if path.startswith((LIB, ".local/bin", ".claude/", ".codex/", ".tmux.conf", ".bashrc")):
            assert after.get(path) == entry, path
