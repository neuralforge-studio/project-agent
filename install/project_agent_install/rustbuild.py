"""The Rust sidebar of a release (contract section 2): where the toolchain is, and the offline build.

The crate is part of the release's source files (`tools/project-board/rust`); a release holds no binary until
this build makes one. The build runs inside the release's temporary directory (actions.build_release), so a
failure leaves no release directory and no change to `current`.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile

from .layout import InstallerError

CARGO_ENV = "PROJECT_AGENT_CARGO"
VENDOR_ENV = "PROJECT_AGENT_RUST_VENDOR"
DEFAULT_CARGO = "/primehome/tools/Inhouse/Rust/latest/bin/cargo"
CRATE = "tools/project-board/rust"
BINARY_NAME = "project-board-sidebar"
BINARY = "tools/project-board/bin/" + BINARY_NAME
OUTPUTS = (BINARY,)                 # the release paths the build makes (the release listing counts them)
VENDOR_SOURCE = "vendored-sources"
TIMEOUT = 1800
TAIL_LINES = 20
TAIL_CHARS = 2500


@dataclass(frozen=True)
class Toolchain:
    cargo: str
    vendor: str            # the vendored crates directory the build uses
    overridden: bool       # whether it comes from PROJECT_AGENT_RUST_VENDOR instead of the crate's config


def find_cargo():
    """`PROJECT_AGENT_CARGO`, else the in-house cargo, else the first `cargo` in PATH. A value that is set but
    unusable is an error, not a reason to look further."""
    configured = os.environ.get(CARGO_ENV)
    if configured:
        if os.path.isfile(configured) and os.access(configured, os.X_OK):
            return os.path.abspath(configured)
        raise InstallerError("cargo_missing", "%s=%s is not an executable file. Nothing was changed."
                             % (CARGO_ENV, configured))
    if os.path.isfile(DEFAULT_CARGO) and os.access(DEFAULT_CARGO, os.X_OK):
        return DEFAULT_CARGO
    found = shutil.which("cargo")
    if found:
        return os.path.abspath(found)
    raise InstallerError("cargo_missing", "cargo was not found, and the Project Board sidebar is built when a "
                         "release is made. Looked at %s, %s, and `cargo` in PATH. Set %s to a cargo executable. "
                         "Nothing was changed." % (CARGO_ENV, DEFAULT_CARGO, CARGO_ENV))


def configured_vendor(crate):
    """The `directory` of `[source.vendored-sources]` in the crate's committed `.cargo/config.toml` (the one
    place that names the default), or None when it does not say."""
    try:
        lines = (Path(crate) / ".cargo/config.toml").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    section = None
    for line in lines:
        text = line.strip()
        header = re.fullmatch(r"\[([^\]]+)\]", text)
        if header:
            section = header.group(1).strip()
            continue
        match = re.fullmatch(r'directory\s*=\s*"([^"]*)"', text)
        if match and section == "source." + VENDOR_SOURCE:
            return match.group(1)
    return None


def prepare(source_root):
    """Find the toolchain and the vendored crates before anything is changed (exit code 3 when one is missing)."""
    cargo = find_cargo()
    override = os.environ.get(VENDOR_ENV)
    vendor = os.path.abspath(os.path.expanduser(override)) if override else configured_vendor(Path(source_root) / CRATE)
    if vendor is None:
        raise InstallerError("vendor_missing", "%s/.cargo/config.toml does not name the vendored crates directory; set "
                             "%s. Nothing was changed." % (CRATE, VENDOR_ENV))
    if not os.path.isdir(vendor):
        raise InstallerError("vendor_missing", "The vendored crates directory %s does not exist, so the Project "
                             "Board sidebar cannot be built offline. %s. Nothing was changed."
                             % (vendor, "Fix %s" % VENDOR_ENV if override else
                                "Set %s to the directory that holds the vendored crates" % VENDOR_ENV))
    return Toolchain(cargo, vendor, bool(override))


def describe(toolchain):
    return ("The Project Board sidebar is built from %s with %s (offline, vendored crates in %s). The release "
            "appears only if the build succeeds." % (CRATE, toolchain.cargo, toolchain.vendor))


class BuildFailed(OSError):
    """The cargo build did not make the binary; the text carries the end of cargo's output."""


def _tail(text):
    lines = text.rstrip().splitlines()[-TAIL_LINES:]
    return "\n".join(lines)[-TAIL_CHARS:]


def build(toolchain, release_root):
    """`cargo build --release --offline --locked` of the crate inside `release_root`, then the binary is
    copied to `BINARY` there (executable). The target directory and CARGO_HOME are one temporary directory
    that is removed afterwards, so a build writes nothing else (not into the user's `~/.cargo`)."""
    release_root = Path(release_root)
    scratch = tempfile.mkdtemp(prefix="project-agent-build-")
    try:
        target = os.path.join(scratch, "target")
        command = [toolchain.cargo]
        if toolchain.overridden:
            command += ["--config", "source.%s.directory=%s" % (VENDOR_SOURCE, json.dumps(toolchain.vendor))]
        command += ["build", "--release", "--offline", "--locked", "--target-dir", target]
        env = {**os.environ, "CARGO_HOME": os.path.join(scratch, "cargo-home"),
               "PATH": os.path.dirname(toolchain.cargo) + os.pathsep + os.environ.get("PATH", "")}
        process = None
        try:
            process = subprocess.Popen(command, cwd=release_root / CRATE, env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       errors="replace", start_new_session=True)
            _, stderr = process.communicate(timeout=TIMEOUT)
        except FileNotFoundError as error:
            raise BuildFailed("cannot run %s: %s" % (toolchain.cargo, error)) from error
        except subprocess.TimeoutExpired as error:
            raise BuildFailed("cargo did not finish within %d seconds" % TIMEOUT) from error
        finally:
            if process is not None and process.poll() is None:     # a signal or a timeout: end the build we started
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except OSError:
                    pass
                process.wait()
        if process.returncode:
            raise BuildFailed("cargo build failed (exit code %d). The end of its output:\n%s"
                              % (process.returncode, _tail(stderr)))
        built = Path(target) / "release" / BINARY_NAME
        if not built.is_file():
            raise BuildFailed("cargo build succeeded but made no %s" % BINARY_NAME)
        destination = release_root / BINARY
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built, destination)
        destination.chmod(0o755)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
