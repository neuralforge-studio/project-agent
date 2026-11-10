"""Fixture builders for the project-board tests (a unique module name; conftest names collide across tools)."""
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1]
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))
SHARED_TESTS = str(TOOL.parent / "tests")  # tmux_test_server, shared by every tool's tests
if SHARED_TESTS not in sys.path:
    sys.path.insert(0, SHARED_TESTS)

def click_socket(request):
    """A unique path for a Board click socket, removed when the test ends however it ends.

    The path is short and directly under ``/tmp`` so it stays under the ~108 byte socket limit.
    """
    path = f"/tmp/project-board-ui-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    request.addfinalizer(lambda: Path(path).unlink(missing_ok=True))
    return path


LEADER_ID = "11111111-1111-4111-8111-111111111111"
WORKER_IDS = ("22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333",
              "44444444-4444-4444-8444-444444444444")
ENDPOINT = "unix:///tmp/project-board-test/codex.sock"
BASE_HASH = "b" * 40


def cr_text(cr_id, title, with_base=True, mode=None, disposition="", result=""):
    headers = ["- Opened: 2026-11-05", "- Scope: board test", "- Severity: S3"]
    if mode:
        headers.append(f"- Mode: {mode}")
    if with_base:
        headers.append(f"- Base: {BASE_HASH} 2026-11-05T09:00:00+09:00")
    body = ("## Symptom\n\nNow.\n\n## Evidence\n\n`a.py:1`\n\n## Contract\n\nThe **contract** of " + cr_id + ".\n\n"
            "## Disposition\n\n" + disposition + "\n\n## Implementation\n\nDo it.\n\n## Verification\n\nCheck it.\n")
    if result:
        body += "\n## Result\n\n" + result + "\n"
    return f"# {cr_id}: {title}\n\n" + "\n".join(headers) + "\n\n" + body


def decide_text(decide_id, title, urgency="high", blocks="TOOL-002", related=None, state="open"):
    answer = '- Answer: "A"\n' if state == "answered" else ""
    outcome = "- Outcome: decided A\n" if state == "done" else ""
    disposition = ("\n## Disposition\n\n- 2026-11-05 user: 답변을 접수했습니다.\n"
                   if state == "answered" else
                   "\n## Disposition\n\n- 2026-11-05 user: A를 결정했습니다.\n" if state == "done" else "")
    return (f"# {decide_id}: {title}\n\n- Opened: 2026-11-05 09:30\n- Urgency: {urgency}\n- Blocks: {blocks}\n"
            + (f"- Related: {related}\n" if related else "") + answer + outcome + "\n"
            + "## Background\n\n배경 <b>입니다</b>.\n\n## Options\n\n| 선택지 | 내용 |\n| --- | --- |\n| A | 하나 |\n\n"
            "## Recommendation\n\nA를 추천합니다.\n\n## Evidence\n\n`b.py:2`\n" + disposition)


class Board:
    """A registry with one or more projects on the temporary disk."""

    def __init__(self, root: Path):
        self.root = root
        self.config = root / "project.json"
        self.registry = {}

    def project(self, name, seats=3, items=True):
        base = self.root / name / "main"
        base.mkdir(parents=True)
        entry = {"project": name, "provider": "codex", "seats": [f"../seat{n}" for n in range(seats)]}
        if items:
            entry.update(path_cr="./agent/cr/", path_decide="./agent/decide/")
            for state in ("open", "todo", "in-progress", "done", "deferred"):
                (base / "agent/cr" / state).mkdir(parents=True)
            for state in ("open", "answered", "done"):
                (base / "agent/decide" / state).mkdir(parents=True)
        self.registry[str(base)] = entry
        self.config.write_text(json.dumps(self.registry), encoding="utf-8")
        return base

    @staticmethod
    def state(base, value):
        (base / "agent").mkdir(exist_ok=True)
        (base / "agent/state.json").write_text(json.dumps(value), encoding="utf-8")

    @staticmethod
    def cr(base, state, cr_id, title="CR title", **kwargs):
        path = base / "agent/cr" / state / f"{cr_id}-item.md"
        path.write_text(cr_text(cr_id, title, **kwargs), encoding="utf-8")
        return path

    @staticmethod
    def decide(base, state, decide_id, title="Question", **kwargs):
        path = base / "agent/decide" / state / f"{decide_id}.md"
        path.write_text(decide_text(decide_id, title, state=state, **kwargs), encoding="utf-8")
        return path


def session(index, connected_at="2026-11-05T08:00:00Z"):
    value = {"session_id": WORKER_IDS[index], "endpoint": ENDPOINT}
    if connected_at:
        value["connected_at"] = connected_at
    return value


def leader(reviewing=None, connected_at="2026-11-04T09:00:00Z"):
    value = {"session_id": LEADER_ID, "endpoint": ENDPOINT}
    if connected_at:
        value.update(connected_at=connected_at, reviewing=reviewing)
    return value


async def wait_until(pilot, condition, timeout=10.0):
    """Wait for an asynchronous screen update to be observable instead of sleeping a fixed time."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        assert asyncio.get_running_loop().time() < deadline, "timed out waiting for the screen state"
        await pilot.pause(0.01)


class Frames:
    """Every frame Textual displays for an app, as the compositor's screen text followed by its styles.

    A frame is one `App._display` call outside `batch_update` (a headless run never reaches the terminal,
    so this is the point where a real terminal would be written)."""

    def __init__(self, app):
        self.app, self.shown, self.recording = app, [], False
        display = app._display

        def record(screen, renderable):
            if self.recording and renderable is not None and not app._batch_count:
                self.shown.append(self.screen())
            return display(screen, renderable)
        app._display = record

    def screen(self) -> str:
        strips = self.app.screen._compositor.render_strips()
        return ("\n".join(strip.text.rstrip() for strip in strips) + "\n--- styles\n"
                + "\n".join("|".join(str(segment.style) for segment in strip) for strip in strips))

    async def during(self, pilot, action):
        """Run `action` and let the screen settle. Returns the screen before, the frames drawn, the screen after."""
        await pilot.pause(0.05)
        before = self.screen()
        self.shown.clear()
        self.recording = True
        await action()
        await pilot.pause(0.2)
        self.recording = False
        return before, list(self.shown), self.screen()

    async def assert_only_before_or_after(self, pilot, action, what):
        """The contract of BOARD-017: no frame between the screen before the change and the one after it."""
        before, frames, after = await self.during(pilot, action)
        assert before != after, f"{what}: the change is not visible"
        assert frames, f"{what}: nothing was drawn"
        for frame in frames:
            assert frame in (before, after), f"{what}: an intermediate frame was drawn:\n{frame}\n--- before:\n{before}\n--- after:\n{after}"
