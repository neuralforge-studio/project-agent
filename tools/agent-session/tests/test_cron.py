"""SESSION-015. A project's cron jobs live in one marked section of the user's crontab.

Nothing here touches the real crontab: `conftest.isolated_crontab` puts a shim over a file of the test on PATH
(`tests/fake_crontab.py`). The next-run rule is checked against hand-written cases (`fixtures/cron_next_run.json`)
that the Board's sidebar must also meet."""

import datetime as dt
import json
import os
from pathlib import Path
import threading

import pytest

from agent_session import cli, cron
from agent_session.config import load_registry
from agent_session.errors import SessionError

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "cron_next_run.json").read_text(encoding="utf-8"))
USER = "0 23 * * * /home/user/nightly.sh\n*/5 * * * * /home/user/poll.sh --flag\n"


@pytest.fixture(autouse=True)
def an_operator(monkeypatch):
    """The commands run as the operator unless a test sets an identity (an agent session would otherwise be one)."""
    for name in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "AGENT_SESSION_CONFIG", "TMUX", "TMUX_PANE"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def crontab_file():
    return Path(os.environ["FAKE_CRONTAB"])


@pytest.fixture
def crontab(tmp_path):
    return cron.Crontab(tmp_path / "crontab.lock")


def make_projects(tmp_path, *names):
    registry = {}
    for name in names:
        base = tmp_path / f"{name}.base"
        (base / "agent").mkdir(parents=True)
        registry[str(base)] = {"project": name, "provider": "codex", "seats": []}
    config = tmp_path / "project.json"
    config.write_text(json.dumps(registry))
    return config, {item.project_id: item for item in load_registry(config)}


@pytest.fixture
def projects(tmp_path):
    config, found = make_projects(tmp_path, "alpha", "beta")
    return config, found


def add_job(project, crontab, job_id="check", command="/bin/true"):
    return cron.add(project, crontab, job_id, "13,43 * * * *", "점검", command)


# The next-run rule

@pytest.mark.parametrize("case", FIXTURE["next_run"], ids=lambda case: f"{case['schedule']}@{case['after']}")
def test_next_run_matches_the_hand_written_cases(case):
    got = cron.next_run(case["schedule"], dt.datetime.fromisoformat(case["after"]))
    assert got.isoformat(timespec="minutes") == case["next"]


@pytest.mark.parametrize("text", FIXTURE["invalid"])
def test_a_schedule_outside_the_number_grammar_is_refused(text):
    with pytest.raises(SessionError) as error:
        cron.Schedule(text)
    assert error.value.code == "cron_invalid"


def test_the_check_schedule_is_every_thirty_minutes_off_the_hour_marks():
    schedule = cron.Schedule(cron.CHECK_SCHEDULE)
    first = schedule.next_run(dt.datetime(2026, 11, 11, 0, 0))
    second = schedule.next_run(first)
    assert (second - first) == dt.timedelta(minutes=30) and first.minute not in (0, 30) and second.minute not in (0, 30)


# The project's section

def test_adding_a_job_keeps_every_other_line_and_removing_it_restores_the_crontab(projects, crontab, crontab_file):
    _, found = projects
    for original in (USER, USER + "\n", "# only a comment\n", ""):
        if original:
            crontab_file.write_text(original)
        elif crontab_file.exists():
            crontab_file.unlink()
        add_job(found["alpha"], crontab)
        text = crontab_file.read_text()
        assert text.startswith(original) and "# >>> project-agent: alpha >>>" in text and text.endswith("\n")
        cron.remove(found["alpha"], crontab, "check")
        assert (crontab_file.read_text() if crontab_file.exists() else "") == original


def test_a_user_crontab_without_a_final_newline_gets_one_and_keeps_its_lines(projects, crontab, crontab_file):
    _, found = projects
    crontab_file.write_text("0 1 * * * /a")
    add_job(found["alpha"], crontab)
    assert crontab_file.read_text().startswith("0 1 * * * /a\n")


