"""The steps of a plan. A step names one change and applies it; `dry-run` prints the same list.

A step that creates or replaces something registers how to undo it in the `Journal`. When a later
step fails, `Journal.rollback()` returns the disk to its state before the command (contract section 2,
rule 5). Removing steps (uninstall) are not undone: the record is deleted last, so a second run finishes.
"""

import compileall
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
from typing import Callable


class Journal:
    def __init__(self):
        self.undo = []

    def push(self, function):
        self.undo.append(function)

    def rollback(self):
        failures = []
        for function in reversed(self.undo):
            try:
                function()
            except OSError as error:
                failures.append(str(error))
        self.undo = []
        return failures


@dataclass
class Step:
    action: str          # create | replace | modify | remove
    path: Path
    kind: str            # dir | file | symlink | tree | block
    detail: str
    run: Callable[[Journal], None]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def mkdir(path):
    def run(journal):
        os.mkdir(path)
        journal.push(lambda: os.rmdir(path))
    return Step("create", path, "dir", "", run)


def write_file(path, data, detail=""):
    """Create a new file; an existing path is an error."""
    def run(journal):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        journal.push(lambda: os.unlink(path))
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
    return Step("create", path, "file", detail, run)


def symlink(path, target):
    def run(journal):
        os.symlink(target, path)
        journal.push(lambda: os.unlink(path))
    return Step("create", path, "symlink", "-> " + str(target), run)


def _swap(path, target):
    temporary = path.parent / (".%s.tmp-%d" % (path.name, os.getpid()))
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
    os.symlink(target, temporary)
    try:
        os.replace(temporary, path)
    except BaseException:
        os.unlink(temporary)
        raise


def swap_symlink(path, target, detail=""):
    """Point an existing symlink at a new target in one atomic rename: a reader never sees it missing."""
    def run(journal):
        previous = os.readlink(path)
        _swap(path, target)
        journal.push(lambda: _swap(path, previous))
    return Step("replace", path, "symlink", detail or "-> " + str(target), run)


def replace_file(path, data):
    """Write a file through a temporary file in the same directory and an atomic rename."""
    def run(journal):
        try:
            previous = path.read_bytes()
        except FileNotFoundError:
            previous = None
        _write_atomic(path, data)
        journal.push((lambda: os.unlink(path)) if previous is None else (lambda: _write_atomic(path, previous)))
    return Step("replace" if os.path.lexists(path) else "create", path, "file", "", run)


def _write_atomic(path, data):
    temporary = path.parent / (".%s.tmp-%d" % (path.name, os.getpid()))
    with open(temporary, "wb") as stream:
        stream.write(data)
    os.replace(temporary, path)


def force_rmtree(path):
    """Remove a release (or any tree) whose directories were made read-only."""
    for directory, names, _ in os.walk(path):
        os.chmod(directory, 0o755)
    shutil.rmtree(path, ignore_errors=True)


def _freeze(root):
    """Remove every write bit: a release does not change after it is made (nothing may add `__pycache__`)."""
    for directory, names, files in os.walk(root, topdown=False):
        for name in files:
            entry = os.path.join(directory, name)
            if not os.path.islink(entry):
                os.chmod(entry, os.stat(entry).st_mode & ~0o222)
        os.chmod(directory, os.stat(directory).st_mode & ~0o222)


def build_release(destination, files, source_root, extra):
    """Copy `files` (relative paths of the source tree) into a new release directory, precompile it for the
    installing interpreter, make it read-only, then rename it into place, so that the directory appears only
    when complete. `extra` maps a release-relative path to the bytes written after the copy."""
    def run(journal):
        temporary = destination.parent / (".tmp-%s-%d" % (destination.name, os.getpid()))
        if temporary.exists():
            force_rmtree(temporary)
        try:
            for relative in files:
                source = source_root / relative
                target = temporary / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_symlink():
                    os.symlink(os.readlink(source), target)
                else:
                    shutil.copy2(source, target)
            for relative, data in extra.items():
                target = temporary / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            compileall.compile_dir(str(temporary), quiet=2, force=True, stripdir=str(temporary),
                                   prependdir=str(destination))         # tracebacks name the final path
            _freeze(temporary)
            os.rename(temporary, destination)
        except BaseException:
            force_rmtree(temporary)
            raise
        journal.push(lambda: force_rmtree(destination))
    return Step("create", destination, "tree", "%d files" % (len(files) + len(extra)), run)


def append_block(path, block):
    """Append the managed block to the user's tmux file in place (inode, mode and owner stay)."""
    def run(journal):
        info = os.lstat(path)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        try:
            os.write(fd, block)
        finally:
            os.close(fd)

        def undo():
            descriptor = os.open(path, os.O_WRONLY | os.O_NOFOLLOW)
            try:
                os.ftruncate(descriptor, info.st_size)
            finally:
                os.close(descriptor)
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns), follow_symlinks=False)
        journal.push(undo)
    return Step("modify", path, "block", "append the managed block", run)


def remove_block(path, block, delete_if_empty):
    """Cut the exact block (with its leading newline) out of the file; nothing else changes. A file that
    the installer created and that holds nothing else is deleted (the step then reports `remove`)."""
    delete = delete_if_empty and path.read_bytes() == block

    def run(journal):
        data = path.read_bytes()
        at = data.find(block)
        if at < 0:
            return
        rest = data[:at] + data[at + len(block):]
        if delete and not rest:
            os.unlink(path)
        else:
            fd = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
            try:
                os.write(fd, rest)
            finally:
                os.close(fd)
    return Step("remove" if delete else "modify", path, "file" if delete else "block",
                "" if delete else "remove the managed block", run)


def remove_path(path, kind):
    def run(journal):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
    return Step("remove", path, kind, "", run)


def remove_tree(path):
    def run(journal):
        force_rmtree(path)
    return Step("remove", path, "tree", "", run)


def remove_dir(path):
    def run(journal):
        try:
            os.rmdir(path)
        except OSError:
            pass            # a user's file arrived meanwhile: the directory is not the installer's to empty
    return Step("remove", path, "dir", "", run)
