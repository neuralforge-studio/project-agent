"""Running a plan so that no interruption leaves the HOME in an undefined state (contract section 2, rule 5).

Before the first change the plan's undo (install, upgrade, rollback) or redo (uninstall) specs are written to
a journal file. The journal lives in the nearest directory of the library path that exists before the run
(the library itself for every command but the first install), so that the next command can always find it.
A failure or a SIGINT/SIGTERM/SIGHUP undoes the run at once; SIGKILL or a power loss leaves the journal, and
the next command undoes the run (or, for uninstall, finishes it) before doing anything else.

The journal holds operations, identifiers and fingerprints only (paths.py): the paths come from the installer.
"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal

from . import actions, paths
from .layout import InstallerError

NAME = ".project-agent-install-journal.json"
FORMAT = 2
SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


class Interrupted(BaseException):
    """A signal arrived. It is a BaseException so that no `except Exception` on the way swallows it."""

    def __init__(self, number):
        super().__init__(number)
        self.number = number


def locations(env):
    """The directories that may hold the journal: the library and its ancestors up to the home."""
    return [env.lib, env.lib.parent, env.lib.parent.parent, env.home]


def path_for(env):
    """Where a run that starts now keeps its journal: the first of `locations` that exists."""
    for directory in locations(env):
        if os.path.isdir(directory) and not os.path.islink(directory):
            return directory / NAME
    return env.home / NAME


def find(env):
    for directory in locations(env):
        candidate = directory / NAME
        if os.path.lexists(candidate):
            return candidate
    return None


def clean_temporary(env):
    """A run cut off while it wrote the journal changed nothing; its half-written file is removed."""
    for directory in locations(env):
        temporary = directory / (NAME + ".tmp")
        if os.path.lexists(temporary):
            actions.unlink(temporary)


def _document(journal):
    return {"format": FORMAT, "command": journal.command, "mode": journal.mode, "homes": journal.homes,
            "specs": journal.specs}


def _write(journal):
    """Write the journal through a temporary file and a rename. If any part fails, nothing of it remains."""
    temporary = journal.path.parent / (journal.path.name + ".tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            view = memoryview(json.dumps(_document(journal)).encode())
            while view:                     # the journal does not go through actions.raw_write (tests inject there)
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        actions.temp_created()
        os.replace(temporary, journal.path)
        actions.fsync_dir(journal.path.parent)
    except BaseException:
        actions.unlink(temporary)
        actions.unlink(journal.path)
        raise


def places_of(env, homes):
    try:
        return paths.Places(env, {provider: Path(text) for provider, text in homes.items()})
    except (TypeError, ValueError, AttributeError) as error:
        raise InstallerError("journal_invalid", "The journal's provider homes are not valid.") from error


def read(env, path):
    """The journal at `path`. Everything in it is checked against the installer's own places; anything else
    is refused."""
    try:
        document = json.loads(Path(path).read_text())
        ok = (isinstance(document, dict) and document["format"] == FORMAT and document["mode"] in ("undo", "redo")
              and isinstance(document["command"], str) and isinstance(document["specs"], list)
              and isinstance(document["homes"], dict)
              and all(isinstance(text, str) for text in document["homes"].values()))
    except (OSError, ValueError, KeyError):
        ok = False
    if not ok:
        raise InstallerError("journal_invalid", "The interrupted-run journal cannot be read. Preserve it.",
                             {"path": env.display(path)})
    places = places_of(env, document["homes"])
    for spec in document["specs"]:
        paths.validate_spec(places, spec)
    return actions.Journal(Path(path), document["command"], document["mode"], document["homes"], document["specs"])


@contextmanager
def interrupts():
    """SIGINT, SIGTERM and SIGHUP raise `Interrupted` in the main thread while the steps run."""
    def handler(number, frame):
        raise Interrupted(number)
    saved = {number: signal.signal(number, handler) for number in SIGNALS}
    try:
        yield
    finally:
        for number, previous in saved.items():
            signal.signal(number, previous)


@contextmanager
def uninterruptible():
    saved = {number: signal.signal(number, signal.SIG_IGN) for number in SIGNALS}
    try:
        yield
    finally:
        for number, previous in saved.items():
            signal.signal(number, previous)


def recover(env, journal):
    """Undo an interrupted install, upgrade or rollback: the undo specs in reverse order, each only on what is
    in the state the installer made it. Returns (failures, notes); the journal is removed only without failures."""
    ctx = actions.Context(places_of(env, journal.homes), journal.path, strict=False)
    failures = []
    with uninterruptible():
        for spec in reversed(journal.specs):
            try:
                actions.apply_spec(ctx, spec)
            except (OSError, ValueError, KeyError) as error:
                failures.append("%s: %s" % (spec.get("id", spec["op"]), error))
        if not failures:
            actions.unlink(journal.path)
    return failures, ctx.notes


def resume(env, journal):
    """Finish an interrupted uninstall or prune: replay its removals (each tolerates what is already gone).
    Returns the notes about what was left alone."""
    ctx = actions.Context(places_of(env, journal.homes), journal.path, strict=False)
    with uninterruptible():
        for spec in journal.specs:
            try:
                actions.apply_spec(ctx, spec)
            except (OSError, ValueError, KeyError) as error:
                raise InstallerError("command_failed", "Finishing the interrupted %s failed at %s: %s. The "
                                     "journal is kept; run `%s` again." % (journal.command, spec.get("id", spec["op"]),
                                                                          error, journal.command),
                                     {}, exit_code=4) from error
        actions.unlink(journal.path)
    return ctx.notes


def execute(env, plan):
    """Write the journal, apply the steps in order, and drop the journal. On a failure or a signal an
    undoable run is undone; an uninstall is not undone and keeps its journal for the next `uninstall`.
    Returns the notes about what the run left alone."""
    if not plan.steps:
        return []
    mode = "redo" if any(step.redo for step in plan.steps) else "undo"
    specs = [(step.redo if mode == "redo" else step.undo) for step in plan.steps]
    journal = actions.Journal(plan.journal_path or path_for(env), plan.command, mode,
                              {provider: str(home) for provider, home in plan.places.homes.items()},
                              [spec for spec in specs if spec])
    try:
        _write(journal)
    except OSError as error:
        raise InstallerError("journal_unwritable", "Cannot write the interrupted-run journal (%s). Nothing was "
                             "changed." % error, {}, exit_code=4) from error
    ctx = actions.Context(plan.places, journal.path, strict=True)
    index = 0
    try:
        with interrupts():
            for index, step in enumerate(plan.steps):
                actions.checkpoint("before", index)
                step.run(ctx)
                actions.checkpoint("after", index)
    except BaseException as error:
        what = ("interrupted by signal %d" % error.number) if isinstance(error, Interrupted) else str(error)
        if isinstance(error, actions.Changed) and index == 0:
            with uninterruptible():
                actions.unlink(journal.path)               # refused before the first change: nothing to finish
            raise InstallerError("changed_since_plan", "%s refused: %s" % (plan.command, what), {}) from error
        notes = []
        if mode == "undo":
            failures, notes = recover(env, journal)
            outcome = ("The changes made so far were undone." if not failures else
                       "The changes could not all be undone (%s); the next command retries." % "; ".join(failures))
        else:
            outcome = ("Nothing was undone: removals are not undone. The install record is kept; run `%s` "
                       "again to finish." % plan.command)
        if not isinstance(error, (Exception, Interrupted)):
            raise
        raise InstallerError("interrupted" if isinstance(error, Interrupted) else "command_failed",
                             "%s stopped: %s. %s%s" % (plan.command, what, outcome,
                                                       "".join(" " + note for note in notes)),
                             {}, exit_code=4) from error
    actions.unlink(journal.path)
    return ctx.notes
