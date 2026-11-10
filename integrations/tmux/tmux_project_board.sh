#!/bin/bash
# Run the Project Board entry point from the tmux configuration source tree.
set -euo pipefail

script="${BASH_SOURCE[0]}"
[[ "$script" == */* ]] || script="./$script"
SCRIPT_DIR="$(CDPATH= cd -P -- "${script%/*}" && pwd -P)"
exec "$SCRIPT_DIR/../../tools/project-board/bin/project-board" "$@"
