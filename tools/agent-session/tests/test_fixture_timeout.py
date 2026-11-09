"""The fixture's per-command wait limit is a ceiling for a hung command and can be overridden."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from agent_session_fixture import session_env  # noqa: F401


def test_default_wait_limit_is_two_minutes(session_env, monkeypatch):
    monkeypatch.delenv("AGENT_SESSION_TEST_TIMEOUT", raising=False)
    assert session_env.manager().timeout == 120


def test_environment_variable_raises_every_manager_wait_limit(session_env, monkeypatch):
    monkeypatch.setenv("AGENT_SESSION_TEST_TIMEOUT", "240")
    assert session_env.manager().timeout == 240
    assert session_env.manager_at(session_env.base).timeout == 240


def test_explicit_wait_limit_overrides_the_environment_variable(session_env, monkeypatch):
    monkeypatch.setenv("AGENT_SESSION_TEST_TIMEOUT", "240")
    assert session_env.manager(timeout=3).timeout == 3
