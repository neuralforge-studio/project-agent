"""Load the project registry and select a project from the caller's path."""

from dataclasses import dataclass
import json
from pathlib import Path

from .errors import SessionError


@dataclass(frozen=True)
class Project:
    base: Path
    base_path_key: str
    project_id: str
    provider: str
    seats: tuple[Path, ...]
    config_path: Path
    path_cr: Path | None = None
    path_decide: Path | None = None
    launch_args: tuple[str, ...] = ()      # provider CLI arguments of every session (launch.args)
    leader_args: tuple[str, ...] = ()      # appended for the Leader (launch.leader_args)
    worker_args: tuple[str, ...] = ()      # appended for every Worker (launch.worker_args)

    def args_for(self, role):
        """Provider CLI arguments of a leader or worker session: the common args, then the role's."""
        return self.launch_args + (self.leader_args if role == "leader" else self.worker_args)

    @property
    def state_path(self):
        return self.base / "agent" / "state.json"

    @property
    def runtime_path(self):
        return self.base / "agent"


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate registry key: {key}")
        result[key] = value
    return result


def registry_path(config_path=None):
    """Choose one registry file without merging separate user inputs."""
    if config_path is not None:
        path = Path(config_path).expanduser()
        if not path.is_file():
            raise SessionError("registry_not_found", "The selected project registry is unavailable.", 2,
                               {"path": str(path)})
        return path.resolve()
    candidates = [Path.home() / tool / "project.json" for tool in (".codex", ".claude")]
    existing = [path for path in candidates if path.is_file()]
    if not existing:
        raise SessionError("registry_not_found", "Register projects in ~/.codex/project.json or ~/.claude/project.json.", 2)
    if len(existing) == 2:
        try:
            same = existing[0].samefile(existing[1])
        except OSError as exc:
            raise SessionError("registry_unavailable", "Cannot compare the project registries.", 5) from exc
        if not same:
            raise SessionError("registry_ambiguous", "Use --config when the two standard registry paths are separate files.", 2,
                               {"paths": [str(path) for path in existing]})
    return existing[0].resolve()


REQUIRED_KEYS = {"project", "provider", "seats"}
# Optional item roots of the project-item skill. They never take part in project selection.
ITEM_KEYS = ("path_cr", "path_decide")
# Optional launch declaration for the provider CLI: args for every session, then
# leader_args or worker_args for that role. At least one of the three is present.
LAUNCH_KEY = "launch"
LAUNCH_ARG_KEYS = ("args", "leader_args", "worker_args")
# Arguments that the common runtime sets for registration and the new conversation.
RESERVED_ARGS = {"--remote", "--cd", "--session-id", "--settings", "--append-system-prompt-file",
                 "-n", "--name", "--resume", "--continue"}


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and not any(c in value for c in "\x00\n\r")


def _path(value, base):
    """Resolve a registered path: absolute, ~/, or relative to the base."""
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def _overlap(first, second):
    return first == second or first in second.parents or second in first.parents


def _launch_args(value, base_key):
    def bad(message):
        raise SessionError("registry_invalid", f"launch: {message}", 2, {"base": base_key})

    if not isinstance(value, dict) or not value or set(value) - set(LAUNCH_ARG_KEYS):
        bad("use an object with only args, leader_args and worker_args.")
    result = {}
    for key in LAUNCH_ARG_KEYS:
        args = value.get(key, [])
        if not isinstance(args, list) or not all(_text(arg) for arg in args):
            bad(f"{key} must be nonempty strings.")
        if any(arg.split("=", 1)[0] in RESERVED_ARGS for arg in args):
            bad(f"{key} must not set the arguments that the common runtime owns.")
        result[key] = tuple(args)
    return result


