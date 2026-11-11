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

from .cr import add_disposition, outcome_kind, set_header
from .errors import ItemError
from .kinds import CR, DECIDE, Kind


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


_NUMBER_RE = re.compile(r"^([A-Z][A-Z0-9]*)-(\d+)\b")
_CACHE_VERSION = 1
_OBJECT_ID_RE = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")


def number_cache_path(root: Path) -> Path:
    return lock_path(root).parent.parent / "numbers" / lock_path(root).with_suffix(".json").name


def _history_tips(root: Path) -> list[str] | None:
    """Sorted commit IDs at the ends of every ref and HEAD (what `git log --all` starts from)."""
    refs = _git(root, "for-each-ref", "--format=%(objecttype) %(objectname)")
    if refs.returncode != 0:
        return None
    tips = {line.split()[1] for line in refs.stdout.splitlines() if line.split()[:1] in (["commit"], ["tag"])}
    head = _git(root, "rev-parse", "--verify", "-q", "HEAD^{commit}")
    if head.returncode == 0 and head.stdout.strip():
        tips.add(head.stdout.strip())
    return sorted(tips)


def _history_numbers(root: Path, tips: list[str] | None, known: list[str]) -> dict[str, int] | None:
    """Highest number per AREA among state-directory files that changed in the commits reachable
    from `tips` and not from `known` (every ref when `tips` is None). None when git cannot read them."""
    revs = "".join(f"{tip}\n" for tip in tips or []) + "".join(f"^{tip}\n" for tip in known)
    args = ["--stdin"] if tips is not None else ["--all"]
    out = subprocess.run(["git", "-C", str(root), "log", *args, "--name-only", "--format=", "-z",
                          "--relative", "--", "."], input=revs.encode(), capture_output=True)
    if out.returncode != 0:
        return None
    high: dict[str, int] = {}
    for name in out.stdout.decode("utf-8", "surrogateescape").split("\0"):
        parts = Path(name.strip("\n")).parts
        if len(parts) > 1 and parts[0] in CR.states:
            m = _NUMBER_RE.match(parts[-1])
            if m:
                high[m.group(1)] = max(high.get(m.group(1), 0), int(m.group(2)))
    return high


def _read_number_cache(root: Path) -> tuple[list[str], dict[str, int]] | None:
    try:
        data = json.loads(number_cache_path(root).read_text(encoding="utf-8"))
        tips, high = data["tips"], data["high"]
        if (data["version"] != _CACHE_VERSION or data["root"] != str(root.resolve())
                or not isinstance(tips, list) or not isinstance(high, dict)
                or not all(isinstance(t, str) and _OBJECT_ID_RE.fullmatch(t) for t in tips)
                or not all(isinstance(k, str) and type(v) is int and v >= 0 for k, v in high.items())):
            return None
        return tips, high
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_number_cache(root: Path, tips: list[str], high: dict[str, int]) -> None:
    """Atomic replace; the caller holds root_lock(root). A cache that cannot be written is skipped."""
    path = number_cache_path(root)
    data = {"version": _CACHE_VERSION, "root": str(root.resolve()), "tips": tips, "high": high}
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()


def history_high(root: Path, area: str) -> int:
    """Highest <AREA>-<NNN> number named by any state-directory file in the git history of the root,
    removed files included (a number is not reused). Other directories are not read. 0 outside git.

    The caller holds root_lock(root). The result of earlier reads is cached per root with the commits
    it covers; a call reads only the commits that are new since. No usable cache means a full read."""
    if not in_git(root):
        return 0
    tips = _history_tips(root)
    if tips is None:                                    # refs unreadable: read as before, remember nothing
        return (_history_numbers(root, None, []) or {}).get(area, 0)
    cached = _read_number_cache(root)
    if cached and cached[0] == tips:
        return cached[1].get(area, 0)
    new = _history_numbers(root, tips, cached[0]) if cached else None
    if new is None:                                     # no usable cache, or its commits are gone
        high = _history_numbers(root, tips, [])
    else:
        high = {a: max(cached[1].get(a, 0), new.get(a, 0)) for a in cached[1].keys() | new.keys()}
    if high is None:                                    # e.g. a ref that is not a commit
        return (_history_numbers(root, None, []) or {}).get(area, 0)
    _write_number_cache(root, tips, high)
    return high.get(area, 0)


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
    DECIDE.fmt.check_answer(answer)
    with root_lock(root):
        state, source = find(DECIDE, root, item_id)
        if state != "open":
            raise ItemError("decide_not_open", f"{item_id} is {state}; only open decisions accept answers.")
        text = set_header(source.read_text(encoding="utf-8"), "Answer", DECIDE.fmt.answer_json(answer))
        day = dt.date.today().isoformat()
        text = add_disposition(text, f"{day} {by}: open -> answered. 답변을 접수했습니다.", DECIDE.sections)
        return _relocate(DECIDE, root, item_id, state, source, "answered", text)


# ---------------------------------------------------------------- move
def set_outcome(text: str, outcome: str | None) -> str:
    """Write the Outcome header (None removes it)."""
    return set_header(text, "Outcome", outcome)


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
    text, note = kind.fmt.prepare_move(item_id, source.read_text(encoding="utf-8"), source, source_state,
                                       state, outcome, note)
    current = kind.fmt.parse_text(text, source, source_state).headers.get("Outcome")
    new_outcome = None if state in ("open", "todo", "in-progress") else (outcome or current)
    if outcome and new_outcome is None:
        raise ItemError("invalid_outcome", f"{state}/ has no Outcome.")
    allowed = kind.outcomes.get(state)
    if allowed is not None and outcome_kind(new_outcome) not in allowed:
        raise ItemError("invalid_outcome", f"{kind.name} {state}/ takes Outcome "
                        + " | ".join(allowed) + f", not '{new_outcome}'.")
    kind.fmt.check_outcome(source_state, new_outcome)
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
