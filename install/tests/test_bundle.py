"""PERF-003: the start-up bundle of a release (install-contract.md 6.1, "시동 번들").

The installer writes one file with the compiled modules of the three tools and of the standard library modules
they import; the entry points import from it instead of opening a file per module. The cases below run the
installed release the way a user does.
"""

import marshal
import os
import shutil
from pathlib import Path
import subprocess
import sys
import sysconfig

import pytest

from harness import LIB, command_timeout

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from project_agent_install import bundle as bundles  # noqa: E402

ENTRIES = {"agent-session": "agent_session", "project-item": "project_item", "project-board": "project_board"}
# The commands that start from the bundle (project-board's TUI commands import textual from site-packages).
HELP = {"agent-session": ["--help"], "project-item": ["--help"], "project-board": ["sync", "--help"]}


@pytest.fixture(scope="module")
def release(tmp_path_factory, product_repository):
    """The product released by the installer into an isolated HOME: the directory of the release."""
    from harness import Home
    home = Home()
    result = home.run("install", source=product_repository)
    assert result.returncode == 0, result.stderr
    directory = (home.path(LIB + "/current")).resolve()
    yield directory, home
    home.close()


def bundle_path(directory):
    return directory / "tools" / "__pycache__" / bundles.bundle_name()


def python_in(directory, home, program, *arguments):
    """`program` in the release's interpreter after the bundle reader, as an entry point starts it."""
    boot = (directory / "tools" / "bundle_boot.py").read_text()
    return subprocess.run([sys.executable, "-S", "-c", "import sys\n" + boot + "\n_project_agent_bundle(sys.argv.pop(1))\n" + program,
                           str(directory / "tools"), *arguments], capture_output=True, text=True, timeout=command_timeout(), env=home.env)


def index_of(path):
    data = path.read_bytes()
    size = int.from_bytes(data[:4], "little")
    return marshal.loads(data[4:4 + size])


def test_the_release_has_one_bundle_for_the_installing_interpreter(release):
    directory, _ = release
    magic, version, modules = index_of(bundle_path(directory))
    assert version == sys.version
    assert {"agent_session.cli", "project_item.cli", "project_board.model", "json", "argparse", "_strptime"} <= set(modules)
    own = modules["agent_session.cli"]
    assert own[3] == "agent-session/agent_session/cli.py" and not own[2]
    assert modules["agent_session"][2] and modules["json"][3].startswith("/")


def test_the_bundle_holds_every_module_of_the_three_tools(release):
    directory, _ = release
    modules = index_of(bundle_path(directory))[2]
    for tool, package in ENTRIES.items():
        for source in (directory / "tools" / tool / package).rglob("*.py"):
            relative = source.relative_to(directory / "tools").as_posix()
            assert relative in {entry[3] for entry in modules.values()}, relative


def test_modules_come_from_the_bundle_and_keep_their_files(release):
    directory, home = release
    program = ("import sys, json, agent_session.cli, project_item.cli, wave\n"
               "for module in (json, agent_session.cli, project_item.cli, wave):\n"
               "    print(type(module.__spec__.loader).__name__, module.__file__)\n"
               "print(agent_session.cli.main.__code__.co_filename)\n")
    result = python_in(directory, home, program)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert [line.split()[0] for line in lines[:4]] == ["BundleFinder", "BundleFinder", "BundleFinder", "SourceFileLoader"]
    assert lines[1].split()[1] == str(directory / "tools/agent-session/agent_session/cli.py")
    assert lines[2].split()[1] == str(directory / "tools/project-item/project_item/cli.py")
    assert lines[4] == lines[1].split()[1]                      # tracebacks name the file that is there
    assert lines[0].split()[1] == os.path.join(os.path.dirname(os.__file__), "json", "__init__.py")


def test_a_package_of_the_bundle_still_finds_the_modules_that_are_not_in_it(release):
    directory, home = release
    result = python_in(directory, home, "import json, json.tool\nprint(type(json.tool.__spec__.loader).__name__)\n")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["SourceFileLoader"]       # json.tool is not imported by the tools


