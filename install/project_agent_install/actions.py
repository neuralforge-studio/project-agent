"""The steps of a plan, and the operations they are made of (contract section 2, rule 5).

A step names one change (`dry-run` prints the same list) and carries a spec that survives a crash:

* `undo` (install, upgrade, rollback): what restores the state before the step. Computed at plan time and
  written to the journal before the first change, so it is safe whether the step ran, ran half, or never ran.
* `redo` (uninstall): the removal itself. Removing is not undone; the journal lets the next `uninstall` finish.

A spec holds an operation, a closed-set identifier and state fingerprints, never a path (paths.py). Every
operation first looks at what is there and acts only if it is the state the installer made (principle B); it
reports anything else in `ctx.notes` and leaves it. The user's tmux file is replaced by renaming a complete
temporary file over it, so it is always the bytes from before or after (principle C).

`checkpoint` is called around each step and when a temporary file or link exists; it does nothing and the
tests replace it to stop the process there.
"""

import base64
import compileall
from dataclasses import dataclass, field
import errno
import hashlib
import os
from pathlib import Path
import shutil
import stat
from typing import Callable

from . import bundle, tmuxconf
from .paths import temp_of

_temp_events = [0]


def checkpoint(position, index):
    """Called before ("before") and after ("after") step `index`, and as "temp" for each temporary file."""


def temp_created():
    index = _temp_events[0]
    _temp_events[0] += 1
    checkpoint("temp", index)


def raw_write(fd, data):
    return os.write(fd, data)


def write_all(fd, data):
    """Write every byte; a short write continues where it stopped."""
    view = memoryview(data)
    while view:
        count = raw_write(fd, view)
        if count <= 0:
            raise OSError(errno.EIO, "a write made no progress")
        view = view[count:]


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


def fsync_dir(directory):
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Changed(OSError):
    """A file is not what the plan read: nothing is written to it."""


@dataclass
class Context:
    """What an operation may use besides its spec: the places, a list for what it leaves alone, and whether a
    changed file refuses the run (the first run) or is only reported (a resumed uninstall)."""

    places: object
    journal_path: Path = None
    strict: bool = True
    notes: list = field(default_factory=list)


@dataclass
class Step:
    action: str          # create | replace | modify | remove
    path: Path
    kind: str            # dir | file | symlink | tree | block
    detail: str
    run: Callable[[Context], None]
    undo: dict = None
    redo: dict = None
    internal: bool = False      # bookkeeping that the plan does not list (the journal itself)


# ---------------------------------------------------------------- what is on disk

def unlink(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def inspect(path):
    """("absent"|"file"|"link"|"dir"|"other", fingerprint): a file's hash, a link's target."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return "absent", None
    if stat.S_ISLNK(info.st_mode):
        return "link", os.readlink(path)
    if stat.S_ISDIR(info.st_mode):
        return "dir", None
    if stat.S_ISREG(info.st_mode):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            return "file", sha256(read_all(fd))
        finally:
            os.close(fd)
    return "other", None


def digest_of(names):
    return sha256("\n".join(sorted(names)).encode())


def release_digest(files, extra):
    """The listing of a release as the plan knows it: every file, and every directory above one (`name/`).
    The bytecode directories the build adds are not in it."""
    names = set(files) | set(extra)
    for relative in list(names):
        parts = relative.split("/")
        names.update("/".join(parts[:count]) + "/" for count in range(1, len(parts)))
    return digest_of(names)


def tree_digest(root):
    """The same listing read from disk. Of the bytecode directories only `__pycache__` itself and the `.pyc` files
    directly in it are left out: anything else in them (a user's file) changes the digest."""
    names = []
    for directory, dirs, files in os.walk(root):
        base = os.path.relpath(directory, root)
        prefix = "" if base == "." else base.replace(os.sep, "/") + "/"
        in_cache = os.path.basename(directory) == "__pycache__"
        for name in files:
            if not (in_cache and name.endswith(".pyc")):
                names.append(prefix + name)
        for name in dirs:
            if os.path.islink(os.path.join(directory, name)):
                names.append(prefix + name)
            elif name != "__pycache__":
                names.append(prefix + name + "/")
    return digest_of(names)


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


# ---------------------------------------------------------------- making things

def swap_path(path, target):
    """Point a symlink at a new target by renaming a complete temporary link over it: never missing."""
    temporary = temp_of(path)
    unlink(temporary)
    os.symlink(target, temporary)
    temp_created()
    try:
        os.replace(temporary, path)
    except BaseException:
        unlink(temporary)
        raise


def create_new(path, data, guard=None, mode=None):
    """Make a file that does not exist yet, complete: write a temporary file, then `link` it to the name (which
    fails if the name exists, so nothing is overwritten) and remove the temporary file."""
    temporary = temp_of(path)
    unlink(temporary)
    if guard:
        guard()
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o666)
    try:
        if mode is not None:
            os.fchmod(fd, mode)                     # not the umask's guess: the mode the caller asked for
        write_all(fd, data)
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        unlink(temporary)
        raise
    os.close(fd)
    temp_created()
    try:
        os.link(temporary, path)
    except OSError as error:
        if error.errno not in (errno.EPERM, errno.ENOTSUP, errno.EMLINK):
            raise
        out = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)        # a file system without hard links
        try:
            if mode is not None:
                os.fchmod(out, mode)
            write_all(out, data)
        finally:
            os.close(out)
    finally:
        unlink(temporary)
    fsync_dir(path.parent)


