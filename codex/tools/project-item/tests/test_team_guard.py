"""Team projects: who moves an in-progress CR, and the Leader review a fixed CR needs first."""
import json

import pytest

from project_item import registry
from project_item.cli import main
from project_item_testing import git, git_init

CR_TEXT = """\
# TOOL-001: a

- Opened: 2026-11-04
- Scope: demo
- Severity: S2
{extra}
## Symptom
s

## Evidence
e

## Contract
c

## Disposition
- 2026-11-04 user: approved.

## Implementation
i

## Verification
v

## Result
{result}
"""


class Team:
    """A team project 'demo' whose base is a clone of a bare origin, with one in-progress CR."""

    def __init__(self, project, tmp_path, monkeypatch):
        self.project = project
        self.monkeypatch = monkeypatch
        self.origin = tmp_path / "origin.git"
        git(tmp_path, "init", "-q", "--bare", "--initial-branch=main", str(self.origin))
        self.work = tmp_path / "work"
        git_init(self.work)
        (self.work / "a.txt").write_text("1\n")
        git(self.work, "add", ".")
        git(self.work, "commit", "-qm", "seed")
        git(self.work, "branch", "-M", "main")
        git(self.work, "remote", "add", "origin", str(self.origin))
        git(self.work, "push", "-q", "origin", "main")
        git(project["base"], "init", "-q")
        git(project["base"], "remote", "add", "origin", str(self.origin))
        config = json.loads(project["config"].read_text())
        config[str(project["base"])]["seats"] = ["../demo.seat0"]
        project["config"].write_text(json.dumps(config))
        self.path = None

    def caller(self, actor, identity="id"):
        self.monkeypatch.setattr(registry, "caller", lambda project: (actor, identity))

    def cr(self, result="", extra="", state="in-progress"):
        self.path = self.project["cr"] / state / "TOOL-001-a.md"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(CR_TEXT.format(result=result, extra=extra))
        return self.path

    def submit(self, push=True):
        """Commit on the work clone; push it to origin/main when asked. Return the hash."""
        (self.work / "a.txt").write_text(f"{git(self.work, 'rev-list', '--count', 'HEAD')}\n")
        git(self.work, "commit", "-qam", "submit")
        if push:
            git(self.work, "push", "-q", "origin", "main")
        return git(self.work, "rev-parse", "HEAD").strip()

    def run(self, capsys, *args):
        code = main([args[0], "--config", str(self.project["config"]), "--project", "demo", *args[1:]])
        out = capsys.readouterr()
        return code, out.out, out.err

    def state(self):
        return next(p.parent.name for p in self.project["cr"].glob("*/TOOL-001-a.md"))


@pytest.fixture
def team(project, tmp_path, monkeypatch):
    return Team(project, tmp_path, monkeypatch)


def test_only_current_leader_records_and_confirms_direct_answer(team, capsys):
    item_id = "D-20261104-01"
    source = team.project["decide"] / "open" / f"{item_id}.md"
    source.parent.mkdir(parents=True)
    source.write_text(f"# {item_id}: 선택?\n\n- Opened: 2026-11-04 10:00\n- Urgency: normal\n\n"
                      "## Background\nb\n\n## Options\n| 선택지 | 내용 | 결과 |\n| --- | --- | --- |\n"
                      "## Recommendation\nA\n\n## Evidence\ne\n")
    team.caller("seat-0")
    code, _, err = team.run(capsys, "answer", item_id, "--text", "A")
    assert code == 2 and "role_denied" in err and source.exists()
    team.caller("leader")
    assert team.run(capsys, "answer", item_id, "--text", "A")[0] == 0
    team.caller("seat-0")
    code, _, err = team.run(capsys, "move", item_id, "done", "--outcome", "decided A", "--by", "user")
    assert code == 2 and "role_denied" in err
    team.caller("leader")
    assert team.run(capsys, "move", item_id, "done", "--outcome", "decided A", "--by", "Leader")[0] == 0


@pytest.mark.parametrize("actor", ["seat-0", "unmanaged-agent"])
@pytest.mark.parametrize("args", [("done", "--outcome", "fixed", "--by", "user", "--note", "n"),
                                  ("done", "--outcome", "waived", "--by", "user", "--note", "n"),
                                  ("todo",), ("open", "--by", "user", "--note", "n"),
                                  ("deferred", "--outcome", "moved p X-001", "--by", "user", "--note", "n")])
def test_worker_and_other_agents_cannot_move_an_in_progress_cr(team, capsys, actor, args):
    path = team.cr(result="- 제출 commit: " + "a" * 40)
    before = path.read_text()
    team.caller(actor)
    code, _, err = team.run(capsys, "move", "TOOL-001", *args)
    assert code == 2 and "role_denied" in err
    assert path.read_text() == before and team.state() == "in-progress"


@pytest.mark.parametrize("actor", ["leader", "operator"])
def test_leader_and_operator_move_an_in_progress_cr_back_to_todo(team, capsys, actor):
    team.cr()
    team.caller(actor)
    code, _, err = team.run(capsys, "move", "TOOL-001", "todo")
    assert code == 0, err
    assert team.state() == "todo"


