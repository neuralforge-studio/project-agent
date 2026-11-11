"""Watch wakes an instance whose conversation record is older than the threshold, once per stall, and tells the Leader.

The judgement reads the newest record of the provider's conversation file; the Worker tests set that time through
`FakeProvider.last_record`, and the file reading is tested on real JSON-lines files shaped like Claude's transcript."""

import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from agent_session_fixture import command_timeout, session_env  # noqa: F401,E402
from agent_session import cli, process
from agent_session.errors import SessionError
from agent_session.lifecycle import Manager
from agent_session.providers.claude import ClaudeProvider
from agent_session.providers.codex import CodexProvider
from agent_session.providers.common import last_record_time
from agent_session.watch import Watch

THRESHOLD = 1800
SLOT = "seat-0"


def iso(seconds):
    return dt.datetime.fromtimestamp(seconds, dt.timezone.utc).isoformat()


def stamp(seconds):
    """A transcript's timestamp text: UTC with a trailing Z and milliseconds."""
    return dt.datetime.fromtimestamp(seconds, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def record(kind, seconds=None, **fields):
    value = {"type": kind, **fields}
    if seconds is not None:
        value["timestamp"] = stamp(seconds)
    return json.dumps(value, ensure_ascii=False)


# The judgement's reading of a conversation file (spec 7, watch)

def test_last_record_time_is_the_newest_complete_record_with_a_time(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join([record("user", 1000), record("assistant", 2000),
                               record("session-owner"), record("atis-latch")]) + "\n")   # bookkeeping lines carry no time
    assert last_record_time(path) == pytest.approx(2000, abs=0.001)


def test_a_last_line_that_is_still_being_written_is_skipped(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(record("user", 1000) + "\n" + record("assistant", 2000) + "\n" + record("assistant", 3000)[:40])
    assert last_record_time(path) == pytest.approx(2000, abs=0.001)


def test_a_file_without_a_record_with_a_time_has_none(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(record("mode") + "\n" + "not json\n")
    assert last_record_time(path) is None
    path.write_text("")
    assert last_record_time(path) is None


def test_only_the_tail_of_a_long_file_is_read_and_a_cut_first_line_is_ignored(tmp_path):
    path = tmp_path / "t.jsonl"
    old = record("user", 1000, text="x" * 50)
    path.write_text("\n".join([old] * 100 + [record("assistant", 5000), record("assistant", 6000)]) + "\n")
    assert last_record_time(path, tail=200) == pytest.approx(6000, abs=0.001)
    assert last_record_time(path, tail=80) == pytest.approx(6000, abs=0.001)   # cuts into the line before the last
    path.write_text(record("user", 1000, text="y" * 500) + "\n")
    assert last_record_time(path, tail=100) is None                            # one cut line is not a record


def transcripts(tmp_path, monkeypatch, lines=None):
    root = tmp_path / "claude" / "projects" / "-some-project"
    root.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    if lines is not None:
        (root / "s1.jsonl").write_text("\n".join(lines) + "\n")
    return root / "s1.jsonl"


def test_claude_reads_the_last_record_of_its_own_transcript(tmp_path, monkeypatch):
    now = time.time()
    path = transcripts(tmp_path, monkeypatch, lines=[record("user", now - 7200), record("assistant", now - 5400),
                                                     record("last-prompt")])
    old = ClaudeProvider().last_record("s1")                   # an old last record
    assert old["reason"] is None and old["at"] == pytest.approx(now - 5400, abs=0.01)
    path.write_text(record("user", now - 7200) + "\n" + record("assistant", now - 60) + "\n")
    assert ClaudeProvider().last_record("s1")["at"] == pytest.approx(now - 60, abs=0.01)    # a recent record
    path.write_text(record("assistant", now - 90) + "\n" + record("assistant", now)[:30])
    assert ClaudeProvider().last_record("s1")["at"] == pytest.approx(now - 90, abs=0.01)    # the last line is being written


def test_a_missing_or_timeless_transcript_is_no_judgement_with_a_reason(tmp_path, monkeypatch):
    transcripts(tmp_path, monkeypatch, lines=[record("mode")])
    assert ClaudeProvider().last_record("s1") == {"at": None, "reason": "no_record_with_time"}
    assert ClaudeProvider().last_record("other") == {"at": None, "reason": "transcript_not_found"}
    assert ClaudeProvider().last_record(None) == {"at": None, "reason": "transcript_not_found"}


def test_codex_reads_the_last_record_of_its_thread_file(tmp_path, monkeypatch):
    now = time.time()
    day = tmp_path / "codex" / "sessions" / "2026" / "11" / "10"
    day.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    (day / "rollout-2026-11-10T01-02-03-thread-1.jsonl").write_text(
        record("session_meta", now - 7200) + "\n" + record("event_msg", now - 4000) + "\n")
    assert CodexProvider().last_record("thread-1")["at"] == pytest.approx(now - 4000, abs=0.01)
    assert CodexProvider().last_record("thread-2") == {"at": None, "reason": "transcript_not_found"}
    assert CodexProvider().last_record("../x") == {"at": None, "reason": "transcript_not_found"}


# The judgement and what watch does about it

def started(env):
    """Leader and one Worker on a CR in progress."""
    leader = env.manager().start("leader")
    cr = env.cr()
    worker = env.manager().start(cr)
    return leader, cr, worker, time.time()


def messages(env, target=None):
    path = env.base / "agent" / "fixture-messages.jsonl"
    found = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [item for item in found if "[agent-session watch]" in item["text"]
            and (target is None or item["target"] == target)]


def look(env, now, minutes=THRESHOLD // 60, slot=SLOT):
    return env.manager().watch_target(slot, minutes * 60, now=now)


@pytest.fixture
def last(monkeypatch):
    """The newest conversation record of every instance: set `last.at` (epoch seconds) or `last.reason`."""
    from agent_session_fake_provider import FakeProvider

    class Last:
        at = None
        reason = None
    holder = Last()
    monkeypatch.setattr(FakeProvider, "last_record",
                        lambda self, session_id: {"at": holder.at, "reason": holder.reason if holder.at is None else None})
    monkeypatch.setattr(process, "tree", lambda pid: [])
    return holder


def test_a_worker_that_waits_for_the_leader_is_woken_and_told_to_remind_the_leader(session_env, last, monkeypatch):
    env = session_env
    leader, cr, worker, now = started(env)
    with monkeypatch.context() as actor:                  # it reported and the Leader has not answered
        actor.setenv("CODEX_THREAD_ID", worker["session"]["session_id"])
        env.manager().send(job="leader", message="제출합니다.")
    last.at = now
    assert look(env, now + THRESHOLD - 60)["status"] == "active"
    assert messages(env) == []
    first = look(env, now + THRESHOLD)
    assert first["status"] == "resting"
    worker_text, leader_text = messages(env, SLOT), messages(env, "leader")
    assert len(worker_text) == 1 and len(leader_text) == 1
    text = worker_text[0]["text"]
    assert cr in text and "Leader에게 CR ID와 제출 commit을 짧게 다시 알리십시오" in text and "대화 기록 마지막" in text
    assert "자식 process가 없습니다" in text
    assert "seat 0" in leader_text[0]["text"] and "Disposition에 없는 CR" in leader_text[0]["text"]
    # The same stall later: the Worker is not woken again, the Leader is reminded after each threshold.
    again = look(env, now + 2 * THRESHOLD + 60)
    assert again["status"] == "resting" and [item for item in again["actions"] if item["send"] == cr] == []
    assert len(messages(env, SLOT)) == 1 and len(messages(env, "leader")) == 2


def test_a_record_after_the_nudge_is_a_new_state_and_wakes_again_when_it_stalls(session_env, last):
    env = session_env
    _, _, _, now = started(env)
    last.at = now
    assert look(env, now + THRESHOLD)["status"] == "resting"
    last.at = now + THRESHOLD + 30                          # the Worker answered the nudge and rested again
    assert look(env, now + THRESHOLD + 60)["status"] == "active"
    assert look(env, now + 2 * THRESHOLD)["status"] == "active"
    assert look(env, now + 2 * THRESHOLD + 60)["status"] == "resting"
    assert len(messages(env, SLOT)) == 2


def test_a_conversation_that_keeps_appending_records_is_working_and_is_left_alone(session_env, last):
    env = session_env
    _, _, _, now = started(env)
    for step in range(4):
        at = now + step * 20 * 60
        last.at = at - 60                                   # every look finds a record a minute old
        assert look(env, at)["status"] == "active"
    assert messages(env) == []


def test_a_conversation_without_a_readable_record_is_not_a_stall_and_says_why(session_env, last):
    env = session_env
    _, _, _, now = started(env)
    last.reason = "transcript_not_found"
    result = look(env, now + 10 * THRESHOLD)
    assert result["status"] == "skipped" and result["reason"] == "transcript_not_found"
    assert messages(env) == []


def test_a_cr_that_left_in_progress_is_not_watched(session_env, last):
    env = session_env
    _, cr, _, now = started(env)
    env.finish(cr)
    last.at = now - 10 * THRESHOLD
    result = look(env, now)
    assert result["status"] == "skipped" and result["reason"] == "cr_not_in_progress"
    assert messages(env) == []


def test_a_stalled_worker_with_a_background_shell_names_it_in_the_message(session_env, last, monkeypatch):
    from agent_session_fake_provider import FakeProvider
    env = session_env
    _, _, _, now = started(env)
    shell = {"idle": False, "active_turn": True, "runtime_status": "shell",
             "background": [{"id": "bz1", "type": "shell", "command": "until ! pgrep -f x; do sleep 3; done"}]}
    monkeypatch.setattr(FakeProvider, "observe", lambda self, *a, **k: shell)
    last.at = now - THRESHOLD
    assert look(env, now)["status"] == "resting"
    assert "until ! pgrep -f x; do sleep 3; done" in messages(env, SLOT)[0]["text"]


def test_a_child_process_is_named_in_the_message_but_does_not_stop_the_nudge(session_env, last, monkeypatch):
    env = session_env
    _, _, _, now = started(env)
    monkeypatch.setattr(process, "started", lambda pid: 0.0)
    monkeypatch.setattr(process, "tree", lambda pid: [
        {"pid": 4242, "birth": "b4242", "started": 1000.0, "cpu": 90.0, "args": "make -j8 test"}])
    last.at = now - THRESHOLD
    assert look(env, now)["status"] == "resting"           # a quiet conversation is a stall whatever runs
    assert "pid 4242" in messages(env, SLOT)[0]["text"] and "make -j8 test" in messages(env, SLOT)[0]["text"]


def test_a_stalled_leader_with_a_cr_in_progress_is_woken_once_per_stall(session_env, last):
    env = session_env
    _, cr, _, now = started(env)
    leader = lambda at: look(env, at, slot="leader")
    last.at = now
    assert leader(now + THRESHOLD - 60)["status"] == "active"
    assert leader(now + THRESHOLD)["status"] == "resting"
    [sent] = messages(env, "leader")
    assert cr in sent["text"] and "seat 0" in sent["text"] and "review 대기 CR" in sent["text"]
    assert leader(now + 2 * THRESHOLD)["status"] == "resting"
    assert len(messages(env, "leader")) == 1
    last.at = now + 2 * THRESHOLD + 30                      # the Leader worked, then rested again
    assert leader(now + 2 * THRESHOLD + 60)["status"] == "active"
    assert leader(now + 3 * THRESHOLD + 60)["status"] == "resting"
    assert len(messages(env, "leader")) == 2


def test_a_leader_with_no_cr_in_progress_has_nothing_to_have_forgotten(session_env, last):
    env = session_env
    env.manager().start("leader")
    last.at = time.time() - 10 * THRESHOLD
    result = look(env, time.time(), slot="leader")
    assert result["status"] == "skipped" and result["reason"] == "no_cr_in_progress"
    assert messages(env) == []


def spawn(*command):
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_process_tree_reports_command_cpu_and_start_of_the_descendants():
    if not sys.platform.startswith("linux"):
        pytest.skip("needs /proc")
    loop = spawn(sys.executable, "-c", "import time\nwhile True: time.sleep(1)")
    try:
        time.sleep(0.5)
        found = [item for item in process.tree(os.getpid()) if item["pid"] == loop.pid]
        assert len(found) == 1
        item = found[0]
        assert "time.sleep" in item["args"] and item["cpu"] >= 0
        assert abs(item["started"] - time.time()) < 60 and item["birth"] == process.birth(loop.pid)
    finally:
        loop.kill()
        loop.wait()


def run_command(env, *arguments):
    return cli.main(["--config", str(env.config), "--socket-name", env.socket_name, "watch", *arguments])


def test_watch_command_is_the_operators_and_reports_each_target(session_env, last, monkeypatch, capsys):
    env = session_env
    leader, cr, worker, _ = started(env)
    last.at = time.time() - 2 * THRESHOLD
    capsys.readouterr()
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", worker["session"]["session_id"])
        assert run_command(env, "--all") != 0
        assert json.loads(capsys.readouterr().out)["error"]["code"] == "role_denied"
    assert messages(env) == []
    assert run_command(env, "--project", "fixture") == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["threshold_minutes"] == 30
    leader_target, target = data["projects"][0]["targets"]          # the operator judges the Leader too
    assert (leader_target["slot"], leader_target["status"]) == ("leader", "resting")
    assert (target["slot"], target["job_id"], target["status"]) == (SLOT, cr, "resting")
    assert (len(messages(env, SLOT)), len(messages(env, "leader"))) == (1, 2)    # the Worker's stall, and the Leader's own
    # A second run at once sends nothing more.
    assert run_command(env, "--project", "fixture") == 0
    assert (len(messages(env, SLOT)), len(messages(env, "leader"))) == (1, 2)
    assert run_command(env, "--project", "unknown") == 2


def test_a_second_watch_of_the_project_does_not_run_at_once(session_env, monkeypatch):
    from agent_session.state import locked
    env = session_env
    started(env)
    watch = Watch(Manager, config_path=env.config, socket_name=env.socket_name, timeout=command_timeout())
    with locked(env.project.runtime_path / "watch.lock"):
        result = watch.run(project="fixture")
    assert result["projects"][0]["error"]["code"] == "control_busy"
    assert messages(env) == []


def test_a_failed_target_does_not_hide_the_others(session_env, monkeypatch):
    env = session_env
    started(env)
    monkeypatch.setattr(Manager, "watch_target", lambda self, *a, **k: (_ for _ in ()).throw(SessionError("x", "boom")))
    watch = Watch(Manager, config_path=env.config, socket_name=env.socket_name, timeout=command_timeout())
    targets = watch.run(project="fixture")["projects"][0]["targets"]
    assert [item["slot"] for item in targets] == ["leader", SLOT]     # the first error does not stop the second look
    assert all(item["status"] == "error" and item["error"]["code"] == "x" for item in targets)


def test_the_leader_watches_its_own_project_and_gets_the_evidence_instead_of_a_message(session_env, last, monkeypatch, capsys):
    env = session_env
    leader, cr, worker, _ = started(env)
    last.at = time.time() - 2 * THRESHOLD
    capsys.readouterr()
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", leader["session"]["session_id"])
        assert run_command(env, "--project", "fixture") == 0
        [target] = json.loads(capsys.readouterr().out)["data"]["projects"][0]["targets"]    # not the Leader itself
        assert target["slot"] == SLOT and target["status"] == "resting" and cr in target["evidence"] and "자식 process가 없습니다" in target["evidence"]
        # The Worker is woken as in the operator's run; the Leader is not messaged by its own command.
        assert len(messages(env, SLOT)) == 1 and messages(env, "leader") == []
        # The same state again: the Worker is not woken twice and the Leader is still not messaged.
        assert run_command(env, "--project", "fixture") == 0
        assert len(messages(env, SLOT)) == 1 and messages(env, "leader") == []
    # The Leader's own looks leave no notification record (`notified_at`) for the operator's run to skip.
    assert "notified_at" not in (env.tmux.get_current("fixture", SLOT)["watch"].get("resting") or {})


def test_only_this_projects_leader_may_watch_it_and_never_several_projects(session_env, monkeypatch, capsys):
    env = session_env
    leader, _, worker, _ = started(env)
    other = env.add_project()
    other_leader = env.manager_at(other).start("leader")
    capsys.readouterr()

    def refused(identity, *arguments):
        with monkeypatch.context() as actor:
            actor.setenv("CODEX_THREAD_ID", identity)
            assert run_command(env, *arguments) != 0
            return json.loads(capsys.readouterr().out)["error"]["code"]
    assert refused(leader["session"]["session_id"], "--all") == "caller_unbound"       # two projects: not the Leader's
    assert refused(leader["session"]["session_id"], "--project", "other") == "caller_unbound"
    assert refused(other_leader["session"]["session_id"], "--project", "fixture") == "caller_unbound"
    assert refused(worker["session"]["session_id"], "--project", "fixture") == "role_denied"
    assert refused("someone-else", "--project", "fixture") == "caller_unbound"
    assert messages(env) == []