def replace_atomic(path, data, mode, mtime_ns=None, expect=None):
    """Replace a file by renaming a complete temporary file over it. `expect` is (inode, size, mtime) the file
    must still have; `mode` is the permission the new file gets."""
    temporary = temp_of(path)
    unlink(temporary)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, mode)
        write_all(fd, data)
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        unlink(temporary)
        raise
    os.close(fd)
    temp_created()
    try:
        if expect is not None:
            info = os.lstat(path)
            if (info.st_ino, info.st_size, info.st_mtime_ns) != expect:
                raise Changed(errno.EBUSY, "%s changed while it was being rewritten; nothing was changed" % path)
        os.replace(temporary, path)
    except BaseException:
        unlink(temporary)
        raise
    fsync_dir(path.parent)
    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))


def read_user_file(path):
    """(bytes, stat) of a regular file the user owns, read through the open file."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        return read_all(fd), os.fstat(fd)
    finally:
        os.close(fd)


def _freeze(root):
    """Remove every write bit: a release does not change after it is made (nothing may add `__pycache__`)."""
    for directory, _, files in os.walk(root, topdown=False):
        for name in files:
            entry = os.path.join(directory, name)
            if not os.path.islink(entry):
                os.chmod(entry, os.stat(entry).st_mode & ~0o222)
        os.chmod(directory, os.stat(directory).st_mode & ~0o222)


# ---------------------------------------------------------------- undo and redo operations

def _leave(ctx, path):
    ctx.notes.append("%s is not as the installer left it; it is left as it is." % path)


def _op_dir(ctx, spec):
    path = ctx.places.dir(spec["id"])
    if inspect(path)[0] == "dir":
        try:
            os.rmdir(path)
        except OSError as error:
            if error.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                raise
            ctx.notes.append("%s is not empty; it is left as it is." % path)


def _op_file(ctx, spec):
    path = ctx.places.file(spec["id"])
    unlink(temp_of(path))
    state, fingerprint = inspect(path)
    if state == "file" and fingerprint == spec["sha"]:
        unlink(path)
    elif state != "absent":
        _leave(ctx, path)


def _op_link(ctx, spec):
    path = ctx.places.link(spec["id"])
    state, fingerprint = inspect(path)
    if state == "link" and fingerprint == spec["target"]:
        unlink(path)
    elif state != "absent":
        _leave(ctx, path)


def _op_swap(ctx, spec):
    path = ctx.places.link(spec["id"])
    temporary = temp_of(path)
    if os.path.islink(temporary):
        unlink(temporary)
    state, fingerprint = inspect(path)
    if state == "link" and fingerprint == spec["new"]:
        swap_path(path, spec["previous"])
    elif not (state == "link" and fingerprint == spec["previous"]):
        _leave(ctx, path)


def _op_record(ctx, spec):
    path = ctx.places.file("record")
    unlink(temp_of(path))
    state, fingerprint = inspect(path)
    if state == "file" and fingerprint == spec["after_sha"]:
        if spec["previous"] is None:
            unlink(path)
        else:
            replace_atomic(path, base64.b64decode(spec["previous"]), stat.S_IMODE(os.lstat(path).st_mode),
                           spec["mtime_ns"])
    elif not ((state == "file" and fingerprint == spec["before_sha"])
              or (state == "absent" and spec["previous"] is None)):
        _leave(ctx, path)


def _op_release(ctx, spec):
    places = ctx.places
    temporary = places.release_temp(places.release_name(spec["id"]))
    if os.path.isdir(temporary) and not os.path.islink(temporary):
        force_rmtree(temporary)
    path = places.tree(spec["id"])
    state, _ = inspect(path)
    if state == "dir":
        if tree_digest(path) == spec["digest"]:
            force_rmtree(path)
        else:
            _leave(ctx, path)
    elif state != "absent":
        _leave(ctx, path)


def _tmux_state(path):
    """(state, sha, stat) of the user's tmux file; "other" for what the installer will not rewrite."""
    state, _ = inspect(path)
    if state != "file":
        return state, None, None
    data, info = read_user_file(path)
    if tmuxconf.rewrite_problem(path, info):
        return "other", None, info
    return "file", sha256(data), info


