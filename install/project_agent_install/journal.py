"""Running a plan so that no interruption leaves the HOME in an undefined state (contract section 2, rule 5).

Before the first change the plan's undo (install, upgrade, rollback) or redo (uninstall) specs are written to
a journal file. The journal lives in the nearest directory of the library path that exists before the run
(the library itself for every command but the first install), so that the next command can always find it.
A failure or a SIGINT/SIGTERM/SIGHUP undoes the run at once; SIGKILL or a power loss leaves the journal, and
the next command undoes the run (or, for uninstall, finishes it) before doing anything else.
"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal

from . import actions, paths
from .layout import InstallerError

NAME = ".project-agent-install-journal.json"
FORMAT = 1
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


def _write(journal):
    document = {"format": FORMAT, "command": journal.command, "mode": journal.mode, "specs": journal.specs}
    temporary = journal.path.parent / (journal.path.name + ".tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            view = memoryview(json.dumps(document).encode())
            while view:                     # the journal does not go through actions.raw_write (tests inject there)
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, journal.path)
    except BaseException:
        actions._unlink(temporary)
        raise
    directory = os.open(journal.path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def read(env, path):
    """The journal at `path`, with every path checked to be the installer's. Anything else is refused."""
    try:
        document = json.loads(Path(path).read_text())
        ok = (isinstance(document, dict) and document["format"] == FORMAT and document["mode"] in ("undo", "redo")
              and isinstance(document["command"], str) and isinstance(document["specs"], list))
    except (OSError, ValueError, KeyError):
        ok = False
    if not ok:
        raise InstallerError("journal_invalid", "The interrupted-run journal cannot be read. Preserve it.",
                             {"path": env.display(path)})
    for spec in document["specs"]:
        if not isinstance(spec, dict):
            raise InstallerError("journal_invalid", "The interrupted-run journal has an invalid entry.",
                                 {"path": env.display(path)})
        paths.check_spec(env, spec)
    return actions.Journal(Path(path), document["command"], document["mode"], document["specs"])


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
    """Undo an interrupted install, upgrade or rollback: the undo specs in reverse order. Returns the
    failures; the journal is removed only when there are none."""
    failures = []
    with uninterruptible():
        for spec in reversed(journal.specs):
            try:
                actions.apply_spec(spec)
            except OSError as error:
                failures.append("%s: %s" % (spec.get("path"), error))
        if not failures:
            actions._unlink(journal.path)
    return failures


def resume(env, journal):
    """Finish an interrupted uninstall: replay its removals (each tolerates what is already gone)."""
    with uninterruptible():
        for spec in journal.specs:
            actions.apply_spec(spec)
        actions._unlink(journal.path)


def execute(env, plan):
    """Write the journal, apply the steps in order, and drop the journal. On a failure or a signal an
    undoable run is undone; an uninstall is not undone and keeps its journal for the next `uninstall`."""
    if not plan.steps:
        return
    mode = "redo" if any(step.redo for step in plan.steps) else "undo"
    specs = [(step.redo if mode == "redo" else step.undo) for step in plan.steps]
    journal = actions.Journal(plan.journal_path or path_for(env), plan.command, mode,
                              [spec for spec in specs if spec])
    try:
        _write(journal)
    except OSError as error:
        raise InstallerError("journal_unwritable", "Cannot write the interrupted-run journal (%s). Nothing was "
                             "changed." % error, {}, exit_code=4) from error
    index = 0
    try:
        with interrupts():
            for index, step in enumerate(plan.steps):
                actions.checkpoint("before", index)
                step.do()
                actions.checkpoint("after", index)
    except BaseException as error:
        what = ("interrupted by signal %d" % error.number) if isinstance(error, Interrupted) else str(error)
        if isinstance(error, actions.Changed) and index == 0:
            with uninterruptible():
                actions._unlink(journal.path)               # refused before the first change: nothing to finish
            raise InstallerError("changed_since_plan", "%s refused: %s" % (plan.command, what), {}) from error
        if mode == "undo":
            failures = recover(env, journal)
            outcome = ("The changes made so far were undone." if not failures else
                       "The changes could not all be undone (%s); the next command retries." % "; ".join(failures))
        else:
            outcome = ("Nothing was undone: removals are not undone. The install record is kept; run `uninstall` "
                       "again to finish.")
        if not isinstance(error, (Exception, Interrupted)):
            raise
        raise InstallerError("interrupted" if isinstance(error, Interrupted) else "command_failed",
                             "%s stopped: %s. %s" % (plan.command, what, outcome), {}, exit_code=4) from error
    actions._unlink(journal.path)
