"""Codex provider launch, configuration, binding and observation contracts."""

import argparse
import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_session.errors import SessionError
from agent_session.providers.codex import CodexProvider, _arguments
from agent_session.providers.common import deadline
from agent_session import remote


class FakeRPC:
    def __init__(self, cwd, config=None):
        self.config = config if config is not None else {"sandbox_mode": "danger-full-access"}
        self.layers = None
        self.omit_layers = False
        self.config_responses = []
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
            response = {"config": copy.deepcopy(self.config), "origins": {}}
            if params.get("includeLayers") and not self.omit_layers:
                response["layers"] = copy.deepcopy(self.layers)
            self.config_responses.append(response)
            return response
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


@pytest.mark.parametrize("method, operation", [
    ("verify_binding", "check_binding"), ("observe", "observe"), ("send", "send"),
    ("request_stop", "request_stop"), ("request_exit", "request_exit"),
])
@pytest.mark.parametrize("disconnected", [False, True])
def test_ssh_seat_control_uses_the_remote_native_run_without_local_fallback(
        codex, monkeypatch, method, operation, disconnected):
    provider, _, context, _ = codex
    session = {"session_id": "thread-one", "endpoint": context["endpoint"]}
    context.update(session_id=session["session_id"], run_id="a" * 32,
                   remote_seat={"host": "macbook-worker", "path": "/Users/swain/seat"},
                   remote_native={"session_id": session["session_id"]})
    observed = {"known": True, "terminal": True, "active_turn": False, "pending": [], "background": []}
    remote_result = ({"disposition": "accepted", "session": {**session, "endpoint": "unix:///remote/native.sock"}}
                     if method == "send" else observed)
    calls = []

    def local_rpc(*args):
        pytest.fail("an SSH seat must not access a local Codex socket")

    def run_call(meta, action, payload=None, timeout=30):
        calls.append((action, payload, timeout))
        assert meta["remote_seat"] == context["remote_seat"] and meta["run_id"] == context["run_id"]
        if disconnected:
            raise SessionError("remote_unknown", "SSH connection lost.", 4)
        return remote_result

    monkeypatch.setattr(remote, "run_call", run_call)
    provider.rpc_factory = local_rpc
    if method == "send":
        invoke = lambda: provider.send(session, "Leader feedback", context, timeout=11)
    elif method == "request_exit":
        invoke = lambda: provider.request_exit(context, object())
    else:
        invoke = lambda: getattr(provider, method)(session, context, context, timeout=11)
    if disconnected:
        with pytest.raises(SessionError) as caught:
            invoke()
        assert caught.value.code == "remote_unknown"
    else:
        result = invoke()
        if method == "verify_binding":
            assert result == session
        elif method == "send":
            assert result["disposition"] == "accepted" and result["session"] == session
        elif method != "request_exit":
            assert result == observed
    assert len(calls) == 1 and calls[0][0] == operation
    assert calls[0][1] == ({"message": "Leader feedback"} if method == "send" else None)
    assert calls[0][2] == (30 if method == "request_exit" else 11)


def config_layer(kind, config, *, profile=None, disabled_reason=None):
    name = {"type": kind}
    if kind == "user":
        name["file"] = "/fixture/config.toml" if profile is None else f"/fixture/{profile}.config.toml"
        if profile is not None:
            name["profile"] = profile
    elif kind == "project":
        name["dotCodexFolder"] = "/fixture/project/.codex"
    elif kind in ("system", "packagedDefaults", "legacyManagedConfigTomlFromFile"):
        name["file"] = f"/fixture/{kind}.toml"
    elif kind == "enterpriseManaged":
        name.update({"id": "fixture-managed", "name": "Fixture managed defaults"})
    layer = {"name": name, "version": "fixture-version", "config": config}
    if disabled_reason is not None:
        layer["disabledReason"] = disabled_reason
    return layer


@pytest.fixture
def profile_file(codex, tmp_path, monkeypatch):
    _, rpc, _, prepared = codex
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    path = tmp_path / "selected.config.toml"
    path.write_text('sandbox_mode = "danger-full-access"\n')
    rpc.layers = [config_layer("user", copy.deepcopy(rpc.config))]
    prepared["provider_args"] = ["--profile", "selected"]
    return path


