"""SESSION-015. `agent-session check` judges what the Leader has to do, tells an idle Leader once, and keeps its run.

The Leader's conversation time is set through `FakeProvider.last_record` as in test_watch.py. The findings are
read from real CR and decision files and from the fixture's state and tmux, not from stubs, except where a
test names the stub."""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from agent_session_fixture import command_timeout, session_env  # noqa: F401,E402
from agent_session import cli, cron, jobs, process
from agent_session.lifecycle import Manager

THRESHOLD = 1800
SUBMITTED = "a" * 40


@pytest.fixture
def last(monkeypatch):
    """The newest conversation record of every instance: set `last.at` (epoch seconds)."""
    from agent_session_fake_provider import FakeProvider

    class Last:
        at = None
    holder = Last()
    monkeypatch.setattr(FakeProvider, "last_record",
                        lambda self, session_id: {"at": holder.at, "reason": None if holder.at else "no_record"})
    monkeypatch.setattr(process, "tree", lambda pid: [])
    return holder


def messages(env, target="leader"):
    path = env.base / "agent" / "fixture-messages.jsonl"
    found = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [item for item in found if "[agent-session check]" in item["text"] and item["target"] == target]


def check(env, capsys, *arguments):
    capsys.readouterr()
    code = cli.main(["--config", str(env.config), "--socket-name", env.socket_name, "check", "--project", "fixture",
                     *arguments])
    out = json.loads(capsys.readouterr().out)
    return code, out


def submit(env, cr):
    """The Worker's submission: a last `- 제출 commit:` line in the CR's Result."""
    _, path = env.cr_state(cr)
    path.write_text(path.read_text() + f"\n## Result\n- 제출 commit: {SUBMITTED}\n- 검증: 통과\n")


def cite(env, cr, commit=SUBMITTED[:7]):
    """The Leader's answer: a Disposition line that names the submitted hash."""
    _, path = env.cr_state(cr)
    marker = "approved the temporary fixture task.\n"
    path.write_text(path.read_text().replace(marker, f"{marker}- 2026-11-12 Leader: 제출 {commit}를 검토합니다.\n", 1))


def findings(env):
    manager = env.manager()
    return manager.leader_findings(manager.store.read())


# What the Leader has to do

def test_a_leader_with_nothing_left_to_it_has_no_findings(session_env):
    env = session_env
    env.manager().start("leader")
    assert findings(env) == []


def test_a_submission_the_disposition_does_not_cite_is_a_review_wait_until_it_does(session_env):
    env = session_env
    env.manager().start("leader")
    cr = env.cr()
    env.manager().start(cr)
    assert findings(env) == []                                  # no submission yet
    submit(env, cr)
    [line] = findings(env)
    assert "review 대기 CR" in line and cr in line
    cite(env, cr, "b" * 7)                                      # another hash does not answer this submission
    assert len(findings(env)) == 1
    cite(env, cr)                                               # any Disposition text that names the hash does
    assert findings(env) == []


def test_a_free_seat_with_a_todo_cr_waiting_is_a_finding_and_a_taken_cr_is_not(session_env):
    env = session_env
    env.manager().start("leader")
    first, second, third = env.cr(1), env.cr(2), env.cr(3)
    env.manager().start(first)
    env.manager().start(second)                                  # both fixture seats are taken
    assert findings(env) == []
    env.finish(second)                                           # its CR is done: the seat can be given back
    env.manager().control("stop", job=second)
    [line] = findings(env)
    assert "빈 seat 1" in line and third in line and first not in line


def test_a_stopped_worker_whose_cr_is_still_in_progress_is_a_release_wait(session_env):
    env = session_env
    env.manager().start("leader")
    cr = env.cr()
    env.manager().start(cr)
    env.manager().control("stop", job=cr)                        # the CR stays in-progress, so the seat is not released
    [line] = findings(env)
    assert "반납 대기 seat" in line and cr in line


