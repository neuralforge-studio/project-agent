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


def _api(source_root):
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
    api = _api(source_root)
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


def release_of_run(env, base, run_id):
    """The release name a run's generated scripts call, or None when they name no release.

    A run's `launch.sh`, `controller.sh` and Claude `settings.json` hold the resolved release path."""
    directory = Path(base) / "agent" / "runs" / run_id
    roots = {str(env.releases), str(env.releases.resolve())}
    pattern = re.compile("(?:%s)/([^/\\s'\"]+)/" % "|".join(re.escape(root) for root in roots))
    for name in ("launch.sh", "controller.sh", "settings.json"):
        try:
            text = (directory / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = pattern.search(text)
        if found:
            return found.group(1)
    return None


def releases_in_use(env, slots):
    """{release name: [project/slot, ...]} for the runs that have not ended."""
    used = {}
    for item in slots:
        if item["state"] == "stopped" or not item["run_id"]:
            continue
        release = release_of_run(env, item["base"], item["run_id"])
        if release:
            used.setdefault(release, []).append("%s/%s" % (item["project"], item["slot"]))
    return used


def server_option(name, socket=None):
    """A tmux server option of the user's server (AGENT_SESSION_SOCKET, else the default), or None."""
    command = ["tmux"] + (["-S", socket] if socket else []) + ["show-options", "-gqv", name]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None
