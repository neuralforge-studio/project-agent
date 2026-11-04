"""Item kinds: states, transitions and the format module of each kind.

The rules are owned by codex/skills/project-item/SKILL.md ("상태와 전이"). Keep the tables
below in step with it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from types import ModuleType

from . import cr, decide


@dataclass(frozen=True)
class Kind:
    name: str
    fmt: ModuleType
    states: tuple[str, ...]
    terminal: tuple[str, ...]          # states whose committed files are history
    listed: tuple[str, ...]            # default states of `ls`
    transitions: dict[str, frozenset[str]]
    id_re: re.Pattern
    sections: tuple[str, ...]          # known sections in their order
    outcomes: dict[str, tuple[str, ...]]   # Outcome kinds that a move may give per destination

    def item_id(self, item) -> str | None:
        return item.cr_id if self.name == "cr" else item.item_id


CR = Kind(
    name="cr", fmt=cr, states=cr.STATES, terminal=("done", "deferred"),
    listed=("open", "todo", "in-progress", "deferred"),
    transitions={"open": frozenset({"todo", "done", "deferred"}),
                 "todo": frozenset({"open", "done", "deferred", "in-progress"}),
                 "in-progress": frozenset({"done", "todo", "open", "deferred"}),
                 "done": frozenset({"open"}), "deferred": frozenset({"open"})},
    id_re=re.compile(rf"^({cr.ID_RE})\b"), sections=cr.SECTION_ORDER,
    outcomes={"done": ("fixed", "waived", "merged"), "deferred": ("moved",)})

DECIDE = Kind(
    name="decide", fmt=decide, states=decide.STATES, terminal=("done",), listed=("open",),
    transitions={"open": frozenset({"done"}), "done": frozenset({"open"})},
    id_re=re.compile(rf"^({decide.ID_RE})\b"), sections=decide.SECTION_ORDER,
    outcomes={"done": ("decided", "withdrawn", "merged")})

KINDS = {"cr": CR, "decide": DECIDE}
DECIDE_ID = re.compile(rf"^{decide.ID_RE}$")


def kind_of_id(item_id: str) -> Kind:
    return DECIDE if DECIDE_ID.match(item_id) else CR