def read_configuration(provider, context, prepared):
    return provider._configuration(context, _arguments(prepared["provider_args"]), deadline(30))


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


def test_codex_profile_v2_is_read_without_modifying_it(codex, profile_file):
    provider, rpc, context, prepared = codex
    rpc.config["sandbox_mode"] = "workspace-write"
    rpc.layers = [config_layer("user", {"sandbox_mode": "workspace-write"})]
    text = 'sandbox_mode = "danger-full-access"\nmodel_reasoning_effort = "max"\n'
    profile_file.write_text(text)
    assert "--profile" in provider.launch_spec(context, prepared)["argv"]
    assert profile_file.read_text() == text
    prepared["provider_args"] = ["--profile", "missing"]
    with pytest.raises(SessionError) as caught:
        provider.launch_spec(context, prepared)
    assert caught.value.code == "invalid_provider_args"


@pytest.mark.parametrize(("project_mode", "profile_mode", "allowed"), [
    ("workspace-write", "danger-full-access", False),
    ("danger-full-access", "workspace-write", True),
])
def test_codex_project_settings_take_precedence_over_selected_profile(
    codex, profile_file, project_mode, profile_mode, allowed
):
    provider, rpc, context, prepared = codex
    rpc.config["sandbox_mode"] = project_mode
    rpc.layers = [config_layer("project", {"sandbox_mode": project_mode}),
                  config_layer("user", {"sandbox_mode": "read-only"})]
    profile_file.write_text(f'sandbox_mode = "{profile_mode}"\n')
    before = (copy.deepcopy(rpc.config), copy.deepcopy(rpc.layers), profile_file.read_text())
    if allowed:
        assert "--profile" in provider.launch_spec(context, prepared)["argv"]
    else:
        with pytest.raises(SessionError) as caught:
            provider.launch_spec(context, prepared)
        assert caught.value.code == "unsupported_sandbox"
    assert (rpc.config, rpc.layers, profile_file.read_text()) == before


@pytest.mark.parametrize(("overrides", "allowed"), [
    (["-c", 'sandbox_mode="danger-full-access"'], True),
    (["--sandbox", "danger-full-access"], True),
    (["--dangerously-bypass-approvals-and-sandbox"], True),
    (["-c", 'sandbox_mode="workspace-write"'], False),
    (["--sandbox", "workspace-write"], False),
])
def test_codex_explicit_cli_sandbox_overrides_profile_and_project(codex, profile_file, overrides, allowed):
    provider, rpc, context, prepared = codex
    rpc.config["sandbox_mode"] = "workspace-write"
    rpc.layers = [config_layer("project", {"sandbox_mode": "workspace-write"}),
                  config_layer("user", {"sandbox_mode": "read-only"})]
    prepared["provider_args"] += overrides
    if allowed:
        assert "--profile" in provider.launch_spec(context, prepared)["argv"]
    else:
        with pytest.raises(SessionError) as caught:
            provider.launch_spec(context, prepared)
        assert caught.value.code == "unsupported_sandbox"


@pytest.mark.parametrize("disabled_reason", ["project is not trusted", ""])
def test_codex_disabled_project_layer_does_not_restore_its_policy(codex, profile_file, disabled_reason):
    provider, rpc, context, prepared = codex
    rpc.config = {"sandbox_mode": "workspace-write", "shell_environment_policy": {"set": {"BASE": "keep"}}}
    rpc.layers = [config_layer("project", {"sandbox_mode": "read-only",
                  "shell_environment_policy": {"set": {"DISABLED": "must-not-return"}}},
                  disabled_reason=disabled_reason),
                  config_layer("user", copy.deepcopy(rpc.config))]
    result = read_configuration(provider, context, prepared)
    assert result["sandbox_mode"] == "danger-full-access"
    assert result["shell_environment_policy"] == {"set": {"BASE": "keep"}}


def test_codex_disabled_layer_is_skipped_before_reading_its_raw_config(codex, profile_file):
    provider, rpc, context, prepared = codex
    rpc.layers.insert(0, config_layer("project", "disabled raw input", disabled_reason="untrusted"))
    assert read_configuration(provider, context, prepared)["sandbox_mode"] == "danger-full-access"


