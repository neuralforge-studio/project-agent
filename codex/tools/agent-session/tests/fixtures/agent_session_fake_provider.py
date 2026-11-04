"""Native provider boundary for real tmux integration tests."""

import argparse
import json
import os
from pathlib import Path
import sys
import uuid


class FakeProvider:
    def prepare_context(self, context):
        return {**context, "endpoint": "unix:///tmp/agent-session-fixture.sock"}

    def registration_hooks(self, context):
        return {}

    def launch_spec(self, context, prepared):
        return {
            "argv": [context["python"], "-u", str(Path(__file__).resolve()),
                     "--library", context["library_path"], "--run", context["run_id"],
                     "--config", context["config_path"], "--socket", context["socket_path"],
                     "--endpoint", context["endpoint"]],
            "env": prepared.get("env", {}), "unset_env": [],
        }

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


def main():
    parser = argparse.ArgumentParser()
    for key in ("library", "run", "config", "socket", "endpoint"):
        parser.add_argument("--" + key, required=True)
    args = parser.parse_args()
    sys.path.insert(0, args.library)
    import agent_session.providers as providers
    providers.get_provider = lambda name: FakeProvider()
    from agent_session.internal import register_current
    from agent_session.errors import SessionError
    os.environ["CODEX_THREAD_ID"] = str(uuid.uuid4())
    try:
        register_current(args.run, args.config, args.socket, args.endpoint)
    except SessionError as error:
        # A failed tool call does not exit an interactive provider TUI.
        base = Path(os.environ["AGENT_SESSION_BASE"])
        path = base / "agent" / "runs" / args.run / "fixture-tool-error.json"
        path.write_text(json.dumps(error.as_dict()), encoding="utf-8")
    for line in sys.stdin:
        if line.strip() == "/exit":
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