def test_an_answered_decision_the_leader_has_not_finished_is_a_finding(session_env):
    env = session_env
    env.manager().start("leader")
    answered = env.base / "agent" / "decide" / "answered"
    answered.mkdir(parents=True)
    (answered / "D-20261111-01-pick-one.md").write_text("# D-20261111-01: Pick one\n")
    [line] = findings(env)
    assert "답을 받고" in line and "D-20261111-01" in line
    (env.base / "agent" / "decide" / "open").mkdir()
    (env.base / "agent" / "decide" / "open" / "D-20261111-02-asks.md").write_text("# D-20261111-02: Asks\n")
    assert len(findings(env)) == 1                                # an open decision waits for the user, not the Leader


def test_a_worker_whose_cli_is_gone_is_a_finding(session_env, monkeypatch):
    env = session_env
    env.manager().start("leader")
    cr = env.cr()
    env.manager().start(cr)
    assert findings(env) == []
    monkeypatch.setattr(process, "cli_alive", lambda meta, pane: False)
    [line] = findings(env)
    assert "사라진 Worker" in line and cr in line and "seat 0" in line


def test_a_group_that_cannot_be_judged_is_a_finding_that_errs_toward_telling_the_leader(session_env, monkeypatch):
    env = session_env
    env.manager().start("leader")
    monkeypatch.setattr(jobs, "waiting_review", lambda project: (_ for _ in ()).throw(RuntimeError("boom")))
    [line] = findings(env)
    assert "review_waits" in line and "판정하지 못했습니다(RuntimeError)" in line


def test_several_findings_are_listed_one_per_group(session_env):
    env = session_env
    env.manager().start("leader")
    cr = env.cr()
    env.manager().start(cr)
    submit(env, cr)
    env.cr(2)
    (env.base / "agent" / "decide" / "answered").mkdir(parents=True)
    (env.base / "agent" / "decide" / "answered" / "D-20261111-01-x.md").write_text("# D-20261111-01: X\n")
    kinds = [line.split(" ")[0] for line in findings(env)]
    assert len(kinds) == 3 and kinds[0] == "review"


# The command

def test_an_idle_leader_with_a_finding_is_told_once_and_a_working_one_is_not(session_env, last, capsys):
    env = session_env
    env.manager().start("leader")
    cr = env.cr()
    env.manager().start(cr)
    submit(env, cr)
    last.at = time.time() - 10                                  # the Leader is working
    code, out = check(env, capsys)
    assert code == 0 and messages(env) == []
    leader_target = out["data"]["projects"][0]["targets"][0]
    assert (leader_target["slot"], leader_target["status"]) == ("leader", "active")
    last.at = time.time() - 2 * THRESHOLD                       # it has been still for an hour
    check(env, capsys)
    [sent] = messages(env)
    assert cr in sent["text"] and "review 대기 CR" in sent["text"] and "처리할 일" in sent["text"]
    check(env, capsys)                                          # the same rest: no second message
    assert len(messages(env)) == 1


def test_a_new_rest_with_the_finding_still_open_is_told_again(session_env, last):
    env = session_env
    env.manager().start("leader")
    cr = env.cr()
    env.manager().start(cr)
    submit(env, cr)
    now = time.time()
    last.at = now - 2 * THRESHOLD

    def look(at):
        manager = env.manager()
        return manager.watch_target("leader", THRESHOLD, now=at, findings=manager.leader_findings(manager.store.read()))

    assert look(now)["status"] == "resting" and len(messages(env)) == 1
    assert look(now + 600)["status"] == "resting" and len(messages(env)) == 1       # the same rest
    last.at = now + 700                                          # the Leader answered, then rested again
    assert look(now + 800)["status"] == "active"
    assert look(now + 700 + THRESHOLD)["status"] == "resting" and len(messages(env)) == 2


def test_an_idle_leader_with_nothing_to_do_gets_nothing_and_the_run_is_kept_as_idle(session_env, last, capsys):
    env = session_env
    env.manager().start("leader")
    last.at = time.time() - 10 * THRESHOLD
    code, out = check(env, capsys)
    [target] = out["data"]["projects"][0]["targets"]
    assert code == 0 and (target["status"], target["reason"]) == ("skipped", "nothing_to_do")
    assert messages(env) == [] and out["data"]["projects"][0]["run"] == {"ok": True, "result": "idle"}
    record = json.loads((env.base / "agent" / "cron" / "check.json").read_text())
    assert record["ok"] is True and record["result"] == "idle" and record["at"].endswith("Z")


