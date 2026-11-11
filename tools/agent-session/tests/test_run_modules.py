"""The modules that `lifecycle.Manager` assembles: launch files, a slot's windows, and the handoff file.

Each case calls a module function directly with plain arguments and checks an observable result, so a
function that came to need `Manager` fails here. The full start/stop/restart flows are in test_lifecycle.py.
"""
import os
import shlex
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_session import handoff, launch_artifacts, windows
from agent_session.errors import SessionError
from fake_tmux import FakeTmux

JOB = {"job_id": "TOOL-001", "title": "Example", "path": "/cr/TOOL-001.md", "mode": "write",
       "branch": "cr/TOOL-001", "base": {"base_hash": "a" * 40}}


def project(tmp_path, provider="codex", base=None):
    return SimpleNamespace(provider=provider, project_id="fx", base=base or tmp_path, runtime_path=tmp_path / "agent",
                           args_for=lambda role: ["--" + role])


def context(**values):
    return {"python": "/usr/bin/python3", "library_path": "/lib", "run_id": "r" * 32, "config_path": "/cfg.json",
            "socket_path": "/tmp/s", "endpoint": "unix:///e", "cwd": "/seat/sub", "seat_root": "/seat",
            "seat": 0, "target": "seat-0", "job": JOB, "base": "/base", **values}


# launch_artifacts

def test_a_worker_prompt_names_the_cr_and_the_registration_for_codex_only(tmp_path):
    codex = launch_artifacts.prompt_text(project(tmp_path), context())
    claude = launch_artifacts.prompt_text(project(tmp_path, "claude"), context())
    assert codex.startswith("$project-team을 사용하십시오. 현재 프로젝트의 Worker 역할입니다.\n")
    for text in (codex, claude):
        assert "배정 CR: TOOL-001 (Example)\nCR 파일: /cr/TOOL-001.md\nSeat: /seat\n" in text
        assert "Branch: cr/TOOL-001\nBase: " + "a" * 40 in text
    assert "register_current" in codex and "register_current" not in claude
    assert "SessionStart 내부 등록이 실패하면" in claude and "SessionStart" not in codex


def test_no_prompt_tells_an_instance_to_register_a_session_cron(tmp_path):
    """SESSION-015: the periodic check is the project's crontab job, so no prompt asks for CronCreate."""
    prompts = [launch_artifacts.prompt_text(project(tmp_path, provider), context(**role))
               for provider in ("claude", "codex")
               for role in ({}, {"seat": None, "target": "leader", "job": None})]
    for text in prompts:
        assert "CronCreate" not in text and "CronList" not in text and "self-check" not in text
        assert "자기 점검" not in text
    assert not hasattr(launch_artifacts, "self_check_text")


def test_a_resumed_conversation_gets_only_the_request_and_a_leader_gets_no_job_lines(tmp_path):
    assert launch_artifacts.prompt_text(project(tmp_path), context(resume=True), "RESUME") == "RESUME"
    leader = launch_artifacts.prompt_text(project(tmp_path, "claude"), context(seat=None, target="leader", job=None))
    assert "Leader 역할" in leader and "배정 CR" not in leader and "project-item ls" in leader


def test_a_prompt_over_the_limit_is_refused(tmp_path):
    with pytest.raises(SessionError) as error:
        launch_artifacts.prompt_text(project(tmp_path, "claude"), context(), "x" * launch_artifacts.PROMPT_LIMIT)
    assert error.value.code == "prompt_too_large"


def test_the_handoff_text_precedes_the_job_lines(tmp_path):
    carried = tmp_path / "handoff.md"
    carried.write_text("NEXT: continue\n", encoding="utf-8")
    text = launch_artifacts.prompt_text(project(tmp_path, "claude"), context(handoff_file=str(carried)))
    assert text.index("NEXT: continue") < text.index("배정 CR: TOOL-001")


