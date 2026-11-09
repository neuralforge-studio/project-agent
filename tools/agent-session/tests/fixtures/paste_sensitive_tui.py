"""Model Codex 0.166's 120 ms Enter suppression through a real terminal."""

import json
import os
from pathlib import Path
import sys
import termios
import time
import tty


# External contract: PASTE_ENTER_SUPPRESS_WINDOW in Codex rust-v0.166.0.
# https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/tui/src/bottom_pane/paste_burst.rs
ENTER_SUPPRESS_SECONDS = 0.120


def main():
    ready, observation = map(Path, sys.argv[1:])
    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    text = ""
    last_text = None
    enters = 0
    try:
        tty.setraw(fd)
        ready.write_text("ready\n")
        while True:
            data = os.read(fd, 4096)
            if not data:
                return 2
            received_at = time.monotonic()
            for value in data.decode("ascii"):
                if value not in "\r\n":
                    text += value
                    last_text = received_at
                    continue
                enters += 1
                suppressed = last_text is not None and received_at - last_text <= ENTER_SUPPRESS_SECONDS
                event = {"text": text, "enter_suppressed": suppressed, "enter_count": enters}
                temporary = observation.with_suffix(".tmp")
                temporary.write_text(json.dumps(event))
                temporary.replace(observation)
                if not suppressed and text.strip() == "/exit":
                    return 0
                text += "\n"
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, previous)


if __name__ == "__main__":
    raise SystemExit(main())
