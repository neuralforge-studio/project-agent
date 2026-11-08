"""Native provider boundary for real tmux integration tests."""

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import uuid


class FakeProvider:
    def __init__(self, dialog=False):
        self.dialog = dialog               # hold the start at a trust dialog until the pane reads "approve"

    def prepare_context(self, context):
        return {**context, "endpoint": "unix:///tmp/agent-session-fixture.sock"}

    def registration_hooks(self, context):
        return {}

    def launch_spec(self, context, prepared):
        return {
            "argv": [context["python"], "-u", str(Path(__file__).resolve()),
                     "--library", context["library_path"], "--run", context["run_id"],
                     "--config", context["config_path"], "--socket", context["socket_path"],
                     "--endpoint", context["endpoint"]] + (["--dialog"] if self.dialog else [])
                    + (["--codex-dialog"] if self.dialog == "codex" else [])
                    + (["--session", context["session_id"]] if context.get("resume") else []),
            "env": prepared.get("env", {}), "unset_env": [],
        }

    def trust_new_seat(self, root):
        return False

    def trust_base(self, root):
        return False

    def startup_dialog(self, screen):
        from agent_session.providers.claude import startup_dialog
        return startup_dialog(screen)

    def verify_binding(self, session, context, meta, timeout=30):
        from agent_session.errors import SessionError
        expected = meta.get("session_id") or context.get("session_id")
        if expected and expected != session["session_id"]:
            raise SessionError("owner_mismatch", "The fixture native conversation does not match.")
        return session

    def observe(self, session, context, meta=None, timeout=30):
        return {"known": True, "terminal": True, "active_turn": False,
                "pending": [], "background": [], "idle": True}

    def send(self, session, text, context, timeout=30):
        path = Path(context["base"]) / "agent" / "fixture-messages.jsonl"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"session": session, "text": text, "target": context["target"]}, ensure_ascii=False) + "\n")
        return {"disposition": "accepted"}

    def request_stop(self, session, context, meta=None, timeout=30):
        return {"requested": True}

    def request_exit(self, meta, tmux):
        # The fixture CLI stands for a Codex TUI, so its exit request is Codex's own.
        from agent_session.providers.codex import CodexProvider
        return CodexProvider().request_exit(meta, tmux)


class FakeClaudeProvider(FakeProvider):
    """A Claude project whose CLI records its pane input and the signals it receives."""

    def launch_spec(self, context, prepared):
        spec = super().launch_spec(context, prepared)
        record = Path(context["base"]) / "agent" / "fixture-cli.jsonl"
        spec["argv"] += ["--claude", "--record", str(record)]
        return spec

    def verify_binding(self, session, context, meta, timeout=30):
        return {**super().verify_binding(session, context, meta, timeout), "message_to": "fixture-claude [f1x7ce]"}

    def request_exit(self, meta, tmux):
        from agent_session.providers.claude import ClaudeProvider
        return ClaudeProvider().request_exit(meta, tmux)

    def observe(self, session, context, meta=None, timeout=30):
        """The CLI is mid-turn while `<base>/agent/fixture-busy-<target>` exists and its pane lives."""
        observed = super().observe(session, context, meta, timeout)
        agent = Path(context["base"]) / "agent"
        if (agent / ("fixture-busy-" + context["target"])).exists() and not (meta or context).get("pane_dead"):
            return {**observed, "terminal": False, "active_turn": True, "idle": False}
        if (agent / ("fixture-shell-" + context["target"])).exists():
            # Claude reports status "shell", not "idle", while a background shell runs, and the Stop
            # report names that shell.
            return {**observed, "terminal": False, "idle": False, "active_turn": True, "runtime_status": "shell",
                    "background": [{"id": "bz1mzn8iq", "type": "shell", "status": "running",
                                    "description": "watch", "command": "until ! pgrep -f x; do sleep 3; done"}]}
        if (agent / ("fixture-background-" + context["target"])).exists():
            # Idle, but the last Stop report named a background task; that report stays after the CLI dies.
            return {**observed, "terminal": False, "background": ["task"]}
        return observed


def main():
    parser = argparse.ArgumentParser()
    for key in ("library", "run", "config", "socket", "endpoint"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--dialog", action="store_true")
    parser.add_argument("--codex-dialog", action="store_true")
    parser.add_argument("--session")                   # a resumed conversation keeps its recorded ID
    parser.add_argument("--claude", action="store_true")
    parser.add_argument("--record")
    args = parser.parse_args()

    def note(event):
        if args.record:
            with open(args.record, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(event) + "\n")

    def terminate(number, frame):
        note({"signal": "SIGTERM"})
        raise SystemExit(143)              # Claude 2.1.317 ends with status 143 on SIGTERM
    if args.record:
        signal.signal(signal.SIGTERM, terminate)
    if args.dialog:
        screen = ("Folder access\nTrust this folder?\n❯ 1. Yes, trust this folder\n  2. No, exit"
                  if args.codex_dialog else
                  "Accessing workspace:\n\n❯ 1. Yes, I trust this folder\n  2. No, exit")
        print(screen, flush=True)
        for line in sys.stdin:
            if line.strip() == "approve":
                break
        print("\033[2J\033[H", end="", flush=True)  # the answered dialog leaves the screen
    sys.path.insert(0, args.library)
    import agent_session.providers as providers
    fake = FakeClaudeProvider() if args.claude else FakeProvider()
    providers.get_provider = lambda name: fake
    from agent_session.internal import register_current
    from agent_session.errors import SessionError
    os.environ["CODEX_THREAD_ID"] = args.session or str(uuid.uuid4())
    try:
        register_current(args.run, args.config, args.socket, args.endpoint)
    except SessionError as error:
        # A failed tool call does not exit an interactive provider TUI.
        base = Path(os.environ["AGENT_SESSION_BASE"])
        path = base / "agent" / "runs" / args.run / "fixture-tool-error.json"
        path.write_text(json.dumps(error.as_dict()), encoding="utf-8")
    for line in sys.stdin:
        note({"input": line.rstrip("\n")})
        if line.strip() == "/exit":
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
