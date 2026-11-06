"""Check the decision status with a temporary registry, temporary decision directories and a fake tmux."""

import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import time

import pytest


SCRIPT = Path(__file__).with_name("tmux_decide_status.py")


class FakeTmux:
    """Records the tmux commands; answers list-clients and list-panes from the fixture."""

    def __init__(self):
        self.calls = []
        self.clients = ["client-1", "client-2"]
        self.panes = []             # (window_name, pane_active, tty)

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == "list-clients":
            return "".join(name + "\n" for name in self.clients)
        if args[0] == "list-panes":
            return "".join("%s\t%s\t%s\n" % pane for pane in self.panes)
        return ""

    def messages(self):
        return [call for call in self.calls if call[0] == "display-message"]


@pytest.fixture
def status(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("tmux_decide_status_test_target", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home" / ".claude").mkdir(parents=True)
    module.tmux = FakeTmux()
    module.projects = {}
    return module


def register(status, tmp_path, name, *ids):
    """Add a project with a decision directory and the open decisions `ids` to the temporary registry."""
    base = tmp_path / name / "base"
    decide = base / "agent" / "decide"
    (decide / "open").mkdir(parents=True)
    (decide / "done").mkdir(parents=True)
    status.projects[name] = {"base": base, "decide": decide}
    for item_id in ids:
        open_decision(decide, item_id)
    write_registry(status, tmp_path)
    return decide


def write_registry(status, tmp_path):
    registry = {str(item["base"]): {"project": name, "provider": "claude", "seats": [],
                                    "path_decide": str(item["decide"])}
                for name, item in status.projects.items()}
    (tmp_path / "home" / ".claude" / "project.json").write_text(json.dumps(registry), encoding="utf-8")


def open_decision(decide, item_id, title="질문"):
    (decide / "open" / (item_id + ".md")).write_text(
        "# %s: %s\n\n- Opened: 2026-11-06 10:00\n- Urgency: normal\n" % (item_id, title),
        encoding="utf-8")


def close_decision(decide, item_id):
    (decide / "open" / (item_id + ".md")).rename(decide / "done" / (item_id + ".md"))


def expire(status):
    """Make the cache older than CACHE_TTL."""
    path = status.cache_path()
    old = time.time() - status.CACHE_TTL * 2
    os.utime(path, (old, old))


def display(status, capsys):
    assert status.main() == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    return re.sub(r"#\[[^]]*\]", "", captured.out)


def test_counts_the_open_decisions_of_every_project(status, tmp_path, capsys):
    register(status, tmp_path, "alpha", "D-20261106-01")
    register(status, tmp_path, "beta", "D-20261106-02", "D-20261106-03")
    register(status, tmp_path, "gamma")
    assert display(status, capsys).strip() == "결정 3"


def test_the_count_is_white_on_red(status, tmp_path, capsys):
    register(status, tmp_path, "alpha", "D-20261106-01")
    status.main()
    assert capsys.readouterr().out.startswith("#[fg=white,bg=red")


def test_no_open_decision_prints_nothing(status, tmp_path, capsys):
    decide = register(status, tmp_path, "alpha", "D-20261106-01")
    close_decision(decide, "D-20261106-01")
    assert display(status, capsys) == ""


def test_an_unusable_registry_prints_nothing(status, capsys):
    (Path(os.environ["HOME"]) / ".claude" / "project.json").write_text("{", encoding="utf-8")
    assert display(status, capsys) == ""


def test_a_fresh_cache_does_not_read_the_directories_again(status, tmp_path, capsys):
    decide = register(status, tmp_path, "alpha", "D-20261106-01")
    assert display(status, capsys).strip() == "결정 1"
    open_decision(decide, "D-20261106-02")
    assert display(status, capsys).strip() == "결정 1"
    expire(status)
    assert display(status, capsys).strip() == "결정 2"


def test_a_run_that_finds_the_lock_taken_prints_the_last_value(status, tmp_path, capsys):
    decide = register(status, tmp_path, "alpha", "D-20261106-01")
    assert display(status, capsys).strip() == "결정 1"
    open_decision(decide, "D-20261106-02")
    expire(status)
    holder = os.open(status.cache_path() + ".lock", os.O_WRONLY)
    fcntl.flock(holder, fcntl.LOCK_EX)
    try:
        assert display(status, capsys).strip() == "결정 1"
    finally:
        os.close(holder)
    assert status.tmux.calls == []
    assert display(status, capsys).strip() == "결정 2"


def test_a_failed_read_prints_the_last_value_and_waits_for_the_next_interval(
        status, tmp_path, capsys, monkeypatch):
    register(status, tmp_path, "alpha", "D-20261106-01")
    assert display(status, capsys).strip() == "결정 1"
    expire(status)
    reads = []

    def failing(previous):
        reads.append(previous)

    monkeypatch.setattr(status, "read_open_decisions", failing)
    assert display(status, capsys).strip() == "결정 1"
    assert display(status, capsys).strip() == "결정 1"
    assert len(reads) == 1          # the failed read renewed the cache age


def test_an_unreadable_project_keeps_its_last_decisions(status, tmp_path, capsys, monkeypatch):
    alpha = register(status, tmp_path, "alpha", "D-20261106-01")
    register(status, tmp_path, "beta", "D-20261106-02")
    assert display(status, capsys).strip() == "결정 2"
    _, _, store, _ = status.load_project_item()
    item_files = store.item_files

    def unreadable_alpha(kind, root, state):
        if root == alpha.resolve():
            raise OSError("stale file handle")
        return item_files(kind, root, state)

    monkeypatch.setattr(store, "item_files", unreadable_alpha)
    close_decision(alpha, "D-20261106-01")
    expire(status)
    assert display(status, capsys).strip() == "결정 2"
    assert status.read_cache(status.cache_path())[0]["alpha"] == {"D-20261106-01": "질문"}
    assert status.tmux.calls == []


def test_the_first_run_stores_the_baseline_without_an_alarm(status, tmp_path, capsys):
    register(status, tmp_path, "alpha", "D-20261106-01")
    assert display(status, capsys).strip() == "결정 1"
    assert status.tmux.calls == []
    known, _ = status.read_cache(status.cache_path())
    assert known == {"alpha": {"D-20261106-01": "질문"}}


def test_a_new_decision_is_announced_once_to_every_client(status, tmp_path, capsys):
    decide = register(status, tmp_path, "alpha", "D-20261106-01")
    display(status, capsys)
    open_decision(decide, "D-20261106-02", "무엇을 할까요?")
    expire(status)
    assert display(status, capsys).strip() == "결정 2"
    text = "새 결정: alpha D-20261106-02 무엇을 할까요?"
    assert status.tmux.messages() == [
        ("display-message", "-c", "client-1", "-d", "10000", text),
        ("display-message", "-c", "client-2", "-d", "10000", text)]
    status.tmux.calls.clear()
    expire(status)
    assert display(status, capsys).strip() == "결정 2"
    assert status.tmux.calls == []


def test_a_title_with_a_hash_is_not_expanded_by_tmux(status, tmp_path, capsys):
    decide = register(status, tmp_path, "alpha", "D-20261106-01")
    display(status, capsys)
    open_decision(decide, "D-20261106-02", "#{pane_id} 왜?")
    expire(status)
    display(status, capsys)
    assert status.tmux.messages()[0][-1] == "새 결정: alpha D-20261106-02 ##{pane_id} 왜?"


def test_a_reopened_decision_is_announced_again(status, tmp_path, capsys):
    decide = register(status, tmp_path, "alpha", "D-20261106-01", "D-20261106-02")
    display(status, capsys)
    close_decision(decide, "D-20261106-02")
    expire(status)
    assert display(status, capsys).strip() == "결정 1"
    assert status.tmux.messages() == []
    (decide / "done" / "D-20261106-02.md").rename(decide / "open" / "D-20261106-02.md")
    expire(status)
    assert display(status, capsys).strip() == "결정 2"
    assert len(status.tmux.messages()) == 2
    assert "alpha D-20261106-02" in status.tmux.messages()[0][-1]


def test_the_leader_window_gets_a_bell_on_its_active_pane(status, tmp_path, capsys):
    decide = register(status, tmp_path, "alpha", "D-20261106-01")
    register(status, tmp_path, "beta")
    display(status, capsys)
    ttys = {name: tmp_path / ("tty-" + name) for name in ("leader-active", "leader-idle", "beta", "other")}
    for tty in ttys.values():
        tty.write_text("", encoding="utf-8")
    status.tmux.panes = [
        ("alpha-leader", "1", str(ttys["leader-active"])),
        ("alpha-leader", "0", str(ttys["leader-idle"])),
        ("beta-leader", "1", str(ttys["beta"])),
        ("alpha-seat-1", "1", str(ttys["other"]))]
    open_decision(decide, "D-20261106-02")
    expire(status)
    display(status, capsys)
    assert ttys["leader-active"].read_bytes() == b"\a"
    assert [ttys[name].read_bytes() for name in ("leader-idle", "beta", "other")] == [b"", b"", b""]


def test_without_a_leader_window_only_the_message_is_sent(status, tmp_path, capsys):
    decide = register(status, tmp_path, "alpha", "D-20261106-01")
    display(status, capsys)
    status.tmux.panes = [("alpha-seat-1", "1", str(tmp_path / "seat-tty"))]
    open_decision(decide, "D-20261106-02")
    expire(status)
    display(status, capsys)
    assert len(status.tmux.messages()) == 2
    assert not (tmp_path / "seat-tty").exists()


def test_a_project_seen_for_the_first_time_is_a_baseline(status, tmp_path, capsys):
    decide = register(status, tmp_path, "alpha", "D-20261106-01")
    display(status, capsys)
    register(status, tmp_path, "beta", "D-20261106-05")
    expire(status)
    assert display(status, capsys).strip() == "결정 2"
    assert status.tmux.calls == []
    open_decision(decide, "D-20261106-02")
    open_decision(status.projects["beta"]["decide"], "D-20261106-06")
    expire(status)
    display(status, capsys)
    assert status.tmux.messages()[0][-1] == (
        "새 결정: alpha D-20261106-02 질문 / beta D-20261106-06 질문")
