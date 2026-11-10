import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tomllib

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_session.errors import SessionError
from agent_session.providers import get_provider
from agent_session.providers.claude import ClaudeProvider, parse_peers
from agent_session.providers.codex import CodexProvider
from agent_session.providers.mcp import MCPClient


IDENTITY = "add69150-b337-440d-9968-a8cb3d9ec866"


def test_factory_rejects_unknown_provider():
    assert isinstance(get_provider("codex"), CodexProvider)
    assert isinstance(get_provider("claude"), ClaudeProvider)
    with pytest.raises(SessionError) as caught:
        get_provider("other")
    assert caught.value.exit_code == 2


def listing(status="idle", name="worker", ref="6d267e", pane="%24"):
    return {"listing": f"Peer sessions (1):\n  {name} [{ref}]  ·  interactive  ·  {status}  ·  tmux project:@12.{pane}  ·  started 1h ago",
            "sections": [{"kind": "sessions", "rows": [{"name": name, "ref": ref, "type": "interactive", "status": status}]}]}


class FakeMCP:
    def __init__(self):
        self.listing = listing()
        self.delivery = {"success": True}
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        pass

    def tool(self, name, arguments):
        if name == "ListAgents":
            return self.listing
        assert name == "SendMessage"
        self.sent.append(arguments)
        return self.delivery


@pytest.fixture
def claude(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "home"))
    provider = ClaudeProvider()
    fake = FakeMCP()
    provider.mcp_factory = lambda argv, timeout: fake
    managed = tmp_path / "managed.json"
    managed.write_text("{}")
    context = {"provider_executable": sys.executable, "project_id": "project", "cwd": str(tmp_path),
               "seat_root": str(tmp_path), "session_id": IDENTITY, "expected_session_id": IDENTITY,
               "managed_settings_file": str(managed)}
    meta = {"run_id": "run-one", "pane_id": "%24", "window_id": "@12", "session_name": "project", "session_id": IDENTITY,
            "hook_observations": {"Stop": {"session_id": IDENTITY, "background_tasks": [], "session_crons": []}}}
    context["meta"] = meta
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Use the assigned JOB.")
    system = tmp_path / "system.md"
    system.write_text("Preserve the project role instructions.")
    settings = tmp_path / "settings.json"
    data = {"crossSessionInbound": "accept", "hooks": {event: [{"hooks": [{"type": "command", "command": "python hook"}]}] for event in ("SessionStart", "Stop", "StopFailure", "SessionEnd")}}
    settings.write_text(json.dumps(data))
    prepared = {"prompt_file": str(prompt), "settings_file": str(settings), "system_prompt_file": str(system),
                "provider_name": "worker", "provider_args": [], "env": {}, "unset_env": []}
    return provider, fake, context, meta, prepared


class CountingMCP(FakeMCP):
    """A factory's clients: one FakeMCP per start, so that the starts and the closes can be counted."""

    def __init__(self, failures=()):
        super().__init__()
        self.started, self.closed, self.calls = 0, 0, 0
        self.failures = list(failures)               # error codes that the next ListAgents calls raise, in order

    def __call__(self, argv, timeout):
        self.started += 1
        return self

    def __exit__(self, *unused):
        self.closed += 1

    def tool(self, name, arguments):
        self.calls += 1
        if self.failures:
            code = self.failures.pop(0)
            if code:
                raise SessionError(code, "fixture failure", 4)
        return super().tool(name, arguments)


def test_observations_in_a_reusing_block_share_one_mcp_server_however_many_there_are(claude):
    provider, fake, context, meta, _ = claude
    counting = CountingMCP()
    provider.mcp_factory = counting
    session = {"session_id": IDENTITY}
    provider.observe(session, context, meta)
    assert (counting.started, counting.closed) == (1, 1)                 # outside the block each observe has its own
    with provider.reusing_client(30):
        for _ in range(12):
            assert provider.observe(session, context, meta)["listed"] is True
        assert (counting.started, counting.closed) == (2, 1)
    assert (counting.started, counting.closed, counting.calls) == (2, 2, 13)


def test_binding_checks_inside_a_reusing_block_share_one_mcp_server(claude):
    """SESSION-013. The retries of a registration's binding check start `claude mcp serve` once, not once each."""
    provider, _, context, meta, _ = claude
    counting = CountingMCP()
    provider.mcp_factory = counting
    session = {"session_id": IDENTITY}
    counting.listing = listing(pane="%99")                                 # this pane is not listed yet: retryable
    with provider.reusing_client(30):
        for _ in range(3):
            with pytest.raises(SessionError) as caught:
                provider.verify_binding(session, context, meta)
            assert caught.value.details["retryable"] is True
        counting.listing = listing()
        assert provider.verify_binding(session, context, meta)["session_id"] == IDENTITY
        assert (counting.started, counting.closed, counting.calls) == (1, 0, 4)
    assert (counting.started, counting.closed) == (1, 1)
    provider.verify_binding(session, context, meta)                         # outside a block it has its own server
    assert (counting.started, counting.closed) == (2, 2)


