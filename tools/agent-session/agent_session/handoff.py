"""A slot's handoff file: where it lives, whether this run wrote it, and its validated path.

Dependency direction: `lifecycle` imports this module; this module never imports `lifecycle`. A restart
needs a handoff written during the run being replaced. Freshness is judged against that run's
`launch.sh`, so this module reads the run directory through `launch_artifacts.run_directory`.
"""

from pathlib import Path

from .errors import SessionError
from .launch_artifacts import run_directory


def path(project, meta):
    return project.runtime_path / "handoff" / f"{meta['target']}.md"


def fresh(project, meta, timeout):
    """The slot's handoff file when it changed after this run's launch, else None.

    A remote seat writes its handoff on its own host; a fresh one is copied to the central path first."""
    if meta.get("remote_seat"):
        from .remote import run_call
        handoff = run_call(meta, "handoff", timeout=timeout)
        if handoff.get("fresh"):
            central = path(project, meta)
            central.parent.mkdir(parents=True, exist_ok=True)
            central.write_text(handoff["text"], encoding="utf-8")
            return str(central)
        return None
    handoff = path(project, meta)
    launched = run_directory(project, meta["run_id"]) / "launch.sh"
    if handoff.is_file() and launched.is_file() and handoff.stat().st_mtime > launched.stat().st_mtime:
        return str(handoff)
    return None


def require(project, meta, timeout):
    """The fresh handoff file, or `handoff_required` naming the path to write."""
    found = fresh(project, meta, timeout)
    if found is None:
        raise SessionError("handoff_required", "Write the slot's handoff file during this run before restart.",
                           3, {"path": str(path(project, meta)), "run_id": meta["run_id"]})
    return found


def existing_file(value):
    """The absolute path of a handoff document, from a path or a result that names one; None for no handoff."""
    if isinstance(value, dict):
        value = value.get("handoff_file") or value.get("path")
    if value is None:
        return None
    resolved = Path(value).resolve()
    if not resolved.is_file():
        raise SessionError("handoff_missing", "The project handoff document is unavailable.")
    return str(resolved)
