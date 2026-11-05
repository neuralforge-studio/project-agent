"""CR file format: parse a CR file and check it against the format of the CR contract
(codex/skills/project-item/references/cr.md).

The format (references/cr.md "파일 형식") is the single source. This module is its
only executable copy; keep the two in step.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

STATES = ("open", "todo", "in-progress", "done", "deferred")
MODES = ("write", "read-only")
SEVERITIES = ("S1", "S2", "S3")

ID_RE = r"[A-Z][A-Z0-9]*-\d{2,}"
TITLE_RE = re.compile(rf"^#\s+({ID_RE}):\s+(\S.*?)\s*$")
HEADER_RE = re.compile(r"^-\s+([A-Z][A-Za-z ]*?):\s*(.*?)\s*$")
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\b")
OUTCOME_RE = re.compile(rf"^(fixed|waived|merged\s+{ID_RE}|moved\s+\S+\s+\S+)$")
BASE_RE = re.compile(r"^[0-9a-f]{40} \d{4}-\d{2}-\d{2}T\S+$")
STATUS_LINE_RE = re.compile(r"^-\s+\**Status\**\s*:", re.I)

REQUIRED_HEADERS = ("Opened", "Scope", "Severity")
FINDING_SECTIONS = ("Symptom", "Evidence", "Contract")
PLAN_SECTIONS = ("Implementation", "Verification")
SECTION_ORDER = ("Symptom", "Evidence", "Contract", "Suspected cause", "Disposition",
                 "Implementation", "Verification", "Result")


@dataclass
class Cr:
    path: Path
    state: str
    cr_id: str | None = None
    title: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    sections: list[str] = field(default_factory=list)
    status_line: bool = False


def state_of(path: Path, root: Path) -> str | None:
    """State directory of a file under a CR root (done/ may have group subdirectories)."""
    try:
        first = path.resolve().relative_to(root.resolve()).parts[0]
    except (ValueError, IndexError):
        return None
    return first if first in STATES else None


def parse(path: Path, state: str) -> Cr:
    return parse_text(path.read_text(encoding="utf-8"), path, state)


def parse_text(text: str, path: Path, state: str) -> Cr:
    """Parse CR text as if it were the file `path` in `state` (used before a move)."""
    cr = Cr(path=path, state=state)
    in_fence = False
    in_header = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if cr.title is None:
            m = TITLE_RE.match(line)
            if m:
                cr.cr_id, cr.title = m.group(1), m.group(2)
                in_header = True
                continue
            if line.startswith("# "):
                cr.title = line[2:].strip()
                in_header = True
                continue
        if in_header:
            m = HEADER_RE.match(line)
            if m:
                cr.headers.setdefault(m.group(1), m.group(2))
                continue
            if STATUS_LINE_RE.match(line):
                cr.status_line = True
                continue
            if line.strip() == "":
                continue
            in_header = False
        if STATUS_LINE_RE.match(line):
            cr.status_line = True
        m = SECTION_RE.match(line)
        if m:
            cr.sections.append(m.group(1))
    return cr


def check(cr: Cr) -> list[str]:
    """Format violations of one CR file. Empty list = the file follows the format."""
    bad = []
    history = cr.state == "done" and "Migrated" in cr.headers
    if history:
        pass                               # migrated history keeps its ID and file name
    elif cr.cr_id is None:
        bad.append("title is not '# <AREA>-<NNN>: <title>'")
    elif not cr.path.name.startswith(cr.cr_id + "-"):
        bad.append(f"file name does not start with '{cr.cr_id}-'")
    for key in REQUIRED_HEADERS:
        if not cr.headers.get(key):
            bad.append(f"header '- {key}:' missing")
    if cr.headers.get("Opened") and not DATE_RE.match(cr.headers["Opened"]):
        bad.append("Opened is not YYYY-MM-DD")
    sev = cr.headers.get("Severity", "")
    if sev and sev.split()[0] not in SEVERITIES:
        bad.append(f"Severity '{sev}' is not S1, S2 or S3")
    if cr.status_line:
        bad.append("status line in the body; the directory owns the state")
    mode = cr.headers.get("Mode")
    if mode is not None and mode not in MODES:
        bad.append(f"Mode '{mode}' is not write or read-only")
    cwd = cr.headers.get("Cwd")
    if cwd is not None and (not cwd or cwd.startswith("/") or ".." in Path(cwd).parts):
        bad.append(f"Cwd '{cwd}' is not a relative path inside the seat")
    base = cr.headers.get("Base")
    if base is not None and not BASE_RE.match(base):
        bad.append(f"Base '{base}' is not '<40-hex commit> <ISO time>'")
    outcome = cr.headers.get("Outcome")
    if cr.state in ("open", "todo", "in-progress") and outcome:
        bad.append(f"Outcome in {cr.state}/; only done/ and deferred/ have it")
    if cr.state in ("done", "deferred"):
        if not outcome:
            bad.append("header '- Outcome:' missing")
        elif not OUTCOME_RE.match(outcome) or "TBD" in outcome:
            bad.append(f"Outcome '{outcome}' is not fixed | waived | merged <ID> | moved <program> <ID>")
        elif cr.state == "deferred" and not outcome.startswith("moved"):
            bad.append("Outcome in deferred/ must be 'moved <program> <ID>'")
    dup = sorted({s for s in cr.sections if cr.sections.count(s) > 1})
    if dup:
        bad.append(f"duplicate sections: {', '.join(dup)}")
    if history:
        return bad                         # migrated history: only the header rules apply
    need: list[str] = []
    kind = (outcome or "").split()[0] if outcome else ""
    if cr.state in ("open", "todo", "in-progress", "deferred") or kind == "fixed":
        need += FINDING_SECTIONS
    if cr.state in ("todo", "in-progress") or kind == "fixed":
        need += PLAN_SECTIONS
    if kind == "fixed":
        need.append("Result")
    if kind in ("waived", "merged"):
        need.append("Disposition")
    for name in need:
        if name not in cr.sections:
            bad.append(f"section '## {name}' missing")
    known = [s for s in cr.sections if s in SECTION_ORDER]
    if known != sorted(known, key=SECTION_ORDER.index):
        bad.append("sections are not in the order " + " / ".join(SECTION_ORDER))
    return bad


def files(root: Path, state: str) -> list[Path]:
    base = root / state
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.md") if p.name != "README.md" and not p.name.startswith("ORDER"))


def next_id(root: Path, area: str) -> str:
    """Next free <AREA>-<NNN>: highest number of the area in any state directory + 1."""
    pat = re.compile(rf"^{re.escape(area)}-(\d+)\b")
    high = 0
    for state in STATES:
        for path in files(root, state):
            m = pat.match(path.name)
            if m:
                high = max(high, int(m.group(1)))
    return f"{area}-{high + 1:03d}"


def slug(text: str, limit: int = 60) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    out = "-".join(words)[:limit].rstrip("-")
    return out or "item"


TEMPLATE = """\
# {cr_id}: {title}

- Opened: {opened}
- Scope: {scope}
- Severity: {severity}
{extra}
{body}"""

EMPTY_BODY = """\
## Symptom

## Evidence

## Contract

## Suspected cause

## Disposition
"""
