"""Retries keep a live SSH display instead of respawning its owned pane."""

from types import SimpleNamespace

import pytest

from agent_session import process, remote, remote_bridge, remote_lifecycle
from fake_tmux import fake_tmux


def test_prelaunch_retry_reuses_an_already_connected_ssh_display(tmp_path, monkeypatch):
    cr = tmp_path / "cr.md"
    cr.write_text("# TOOL-001: Example\n\n## Result\n")
    context = {"run_id": "a" * 32, "window_id": "@1", "pane_id": "%1", "target": "seat-0",
               "cli_pid": 123, "cli_birth": "ssh-birth", "remote_native": {"run_id": "a" * 32},
               "job": {"job_id": "TOOL-001", "path": str(cr)}, "job_id": "TOOL-001"}
    manager = SimpleNamespace(project=SimpleNamespace(base=tmp_path, args_for=lambda role: ()),
                              tmux=fake_tmux(write_meta=lambda *args: None,
                                                   pane_info=lambda pane_id: {"pane_dead": False, "pane_pid": 123}),
                              remaining=lambda: 30, _wait_ready=lambda meta: {"ready": True, "run_id": meta["run_id"]},
                              _sweep=lambda target: {})
    operations = []

    def request(meta, operation, payload=None, timeout=30):
        operations.append(operation)
        return 1 if operation == "display_clients" else {}

    monkeypatch.setattr(remote, "run_call", request)
    monkeypatch.setattr(process, "alive", lambda pid, birth: pid == 123 and birth == "ssh-birth")
    monkeypatch.setattr(remote_bridge, "prepare", lambda *args: {"remote_listen": "/tmp/uplink", "token": "token"})
    monkeypatch.setattr(remote_lifecycle, "attach", lambda *args: pytest.fail("The still-connected display must not respawn"))
    result = remote_lifecycle.launch(manager, context)
    assert result["ready"] is True and result["run_id"] == context["run_id"]
    assert operations == ["launch", "display_clients"]
