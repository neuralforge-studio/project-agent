"""The public interface of project-item. Another tool and a tmux script import project-item
only through this module; every other module of the package is internal.

Each name below is owned by the module it comes from (the format modules `cr` and `decide`,
`kinds`, `store`, `read`, `assign`, `registry`, `render`). This module only lists what a
consumer may use, so the boundary is one list. tests/test_api_boundary.py checks the consumers.
"""
from __future__ import annotations

import re

from . import cr as _cr
from .assign import claim, lookup, lookup_locked, set_base, unclaim
from .cr import outcome_kind, submitted_hash
from .decide import MAX_ANSWER_BYTES, decision_stage
from .errors import ItemError
from .kinds import CR, DECIDE
from .read import cr_states, sections, text_sections
from .registry import item_root, projects
from .render import render as render_decision_page
from .store import answer_decide, file_id, item_files, root_lock

# The CR ID format, also the JOB ID format of agent-session.
JOB_ID = re.compile(_cr.ID_RE)

__all__ = [
    "CR", "DECIDE", "ItemError", "JOB_ID",
    "projects", "item_root", "root_lock", "item_files", "file_id",
    "sections", "text_sections", "cr_states", "decision_stage", "submitted_hash", "outcome_kind",
    "answer_decide", "MAX_ANSWER_BYTES", "render_decision_page",
    "lookup", "lookup_locked", "claim", "unclaim", "set_base",
]