def test_a_shared_server_that_ended_during_the_binding_retries_is_replaced_once(claude):
    provider, _, context, meta, _ = claude
    counting = CountingMCP(failures=[None, "provider_connection_closed"])
    provider.mcp_factory = counting
    with provider.reusing_client(30):
        provider.verify_binding({"session_id": IDENTITY}, context, meta)
        assert provider.verify_binding({"session_id": IDENTITY}, context, meta)["session_id"] == IDENTITY
        assert (counting.started, counting.closed) == (2, 1)
    assert (counting.started, counting.closed) == (2, 2)


def test_a_reusing_block_inside_another_adds_no_server_and_an_unused_one_starts_none(claude):
    provider, _, context, meta, _ = claude
    counting = CountingMCP()
    provider.mcp_factory = counting
    with provider.reusing_client(30):
        with provider.reusing_client(30):
            provider.observe({"session_id": IDENTITY}, context, meta)
        provider.observe({"session_id": IDENTITY}, context, meta)
        assert counting.closed == 0
    with provider.reusing_client(30):
        pass
    assert (counting.started, counting.closed) == (1, 1)


def test_a_shared_server_that_ended_between_two_calls_is_replaced_once(claude):
    provider, _, context, meta, _ = claude
    counting = CountingMCP(failures=[None, "provider_connection_closed"])
    provider.mcp_factory = counting
    with provider.reusing_client(30):
        provider.observe({"session_id": IDENTITY}, context, meta)
        assert provider.observe({"session_id": IDENTITY}, context, meta)["listed"] is True
        assert (counting.started, counting.closed) == (2, 1)             # the dead one was closed, a new one asked
    assert (counting.started, counting.closed) == (2, 2)


def test_a_fresh_server_that_fails_is_not_retried_and_the_next_call_starts_another(claude):
    provider, _, context, meta, _ = claude
    counting = CountingMCP(failures=["provider_connection_closed", "provider_timeout"])
    provider.mcp_factory = counting
    with provider.reusing_client(30):
        for code in ("provider_connection_closed", "provider_timeout"):
            with pytest.raises(SessionError) as caught:
                provider.observe({"session_id": IDENTITY}, context, meta)
            assert caught.value.code == code
        assert (counting.started, counting.closed) == (2, 2)
        assert provider.observe({"session_id": IDENTITY}, context, meta)["listed"] is True
    assert (counting.started, counting.closed) == (3, 3)


def test_a_shared_server_stays_after_an_answer_about_the_session(claude):
    provider, fake, context, meta, _ = claude
    import os
    from agent_session.process import birth

    counting = CountingMCP()
    provider.mcp_factory = counting
    meta.update(cli_pid=os.getpid(), cli_birth=birth(os.getpid()), pane_dead=False)     # a live CLI: not listed is an error
    with provider.reusing_client(30):
        counting.listing = listing(pane="%99")                             # this pane is not listed: an answer, not a failure
        with pytest.raises(SessionError) as caught:
            provider.observe({"session_id": IDENTITY}, context, meta)
        assert caught.value.code == "session_not_bound"
        counting.listing = listing()
        assert provider.observe({"session_id": IDENTITY}, context, meta)["listed"] is True
        assert counting.started == 1


def test_the_end_of_a_shared_server_is_not_hidden_by_the_block_ending_with_an_error(claude):
    provider, _, context, meta, _ = claude
    counting = CountingMCP()
    provider.mcp_factory = counting
    with pytest.raises(RuntimeError):
        with provider.reusing_client(30):
            provider.observe({"session_id": IDENTITY}, context, meta)
            raise RuntimeError("the wait loop failed")
    assert (counting.started, counting.closed) == (1, 1) and provider._reused is None


def test_mcp_close_does_not_wait_a_second_for_a_server_that_ignores_the_end_of_its_input(tmp_path):
    # Claude's `mcp serve` keeps running when its stdin closes; only SIGTERM ends it.
    server = tmp_path / "server.py"
    server.write_text(
        "import json, signal, sys, time\n"
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    if 'id' not in request: continue\n"
        "    result = {'tools': [{'name': 'ListAgents'}, {'name': 'SendMessage'}]} if request['method'] == 'tools/list' else {}\n"
        "    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)\n"
        "while True: time.sleep(60)\n")
    client = MCPClient([sys.executable, "-u", str(server)], 30)
    with client:
        process = client.process
    assert process.poll() is not None and MCPClient.EXIT_GRACE < 1


