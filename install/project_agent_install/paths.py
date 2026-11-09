"""The one source of every path the installer touches (contract section 2, rule 5, principle A).

`Places` turns a closed set of identifiers into paths from the user's HOME and the provider homes. Recovery and
removal work from identifiers and state fingerprints only; a path string read from the journal or the install
record is accepted only when it equals the path computed here. A file read from disk never chooses what is
deleted or rewritten.

Identifiers:
    dir      local locallib lib releases bin backup config configpa skills:<provider>
    link     current  shim:<tool>  skill:<provider>:<name>
    file     tmux_conf record registry backup:<name> tmux:<candidate number>
    tree     release:<name>  backup
"""

import base64
import os
import re

from .layout import PROVIDERS, SKILLS, TOOLS, InstallerError

RELEASE_NAME = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+~-]*-[0-9a-f]{12}")
BACKUP_NAME = re.compile(r"[0-9]{8}T[0-9]{6}Z-[^/\0]+")
HEX = re.compile(r"[0-9a-f]{64}")
DIRS = {"local": ".local", "locallib": ".local/lib", "lib": ".local/lib/project-agent",
        "releases": ".local/lib/project-agent/releases", "bin": ".local/bin",
        "backup": ".local/lib/project-agent/backup", "config": ".config", "configpa": ".config/project-agent"}
PROVIDER_NAMES = tuple(name for name, _, _ in PROVIDERS)


def temp_of(path):
    """The temporary file of a file or link: a fixed name beside it, so the next run finds it."""
    return path.parent / ("." + path.name + ".pi-tmp")


class Places:
    def __init__(self, env, homes, code="journal_invalid"):
        """`homes` maps a provider name to its home directory (a Path)."""
        self.env = env
        self.homes = dict(homes)
        self.code = code
        for provider, home in self.homes.items():
            if provider not in PROVIDER_NAMES or not home.is_absolute() or ".." in home.parts:
                self.bad("A provider home", "%s=%s" % (provider, home))

    def bad(self, what, value):
        raise InstallerError(self.code, "%s is not one the installer makes: %s" % (what, value),
                             {"value": str(value)[:120]})

    # directories
    def dir(self, ident):
        if ident in DIRS:
            return self.env.home / DIRS[ident]
        if ident.startswith("skills:") and ident[7:] in self.homes:
            return self.homes[ident[7:]] / "skills"
        self.bad("A directory", ident)

    def dir_id(self, path):
        """The identifier of a directory the installer may create (the path comes from the plan)."""
        for ident in list(DIRS) + ["skills:" + provider for provider in self.homes]:
            if self.dir(ident) == path:
                return ident
        self.bad("A directory", path)

    # releases
    def release_name(self, ident):
        name = ident[len("release:"):] if ident.startswith("release:") else ""
        if not RELEASE_NAME.fullmatch(name):
            self.bad("A release", ident)
        return name

    def tree(self, ident):
        if ident == "backup":
            return self.env.backup
        return self.env.releases / self.release_name(ident)

    def release_temp(self, name):
        return self.env.releases / (".tmp-" + name)

    # links
    def link(self, ident):
        env = self.env
        if ident == "current":
            return env.current
        parts = ident.split(":")
        if len(parts) == 2 and parts[0] == "shim" and parts[1] in TOOLS:
            return env.shim(parts[1])
        if len(parts) == 3 and parts[0] == "skill" and parts[1] in self.homes and parts[2] in SKILLS:
            return self.homes[parts[1]] / "skills" / parts[2]
        self.bad("A link", ident)

    def link_target(self, ident):
        """What the installer points a shim or skill link at (`current` points at a release: see current_target)."""
        env = self.env
        parts = ident.split(":")
        if parts[0] == "shim":
            return str(env.current / "tools" / parts[1] / "bin" / parts[1])
        if parts[0] == "skill":
            return str(env.current / "skills" / parts[2])
        self.bad("A link target", ident)

    def current_target(self, text):
        if not isinstance(text, str) or not text.startswith("releases/") or not RELEASE_NAME.fullmatch(text[9:]):
            self.bad("The target of current", text)
        return text

    # links of the old development checkout (contract section 2, rule 8)
    def dev_target(self, ident, checkout):
        """Where a shim or skill link points when it is a link into the development checkout `checkout`."""
        parts = ident.split(":")
        if parts[0] == "shim" and len(parts) == 2 and parts[1] in TOOLS:
            return os.path.join(checkout, "codex/tools", parts[1], "bin", parts[1])
        if parts[0] == "skill" and len(parts) == 3 and parts[2] in SKILLS:
            return os.path.join(checkout, "codex/skills", parts[2])
        self.bad("A development link", ident)

    def dev_shaped(self, ident, text):
        """The text of such a link ends in the known shape (`codex/tools/<tool>/bin/<tool>`, `codex/skills/<name>`);
        what comes before it is the user's checkout, absolute or relative. The record may hold only such a text."""
        tail = self.dev_target(ident, "").lstrip("/").split("/")
        parts = text.split("/") if isinstance(text, str) and text and "\0" not in text else []
        return len(parts) > len(tail) and parts[-len(tail):] == tail

    # files
    def file(self, ident):
        env = self.env
        fixed = {"tmux_conf": env.tmux_conf, "record": env.record, "registry": env.registry}
        if ident in fixed:
            return fixed[ident]
        if ident.startswith("tmux:") and ident[5:] in ("0", "1"):
            return env.tmux_candidates[int(ident[5:])]
        if ident.startswith("backup:") and BACKUP_NAME.fullmatch(ident[7:]):
            return env.backup / ident[7:]
        self.bad("A file", ident)

    def tmux_id(self, path):
        for number, candidate in enumerate(self.env.tmux_candidates):
            if candidate == path:
                return "tmux:%d" % number
        self.bad("A tmux file", path)

    def identify(self, path):
        """(kind, identifier) of a path of the install record. The path must be exactly one the installer makes."""
        env = self.env
        if path == env.current:
            return "link", "current"
        for tool in TOOLS:
            if path == env.shim(tool):
                return "link", "shim:" + tool
        for provider in self.homes:
            for name in SKILLS:
                if path == self.homes[provider] / "skills" / name:
                    return "link", "skill:%s:%s" % (provider, name)
        for ident in ("tmux_conf", "record"):
            if path == self.file(ident):
                return "file", ident
        if path == env.backup:
            return "tree", "backup"
        if path.parent == env.releases and RELEASE_NAME.fullmatch(path.name):
            return "tree", "release:" + path.name
        self.bad("A recorded path", path)


