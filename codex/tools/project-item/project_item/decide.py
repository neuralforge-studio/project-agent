"""Decision item format: parse a decision file and check it.

The format is owned by codex/skills/project-item/references/decide.md. This module is its
only executable copy; tests/test_doc_contract.py::test_code_matches_format_documents
fails when the two differ.
"""
from __future__ import annotations

import re
import json
from dataclasses import dataclass, field
from pathlib import Path

from .cr import HEADER_RE, SECTION_RE, STATUS_LINE_RE, files, outside_fence

STATES = ("open", "answered", "done")
URGENCIES = ("high", "normal", "low")

ID_RE = r"D-\d{8}-\d{2,}"
TITLE_RE = re.compile(rf"^#\s+({ID_RE}):\s+(\S.*?)\s*$")
OPENED_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
OUTCOME_RE = re.compile(r"^(decided\s+\S.*|withdrawn|merged\s+\S+)$")

REQUIRED_HEADERS = ("Opened", "Urgency")
BODY_SECTIONS = ("Background", "Options", "Recommendation", "Evidence")
SECTION_ORDER = ("Background", "Options", "Recommendation", "Evidence", "Disposition", "Result")

__all__ = ["STATES", "URGENCIES", "ID_RE", "TITLE_RE", "SECTION_ORDER", "Decision",
           "answer_text",
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