def test_codex_replacing_profile_removes_old_values_and_preserves_native_fields(codex, profile_file):
    provider, rpc, context, prepared = codex
    rpc.config = {"sandbox_mode": "danger-full-access",
                  "shell_environment_policy": {"set": {"BASE": "keep", "OLD_PROFILE": "remove"}},
                  "model": "native-model", "model_reasoning_effort": "high"}
    rpc.layers = [config_layer("user", {"sandbox_mode": "danger-full-access",
                  "shell_environment_policy": {"set": {"OLD_PROFILE": "remove"}}}, profile="old"),
                  config_layer("user", {"shell_environment_policy": {"set": {"BASE": "keep"}}})]
    profile_file.write_text('model = "selected-profile-model"\nmodel_reasoning_effort = "max"\n')
    before_config, before_layers = copy.deepcopy(rpc.config), copy.deepcopy(rpc.layers)
    result = read_configuration(provider, context, prepared)
    assert result == {"shell_environment_policy": {"set": {"BASE": "keep"}},
                      "model": "native-model", "model_reasoning_effort": "high"}
    assert rpc.config == before_config and rpc.layers == before_layers
    assert rpc.config_responses[-1] == {"config": before_config, "origins": {}, "layers": before_layers}
    assert profile_file.read_text() == 'model = "selected-profile-model"\nmodel_reasoning_effort = "max"\n'


@pytest.mark.parametrize(("lower_policy", "upper_policy", "blocked_name", "allowed_name"), [
    ({"include_only": ["SESSION007_ALLOWED"], "exclude": ["SESSION007_EXCLUDED"]},
     {"filters": {"SESSION007_NEW": "include", "SESSION007_DROP": "exclude"}},
     "SESSION007_ALLOWED", "SESSION007_NEW"),
    ({"filters": {"SESSION007_NEW": "include", "SESSION007_DROP": "exclude"}},
     {"include_only": ["SESSION007_ALLOWED"], "exclude": ["SESSION007_EXCLUDED"]},
     "SESSION007_NEW", "SESSION007_ALLOWED"),
])
def test_codex_policy_filter_family_switch_drops_lower_family(
    codex, profile_file, lower_policy, upper_policy, blocked_name, allowed_name
):
    # Native 0.166.0 replaces the other filter family when a higher layer selects one.
    provider, rpc, context, prepared = codex
    rpc.config = {"sandbox_mode": "danger-full-access", "shell_environment_policy": upper_policy}
    rpc.layers = [config_layer("project", {"shell_environment_policy": upper_policy}),
                  config_layer("project", {"shell_environment_policy": lower_policy}),
                  config_layer("user", {"sandbox_mode": "danger-full-access"})]
    before = (copy.deepcopy(rpc.config), copy.deepcopy(rpc.layers), profile_file.read_text())
    prepared["env"] = {blocked_name: "required"}
    with pytest.raises(SessionError) as caught:
        provider.launch_spec(context, prepared)
    assert caught.value.code == "env_policy_conflict"
    prepared["env"] = {allowed_name: "required"}
    assert provider.launch_spec(context, prepared)["env"] == {allowed_name: "required"}
    resolved = read_configuration(provider, context, prepared)["shell_environment_policy"]
    if "filters" in upper_policy:
        assert resolved.get("include_only") is None and resolved.get("exclude") is None
        assert resolved["filters"] == upper_policy["filters"]
    else:
        assert resolved.get("filters") is None
        assert resolved["include_only"] == ["SESSION007_ALLOWED"]
        assert resolved["exclude"] == ["SESSION007_EXCLUDED"]
    assert (rpc.config, rpc.layers, profile_file.read_text()) == before