def test_a_notified_run_is_kept_as_notified_and_cron_ls_shows_it(session_env, last, capsys):
    env = session_env
    env.manager().start("leader")
    cr = env.cr()
    env.manager().start(cr)
    submit(env, cr)
    last.at = time.time() - 2 * THRESHOLD
    _, out = check(env, capsys)
    assert out["data"]["projects"][0]["run"] == {"ok": True, "result": "notified"}
    capsys.readouterr()
    assert cli.main(["--config", str(env.config), "--socket-name", env.socket_name,
                     "cron", "ls", "--project", "fixture"]) == 0
    [job] = json.loads(capsys.readouterr().out)["data"]["jobs"]
    assert job["id"] == "check" and job["last_run"]["result"] == "notified" and job["last_run"]["ok"] is True


def test_a_failing_run_is_kept_as_not_ok(session_env, last, capsys, monkeypatch):
    env = session_env
    env.manager().start("leader")
    last.at = time.time() - 10 * THRESHOLD
    monkeypatch.setattr(Manager, "watch_target", lambda self, *a, **k: (_ for _ in ()).throw(ValueError("x")))
    _, out = check(env, capsys)
    assert out["data"]["projects"][0]["run"] == {"ok": False, "result": "error", "code": "internal_error"}
    record = json.loads((env.base / "agent" / "cron" / "check.json").read_text())
    assert record["ok"] is False and record["code"] == "internal_error"


def test_the_check_wakes_a_stalled_worker_as_watch_does(session_env, last, capsys):
    env = session_env
    env.manager().start("leader")
    cr = env.cr()
    env.manager().start(cr)
    last.at = time.time() - 2 * THRESHOLD
    check(env, capsys)
    path = env.base / "agent" / "fixture-messages.jsonl"
    texts = [json.loads(line) for line in path.read_text().splitlines()]
    assert [item["target"] for item in texts if "[agent-session watch]" in item["text"]] == ["seat-0", "leader"]
    assert not messages(env)                                    # nothing for the Leader to do besides the Worker notice


def test_the_check_is_for_one_project_and_the_operator_or_its_leader(session_env, last, capsys, monkeypatch):
    env = session_env
    leader = env.manager().start("leader")
    cr = env.cr()
    worker = env.manager().start(cr)
    submit(env, cr)
    last.at = time.time() - 2 * THRESHOLD
    capsys.readouterr()
    assert cli.main(["--config", str(env.config), "check"]) == 2          # --project is required
    with monkeypatch.context() as actor:
        actor.setenv("CODEX_THREAD_ID", worker["session"]["session_id"])
        code, out = check(env, capsys)
        assert code != 0 and out["error"]["code"] == "role_denied"
    assert messages(env) == []
    with monkeypatch.context() as actor:                         # the Leader's own run is not messaged by itself
        actor.setenv("CODEX_THREAD_ID", leader["session"]["session_id"])
        code, out = check(env, capsys)
        assert code == 0 and messages(env) == []


# The Leader's start keeps the project's check job

def test_starting_a_leader_adds_the_check_job_and_a_restart_finds_it(session_env):
    env = session_env
    assert not env.crontab.exists()
    first = env.manager().start("leader")
    assert first["cron"] == {"check": "added"}
    text = env.crontab.read_text()
    assert "# >>> project-agent: fixture >>>" in text and "# job check:" in text
    [job] = cron.listing(env.project, cron.Crontab(env.root / "crontab.lock"))["jobs"]
    assert job["id"] == "check" and f"--config {env.config}" in job["command"]
    assert f"--socket-name {env.socket_name}" in job["command"] and job["command"].endswith(" check --project fixture >/dev/null 2>&1")
    env.manager().control("stop", job="leader")
    again = env.manager().start("leader")
    assert again["cron"] == {"check": "present"} and env.crontab.read_text() == text