def _op_tmux(ctx, spec):
    path = ctx.places.file(spec["id"])
    unlink(temp_of(path))
    state, fingerprint, info = _tmux_state(path)
    if state == "file" and fingerprint == spec["after_sha"]:
        replace_atomic(path, base64.b64decode(spec["before_bytes"]), stat.S_IMODE(info.st_mode), spec["mtime_ns"],
                       expect=(info.st_ino, info.st_size, info.st_mtime_ns))
    elif not (state == "file" and fingerprint == spec["before_sha"]):
        ctx.notes.append("%s changed after the installer's edit; its project-agent block is left in it. Remove the "
                         "lines from `# >>> project-agent` to `# <<< project-agent <<<` yourself." % path)


def _op_rm_file(ctx, spec):
    path = ctx.places.file(spec["id"])
    state, fingerprint = inspect(path)
    if state == "file" and spec["sha"] in (None, fingerprint):
        unlink(path)
    elif state != "absent":
        _leave(ctx, path)


def _op_rm_tree(ctx, spec):
    """Remove a release: only if it is still exactly what the installer built (its listing digest). The release is
    first renamed to its reserved temporary name, so that a removal that fails half way is finished by the next run
    and never leaves a release that no longer matches its digest."""
    places = ctx.places
    path = places.tree(spec["id"])
    temporary = places.release_temp(places.release_name(spec["id"]))
    if os.path.isdir(temporary) and not os.path.islink(temporary):
        force_rmtree(temporary)                       # an earlier removal was cut off after the rename
    state, _ = inspect(path)
    if state == "dir":
        if tree_digest(path) == spec["digest"]:
            os.rename(path, temporary)
            force_rmtree(temporary)
        else:
            ctx.notes.append("%s holds files that are not the installer's; the release is left as it is." % path)
    elif state != "absent":
        _leave(ctx, path)


def _op_forget(ctx, spec):
    """Drop a release from the install record once its directory is gone. A release that is still there (its
    removal left it, because it was no longer what the installer made) stays in the record."""
    from . import record as records                 # record.py imports this module
    places = ctx.places
    name = places.release_name(spec["id"])
    if inspect(places.tree(spec["id"]))[0] != "absent" or os.path.lexists(places.release_temp(name)):
        return
    path = places.file("record")
    unlink(temp_of(path))
    if inspect(path)[0] != "file":
        return
    installed = records.read(places.env)
    if name not in installed["releases"]:
        return
    replace_atomic(path, records.encode(records.without_release(places.env, installed, name)),
                   stat.S_IMODE(os.lstat(path).st_mode))


def _op_rm_dir(ctx, spec):
    path = ctx.places.dir(spec["id"])
    if inspect(path)[0] == "dir":
        try:
            os.rmdir(path)
        except OSError as error:
            if error.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                raise
            ctx.notes.append("%s is not empty; it is left as it is." % path)


