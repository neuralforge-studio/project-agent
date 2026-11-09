"""project-item <command>  --  CR and decision items of a registered project.

Rules: skills/project-item/SKILL.md. Run `project-item -h` for the commands.
"""
from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