def test_parse_peers_reads_a_long_listing_by_row_and_keeps_the_rule_for_odd_names():
    rows, lines = [], []
    for n in range(300):
        rows.append({"name": f"p{n // 16:02}-seat-{n % 16}", "ref": f"{n:06x}", "status": "idle"})
        lines.append(f"  p{n // 16:02}-seat-{n % 16} [{n:06x}]  ·  interactive  ·  idle  ·  tmux project:@{n}.%{n}  ·  started 1h ago")
    # A name that holds "] " is found as before, and a pane that is not in tmux is left out.
    rows.append({"name": "odd] name", "ref": "abc123", "status": "idle"})
    lines.append("  odd] name [abc123]  ·  interactive  ·  idle  ·  tmux project:@999.%999  ·  started 1h ago")
    rows.append({"name": "plain", "ref": "ffffff", "status": "idle"})
    lines.append("  plain [ffffff]  ·  interactive  ·  idle  ·  started 1h ago")
    peers = parse_peers({"listing": "Peer sessions:\n" + "\n".join(lines), "sections": [{"kind": "sessions", "rows": rows}]})
    assert len(peers) == 301
    assert peers[0]["pane_id"] == "%0" and peers[299]["window_id"] == "@299" and peers[299]["message_to"] == "p18-seat-11 [00012b]"
    assert peers[300]["message_to"] == "odd] name [abc123]" and peers[300]["pane_id"] == "%999"
    with pytest.raises(SessionError) as caught:                          # a line twice: the listing does not agree
        parse_peers({"listing": lines[0] + "\n" + lines[0], "sections": [{"kind": "sessions", "rows": [rows[0]]}]})
    assert caught.value.code == "provider_protocol_error"
    with pytest.raises(SessionError) as caught:                          # a row without its line
        parse_peers({"listing": lines[1], "sections": [{"kind": "sessions", "rows": [rows[0]]}]})
    assert caught.value.code == "provider_protocol_error"


def test_claude_native_ref_is_not_a_uuid_prefix(claude):
    provider, _, context, meta, _ = claude
    result = provider.verify_binding({"session_id": IDENTITY, "message_to": "old [123456]"}, context, meta)
    assert result == {"session_id": IDENTITY, "message_to": "worker [6d267e]"}
    assert not IDENTITY.startswith("6d267e")


def test_claude_refuses_wrong_pane_or_uuid(claude):
    provider, fake, context, meta, _ = claude
    fake.listing = listing(pane="%99")
    with pytest.raises(SessionError) as caught:
        provider.verify_binding({"session_id": IDENTITY}, context, meta)
    assert caught.value.code == "session_not_bound"
    with pytest.raises(SessionError) as caught:
        provider.verify_binding({"session_id": "wrong"}, context, meta)
    assert caught.value.code == "session_mismatch"


def test_claude_does_not_bind_without_a_launch_uuid(claude):
    provider, _, context, meta, _ = claude
    context.pop("expected_session_id")
    meta.pop("session_id")
    with pytest.raises(SessionError) as caught:
        provider.verify_binding({"session_id": IDENTITY}, context, meta)
    assert caught.value.code == "session_not_bound"


def test_claude_unsupported_listing_cannot_adopt_a_name():
    result = listing()
    result["listing"] = "worker [6d267e] interactive idle cwd /project"
    assert parse_peers(result) == []
    result["sections"][0]["rows"][0]["ref"] = "changed"
    with pytest.raises(SessionError):
        parse_peers(result)


def listing_with_unrelated_blank_row(blank):
    result = listing()
    other = {"name": "other", "ref": "aaaaaa", "type": "interactive", "status": "idle", **blank}
    result["listing"] += "\n  other [aaaaaa]  ·  interactive  ·  starting  ·  tmux project:@13.%30  ·  started 1s ago"
    result["sections"][0]["rows"].append(other)
    return result


@pytest.mark.parametrize("blank", [{"status": ""}, {"name": ""}, {"ref": ""}])
def test_claude_unrelated_blank_row_does_not_block_the_target(claude, blank):
    provider, fake, context, meta, _ = claude
    fake.listing = listing_with_unrelated_blank_row(blank)
    skipped = []
    assert [peer["name"] for peer in parse_peers(fake.listing, skipped)] == ["worker"]
    assert len(skipped) == 1
    assert provider.verify_binding({"session_id": IDENTITY}, context, meta)["message_to"] == "worker [6d267e]"
    assert provider.send({"session_id": IDENTITY}, "peer message", context)["disposition"] == "accepted"


