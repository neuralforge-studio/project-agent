"""The acceptance harness of docs/project-team/install-contract.md section 8.1.

Every run uses an isolated HOME. A snapshot walks HOME (TMPDIR lives inside it) without following
symlinks; the expectation of each case is written from the contract, never read from the install record.
Later installer CRs add cases by importing this module.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "tests"))  # tmux_test_server, shared by every tool's tests
import tmux_test_server  # noqa: E402
# PROJECT_AGENT_INSTALLER points the tests at another copy of the installer (to show that a test fails on an
# older one); by default it is the checkout's.
INSTALLER = Path(os.environ.get("PROJECT_AGENT_INSTALLER") or REPO / "install" / "project-agent-install")
LIB = ".local/lib/project-agent"
# The names the contract gives (section 2). Written here, not imported from the installer.
SHIMS = (".local/bin/agent-session", ".local/bin/project-item", ".local/bin/project-board")
CLAUDE_LINKS = (".claude/skills/project-team", ".claude/skills/project-item")
CODEX_LINKS = (".codex/skills/project-team", ".codex/skills/project-item")
REGISTRY_DRAFT = ".config/project-agent/project.json"
BLOCK = (b"\n# >>> project-agent (managed block, do not edit) >>>\n"
         b"source-file -q ~/.local/lib/project-agent/tmux.conf\n# <<< project-agent <<<\n")
TMUX_CONF = b"source-file -q ~/.local/lib/project-agent/current/integrations/tmux/project-agent.conf\n"
OLD = 1_600_000_000_000_000_000       # mtime_ns of the user's files: far from "now"

GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60,
                            env={**os.environ, **GIT_ENV})
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _ignored(directory, names):
    """What a copy of the product leaves out: caches, the CR files, and the Rust crate's `target/` build output."""
    skipped = set(shutil.ignore_patterns("__pycache__", ".pytest_cache", "cr")(directory, names))
    if Path(directory) == REPO / "tools" / "project-board" / "rust":
        skipped |= {"target"} & set(names)
    return skipped


def build_product_repository(target):
    """A Git repository of the product as it is in this checkout (committed or not), with a VERSION."""
    target.mkdir(parents=True)
    for name in ("tools", "skills", "docs", "integrations", "install"):
        shutil.copytree(REPO / name, target / name, symlinks=True, ignore=_ignored)
    for name in ("README.md", "AGENTS.md"):
        shutil.copy2(REPO / name, target / name)
    (target / "VERSION").write_text("1.0.0\n")
    git(target, "init", "-q", "-b", "main")
    git(target, "add", "-A")
    git(target, "commit", "-q", "-m", "product")
    return target


def commit_change(source, version):
    """A new commit with a new VERSION and one changed product file, so an upgrade has a new release."""
    (source / "VERSION").write_text(version + "\n")
    notes = source / "docs" / "project-team" / "README.md"
    notes.write_text(notes.read_text() + "\nchanged for %s\n" % version)
    git(source, "add", "-A")
    git(source, "commit", "-q", "-m", "change " + version)


def release_name(source):
    version = (Path(source) / "VERSION").read_text().splitlines()[0].strip()
    return "%s-%s" % (version, git(source, "rev-parse", "HEAD")[:12])


# A cargo that stands in for the real one in most tests (the real build takes about a minute). Like cargo it gets
# `build --release --offline --locked --target-dir DIR` in the crate directory and leaves a program at
# DIR/release/project-board-sidebar; that program answers `--version`. FAKE_CARGO_MODE: ok (default), fail (exit
# code 101 with a message on stderr), nobinary (exit code 0 and no program). FAKE_CARGO_LOG gets one line per call.
FAKE_CARGO = '''\
#!/bin/sh
printf 'cwd=%s cargo_home=%s args=%s files=%s\\n' "$PWD" "${CARGO_HOME:-}" "$*" "$(ls -A "$PWD" | tr '\\n' ' ')" \\
    >> "${FAKE_CARGO_LOG:-/dev/null}"
target=
previous=
for argument in "$@"; do
    [ "$previous" = --target-dir ] && target=$argument
    previous=$argument
done
case "${FAKE_CARGO_MODE:-ok}" in
    fail) echo "error: could not compile project-board-sidebar" >&2; echo "FAKE-CARGO-REASON: no space left" >&2; exit 101;;
    nobinary) exit 0;;
esac
[ -n "$target" ] || { echo "the fake cargo needs --target-dir" >&2; exit 2; }
mkdir -p "$target/release"
printf '#!/bin/sh\\n[ "$1" = --version ] && echo "project-board-sidebar 0.0.0-stub"\\n' > "$target/release/project-board-sidebar"
chmod +x "$target/release/project-board-sidebar"
'''
REAL_CARGO = "/primehome/tools/Inhouse/Rust/latest/bin/cargo"


