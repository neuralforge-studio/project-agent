"""Select the provider implementation from the project registry.

Each implementation is imported when it is selected: a Claude project never loads the Codex module
(and its tomllib, WebSocket and URL code), and the other way round.
"""

from ..errors import SessionError


def get_provider(name):
    if name == "claude":
        from .claude import ClaudeProvider
        return ClaudeProvider()
    if name == "codex":
        from .codex import CodexProvider
        return CodexProvider()
    raise SessionError("invalid_provider", "Provider must be claude or codex.", 2)