def _op_cut(ctx, spec):
    """Remove the managed block from the user's tmux file: only a file that is exactly as the plan read it (or
    already cut) is touched; anything else is the user's edit."""
    path = ctx.places.file(spec["id"])
    unlink(temp_of(path))
    state, fingerprint, info = _tmux_state(path)
    if state == "absent" or (state == "file" and fingerprint == spec["after_sha"]):
        return
    if state == "file" and fingerprint == spec["before_sha"]:
        data, info = read_user_file(path)
        if spec["delete"] and data == tmuxconf.BLOCK:
            os.unlink(path)
            return
        if tmuxconf.BLOCK in data:
            replace_atomic(path, data.replace(tmuxconf.BLOCK, b"", 1), stat.S_IMODE(info.st_mode),
                           expect=(info.st_ino, info.st_size, info.st_mtime_ns))
        return
    if ctx.strict:
        raise Changed(errno.EBUSY, "%s changed after the plan; nothing was changed" % path)
    ctx.notes.append("%s was changed after the plan; its project-agent block is left in it. Remove the lines from "
                     "`# >>> project-agent` to `# <<< project-agent <<<` yourself." % path)


def _op_drop_journal(ctx, spec):
    unlink(ctx.journal_path)


OPERATIONS = {"dir": _op_dir, "file": _op_file, "link": _op_link, "swap": _op_swap, "record": _op_record,
              "release": _op_release, "tmux": _op_tmux, "rm_link": _op_link, "rm_file": _op_rm_file,
              "rm_tree": _op_rm_tree, "forget": _op_forget, "rm_dir": _op_rm_dir, "cut": _op_cut, "drop_journal": _op_drop_journal}


def apply_spec(ctx, spec):
    """Run one journal operation. Every operation is safe to run again and when its target is already gone."""
    OPERATIONS[spec["op"]](ctx, spec)


# ---------------------------------------------------------------- steps that make or change

def mkdir(places, ident):
    path = places.dir(ident)
    return Step("create", path, "dir", "", lambda ctx: os.mkdir(path), undo={"op": "dir", "id": ident})


def new_file(places, ident, data, detail="", guard=None, mode=None):
    """Create a file that does not exist; an existing name is an error and is left alone."""
    path = places.file(ident)
    return Step("create", path, "file", detail, lambda ctx: create_new(path, data, guard, mode),
                undo={"op": "file", "id": ident, "sha": sha256(data)})


def new_link(places, ident, target):
    path = places.link(ident)
    return Step("create", path, "symlink", "-> " + str(target), lambda ctx: os.symlink(target, path),
                undo={"op": "link", "id": ident, "target": str(target)})


def swap_link(places, ident, target, detail=""):
    """Point a link the installer owns or takes over at `target`. The link must still be what the plan read (its
    text and owner): one that changed since is the user's and is not overwritten (principle B); the run then fails
    and is undone."""
    path = places.link(ident)
    previous, owner = os.readlink(path), os.lstat(path).st_uid

    def run(ctx):
        try:
            same = os.readlink(path) == previous and os.lstat(path).st_uid == owner
        except OSError:
            same = False
        if not same:
            raise Changed(errno.EBUSY, "%s changed after the plan; it was not replaced" % path)
        swap_path(path, target)
    return Step("replace", path, "symlink", detail or "-> " + str(target), run,
                undo={"op": "swap", "id": ident, "previous": previous, "new": str(target)})


def restore_link(places, ident, installed, previous):
    """Uninstall: point a link the installer took over back at the target it had (one rename, never missing).
    Only a link that still points where the installer put it is changed (the swap operation)."""
    path = places.link(ident)
    spec = {"op": "swap", "id": ident, "previous": previous, "new": installed}
    return Step("replace", path, "symlink", "-> %s (restore the link as it was before the install)" % previous,
                lambda ctx: apply_spec(ctx, spec), redo=spec)


def replace_record(places, data):
    path = places.file("record")
    state, fingerprint = inspect(path)
    previous = path.read_bytes() if state == "file" else None
    mtime = os.lstat(path).st_mtime_ns if state == "file" else None
    mode = 0o644 if previous is None else stat.S_IMODE(os.lstat(path).st_mode)
    return Step("replace" if previous is not None else "create", path, "file", "",
                lambda ctx: replace_atomic(path, data, mode),
                undo={"op": "record", "previous": None if previous is None else b64(previous),
                      "before_sha": fingerprint, "after_sha": sha256(data), "mtime_ns": mtime})