class Home:
    """An isolated HOME with the user's own files that no command may change (8.1 item 5)."""

    USER_FILES = {
        ".claude/settings.json": b'{"theme": "dark"}\n',
        ".claude/CLAUDE.md": b"my rules\n",
        ".claude/skills/other-skill/SKILL.md": b"other skill\n",
        ".claude.json": b'{"projects": {}}\n',
        ".codex/config.toml": b'model = "x"\n',
        ".codex/AGENTS.md": b"my agents\n",
        ".codex/skills/other-skill/SKILL.md": b"other skill\n",
        ".bashrc": b"export A=1\n",
    }

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="pi-"))
        self.home = self.root / "h"
        self.home.mkdir()
        for relative, data in self.USER_FILES.items():
            self.write(relative, data)
        (self.home / "tmp").mkdir()
        self.env = {key: value for key, value in os.environ.items()
                    if not (key.startswith(("XDG_", "AGENT_SESSION_", "CLAUDE", "CODEX")) or key in (
                        "TMUX", "TMUX_PANE", "TMPDIR", "PYTHONPATH", "PROJECT_AGENT_PYTHON", "PROJECT_AGENT_PYTHONPATH"))}
        for name in ("PROJECT_AGENT_CARGO", "PROJECT_AGENT_RUST_VENDOR", "CARGO_HOME", "CARGO_TARGET_DIR", "FAKE_CARGO_MODE"):
            self.env.pop(name, None)
        self.fake_cargo = self.root / "fake-cargo" / "cargo"          # outside HOME: not part of any snapshot
        self.fake_cargo.parent.mkdir()
        self.fake_cargo.write_text(FAKE_CARGO)
        self.fake_cargo.chmod(0o755)
        self.vendor = self.root / "vendor"
        self.vendor.mkdir()
        self.cargo_log = self.root / "cargo.log"
        self.env.update(PROJECT_AGENT_CARGO=str(self.fake_cargo), PROJECT_AGENT_RUST_VENDOR=str(self.vendor),
                        FAKE_CARGO_LOG=str(self.cargo_log))
        self.env.update(HOME=str(self.home), TMPDIR=str(self.home / "tmp"), PYTHONNOUSERSITE="1",
                        TMUX_TMPDIR=str(self.root / "tt"),          # no command of a test can reach the user's tmux server
                        PATH=str(self.home / ".local/bin") + os.pathsep + os.environ.get("PATH", ""),
                        **GIT_ENV)

    def close(self):
        for directory, _, _ in os.walk(self.root):          # releases are read-only
            os.chmod(directory, 0o755)
        shutil.rmtree(self.root, ignore_errors=True)

    def path(self, relative):
        return self.home / relative

    def write(self, relative, data, mode=None):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if mode is not None:
            path.chmod(mode)
        os.utime(path, ns=(OLD, OLD))
        return path

    def read(self, relative):
        return (self.home / relative).read_bytes()

    def run(self, *args, source=None, env=None, cwd=None, installer=None):
        """Run the installer as a user would; `source` is the Git checkout to release."""
        command = [sys.executable, str(installer or INSTALLER), *args]
        if source is not None and args[0] in ("install", "upgrade"):
            command += ["--source", str(source)]
        return subprocess.run(command, capture_output=True, text=True, timeout=300, cwd=cwd or self.root,
                              env={**self.env, **(env or {})})

    def snapshot(self):
        return snapshot(self.home)

    def cargo_calls(self):
        """The lines the fake cargo logged (one per call)."""
        return self.cargo_log.read_text().splitlines() if self.cargo_log.exists() else []


def snapshot(root):
    """Every entry under root, not following symlinks: path -> (kind, mode, hash, target, mtime_ns).
    A directory's own mtime is not recorded: it changes with its children, which are listed themselves."""
    result = {}

    def walk(directory, prefix):
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                relative = prefix + entry.name
                info = entry.stat(follow_symlinks=False)
                mode = stat.S_IMODE(info.st_mode)
                if entry.is_symlink():
                    result[relative] = ("symlink", mode, None, os.readlink(entry.path), None)
                elif entry.is_dir(follow_symlinks=False):
                    result[relative] = ("dir", mode, None, None, None)
                    walk(entry.path, relative + "/")
                elif entry.is_file(follow_symlinks=False):
                    digest = hashlib.sha256(Path(entry.path).read_bytes()).hexdigest()
                    result[relative] = ("file", mode, digest, None, info.st_mtime_ns)
                else:
                    result[relative] = ("other", mode, None, None, None)
    walk(root, "")
    return result


