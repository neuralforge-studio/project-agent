"""Item files: the per-root lock, ID issue, lookup, move and the files that `check` reads."""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from .cr import section_heads
from .kinds import CR, DECIDE, Kind
from .registry import ItemError

MAX_DECISION_ANSWER_BYTES = 16384


# ---------------------------------------------------------------- lock
def lock_path(root: Path) -> Path:
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]
    return Path.home() / ".cache" / "project-item" / "locks" / f"{digest}.lock"


@contextlib.contextmanager
def root_lock(root: Path):
    """Serialize ID issue and moves of one item root between sessions of this machine."""
    path = lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _pause(step: str) -> None:
    """Test hook: called inside the lock between the read and the write of new and move."""


# ---------------------------------------------------------------- files
def item_files(kind: Kind, root: Path, state: str) -> list[Path]:
    return kind.fmt.files(root, state)


def all_files(kind: Kind, root: Path) -> list[tuple[str, Path]]:
    return [(state, path) for state in kind.states for path in item_files(kind, root, state)]


def file_id(kind: Kind, path: Path) -> str | None:
    m = kind.id_re.match(path.name)
    return m.group(1) if m else None


def find(kind: Kind, root: Path, item_id: str) -> tuple[str, Path]:
    found = [(state, path) for state, path in all_files(kind, root) if file_id(kind, path) == item_id]
    if not found:
        raise ItemError("item_not_found", f"No {kind.name} item {item_id} under {root}.")
    if len(found) > 1:
        raise ItemError("item_duplicate", f"{item_id} has several files: "
                        + ", ".join(str(path) for _, path in found))
    return found[0]


def duplicates(kind: Kind, root: Path) -> dict[str, list[Path]]:
    seen: dict[str, list[Path]] = {}
    for _, path in all_files(kind, root):
        item_id = file_id(kind, path)
        if item_id:
            seen.setdefault(item_id, []).append(path)
    return {item_id: paths for item_id, paths in seen.items() if len(paths) > 1}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def in_git(root: Path) -> bool:
    return root.is_dir() and _git(root, "rev-parse", "--is-inside-work-tree").stdout.strip() == "true"


def uncommitted(root: Path) -> set[Path]:
    """Changed, untracked or renamed files under the root. NUL-separated porcelain output keeps
    non-ASCII paths exact (the default output quotes them with octal escapes)."""
    out = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "-z", "-uall", "--", "."],
                         capture_output=True)
    top = Path(_git(root, "rev-parse", "--show-toplevel").stdout.strip())
    fields = out.stdout.decode("utf-8", "surrogateescape").split("\0")
    paths = set()
    i = 0
    while i < len(fields) and fields[i]:
        status, rel = fields[i][:2], fields[i][3:]
        paths.add((top / rel).resolve())
        i += 2 if "R" in status or "C" in status else 1    # the next field is the original path
    return paths


def history_high(root: Path, area: str) -> int:
    """Highest <AREA>-<NNN> number named by any state-directory file in the git history of the root,
    removed files included (a number is not reused). Other directories are not read. 0 outside git."""
    if not in_git(root):
        return 0
    out = subprocess.run(["git", "-C", str(root), "log", "--all", "--name-only", "--format=", "-z",
                          "--relative", "--", "."], capture_output=True)
    pat = re.compile(rf"^{re.escape(area)}-(\d+)\b")
    high = 0
    for name in out.stdout.decode("utf-8", "surrogateescape").split("\0"):
        parts = Path(name.strip("\n")).parts
        if len(parts) > 1 and parts[0] in CR.states:
            m = pat.match(parts[-1])
            if m:
                high = max(high, int(m.group(1)))
    return high


def check_targets(kind: Kind, root: Path) -> list[tuple[str, Path]]:
    """Every file in a non-terminal state, and the terminal files that are not committed history.
    Outside a git work tree every file is a target."""
    committed_history = in_git(root)
    changed = uncommitted(root) if committed_history else set()
    out = []
    for state, path in all_files(kind, root):
        if state in kind.terminal and committed_history and path.resolve() not in changed:
            continue
        out.append((state, path))
    return out