def test_claude_blank_target_row_or_other_format_is_still_an_error(claude):
    provider, fake, context, meta, _ = claude
    fake.listing = listing(status="")
    with pytest.raises(SessionError):
        provider.verify_binding({"session_id": IDENTITY}, context, meta)
    for broken in ({"listing": None, "sections": []}, {"listing": "x", "sections": None}):
        with pytest.raises(SessionError) as caught:
            parse_peers(broken)
        assert caught.value.code == "provider_protocol_unsupported"
    result = listing()
    result["sections"][0]["rows"] = ["not a row"]
    with pytest.raises(SessionError) as caught:
        parse_peers(result)
    assert caught.value.code == "provider_protocol_error"


def test_claude_send_refreshes_address_and_never_claims_read(claude):
    provider, fake, context, _, _ = claude
    fake.delivery = {"success": True, "status": "held"}
    result = provider.send({"session_id": IDENTITY, "message_to": "old [123456]"}, "peer message", context)
    assert result["disposition"] == "held"
    assert result["accepted"] is False
    assert result["read"] is False
    assert fake.sent[0]["to"] == "worker [6d267e]"
    assert "notify_when_idle" not in fake.sent[0]


def test_claude_bound_session_can_be_renamed_without_switching_panes(claude):
    provider, fake, context, _, _ = claude
    context["provider_name"] = "worker"
    fake.listing = listing(name="renamed", ref="abcdef")
    result = provider.send({"session_id": IDENTITY, "message_to": "worker [6d267e]"}, "result", context)
    assert fake.sent[0]["to"] == "renamed [abcdef]"
    assert result["session"]["session_id"] == IDENTITY


def test_claude_waiting_status_is_not_verified_idle(claude):
    provider, fake, context, meta, _ = claude
    fake.listing = listing(status="waiting")
    result = provider.observe({"session_id": IDENTITY}, context, meta)
    assert result["idle"] is False
    assert result["terminal"] is False


def test_claude_launch_keeps_system_prompt_and_explicit_session(claude):
    provider, _, context, _, prepared = claude
    argv = provider.launch_spec(context, prepared)["argv"]
    assert argv[argv.index("--session-id") + 1] == IDENTITY
    assert argv[argv.index("--append-system-prompt-file") + 1] == prepared["system_prompt_file"]
    assert argv[argv.index("-n") + 1] == "worker"
    assert "--resume" not in argv
    assert "--dangerously-skip-permissions" not in argv


def test_claude_resume_reopens_the_recorded_conversation_without_forking_or_a_prompt(claude):
    provider, _, context, _, prepared = claude
    context["resume"] = True
    argv = provider.launch_spec(context, prepared)["argv"]
    assert argv[argv.index("--resume") + 1] == IDENTITY
    assert "--session-id" not in argv and "--fork-session" not in argv
    assert "Use the assigned JOB." not in argv                 # the resume message is sent after registration
    assert argv[argv.index("--settings") + 1] == str(Path(prepared["settings_file"]).resolve())
    assert argv[argv.index("-n") + 1] == "worker"


def test_claude_hooks_wait_for_the_source_that_matches_the_run(claude, tmp_path):
    provider, _, context, _, _ = claude
    context.update({"python": sys.executable, "library_path": str(tmp_path), "run_id": "run-one",
                    "config_path": str(tmp_path / "project.json"), "socket_path": "/tmp/tmux.sock"})
    assert provider.registration_hooks(context)["SessionStart"][0]["matcher"] == "startup"
    assert provider.registration_hooks({**context, "resume": True})["SessionStart"][0]["matcher"] == "resume"


def test_claude_requires_tmpdir_in_final_settings(claude):
    provider, _, context, _, prepared = claude
    prepared["env"] = {"CLAUDE_CODE_TMPDIR": "/project/scratch"}
    with pytest.raises(SessionError) as caught:
        provider.launch_spec(context, prepared)
    assert caught.value.code == "env_policy_conflict"
    path = Path(prepared["settings_file"])
    data = json.loads(path.read_text())
    data["env"] = dict(prepared["env"])
    path.write_text(json.dumps(data))
    assert provider.launch_spec(context, prepared)["env"] == {**prepared["env"], "CLAUDE_DISABLE_ADOPT": "1"}


def test_claude_observation_preserves_missing_background(claude):
    provider, _, context, meta, _ = claude
    assert provider.observe({"session_id": IDENTITY}, context, meta)["terminal"] is True
    del meta["hook_observations"]["Stop"]["background_tasks"]
    result = provider.observe({"session_id": IDENTITY}, context, meta)
    assert result["known"] is False
    assert result["background"] is None
    assert result["terminal"] is False


CRON = {"id": "585de34f", "cron": "13,43 * * * *", "recurring": True}


