import argparse
import copy
import json
from pathlib import Path
import shlex
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_session.errors import SessionError
from agent_session.providers import get_provider
from agent_session.providers.claude import ClaudeProvider, parse_peers
from agent_session.providers.codex import CodexProvider
from agent_session.providers.mcp import MCPClient


IDENTITY = "add69150-b337-440d-9968-a8cb3d9ec866"


class FakeRPC:
    def __init__(self, cwd, config=None):
        self.config = config if config is not None else {"sandbox_mode": "danger-full-access"}
        self.thread = {"id": "thread-one", "cwd": str(cwd), "status": {"type": "idle"}}
        self.turns = [{"id": "turn-one", "status": "completed"}]
        self.pending = []
        self.background = []
        self.calls = []
        self.fail_background = False
        self.interrupt_finishes = True

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        pass

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "config/read":
            return {"config": copy.deepcopy(self.config)}
        if method == "thread/read":
            return {"thread": copy.deepcopy(self.thread)}
        if method == "thread/queue/delete":
            self.pending = [entry for entry in self.pending if entry["id"] != params["queuedSubmissionId"]]
            return {}
        if method == "turn/interrupt":
            if self.interrupt_finishes:
                for turn in self.turns:
                    if turn["id"] == params["turnId"]:
                        turn["status"] = "interrupted"
                self.thread["status"] = {"type": "idle"}
            return {}
        raise AssertionError(method)

    def pages(self, method, params):
        self.calls.append((method, params))
        if method == "thread/turns/list":
            return copy.deepcopy(self.turns)
        if method == "thread/queue/list":
            return copy.deepcopy(self.pending)
        if method == "thread/backgroundTerminals/list":
            if self.thread["status"]["type"] == "notLoaded":
                raise SessionError("provider_rpc_error", "Thread is not loaded", 4, {"rpc_code": -32600})
            if self.fail_background:
                raise SessionError("provider_rpc_error", "Unsupported background query", 4)
            return copy.deepcopy(self.background)
        raise AssertionError(method)


@pytest.fixture
def codex(tmp_path):
    provider = CodexProvider()
    rpc = FakeRPC(tmp_path)
    provider.rpc_factory = lambda endpoint, timeout: rpc
    context = {"cwd": str(tmp_path), "endpoint": "unix:///tmp/fake-codex.sock", "provider_executable": sys.executable}
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Register, then perform the assigned JOB.")
    prepared = {"prompt_file": str(prompt), "settings_file": None, "provider_args": [], "env": {}, "unset_env": []}
    return provider, rpc, context, prepared


def test_factory_rejects_unknown_provider():
    assert isinstance(get_provider("codex"), CodexProvider)
    assert isinstance(get_provider("claude"), ClaudeProvider)
    with pytest.raises(SessionError) as caught:
        get_provider("other")
    assert caught.value.exit_code == 2


def test_codex_launch_uses_same_endpoint_without_adding_bypass(codex):
    provider, rpc, context, prepared = codex
    launched = provider.launch_spec(context, prepared)
    assert launched["argv"][:3] == [str(Path(sys.executable).resolve()), "--remote", context["endpoint"]]
    assert "--dangerously-bypass-approvals-and-sandbox" not in launched["argv"]
    assert "resume" not in launched["argv"]
    assert launched["session_id"] is None


@pytest.mark.parametrize("target", ["leader", "seat-0/server with spaces"])
def test_codex_remote_launch_selects_target_cwd_over_daemon_default(codex, tmp_path, target):
    provider, rpc, context, prepared = codex
    daemon_cwd = tmp_path / "daemon-default"
    daemon_cwd.mkdir()
    target_cwd = tmp_path / target
    target_cwd.mkdir(parents=True)
    rpc.thread["cwd"] = str(daemon_cwd)
    context["cwd"] = str(target_cwd)
    launched = provider.launch_spec(context, prepared)

    # The native CLI's --cd contract selects the thread root on a remote daemon.
    native = argparse.ArgumentParser(add_help=False)
    native.add_argument("--remote")
    native.add_argument("-C", "--cd", type=Path, default=daemon_cwd)
    received, _ = native.parse_known_args(launched["argv"][1:])
    assert received.cd.resolve() == target_cwd.resolve()
    assert rpc.thread["cwd"] == str(daemon_cwd)