def test_each_project_has_its_own_section_and_one_never_touches_the_other(projects, crontab, crontab_file):
    _, found = projects
    crontab_file.write_text(USER)
    add_job(found["alpha"], crontab, command="/alpha")
    add_job(found["beta"], crontab, command="/beta")
    cron.add(found["alpha"], crontab, "report", "0 9 * * 1-5", "보고", "/alpha/report")
    beta_lines = [line for line in crontab_file.read_text().splitlines() if "beta" in line or "/beta" in line]
    cron.remove(found["alpha"], crontab, "check")
    assert [line for line in crontab_file.read_text().splitlines() if "beta" in line or "/beta" in line] == beta_lines
    assert [job["id"] for job in cron.listing(found["alpha"], crontab)["jobs"]] == ["report"]
    assert [job["id"] for job in cron.listing(found["beta"], crontab)["jobs"]] == ["check"]
    cron.remove(found["alpha"], crontab, "report")
    cron.remove(found["beta"], crontab, "check")
    assert crontab_file.read_text() == USER


def test_a_percent_in_a_command_is_escaped_in_the_crontab_and_read_back_whole(projects, crontab, crontab_file):
    _, found = projects
    add_job(found["alpha"], crontab, command="date +%Y%m%d >> /tmp/x")
    assert "date +\\%Y\\%m\\%d >> /tmp/x" in crontab_file.read_text()
    [job] = cron.listing(found["alpha"], crontab)["jobs"]
    assert job["command"] == "date +%Y%m%d >> /tmp/x"


def test_a_job_is_listed_with_its_schedule_description_and_next_and_last_run(projects, crontab):
    _, found = projects
    project = found["alpha"]
    add_job(project, crontab)
    now = dt.datetime(2026, 11, 11, 20, 15)
    [job] = cron.listing(project, crontab, now=now)["jobs"]
    assert (job["id"], job["schedule"], job["description"]) == ("check", "13,43 * * * *", "점검")
    assert job["next_run"] == "2026-11-11T20:43" and job["last_run"] is None
    cron.record_run(project, "check", False, "error", at=0)
    [job] = cron.listing(project, crontab, now=now)["jobs"]
    assert job["last_run"] == {"at": "1970-01-01T00:00:00Z", "ok": False, "result": "error"}
    assert cron.listing(project, crontab, now=now, summary=True) == {
        "project": "alpha", "count": 1, "next_run": "2026-11-11T20:43"}
    assert cron.listing(found["beta"], crontab, now=now, summary=True) == {
        "project": "beta", "count": 0, "next_run": None}


def test_the_nearest_next_run_of_several_jobs_is_the_summary(projects, crontab):
    _, found = projects
    add_job(found["alpha"], crontab)
    cron.add(found["alpha"], crontab, "daily", "0 21 * * *", "매일", "/x")
    summary = cron.listing(found["alpha"], crontab, now=dt.datetime(2026, 11, 11, 20, 50), summary=True)
    assert summary == {"project": "alpha", "count": 2, "next_run": "2026-11-11T21:00"}


def test_job_ids_schedules_and_text_are_checked_before_anything_is_written(projects, crontab, crontab_file):
    _, found = projects
    for args in (("Check", "* * * * *", "d", "c"), ("ok", "* * * *", "d", "c"), ("ok", "* * * * *", "", "c"),
                 ("ok", "* * * * *", "two\nlines", "c"), ("ok", "* * * * *", "d", "c\nd"), ("ok", "* * * * *", "d", " ")):
        with pytest.raises(SessionError) as error:
            cron.add(found["alpha"], crontab, *args)
        assert error.value.code == "cron_invalid"
    assert not crontab_file.exists()


def test_an_existing_id_is_refused_and_a_missing_one_cannot_be_removed(projects, crontab, crontab_file):
    _, found = projects
    add_job(found["alpha"], crontab)
    before = crontab_file.read_text()
    with pytest.raises(SessionError) as error:
        add_job(found["alpha"], crontab)
    assert error.value.code == "cron_exists"
    with pytest.raises(SessionError) as error:
        cron.remove(found["alpha"], crontab, "nothing")
    assert error.value.code == "cron_not_found"
    assert crontab_file.read_text() == before


# Failures never lose the user's lines

def calls(log):
    return log.read_text().splitlines() if log.exists() else []


def test_a_crontab_that_cannot_be_read_is_never_written(projects, crontab, crontab_file, monkeypatch, tmp_path):
    _, found = projects
    crontab_file.write_text(USER)
    log = tmp_path / "calls.log"
    monkeypatch.setenv("FAKE_CRONTAB_LOG", str(log))
    monkeypatch.setenv("FAKE_CRONTAB_FAIL", "read")
    with pytest.raises(SessionError) as error:
        add_job(found["alpha"], crontab)
    assert error.value.code == "crontab_unreadable"
    assert "-" not in calls(log) and crontab_file.read_text() == USER