def with_launch_script(meta, tmp_path, *lines):
    script = tmp_path / "launch.sh"
    script.write_text("\n".join(["#!/bin/bash", "set -e", *lines, "exec claude"]) + "\n", encoding="utf-8")
    meta["launch_file"] = str(script)


def test_claude_session_cron_does_not_keep_a_run_without_the_exit_handoff_from_resting(claude, tmp_path):
    provider, _, context, meta, _ = claude
    with_launch_script(meta, tmp_path, "export CLAUDE_DISABLE_ADOPT=1")
    meta["hook_observations"]["Stop"]["session_crons"] = [CRON]
    result = provider.observe({"session_id": IDENTITY}, context, meta)
    assert (result["known"], result["terminal"], result["background"]) == (True, True, [])
    assert result["session_crons"] == [CRON]                    # kept for diagnosis


def test_claude_session_cron_still_keeps_a_run_that_has_no_record_of_the_launch_from_resting(claude, tmp_path):
    provider, _, context, meta, _ = claude
    meta["hook_observations"]["Stop"]["session_crons"] = [CRON]
    for launch_file in (None, str(tmp_path / "missing.sh")):
        meta["launch_file"] = launch_file
        result = provider.observe({"session_id": IDENTITY}, context, meta)
        assert (result["terminal"], result["background"], result["session_crons"]) == (False, [CRON], [CRON])
    with_launch_script(meta, tmp_path, "export CLAUDE_DISABLE_ADOPT=0", "# export CLAUDE_DISABLE_ADOPT=1")
    assert provider.observe({"session_id": IDENTITY}, context, meta)["terminal"] is False


def test_claude_background_task_keeps_a_run_from_resting_with_or_without_the_exit_handoff(claude, tmp_path):
    provider, _, context, meta, _ = claude
    with_launch_script(meta, tmp_path, "export CLAUDE_DISABLE_ADOPT=1")
    task = {"id": "bz1mzn8iq", "type": "shell"}
    meta["hook_observations"]["Stop"].update(background_tasks=[task], session_crons=[CRON])
    result = provider.observe({"session_id": IDENTITY}, context, meta)
    assert (result["terminal"], result["background"], result["session_crons"]) == (False, [task], [CRON])


def test_claude_cli_that_ended_with_only_a_session_cron_in_its_last_report_is_terminal(claude, tmp_path):
    # The stuck stop: SIGTERM ended the CLI after an idle Stop report that listed the self-check cron.
    import subprocess

    provider, fake, context, meta, _ = claude
    ended = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    fake.listing = listing(pane="%99")
    with_launch_script(meta, tmp_path, "export CLAUDE_DISABLE_ADOPT=1")
    meta.update(cli_pid=int(ended.stdout), cli_birth="ended", pane_dead=True)
    meta["hook_observations"]["Stop"]["session_crons"] = [CRON]
    meta["hook_observations"]["SessionEnd"] = {"session_id": IDENTITY, "reason": "other"}
    result = provider.observe({"session_id": IDENTITY}, context, meta)
    assert (result["known"], result["terminal"], result["background"], result["session_crons"]) == (True, True, [], [CRON])


def test_claude_cli_that_ended_during_the_listing_is_observed_from_its_hooks(claude):
    # The stop loop read a live pane, then /exit ended the CLI before ListAgents ran.
    import subprocess

    provider, fake, context, meta, _ = claude
    ended = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    fake.listing = listing(pane="%99")
    meta.update(cli_pid=int(ended.stdout), cli_birth="ended", pane_dead=False)
    meta["hook_observations"]["SessionEnd"] = {"session_id": IDENTITY, "reason": "prompt_input_exit"}
    result = provider.observe({"session_id": IDENTITY}, context, meta)
    assert (result["known"], result["terminal"], result["background"]) == (True, True, [])


def test_claude_live_cli_missing_from_the_listing_is_not_bound(claude):
    import os
    from agent_session.process import birth

    provider, fake, context, meta, _ = claude
    fake.listing = listing(pane="%99")
    meta.update(cli_pid=os.getpid(), cli_birth=birth(os.getpid()), pane_dead=False)
    with pytest.raises(SessionError) as error:
        provider.observe({"session_id": IDENTITY}, context, meta)
    assert error.value.code == "session_not_bound"


def test_claude_managed_deny_and_sandbox_are_not_overridden(claude):
    provider, _, context, _, prepared = claude
    path = Path(context["managed_settings_file"])
    path.write_text(json.dumps({"permissions": {"deny": ["SendMessage"]}}))
    with pytest.raises(SessionError) as caught:
        provider.launch_spec(context, prepared)
    assert caught.value.code == "needs_user_action"
    path.write_text(json.dumps({"sandbox": {"enabled": True}}))
    with pytest.raises(SessionError) as caught:
        provider.launch_spec(context, prepared)
    assert caught.value.code == "unsupported_sandbox"


