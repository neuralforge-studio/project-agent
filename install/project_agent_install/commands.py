"""The commands as plans. Each `plan_*` reads the disk, decides everything, and returns a `Plan`;
`execute` applies it. `--dry-run` prints the plan, so the printed changes are the executed ones."""

from dataclasses import dataclass, field
import datetime as dt
import json
import os
import stat
import subprocess

from . import actions, journal, paths, record as records, release as releases, runs, tmuxconf
from .layout import SKILLS, TOOLS, InstallerError


@dataclass
class Plan:
    command: str
    steps: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    journal_path: object = None          # where the run keeps its journal (journal.path_for)
    places: object = None                # paths.Places: the one source of every path the steps touch


class Builder:
    """Collects steps, notes and conflicts; `finish` refuses with every conflict at once."""

    def __init__(self, env, command):
        self.env = env
        self.places = paths.Places(env, dict(env.provider_homes()))
        self.plan = Plan(command, journal_path=journal.path_for(env), places=self.places)
        self.conflicts = []
        self.created_dirs = []
        self._planned = set()

    def add(self, step):
        self.plan.steps.append(step)

    def note(self, text):
        self.plan.notes.append(text)

    def conflict(self, path, reason):
        self.conflicts.append({"path": self.env.display(path), "reason": reason})

    def ensure_dir(self, path, track=True):
        """Plan the missing directories above `path` (and `path`); a parent that is a symlink to a
        directory is followed (contract section 2, rule 4)."""
        missing = []
        current = path
        while current not in self._planned and not os.path.lexists(current):
            missing.append(current)
            current = current.parent
        if current not in self._planned and not os.path.isdir(current):
            self.conflict(current, "exists and is not a directory")
            return False
        for directory in reversed(missing):
            self.add(actions.mkdir(self.places, self.places.dir_id(directory)))
            self._planned.add(directory)
            if track:
                self.created_dirs.append(self.env.display(directory))
        return True

    def finish(self):
        if self.conflicts:
            raise InstallerError("conflict", "Names that the installation needs are already in use. Nothing was "
                                 "changed.", {"conflicts": self.conflicts})
        return self.plan


# ---------------------------------------------------------------- install