def parse(env, text, code="record_invalid"):
    """A path from the install record: absolute or `~/…` without `..`, `.`, empty parts or NUL."""
    if not isinstance(text, str) or not text or "\0" in text:
        raise InstallerError(code, "A recorded path is not valid.", {"value": repr(text)[:80]})
    path = env.expand(text)
    if not path.is_absolute() or any(part in ("..", ".", "") for part in text.split("/")[1:]):
        raise InstallerError(code, "A recorded path is not a plain absolute path: %s" % text, {"value": text})
    return path


def require(condition, what, value):
    if not condition:
        raise InstallerError("record_invalid", "%s is not one the installer makes: %s" % (what, value),
                             {"value": str(value)[:120]})


def record_places(env, record):
    homes = record.get("provider_homes", {})
    require(isinstance(homes, dict), "The provider homes", homes)
    return Places(env, {provider: parse(env, text) for provider, text in homes.items()}, code="record_invalid")


def validate_record(env, record):
    """Every path and name in the install record must equal one that the installer computes. A record that fails
    is refused before any command changes anything."""
    places = record_places(env, record)
    releases = record["releases"]
    for name in releases:
        require(isinstance(name, str) and RELEASE_NAME.fullmatch(name), "A release name", name)
    require(record["current"] in releases, "The current release", record["current"])
    require(record.get("previous") is None or record["previous"] in releases, "The previous release",
            record.get("previous"))
    for entry in record["owned"]:
        require(isinstance(entry, dict) and isinstance(entry.get("kind"), str), "A record entry", entry)
        kind, ident = places.identify(parse(env, entry.get("path")))
        require({"link": "symlink", "file": "file", "tree": "dir"}[kind] == entry["kind"], "A record entry kind",
                entry["kind"])
        if kind == "link":
            target = entry.get("target")
            require(isinstance(target, str) and "\0" not in target, "A link target", target)
            if ident == "current":
                places.current_target(target)
                require(target == "releases/" + record["current"], "The target of current", target)
            else:
                require(target == places.link_target(ident), "A link target", target)
                if ident.startswith("skill:"):
                    require(entry.get("provider") == ident.split(":")[1], "A skill link provider", entry.get("provider"))
                if "adopted_from" in entry:
                    require(places.dev_shaped(ident, entry["adopted_from"]), "A link target before adoption",
                            entry["adopted_from"])
        elif ident.startswith("release:"):
            require(ident[len("release:"):] in releases, "A release directory", ident)
            require(isinstance(entry.get("digest"), str) and HEX.fullmatch(entry["digest"]), "A release digest",
                    entry.get("digest"))
        elif kind == "file" and entry.get("sha256") is not None:
            require(HEX.fullmatch(str(entry["sha256"])), "A file hash", entry["sha256"])
    for text in record["created_dirs"]:
        path = parse(env, text)
        ident = places.dir_id(path)
        require(ident not in ("backup", "config", "configpa"), "A created directory", text)
        require(path != env.home and path not in env.home.parents, "A created directory", text)
    tmux = record["tmux"]
    require(tmux.get("state") in ("none", "inserted", "present", "manual"), "The tmux state", tmux.get("state"))
    if tmux["state"] != "none":
        places.tmux_id(parse(env, tmux.get("file")))
    if tmux.get("backup") is not None:
        backup = parse(env, tmux["backup"])
        require(backup.parent == env.backup and BACKUP_NAME.fullmatch(backup.name), "The tmux backup", tmux["backup"])
        require(isinstance(tmux.get("backup_sha256"), str) and HEX.fullmatch(tmux["backup_sha256"]),
                "The tmux backup hash", tmux.get("backup_sha256"))
    return places