def collapse(paths, trees):
    """Replace every path under one of the `trees` by the tree's root (a release is one change)."""
    result = set()
    for path in paths:
        for tree in trees:
            if path == tree or path.startswith(tree + "/"):
                path = tree
                break
        result.add(path)
    return result


def changes(before, after, trees=()):
    created = collapse(set(after) - set(before), trees)
    removed = collapse(set(before) - set(after), trees)
    modified = collapse({path for path in set(before) & set(after) if before[path] != after[path]}, trees)
    return created, removed, modified


def assert_changes(before, after, created=(), removed=(), modified=(), trees=()):
    """The contract's expectation: the sets of added, deleted and changed paths must be exactly these.
    Anything else that differs (an unexpected path, or an unchanged expected one) is a failure."""
    got = changes(before, after, trees)
    want = (set(created), set(removed), set(modified))
    names = ("created", "removed", "modified")
    for name, actual, expected in zip(names, got, want):
        assert actual == expected, "%s differ:\n  unexpected: %s\n  missing: %s" % (
            name, sorted(actual - expected), sorted(expected - actual))


def install_paths(name, claude=True, codex=True, draft=True, bin_dir=True, home_dirs=(".local", ".local/lib")):
    """The paths a clean-HOME install creates, written from contract section 2 (not from the record)."""
    paths = {LIB, LIB + "/releases", LIB + "/releases/" + name, LIB + "/current", LIB + "/tmux.conf",
             LIB + "/install.json", *home_dirs}
    if bin_dir:
        paths |= {".local/bin", *SHIMS}
    if claude:
        paths |= set(CLAUDE_LINKS)
    if codex:
        paths |= set(CODEX_LINKS)
    if draft:
        paths |= {".config", ".config/project-agent", REGISTRY_DRAFT}
    return paths


FIXTURES = REPO / "tools" / "agent-session" / "tests" / "fixtures"
SITECUSTOMIZE = '''\
import os, sys
lib = os.environ.get("FAKE_PROVIDER_LIB")
if lib:
    sys.path[:0] = [lib, os.environ["FAKE_PROVIDER_FIXTURES"]]
    import agent_session.lifecycle as lifecycle
    import agent_session.providers as providers
    from agent_session_fake_provider import FakeProvider
    lifecycle.get_provider = lambda name: FakeProvider()
    providers.get_provider = lambda name: FakeProvider()
'''