def test_the_launch_script_cleans_the_environment_enters_the_cwd_and_marks_the_process():
    ctx = context(cwd="/seat/with space")
    script = launch_artifacts.launch_script(ctx, {"argv": ["cli", "--x", "a b"], "env": {"K": "v w"}, "unset_env": ["ZED", "ALPHA"]})
    lines = script.split("\n")
    assert lines[:2] == ["#!/bin/bash", "set -e"]
    assert lines[2] == 'for name in ${!CLAUDE_CODE_MESSAGING_@} ${!AGENT_SESSION_@}; do unset "$name"; done'
    unset = lines[3].split()
    assert unset[0] == "unset" and {"ALPHA", "ZED", "CLAUDECODE", "CODEX_THREAD_ID"} <= set(unset)
    assert unset[1:] == sorted(unset[1:])
    assert lines[4] == "cd '/seat/with space'"
    marker = shlex.split(lines[5].rsplit(" ", 1)[0])
    assert marker[:3] == ["/usr/bin/python3", "-S", "-c"] and "mark_process" in marker[3]
    assert marker[4:] == ["/lib", "r" * 32, "/cfg.json", "/tmp/s"] and lines[5].endswith(' "$$"')
    assert lines[6:] == ["export K='v w'", "exec cli --x 'a b'", ""]


def test_the_controller_script_runs_the_request_through_the_internal_entry(tmp_path):
    script = launch_artifacts.write_controller_script(tmp_path, tmp_path / "request file.json")
    assert script == tmp_path / "controller.sh"
    lines = script.read_text(encoding="utf-8").split("\n")
    assert lines[:3] == ["#!/bin/bash", "set -e", "unset CODEX_THREAD_ID CLAUDE_CODE_SESSION_ID TMUX TMUX_PANE"]
    words = shlex.split(lines[3])
    assert words[:3] == ["exec", sys.executable, "-S"] and words[3] == "-c" and "run_controller" in words[4]
    assert words[5] == str(launch_artifacts.library_path()) and words[6] == str(tmp_path / "request file.json")
    assert (launch_artifacts.library_path() / "agent_session" / "internal.py").is_file()


def test_prepare_writes_the_prompt_and_settings_and_passes_the_environment(tmp_path):
    class Provider:
        def __init__(self):
            self.trusted = []

        def trust_base(self, root):
            self.trusted.append(root)

        def registration_hooks(self, ctx):
            return {"Stop": []}

        def launch_spec(self, ctx, prepared):
            return {"argv": ["cli"], "env": prepared["env"]}

    provider = Provider()
    ctx = context(upstream="/up", upstream_bin="/up/bin", window_name="fx-seat0-TOOL-001")
    prepared, launch = launch_artifacts.prepare(project(tmp_path, "claude"), provider, ctx, None, lambda: 12.5)
    directory = tmp_path / "agent" / "runs" / ("r" * 32)
    assert ctx["timeout"] == 12.5 and provider.trusted == []
    assert (directory / "prompt.md").read_text(encoding="utf-8").startswith("$project-team")
    assert '"crossSessionInbound": "accept"' in (directory / "settings.json").read_text(encoding="utf-8")
    assert prepared["provider_args"] == ["--worker"] and prepared["provider_name"] == "fx-seat0-TOOL-001"
    env = launch["env"]
    assert (env["AGENT_SESSION_CONFIG"], env["AGENT_SESSION_SOCKET"], env["AGENT_SESSION_BASE"]) == ("/cfg.json", "/tmp/s", "/base")
    assert env["AGENT_SESSION_UPLINK"] == "/up" and env["PYTHONPATH"] == "/lib"
    assert env["PATH"].startswith("/up/bin" + os.pathsep)
    leader = context(seat=None, target="leader", job=None)
    launch_artifacts.prepare(project(tmp_path), provider, leader, None, lambda: 1.0)
    assert provider.trusted == [tmp_path]            # only the Codex Leader records the base's trust
    assert launch_artifacts.prepare(project(tmp_path), provider, context(remote_seat={"host": "h"}), None, lambda: 1/0) == ({}, {})


# handoff