def test_the_entry_points_run_from_the_bundle_not_from_the_sources(release):
    """Changing a module's source after the bundle was written changes nothing: the code is the bundle's."""
    directory, home = release
    for tool, package in ENTRIES.items():
        source = directory / "tools" / tool / package / "cli.py"
        mode = source.stat().st_mode
        source.chmod(0o644)
        saved = source.read_bytes()
        source.write_bytes(b"raise SystemExit('the source file was read')\n")
        try:
            result = subprocess.run([str(directory / "tools" / tool / "bin" / tool), *HELP[tool]], capture_output=True, text=True,
                                    timeout=command_timeout(), env=home.env)
        finally:
            source.write_bytes(saved)
            source.chmod(mode)
        assert result.returncode == 0 and "usage" in result.stdout.lower(), (tool, result.stdout, result.stderr)


def damaged(directory, tmp_path, change):
    """A copy of the bundle of `directory` whose header was passed through `change`, in a tools directory of its own."""
    tools = tmp_path / "tools"
    (tools / "__pycache__").mkdir(parents=True)
    data = bundle_path(directory).read_bytes()
    size = int.from_bytes(data[:4], "little")
    header = marshal.dumps(change(*marshal.loads(data[4:4 + size])))
    (tools / "__pycache__" / bundles.bundle_name()).write_bytes(len(header).to_bytes(4, "little") + header + data[4 + size:])
    return tools


