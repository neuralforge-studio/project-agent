"""Acceptance tests T34-T35 of install-contract.md section 8.2: the project-agent sections that stay in the
user's crontab (5.4, 7). The crontab is the fake of tools/tests/fake_crontab.py (a file outside HOME).

The crontab texts are written here from the section format of docs/project-team/spec.md (cron), not produced
by the product, so a change of the format in `cron.py` shows up as a failing test.
"""

import json
import subprocess

from harness import LIB

USER_TOP = "MAILTO=me@example.invalid\n0 3 * * * /usr/bin/backup --all\n"
USER_BOTTOM = "# mine\n*/5 * * * * /usr/bin/ping-me\n"
RELEASE = "/gone/releases/0.0.0-dead"


def section(name, program="%s/bin/agent-session" % RELEASE):
    return ("# >>> project-agent: %s >>>\n# job check: describe\n13,43 * * * * %s --config /c.json check "
            "--project %s >/dev/null 2>&1\n# <<< project-agent: %s <<<\n" % (name, program, name, name))


def notes_of(result):
    return json.loads(result.stdout)["notes"]


def crontab_notes(result):
    return [note for note in notes_of(result) if "crontab" in note]


def removal_commands(result):
    return [line.strip() for note in notes_of(result) for line in note.splitlines()
            if line.strip().startswith("text=$(crontab -l)")]


def run_shell(home, command):
    done = subprocess.run(["sh", "-c", command], capture_output=True, text=True, timeout=60, env=home.env)
    assert done.returncode == 0, done.stderr


def test_t34_uninstall_prints_the_commands_that_remove_the_sections_and_leaves_the_crontab(home, source):
    assert home.run("install", source=source).returncode == 0
    text = USER_TOP + "\n" + section("alpha") + "\n" + section("beta") + USER_BOTTOM
    home.crontab.write_text(text)
    before = home.snapshot()
    dry = home.run("uninstall", "--dry-run", "--json")
    assert dry.returncode == 0, dry.stderr
    assert home.snapshot() == before and home.crontab.read_text() == text
    result = home.run("uninstall", "--json")
    assert result.returncode == 0, result.stderr
    assert home.crontab.read_text() == text                          # printed, never written
    commands = removal_commands(result)
    assert len(commands) == 2 and removal_commands(dry) == commands   # one per project, the dry run shows the same
    assert any("alpha" in note and "(check)" in note for note in crontab_notes(result))
    assert not home.path(LIB).exists()                                # the uninstall itself went through
    for command in commands:                                          # they work after the release is gone
        run_shell(home, command)
    assert home.crontab.read_text() == USER_TOP + "\n\n" + USER_BOTTOM   # user lines kept; the blank separators stay


def test_t34_a_section_name_with_pattern_characters_removes_only_its_own_section(home, source):
    assert home.run("install", source=source).returncode == 0
    text = section("a.b") + section("aXb") + section("c*")
    home.crontab.write_text(text)
    result = home.run("uninstall", "--json")
    for command in removal_commands(result):
        run_shell(home, command)
    assert home.crontab.read_text() == ""


def test_t34_without_sections_or_crontab_uninstall_says_nothing_about_the_crontab(home, source):
    assert home.run("install", source=source).returncode == 0
    result = home.run("uninstall", "--json")                          # no crontab file: no crontab for the user
    assert result.returncode == 0 and crontab_notes(result) == []
    assert not home.crontab.exists()
    assert home.run("install", source=source).returncode == 0
    home.crontab.write_text(USER_TOP + USER_BOTTOM)
    result = home.run("uninstall", "--json")
    assert result.returncode == 0 and crontab_notes(result) == []
    assert home.crontab.read_text() == USER_TOP + USER_BOTTOM


def test_t34_a_broken_section_is_not_given_a_removal_command_and_an_unreadable_crontab_is_told(home, source):
    assert home.run("install", source=source).returncode == 0
    home.crontab.write_text(USER_TOP + section("whole") + "# >>> project-agent: broken >>>\n" + USER_BOTTOM)
    result = home.run("uninstall", "--json")
    assert result.returncode == 0
    assert len(removal_commands(result)) == 1 and "whole" in removal_commands(result)[0]
    assert any("broken" in note and "crontab -e" in note for note in crontab_notes(result))
    assert home.run("install", source=source).returncode == 0
    result = home.run("uninstall", "--json", env={"FAKE_CRONTAB_FAIL": "read"})
    assert result.returncode == 0 and removal_commands(result) == []
    assert any("could not be read" in note and "crontab_unreadable" in note for note in crontab_notes(result))


def test_t35_check_names_a_section_whose_release_is_gone(home, source):
    assert home.run("install", source=source).returncode == 0
    alive = str(home.path(LIB + "/current/tools/agent-session/bin/agent-session"))
    home.crontab.write_text(USER_TOP + section("gone") + section("here", program=alive))
    result = home.run("check", "--json")
    assert result.returncode == 0, result.stdout                      # a notice, not a failure
    found = crontab_notes(result)
    assert len(found) == 1 and "gone" in found[0] and RELEASE in found[0] and "here" not in found[0]
    assert "agent-session cron rm --project gone --id check" in found[0]
    assert home.crontab.read_text() == USER_TOP + section("gone") + section("here", program=alive)   # read only


def test_t35_check_is_quiet_without_sections_and_tells_an_unreadable_crontab(home, source):
    assert home.run("install", source=source).returncode == 0
    assert crontab_notes(home.run("check", "--json")) == []
    home.crontab.write_text(USER_TOP)
    assert crontab_notes(home.run("check", "--json")) == []
    result = home.run("check", "--json", env={"FAKE_CRONTAB_FAIL": "read"})
    assert result.returncode == 0
    assert any("could not be read" in note for note in crontab_notes(result))
