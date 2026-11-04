"""Format rules of the two kinds, from the contracts (references/cr.md, references/decide.md)."""
from pathlib import Path

import pytest

from project_item import cr, decide

DECISION = """\
# D-20261104-01: 결정 페이지를 어디에 둘까요?

- Opened: 2026-11-04 10:30
- Urgency: high
- Blocks: API 이전

## Background
배경입니다.

## Options
| 선택지 | 내용 | 결과 |
| --- | --- | --- |
| A | 안 | 결과 |

## Recommendation
A

## Evidence
`path:1`
"""


def write(root: Path, state: str, name: str, text: str) -> Path:
    path = root / state / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_valid_open_decision(tmp_path):
    path = write(tmp_path, "open", "D-20261104-01.md", DECISION)
    item = decide.parse(path, "open")
    assert item.item_id == "D-20261104-01"
    assert item.headers["Blocks"] == "API 이전"
    assert decide.check(item) == []


def test_done_decision_needs_outcome_and_disposition(tmp_path):
    path = write(tmp_path, "done", "D-20261104-01.md", DECISION)
    assert decide.check(decide.parse(path, "done")) == [
        "header '- Outcome:' missing", "section '## Disposition' missing"]
    text = DECISION.replace("- Blocks:", "- Outcome: decided A\n- Blocks:") + (
        "\n## Disposition\n- 2026-11-04 user: open -> done. \"D-20261104-01 A\"\n")
    path.write_text(text, encoding="utf-8")
    assert decide.check(decide.parse(path, "done")) == []


@pytest.mark.parametrize("change, message", [
    (("- Urgency: high", "- Urgency: urgent"), "Urgency 'urgent' is not high, normal or low"),
    (("- Opened: 2026-11-04 10:30", "- Opened: 2026-11-04"), "Opened is not 'YYYY-MM-DD HH:MM'"),
    (("- Blocks:", "- Outcome: decided A\n- Blocks:"), "Outcome in open/; only done/ has it"),
    (("## Evidence\n`path:1`\n", ""), "section '## Evidence' missing"),
    (("# D-20261104-01: ", "# D-20261104-01 "), "title is not '# D-YYYYMMDD-NN: <question>'"),
    (("- Blocks: API 이전", "- Blocks: x\n- Status: open"),
     "status line in the body; the directory owns the state"),
])
def test_decision_violations(tmp_path, change, message):
    path = write(tmp_path, "open", "D-20261104-01.md", DECISION.replace(*change))
    assert message in decide.check(decide.parse(path, "open"))


def test_decision_file_name_and_section_order(tmp_path):
    path = write(tmp_path, "open", "D-20261104-01-question.md", DECISION)
    assert "file name is not 'D-20261104-01.md'" in decide.check(decide.parse(path, "open"))
    moved = DECISION.replace("## Recommendation\nA\n\n", "") + "\n## Recommendation\nA\n"
    path = write(tmp_path, "open", "D-20261104-01.md", moved)
    assert any(m.startswith("sections are not in the order") for m in decide.check(decide.parse(path, "open")))


CR_OPEN = """\
# TOOL-001: Lost lock

- Opened: 2026-11-04
- Scope: demo
- Severity: S2

## Symptom
s

## Evidence
`a.py:1`

## Contract
c
"""


def test_cr_rules_are_the_contract_rules(tmp_path):
    path = write(tmp_path, "open", "TOOL-001-lost-lock.md", CR_OPEN)
    assert cr.check(cr.parse(path, "open")) == []
    path = write(tmp_path, "todo", "TOOL-001-lost-lock.md", CR_OPEN)
    assert cr.check(cr.parse(path, "todo")) == [
        "section '## Implementation' missing", "section '## Verification' missing"]
    path = write(tmp_path, "done", "TOOL-001-lost-lock.md", CR_OPEN.replace("- Severity: S2", "- Severity: S2\n- Outcome: fixed"))
    assert "section '## Result' missing" in cr.check(cr.parse(path, "done"))


def test_parse_text_matches_parse(tmp_path):
    path = write(tmp_path, "open", "TOOL-001-lost-lock.md", CR_OPEN)
    assert cr.parse_text(CR_OPEN, path, "open") == cr.parse(path, "open")
    path = write(tmp_path, "open", "D-20261104-01.md", DECISION)
    assert decide.parse_text(DECISION, path, "open") == decide.parse(path, "open")