# ---------------------------------------------------------------- new
def _create(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def new_cr(root: Path, area: str, title: str, text_of) -> Path:
    """Create open/<AREA>-<NNN>-<slug>.md with the next free number. text_of(id) gives the text."""
    fmt = CR.fmt
    with root_lock(root):
        item_id = fmt.next_id(root, area, history_high(root, area))
        _pause("new")
        path = root / "open" / f"{item_id}-{fmt.slug(title)}.md"
        _create(path, text_of(item_id))
    return path


def new_decide(root: Path, text_of, today: dt.date | None = None) -> Path:
    """Create open/D-<YYYYMMDD>-<NN>.md with the next free number of the day."""
    day = f"{(today or dt.date.today()):%Y%m%d}"
    pattern = re.compile(rf"^D-{day}-(\d+)\b")
    with root_lock(root):
        high = 0
        for _, path in all_files(DECIDE, root):
            m = pattern.match(path.name)
            if m:
                high = max(high, int(m.group(1)))
        item_id = f"D-{day}-{high + 1:02d}"
        _pause("new")
        path = root / "open" / f"{item_id}.md"
        _create(path, text_of(item_id))
    return path


def answer_decide(root: Path, item_id: str, answer: str, *, by: str = "user") -> Path:
    """Record one answer and move open/ to answered/ under the same decision-root lock.

    The answer is a JSON string in the file header, so newlines and Markdown headings survive
    without creating a second item store. Notification is the caller's next step.
    """
    if not isinstance(answer, str):
        raise ItemError("answer_invalid", "The decision answer must be text.")
    if not answer.strip():
        raise ItemError("answer_empty", "The decision answer is empty.")
    if "\x00" in answer:
        raise ItemError("answer_invalid", "The decision answer contains a NUL byte.")
    if len(answer.encode("utf-8")) > MAX_DECISION_ANSWER_BYTES:
        raise ItemError("answer_too_large", f"Keep the answer within {MAX_DECISION_ANSWER_BYTES} bytes.")
    with root_lock(root):
        state, source = find(DECIDE, root, item_id)
        if state != "open":
            raise ItemError("decide_not_open", f"{item_id} is {state}; only open decisions accept answers.")
        text = set_header(source.read_text(encoding="utf-8"), "Answer", json.dumps(answer, ensure_ascii=False))
        day = dt.date.today().isoformat()
        text = add_disposition(text, f"{day} {by}: open -> answered. 답변을 접수했습니다.", DECIDE.sections)
        return _relocate(DECIDE, root, item_id, state, source, "answered", text)


# ---------------------------------------------------------------- move
_HEADER_LINE = re.compile(r"^-\s+([A-Z][A-Za-z ]*?):")


def _header_end(lines: list[str]) -> int:
    """Index after the header block (title, then '- Key: value' lines and blank lines)."""
    i = 1
    while i < len(lines) and (lines[i].strip() == "" or _HEADER_LINE.match(lines[i])):
        i += 1
    while i > 1 and lines[i - 1].strip() == "":
        i -= 1
    return i


def set_header(text: str, key: str, value: str | None) -> str:
    """Write the '- <key>: <value>' header at the end of the header block (None removes it)."""
    lines = text.splitlines()
    end = _header_end(lines)
    kept = [n for n in range(1, end) if not re.match(rf"^-\s+{re.escape(key)}:", lines[n])]
    head = [lines[0]] + [lines[n] for n in kept]
    if value is not None:
        head.append(f"- {key}: {value}")
    return "\n".join(head + lines[end:]) + "\n"


def set_outcome(text: str, outcome: str | None) -> str:
    """Write the Outcome header (None removes it)."""
    return set_header(text, "Outcome", outcome)


def add_disposition(text: str, entry: str, order: tuple[str, ...]) -> str:
    """Append one entry to '## Disposition', creating the section at its place in the order."""
    lines = text.rstrip("\n").splitlines()
    heads = section_heads(lines)
    for n, name in heads:
        if name == "Disposition":
            end = next((m for m, _ in heads if m > n), len(lines))
            while end > n + 1 and lines[end - 1].strip() == "":
                end -= 1
            lines[end:end] = [f"- {entry}"]
            return "\n".join(lines) + "\n"
    later = set(order[order.index("Disposition") + 1:])
    at = next((n for n, name in heads if name in later), len(lines))
    block = ["## Disposition", "", f"- {entry}", ""]
    if at == len(lines):
        block = [""] + block[:-1]
    lines[at:at] = block
    return "\n".join(lines) + "\n"


def record(kind: Kind, root: Path, item_id: str, entry: str) -> Path:
    """Append one Disposition entry to an item in place. Nothing changes on a refusal."""
    with root_lock(root):
        state, path = find(kind, root, item_id)
        text = add_disposition(path.read_text(encoding="utf-8"), entry, kind.sections)
        bad = kind.fmt.check(kind.fmt.parse_text(text, path, state))
        if bad:
            raise ItemError("format_invalid", f"{item_id} does not meet {state}/: " + "; ".join(bad))
        path.write_text(text, encoding="utf-8")
    return path


def _outcome_kind(outcome: str | None) -> str:
    return outcome.split()[0] if outcome else ""


def _in_index(root: Path, path: Path) -> bool:
    return _git(root, "ls-files", "--error-unmatch", "--", str(path)).returncode == 0


def _roll_back(root: Path, source: Path, target: Path, original: str, created: list[Path],
               tracked: bool) -> list[str]:
    """Undo a failed move: bring the file back from the target (git mv can rename the work tree
    file and then fail to write the index), restore the text, remove new directories. The index
    is not written here. Return what is still not as before (empty = fully undone)."""
    with contextlib.suppress(OSError):
        if not source.exists() and target.exists():
            os.rename(target, source)
    with contextlib.suppress(OSError):
        if source.exists():
            source.write_text(original, encoding="utf-8")
    for directory in sorted(created, key=lambda d: len(d.parts), reverse=True):
        with contextlib.suppress(OSError):
            directory.rmdir()
    left = []
    if not source.exists():
        left.append(f"{source} is missing")
    elif source.read_text(encoding="utf-8") != original:
        left.append(f"{source} has changed text")
    if target.exists():
        left.append(f"{target} exists")
    if tracked:
        if not _in_index(root, source):
            left.append(f"the index has no {source}")
        if _in_index(root, target):
            left.append(f"the index has {target}")
    return left


def move(kind: Kind, root: Path, item_id: str, state: str, outcome: str | None = None,
         by: str | None = None, note: str | None = None, today: dt.date | None = None) -> Path:
    """Check the transition and the destination format, then move the file. Nothing changes on
    a refusal. A tracked file moves with `git mv`; the tool never commits."""
    with root_lock(root):
        return move_locked(kind, root, item_id, state, outcome, by, note, today)


def move_locked(kind: Kind, root: Path, item_id: str, state: str, outcome: str | None = None,
                by: str | None = None, note: str | None = None, today: dt.date | None = None) -> Path:
    """`move` for a caller that already holds root_lock(root). The lock is not reentrant."""
    if state not in kind.states:
        raise ItemError("invalid_state", f"{kind.name} states are {', '.join(kind.states)}.")
    if (outcome or note) and not by:
        raise ItemError("decider_missing", "--outcome and --note need --by (the decider).")
    if state == "open" and not (by and note):
        raise ItemError("reason_missing", "A move back to open needs --by and --note for Disposition.")
    if state == "open" and outcome:
        raise ItemError("invalid_outcome", "open/ has no Outcome.")
    source_state, source = find(kind, root, item_id)
    if state == source_state or state not in kind.transitions[source_state]:
        raise ItemError("invalid_transition",
                        f"{kind.name} {item_id}: {source_state} -> {state} is not allowed.")
    text = source.read_text(encoding="utf-8")
    if kind is DECIDE and state == "done" and source_state == "open" and _outcome_kind(outcome) == "decided":
        raise ItemError("invalid_transition", "Record the answer before confirming a decided decision.")
    if kind is DECIDE and state == "done" and source_state == "answered":
        answer = kind.fmt.answer_text(kind.fmt.parse_text(text, source, source_state))
        if answer is None:
            raise ItemError("format_invalid", f"{item_id} has no recorded answer.")
        original = f"사용자 답변 원문: {json.dumps(answer, ensure_ascii=False)}"
        note = f"{note} {original}" if note else original
    if kind is DECIDE and state == "open" and source_state == "answered":
        answer = kind.fmt.answer_text(kind.fmt.parse_text(text, source, source_state))
        if answer is None:
            raise ItemError("format_invalid", f"{item_id} has no recorded answer.")
        note = f"{note} 이전 답변 원문: {json.dumps(answer, ensure_ascii=False)}"
    if kind is DECIDE and state == "open":
        text = set_header(text, "Answer", None)
    current = kind.fmt.parse_text(text, source, source_state).headers.get("Outcome")
    new_outcome = None if state in ("open", "todo", "in-progress") else (outcome or current)
    if outcome and new_outcome is None:
        raise ItemError("invalid_outcome", f"{state}/ has no Outcome.")
    allowed = kind.outcomes.get(state)
    if allowed is not None and _outcome_kind(new_outcome) not in allowed:
        raise ItemError("invalid_outcome", f"{kind.name} {state}/ takes Outcome "
                        + " | ".join(allowed) + f", not '{new_outcome}'.")
    if kind is CR and _outcome_kind(new_outcome) == "fixed" and source_state not in ("todo", "in-progress"):
        raise ItemError("invalid_transition", "A fixed CR reaches done only from todo or in-progress.")
    if new_outcome != current:
        text = set_header(text, "Outcome", new_outcome)
    if by:
        day = (today or dt.date.today()).isoformat()
        verdict = f"{source_state} -> {state}" + (f", Outcome {outcome}" if outcome else "")
        text = add_disposition(text, f"{day} {by}: {verdict}." + (f" {note}" if note else ""),
                               kind.sections)
    return _relocate(kind, root, item_id, source_state, source, state, text)


def _relocate(kind: Kind, root: Path, item_id: str, source_state: str, source: Path, state: str,
              text: str) -> Path:
    """Write `text` and move the file to `state`, after the destination format check. On a
    failure the text, path and index are restored, or move_partial names what is left."""
    target = root / state / source.relative_to(root / source_state)
    bad = kind.fmt.check(kind.fmt.parse_text(text, target, state))
    if bad:
        raise ItemError("format_invalid", f"{item_id} does not meet {state}/: " + "; ".join(bad))
    if target.exists():
        raise ItemError("target_exists", f"{target} already exists.")
    _pause("move")
    tracked = in_git(root) and _in_index(root, source)
    created = [d for d in [target.parent, *target.parent.parents] if not d.exists() and root in d.parents]
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ItemError("move_failed", f"Cannot create {target.parent}: {error}") from error
    original = source.read_text(encoding="utf-8")
    try:
        source.write_text(text, encoding="utf-8")
        if tracked:
            result = _git(root, "mv", "--", str(source), str(target))
            if result.returncode != 0:
                raise ItemError("git_mv_failed", result.stderr.strip())
        else:
            try:
                os.rename(source, target)
            except OSError as error:
                raise ItemError("move_failed", str(error)) from error
    except BaseException as failure:
        left = _roll_back(root, source, target, original, created, tracked)
        if left:
            raise ItemError("move_partial", f"{item_id}: the move failed ({failure}) and could not "
                            "be undone. Left: " + "; ".join(left)) from failure
        raise
    return target