def test_a_user_without_a_crontab_starts_from_an_empty_one(projects, crontab, crontab_file):
    _, found = projects
    assert not crontab_file.exists()
    assert cron.listing(found["alpha"], crontab)["jobs"] == []
    add_job(found["alpha"], crontab)
    assert crontab_file.read_text().splitlines()[0] == "# >>> project-agent: alpha >>>"


def test_a_failed_write_is_reported_and_leaves_the_crontab(projects, crontab, crontab_file, monkeypatch):
    _, found = projects
    crontab_file.write_text(USER)
    monkeypatch.setenv("FAKE_CRONTAB_FAIL", "write")
    with pytest.raises(SessionError) as error:
        add_job(found["alpha"], crontab)
    assert error.value.code == "crontab_unwritable" and crontab_file.read_text() == USER


def test_a_missing_crontab_command_is_reported(projects, crontab, monkeypatch):
    _, found = projects
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(SessionError) as error:
        cron.listing(found["alpha"], crontab)
    assert error.value.code == "crontab_unavailable"


@pytest.mark.parametrize("text", [
    "# >>> project-agent: alpha >>>\n# job check: d\n* * * * * /x\n",                                  # no end
    "# <<< project-agent: alpha <<<\n",                                                                # no begin
    "# >>> project-agent: alpha >>>\n# <<< project-agent: alpha <<<\n# >>> project-agent: alpha >>>\n# <<< project-agent: alpha <<<\n",
    "# >>> project-agent: alpha >>>\nnot a job\n# <<< project-agent: alpha <<<\n",                      # a stray line
    "# >>> project-agent: alpha >>>\n# job check: d\n# <<< project-agent: alpha <<<\n",                 # comment without schedule
])
def test_a_damaged_section_stops_every_write_and_names_the_project(projects, crontab, crontab_file, text):
    _, found = projects
    crontab_file.write_text(USER + text)
    with pytest.raises(SessionError) as error:
        add_job(found["alpha"], crontab)
    assert error.value.code == "cron_invalid" and error.value.details["project"] == "alpha"
    assert crontab_file.read_text() == USER + text
    add_job(found["beta"], crontab)                      # another project's section is still its own
    assert "project-agent: beta" in crontab_file.read_text()


def test_concurrent_edits_of_several_projects_lose_no_job_and_no_user_line(tmp_path, crontab_file):
    config, found = make_projects(tmp_path, *[f"p{n}" for n in range(6)])
    crontab_file.write_text(USER)
    errors = []

    def work(name):
        try:
            editor = cron.Crontab(tmp_path / "shared.lock")
            for number in range(3):
                cron.add(found[name], editor, f"job{number}", "1 * * * *", "d", f"/{name}/{number}")
        except Exception as error:                      # noqa: BLE001 - reported below
            errors.append(error)

    threads = [threading.Thread(target=work, args=(name,)) for name in found]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    text = crontab_file.read_text()
    assert text.startswith(USER)
    editor = cron.Crontab(tmp_path / "shared.lock")
    for name, project in found.items():
        assert [job["id"] for job in cron.listing(project, editor)["jobs"]] == ["job0", "job1", "job2"]


def test_another_editor_that_changes_the_crontab_between_read_and_write_is_not_overwritten(projects, crontab, crontab_file):
    _, found = projects
    crontab_file.write_text(USER)
    real, seen = crontab.read, []

    def racing_read():
        text = real()
        seen.append(text)
        if len(seen) == 1:                               # a person runs `crontab -e` right after the first read
            crontab_file.write_text(text + "30 5 * * * /added/by/hand\n")
        return text

    crontab.read = racing_read
    add_job(found["alpha"], crontab)
    text = crontab_file.read_text()
    assert "30 5 * * * /added/by/hand" in text and "project-agent: alpha" in text and text.startswith(USER)


# ensure_check

def test_the_check_job_is_added_once_and_is_idempotent(projects, crontab, crontab_file, tmp_path):
    _, found = projects
    crontab_file.write_text(USER)
    assert cron.ensure_check(found["alpha"], crontab) == {"check": "added"}
    first = crontab_file.read_text()
    assert cron.ensure_check(found["alpha"], crontab) == {"check": "present"}
    assert crontab_file.read_text() == first and first.startswith(USER)
    [job] = cron.listing(found["alpha"], crontab)["jobs"]
    assert job["schedule"] == cron.CHECK_SCHEDULE and job["description"] == cron.CHECK_DESCRIPTION
    # The command runs this release's check for the project, silently (cron would mail any output).
    assert job["command"].endswith(" check --project alpha >/dev/null 2>&1")
    assert f"--config {found['alpha'].config_path}" in job["command"]
    assert str(Path(cron.__file__).resolve().parents[1] / "bin" / "agent-session") in job["command"]


