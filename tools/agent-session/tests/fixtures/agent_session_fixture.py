"""Create temporary Git clones and a provider stub for lifecycle tests."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

TOOL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TOOL))
from agent_session.config import resolve_project
from agent_session.lifecycle import Manager
from agent_session.state import StateStore
from agent_session.tmux import Tmux
from agent_session_fake_provider import FakeProvider

PROJECT_ITEM = TOOL.parent / "project-item"
sys.path.insert(0, str(PROJECT_ITEM))
import tmux_test_server  # noqa: E402
from project_item import store as item_store  # noqa: E402
from project_item.kinds import CR  # noqa: E402


# The wait limit is a ceiling for a command that never finishes, so a hung test fails instead of
# stalling the run; it asserts no speed. A fixture `start` runs a real tmux pane and a Python child that
# imports agent_session, so its time follows the host's load. Measured on this workstation:
# - TEST-003: with three `-n 8` suites at once on a host at load 75-100 on 64 cores, one command took
#   p50 9.8 s, p99 29.8 s and at most 38.0 s over 1350 commands, so 15 s failed about 95 of 704 tests.
# - TEST-013: with `-n 8` agent-session and `-n 8` install tests at once at load 50-100, a `start` took
#   p50 24.6 s, p99 61.0 s and at most 80.3 s over 386 starts, and a two-slot `resume` 43 s, which shares
#   one limit across its slots. 120 s left 1.5 times the maximum, and the 0.9.0 gate (load 92-143) passed it.
# 240 s is three times the TEST-013 maximum.
DEFAULT_TIMEOUT = 240


def command_timeout():
    """The wait limit for one fixture Manager command; AGENT_SESSION_TEST_TIMEOUT overrides it."""
    return float(os.environ.get("AGENT_SESSION_TEST_TIMEOUT", DEFAULT_TIMEOUT))


def git(root, *args):
    result = subprocess.run(["git", "-c", "submodule.recurse=false", "-C", str(root), *args],
                            capture_output=True, text=True, timeout=command_timeout())
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def build_repositories(layout):
    """Create the bare remote, the seed clone, the base and the seat clones under ``layout.root``.

    Return the hash of the seed commit, the main every clone starts at. ``--template=`` leaves out
    Git's sample hooks, which no test uses, so the template has a third of the files to copy.
    """
    layout.remote.mkdir()
    git(layout.remote, "init", "--bare", "--template=", "--initial-branch=main")
    layout.seed.mkdir()
    git(layout.seed, "init", "--template=", "--initial-branch=main")
    git(layout.seed, "config", "user.name", "Fixture")
    git(layout.seed, "config", "user.email", "fixture@example.invalid")
    (layout.seed / "server.py").write_text("VALUE = 1\n")
    (layout.seed / ".gitignore").write_text("/agent/\n")
    git(layout.seed, "add", ".")
    git(layout.seed, "commit", "-m", "Seed fixture main")
    git(layout.seed, "remote", "add", "origin", str(layout.remote))
    git(layout.seed, "push", "-u", "origin", "main")
    for target in [layout.base, *layout.seats]:
        git(layout.root, "clone", "--template=", str(layout.remote), str(target))
        git(target, "config", "user.name", "Fixture")
        git(target, "config", "user.email", "fixture@example.invalid")
    return git(layout.seed, "rev-parse", "HEAD")


class GitTemplate:
    """The fixture's Git repositories, built once and copied for each test.

    The copy keeps every test's remote, seed, base and seats private; the template itself is never
    handed to a test. Only the remote URL of the seed and the clones names a path, so the copy
    rewrites it to its own ``origin.git``.
    """

    def __init__(self, directory):
        self.layout = Environment(directory)
        self.initial_hash = build_repositories(self.layout)

    def copy_to(self, env):
        for name in ("remote", "seed", "base"):
            shutil.copytree(getattr(self.layout, name), getattr(env, name), symlinks=True)
        for source, target in zip(self.layout.seats, env.seats):
            shutil.copytree(source, target, symlinks=True)
        for source, target in zip([self.layout.seed, self.layout.base, *self.layout.seats],
                                  [env.seed, env.base, *env.seats]):
            git(target, "remote", "set-url", "origin", str(env.remote))
        return self.initial_hash


class Environment:
    def __init__(self, directory):
        self.root = directory
        self.remote = directory / "origin.git"
        self.seed = directory / "seed"
        self.base = directory / "project.main"
        self.seats = [directory / f"project.seat{n}" for n in range(2)]
        self.config = directory / "project.json"
        self.socket_name = tmux_test_server.new_name("agent-lifecycle-test")

    def setup(self, template=None):
        """Lay out the Git repositories and the tmux harness.

        With a ``GitTemplate`` the repositories are copied from it instead of being built again.
        """
        if template is None:
            self.initial_hash = build_repositories(self)
        else:
            self.initial_hash = template.copy_to(self)
        self.config.write_text(json.dumps({str(self.base): {"project": "fixture", "provider": "codex",
                                                          "seats": [str(path) for path in self.seats],
                                                          "path_cr": "agent/cr", "path_decide": "agent/decide"}}))
        (self.base / "agent").mkdir()
        self.cr_root = self.base / "agent" / "cr"
        tmux_test_server.watch(self.socket_name)
        subprocess.run(["tmux", "-L", self.socket_name, "-f", os.devnull,
                        "new-session", "-d", "-s", "harness", "sleep", "86400"], check=True, capture_output=True)
        self.project = resolve_project(self.base, self.config)
        self.store = StateStore(self.project)
        self.tmux = Tmux(socket_name=self.socket_name)
        return self

    def manager(self, timeout=None):
        return Manager(self.base, self.config, socket_name=self.socket_name, timeout=timeout or command_timeout())

    def add_project(self, name="other"):
        """Register a second project (own clone and state, no seats) and return its base."""
        base = self.root / f"{name}.main"
        git(self.root, "clone", str(self.remote), str(base))
        git(base, "config", "user.name", "Fixture")
        git(base, "config", "user.email", "fixture@example.invalid")
        (base / "agent").mkdir()
        registry = json.loads(self.config.read_text())
        registry[str(base)] = {"project": name, "provider": "codex", "seats": []}
        self.config.write_text(json.dumps(registry))
        return base

    def manager_at(self, base, timeout=None):
        return Manager(base, self.config, socket_name=self.socket_name, timeout=timeout or command_timeout())

    def cr(self, number=1, mode="write", cwd=None):
        """Write an approved CR in todo/ and return its ID."""
        cr_id = f"TOOL-{number:03}"
        extra = f"- Mode: {mode}\n" + (f"- Cwd: {cwd}\n" if cwd else "")
        path = self.cr_root / "todo" / f"{cr_id}-fixture.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {cr_id}: Refactor the temporary server fixture\n\n- Opened: 2026-11-04\n"
                        f"- Scope: fixture\n- Severity: S3\n{extra}\n## Symptom\nThe fixture needs a change.\n\n"
                        "## Evidence\n`server.py:1`\n\n## Contract\nThe fixture contract.\n\n"
                        "## Disposition\n- 2026-11-04 user: approved the temporary fixture task.\n\n"
                        "## Implementation\nChange server.py.\n\n## Verification\npython -m py_compile server.py\n",
                        encoding="utf-8")
        return cr_id

    def cr_state(self, cr_id):
        return item_store.find(CR, self.cr_root, cr_id)

    def cr_header(self, cr_id, key):
        state, path = self.cr_state(cr_id)
        return CR.fmt.parse(path, state).headers.get(key)

    def finish(self, cr_id, state="done", outcome="fixed", note="fixture review"):
        """The Leader's move out of in-progress (with a Result for fixed)."""
        current, path = self.cr_state(cr_id)
        if outcome == "fixed":
            path.write_text(path.read_text() + "\n## Result\nfixture commit and checks\n")
        item_store.move(CR, self.cr_root, cr_id, state, outcome=outcome if state in ("done", "deferred") else None,
                        by="leader", note=note)

    def handoff(self, slot, text="fixture handoff"):
        path = self.base / "agent" / "handoff" / f"{slot}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        return path

    def advance_remote(self):
        (self.seed / "upstream.txt").write_text("another owner changed main\n")
        git(self.seed, "add", "upstream.txt")
        git(self.seed, "commit", "-m", "Advance fixture main")
        git(self.seed, "push", "origin", "main")
        return git(self.seed, "rev-parse", "HEAD")

    def publish(self, seat):
        branch = git(seat, "branch", "--show-current")
        git(seat, "push", "-u", "origin", branch)
        return git(seat, "rev-parse", "HEAD")

    def publish_and_integrate(self, seat):
        branch = git(seat, "branch", "--show-current")
        submitted = self.publish(seat)
        git(self.base, "fetch", "origin", branch)
        git(self.base, "merge", "--ff-only", "origin/" + branch)
        git(self.base, "push", "origin", "main")
        assert git(self.remote, "rev-parse", "refs/heads/main") == submitted
        return submitted


_template = None


def shared_template(tmp_path_factory):
    """The Git template of this pytest process, built on first use (once per xdist worker)."""
    global _template
    if _template is None:
        _template = GitTemplate(tmp_path_factory.mktemp("git-template"))
    return _template


@pytest.fixture
def session_env(tmp_path, tmp_path_factory, monkeypatch):
    if not shutil.which("tmux") or not shutil.which("git"):
        pytest.skip("tmux and Git are required")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "AGENT_SESSION_CONFIG", "AGENT_SESSION_SOCKET", "AGENT_SESSION_BASE", "TMUX", "TMUX_PANE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    import agent_session.lifecycle as lifecycle
    import agent_session.providers as providers
    monkeypatch.setattr(lifecycle, "get_provider", lambda name: FakeProvider())
    monkeypatch.setattr(providers, "get_provider", lambda name: FakeProvider())
    fixture = Environment(tmp_path).setup(shared_template(tmp_path_factory))
    yield fixture
    tmux_test_server.release(fixture.socket_name)