def test_handoff_path_is_per_slot_and_existing_file_validates_its_input(tmp_path):
    assert handoff.path(project(tmp_path), {"target": "seat-2"}) == tmp_path / "agent" / "handoff" / "seat-2.md"
    carried = tmp_path / "carried.md"
    carried.write_text("x", encoding="utf-8")
    assert handoff.existing_file(None) is None
    assert handoff.existing_file(str(carried)) == str(carried.resolve())
    assert handoff.existing_file({"path": str(carried)}) == str(carried.resolve())
    assert handoff.existing_file({"handoff_file": str(carried), "path": "/missing"}) == str(carried.resolve())
    with pytest.raises(SessionError) as error:
        handoff.existing_file(str(tmp_path / "missing.md"))
    assert error.value.code == "handoff_missing"


def test_a_handoff_is_fresh_only_when_written_after_the_run_launched(tmp_path):
    base, meta = project(tmp_path), {"target": "seat-0", "run_id": "run1"}
    with pytest.raises(SessionError) as error:
        handoff.require(base, meta, 5)
    assert (error.value.code, error.value.exit_code) == ("handoff_required", 3)
    assert error.value.details == {"path": str(handoff.path(base, meta)), "run_id": "run1"}
    launched = launch_artifacts.run_directory(base, "run1") / "launch.sh"
    launched.parent.mkdir(parents=True)
    launched.write_text("x")
    written = handoff.path(base, meta)
    written.parent.mkdir(parents=True)
    written.write_text("old")
    os.utime(written, (1, 1))
    os.utime(launched, (2, 2))
    assert handoff.fresh(base, meta, 5) is None          # written before the launch
    os.utime(written, (3, 3))
    assert handoff.fresh(base, meta, 5) == str(written) == handoff.require(base, meta, 5)


# windows

class Tmux(FakeTmux):
    """Records the commands and answers the metadata queries that the window functions use."""

    def __init__(self, current=None, windows_=()):
        self.current, self.windows, self.commands, self.closed = current, {w["window_id"]: w for w in windows_}, [], []

    def command(self, *arguments):
        self.commands.append(arguments)

    def get_current(self, project_id, target):
        return self.current

    def managed_windows(self, project_id, target):
        return list(self.windows)

    def read_meta(self, window_id):
        return self.windows[window_id]

    def close_window(self, window_id, expected):
        self.closed.append(window_id)
        return "pane" if expected.get("person") else "window"


def test_window_names_follow_the_project_slot_and_job_and_a_retired_name_adds_the_run():
    assert windows.window_name("fx", {"seat": None}) == "fx-leader"
    assert windows.window_name("fx", {"seat": 3, "job_id": "TOOL-001"}) == "fx-seat3-TOOL-001"
    tmux = Tmux()
    windows.retire_name(tmux, "fx", {"seat": 3, "job_id": "TOOL-001", "window_id": "@7", "run_id": "0123456789abcdef"})
    assert tmux.commands == [("rename-window", "-t", "@7", "fx-seat3-TOOL-001-exited-01234567")]


def test_a_window_of_another_base_or_without_a_pane_is_kept(tmp_path):
    base = project(tmp_path)
    never = lambda meta: pytest.fail("a foreign window is not observed")
    assert windows.retained(base, {"pane_id": "%1"}, never) == "foreign_window"
    assert windows.retained(base, {"base": str(tmp_path / "other"), "pane_id": "%1"}, never) == "foreign_window"
    assert windows.retained(base, {"base": str(tmp_path)}, never) == "foreign_window"


def test_a_window_stays_while_control_is_pending_or_its_end_is_unconfirmed(tmp_path):
    base = project(tmp_path)
    own = {"base": str(tmp_path), "pane_id": "%1", "run_id": "r1"}
    assert windows.retained(base, {**own, "control_pending": True}, lambda meta: {"stopped": True}) == "control_pending"
    assert windows.retained(base, own, lambda meta: {"stopped": False}) == "termination_unconfirmed"
    assert windows.retained(base, own, lambda meta: {"stopped": True}) is None