def test_codex_legacy_include_and_exclude_survive_separate_layers(codex, profile_file):
    provider, rpc, context, prepared = codex
    rpc.config = {"sandbox_mode": "danger-full-access",
                  "shell_environment_policy": {"include_only": ["SESSION007_ALLOWED"],
                                               "exclude": ["SESSION007_EXCLUDED"]}}
    rpc.layers = [config_layer("project", {"shell_environment_policy": {"exclude": ["SESSION007_EXCLUDED"]}}),
                  config_layer("project", {"shell_environment_policy": {"include_only": ["SESSION007_ALLOWED"]}}),
                  config_layer("user", {"sandbox_mode": "danger-full-access"})]
    before = (copy.deepcopy(rpc.config), copy.deepcopy(rpc.layers), profile_file.read_text())
    resolved = read_configuration(provider, context, prepared)["shell_environment_policy"]
    assert resolved["include_only"] == ["SESSION007_ALLOWED"]
    assert resolved["exclude"] == ["SESSION007_EXCLUDED"]
    assert resolved.get("filters") is None
    prepared["env"] = {"SESSION007_OTHER": "required"}
    with pytest.raises(SessionError) as caught:
        provider.launch_spec(context, prepared)
    assert caught.value.code == "env_policy_conflict"
    prepared["env"] = {"SESSION007_ALLOWED": "required"}
    assert provider.launch_spec(context, prepared)["env"] == {"SESSION007_ALLOWED": "required"}
    assert (rpc.config, rpc.layers, profile_file.read_text()) == before


def test_codex_empty_filters_clear_a_lower_legacy_allowlist(codex, profile_file):
    provider, rpc, context, prepared = codex
    rpc.config = {"sandbox_mode": "danger-full-access", "shell_environment_policy": {"filters": {}}}
    rpc.layers = [config_layer("project", {"shell_environment_policy": {"filters": {}}}),
                  config_layer("project", {"shell_environment_policy": {
                      "include_only": ["SESSION007_ALLOWED"], "exclude": ["SESSION007_EXCLUDED"]}}),
                  config_layer("user", {"sandbox_mode": "danger-full-access"})]
    before = (copy.deepcopy(rpc.config), copy.deepcopy(rpc.layers), profile_file.read_text())
    resolved = read_configuration(provider, context, prepared)["shell_environment_policy"]
    assert resolved.get("include_only") is None and resolved.get("exclude") is None
    assert resolved["filters"] == {}
    prepared["env"] = {"SESSION007_OTHER": "required"}
    assert provider.launch_spec(context, prepared)["env"] == {"SESSION007_OTHER": "required"}
    assert (rpc.config, rpc.layers, profile_file.read_text()) == before


def test_codex_selected_profile_rejects_mixed_filter_families(codex, profile_file):
    provider, rpc, context, prepared = codex
    text = '''sandbox_mode = "danger-full-access"
[shell_environment_policy]
include_only = ["SESSION007_ALLOWED"]
[shell_environment_policy.filters]
SESSION007_NEW = "include"
'''
    profile_file.write_text(text)
    before = (copy.deepcopy(rpc.config), copy.deepcopy(rpc.layers))
    with pytest.raises(SessionError) as caught:
        provider.launch_spec(context, prepared)
    assert caught.value.code == "env_policy_conflict"
    assert profile_file.read_text() == text
    assert (rpc.config, rpc.layers) == before


@pytest.mark.parametrize(("lower_mode", "upper_mode", "allowed"), [
    ("include", "exclude", False),
    ("exclude", "include", True),
])
def test_codex_filters_merge_casefolded_names_with_upper_layer_winning(
    codex, profile_file, lower_mode, upper_mode, allowed
):
    provider, rpc, context, prepared = codex
    rpc.config = {"sandbox_mode": "danger-full-access", "shell_environment_policy": {"filters": {
        "session007_allowed": upper_mode, "session007_base": "exclude", "session007_other": "include"}}}
    rpc.layers = [config_layer("project", {"shell_environment_policy": {"filters": {
                      "session007_allowed": upper_mode, "SESSION007_OTHER": "include"}}}),
                  config_layer("project", {"shell_environment_policy": {"filters": {
                      "SESSION007_ALLOWED": lower_mode, "SESSION007_BASE": "exclude"}}}),
                  config_layer("user", {"sandbox_mode": "danger-full-access"})]
    before = (copy.deepcopy(rpc.config), copy.deepcopy(rpc.layers), profile_file.read_text())
    resolved = read_configuration(provider, context, prepared)["shell_environment_policy"]
    assert resolved["filters"] == {"session007_allowed": upper_mode, "session007_base": "exclude",
                                   "session007_other": "include"}
    prepared["env"] = {"SESSION007_ALLOWED": "required"}
    if allowed:
        assert provider.launch_spec(context, prepared)["env"] == {"SESSION007_ALLOWED": "required"}
    else:
        with pytest.raises(SessionError) as caught:
            provider.launch_spec(context, prepared)
        assert caught.value.code == "env_policy_conflict"
    assert (rpc.config, rpc.layers, profile_file.read_text()) == before