def test_ensure_follows_the_release_for_the_command_but_keeps_a_changed_schedule(projects, crontab, crontab_file):
    _, found = projects
    cron.add(found["alpha"], crontab, "check", "5 * * * *", "내가 바꾼 점검", "/old/release/agent-session check")
    assert cron.ensure_check(found["alpha"], crontab) == {"check": "updated"}
    [job] = cron.listing(found["alpha"], crontab)["jobs"]
    assert (job["schedule"], job["description"]) == ("5 * * * *", "내가 바꾼 점검")
    assert "/old/release" not in job["command"] and " check --project alpha" in job["command"]


def test_the_check_command_names_the_socket_it_was_given(projects):
    _, found = projects
    named = cron.check_command(found["alpha"], socket_name="main")
    pathed = cron.check_command(found["alpha"], socket_path="/tmp/s ock")
    assert "--socket-name main" in named and "--socket-path '/tmp/s ock'" in pathed
    assert "--socket" not in cron.check_command(found["alpha"])


# The command

def run(config, *arguments, capsys):
    capsys.readouterr()
    code = cli.main(["--config", str(config), "cron", *arguments])
    return code, json.loads(capsys.readouterr().out)


def test_the_cron_command_lists_adds_and_removes_in_json(projects, crontab_file, capsys):
    config, _ = projects
    crontab_file.write_text(USER)
    code, out = run(config, "add", "--project", "alpha", "--id", "report", "--schedule", "0 9 * * 1-5",
                    "--description", "평일 보고", "--command", "echo 100%", capsys=capsys)
    assert code == 0 and out["ok"] and out["data"]["job"]["id"] == "report" and out["data"]["written"] is True
    code, out = run(config, "ls", "--project", "alpha", capsys=capsys)
    [job] = out["data"]["jobs"]
    assert code == 0 and job["command"] == "echo 100%" and job["next_run"] and job["last_run"] is None
    code, out = run(config, "ls", "--project", "alpha", "--summary", capsys=capsys)
    assert out["data"]["count"] == 1 and out["data"]["next_run"] == job["next_run"]
    code, out = run(config, "rm", "--project", "alpha", "--id", "report", capsys=capsys)
    assert code == 0 and out["data"]["removed"] == "report" and crontab_file.read_text() == USER
    code, out = run(config, "rm", "--project", "alpha", "--id", "report", capsys=capsys)
    assert code != 0 and out["error"]["code"] == "cron_not_found"
    code, out = run(config, "ls", "--project", "nobody", capsys=capsys)
    assert code == 2 and out["error"]["code"] == "project_not_found"
    code, out = run(config, "add", "--project", "alpha", "--id", "x", "--schedule", "bad", "--description", "d",
                    "--command", "c", capsys=capsys)
    assert code == 2 and out["error"]["code"] == "cron_invalid" and crontab_file.read_text() == USER


def test_an_agent_that_is_not_a_member_of_the_project_may_not_use_cron(projects, crontab_file, monkeypatch, capsys):
    config, _ = projects
    monkeypatch.setenv("CODEX_THREAD_ID", "someone-else")
    for arguments in (("ls", "--project", "alpha"), ("add", "--project", "alpha", "--id", "x", "--schedule",
                                                     "* * * * *", "--description", "d", "--command", "c")):
        code, out = run(config, *arguments, capsys=capsys)
        assert code != 0 and out["error"]["code"] == "caller_unbound"
    assert not crontab_file.exists()


# The sections as a reader outside agent-session (the installer) sees them: `api.crontab_sections`

