"""Find (and when needed build) the Rust sidebar binary that the tests run (BOARD-018).

`PROJECT_BOARD_SIDEBAR_BIN` names a binary to use as it is. Otherwise the release binary of
`tools/project-board/rust` is built with `cargo build --release --offline --locked` when it is missing or older
than the sources. The cargo is `PROJECT_AGENT_CARGO`, then `/primehome/tools/Inhouse/Rust/latest/bin/cargo`, then
the one on PATH. The vendored crate directory of `rust/.cargo/config.toml` is replaced only when
`PROJECT_AGENT_RUST_VENDOR` is set. `CARGO_TARGET_DIR` is respected. A binary that cannot be had is an error,
never a skip: the equivalence of the two implementations must not pass by not running.
"""
import os
import shutil
import subprocess
from pathlib import Path

CRATE = Path(__file__).resolve().parents[1] / "rust"
BINARY_NAME = "project-board-sidebar"
COMPANY_CARGO = Path("/primehome/tools/Inhouse/Rust/latest/bin/cargo")


class RustBinaryError(RuntimeError):
    """The sidebar binary is not available and could not be built."""


def cargo() -> str:
    if os.environ.get("PROJECT_AGENT_CARGO"):
        return os.environ["PROJECT_AGENT_CARGO"]
    if COMPANY_CARGO.is_file():
        return str(COMPANY_CARGO)
    found = shutil.which("cargo")
    if found:
        return found
    raise RustBinaryError("no cargo: set PROJECT_AGENT_CARGO, or install cargo")


def target_dir() -> Path:
    return (CRATE / os.environ["CARGO_TARGET_DIR"]) if os.environ.get("CARGO_TARGET_DIR") else CRATE / "target"


def release_binary() -> Path:
    return target_dir() / "release" / BINARY_NAME


def sources_mtime() -> float:
    files = [CRATE / "Cargo.toml", CRATE / "Cargo.lock", *(CRATE / "src").rglob("*.rs")]
    return max(path.stat().st_mtime for path in files if path.is_file())


def build_command() -> list[str]:
    command = [cargo(), "build", "--release", "--offline", "--locked"]
    vendor = os.environ.get("PROJECT_AGENT_RUST_VENDOR")
    if vendor:
        command += ["--config", f"source.vendored-sources.directory='{vendor}'"]
    return command


def sidebar_binary() -> Path:
    """The binary to test. Raises `RustBinaryError` with the build output when there is none."""
    given = os.environ.get("PROJECT_BOARD_SIDEBAR_BIN")
    if given:
        if not Path(given).is_file():
            raise RustBinaryError(f"PROJECT_BOARD_SIDEBAR_BIN is not a file: {given}")
        return Path(given)
    binary = release_binary()
    if binary.is_file() and binary.stat().st_mtime >= sources_mtime():
        return binary
    result = subprocess.run(build_command(), cwd=CRATE, capture_output=True, text=True)
    if result.returncode or not binary.is_file():
        raise RustBinaryError(f"cargo build failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
    return binary
