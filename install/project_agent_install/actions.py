"""The steps of a plan, and the operations they are made of.

A step names one change (`dry-run` prints the same list) and carries a declarative spec that survives a
crash:

* `undo` (install, upgrade, rollback): what restores the state before the step. It is computed at plan
  time and written to the journal before the first change, so it is safe to run whether the step ran,
  ran half, or never ran. A failure, a signal, or the next command after a crash runs the undo specs in
  reverse order.
* `redo` (uninstall): the removal itself. Removing is not undone; the journal lets the next `uninstall`
  finish the work. Every redo operation tolerates what an earlier run already removed.

Every write goes through `raw_write`, `raw_pwrite` and `raw_ftruncate`, which loop over short writes and let
the tests inject failures. `checkpoint` is called around each step and does nothing; the tests replace it
to stop the process at a step boundary.
"""

import base64
import compileall
from dataclasses import dataclass, field
import errno
import hashlib
import os
from pathlib import Path
import shutil
from typing import Callable


def checkpoint(position, index):
    """Called before ("before") and after ("after") step `index`. The tests replace it."""


def raw_write(fd, data):
    return os.write(fd, data)


def raw_pwrite(fd, data, offset):
    return os.pwrite(fd, data, offset)


def raw_ftruncate(fd, size):
    os.ftruncate(fd, size)


def write_all(fd, data, offset=None):
    """Write every byte; a short write continues where it stopped (appending when `offset` is None)."""
    view = memoryview(data)
    position = offset
    while view:
        count = raw_write(fd, view) if offset is None else raw_pwrite(fd, view, position)
        if count <= 0:
            raise OSError(errno.EIO, "a write made no progress")
        view = view[count:]
        if offset is not None:
            position += count


def read_all(fd):
    chunks, offset = [], 0
    while True:
        chunk = os.pread(fd, 1 << 20, offset)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        offset += len(chunk)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def b64(data):
    return base64.b64encode(data).decode("ascii")


class Changed(OSError):
    """A file is not what the plan read: it changed after the plan. Nothing is written to it."""


@dataclass
class Step:
    action: str          # create | replace | modify | remove
    path: Path
    kind: str            # dir | file | symlink | tree | block
    detail: str
    do: Callable[[], None]
    undo: dict = None
    redo: dict = None
    internal: bool = False      # bookkeeping that the plan does not list (the journal itself)


# ---------------------------------------------------------------- operations (also what the journal replays)

def force_rmtree(path):
    """Remove a tree whose directories were made read-only. A failure is raised, not ignored; a symlink is
    never followed or removed here."""
    if os.path.islink(path):
        raise OSError(errno.EPERM, "refusing to remove a symlink as a tree", str(path))
    if not os.path.lexists(path):
        return
    for directory, _, _ in os.walk(path):
        os.chmod(directory, 0o755)
    errors = []
    shutil.rmtree(path, onerror=lambda function, target, info: errors.append("%s: %s" % (target, info[1])))
    if errors:
        raise OSError(errno.EIO, "cannot remove %s (%s)" % (path, "; ".join(errors[:3])))


def _unlink(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _swap(path, target):
    temporary = Path(str(path.parent / (".%s.tmp-%d" % (path.name, os.getpid()))))
    _unlink(temporary)
    os.symlink(target, temporary)
    try:
        os.replace(temporary, path)
    except BaseException:
        _unlink(temporary)
        raise


def _write_atomic(path, data):
    temporary = path.parent / (".%s.tmp-%d" % (path.name, os.getpid()))
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o666)
        try:
            write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, path)
    except BaseException:
        _unlink(temporary)
        raise


def _restore_fd(fd, original, info):
    """Put a file's bytes and times back after a failed rewrite (best effort: it runs while failing)."""
    write_all(fd, original, 0)
    raw_ftruncate(fd, len(original))
    os.utime(fd, ns=(info.st_atime_ns, info.st_mtime_ns))


