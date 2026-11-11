"""Managed runs as the installer sees them: which are alive, and which release each one runs.

`uninstall` refuses while a run lives (contract 7.2). `releases_in_use` answers contract 7.1 item 2 and is
the one place that maps a run to its release, for later commands that need it (release cleanup, the
state-format check).
"""

import json
import os
from pathlib import Path
import re
import subprocess
import sys

from .layout import InstallerError


def api_of(source_root):
    """The product's `agent_session.api` (the only module of agent-session the installer imports)."""
    path = str(Path(source_root) / "tools" / "agent-session")
    if path not in sys.path:
        sys.path.insert(0, path)
    from agent_session import api
    return api


def _projects(api, config_path):
    """The registered projects. No registry file at all means no project, hence no run."""
    try:
        return api.load_registry(config_path)
    except api.SessionError as error:
        if error.code == "registry_not_found":
            return ()
        raise InstallerError("registry_unreadable", "Cannot judge the managed runs: the project registry cannot "
                             "be read (%s)." % error.code, {"code": error.code, **error.details}) from error


def run_slots(env, source_root, socket=None):
    """Every slot with a recorded session, for every registered project:
    list of {project, slot, run_id, state}; state is alive, unknown, stopped, or "suspended" (a
    shutdown record names it). Raises InstallerError when a project cannot be judged."""
    api = api_of(source_root)
    config_path = os.environ.get("AGENT_SESSION_CONFIG") or None
    socket = socket or os.environ.get("AGENT_SESSION_SOCKET") or None
    result = []
    for project in _projects(api, config_path):
        if not project.state_path.is_file():
            continue
        try:
            verdicts = api.liveness(cwd=project.base, config_path=config_path, socket=socket)
            control = api.Tmux(socket_path=socket) if socket else api.Tmux()
            suspended = _suspended(project)
        except (api.SessionError, OSError) as error:
            raise InstallerError("run_unjudgeable", "Cannot judge the managed runs of %s." % project.project_id,
                                 {"project": project.project_id, "reason": str(error)}) from error
        for key, verdict in verdicts.items():
            slot = "leader" if key == "leader" else "seat-" + key
            try:
                meta = control.get_current(project.project_id, slot)
            except api.SessionError:
                meta = None
            result.append({"project": project.project_id, "slot": slot, "state": verdict["state"],
                           "run_id": (meta or {}).get("run_id"), "base": str(project.base)})
        for slot in suspended:
            result.append({"project": project.project_id, "slot": slot, "state": "suspended", "run_id": None,
                           "base": str(project.base)})
    return result


def _suspended(project):
    path = project.runtime_path / "suspend.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, UnicodeError, ValueError) as error:
        raise OSError("the shutdown record %s is unreadable: %s" % (path, error)) from error
    if not isinstance(value, dict):
        raise OSError("the shutdown record %s is not an object" % path)
    return sorted(value)


def blocking(slots):
    """The slots that make `uninstall` refuse: alive and unknown runs, and slots a shutdown still records."""
    return [item for item in slots if item["state"] in ("alive", "unknown", "suspended")]


def _run_text(directory):
    """The generated scripts of a run, in the order they are searched."""
    for name in ("launch.sh", "controller.sh", "settings.json"):
        try:
            yield (directory / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue


def origin_of_run(env, base, run_id):
    """Where the code of a run comes from: `("release", name)`, `("other", None)` for a product copy that is not
    a release (the agent repository's frozen copy `.../codex/tools/agent-session`), or None when the run's
    scripts name neither.

    A run's `launch.sh`, `controller.sh` and Claude `settings.json` hold the resolved path of its code."""
    directory = Path(base) / "agent" / "runs" / run_id
    roots = {str(env.releases), str(env.releases.resolve())}
    in_release = re.compile("(?:%s)/([^/\\s'\"]+)/" % "|".join(re.escape(root) for root in roots))
    other = re.compile("/tools/agent-session\\b")
    texts = list(_run_text(directory))
    for text in texts:
        found = in_release.search(text)
        if found:
            return "release", found.group(1)
    return ("other", None) if any(other.search(text) for text in texts) else None


def release_of_run(env, base, run_id):
    """The release name a run's generated scripts call, or None when they name no release."""
    origin = origin_of_run(env, base, run_id)
    return origin[1] if origin and origin[0] == "release" else None


def live(slots):
    """The slots whose run may still call its code: `alive` and `unknown` (contract 7.2)."""
    return [item for item in slots if item["state"] in ("alive", "unknown")]


def origins_in_use(env, slots):
    """{origin: [project/slot, ...]} for the live runs, `origin` as in `origin_of_run`.

    A live slot whose run cannot be traced to its scripts (no run in tmux after a server restart, or scripts
    that name no code) is charged with every run directory of its project: what cannot be told apart is treated
    as used, so that nothing a live run might call is judged unused."""
    used = {}
    for item in live(slots):
        label = "%s/%s" % (item["project"], item["slot"])
        origin = origin_of_run(env, item["base"], item["run_id"]) if item["run_id"] else None
        found = {origin} if origin else set()
        if not found:
            runs = Path(item["base"]) / "agent" / "runs"
            try:
                names = sorted(path.name for path in runs.iterdir() if path.is_dir())
            except OSError:
                names = []
            found = {origin_of_run(env, item["base"], name) for name in names} - {None}
        for origin in found:
            used.setdefault(origin, []).append(label)
    return used


def releases_in_use(env, slots):
    """{release name: [project/slot, ...]} for the runs that have not ended."""
    return {origin[1]: labels for origin, labels in origins_in_use(env, slots).items() if origin[0] == "release"}


def server_option(name, socket=None):
    """A tmux server option of the user's server (AGENT_SESSION_SOCKET, else the default), or None."""
    command = ["tmux"] + (["-S", socket] if socket else []) + ["show-options", "-gqv", name]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None