def test_claude_hook_command_is_fixed_python_function(claude, tmp_path):
    provider, _, context, _, _ = claude
    context.update({"python": sys.executable, "library_path": str(tmp_path), "run_id": "run-one", "config_path": str(tmp_path / "project.json"), "socket_path": "/tmp/tmux.sock"})
    hooks = provider.registration_hooks(context)
    assert set(hooks) == {"SessionStart", "Stop", "StopFailure", "SessionEnd"}
    argv = shlex.split(hooks["SessionStart"][0]["hooks"][0]["command"])
    assert argv[0] == sys.executable
    assert argv[1] == "-c"
    assert "register_from_hook" in argv[2]
    assert argv[-1] == IDENTITY
    assert hooks["SessionStart"][0]["matcher"] == "startup"


def test_mcp_process_scrubs_parent_markers_and_uses_current_schema(tmp_path, monkeypatch):
    source = tmp_path / "mcp_fixture.py"
    source.write_text('''import json,os,sys
for line in sys.stdin:
 request=json.loads(line)
 if 'id' not in request:continue
 method=request['method']
 if method=='initialize':result={}
 elif method=='tools/list':result={'tools':[{'name':'ListAgents','inputSchema':{'type':'object','properties':{},'additionalProperties':False}},{'name':'SendMessage','inputSchema':{'type':'object','properties':{'to':{'type':'string'},'message':{'type':'string'}},'required':['to','message'],'additionalProperties':False}}]}
 elif method=='tools/call':
  result={'content':[{'type':'text','text':json.dumps({'nested':any(k in os.environ for k in ['CLAUDECODE','CLAUDE_CODE_SESSION_ID','CODEX_THREAD_ID','CLAUDE_CODE_MESSAGING_SOCKET']), 'auth_kept':'ANTHROPIC_API_KEY'in os.environ})}]}
 else:raise RuntimeError(method)
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
''')
    for name in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CLAUDE_CODE_MESSAGING_SOCKET"):
        monkeypatch.setenv(name, "parent-value")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-only-not-live")
    with MCPClient([sys.executable, "-u", str(source)], 3) as client:
        assert client.tool("ListAgents", {}) == {"nested": False, "auth_kept": True}
        with pytest.raises(SessionError) as caught:
            client.tool("SendMessage", {"to": "peer", "message": "text", "unexpected": "field"})
        assert caught.value.code == "provider_protocol_unsupported"