def test_a_worker_start_does_not_touch_the_crontab(session_env):
    env = session_env
    env.manager().start("leader")
    before = env.crontab.read_text()
    result = env.manager().start(env.cr())
    assert "cron" not in result and env.crontab.read_text() == before


def test_a_crontab_that_cannot_be_read_does_not_stop_the_leader(session_env, monkeypatch):
    env = session_env
    env.crontab.write_text("0 1 * * * /user\n")
    monkeypatch.setenv("FAKE_CRONTAB_FAIL", "read")
    result = env.manager().start("leader")
    assert result["cron"]["check"] == "failed" and result["cron"]["error"]["code"] == "crontab_unreadable"
    assert env.crontab.read_text() == "0 1 * * * /user\n"
    monkeypatch.delenv("FAKE_CRONTAB_FAIL")
    env.manager().control("stop", job="leader")
    assert env.manager().start("leader")["cron"] == {"check": "added"}
    assert env.crontab.read_text().startswith("0 1 * * * /user\n")


# SESSION-016: the check job under cron's environment

def cron_run(env, line, path):
    """What cron does: the line in `/bin/sh` with a minimal environment and PATH `path`."""
    import os
    import subprocess
    return subprocess.run(["env", "-i", f"HOME={os.environ['HOME']}", f"PATH={path}", "/bin/sh", "-c", line],
                          capture_output=True, text=True, timeout=120)


def kept_run(env):
    return json.loads((env.base / "agent" / "cron" / "check.json").read_text())


def with_a_worker(env):
    """A Leader and a Worker on a CR in progress: the check has a window to ask tmux about."""
    env.manager().start("leader")
    env.manager().start(env.cr())


def wrong_tmux(tmp_path):
    """A directory whose `tmux` does not speak to the server (the system tmux 2.7 against a 3.8 server)."""
    wrong = tmp_path / "wrong"
    wrong.mkdir()
    (wrong / "tmux").write_text("#!/bin/sh\necho 'lost server' >&2\nexit 1\n")
    (wrong / "tmux").chmod(0o755)
    return wrong


def test_the_check_line_reaches_the_leaders_tmux_where_a_wrong_tmux_stands_ahead_in_cron_path(
        session_env, monkeypatch, tmp_path):
    import shutil
    env = session_env
    with_a_worker(env)
    right = tmp_path / "right"
    right.mkdir()
    (right / "tmux").symlink_to(shutil.which("tmux"))
    monkeypatch.setattr(cron, "tmux_directory", lambda: str(right))     # the tmux the Leader start ran with
    line = cron.check_command(env.project, socket_name=env.socket_name)
    assert line.startswith(f"env PATH={right}:/usr/bin:/bin ")
    done = cron_run(env, line, f"{wrong_tmux(tmp_path)}:/usr/bin:/bin")
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
    record = kept_run(env)
    assert record["ok"] is True and record["result"] == "idle" and "code" not in record


def test_a_tmux_that_cannot_reach_the_server_leaves_its_code_in_the_run(session_env, monkeypatch, tmp_path):
    env = session_env
    with_a_worker(env)
    monkeypatch.setattr(cron, "tmux_directory", lambda: None)           # a line without the Leader's tmux
    line = cron.check_command(env.project, socket_name=env.socket_name)
    assert not line.startswith("env ")
    cron_run(env, line, f"{wrong_tmux(tmp_path)}:/usr/bin:/bin")
    record = kept_run(env)
    assert record["ok"] is False and record["result"] == "error" and record["code"] == "tmux_command_failed"


def test_without_any_tmux_the_run_names_tmux_unavailable(session_env, capsys, monkeypatch, tmp_path):
    env = session_env
    with_a_worker(env)
    empty = tmp_path / "empty"
    empty.mkdir()
    with monkeypatch.context() as search:
        search.setenv("PATH", str(empty))
        _, out = check(env, capsys)
    assert out["data"]["projects"][0]["run"] == {"ok": False, "result": "error", "code": "tmux_unavailable"}
    assert kept_run(env)["code"] == "tmux_unavailable"