def test_codex_rejects_effective_sandbox(codex):
    provider, rpc, context, prepared = codex
    rpc.config["sandbox_mode"] = "workspace-write"
    with pytest.raises(SessionError) as caught:
        provider.launch_spec(context, prepared)
    assert caught.value.code == "unsupported_sandbox"
    prepared["provider_args"] = ["--dangerously-bypass-approvals-and-sandbox"]
    assert "--dangerously-bypass-approvals-and-sandbox" in provider.launch_spec(context, prepared)["argv"]


@pytest.mark.parametrize("args", [["resume", "old"], ["--remote", "unix:///wrong"], ["-C", "/tmp"], ["--cd", "/tmp"], ["--settings", "file"], ["exec"]])
def test_codex_rejects_structural_args(codex, args):
    provider, _, context, prepared = codex
    prepared["provider_args"] = args
    with pytest.raises(SessionError) as caught:
        provider.launch_spec(context, prepared)
    assert caught.value.code == "invalid_provider_args"


def test_codex_env_uses_exact_keys_and_preserves_policy(codex):
    provider, rpc, context, prepared = codex
    rpc.config["shell_environment_policy"] = {"inherit": "core", "filters": {"KEPT": "exclude"}, "set": {"KEEP_VALUE": "keep"}}
    before = copy.deepcopy(rpc.config)
    prepared["env"] = {"EXAMPLE_SESSION": "worker-name"}
    prepared["unset_env"] = ["EXAMPLE_FLAG", "EXAMPLE_MODE"]
    argv = provider.launch_spec(context, prepared)["argv"]
    assert 'shell_environment_policy.set.EXAMPLE_SESSION="worker-name"' in argv
    assert 'shell_environment_policy.filters."EXAMPLE_FLAG"="exclude"' in argv
    assert 'shell_environment_policy.filters."EXAMPLE_MODE"="exclude"' in argv
    assert not any("EXAMPLE_*" in value for value in argv)
    assert rpc.config == before


@pytest.mark.parametrize("policy", [
    {"set": {"EXAMPLE_FLAG": "would-return"}},
    {"include_only": ["OTHER"]},
    {"filters": {"OTHER": "include"}},
])
def test_codex_refuses_env_policy_conflicts(codex, policy):
    provider, rpc, context, prepared = codex
    rpc.config["shell_environment_policy"] = policy
    prepared["env"] = {"EXAMPLE_SESSION": "worker-name"}
    prepared["unset_env"] = ["EXAMPLE_FLAG"]
    with pytest.raises(SessionError) as caught:
        provider.launch_spec(context, prepared)
    assert caught.value.code == "env_policy_conflict"


def test_codex_rejects_wildcard_unset(codex):
    provider, _, context, prepared = codex
    prepared["unset_env"] = ["EXAMPLE_*"]
    with pytest.raises(SessionError) as caught:
        provider.launch_spec(context, prepared)
    assert caught.value.code == "invalid_provider_input"


def test_codex_invalid_env_does_not_escape_as_python_error(codex):
    provider, _, context, prepared = codex
    for env in ({1: "value"}, {"NAME": "embedded\0nul"}):
        prepared["env"] = env
        with pytest.raises(SessionError) as caught:
            provider.launch_spec(context, prepared)
        assert caught.value.code == "invalid_provider_input"


def test_codex_prepare_context_does_not_start_an_absent_daemon(codex, monkeypatch):
    provider, _, context, _ = codex
    called = []

    def cli(argv, timeout):
        called.append(argv)
        return json.dumps({"status": "stopped"})

    monkeypatch.setattr("agent_session.providers.codex.run", cli)
    with pytest.raises(SessionError) as caught:
        provider.prepare_context(context)
    assert caught.value.code == "provider_not_running"
    assert all(argv[-1] == "version" for argv in called)


