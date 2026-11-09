"""Which paths belong to the installer. Everything that is read back from disk (the install record, the
journal) is checked here before the installer deletes or rewrites anything: a damaged or edited file must not
point the installer at a user's file.
"""

import re

from .layout import SKILLS, TOOLS, InstallerError

RELEASE_NAME = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+~-]*-[0-9a-f]{12}")


def parse(env, text):
    """A path from a record: absolute or `~/…`, without `..`, `.`, empty parts or NUL."""
    if not isinstance(text, str) or "\0" in text or not text:
        raise InstallerError("record_invalid", "A recorded path is not valid.", {"path": repr(text)[:80]})
    path = env.expand(text)
    if not path.is_absolute() or any(part in ("..", ".", "") for part in text.split("/")[1:]):
        raise InstallerError("record_invalid", "A recorded path is not a plain absolute path.", {"path": text})
    return path


def in_lib(env, path):
    return path == env.lib or env.lib in path.parents


def is_release(env, path):
    return path.parent == env.releases and RELEASE_NAME.fullmatch(path.name) is not None


def is_temporary_release(env, path):
    return path.parent == env.releases and path.name.startswith(".tmp-")


def is_shim(env, path):
    return path in {env.shim(tool) for tool in TOOLS}


def is_skill_link(path):
    return path.name in SKILLS and path.parent.name == "skills"


def is_skills_dir(path):
    return path.name == "skills" and len(path.parts) > 3


def is_tmux_file(env, path):
    return path in env.tmux_candidates


def is_link_place(env, path):
    """Where the installer puts symlinks: a shim, a skill link, or `current`."""
    return is_shim(env, path) or is_skill_link(path) or path == env.current


def is_installer_dir(env, path):
    """A directory the installer may have created (and may remove when it is empty)."""
    return (path in {env.home / ".local", env.home / ".local/lib", env.home / ".local/bin",
                     env.home / ".config", env.home / ".config/project-agent", env.lib, env.releases}
            or is_skills_dir(path) or is_release(env, path) or path == env.backup)


def is_lib_file(env, path):
    return path in (env.tmux_conf, env.record)


def require(condition, what, text):
    if not condition:
        raise InstallerError("record_invalid", "%s is outside what the installer makes: %s" % (what, text),
                             {"path": str(text)})


def validate_record(env, record):
    """Every path and name in the install record must be one the installer itself would have made.
    A record that fails is refused before any command changes anything."""
    releases = record["releases"]
    for name in releases:
        require(isinstance(name, str) and RELEASE_NAME.fullmatch(name), "A release name", name)
    require(record["current"] in releases, "The current release", record["current"])
    require(record.get("previous") is None or record["previous"] in releases, "The previous release",
            record.get("previous"))
    owned_paths = []
    for entry in record["owned"]:
        require(isinstance(entry, dict) and isinstance(entry.get("kind"), str), "A record entry", entry)
        path = parse(env, entry.get("path"))
        kind = entry["kind"]
        if kind == "dir":
            require(is_release(env, path) and path.name in releases or path == env.backup,
                    "A directory entry", entry["path"])
        elif kind == "file":
            require(is_lib_file(env, path), "A file entry", entry["path"])
        elif kind == "symlink":
            require(is_link_place(env, path), "A symlink entry", entry["path"])
            target = entry.get("target")
            require(isinstance(target, str) and "\0" not in target, "A symlink target", target)
            if path == env.current:
                require(target == "releases/" + record["current"], "The target of current", target)
            elif is_shim(env, path):
                require(target == str(env.current / "tools" / path.name / "bin" / path.name), "A shim target", target)
            else:
                require(target == str(env.current / "skills" / path.name), "A skill link target", target)
        else:
            require(False, "An entry kind", kind)
        owned_paths.append(path)
    for text in record["created_dirs"]:
        path = parse(env, text)
        require(is_installer_dir(env, path) and not is_release(env, path) and path != env.backup,
                "A created directory", text)
        require(path != env.home and path not in env.home.parents, "A created directory", text)
        require(any(path in owned.parents for owned in owned_paths) or path == env.lib or path == env.releases
                or path == env.home / ".local" or path == env.home / ".local/lib",
                "A created directory with nothing of the installer in it", text)
    tmux = record["tmux"]
    require(tmux.get("state") in ("none", "inserted", "present", "manual"), "The tmux state", tmux.get("state"))
    if tmux["state"] != "none":
        require(is_tmux_file(env, parse(env, tmux.get("file"))), "The tmux file", tmux.get("file"))
    if tmux.get("backup") is not None:
        backup = parse(env, tmux["backup"])
        require(backup.parent == env.backup, "The tmux backup", tmux["backup"])


# Where each journal operation may act (operations are in actions.py).
def check_spec(env, spec):
    """A journal entry may only name installer places, and only for the operation that belongs there."""
    op = spec.get("op")
    path = parse(env, spec.get("path"))
    allowed = {
        "rmdir": lambda: is_installer_dir(env, path),
        "rmdir_empty": lambda: is_installer_dir(env, path),
        "unlink": lambda: (in_lib(env, path) and path != env.lib) or is_link_place(env, path)
        or path == env.registry or path in env.tmux_candidates,
        "unlink_link": lambda: is_link_place(env, path),
        "relink": lambda: path == env.current or is_skill_link(path),
        "restore": lambda: path == env.record,
        "rmtree": lambda: is_release(env, path) or is_temporary_release(env, path),
        "untruncate": lambda: is_tmux_file(env, path),
        "cut_block": lambda: is_tmux_file(env, path),
        "rm_link": lambda: is_link_place(env, path),
        "rm_file": lambda: is_lib_file(env, path),
        "rm_tree": lambda: is_release(env, path) or path == env.backup,
        "drop_journal": lambda: True,
    }
    if op not in allowed or not allowed[op]():
        raise InstallerError("journal_invalid", "The journal names a path the installer does not own.",
                             {"op": op, "path": str(path)})
    return path