def test_send_reports_provider_timeout_when_the_silent_mcp_is_not_reaped(claude, tmp_path, monkeypatch):
    # The MCP stand-in never answers, and even after SIGTERM and SIGKILL the wait for it times out
    # (a host stuck in I/O wait). The caller must still see the stage that failed.
    silent = tmp_path / "claude"
    silent.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(60)\n")
    silent.chmod(0o755)
    spawned = []
    original_popen = subprocess.Popen

    class Unreaped(original_popen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            spawned.append(self)

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(self.args, timeout)

    monkeypatch.setattr(subprocess, "Popen", Unreaped)
    provider, _, context, _, _ = claude
    provider.mcp_factory = MCPClient
    context["provider_executable"] = str(silent)
    try:
        with pytest.raises(SessionError) as caught:
            provider.send({"session_id": IDENTITY}, "peer message", context, timeout=0.5)
    finally:
        for process in spawned:
            original_popen.kill(process)
            original_popen.wait(process)
    assert caught.value.code == "provider_timeout"
    assert caught.value.exit_code == 4
    assert caught.value.details["unreaped_pid"] == spawned[0].pid


@pytest.mark.parametrize(("screen", "kind"), [
    ("Accessing workspace:\n\n /work/seat0\n\n❯ 1. Yes, I trust this folder\n  2. No, exit", "workspace_trust"),
    ("WARNING: Claude Code running in Bypass Permissions mode\n\n❯ 1. No, exit\n  2. Yes, I accept",
     "bypass_permissions"),
    ("Select login method:\n\n❯ 1. Claude account with subscription", "login"),
    ("❯ \n  ⏵⏵ bypass permissions on (shift+tab to cycle)", None),
])
def test_claude_startup_dialog_is_named_from_its_screen(screen, kind):
    # The dialog text is the 2.1.317 CLI's own wording.
    assert ClaudeProvider().startup_dialog(screen) == kind


def test_claude_trust_adds_one_entry_under_claude_config_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    config = tmp_path / ".claude.json"
    seat = tmp_path / "seat"
    seat.mkdir()
    config.write_text(json.dumps({"numStartups": 3, "projects": {
        str(seat): {"allowedTools": ["Bash"], "hasTrustDialogAccepted": False},
        "/other": {"hasTrustDialogAccepted": True}}}, indent=2))
    config.chmod(0o600)
    assert ClaudeProvider().trust_new_seat(seat) is True
    data = json.loads(config.read_text())
    assert data["numStartups"] == 3 and data["projects"]["/other"] == {"hasTrustDialogAccepted": True}
    assert data["projects"][str(seat)] == {"allowedTools": ["Bash"], "hasTrustDialogAccepted": True}
    assert config.stat().st_mode & 0o777 == 0o600
    assert sorted(path.name for path in tmp_path.iterdir()) == [".claude.json", "seat"]


def test_claude_trust_waits_for_a_held_lock_then_leaves_the_config(tmp_path, monkeypatch):
    from agent_session.providers.claude import trust_workspace

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    config = tmp_path / ".claude.json"
    config.write_text('{"projects": {}}')
    (tmp_path / ".claude.json.lock").mkdir()
    assert trust_workspace(tmp_path, wait=0.2) is False
    assert config.read_text() == '{"projects": {}}' and (tmp_path / ".claude.json.lock").is_dir()


def test_claude_trust_does_not_create_a_missing_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert ClaudeProvider().trust_new_seat(tmp_path) is False
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(("screen", "kind"), [
    ("Folder access\nTrust this folder?\n❯ 1. Yes, trust this folder\n  2. No, exit", "workspace_trust"),
    ("Welcome to Codex\nChoose a model\n1. Recommended", None),
    ("Codex Worker\n/fixture/project.seat0\nReady to help", None),
    ("Folder access\nProject settings loaded", None),
])
def test_codex_startup_dialog_is_named_from_its_screen(screen, kind):
    assert CodexProvider().startup_dialog(screen) == kind


@pytest.mark.parametrize("method", ["trust_new_seat", "trust_base"])
def test_codex_trust_records_only_the_workspace_and_preserves_settings(tmp_path, monkeypatch, method):
    home = tmp_path / "codex"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    config = home / "config.toml"
    original = ('model = "gpt-6"\n# keep this comment\n[projects."/other"]\n'
                'trust_level = "untrusted"\n')
    config.write_text(original)
    config.chmod(0o600)
    seat = tmp_path / "new seat"
    seat.mkdir()
    trust = getattr(CodexProvider(), method)

    assert trust(seat) is True
    updated = config.read_text()
    values = tomllib.loads(updated)
    assert values["model"] == "gpt-6"
    assert values["projects"]["/other"] == {"trust_level": "untrusted"}
    assert values["projects"][str(seat.resolve())] == {"trust_level": "trusted"}
    assert updated.startswith(original)
    assert config.stat().st_mode & 0o777 == 0o600
    assert trust(seat) is True
    assert config.read_text() == updated


@pytest.mark.parametrize("method", ["trust_new_seat", "trust_base"])
def test_codex_trust_keeps_explicit_untrusted_and_existing_workspace_settings(tmp_path, monkeypatch, method):
    home = tmp_path / "codex"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    config = home / "config.toml"
    seat = tmp_path / "seat"
    seat.mkdir()
    trust = getattr(CodexProvider(), method)
    original = f'[projects."{seat.resolve()}"]\ntrust_level = "untrusted"\nsandbox_mode = "read-only"\n'
    config.write_text(original)
    assert trust(seat) is False
    assert config.read_text() == original

    config.write_text(f'[projects."{seat.resolve()}"]\nsandbox_mode = "read-only"\n')
    assert trust(seat) is True
    assert tomllib.loads(config.read_text())["projects"][str(seat.resolve())] == {
        "sandbox_mode": "read-only", "trust_level": "trusted"}


def test_codex_base_trust_write_failure_preserves_config(tmp_path, monkeypatch):
    from agent_session.providers import codex

    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    config = tmp_path / "config.toml"
    original = 'model = "gpt-6"\n# preserve this comment\n'
    config.write_text(original)

    def refuse_replace(source, target):
        raise PermissionError("The config cannot be replaced.")

    monkeypatch.setattr(codex.os, "replace", refuse_replace)
    assert CodexProvider().trust_base(tmp_path / "base") is False
    assert config.read_text() == original
    assert sorted(path.name for path in tmp_path.iterdir()) == ["config.toml"]


def test_claude_marks_only_an_unlisted_pane_as_retryable(claude):
    provider, fake, context, meta, _ = claude
    fake.listing = listing(pane="%99")
    with pytest.raises(SessionError) as caught:
        provider.verify_binding({"session_id": IDENTITY}, context, meta)
    assert caught.value.code == "session_not_bound" and caught.value.details == {"retryable": True}
    # The pane is listed, but under another name: that is a mismatch, not a late listing.
    fake.listing = listing(name="intruder")
    context["provider_name"] = "worker"
    with pytest.raises(SessionError) as caught:
        provider.verify_binding({"session_id": IDENTITY}, context, meta)
    assert caught.value.code == "session_not_bound" and not caught.value.details
    # Two rows for the pane are ambiguous.
    twice = listing()
    twice["listing"] += "\n  twin [aaaaaa]  ·  interactive  ·  idle  ·  tmux project:@12.%24  ·  started 1s ago"
    twice["sections"][0]["rows"].append({"name": "twin", "ref": "aaaaaa", "type": "interactive", "status": "idle"})
    fake.listing = twice
    context.pop("provider_name")
    with pytest.raises(SessionError) as caught:
        provider.verify_binding({"session_id": IDENTITY}, context, meta)
    assert caught.value.code == "session_not_bound" and not caught.value.details


def test_claude_launch_disables_the_exit_handoff_to_a_background_session(claude):
    provider, _, context, _, prepared = claude
    assert provider.launch_spec(context, prepared)["env"]["CLAUDE_DISABLE_ADOPT"] == "1"


def transcript(tmp_path, session_id, *records):
    path = tmp_path / "home" / "projects" / "-some-project" / (session_id + ".jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


MOVED = {"type": "continued-in", "continuedInSessionId": "ddfda1ec-803a-420d-897c-bd8444c16abd"}


def test_a_transcript_that_ends_with_continued_in_names_the_background_session(claude, tmp_path):
    provider = claude[0]
    transcript(tmp_path, IDENTITY, {"type": "user"}, {"type": "attachment", "attachment": {"type": "session_cron_carry"}}, MOVED)
    assert provider.moved_to(IDENTITY) == MOVED["continuedInSessionId"]


@pytest.mark.parametrize("records", [
    [{"type": "user"}, {"type": "assistant"}],
    [MOVED, {"type": "user"}],                      # a conversation resumed after the handoff goes on
    [{"type": "continued-in"}],
])
def test_a_transcript_without_a_final_move_record_is_not_a_move(claude, tmp_path, records):
    transcript(tmp_path, IDENTITY, *records)
    assert claude[0].moved_to(IDENTITY) is None


def test_a_missing_or_unreadable_transcript_is_not_a_move(claude, tmp_path):
    provider = claude[0]
    assert provider.moved_to(IDENTITY) is None
    path = transcript(tmp_path, IDENTITY, {"type": "user"})
    path.write_text("{not json\n", encoding="utf-8")
    assert provider.moved_to(IDENTITY) is None
    assert provider.moved_to("../" + IDENTITY) is None


def test_the_background_host_comes_from_the_agents_listing(claude, monkeypatch):
    import agent_session.providers.claude as module

    provider = claude[0]
    rows = [{"pid": 3568208, "sessionId": MOVED["continuedInSessionId"], "kind": "background", "status": "idle"},
            {"pid": 1, "sessionId": "other", "kind": "interactive"}]
    seen = []
    monkeypatch.setattr(module, "run", lambda argv, timeout, **keywords: seen.append(argv) or json.dumps(rows))
    monkeypatch.setattr(module, "executable", lambda name, context=None: "/bin/claude")
    assert provider.background_host(MOVED["continuedInSessionId"], "/project") == {"listed": True, "pid": 3568208}
    assert seen[0][1:] == ["agents", "--json", "--cwd", "/project"]
    assert provider.background_host("absent", "/project") == {"listed": False, "pid": None}
    monkeypatch.setattr(module, "run", lambda argv, timeout, **keywords: "not json")
    with pytest.raises(SessionError):
        provider.background_host("absent", "/project")


def test_transcript_files_follow_claudes_directory_naming(tmp_path, monkeypatch):
    from agent_session.providers.claude import transcript_files

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    seat = tmp_path / "agent.seat2"
    seat.mkdir()
    folder = tmp_path / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(seat.resolve()))
    folder.mkdir(parents=True)
    (folder / f"{IDENTITY}.jsonl").write_text("{}\n")
    assert transcript_files([seat], IDENTITY) == [folder / f"{IDENTITY}.jsonl"]
    assert transcript_files([seat], "other") == [] and transcript_files([tmp_path / "elsewhere"], IDENTITY) == []
    # Without a directory every project directory is searched, in the same config directory.
    assert transcript_files(None, IDENTITY) == [folder / f"{IDENTITY}.jsonl"]
    assert transcript_files(None, "other") == [] and transcript_files(None, "../" + IDENTITY) == []