def test_codex_profile_v2_is_read_without_modifying_it(codex, tmp_path, monkeypatch):
    provider, rpc, context, prepared = codex
    rpc.config["sandbox_mode"] = "workspace-write"
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    profile = tmp_path / "existing.config.toml"
    text = 'sandbox_mode = "danger-full-access"\nmodel_reasoning_effort = "max"\n'
    profile.write_text(text)
    prepared["provider_args"] = ["--profile", "existing"]
    assert "--profile" in provider.launch_spec(context, prepared)["argv"]
    assert profile.read_text() == text
    prepared["provider_args"] = ["--profile", "missing"]
    with pytest.raises(SessionError) as caught:
        provider.launch_spec(context, prepared)
    assert caught.value.code == "invalid_provider_args"


def test_codex_binding_checks_id_and_cwd(codex):
    provider, rpc, context, _ = codex
    session = {"session_id": "thread-one", "endpoint": context["endpoint"]}
    assert provider.verify_binding(session, context, {}) == session
    rpc.thread["id"] = "different"
    with pytest.raises(SessionError) as caught:
        provider.verify_binding(session, context, {})
    assert caught.value.code == "session_mismatch"
    rpc.thread["id"] = "thread-one"
    rpc.thread["cwd"] = "/other"
    with pytest.raises(SessionError, match="working directory"):
        provider.verify_binding(session, context, {})


def test_codex_observation_does_not_hide_unknown_background(codex):
    provider, rpc, context, _ = codex
    session = {"session_id": "thread-one", "endpoint": context["endpoint"]}
    assert provider.observe(session, context)["terminal"] is True
    rpc.fail_background = True
    with pytest.raises(SessionError):
        provider.observe(session, context)


def test_codex_loaded_background_has_direct_observation(codex):
    provider, _, context, _ = codex
    session = {"session_id": "thread-one", "endpoint": context["endpoint"]}
    result = provider.observe(session, context)
    assert result["background_known"] is True
    assert result["background_source"] == "loaded"


@pytest.mark.parametrize("matching", [True, False])
def test_codex_unloaded_background_uses_only_same_run_clear_evidence(codex, matching):
    provider, rpc, context, _ = codex
    session = {"session_id": "thread-one", "endpoint": context["endpoint"]}
    context["run_id"] = "run-one"
    rpc.thread["status"] = {"type": "notLoaded"}
    meta = {"run_id": "run-one", "last_background_clear": {
        "session_id": "thread-one", "run_id": "run-one" if matching else "old-run",
        "latest_turn_id": "turn-one",
    }}
    result = provider.observe(session, context, meta)
    assert result["known"] is matching
    assert result["terminal"] is matching
    assert result["background_known"] is matching
    assert result["background"] == ([] if matching else None)
    assert not any(method == "thread/backgroundTerminals/list" for method, _ in rpc.calls)


def test_codex_unloaded_background_without_evidence_stays_unknown(codex):
    provider, rpc, context, _ = codex
    session = {"session_id": "thread-one", "endpoint": context["endpoint"]}
    context["run_id"] = "run-one"
    rpc.thread["status"] = {"type": "notLoaded"}
    result = provider.observe(session, context, {"run_id": "run-one"})
    assert result["known"] is False
    assert result["terminal"] is False
    assert result["background_known"] is False
    assert result["background"] is None


def test_codex_background_unload_race_rechecks_runtime(codex):
    provider, rpc, context, _ = codex
    session = {"session_id": "thread-one", "endpoint": context["endpoint"]}
    context["run_id"] = "run-one"
    original = rpc.pages

    def pages(method, params):
        if method == "thread/backgroundTerminals/list":
            rpc.thread["status"] = {"type": "notLoaded"}
            raise SessionError("provider_rpc_error", "Thread is not loaded", 4, {"rpc_code": -32600})
        return original(method, params)

    rpc.pages = pages
    meta = {"run_id": "run-one", "last_background_clear": {"session_id": "thread-one", "run_id": "run-one", "latest_turn_id": "turn-one"}}
    result = provider.observe(session, context, meta)
    assert result["runtime_status"] == "notLoaded"
    assert result["background_source"] == "last_loaded_clear"
    assert result["terminal"] is True


