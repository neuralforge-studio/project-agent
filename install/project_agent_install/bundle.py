"""The start-up bundle of a release (install contract 6.1, "시동 번들").

One file holds the compiled code of the modules of the three tools and of the standard library modules they
import. An entry point opens it once instead of opening one file per module (tools/bundle_boot.py serves from
it and owns the file layout together with `write` below). The bundle is built for the interpreter that runs
the installer, which is the interpreter `python.env` names; the reader ignores a bundle written by another
build. It lives in `tools/__pycache__` with the name of a bytecode file, so the release digest leaves it out
like the bytecode that compileall adds.
"""

import json
import marshal
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
from importlib.metadata import distribution, packages_distributions
from importlib.util import MAGIC_NUMBER

# Tool directory of a release (relative to its root) -> the package that is the tool.
TOOLS = {"tools/agent-session": "agent_session", "tools/project-item": "project_item", "tools/project-board": "project_board"}

# The packages whose commands import an installed package (textual) when they start: their recorder may also
# record that package's modules (an entry of the bundle that is guarded by the package's metadata directory).
EXTERNAL_USERS = ("project_board",)

# Standard library modules that the tools import when a command runs, not when its program starts: the
# recorder does not see them. `datetime.strptime` imports `_strptime` (and `calendar`) on its first call.
STANDARD_EXTRAS = ("_strptime",)

# Runs in the installing interpreter without the site step: imports every module of the tool, then runs its
# `--help` the way its entry point starts it, as `-m <package>` (the imports that a command makes inside
# functions, such as argparse's, happen there) and prints the directory of the standard library and every module that was loaded
# from a source file (name -> file).
RECORDER = """
import contextlib, importlib, io, json, os, runpy, sys
package = sys.argv[1]
for name in sys.argv[2:]:
    try:
        importlib.import_module(name)
    except Exception:
        pass        # a module that needs a package outside the standard library (project_board.tui)
try:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        sys.argv = [package, "--help"]
        runpy.run_module(package, run_name="__main__", alter_sys=True)
except SystemExit:
    pass
found = {}
for name, module in list(sys.modules.items()):
    origin = getattr(getattr(module, "__spec__", None), "origin", None)
    if origin and origin.endswith(".py"):
        found[name] = origin
json.dump({"standard": os.path.dirname(os.__file__), "modules": found}, sys.stdout)
"""


def bundle_name():
    return "bundle.%s.pyc" % sys.implementation.cache_tag


def _tool_modules(tool_directory, package):
    """{module name: (source file, is_package)} for every source file of the package."""
    modules = {}
    for directory, dirs, files in os.walk(tool_directory / package):
        dirs[:] = [name for name in dirs if name != "__pycache__"]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = Path(directory, name)
            parts = list(path.relative_to(tool_directory).with_suffix("").parts)
            package_init = parts[-1] == "__init__"
            if package_init:
                parts.pop()
            modules[".".join(parts)] = (path, package_init)
    return modules


def _site_directories():
    """The installing interpreter's directories of installed packages (resolved), which `python -S` does not search."""
    paths = {sysconfig.get_paths()[key] for key in ("purelib", "platlib")}
    return sorted({str(Path(path).resolve()) for path in paths if Path(path).is_dir()})


def _start_recorder(tool_directory, package, names):
    # The TUI commands import textual: its directory is on the path of the recorder of the tool that needs it,
    # so that the modules it loads are recorded (the recorder itself runs without the site step).
    path = [str(tool_directory), *(_site_directories() if package in EXTERNAL_USERS else [])]
    return subprocess.Popen([sys.executable, "-S", "-c", RECORDER, package, *names], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            env={**os.environ, "PYTHONPATH": os.pathsep.join(path), "PYTHONNOUSERSITE": "1",
                                 "PYTHONDONTWRITEBYTECODE": "1"})


def _recorded_modules(process, tool_directory):
    try:
        out, err = process.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    if process.returncode:
        raise OSError("cannot list the modules of %s: %s" % (tool_directory, err.strip()))
    return json.loads(out)


def _guards(files):
    """{module name: the metadata directory of the installed package that owns it} for the modules of `files`
    that are in an installed package. The bundle serves such a module only while that directory exists: an
    upgrade or removal of the package names another directory, and the module is imported from the package."""
    owners = packages_distributions()
    guards = {}
    for name in files:
        top = name.split(".")[0]
        for dist in owners.get(top, ()):
            path = getattr(distribution(dist), "_path", None)
            if path is not None and Path(path).is_dir():
                guards[name] = str(Path(path).resolve())
                break
    return guards


def write(path, entries):
    """`entries`: {module name: (source file, name the code reports, origin to record, is_package[, guard])}.
    A `guard` is the absolute path of a directory the module's code is valid for (see `_guards`)."""
    index, blobs, offset = {}, [], 0
    for name, (source, filename, origin, is_package, *guard) in sorted(entries.items()):
        code = compile(Path(source).read_bytes(), filename, "exec", dont_inherit=True, optimize=0)
        blob = marshal.dumps(code)
        index[name] = (offset, len(blob), is_package, origin, *guard)
        blobs.append(blob)
        offset += len(blob)
    header = marshal.dumps((MAGIC_NUMBER, sys.version, index))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(len(header).to_bytes(4, "little") + header + b"".join(blobs))


def build(release, final):
    """Write the bundle into the release directory `release`, which will be renamed to `final` (the code
    objects name the final paths, like the bytecode that compileall writes). It holds every module of the three
    tools, so that a tool that imports another tool's package while a command runs finds it there, and the
    standard library modules that each tool loads when it starts."""
    tools, final_tools = Path(release, "tools"), Path(final, "tools")
    entries, standard_files, installed_files, recorders = {}, {}, {}, []
    sites = [path + os.sep for path in _site_directories()]
    for tool, package in TOOLS.items():          # the three recorders run at the same time
        tool_directory = Path(release, tool)
        own = _tool_modules(tool_directory, package)
        for name, (source, is_package) in own.items():
            relative = source.relative_to(tools)
            entries[name] = (source, str(final_tools / relative), relative.as_posix(), is_package)
        importable = [name for name in own if not name.endswith(".__main__")] + list(STANDARD_EXTRAS)
        recorders.append((tool_directory, _start_recorder(tool_directory, package, importable)))
    try:
        for tool_directory, process in recorders:
            loaded = _recorded_modules(process, tool_directory)
            standard = loaded["standard"] + os.sep
            for name, origin in loaded["modules"].items():
                if origin.startswith(standard) and "site-packages" not in origin and "lib-dynload" not in origin:
                    standard_files[name] = origin
                elif any(origin.startswith(site) for site in sites):
                    installed_files[name] = origin
    finally:
        for _, process in recorders:
            if process.poll() is None:
                process.kill()
                process.communicate()
    for name, origin in standard_files.items():
        if name not in entries:
            entries[name] = (origin, origin, origin, Path(origin).name == "__init__.py")
    guards = _guards(installed_files)
    for name, origin in installed_files.items():
        if name not in entries and name in guards:
            entries[name] = (origin, origin, origin, Path(origin).name == "__init__.py", guards[name])
    write(tools / "__pycache__" / bundle_name(), entries)