# Journal entries: the keys each operation has (and no others: a path key is refused).
SPEC_KEYS = {
    "dir": {"id"}, "file": {"id", "sha"}, "link": {"id", "target"}, "swap": {"id", "previous", "new"},
    "record": {"previous", "before_sha", "after_sha", "mtime_ns"}, "release": {"id", "digest"},
    "tmux": {"id", "before_bytes", "before_sha", "after_sha", "mtime_ns"},
    "rm_link": {"id", "target"}, "rm_file": {"id", "sha"}, "rm_tree": {"id", "digest"}, "forget": {"id"}, "rm_dir": {"id"},
    "cut": {"id", "before_sha", "after_sha", "delete"}, "drop_journal": set(),
}
OPTIONAL_HEX = {("rm_file", "sha"), ("record", "before_sha")}      # these two may be null


def validate_spec(places, spec):
    """A journal entry is an operation, closed-set identifiers and fingerprints; nothing else."""
    if not isinstance(spec, dict) or spec.get("op") not in SPEC_KEYS or set(spec) != SPEC_KEYS[spec["op"]] | {"op"}:
        places.bad("A journal entry", repr(spec)[:100])
    op = spec["op"]
    for key in ("sha", "before_sha", "after_sha", "digest"):
        if key in spec:
            value = spec[key]
            if not ((value is None and (op, key) in OPTIONAL_HEX) or (isinstance(value, str) and HEX.fullmatch(value))):
                places.bad("A fingerprint", value)
    for key in ("mtime_ns",):
        if key in spec and not (spec[key] is None or isinstance(spec[key], int)):
            places.bad("A time", spec[key])
    stored = {"record": "previous", "tmux": "before_bytes"}.get(op)         # these two are base64 bytes
    if stored and spec[stored] is not None:
        try:
            base64.b64decode(spec[stored], validate=True)
        except (TypeError, ValueError):
            places.bad("A stored value", stored)
    ident = spec.get("id")
    if "id" in SPEC_KEYS[op] and not isinstance(ident, str):
        places.bad("An identifier", ident)
    if op in ("dir", "rm_dir"):
        places.dir(ident)
    elif op in ("file", "rm_file"):
        places.file(ident)
    elif op in ("link", "rm_link"):
        places.link(ident)
        if ident == "current":
            places.current_target(spec["target"])
        elif spec["target"] != places.link_target(ident):
            places.bad("A link target", spec["target"])
    elif op == "swap":
        places.link(ident)
        if ident == "current":
            places.current_target(spec["previous"])
            places.current_target(spec["new"])
        elif spec["new"] != places.link_target(ident) or not isinstance(spec["previous"], str):
            places.bad("A link target", spec["new"])
    elif op in ("release", "rm_tree", "forget"):
        places.release_name(ident)
    elif op in ("tmux", "cut"):
        if not ident.startswith("tmux:"):
            places.bad("A tmux file", ident)
        places.file(ident)
    return spec
