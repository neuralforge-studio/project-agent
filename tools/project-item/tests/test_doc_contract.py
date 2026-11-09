"""The code constants of the item kinds match the documents that own them.

Owners: SKILL.md "상태와 전이" (states and transitions), references/cr.md and
references/decide.md (headers, sections, Outcome values). `kinds.py`, `cr.py` and
`decide.py` are the executable copies; this test is what keeps the two in step.
"""
import re
import shutil
from pathlib import Path

import pytest

from project_item import cr, decide
from project_item.kinds import CR, DECIDE

SKILLS = Path(__file__).resolve().parents[3] / "skills" / "project-item"
CODE = {"cr": CR, "decide": DECIDE}


def section(text: str, title: str) -> str:
    """Body of the `## <title>` section; a `## ` line inside a code block is not a heading."""
    return cr.section_text(text, title)


def format_block(text: str) -> list[str]:
    """Lines of the first Markdown code block of the `## 파일 형식` section."""
    match = re.search(r"```markdown\n(.*?)```", section(text, "파일 형식"), re.S)
    return match.group(1).splitlines() if match else []


def header_lines(block: list[str]) -> dict[str, str]:
    """Header name -> the rest of its template line (value and annotation)."""
    found = {}
    for line in block:
        match = re.match(r"^- ([A-Z][A-Za-z]*): (.*)$", line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def required_headers(block: list[str]) -> tuple[str, ...]:
    """Headers whose template line has no `( ... )` annotation (optional, or only in some states)."""
    return tuple(name for name, rest in header_lines(block).items() if "(" not in rest)


def values(block: list[str], header: str) -> tuple[str, ...]:
    """First words of the `a | b | c` alternatives of a header line, without its annotation."""
    if header not in header_lines(block):
        return ()
    rest = re.split(r"\s+\(", header_lines(block)[header])[0]
    return tuple(alt.split()[0] for alt in rest.split("|"))


def sections_of(block: list[str]) -> tuple[str, ...]:
    return tuple(line[3:].strip() for line in block if line.startswith("## "))


def skill_rows(skill_md: str) -> dict[str, tuple[tuple[str, ...], set[tuple[str, str]]]]:
    """Kind -> (state directories, transitions) from the table of SKILL.md "상태와 전이"."""
    rows = {}
    for line in section(skill_md, "상태와 전이").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|", 2)]
        if len(cells) == 3 and cells[0].startswith("`"):
            rows[cells[0].strip("`")] = (tuple(re.findall(r"`([a-z-]+)`", cells[1])),
                                         set(re.findall(r"([a-z-]+)→([a-z-]+)", cells[2])))
    return rows


def cr_outcomes(cr_md: str) -> dict[str, set[str]]:
    """Destination -> Outcome kinds from the Outcome table of cr.md (`deferred/`만 marks the deferred one)."""
    found: dict[str, set[str]] = {"done": set(), "deferred": set()}
    for line in section(cr_md, "상태와 소유권").splitlines():
        match = re.match(r"^\| `([a-z]+)(?: [^`]*)?` \|", line)
        if match:
            found["deferred" if "`deferred/`만" in line else "done"].add(match.group(1))
    return found


def compare(skill: Path, cr_md: Path, decide_md: Path) -> list[str]:
    """Differences between the owning documents and the code constants. Empty = in step."""
    skill_text, cr_text, decide_text = (p.read_text(encoding="utf-8") for p in (skill, cr_md, decide_md))
    bad = []

    def check(what: str, document, code):
        if document != code:
            bad.append(f"{what}: document {document!r} != code {code!r}")

    rows = skill_rows(skill_text)
    check("SKILL.md kinds", sorted(rows), sorted(CODE))
    for name, kind in CODE.items():
        states, transitions = rows.get(name, ((), set()))
        check(f"{name} states", states, kind.states)
        check(f"{name} transitions", transitions,
              {(src, dst) for src, targets in kind.transitions.items() for dst in targets})

    cr_dirs = tuple(re.findall(r"^\| `([a-z-]+)/` \|", section(cr_text, "상태와 소유권"), re.M))
    check("cr.md state directories", cr_dirs, cr.STATES)
    cr_block, decide_block = format_block(cr_text), format_block(decide_text)
    check("cr headers", required_headers(cr_block), cr.REQUIRED_HEADERS)
    check("cr sections", sections_of(cr_block), cr.SECTION_ORDER)
    check("cr Severity", values(cr_block, "Severity"), cr.SEVERITIES)
    check("cr Mode", values(cr_block, "Mode"), cr.MODES)
    check("cr Outcome table", cr_outcomes(cr_text),
          {dest: set(kinds) for dest, kinds in CR.outcomes.items()})
    check("cr Outcome header", set(values(cr_block, "Outcome")),
          {kind for kinds in CR.outcomes.values() for kind in kinds})

    check("decide headers", required_headers(decide_block), decide.REQUIRED_HEADERS)
    check("decide sections", sections_of(decide_block), decide.SECTION_ORDER)
    check("decide Urgency", values(decide_block, "Urgency"),
          decide.URGENCIES)
    check("decide Outcome header",
          set(values(decide_block, "Outcome")),
          {kind for kinds in DECIDE.outcomes.values() for kind in kinds})
    return bad


def copies(tmp_path: Path) -> tuple[Path, Path, Path]:
    paths = (SKILLS / "SKILL.md", SKILLS / "references" / "cr.md", SKILLS / "references" / "decide.md")
    out = []
    for path in paths:
        target = tmp_path / path.name
        shutil.copy(path, target)
        out.append(target)
    return tuple(out)


def test_code_matches_format_documents():
    """The code constants equal the tables of SKILL.md, cr.md and decide.md (PASS on the real documents)."""
    assert compare(SKILLS / "SKILL.md", SKILLS / "references" / "cr.md",
                   SKILLS / "references" / "decide.md") == []


MUTATIONS = [      # (document, text to change, replacement, expected difference)
    ("SKILL.md", "todo→done, ", "", "cr transitions"),
    ("SKILL.md", "`open`, `todo`, `in-progress`, `done`, `deferred`", "`open`, `todo`, `done`, `deferred`",
     "cr states"),
    ("SKILL.md", "answered→open, ", "", "decide transitions"),
    ("cr.md", "| `todo/` | 수행하기로", "| `ready/` | 수행하기로", "cr.md state directories"),
    ("cr.md", "## Symptom\n관찰된", "## Sympt\n관찰된", "cr sections"),
    ("cr.md", "- Severity: S1 | S2 | S3", "- Severity: S1 | S2", "cr Severity"),
    ("cr.md", "- Scope: <리뷰 범위 이름>", "- Scope: <리뷰 범위 이름> (선택)", "cr headers"),
    ("cr.md", "| `waived` | 기각했습니다", "| `dropped` | 기각했습니다", "cr Outcome table"),
    ("cr.md", "넘겼습니다(`deferred/`만)", "넘겼습니다", "cr Outcome table"),
    ("decide.md", "- Urgency: high | normal | low", "- Urgency: high | low", "decide Urgency"),
    ("decide.md", "## Recommendation\n추천과", "## Advice\n추천과", "decide sections"),
    ("decide.md", "withdrawn |", "dropped |", "decide Outcome header"),
]


@pytest.mark.parametrize("name, old, new, expected", MUTATIONS)
def test_one_changed_table_is_reported(tmp_path, name, old, new, expected):
    """RED: a copy with one table changed reports a difference; the unchanged copy reports none."""
    skill, cr_md, decide_md = copies(tmp_path)
    assert compare(skill, cr_md, decide_md) == []
    target = {"SKILL.md": skill, "cr.md": cr_md, "decide.md": decide_md}[name]
    text = target.read_text(encoding="utf-8")
    assert text.count(old) >= 1, f"the mutation anchor is gone from {name}: {old!r}"
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    found = compare(skill, cr_md, decide_md)
    assert found and any(expected in line for line in found), found