def test_codex_active_or_pending_work_invalidates_cached_clear(codex):
    provider, rpc, context, _ = codex
    session = {"session_id": "thread-one", "endpoint": context["endpoint"]}
    context["run_id"] = "run-one"
    rpc.thread["status"] = {"type": "notLoaded"}
    rpc.pending = [{"id": "new-input"}]
    meta = {"run_id": "run-one", "last_background_clear": {"session_id": "thread-one", "run_id": "run-one", "latest_turn_id": "turn-one"}}
    result = provider.observe(session, context, meta)
    assert result["known"] is False
    assert result["terminal"] is False


def test_codex_stop_passes_clear_evidence_to_final_observation(codex):
    provider, rpc, context, _ = codex
    session = {"session_id": "thread-one", "endpoint": context["endpoint"]}
    context["run_id"] = "run-one"
    rpc.thread["status"] = {"type": "notLoaded"}
    meta = {"run_id": "run-one", "last_background_clear": {"session_id": "thread-one", "run_id": "run-one", "latest_turn_id": "turn-one"}}
    result = provider.request_stop(session, context, meta)
    assert result["background_source"] == "last_loaded_clear"
    assert result["known"] is True
    assert result["terminal"] is True


def test_codex_clear_evidence_is_rejected_after_an_external_turn(codex):
    provider, rpc, context, _ = codex
    session = {"session_id": "thread-one", "endpoint": context["endpoint"]}
    context["run_id"] = "run-one"
    rpc.thread["status"] = {"type": "notLoaded"}
    rpc.turns = [{"id": "external-new-turn", "status": "completed"},
                 {"id": "turn-one", "status": "completed"}]
    meta = {"run_id": "run-one", "last_background_clear": {
        "session_id": "thread-one", "run_id": "run-one", "latest_turn_id": "turn-one",
    }}
    result = provider.observe(session, context, meta)
    assert result["known"] is False
    assert result["background_known"] is False
    assert result["terminal"] is False


def test_codex_latest_turn_uses_explicit_server_order_not_id_sort(codex):
    provider, rpc, context, _ = codex
    session = {"session_id": "thread-one", "endpoint": context["endpoint"]}
    rpc.turns = [{"id": "a-latest", "status": "completed"},
                 {"id": "z-older", "status": "completed"}]
    result = provider.observe(session, context)
    assert result["latest_turn_id"] == "a-latest"
    assert next(params for method, params in rpc.calls if method == "thread/turns/list")["sortDirection"] == "desc"


def test_codex_stop_cancels_exact_queue_and_waits_for_turn_terminal(codex):
    provider, rpc, context, _ = codex
    session = {"session_id": "thread-one", "endpoint": context["endpoint"]}
    rpc.thread["status"] = {"type": "active"}
    rpc.turns = [{"id": "active-one", "status": "inProgress"}]
    rpc.pending = [{"id": "pending-one"}, {"id": "pending-two"}]
    rpc.background = [{"processId": "background-one"}]
    observed = provider.request_stop(session, context)
    assert observed["pending"] == []
    assert observed["active_turn"] is False
    assert observed["terminal"] is False
    assert observed["background"] == [{"processId": "background-one"}]
    deletion = [params["queuedSubmissionId"] for method, params in rpc.calls if method == "thread/queue/delete"]
    assert deletion == ["pending-one", "pending-two"]
    assert not any("archive" in method or "terminate" in method for method, _ in rpc.calls)


def test_codex_interrupt_ack_is_not_termination(codex):
    provider, rpc, context, _ = codex
    session = {"session_id": "thread-one", "endpoint": context["endpoint"]}
    rpc.thread["status"] = {"type": "active"}
    rpc.turns = [{"id": "active-one", "status": "inProgress"}]
    rpc.interrupt_finishes = False
    result = provider.request_stop(session, context)
    assert result["active_turn"] is True
    assert result["terminal"] is False


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