def test_codex_profile_policy_merges_nested_maps_in_priority_order(codex, profile_file):
    provider, rpc, context, prepared = codex
    rpc.config = {"sandbox_mode": "workspace-write", "model": "native-model"}
    rpc.layers = [
        config_layer("sessionFlags", {"shell_environment_policy": {
            "set": {"DAEMON": "daemon", "WINNER": "daemon"}}}),
        config_layer("project", {"sandbox_mode": "danger-full-access", "shell_environment_policy": {
            "set": {"PROJECT": "project", "WINNER": "project"},
            "filters": {"PROJECT_DROP": "exclude"}}}),
        config_layer("user", {"sandbox_mode": "read-only", "shell_environment_policy": {
            "inherit": "core",
            "set": {"BASE": "base", "WINNER": "user"}, "filters": {"BASE_KEEP": "include"}}}),
        config_layer("enterpriseManaged", {"shell_environment_policy": {"set": {"CLOUD": "cloud"}}}),
        config_layer("system", {"shell_environment_policy": {"set": {"SYSTEM": "system"}}}),
        config_layer("packagedDefaults", {"shell_environment_policy": {"set": {"PACKAGE": "package"}}}),
    ]
    profile_file.write_text('''sandbox_mode = "workspace-write"
[shell_environment_policy.set]
PROFILE = "profile"
WINNER = "profile"
[shell_environment_policy.filters]
PROFILE_KEEP = "include"
''')
    prepared["provider_args"] += ["-c", 'shell_environment_policy.set.WINNER="new-cli"']
    before_config, before_layers = copy.deepcopy(rpc.config), copy.deepcopy(rpc.layers)
    before_profile = profile_file.read_text()
    result = read_configuration(provider, context, prepared)
    assert result == {"sandbox_mode": "danger-full-access", "model": "native-model",
                      "shell_environment_policy": {
                          "inherit": "core",
                          "set": {"PACKAGE": "package", "SYSTEM": "system", "CLOUD": "cloud",
                                  "BASE": "base", "PROFILE": "profile", "PROJECT": "project",
                                  "DAEMON": "daemon", "WINNER": "new-cli"},
                          "filters": {"base_keep": "include", "profile_keep": "include",
                                      "project_drop": "exclude"}}}
    assert rpc.config == before_config and rpc.layers == before_layers
    assert rpc.config_responses[-1] == {"config": before_config, "origins": {}, "layers": before_layers}
    assert profile_file.read_text() == before_profile


def test_codex_legacy_policy_arrays_are_replaced_without_dropping_the_other_array(codex, profile_file):
    provider, rpc, context, prepared = codex
    rpc.config = {"sandbox_mode": "danger-full-access", "shell_environment_policy": {
        "include_only": ["PROJECT_ONLY"], "exclude": ["DAEMON_EXCLUDED"]}}
    rpc.layers = [config_layer("sessionFlags", {"shell_environment_policy": {"exclude": ["DAEMON_EXCLUDED"]}}),
                  config_layer("project", {"shell_environment_policy": {"include_only": ["PROJECT_ONLY"]}}),
                  config_layer("user", {"shell_environment_policy": {
                      "include_only": ["USER_ONLY"], "exclude": ["USER_EXCLUDED"]}})]
    profile_file.write_text('''sandbox_mode = "danger-full-access"
[shell_environment_policy]
include_only = ["PROFILE_ONLY"]
''')
    prepared["provider_args"] += ["-c", 'shell_environment_policy.include_only=["CLI_ONLY"]']
    before = (copy.deepcopy(rpc.config), copy.deepcopy(rpc.layers), profile_file.read_text())
    resolved = read_configuration(provider, context, prepared)["shell_environment_policy"]
    assert resolved["include_only"] == ["CLI_ONLY"]
    assert resolved["exclude"] == ["DAEMON_EXCLUDED"]
    assert resolved.get("filters") is None
    assert (rpc.config, rpc.layers, profile_file.read_text()) == before