def _cut_block(spec):
    """Remove the exact block from the user's file. The bytes are read from the open file and must be what the
    plan read; a block at the end is cut by one truncate, otherwise the tail moves up and the file is cut."""
    path = Path(spec["path"])
    block = base64.b64decode(spec["block"])
    try:
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    except FileNotFoundError:
        return              # an earlier run already deleted the file the installer had created
    try:
        info = os.fstat(fd)
        data = read_all(fd)
        at = data.find(block)
        if at < 0:
            return
        if spec.get("expect") and sha256(data) != spec["expect"]:
            raise Changed(errno.EBUSY, "%s changed after the plan; nothing was changed" % path)
        if spec.get("delete_if_empty") and data == block:
            os.unlink(path)
            return
        try:
            if at + len(block) == len(data):
                raw_ftruncate(fd, at)
            else:
                write_all(fd, data[at + len(block):], at)
                raw_ftruncate(fd, len(data) - len(block))
        except BaseException:
            try:
                _restore_fd(fd, data, info)
            except OSError:
                pass
            raise
    finally:
        os.close(fd)


def _untruncate(spec):
    """Undo an append: cut the block back off if (and only if) the file still ends as the append left it."""
    path = Path(spec["path"])
    block = base64.b64decode(spec["block"])
    size = spec["size"]
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return
    try:
        data = read_all(fd)
    finally:
        os.close(fd)
    appended = data[size:]
    if not appended or len(appended) > len(block) or not block.startswith(appended):
        return              # nothing was appended, or the file moved on: leave the user's bytes alone
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        raw_ftruncate(fd, size)
        os.utime(fd, ns=(spec["atime_ns"], spec["mtime_ns"]))
    finally:
        os.close(fd)


def _rmdir_if_empty(path):
    try:
        os.rmdir(path)
    except (FileNotFoundError, NotADirectoryError):
        pass
    except OSError as error:
        if error.errno not in (errno.ENOTEMPTY, errno.EEXIST):
            raise


def apply_spec(spec):
    """Run one journal operation. Every operation is safe to run again and when its target is already gone."""
    op = spec["op"]
    path = Path(spec["path"]) if "path" in spec else None
    if op in ("rmdir", "rmdir_empty"):
        if not os.path.islink(path):
            _rmdir_if_empty(path)
    elif op == "unlink":
        if not os.path.isdir(path) or os.path.islink(path):
            _unlink(path)
    elif op == "unlink_link":
        if os.path.islink(path) and os.readlink(path) == spec["target"]:
            _unlink(path)
    elif op == "relink":
        if os.path.islink(path) and os.readlink(path) in (spec["previous"], spec["new"]):
            _swap(path, spec["previous"])
    elif op == "restore":
        if spec["previous"] is None:
            _unlink(path)
        else:
            previous = base64.b64decode(spec["previous"])
            try:
                unchanged = path.read_bytes() == previous
            except OSError:
                unchanged = False
            if not unchanged:
                _write_atomic(path, previous)
                if spec.get("mtime_ns") is not None:
                    os.utime(path, ns=(spec["mtime_ns"], spec["mtime_ns"]))
    elif op == "rmtree":
        force_rmtree(path)
        if spec.get("temp"):
            force_rmtree(Path(spec["temp"]))
    elif op == "untruncate":
        _untruncate(spec)
    elif op == "cut_block":
        _cut_block(spec)
    elif op == "rm_link":
        if os.path.islink(path) and os.readlink(path) == spec["target"]:
            _unlink(path)
    elif op == "rm_file":
        if os.path.isfile(path) and not os.path.islink(path):
            if spec.get("sha256") is None or sha256(Path(path).read_bytes()) == spec["sha256"]:
                _unlink(path)
    elif op == "rm_tree":
        force_rmtree(path)
    elif op == "drop_journal":
        _unlink(path)
    else:
        raise ValueError("unknown journal operation %r" % op)


# ---------------------------------------------------------------- steps that make or change

def mkdir(path):
    return Step("create", path, "dir", "", lambda: os.mkdir(path), undo={"op": "rmdir", "path": str(path)})


def write_file(path, data, detail=""):
    """Create a new file; an existing path is an error."""
    def do():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        try:
            write_all(fd, data)
        finally:
            os.close(fd)
    return Step("create", path, "file", detail, do, undo={"op": "unlink", "path": str(path)})


def symlink(path, target):
    return Step("create", path, "symlink", "-> " + str(target), lambda: os.symlink(target, path),
                undo={"op": "unlink_link", "path": str(path), "target": str(target)})


def swap_symlink(path, target, detail=""):
    """Point an existing symlink at a new target in one atomic rename: a reader never sees it missing."""
    previous = os.readlink(path)
    return Step("replace", path, "symlink", detail or "-> " + str(target), lambda: _swap(path, target),
                undo={"op": "relink", "path": str(path), "previous": previous, "new": str(target)})


