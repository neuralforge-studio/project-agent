"""Which installed release of project-agent a Board process belongs to (BOARD-028).

The identity of a release is the name of its directory, `releases/<version>-<hash>`: the installer makes it from
`VERSION` and the commit (docs/project-team/install-contract.md, "release의 식별"). A process knows its own release
from where its code is: `<lib>/releases/<name>/tools/project-board` with a symlink `<lib>/current`. Code that is not in
such a place (a development checkout) belongs to no release and its name is ''. The Rust sidebar reads its own
binary's place by the same rule (`rust/src/release.rs`, which also compares it with `current`); `test_rust_release.py`
holds the two equal.
"""
from __future__ import annotations

from pathlib import Path


def name_of(tool: Path) -> str:
    """The release of the `tools/project-board` directory `tool` (resolved), or '' outside an installed release."""
    if tool.name != "project-board" or tool.parent.name != "tools":
        return ""
    release = tool.parent.parent
    releases = release.parent
    if releases.name != "releases" or not (releases.parent / "current").is_symlink():
        return ""
    return release.name