def load_registry(config_path=None):
    """Return validated projects. Unused seat directories may be absent."""
    path = registry_path(config_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object)
    except (OSError, UnicodeError, ValueError) as exc:
        raise SessionError("registry_invalid", "Cannot read a valid project registry.", 2,
                           {"path": str(path), "reason": str(exc)}) from exc
    if not isinstance(raw, dict):
        raise SessionError("registry_invalid", "The project registry must be an object of base entries.", 2)
    projects = []
    names = set()
    roots = {}
    item_roots = []
    for base_key, entry in raw.items():
        if not _text(base_key) or not (Path(base_key).is_absolute() or base_key.startswith("~/")):
            raise SessionError("registry_invalid", "Each base key must be an absolute path or start with ~/.", 2)
        if (not isinstance(entry, dict) or not REQUIRED_KEYS <= set(entry)
                or set(entry) - REQUIRED_KEYS - set(ITEM_KEYS) - {LAUNCH_KEY}):
            raise SessionError("registry_invalid", "Each project entry must contain project, provider, and seats, "
                               "and may add only path_cr, path_decide and launch.", 2, {"base": base_key})
        name, provider, seats = entry["project"], entry["provider"], entry["seats"]
        if not _text(name) or name in names:
            raise SessionError("registry_invalid", "Project names must be nonempty and unique.", 2)
        if provider not in ("claude", "codex"):
            raise SessionError("registry_invalid", "The provider must be claude or codex.", 2)
        if not isinstance(seats, list) or not all(_text(seat) for seat in seats):
            raise SessionError("registry_invalid", "Seats must be an array of nonempty paths.", 2)
        base = Path(base_key).expanduser().resolve()
        resolved_seats = tuple(_path(seat, base) for seat in seats)
        for root in (base,) + resolved_seats:
            if root in roots:
                raise SessionError("project_ambiguous", "A base or seat path is registered more than once.", 2,
                                   {"path": str(root), "projects": [roots[root], name]})
            roots[root] = name
        items = {}
        for key in ITEM_KEYS:
            if key not in entry:
                continue
            if not _text(entry[key]):
                raise SessionError("registry_invalid", f"{key} must be a nonempty path.", 2, {"base": base_key})
            items[key] = _path(entry[key], base)
            for other, owner, other_key in item_roots:
                if _overlap(items[key], other):
                    raise SessionError("registry_invalid", "Item paths must not be equal or nested.", 2,
                                       {"path": str(items[key]), "other": str(other),
                                        "items": [f"{owner}.{other_key}", f"{name}.{key}"]})
            item_roots.append((items[key], name, key))
        launch = _launch_args(entry[LAUNCH_KEY], base_key) if LAUNCH_KEY in entry else {}
        names.add(name)
        projects.append(Project(base, base_key, name, provider, resolved_seats, path, **items,
                                launch_args=launch.get("args", ()), leader_args=launch.get("leader_args", ()),
                                worker_args=launch.get("worker_args", ())))
    return tuple(projects)


def resolve_project(cwd=None, config_path=None):
    """Select the deepest registered path that contains the current directory."""
    try:
        current = Path.cwd() if cwd is None else Path(cwd).expanduser()
        current = current.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SessionError("cwd_unavailable", "The current directory is unavailable.", 2) from exc
    if not current.is_dir():
        raise SessionError("cwd_unavailable", "The selected working path is not a directory.", 2)
    matches = []
    for project in load_registry(config_path):
        for root in (project.base,) + project.seats:
            if current == root or root in current.parents:
                matches.append((len(root.parts), project))
    if not matches:
        raise SessionError("project_not_found", "The current directory is outside every registered base and seat.", 2,
                           {"cwd": str(current)})
    depth = max(item[0] for item in matches)
    deepest = {item[1] for item in matches if item[0] == depth}
    if len(deepest) != 1:
        raise SessionError("project_ambiguous", "The working directory matches more than one project.", 2)
    project = deepest.pop()
    if not project.base.is_dir():
        raise SessionError("base_unavailable", "The registered project base is unavailable.", 3,
                           {"base": str(project.base)})
    return project