class Runs:
    """One registered project whose managed runs use a fake provider CLI, on a private tmux server.

    The installed `agent-session` is the real one; only the provider is replaced (by the agent-session test
    fixture's fake CLI, through a `sitecustomize` that exists only in this test's environment), so that
    start, stop and the run files are the product's. Every command names the private socket: nothing here
    reaches the user's tmux server. Create it before `install`, so the registry exists and no draft is made."""

    PROJECT = "pifx"

    def __init__(self, home):
        self.home = home
        self.socket_dir = Path(tempfile.mkdtemp(prefix="pi-t"))
        self.socket = self.socket_dir / "s"
        self.base = home.home / "proj" / "base"
        (self.base).mkdir(parents=True)
        home.write(REGISTRY_DRAFT, json.dumps({str(self.base): {
            "project": self.PROJECT, "provider": "codex", "seats": [],
            "path_cr": "agent/cr", "path_decide": "agent/decide"}}).encode())
        self.hook = home.root / "hook"
        self.hook.mkdir()
        (self.hook / "sitecustomize.py").write_text(SITECUSTOMIZE)
        # agent-session starts its interpreter with -S (no site step, PERF-002), which would skip the
        # sitecustomize above. This test-only interpreter drops that one flag and runs the real one.
        self.interpreter = self.hook / "python-with-site"
        self.interpreter.write_text('#!/bin/sh\n[ "$1" = -S ] && shift\nexec "%s" "$@"\n' % os.path.abspath(sys.executable))
        self.interpreter.chmod(0o755)
        home.env["TMUX_TMPDIR"] = str(self.socket_dir)          # even a missing option cannot reach the user's server
        tmux_test_server.watch_path(self.socket)
        self.tmux("new-session", "-d", "-s", "harness", "sleep", "86400")

    def tmux(self, *args, check=True):
        result = subprocess.run(["tmux", "-S", str(self.socket), "-f", os.devnull, *args], capture_output=True,
                                text=True, timeout=30, env=self.home.env)
        assert not check or result.returncode == 0, result.stderr
        return result

    def cli_env(self):
        return {**self.home.env, "PYTHONPATH": str(self.hook), "PROJECT_AGENT_PYTHON": str(self.interpreter),
                "FAKE_PROVIDER_LIB": str(self.home.home / LIB / "current/tools/agent-session"),
                "FAKE_PROVIDER_FIXTURES": str(FIXTURES)}

    def call(self, tool, *args):
        command = [str(self.home.home / ".local/bin" / tool), *args]
        return subprocess.run(command, capture_output=True, text=True, timeout=120, cwd=self.base, env=self.cli_env())

    def agent(self, *args):
        return self.call("agent-session", "--socket-path", str(self.socket), *args)

    def start_leader(self):
        result = self.agent("start", "--job", "leader")
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)["data"]

    def start_leader_from(self, root):
        """Start the Leader with the `agent-session` of a checkout (not a release): the frozen-copy case."""
        library = Path(root) / "tools" / "agent-session"
        result = subprocess.run([str(library / "bin" / "agent-session"), "--socket-path", str(self.socket), "start",
                                 "--job", "leader"], capture_output=True, text=True, timeout=120, cwd=self.base,
                                env={**self.cli_env(), "FAKE_PROVIDER_LIB": str(library), "PYTHONDONTWRITEBYTECODE": "1"})
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)["data"]

    def stop_leader(self):
        result = self.agent("stop", "--job", "leader")
        assert result.returncode == 0, result.stdout + result.stderr

    def kill_cli(self):
        """End the managed CLI process; its pane stays (remain-on-exit), so the run reads `stopped`."""
        for line in self.tmux("list-panes", "-s", "-t", self.PROJECT, "-F", "#{pane_pid}").stdout.split():
            os.kill(int(line), 9)
        import time
        for _ in range(100):
            if "1" in self.tmux("list-panes", "-s", "-t", self.PROJECT, "-F", "#{pane_dead}").stdout.split():
                return
            time.sleep(0.1)
        raise AssertionError("the pane did not die")

    def kill_server(self):
        """Lose the server mid-test; the next command starts a new one, which the watchdog must cover again."""
        tmux_test_server.release_path(self.socket)
        tmux_test_server.watch_path(self.socket)

    def run_directories(self):
        return sorted((self.base / "agent" / "runs").iterdir())

    def close(self):
        tmux_test_server.release_path(self.socket)
        shutil.rmtree(self.socket_dir, ignore_errors=True)


STOP_HOOK = '''\
import os, signal, sys
spec = os.environ.get("INSTALLER_STOP")
if spec:
    sys.path.insert(0, os.environ["INSTALLER_DIR"])
    from project_agent_install import actions
    position, index, name = spec.split(":")

    def checkpoint(where, number):
        if where == position and number == int(index):
            if name == "PLANT":               # a user creates a file at this moment
                with open(os.environ["INSTALLER_PLANT_FILE"], "w") as stream:
                    stream.write(os.environ["INSTALLER_PLANT_TEXT"])
            else:
                os.kill(os.getpid(), getattr(signal, name))
    actions.checkpoint = checkpoint
'''


def stop_at(home, position, index, signal_name="SIGKILL"):
    """Environment for `Home.run` that sends `signal_name` to the installer at a boundary: "before" or "after"
    step number `index`, or "temp": right after the `index`-th temporary file, link or directory was made."""
    hook = home.root / "stop-hook"
    hook.mkdir(exist_ok=True)
    (hook / "sitecustomize.py").write_text(STOP_HOOK)
    return {"PYTHONPATH": str(hook), "INSTALLER_DIR": str(INSTALLER.parent),
            "INSTALLER_STOP": "%s:%d:%s" % (position, index, signal_name)}


def plant_at(home, position, index, relative, text):
    """Like `stop_at`, but at that moment a user creates the file `relative` (under HOME) with `text`."""
    env = stop_at(home, position, index, "PLANT")
    env.update(INSTALLER_PLANT_FILE=str(home.path(relative)), INSTALLER_PLANT_TEXT=text)
    return env
