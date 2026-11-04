"""Create temporary Git clones and a provider stub for lifecycle tests."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

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
from project_item import store as item_store  # noqa: E402
from project_item.kinds import CR  # noqa: E402


def git(root, *args):
    result = subprocess.run(["git", "-c", "submodule.recurse=false", "-C", str(root), *args],
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


class Environment:
    def __init__(self, directory):
        self.root = directory
        self.remote = directory / "origin.git"
        self.seed = directory / "seed"
        self.base = directory / "project.main"
        self.seats = [directory / f"project.seat{n}" for n in range(2)]
        self.config = directory / "project.json"
        self.socket_name = "agent-lifecycle-test-" + uuid.uuid4().hex[:10]

    def setup(self):
        self.remote.mkdir()
        git(self.remote, "init", "--bare", "--initial-branch=main")
        self.seed.mkdir()
        git(self.seed, "init", "--initial-branch=main")
        git(self.seed, "config", "user.name", "Fixture")
        git(self.seed, "config", "user.email", "fixture@example.invalid")
        (self.seed / "server.py").write_text("VALUE = 1\n")
        (self.seed / ".gitignore").write_text("/agent/\n")
        git(self.seed, "add", ".")
        git(self.seed, "commit", "-m", "Seed fixture main")
        git(self.seed, "remote", "add", "origin", str(self.remote))
        git(self.seed, "push", "-u", "origin", "main")
        for target in [self.base, *self.seats]:
            git(self.root, "clone", str(self.remote), str(target))
            git(target, "config", "user.name", "Fixture")
            git(target, "config", "user.email", "fixture@example.invalid")
        self.initial_hash = git(self.seed, "rev-parse", "HEAD")
        self.config.write_text(json.dumps({str(self.base): {"project": "fixture", "provider": "codex",
                                                          "seats": [str(path) for path in self.seats],
                                                          "path_cr": "agent/cr", "path_decide": "agent/decide"}}))
        (self.base / "agent").mkdir()
        self.cr_root = self.base / "agent" / "cr"
        subprocess.run(["tmux", "-L", self.socket_name, "-f", os.devnull,
                        "new-session", "-d", "-s", "harness", "sleep", "86400"], check=True, capture_output=True)
        self.project = resolve_project(self.base, self.config)
        self.store = StateStore(self.project)
        self.tmux = Tmux(socket_name=self.socket_name)
        return self

    def manager(self, timeout=15):
        return Manager(self.base, self.config, socket_name=self.socket_name, timeout=timeout)

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


@pytest.fixture
def session_env(tmp_path, monkeypatch):
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
    fixture = Environment(tmp_path).setup()
    yield fixture
    subprocess.run(["tmux", "-L", fixture.socket_name, "kill-server"], capture_output=True, timeout=10)
