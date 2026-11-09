"""The tmux pane-died hook's command with the fixture provider: `internal.finish_ended` as the server runs it."""

import sys

library, fixtures, kind = sys.argv[1:4]
sys.path[:0] = [library, fixtures]
import agent_session_fake_provider as fake  # noqa: E402
import agent_session.lifecycle as lifecycle  # noqa: E402
import agent_session.providers as providers  # noqa: E402

provider = fake.FakeClaudeProvider if kind == "claude" else fake.FakeProvider
providers.get_provider = lifecycle.get_provider = lambda name: provider()
from agent_session.internal import finish_ended  # noqa: E402

finish_ended(*sys.argv[4:7])
