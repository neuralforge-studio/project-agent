#!/usr/bin/env bash
# Run the Project Board entry point from the tmux configuration source tree.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
exec "$SCRIPT_DIR/../../tools/project-board/bin/project-board" "$@"
