"""Decision item format: parse a decision file and check it.

The format is owned by skills/project-item/references/decide.md. This module is its
only executable copy; tests/test_doc_contract.py::test_code_matches_format_documents
fails when the two differ.
"""
from __future__ import annotations

import re
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .cr import (HEADER_RE, ID_RE as CR_ID_RE, SECTION_RE, STATUS_LINE_RE, files, outcome_kind,
                 outside_fence, set_header)
from .errors import ItemError

STATES = ("open", "answered", "done")
URGENCIES = ("high", "normal", "low")

ID_RE = r"D-\d{8}-\d{2,}"
TITLE_RE = re.compile(rf"^#\s+({ID_RE}):\s+(\S.*?)\s*$")
OPENED_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
OUTCOME_RE = re.compile(r"^(decided\s+\S.*|withdrawn|merged\s+\S+)$")

RELATED_CR_RE = re.compile(rf"(?<![\w-])({CR_ID_RE})(?![\w-])")
MAX_ANSWER_BYTES = 16384

REQUIRED_HEADERS = ("Opened", "Urgency")
BODY_SECTIONS = ("Background", "Options", "Recommendation", "Evidence")
SECTION_ORDER = ("Background", "Options", "Recommendation", "Evidence", "Disposition", "Result")

__all__ = ["STATES", "URGENCIES", "ID_RE", "TITLE_RE", "SECTION_ORDER", "Decision",
           "answer_text", "answer_json", "check_answer", "decision_stage", "prepare_move",
           "check_outcome", "MAX_ANSWER_BYTES",
           "parse", "parse_text", "check", "files", "TEMPLATE", "EMPTY_BODY"]


@dataclass
class Decision:
    path: Path
    state: str
    item_id: str | None = None
    title: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    sections: list[str] = field(default_factory=list)
    status_line: bool = False


def parse(path: Path, state: str) -> Decision:
    return parse_text(path.read_text(encoding="utf-8"), path, state)


def parse_text(text: str, path: Path, state: str) -> Decision:
    item = Decision(path=path, state=state)
    in_header = False
    for _, line in outside_fence(text.splitlines()):
        if item.title is None and line.startswith("# "):
            m = TITLE_RE.match(line)
            if m:
                item.item_id, item.title = m.group(1), m.group(2)
            else:
                item.title = line[2:].strip()
            in_header = True
            continue
        if in_header:
            m = HEADER_RE.match(line)
            if m:
                item.headers.setdefault(m.group(1), m.group(2))
                continue
            if STATUS_LINE_RE.match(line):
                item.status_line = True
                continue
            if line.strip() == "":
                continue
            in_header = False
        if STATUS_LINE_RE.match(line):
            item.status_line = True
        m = SECTION_RE.match(line)
        if m:
            item.sections.append(m.group(1))
    return item


def answer_text(item: Decision) -> str | None:
    """Return the exact submitted answer, or None for a legacy decision without one."""
    encoded = item.headers.get("Answer")
    if encoded is None:
        return None
    try:
        answer = json.loads(encoded)
    except (TypeError, ValueError):
        return None
    return answer if isinstance(answer, str) else None


def answer_json(answer: str) -> str:
    """Keep the JSON string on one Markdown line without escaping ordinary Unicode text."""
    encoded = json.dumps(answer, ensure_ascii=False)
    for separator in ("\x85", "\u2028", "\u2029"):
        encoded = encoded.replace(separator, f"\\u{ord(separator):04x}")
    return encoded


def check_answer(answer: object) -> None:
    """Refuse an answer that cannot be recorded."""
    if not isinstance(answer, str):
        raise ItemError("answer_invalid", "The decision answer must be text.")
    if not answer.strip():
        raise ItemError("answer_empty", "The decision answer is empty.")
    if "\x00" in answer:
        raise ItemError("answer_invalid", "The decision answer contains a NUL byte.")
    if len(answer.encode("utf-8")) > MAX_ANSWER_BYTES:
        raise ItemError("answer_too_large", f"Keep the answer within {MAX_ANSWER_BYTES} bytes.")