def build_release(places, name, files, source_root, extra):
    """Copy `files` (relative paths of the source tree) into a new release directory, precompile it and write
    its start-up bundles for the installing interpreter, make it read-only, then rename it into place, so that the directory appears only
    when complete. `extra` maps a release-relative path to the bytes written after the copy."""
    ident = "release:" + name
    destination, temporary = places.tree(ident), places.release_temp(name)
    count = len(files) + len(extra)

    def run(ctx):
        if os.path.lexists(temporary):
            force_rmtree(temporary)
        try:
            os.mkdir(temporary)
            temp_created()
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
            bundle.build(temporary, destination)
            _freeze(temporary)
            os.rename(temporary, destination)
        except BaseException:
            force_rmtree(temporary)
            raise
        fsync_dir(destination.parent)
    return Step("create", destination, "tree", "%d files" % count, run,
                undo={"op": "release", "id": ident, "digest": release_digest(files, extra)})


def backup_file(places, name, source, original, mode):
    """Copy the user's file into backup/ with the same permissions. The bytes read now must be the ones the plan
    read."""
    def guard():
        data, _ = read_user_file(source)
        if sha256(data) != sha256(original):
            raise Changed(errno.EBUSY, "%s changed after the plan; nothing was changed" % source)
    return new_file(places, "backup:" + name, original, "backup of %s" % source, guard, mode)


def append_block(places, ident, original, block, info):
    """Append the managed block to the user's tmux file by renaming a complete new file over it. The file must
    still be the bytes the plan read; the journal holds those bytes and both hashes."""
    path = places.file(ident)

    def run(ctx):
        data, current = read_user_file(path)
        if tmuxconf.rewrite_problem(path, current) or sha256(data) != sha256(original):
            raise Changed(errno.EBUSY, "%s changed after the plan; nothing was changed" % path)
        replace_atomic(path, data + block, stat.S_IMODE(current.st_mode),
                       expect=(current.st_ino, current.st_size, current.st_mtime_ns))
    return Step("modify", path, "block", "append the managed block", run,
                undo={"op": "tmux", "id": ident, "before_bytes": b64(original), "before_sha": sha256(original),
                      "after_sha": sha256(original + block), "mtime_ns": info.st_mtime_ns})


# ---------------------------------------------------------------- steps that remove (uninstall)

def _removal(action, path, kind, detail, spec):
    return Step(action, path, kind, detail, lambda ctx: apply_spec(ctx, spec), redo=spec)


def remove_link(places, ident, target):
    return _removal("remove", places.link(ident), "symlink", "", {"op": "rm_link", "id": ident, "target": target})


def remove_file(places, ident, expected_sha=None):
    return _removal("remove", places.file(ident), "file", "", {"op": "rm_file", "id": ident, "sha": expected_sha})


def remove_tree(places, ident, digest):
    return _removal("remove", places.tree(ident), "tree", "", {"op": "rm_tree", "id": ident, "digest": digest})


def forget_release(places, name):
    """Drop a removed release from the install record. The plan does not list it (the record is bookkeeping)."""
    spec = {"op": "forget", "id": "release:" + name}
    return Step("modify", places.file("record"), "file", "forget release " + name,
                lambda ctx: apply_spec(ctx, spec), redo=spec, internal=True)


def remove_dir(places, ident):
    return _removal("remove", places.dir(ident), "dir", "", {"op": "rm_dir", "id": ident})


def cut_block(places, ident, original, delete_if_empty):
    """Cut the managed block (with its leading newline) out of the user's tmux file. A file that the installer
    created and that holds nothing else is deleted (the step then reports `remove`)."""
    path = places.file(ident)
    delete = bool(delete_if_empty) and original == tmuxconf.BLOCK
    spec = {"op": "cut", "id": ident, "before_sha": sha256(original),
            "after_sha": sha256(original.replace(tmuxconf.BLOCK, b"", 1)), "delete": delete}
    return Step("remove" if delete else "modify", path, "file" if delete else "block",
                "" if delete else "remove the managed block", lambda ctx: apply_spec(ctx, spec), redo=spec)


def drop_journal(journal_path):
    """The journal goes before the directories that may hold it are removed."""
    return Step("remove", journal_path, "file", "interrupted-run journal",
                lambda ctx: apply_spec(ctx, {"op": "drop_journal"}), redo={"op": "drop_journal"}, internal=True)


@dataclass
class Journal:
    """What the next command needs to finish or undo an interrupted run (install-contract.md section 2)."""

    path: Path
    command: str
    mode: str                                   # "undo" or "redo"
    homes: dict = field(default_factory=dict)   # provider -> home directory (str)
    specs: list = field(default_factory=list)