def test_the_sections_of_the_crontab_are_listed_with_their_jobs_and_marker_lines(projects, crontab, crontab_file):
    from agent_session import api
    _, found = projects
    crontab_file.write_text(USER)
    assert api.crontab_sections() == []
    add_job(found["alpha"], crontab, command="/r/1/bin/agent-session check --project alpha")
    cron.add(found["alpha"], crontab, "report", "0 8 * * *", "d", "/r/1/bin/report 50%")
    add_job(found["beta"], crontab)
    assert api.crontab_sections() == [
        {"project": "alpha", "begin": "# >>> project-agent: alpha >>>", "end": "# <<< project-agent: alpha <<<",
         "error": None, "jobs": [{"id": "check", "command": "/r/1/bin/agent-session check --project alpha"},
                                 {"id": "report", "command": "/r/1/bin/report 50%"}]},
        {"project": "beta", "begin": "# >>> project-agent: beta >>>", "end": "# <<< project-agent: beta <<<",
         "error": None, "jobs": [{"id": "check", "command": "/bin/true"}]}]


def test_a_damaged_section_is_listed_with_its_error_and_the_others_stay_readable(crontab_file):
    from agent_session import api
    crontab_file.write_text("# >>> project-agent: bad >>>\n" + USER + "# >>> project-agent: ok >>>\n"
                            "# job check: d\n* * * * * /x\n# <<< project-agent: ok <<<\n")
    listed = api.crontab_sections()
    assert [(item["project"], item["error"]) for item in listed] == [("bad", "cron_invalid"), ("ok", None)]
    assert listed[0]["jobs"] == [] and listed[1]["jobs"] == [{"id": "check", "command": "/x"}]


def test_sections_of_a_crontab_that_cannot_be_read_are_an_error_not_an_empty_list(crontab_file, monkeypatch):
    from agent_session import api
    monkeypatch.setenv("FAKE_CRONTAB_FAIL", "read")
    with pytest.raises(SessionError) as error:
        api.crontab_sections()
    assert error.value.code == "crontab_unreadable"


# SESSION-016: the check job reaches the Leader's tmux under cron's PATH

def fake_tmux_dir(tmp_path, name, body="exit 0"):
    directory = tmp_path / name
    directory.mkdir()
    (directory / "tmux").write_text(f"#!/bin/sh\n{body}\n")
    (directory / "tmux").chmod(0o755)
    return directory


def test_the_check_line_puts_the_tmux_of_the_leader_start_ahead_of_crons_path(projects, tmp_path, monkeypatch):
    _, found = projects
    directory = fake_tmux_dir(tmp_path, "in house")                      # a space: the line must still be one word
    monkeypatch.setenv("PATH", f"{directory}:/usr/bin:/bin")
    command = cron.check_command(found["alpha"], socket_path="/tmp/tmux-1/default")
    assert command.startswith(f"env 'PATH={directory}:/usr/bin:/bin' ")
    assert " --socket-path /tmp/tmux-1/default check --project alpha >/dev/null 2>&1" in command


def test_the_check_line_has_no_env_without_a_tmux_or_when_cron_finds_it_anyway(projects, tmp_path, monkeypatch):
    _, found = projects
    monkeypatch.setenv("PATH", str(tmp_path))                            # no tmux in it
    assert cron.check_command(found["alpha"]).startswith(str(Path(cron.__file__).resolve().parents[1] / "bin"))
    monkeypatch.setattr(cron.shutil, "which", lambda name: "/usr/bin/tmux")
    assert not cron.check_command(found["alpha"]).startswith("env ")


def test_ensure_replaces_an_old_command_and_a_hand_written_path_prefix_and_keeps_the_users_jobs(
        projects, crontab, tmp_path, monkeypatch):
    _, found = projects
    # In front of the PATH of the test, which holds the `crontab` shim: the real crontab is never reached.
    monkeypatch.setenv("PATH", f"{fake_tmux_dir(tmp_path, 'mine')}:{os.environ['PATH']}")
    cron.add(found["alpha"], crontab, "report", "0 9 * * *", "보고", "PATH=/keep/me:/bin /home/user/report.sh")
    cron.add(found["alpha"], crontab, "check", "13,43 * * * *", "점검",
             "PATH=/primehome/tools/Inhouse/tmux/latest/bin:/usr/bin:/bin /old/release/agent-session check")
    assert cron.ensure_check(found["alpha"], crontab) == {"check": "updated"}
    jobs = {job["id"]: job["command"] for job in cron.listing(found["alpha"], crontab)["jobs"]}
    assert jobs["check"] == cron.check_command(found["alpha"]) and "/old/release" not in jobs["check"]
    assert jobs["check"].startswith(f"env PATH={tmp_path / 'mine'}:/usr/bin:/bin ")
    assert jobs["report"] == "PATH=/keep/me:/bin /home/user/report.sh"
    assert cron.ensure_check(found["alpha"], crontab) == {"check": "present"}