def plan_install(env, source, python, adopt=None):
    installed = records.read(env)
    if installed:
        if installed["current"] != source.name:
            raise InstallerError("already_installed", "Version %s is installed. Use `upgrade` to install %s."
                                 % (installed["current"], source.name))
        plan = Plan("install")
        plan.notes.append("Already installed (%s). Nothing to change." % source.name)
        return plan
    b = Builder(env, "install")
    new = records.new_record(source.name)
    owned = new["owned"]
    release_dir = env.releases / source.name
    places = b.places
    new["provider_homes"] = {provider: env.display(home) for provider, home in places.homes.items()}

    if os.path.lexists(env.lib):
        if env.lib.is_symlink() or not env.lib.is_dir():
            b.conflict(env.lib, "exists and is not a directory")
        elif os.listdir(env.lib):
            b.conflict(env.lib, "is not empty and has no install record")
    b.ensure_dir(env.lib)
    b.ensure_dir(env.releases)
    extra = {releases.PYTHON_ENV: releases.python_env(python)}
    b.add(actions.build_release(places, source.name, source.files, source.root, extra))
    owned.append(records.owned(env.display(release_dir), "dir", digest=actions.release_digest(source.files, extra)))
    b.add(actions.new_link(places, "current", "releases/" + source.name))
    owned.append(records.owned(env.display(env.current), "symlink", target="releases/" + source.name))
    tmux_conf = tmuxconf.INTEGRATION.encode()
    b.add(actions.new_file(places, "tmux_conf", tmux_conf))
    owned.append(records.owned(env.display(env.tmux_conf), "file", sha256=actions.sha256(tmux_conf)))

    if b.ensure_dir(env.bin):
        for tool in TOOLS:
            path = env.shim(tool)
            ident = "shim:" + tool
            target = places.link_target(ident)
            entry = records.owned(env.display(path), "symlink", target=target)
            if not os.path.lexists(path):
                b.add(actions.new_link(places, ident, target))
            elif not _adopt_dev_link(b, path, ident, target, adopt, entry):
                continue
            owned.append(entry)
    _plan_skill_links(env, b, owned, adopt)
    if any("adopted_from" in entry for entry in owned):
        b.note("Links into the development checkout were taken over; `uninstall` points them back at the targets "
               "recorded in %s." % env.display(env.record))
    _plan_registry_draft(env, b)
    _plan_tmux_block(env, b, new)
    path_entries = [os.path.realpath(entry) for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    if os.path.realpath(env.bin) not in path_entries:
        b.note("%s is not in PATH; add it to your shell settings (the installer does not edit them)."
               % env.display(env.bin))
    old_tmux = tmuxconf.too_old(source.root)
    if old_tmux:
        b.note(old_tmux[0])
    plan = b.finish()
    new["created_dirs"] = b.created_dirs
    owned.append(records.owned(env.display(env.record), "file"))
    plan.steps.append(actions.replace_record(places, records.encode(new)))
    return plan


def _adoptable(env, link, name):
    """Contract section 2, rule 6: a link of the remote runtime (same owner, recorded in `skills.json`)."""
    if link != env.runtime_codex_skills / name or not link.is_symlink():
        return False
    try:
        owned = json.loads(env.runtime_skills_record.read_text())
        recorded = owned.get(name) if isinstance(owned, dict) else None
        return (isinstance(recorded, str) and link.lstat().st_uid == os.getuid()
                and str(os.readlink(link)) == recorded)
    except (OSError, ValueError):
        return False


def _adopt_dev_link(b, link, ident, target, checkout, entry):
    """Contract section 2, rule 8: with `--adopt-dev-links`, a link that is the user's own and points into the
    known development checkout is swapped for the installer's. The text it had goes into the record. Anything
    else is a conflict (rule 1). Returns whether the name is taken care of."""
    places = b.places
    text = os.readlink(link) if checkout and link.is_symlink() else None
    if (text is not None and link.lstat().st_uid == os.getuid() and places.dev_shaped(ident, text)
            and os.path.realpath(os.path.join(os.path.realpath(link.parent), text))
            == os.path.realpath(places.dev_target(ident, checkout))):
        b.add(actions.swap_link(places, ident, target, "-> %s (take over the development checkout's link)" % target))
        entry["adopted_from"] = text
        return True
    b.conflict(link, "already exists" if not checkout else "already exists and is not your link into %s in the known "
               "shape" % b.env.display(places.dev_target(ident, checkout)))
    return False


def _plan_skill_links(env, b, owned, adopt=None):
    places = b.places
    for provider, home in places.homes.items():
        if not os.path.isdir(home):
            b.note("The %s home %s does not exist; its skill links were not made." % (provider, env.display(home)))
            continue
        skills = home / "skills"
        if not b.ensure_dir(skills):
            continue
        if os.path.realpath(skills) != os.path.abspath(skills):
            b.note("%s is a symlink; its links are placed in %s." % (env.display(skills), os.path.realpath(skills)))
        for name in SKILLS:
            link = skills / name
            ident = "skill:%s:%s" % (provider, name)
            target = places.link_target(ident)
            entry = records.owned(env.display(link), "symlink", target=target, provider=provider)
            if not os.path.lexists(link):
                b.add(actions.new_link(places, ident, target))
            elif _adoptable(env, link, name):
                b.add(actions.swap_link(places, ident, target, "-> %s (adopt the remote runtime's link)" % target))
                entry["adopted"] = True
            elif not _adopt_dev_link(b, link, ident, target, adopt, entry):
                continue
            owned.append(entry)


def _plan_registry_draft(env, b):
    if any(path.is_file() for path in env.registry_candidates):
        return
    if os.path.lexists(env.registry):
        b.conflict(env.registry, "exists and is not a file")
        return
    if b.ensure_dir(env.registry.parent, track=False):
        b.add(actions.new_file(b.places, "registry", b"{}\n", "registry draft"))


def _plan_tmux_block(env, b, new):
    tmux = new["tmux"]
    target = tmuxconf.target(env)
    places = b.places
    reload = "To apply it in a running tmux server: %s" % tmuxconf.RELOAD
    if target is None:
        path = env.tmux_candidates[0]
        b.add(actions.new_file(places, places.tmux_id(path), tmuxconf.BLOCK, "tmux include block"))
        tmux.update(state="inserted", file=env.display(path), created=True)
        b.note(reload)
        return
    display = env.display(target)
    info = os.lstat(target)
    reason = ("a symlink" if target.is_symlink() else "not a regular file" if not target.is_file() else
              tmuxconf.rewrite_problem(target, info))
    if reason:
        tmux.update(state="manual", file=display)
        b.note("%s is %s, so it was not changed. Add this line to the file it points to (or to your tmux "
               "settings):\n    %s" % (display, reason, tmuxconf.SOURCE))
        return
    data = target.read_bytes()
    if tmuxconf.has_block(data):
        tmux.update(state="present", file=display)
        b.note("%s already has a project-agent block that this installer did not add; it is left as it is." % display)
        return
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = "%s-%s" % (stamp, target.name)
    backup = env.backup / name
    if not os.path.lexists(env.backup):
        b.add(actions.mkdir(places, "backup"))
        new["owned"].append(records.owned(env.display(env.backup), "dir"))
    b.add(actions.backup_file(places, name, target, data, stat.S_IMODE(info.st_mode)))
    b.add(actions.append_block(places, places.tmux_id(target), data, tmuxconf.BLOCK, info))
    tmux.update(state="inserted", file=display, created=False, backup=env.display(backup),
                backup_sha256=actions.sha256(data))
    b.note(reload)


# ---------------------------------------------------------------- upgrade and rollback

def _require_record(env):
    installed = records.read(env)
    if installed is None:
        raise InstallerError("not_installed", "project-agent is not installed.")
    return installed


def _require_current(env, installed):
    """`current` must still be the link the installer made; a user's replacement is not ours to swap."""
    entry = records.find_owned(installed, env.display(env.current))
    if (entry is None or not env.current.is_symlink() or os.readlink(env.current) != entry["target"]
            or entry["target"] != "releases/" + installed["current"]):
        raise InstallerError("current_changed", "%s is not the link the installer made. Nothing was changed."
                             % env.display(env.current))


def _changed_notes(env, installed, plan):
    for path, state, _ in records.mismatches(env, installed):
        plan.notes.append("%s is %s; it is left as it is." % (
            path, "missing" if state == "missing" else "not as the installer made it (changed by you)"))


def _switch(env, installed, name, previous):
    new = json.loads(json.dumps(installed))
    new["current"], new["previous"] = name, previous
    if name not in new["releases"]:
        new["releases"].append(name)
    records.find_owned(new, env.display(env.current))["target"] = "releases/" + name
    return new


def _formats_of(env, origin):
    """The format versions of the code a run was started from: a release declares them, a copy that is not a
    release (the frozen copy) is version 1 (release.md 3)."""
    kind, name = origin
    return releases.FROZEN_FORMATS if kind == "other" else releases.read_formats(env.releases / name)


def _require_compatible(env, root, target_root, target_name):
    """Refuse when a run that is up uses code whose format versions differ from the target release's (contract
    7.1 item 5). Nothing is read when no run is up, so the target's declaration is needed only then."""
    slots = runs.run_slots(env, root)
    used = runs.origins_in_use(env, slots)
    if not used:
        return
    target = releases.read_formats(target_root)
    states = {"%s/%s" % (item["project"], item["slot"]): item["state"] for item in runs.live(slots)}
    refused = []
    for origin, labels in sorted(used.items()):
        found = _formats_of(env, origin)
        if found != target:
            where = "release " + origin[1] if origin[0] == "release" else "a copy that is not a release"
            differing = ", ".join("%s %d (target %d)" % (key, found[key], target[key])
                                  for key in releases.FORMAT_KEYS if found[key] != target[key])
            for label in labels:
                project, slot = label.split("/", 1)
                refused.append({"project": project, "slot": slot, "state": states[label],
                                "note": "runs %s: %s" % (where, differing)})
    if refused:
        raise InstallerError("formats_differ", "The target release %s uses other format versions than the runs "
                             "that are up, which would write state, tmux options and CR files in two formats at "
                             "once. Nothing was changed. Restart the runs listed (`agent-session restart --job "
                             "leader` or `--job <CR ID>`) so that they use `current`, then run the command "
                             "again; a run that already uses `current` must be ended instead (`agent-session "
                             "stop`)." % target_name, {"runs": refused})


def plan_upgrade(env, source, python, root):
    installed = _require_record(env)
    _require_current(env, installed)
    places = paths.record_places(env, installed)
    plan = Plan("upgrade", places=places, journal_path=journal.path_for(env))
    if source.name == installed["current"]:
        plan.notes.append("Release %s is already current. Nothing to change." % source.name)
        return plan
    _require_compatible(env, root, source.root, source.name)
    release_dir = env.releases / source.name
    new = _switch(env, installed, source.name, installed["current"])
    python_env = releases.python_env(python)
    if os.path.lexists(release_dir):
        try:
            same = (release_dir / releases.PYTHON_ENV).read_bytes() == python_env
        except OSError:
            same = False
        if not same:
            raise InstallerError("release_conflict", "Release %s exists with another interpreter. Run the "
                                 "installer with the interpreter it was made with, or bump VERSION." % source.name)
        plan.notes.append("Release %s already exists; `current` is pointed at it." % source.name)
    else:
        extra = {releases.PYTHON_ENV: python_env}
        plan.steps.append(actions.build_release(places, source.name, source.files, source.root, extra))
        new["owned"].append(records.owned(env.display(release_dir), "dir",
                                          digest=actions.release_digest(source.files, extra)))
    plan.steps.append(actions.swap_link(places, "current", "releases/" + source.name))
    plan.steps.append(actions.replace_record(places, records.encode(new)))
    _changed_notes(env, installed, plan)
    plan.notes.append("Runs that are up keep the release they started with. Reopen Project Board to use the new "
                      "release.")
    return plan


def plan_rollback(env, root):
    installed = _require_record(env)
    _require_current(env, installed)
    previous = installed.get("previous")
    if not previous or not os.path.isdir(env.releases / previous):
        raise InstallerError("no_previous", "There is no previous release to roll back to.")
    _require_compatible(env, root, env.releases / previous, previous)
    new = _switch(env, installed, previous, installed["current"])
    places = paths.record_places(env, installed)
    plan = Plan("rollback", places=places, journal_path=journal.path_for(env))
    plan.steps.append(actions.swap_link(places, "current", "releases/" + previous))
    plan.steps.append(actions.replace_record(places, records.encode(new)))
    _changed_notes(env, installed, plan)
    plan.notes.append("Runs that are up keep the release they started with. Reopen Project Board to use %s."
                      % previous)
    return plan


# ---------------------------------------------------------------- prune

def plan_prune(env, root):
    """Remove the releases that are neither `current`, `previous`, nor used by a run that is up (contract 7.1
    item 3). Each release goes with its record entry, one after the other, so that a run cut off leaves at most
    one release half removed and the next `prune` finishes it."""
    installed = _require_record(env)
    _require_current(env, installed)
    in_use = runs.releases_in_use(env, runs.run_slots(env, root))
    places = paths.record_places(env, installed)
    plan = Plan("prune", places=places, journal_path=journal.path_for(env))
    for name in installed["releases"]:
        directory = env.releases / name
        reason = ("current" if name == installed["current"] else "previous" if name == installed.get("previous")
                  else "used by " + ", ".join(in_use[name]) if name in in_use else None)
        entry = records.find_owned(installed, env.display(directory))
        if reason:
            plan.notes.append("Kept release %s (%s)." % (name, reason))
        elif os.path.lexists(directory) and (entry is None or entry.get("digest") is None):
            plan.notes.append("Kept release %s: the install record has no listing to check it against." % name)
        elif os.path.lexists(directory) and (os.path.islink(directory) or not os.path.isdir(directory)
                                             or actions.tree_digest(directory) != entry["digest"]):
            plan.notes.append("Kept release %s: it is not as the installer made it (changed by you)." % name)
        else:
            if os.path.lexists(directory):
                plan.steps.append(actions.remove_tree(places, "release:" + name, entry["digest"]))
            else:
                plan.notes.append("Release %s was already gone; it is dropped from the install record." % name)
            plan.steps.append(actions.forget_release(places, name))
    if not plan.steps:
        plan.notes.append("No release to remove.")
        return plan
    plan.notes.append("The install record drops each removed release.")
    socket = os.environ.get("AGENT_SESSION_SOCKET") or None
    if runs.server_option("@project_board_enabled", socket) == "1":
        plan.notes.append("Project Board is on. A Board that started before this may call files of a removed release "
                          "(it answers decisions through `agent-session` in the release it started from); reopen "
                          "Board after pruning.")
    return plan


# ---------------------------------------------------------------- uninstall

def plan_uninstall(env, source_root, socket=None):
    installed = _require_record(env)
    live = runs.blocking(runs.run_slots(env, source_root, socket))
    if live:
        raise InstallerError("runs_alive", "Managed runs are alive or recorded for resume; end them first "
                             "(`agent-session stop`, or `resume` and then `stop`). Nothing was changed.",
                             {"runs": [{"project": item["project"], "slot": item["slot"], "state": item["state"]}
                                       for item in live]})
    places = paths.record_places(env, installed)
    plan = Plan("uninstall", journal_path=journal.path_for(env), places=places)
    removed = set()
    changed = {path for path, _, _ in records.mismatches(env, installed)}
    record_path = env.display(env.record)
    _plan_tmux_removal(env, installed, plan)             # first: a file that changed since the plan stops the run
    after_tmux, restores = len(plan.steps), []
    for entry in installed["owned"]:                     # before anything else was removed
        if entry["path"] == record_path:
            continue
        path = env.expand(entry["path"])
        if entry["path"] in changed:
            if os.path.lexists(path):
                plan.notes.append("%s was changed by you; it is left as it is." % entry["path"])
            continue
        kind, ident = places.identify(path)
        if ident == "backup":
            continue                                    # only the recorded backup file goes, then the directory
        if kind == "tree":
            plan.steps.append(actions.remove_tree(places, ident, entry["digest"]))
        elif kind == "link" and entry.get("adopted_from"):
            restores.append(actions.restore_link(places, ident, entry["target"], entry["adopted_from"]))
            continue                                    # the link stays: its directory is not empty because of it
        elif kind == "link":
            plan.steps.append(actions.remove_link(places, ident, entry["target"]))
        else:
            plan.steps.append(actions.remove_file(places, ident, entry.get("sha256")))
        removed.add(path)
    plan.steps[after_tmux:after_tmux] = restores         # before the release goes: no entry point is left dangling
    tmux = installed["tmux"]
    if any(entry["path"] == env.display(env.backup) for entry in installed["owned"]) and path_exists(env.backup):
        if tmux.get("backup") and path_exists(env.expand(tmux["backup"])):
            name = env.expand(tmux["backup"]).name
            plan.steps.append(actions.remove_file(places, "backup:" + name, tmux.get("backup_sha256")))
            removed.add(env.expand(tmux["backup"]))
        plan.steps.append(actions.remove_dir(places, "backup"))
        if all(env.backup / child in removed for child in os.listdir(env.backup)):
            removed.add(env.backup)
    removed.add(env.record)
    removed.add(plan.journal_path)
    # A directory that holds the journal can only go after it; every other created directory goes before the
    # record, so that a run cut off in between never leaves "a library without a record".
    holding = plan.journal_path.parent
    early, late = [], []
    for text in reversed(installed["created_dirs"]):
        directory = env.expand(text)
        if os.path.isdir(directory) and not directory.is_symlink() and all(
                directory / child in removed for child in os.listdir(directory)):
            (late if directory == holding or directory in holding.parents else early).append(directory)
            removed.add(directory)
    plan.steps += [actions.remove_dir(places, places.dir_id(directory)) for directory in early]
    plan.steps.append(actions.remove_file(places, "record"))     # the record goes after everything it lists
    plan.steps.append(actions.drop_journal(plan.journal_path))
    plan.steps += [actions.remove_dir(places, places.dir_id(directory)) for directory in late]
    _kept_notes(env, plan)
    return plan


def path_exists(path):
    return os.path.lexists(path)


def _plan_tmux_removal(env, installed, plan):
    tmux = installed["tmux"]
    if tmux.get("state") != "inserted":
        return
    path = env.expand(tmux["file"])
    try:
        data, _ = actions.read_user_file(path)
    except OSError:
        data = b""
    if tmuxconf.BLOCK not in data:
        plan.notes.append("The project-agent block was not found in %s; it is left as it is." % tmux["file"])
        return
    places = plan.places
    plan.steps.append(actions.cut_block(places, places.tmux_id(path), data, bool(tmux.get("created"))))


def _kept_notes(env, plan):
    kept = [env.display(env.registry)] if os.path.lexists(env.registry) else []
    plan.notes.append("Not removed (not made by the installer, or not its to remove): %s; the project state under "
                      "<base>/agent/; locks and caches under ~/.cache; the Claude and Codex trust records."
                      % ", ".join(kept + ["your project registry files"]))
    socket = os.environ.get("AGENT_SESSION_SOCKET") or None
    key = runs.server_option("@project_agent_board_key", socket) or "B"
    skipped = runs.server_option("@project_agent_board_skipped", socket)
    plan.notes.append("A running tmux server keeps the bindings and hooks that the integration file set until it "
                      "ends. To remove them now, run:\n"
                      + "\n".join("    " + line for line in binding_undo(key, skipped)))
    if skipped is None:
        plan.notes.append("The tmux server could not be asked which keys were skipped; do not run the line of a "
                          "key that is your own binding.")


HOOKS = ("client-attached", "client-detached", "client-session-changed", "session-window-changed",
         "after-resize-pane")
WINDOW_HOOKS = ("window-created", "window-closed", "pane-died")
MOUSE_DEFAULT = "tmux bind-key -T root MouseDown1Pane select-pane -t = '\\;' send-keys -M"


def binding_undo(key, skipped):
    """The tmux commands that undo the integration file's bindings and hooks (contract 3.1 item 4).
    `skipped` is the server's @project_agent_board_skipped (None when unknown); its keys are not undone."""
    words = (skipped or "").split()
    lines = []
    if "prefix:" + key not in words:
        lines.append("tmux unbind-key -T prefix %s" % key)
    if "root:MouseDown1Pane" not in words:
        lines.append(MOUSE_DEFAULT)
    lines += ["tmux set-hook -gu '%s[project-agent]'" % hook for hook in HOOKS]
    lines += ["tmux set-hook -gwu '%s[project-agent]'" % hook for hook in WINDOW_HOOKS]
    return lines


# ---------------------------------------------------------------- check

def run_check(env):
    """Read-only. Returns (failures, notices): any failure makes the command exit 1."""
    failures, notices = [], []
    pending = journal.find(env)
    if pending:
        failures.append("A run was interrupted (%s). Run any command but `check` to recover it." % env.display(pending))
    installed = records.read(env)
    if installed is None:
        return ["project-agent is not installed (no %s)." % env.display(env.record)], notices
    for path, state, _ in records.mismatches(env, installed):
        failures.append("%s is %s." % (path, "missing" if state == "missing" else
                                       "not as the installer made it (changed by you)"))
    current = env.releases / installed["current"]
    if (not env.current.is_symlink() or os.readlink(env.current) != "releases/" + installed["current"]
            or not current.is_dir()):
        failures.append("%s does not point at the existing release %s." % (env.display(env.current),
                                                                           installed["current"]))
    else:
        failures += _check_entries(env, current)
        notices += _check_textual(current)
        old_tmux = tmuxconf.too_old(current)
        if old_tmux:
            (failures if old_tmux[1] else notices).append(old_tmux[0])
    tmux = installed["tmux"]
    if tmux.get("state") == "inserted":
        path = env.expand(tmux["file"])
        if path.is_symlink() or not path.is_file() or tmuxconf.BLOCK not in path.read_bytes():
            failures.append("The project-agent block is missing from %s." % tmux["file"])
    elif tmux.get("state") == "manual":
        notices.append("Manual connection needed (수동 연결 필요): %s was not changed. Add this line to it: %s"
                       % (tmux["file"], tmuxconf.SOURCE))
    entries = [os.path.realpath(entry) for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    if os.path.realpath(env.bin) not in entries:
        notices.append("%s is not in PATH." % env.display(env.bin))
    skipped = runs.server_option("@project_agent_board_skipped", os.environ.get("AGENT_SESSION_SOCKET") or None)
    if skipped:
        notices.append("Binding skipped (binding 건너뜀): %s are bound to something of yours; the Board keys are "
                       "not set there." % ", ".join(skipped.split()))
    return failures, notices


def _release_python(release):
    try:
        for line in (release / releases.PYTHON_ENV).read_text().splitlines():
            if line.startswith("PROJECT_AGENT_PYTHON="):
                return line.split("=", 1)[1]
    except OSError:
        pass
    return None


def _check_entries(env, release):
    failures = []
    python = _release_python(release)
    child_env = {**os.environ, **({"PROJECT_AGENT_PYTHON": python} if python else {})}
    for tool in TOOLS:
        entry = env.current / "tools" / tool / "bin" / tool
        try:
            ok = subprocess.run([str(entry), "--help"], capture_output=True, timeout=60,
                                env=child_env).returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        if not ok:
            failures.append("The entry point %s does not run." % env.display(entry))
    return failures


def _check_textual(release):
    """Board needs `textual` in the installation's interpreter; a missing package is a notice, not a failure."""
    python = _release_python(release)
    try:
        lines = (release / "tools/project-board/requirements.txt").read_text().splitlines()
        wanted = next(line.strip() for line in lines if line.strip().startswith("textual=="))[len("textual=="):]
    except (OSError, StopIteration):
        return []
    if not python:
        return []
    try:
        result = subprocess.run([python, "-c", "import importlib.metadata as m; print(m.version('textual'))"],
                                capture_output=True, text=True, timeout=30,
                                env={**os.environ, "PYTHONNOUSERSITE": "1"})
        found = result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        found = None
    if found == wanted:
        return []
    return ["Project Board needs textual==%s in %s (%s). Board will not start until it is installed there."
            % (wanted, python, "found " + found if found else "not installed")]