def test_codex_legacy_managed_layer_keeps_the_native_relative_position(codex, profile_file):
    provider, rpc, context, prepared = codex
    rpc.config["sandbox_mode"] = "workspace-write"
    rpc.layers = [config_layer("legacyManagedConfigTomlFromFile", {"sandbox_mode": "workspace-write"}),
                  config_layer("project", {"sandbox_mode": "danger-full-access"}),
                  config_layer("user", {"sandbox_mode": "read-only"})]
    assert read_configuration(provider, context, prepared)["sandbox_mode"] == "workspace-write"


@pytest.mark.parametrize("legacy_policy", [
    'include_only = ["EXAMPLE_SESSION"]',
    'exclude = ["OTHER"]',
])
def test_codex_unset_cannot_replace_configured_legacy_filters(codex, profile_file, legacy_policy):
    provider, _, context, prepared = codex
    profile_file.write_text('sandbox_mode = "danger-full-access"\n[shell_environment_policy]\n'
                            + legacy_policy + '\n')
    prepared["env"] = {"EXAMPLE_SESSION": "required"}
    prepared["unset_env"] = ["EXAMPLE_FLAG"]
    # Injected CLI filters would erase the lower layer's legacy restrictions.
    with pytest.raises(SessionError) as caught:
        provider.launch_spec(context, prepared)
    assert caught.value.code == "env_policy_conflict"


@pytest.mark.parametrize("project_policy", [
    {"set": {"EXAMPLE_FLAG": "restored-by-project"}},
    {"include_only": ["OTHER"]},
])
def test_codex_project_policy_conflicts_are_checked_after_profile_resolution(codex, profile_file, project_policy):
    provider, rpc, context, prepared = codex
    rpc.config = {"sandbox_mode": "danger-full-access", "shell_environment_policy": project_policy}
    rpc.layers = [config_layer("project", copy.deepcopy(rpc.config)), config_layer("user", {})]
    profile_file.write_text('''sandbox_mode = "danger-full-access"
[shell_environment_policy]
include_only = ["EXAMPLE_SESSION"]
''')
    prepared["env"] = {"EXAMPLE_SESSION": "required"}
    prepared["unset_env"] = ["EXAMPLE_FLAG"]
    with pytest.raises(SessionError) as caught:
        provider.launch_spec(context, prepared)
    assert caught.value.code == "env_policy_conflict"


def test_codex_without_profile_preserves_native_effective_config(codex):
    provider, rpc, context, prepared = codex
    rpc.config = {"sandbox_mode": "danger-full-access", "shell_environment_policy": {"set": {"NATIVE": "keep"}},
                  "model": "native-model"}
    rpc.layers = "not consulted without a profile"
    before = copy.deepcopy(rpc.config)
    assert read_configuration(provider, context, prepared) == before
    assert rpc.calls[-1] == ("config/read", {"cwd": context["cwd"], "includeLayers": False})
    assert rpc.config == before


@pytest.mark.parametrize(("layers", "expected_code"), [
    (None, "provider_protocol_unsupported"),
    ([], "provider_protocol_unsupported"),
    ({}, "provider_protocol_error"),
    (["invalid layer"], "provider_protocol_error"),
    ([{"name": None, "config": {}}], "provider_protocol_error"),
    ([{"name": {"type": "user"}, "config": "invalid config"}], "provider_protocol_error"),
    ([config_layer("project", {"sandbox_mode": "danger-full-access"})], "provider_protocol_unsupported"),
    ([config_layer("user", {}, disabled_reason="")], "provider_protocol_unsupported"),
    ([config_layer("user", {}), config_layer("user", {})], "provider_protocol_error"),
    ([config_layer("user", {}), config_layer("project", {})], "provider_protocol_unsupported"),
])
def test_codex_profile_requires_valid_active_layers(codex, profile_file, layers, expected_code):
    provider, rpc, context, prepared = codex
    rpc.layers = layers
    with pytest.raises(SessionError) as caught:
        provider.launch_spec(context, prepared)
    assert caught.value.code == expected_code


def test_codex_profile_refuses_a_response_without_layers(codex, profile_file):
    provider, rpc, context, prepared = codex
    rpc.omit_layers = True
    with pytest.raises(SessionError) as caught:
        provider.launch_spec(context, prepared)
    assert caught.value.code == "provider_protocol_unsupported"


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
