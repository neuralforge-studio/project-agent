"""Public project registration boundary for the project tools.

The config module remains the single parser and model owner. Consumers may load all
projects, resolve a working directory, or select a registered name through this module.
These reads do not load providers or control a session.
"""

from .config import Project, RemoteSeat, load_registry, registry_path, resolve_project
from .errors import SessionError

__all__ = ["Project", "RemoteSeat", "SessionError", "load_registry", "registry_path",
           "resolve_project", "find_project", "select_project"]


def find_project(config_path, project_id: str) -> Project | None:
    """Return the named registration, or None; invalid registries still raise SessionError."""
    return next((project for project in load_registry(config_path)
                 if project.project_id == project_id), None)


def select_project(config_path=None, project_id=None, cwd=None) -> Project:
    """Select the named registration, or use the existing working-directory rule."""
    if project_id is None:
        return resolve_project(cwd, config_path)
    project = find_project(config_path, project_id)
    if project is None:
        raise SessionError("project_not_found", f"No registered project is named '{project_id}'.", 2)
    return project