def test_sweep_closes_ended_retired_windows_and_leaves_the_current_and_unsure_ones(tmp_path):
    base = project(tmp_path)
    ended = {"window_id": "@1", "run_id": "old", "base": str(tmp_path), "pane_id": "%1"}
    live = {"window_id": "@2", "run_id": "live", "base": str(tmp_path), "pane_id": "%2"}
    current = {"window_id": "@3", "run_id": "now", "base": str(tmp_path), "pane_id": "%3"}
    tmux = Tmux(current, [ended, live, current])
    result = windows.sweep(tmux, base, "seat-0", lambda meta: {"stopped": meta["run_id"] != "live"})
    assert result == {"closed": ["@1"], "kept": [{"window_id": "@2", "reason": "termination_unconfirmed"}]}
    assert tmux.closed == ["@1"]


def test_sweep_lists_a_window_that_kept_a_persons_pane_apart_from_the_closed_ones(tmp_path):
    shared = {"window_id": "@1", "run_id": "old", "base": str(tmp_path), "pane_id": "%1", "person": True}
    alone = {"window_id": "@2", "run_id": "older", "base": str(tmp_path), "pane_id": "%2"}
    tmux = Tmux(None, [shared, alone])
    result = windows.sweep(tmux, project(tmp_path), "seat-0", lambda meta: {"stopped": True})
    assert result == {"closed": ["@2"], "kept": [], "pane_closed": ["@1"]}


def test_sweep_leaves_the_rest_to_the_next_sweep_after_its_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(windows, "SWEEP_SECONDS", 0)
    ended = {"window_id": "@1", "run_id": "old", "base": str(tmp_path), "pane_id": "%1"}
    tmux = Tmux(None, [ended])
    assert windows.sweep(tmux, project(tmp_path), "seat-0", lambda meta: {"stopped": True}) == {
        "closed": [], "kept": [{"window_id": "@1", "reason": "cleanup_budget"}]}


def test_the_newest_launch_script_picks_the_window_to_reuse_after_a_release(tmp_path):
    base = project(tmp_path)
    older = {"window_id": "@1", "run_id": "older", "base": str(tmp_path), "pane_id": "%1"}
    newer = {"window_id": "@2", "run_id": "newer", "base": str(tmp_path), "pane_id": "%2"}
    for name, stamp in (("older", 10), ("newer", 20)):
        script = launch_artifacts.run_directory(base, name) / "launch.sh"
        script.parent.mkdir(parents=True)
        script.write_text("x")
        os.utime(script, (stamp, stamp))
    tmux = Tmux(None, [older, newer])
    assert windows.reusable(tmux, base, "seat-0", lambda meta: {"stopped": True}) == newer
    assert windows.reusable(Tmux(None, []), base, "seat-0", lambda meta: {"stopped": True}) is None
    assert windows.reusable(tmux, base, "seat-0", lambda meta: {"stopped": False}) is None


def test_a_failed_start_ends_its_waiting_pane_and_hides_a_secondary_failure(tmp_path):
    class Placeholder(Tmux):
        def request_placeholder_stop(self, window_id):
            self.commands.append(("stop", window_id))

    meta = {"window_id": "@5", "target": "seat-0", "seat": 0, "job_id": "TOOL-001", "run_id": "abcdefgh1234"}
    tmux = Placeholder(meta)
    answers = iter([{"stopped": False}, {"stopped": True}])
    windows.discard_placeholder(tmux, project(tmp_path), meta, lambda current: next(answers), lambda: 5)
    assert tmux.commands == [("stop", "@5"), ("rename-window", "-t", "@5", "fx-seat0-TOOL-001-exited-abcdefgh")]

    class Broken(Tmux):
        def request_placeholder_stop(self, window_id):
            raise SessionError("tmux_failed", "gone")

    windows.discard_placeholder(Broken(meta), project(tmp_path), meta, lambda current: {"stopped": True}, lambda: 5)
