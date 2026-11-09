"""Select the provider implementation from the project registry."""

from ..errors import SessionError
from .claude import ClaudeProvider
from .codex import CodexProvider


def get_provider(name):
    if name == "claude":
        return ClaudeProvider()
    if name == "codex":
        return CodexProvider()
    raise SessionError("invalid_provider", "Provider must be claude or codex.", 2)
