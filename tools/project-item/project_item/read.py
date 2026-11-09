"""Domain reads of item files: the sections of an item, the decisions of a root and the
directory state of each CR. No output format and no write happens here."""
from __future__ import annotations

from pathlib import Path

from . import store
from .cr import section_heads
from .kinds import CR, DECIDE


def sections(path: Path) -> list[tuple[str, str]]:
    """(name, body) of each '## <name>' section of an item file, in file order."""
    return text_sections(path.read_text(encoding="utf-8"))


def text_sections(text: str) -> list[tuple[str, str]]:
    """`sections` of text already read, so that a reader that also parses the header reads the file once."""
    lines = text.splitlines()
    heads = section_heads(lines)
    out = []
    for index, (start, name) in enumerate(heads):
        end = heads[index + 1][0] if index + 1 < len(heads) else len(lines)
        out.append((name, "\n".join(lines[start + 1:end]).strip()))
    return out


def load(root: Path) -> list[dict]:
    """The decisions of a root as dicts with id, title, state, headers and sections."""
    items = []
    for state in DECIDE.states:
        for path in store.item_files(DECIDE, root, state):
            parsed = DECIDE.fmt.parse(path, state)
            items.append({"id": parsed.item_id or path.stem, "title": parsed.title or path.stem,
                          "state": state, "headers": parsed.headers, "sections": sections(path)})
    return items


def cr_states(root: Path | None) -> dict[str, str]:
    """Map CR/JOB IDs to their source directory states for derived decision progress."""
    if root is None:
        return {}
    return {store.file_id(CR, path): state for state, path in store.all_files(CR, root)
            if store.file_id(CR, path)}
