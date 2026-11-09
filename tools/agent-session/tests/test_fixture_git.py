"""Each test's Git repositories are a private copy of the shared template."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from agent_session_fixture import Environment, git, shared_template


@pytest.fixture
def git_template(tmp_path_factory):
    return shared_template(tmp_path_factory)


def copies(git_template, tmp_path):
    envs = []
    for name in ("first", "second"):
        directory = tmp_path / name
        directory.mkdir()
        env = Environment(directory)
        env.initial_hash = git_template.copy_to(env)
        envs.append(env)
    return envs


def heads(env):
    return {"remote": git(env.remote, "rev-parse", "refs/heads/main"),
            "seed": git(env.seed, "rev-parse", "HEAD"),
            "base": git(env.base, "rev-parse", "HEAD"),
            "seats": [git(seat, "rev-parse", "HEAD") for seat in env.seats]}


def test_a_copy_points_every_clone_at_its_own_remote(git_template, tmp_path):
    first, second = copies(git_template, tmp_path)
    for env in (first, second):
        for clone in (env.seed, env.base, *env.seats):
            assert git(clone, "remote", "get-url", "origin") == str(env.remote)
        assert heads(env) == {"remote": env.initial_hash, "seed": env.initial_hash,
                              "base": env.initial_hash, "seats": [env.initial_hash] * 2}
        assert env.initial_hash == git_template.initial_hash
    assert first.remote != second.remote != git_template.layout.remote


def test_changing_one_copy_leaves_the_other_copy_and_the_template_unchanged(git_template, tmp_path):
    first, second = copies(git_template, tmp_path)
    template_before = heads(git_template.layout)
    second_before = heads(second)

    advanced = first.advance_remote()
    (first.seats[0] / "seat.txt").write_text("seat change\n")
    git(first.seats[0], "checkout", "-b", "cr/ONE")
    git(first.seats[0], "add", "seat.txt")
    git(first.seats[0], "commit", "-m", "Change the first copy's seat")
    first.publish(first.seats[0])
    git(first.base, "fetch", "origin")

    assert heads(first)["remote"] == advanced != first.initial_hash
    assert heads(second) == second_before
    assert heads(git_template.layout) == template_before
    assert git(second.remote, "for-each-ref", "--format=%(refname)") == "refs/heads/main"
    assert git(git_template.layout.remote, "for-each-ref", "--format=%(refname)") == "refs/heads/main"
    assert not (second.seed / "upstream.txt").exists()
    assert not (git_template.layout.seed / "upstream.txt").exists()
    assert git(git_template.layout.seats[0], "status", "--porcelain") == ""
    assert git(second.seats[0], "status", "--porcelain") == ""