@pytest.mark.parametrize("what", ["magic", "version", "none"])
def test_a_bundle_of_another_interpreter_or_none_leaves_the_ordinary_import(release, tmp_path, what):
    directory, home = release
    tools = {"magic": lambda: damaged(directory, tmp_path, lambda magic, version, modules: (b"\0\0\0\0", version, modules)),
             "version": lambda: damaged(directory, tmp_path, lambda magic, version, modules: (magic, version + "x", modules)),
             "none": lambda: tmp_path}[what]()
    boot = (directory / "tools" / "bundle_boot.py").read_text()
    program = boot + "\n_project_agent_bundle(sys.argv[1])\nimport json\nprint(type(json.__spec__.loader).__name__)\n"
    result = subprocess.run([sys.executable, "-S", "-c", "import sys\n" + program, str(tools)], capture_output=True, text=True,
                            timeout=command_timeout(), env=home.env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["SourceFileLoader"]


def test_optimized_interpreters_do_not_use_the_bundle(release):
    directory, home = release
    boot = (directory / "tools" / "bundle_boot.py").read_text()
    program = boot + "\n_project_agent_bundle(sys.argv[1])\nimport json\nprint(type(json.__spec__.loader).__name__)\n"
    result = subprocess.run([sys.executable, "-S", "-O", "-c", "import sys\n" + program, str(directory / "tools")],
                            capture_output=True, text=True, timeout=command_timeout(), env=home.env)
    assert result.stdout.split() == ["SourceFileLoader"], result.stderr


# BOARD-025: the two windows of project-board (`cr`, `popup`) start `python -S` too and import textual and what it
# imports from the bundle. Those modules belong to an installed package: each entry names the package's metadata
# directory and is served only while that directory exists.
SITE = "sys.path.append(%r)\n" % sysconfig.get_paths()["purelib"]
TUI = "import project_board.tui, textual.app\nprint(*(type(m.__spec__.loader).__name__ for m in (textual.app, project_board.tui)))\n"


def test_the_bundle_holds_the_modules_of_the_tui_with_the_metadata_directory_that_guards_each(release):
    directory, _ = release
    modules = index_of(bundle_path(directory))[2]
    for name in ("textual.app", "textual.widgets", "rich.markup", "markdown_it", "project_board.tui"):
        assert name in modules, name
    guarded = {name: entry[4] for name, entry in modules.items() if len(entry) > 4}
    assert guarded["textual.app"].endswith(".dist-info") and os.path.isdir(guarded["textual.app"])
    assert guarded["rich.markup"].endswith(".dist-info")
    assert not any(name.split(".")[0] in ("agent_session", "project_item", "project_board", "json") for name in guarded)


def test_the_tui_imports_textual_from_the_bundle(release):
    directory, home = release
    result = python_in(directory, home, "import sys\n" + SITE + TUI)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["BundleFinder", "BundleFinder"]


def test_a_package_that_was_upgraded_or_removed_is_imported_from_where_it_is_installed(release, tmp_path):
    """The guard of every installed module names a directory that does not exist (the package changed after the
    release was made): the bundle serves none of them."""
    directory, home = release
    tools = damaged(directory, tmp_path, lambda magic, version, modules: (
        magic, version, {name: (*entry[:4], "/nonexistent.dist-info") if len(entry) > 4 else entry
                         for name, entry in modules.items()}))
    boot = (directory / "tools" / "bundle_boot.py").read_text()
    result = subprocess.run([sys.executable, "-S", "-c", "import sys\n" + boot + "\n_project_agent_bundle(sys.argv[1])\n" + SITE
                             + "import textual.app\nprint(type(textual.app.__spec__.loader).__name__)\n", str(tools)],
                            capture_output=True, text=True, timeout=command_timeout(), env=home.env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["SourceFileLoader"]


# PERF-004: the processes of the generated commands (registration hook, `mark_process`, controller) start as
# `python -S -c "import sys; sys.path.insert(0, library); from agent_session.internal import ..."`: no reader is
# installed before that import, so `agent_session/__init__.py` installs it.
GENERATED = ("import sys; sys.path.insert(0, sys.argv[1]); from agent_session.internal import register_from_hook\n"
             "import json\n"
             "print(*(type(m.__spec__.loader).__name__ for m in (sys.modules['agent_session'], sys.modules['agent_session.internal'],\n"
             "                                                 sys.modules['agent_session.state'], json)))\n"
             "print(sum(getattr(finder, 'project_agent_bundle', False) for finder in sys.meta_path))\n")


def generated_command(tools, tmp_path, home):
    return subprocess.run([sys.executable, "-S", "-c", GENERATED, str(tools / "agent-session")], capture_output=True, text=True,
                          timeout=command_timeout(), env=home.env, cwd=tmp_path)


def test_a_generated_command_imports_the_internal_entry_from_the_bundle(release, tmp_path):
    directory, home = release
    result = generated_command(directory / "tools", tmp_path, home)
    assert result.returncode == 0, result.stderr
    # `agent_session` itself is read from its file: the reader is installed by the first line of that file.
    assert result.stdout.split("\n")[:2] == ["SourceFileLoader BundleFinder BundleFinder BundleFinder", "1"]


def test_the_entry_point_of_the_cli_installs_one_reader_and_the_package_does_not_install_another(release):
    directory, home = release
    program = "import agent_session.cli\nprint(sum(getattr(finder, 'project_agent_bundle', False) for finder in sys.meta_path))\n"
    result = python_in(directory, home, "import sys\n" + program.replace("import agent_session.cli", "sys.path.insert(0, %r)\nimport agent_session.cli"
                                                                         % str(directory / "tools" / "agent-session")))
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["1"]


def test_a_generated_command_without_a_bundle_imports_the_modules_as_always(release, tmp_path):
    directory, home = release
    tools = tmp_path / "tools-without-bundle"
    shutil.copytree(directory / "tools", tools, ignore=shutil.ignore_patterns("__pycache__"))
    result = generated_command(tools, tmp_path, home)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split("\n")[:2] == ["SourceFileLoader SourceFileLoader SourceFileLoader SourceFileLoader", "0"]


def test_a_generated_command_beside_no_reader_imports_the_modules_as_always(release, tmp_path):
    """The remote runtime's copy of the package has no `bundle_boot.py` beside it."""
    directory, home = release
    tools = tmp_path / "remote-tools"
    shutil.copytree(directory / "tools" / "agent-session", tools / "agent-session", ignore=shutil.ignore_patterns("__pycache__"))
    result = generated_command(tools, tmp_path, home)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split("\n")[:2] == ["SourceFileLoader SourceFileLoader SourceFileLoader SourceFileLoader", "0"]