def test_by_leader_needs_the_current_leader(team, capsys):
    path = team.cr(state="todo")
    before = path.read_text()
    for actor in ("operator", "seat-0", "unmanaged-agent"):
        team.caller(actor)
        code, _, err = team.run(capsys, "move", "TOOL-001", "open", "--by", "Leader", "--note", "n")
        assert code == 2 and "role_denied" in err and path.read_text() == before
    team.caller("leader")
    code, _, err = team.run(capsys, "move", "TOOL-001", "open", "--by", "Leader", "--note", "n")
    assert code == 0, err and team.state() == "open"


def test_operator_names_itself_to_move_a_todo_cr(team, capsys):
    team.cr(state="todo")
    team.caller("operator")
    code, _, err = team.run(capsys, "move", "TOOL-001", "deferred", "--outcome", "moved p X-001",
                            "--by", "user", "--note", "n")
    assert code == 0, err and team.state() == "deferred"


def finish(team, capsys, who="leader"):
    team.caller(who)
    return team.run(capsys, "move", "TOOL-001", "done", "--outcome", "fixed", "--by", "Leader", "--note", "ok")


def test_fixed_needs_the_submission_row(team, capsys):
    team.cr(result="검증만 있습니다.")
    team.caller("leader")
    code, _, err = team.run(capsys, "accept", "TOOL-001", "--commit", "a" * 40)
    assert code == 0, err
    code, _, err = finish(team, capsys)
    assert code == 2 and "review_missing" in err and "제출 commit" in err
    assert team.state() == "in-progress"


def test_fixed_needs_the_leader_acceptance_of_the_last_submission(team, capsys):
    first, second = team.submit(), team.submit()
    team.cr(result=f"- 제출 commit: {first}\n\n- 제출 commit: {second}")
    team.caller("leader")
    team.run(capsys, "accept", "TOOL-001", "--commit", first)         # the first submission is not the last
    code, _, err = finish(team, capsys)
    assert code == 2 and "review_missing" in err and "acceptance" in err
    assert team.state() == "in-progress"


def test_fixed_needs_the_accepted_commit_on_origin_main(team, capsys):
    submitted = team.submit(push=False)
    team.cr(result=f"- 제출 commit: {submitted}")
    team.caller("leader")
    assert team.run(capsys, "accept", "TOOL-001", "--commit", submitted)[0] == 0
    code, _, err = finish(team, capsys)
    assert code == 2 and "review_missing" in err and "not on origin/main" in err
    assert team.state() == "in-progress"


def test_a_reviewed_and_integrated_submission_reaches_done(team, capsys):
    submitted = team.submit()
    path = team.cr(result=f"- 제출 commit: `{submitted}`\n- 검증: pytest")
    team.caller("leader")
    code, out, err = team.run(capsys, "accept", "TOOL-001", "--commit", submitted, "--note", "검증을 확인했습니다.")
    assert code == 0, err
    assert f"Leader: 제출 {submitted}를 인수합니다. 검증을 확인했습니다." in path.read_text()
    code, _, err = finish(team, capsys)
    assert code == 0, err
    assert team.state() == "done"


def test_the_operator_moving_a_fixed_cr_needs_the_review_too(team, capsys):
    submitted = team.submit()
    team.cr(result=f"- 제출 commit: {submitted}")
    team.caller("operator")
    code, _, err = team.run(capsys, "move", "TOOL-001", "done", "--outcome", "fixed", "--by", "user", "--note", "n")
    assert code == 2 and "review_missing" in err


def test_read_only_waived_and_todo_moves_skip_the_review(team, capsys):
    team.caller("leader")
    for extra, args in (("- Mode: read-only\n", ("done", "--outcome", "fixed", "--by", "Leader", "--note", "n")),
                        ("", ("done", "--outcome", "waived", "--by", "Leader", "--note", "n")),
                        ("", ("todo",))):
        team.cr(extra=extra)
        code, _, err = team.run(capsys, "move", "TOOL-001", *args)
        assert code == 0, err
        next(team.project["cr"].glob("*/TOOL-001-a.md")).unlink()


def test_accept_is_for_the_current_leader_of_a_team_project(team, capsys):
    path = team.cr()
    before = path.read_text()
    for actor in ("operator", "seat-0", "unmanaged-agent"):
        team.caller(actor)
        code, _, err = team.run(capsys, "accept", "TOOL-001", "--commit", "a" * 40)
        assert code == 2 and "role_denied" in err and path.read_text() == before
    team.caller("leader")
    code, _, err = team.run(capsys, "accept", "TOOL-001", "--commit", "abc1234")
    assert code == 2 and "commit_invalid" in err and path.read_text() == before


def test_a_project_without_a_team_moves_and_accepts_as_before(project, capsys, monkeypatch):
    monkeypatch.setattr(registry, "caller", lambda p: pytest.fail("a project without seats has no caller rule"))
    path = project["cr"] / "in-progress" / "TOOL-001-a.md"
    path.parent.mkdir(parents=True)
    path.write_text(CR_TEXT.format(result="검증만 있습니다.", extra=""))
    config = ["--config", str(project["config"]), "--project", "demo"]
    assert main(["move", *config, "TOOL-001", "done", "--outcome", "fixed", "--by", "Leader", "--note", "n"]) == 0
    code = main(["accept", *config, "TOOL-001", "--commit", "a" * 40])
    assert code == 2 and "not_team_project" in capsys.readouterr().err
