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
from agent_session.util import write_json
from agent_session_fake_provider import FakeProvider


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
        (self.seed / ".gitignore").write_text("/agent/\n/jobs/\n/handoff/\n/.fixture-domain.json\n/.fixture-controls.json\n")
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
                                                          "seats": [str(path) for path in self.seats]}}))
        (self.base / "agent").mkdir()
        (self.base / "agent/adapter.py").write_text((Path(__file__).parent / "project_adapter.py").read_text())
        (self.base / "jobs").mkdir()
        subprocess.run(["tmux", "-L", self.socket_name, "-f", os.devnull,
                        "new-session", "-d", "-s", "harness", "sleep", "86400"], check=True, capture_output=True)
        self.project = resolve_project(self.base, self.config)
        self.store = StateStore(self.project)
        self.tmux = Tmux(socket_name=self.socket_name)
        return self

    def manager(self, timeout=15):
        return Manager(self.base, self.config, socket_name=self.socket_name, timeout=timeout)

    def job(self, number=1, mode="write"):
        job_id = f"J-20261103-{number:02}"
        metadata = {"job_id": job_id, "created_at": "2026-11-03T10:00:00+09:00", "role": "server",
                    "mode": mode, "cwd": ".", "task": "Refactor the temporary server fixture.",
                    "scope": ["server.py"], "checks": ["python -m py_compile server.py"],
                    "branch": f"job/{job_id}" if mode == "write" else None,
                    "approved": True, "baseline": None, "submission": None, "review": None,
                    "integration": None, "submodules": []}
        path = self.base / "jobs" / (job_id + ".md")
        path.write_text("# Fixture JOB\n\n```json\n" + json.dumps(metadata, indent=2)
                        + "\n```\n\n## 사용자 승인 근거\n\nThe test operator approved this temporary fixture task.\n")
        return path

    def read_job(self, path):
        import re
        return json.loads(re.search(r"```json\n(.*?)\n```", path.read_text(), re.S).group(1))

    def domain(self):
        path = self.base / ".fixture-domain.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def fail_once(self, name):
        write_json(self.base / ".fixture-controls.json", {name: True})

    def accept(self, job_id, head):
        domain = self.domain()
        domain["accepted"][job_id] = head
        write_json(self.base / ".fixture-domain.json", domain)

    def advance_remote(self):
        (self.seed / "upstream.txt").write_text("another owner changed main\n")
        git(self.seed, "add", "upstream.txt")
        git(self.seed, "commit", "-m", "Advance fixture main")
        git(self.seed, "push", "origin", "main")
        return git(self.seed, "rev-parse", "HEAD")

    def publish_and_integrate(self, seat, job_id):
        branch = git(seat, "branch", "--show-current")
        git(seat, "push", "-u", "origin", branch)
        submitted = git(seat, "rev-parse", "HEAD")
        git(self.base, "fetch", "origin", branch)
        git(self.base, "merge", "--ff-only", "origin/" + branch)
        git(self.base, "push", "origin", "main")
        assert git(self.remote, "rev-parse", "refs/heads/main") == submitted
        self.accept(job_id, submitted)
        return submitted


@pytest.fixture
def session_env(tmp_path, monkeypatch):
    if not shutil.which("tmux") or not shutil.which("git"):
        pytest.skip("tmux and Git are required")
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