def decision_stage(item: dict, states: Mapping[str, str]) -> str:
    """Display stage from the decision directory and related CR/JOB directories.
    `item` has the keys state and headers; `states` maps CR/JOB IDs to their directory."""
    if item["state"] == "open":
        return "결정 대기"
    if item["state"] == "answered":
        return "답변 접수"
    if item["headers"].get("Outcome", "").split()[:1] == ["withdrawn"]:
        return "완료"
    related = RELATED_CR_RE.findall(item["headers"].get("Related", ""))
    return ("반영 중" if any(states.get(item_id) not in ("done", "deferred") for item_id in related)
            else "완료")


def prepare_move(item_id: str, text: str, path: Path, source_state: str, state: str,
                 outcome: str | None, note: str | None) -> tuple[str, str | None]:
    """The decision rules of a move that read or change the Answer. Return the text and note to
    use. `outcome` is the one the caller gave."""
    if state == "done" and source_state == "open" and outcome_kind(outcome) == "decided":
        raise ItemError("invalid_transition", "Record the answer before confirming a decided decision.")
    if source_state == "answered" and state in ("done", "open"):
        answer = answer_text(parse_text(text, path, source_state))
        if answer is None:
            raise ItemError("format_invalid", f"{item_id} has no recorded answer.")
        label = "사용자 답변 원문" if state == "done" else "이전 답변 원문"
        original = f"{label}: {answer_json(answer)}"
        note = f"{note} {original}" if note else original    # a move to open always has a note
    if state == "open":
        text = set_header(text, "Answer", None)
    return text, note


def check_outcome(source_state: str, new_outcome: str | None) -> None:
    """The decision rule on the Outcome that a move gives: none."""


def check(item: Decision) -> list[str]:
    """Format violations of one decision file. Empty list = the file follows the format."""
    bad = []
    if item.item_id is None:
        bad.append("title is not '# D-YYYYMMDD-NN: <question>'")
    elif item.path.name != f"{item.item_id}.md":
        bad.append(f"file name is not '{item.item_id}.md'")
    for key in REQUIRED_HEADERS:
        if not item.headers.get(key):
            bad.append(f"header '- {key}:' missing")
    if item.headers.get("Opened") and not OPENED_RE.match(item.headers["Opened"]):
        bad.append("Opened is not 'YYYY-MM-DD HH:MM'")
    urgency = item.headers.get("Urgency")
    if urgency and urgency not in URGENCIES:
        bad.append(f"Urgency '{urgency}' is not high, normal or low")
    if item.status_line or "Status" in item.headers:
        bad.append("status line in the body; the directory owns the state")
    outcome = item.headers.get("Outcome")
    if item.state != "done" and outcome:
        bad.append(f"Outcome in {item.state}/; only done/ has it")
    answer = answer_text(item)
    if item.state == "open" and "Answer" in item.headers:
        bad.append("Answer in open/; only answered/ or done/ has it")
    if item.state == "answered" and (answer is None or not answer.strip()):
        bad.append("answered/ needs a non-empty JSON-string Answer header")
    if "Answer" in item.headers and answer is None:
        bad.append("Answer is not a JSON string")
    if item.state == "done":
        if not outcome:
            bad.append("header '- Outcome:' missing")
        elif not OUTCOME_RE.match(outcome):
            bad.append(f"Outcome '{outcome}' is not decided <choice> | withdrawn | merged <ID>")
    dup = sorted({s for s in item.sections if item.sections.count(s) > 1})
    if dup:
        bad.append(f"duplicate sections: {', '.join(dup)}")
    need = list(BODY_SECTIONS) + (["Disposition"] if item.state == "done" else [])
    for name in need:
        if name not in item.sections:
            bad.append(f"section '## {name}' missing")
    known = [s for s in item.sections if s in SECTION_ORDER]
    if known != sorted(known, key=SECTION_ORDER.index):
        bad.append("sections are not in the order " + " / ".join(SECTION_ORDER))
    return bad


TEMPLATE = """\
# {item_id}: {title}

- Opened: {opened}
- Urgency: {urgency}
{extra}
{body}"""

EMPTY_BODY = """\
## Background

## Options

| 선택지 | 내용 | 결과 |
| --- | --- | --- |

## Recommendation

## Evidence
"""