def replace_file(path, data):
    """Write a file through a temporary file in the same directory and an atomic rename."""
    try:
        previous = path.read_bytes()
        mtime = path.stat().st_mtime_ns
    except FileNotFoundError:
        previous, mtime = None, None
    return Step("replace" if previous is not None else "create", path, "file", "",
                lambda: _write_atomic(path, data),
                undo={"op": "restore", "path": str(path), "previous": None if previous is None else b64(previous),
                      "mtime_ns": mtime})


def build_release(destination, files, source_root, extra):
    """Copy `files` (relative paths of the source tree) into a new release directory, precompile it for the
    installing interpreter, make it read-only, then rename it into place, so that the directory appears only
    when complete. `extra` maps a release-relative path to the bytes written after the copy."""
    temporary = destination.parent / (".tmp-%s-%d" % (destination.name, os.getpid()))

    def do():
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
    return Step("create", destination, "tree", "%d files" % (len(files) + len(extra)), do,
                undo={"op": "rmtree", "path": str(destination), "temp": str(temporary)})


def _freeze(root):
    """Remove every write bit: a release does not change after it is made (nothing may add `__pycache__`)."""
    for directory, _, files in os.walk(root, topdown=False):
        for name in files:
            entry = os.path.join(directory, name)
            if not os.path.islink(entry):
                os.chmod(entry, os.stat(entry).st_mode & ~0o222)
        os.chmod(directory, os.stat(directory).st_mode & ~0o222)


def backup_file(destination, source, expected):
    """Copy the user's file into backup/. The bytes read now must be the ones the plan read."""
    def do():
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            data = read_all(fd)
        finally:
            os.close(fd)
        if sha256(data) != sha256(expected):
            raise Changed(errno.EBUSY, "%s changed after the plan; nothing was changed" % source)
        out = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        try:
            write_all(out, data)
        finally:
            os.close(out)
    return Step("create", destination, "file", "backup of %s" % source, do,
                undo={"op": "unlink", "path": str(destination)})


def append_block(path, block, original, info):
    """Append the managed block to the user's tmux file in place (inode, mode and owner stay). The undo is in
    the journal before the first byte is written; the file must still be the bytes the plan read."""
    undo = {"op": "untruncate", "path": str(path), "size": len(original), "block": b64(block),
            "atime_ns": info.st_atime_ns, "mtime_ns": info.st_mtime_ns}

    def do():
        fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW)
        try:
            if sha256(read_all(fd)) != sha256(original):
                raise Changed(errno.EBUSY, "%s changed after the plan; nothing was changed" % path)
            write_all(fd, block)
        finally:
            os.close(fd)
    return Step("modify", path, "block", "append the managed block", do, undo=undo)


# ---------------------------------------------------------------- steps that remove (uninstall)

def _removal(action, path, kind, detail, spec):
    return Step(action, path, kind, detail, lambda: apply_spec(spec), redo=spec)


def remove_link(path, target):
    return _removal("remove", path, "symlink", "", {"op": "rm_link", "path": str(path), "target": target})


def remove_file(path, expected_sha=None):
    return _removal("remove", path, "file", "", {"op": "rm_file", "path": str(path), "sha256": expected_sha})


def remove_tree(path):
    return _removal("remove", path, "tree", "", {"op": "rm_tree", "path": str(path)})


def remove_dir(path):
    return _removal("remove", path, "dir", "", {"op": "rmdir_empty", "path": str(path)})


def remove_block(path, block, delete_if_empty, original):
    """Cut the exact block (with its leading newline) out of the file; nothing else changes. A file that the
    installer created and that holds nothing else is deleted (the step then reports `remove`)."""
    delete = delete_if_empty and original == block
    spec = {"op": "cut_block", "path": str(path), "block": b64(block), "expect": sha256(original),
            "delete_if_empty": bool(delete_if_empty)}
    return Step("remove" if delete else "modify", path, "file" if delete else "block",
                "" if delete else "remove the managed block", lambda: apply_spec(spec), redo=spec)


def drop_journal(journal_path):
    """The journal goes before the directories that may hold it are removed."""
    return Step("remove", journal_path, "file", "interrupted-run journal", lambda: _unlink(journal_path),
                redo={"op": "drop_journal", "path": str(journal_path)}, internal=True)


@dataclass
class Journal:
    """What the next command needs to finish or undo an interrupted run (install-contract.md section 2)."""

    path: Path
    command: str
    mode: str                                   # "undo" or "redo"
    specs: list = field(default_factory=list)
