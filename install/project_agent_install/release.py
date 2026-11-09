"""The source tree of a release: which files go in, the version, and the commit that names it."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import sysconfig

from .layout import InstallerError

PRODUCT_DIRS = ("tools", "skills", "docs", "integrations", "install")
VERSION_PATTERN = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+~-]*")
HASH_LENGTH = 12
PYTHON_ENV = "tools/python.env"
FORMATS = "tools/formats.json"
FORMAT_KEYS = ("agent_session", "tmux_options", "item_files")
# The format versions of a product copy that is not a release: the agent repository's frozen copy (release.md 3).
FROZEN_FORMATS = {key: 1 for key in FORMAT_KEYS}
MINIMUM_PYTHON = (3, 10)


def included(relative):
    """Whether a tracked file of the repository belongs to a release (contract: product paths and root
    documents; no tests, `__pycache__`, or `docs/cr`)."""
    parts = relative.split("/")
    if len(parts) == 1:
        return True
    if parts[0] not in PRODUCT_DIRS or relative.startswith("docs/cr/"):
        return False
    if any(part in ("tests", "__pycache__") for part in parts[:-1]):
        return False
    name = parts[-1]
    return not ((name.startswith("test_") and name.endswith(".py")) or name == "conftest.py")


@dataclass(frozen=True)
class Source:
    root: Path
    version: str
    commit: str
    files: tuple

    @property
    def name(self):
        return "%s-%s" % (self.version, self.commit[:HASH_LENGTH])


def _git(root, *args):
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=60,
                                env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    except (OSError, subprocess.SubprocessError) as error:
        raise InstallerError("git_unavailable", "Cannot run git: %s" % error) from error
    if result.returncode:
        raise InstallerError("source_not_git", "The release source is not a Git work tree.",
                             {"source": str(root), "git": result.stderr.decode(errors="replace").strip()})
    return result.stdout


def load_source(root):
    """Read the source tree. Refuses a tree without `VERSION` and a tree whose release files differ
    from the commit (changed or untracked), because the release is named by the commit alone."""
    root = Path(root).resolve()
    if not (root / ".git").exists():
        raise InstallerError("source_not_git", "The release source is not a Git work tree. Run the installer "
                             "from a checkout, or pass --source.", {"source": str(root)})
    version_file = root / "VERSION"
    try:
        lines = version_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise InstallerError("version_missing", "The source has no readable VERSION file.",
                             {"source": str(root)}) from error
    version = lines[0].strip() if lines else ""
    if not VERSION_PATTERN.fullmatch(version):
        raise InstallerError("version_invalid", "The first line of VERSION is not a version.",
                             {"source": str(root), "version": version})
    commit = _git(root, "rev-parse", "HEAD").decode().strip()
    tracked = [name.decode() for name in _git(root, "ls-files", "-z").split(b"\0") if name]
    dirty = []
    for entry in _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").split(b"\0"):
        entry = entry.decode(errors="replace")
        if len(entry) > 3 and included(entry[3:]):
            dirty.append(entry[3:])
    if dirty:
        raise InstallerError("source_dirty", "The release files differ from the commit %s; commit or restore "
                             "them first." % commit[:HASH_LENGTH], {"files": sorted(dirty)[:20], "count": len(dirty)})
    files = tuple(sorted(name for name in tracked if included(name)))
    if "VERSION" not in files or not any(name.startswith("tools/agent-session/") for name in files):
        raise InstallerError("source_invalid", "The source tree is not a project-agent checkout.",
                             {"source": str(root)})
    return Source(root, version, commit, files)


def read_formats(root):
    """The format versions a source tree or a release declares in `tools/formats.json` (the one declaration,
    release.md 3). A file that is missing or not the three integers is an error."""
    path = Path(root) / FORMATS
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        ok = (isinstance(value, dict) and set(value) == set(FORMAT_KEYS)
              and all(type(number) is int and number > 0 for number in value.values()))
    except (OSError, UnicodeError, ValueError):
        ok = False
    if not ok:
        raise InstallerError("formats_unreadable", "%s is missing or does not declare the three format versions; "
                             "the format of that release cannot be judged." % path, {"path": str(path)})
    return value


PROBE_ENV = {"PATH": "/usr/bin:/bin"}
PROBE_CODE = "import sys; print(sys.prefix)"


def prefix_in_empty_environment(python, library_path=""):
    """`sys.prefix` of `python` started with an empty environment (only `library_path` as LD_LIBRARY_PATH).
    None when it does not start."""
    env = {**PROBE_ENV, **({"LD_LIBRARY_PATH": library_path} if library_path else {})}
    try:
        result = subprocess.run([python, "-c", PROBE_CODE], capture_output=True, text=True, timeout=30, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def python_env(python, prefix, library_path="", python_path=""):
    """The release's `tools/python.env` (contract section 6.1). The launcher reads the first three names;
    `PROJECT_AGENT_PYTHON_PREFIX` is what `check` compares the running interpreter with."""
    return ("PROJECT_AGENT_PYTHON=%s\nPROJECT_AGENT_PYTHONPATH=%s\nPROJECT_AGENT_LD_LIBRARY_PATH=%s\n"
            "PROJECT_AGENT_PYTHON_PREFIX=%s\n" % (python, python_path, library_path, prefix)).encode()


def installer_python():
    """The interpreter that runs the installer is the one the release will use. Returns `(path, prefix,
    library_path)`: the `sys.prefix` it runs with here, and the library directory it needs to start with that
    same `sys.prefix` in an empty environment (empty when it needs none). Contract section 6.1."""
    if sys.version_info < MINIMUM_PYTHON:
        raise InstallerError("python_version", "Python 3.10 or later is required.")
    python = os.path.abspath(sys.executable)
    candidates = [""]
    for directory in (os.path.join(sys.prefix, "lib"), sysconfig.get_config_var("LIBDIR")):
        if directory and directory not in candidates and os.path.isdir(directory):
            candidates.append(directory)
    for library_path in candidates:
        if prefix_in_empty_environment(python, library_path) == sys.prefix:
            return python, sys.prefix, library_path
    raise InstallerError("python_environment", "%s does not start as the interpreter that runs the installer "
                         "(sys.prefix %s) in an empty environment, with or without its library directory (%s). "
                         "Entry points would run another Python. Nothing was changed."
                         % (python, sys.prefix, ", ".join(candidates[1:]) or "none found"))
