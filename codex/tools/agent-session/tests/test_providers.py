import json
from pathlib import Path
import shlex
import subprocess
import sys

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
    assert provider.launch_spec(context, prepared)["env"] == prepared["env"]


def test_claude_observation_preserves_missing_background(claude):
    provider, _, context, meta, _ = claude
    assert provider.observe({"session_id": IDENTITY}, context, meta)["terminal"] is True
    del meta["hook_observations"]["Stop"]["background_tasks"]
    result = provider.observe({"session_id": IDENTITY}, context, meta)
    assert result["known"] is False
    assert result["background"] is None
    assert result["terminal"] is False


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
