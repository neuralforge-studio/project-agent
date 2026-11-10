#!/bin/bash
# Run tmux_decide_status.py with the interpreter of the release (install contract 6.1).
# The status line option @project_agent_decide_status calls this file, never the .py directly.
set -euo pipefail

script="${BASH_SOURCE[0]}"
[[ "$script" == */* ]] || script="./$script"
SCRIPT_DIR="$(CDPATH= cd -P -- "${script%/*}" && pwd -P)"
source "$SCRIPT_DIR/../../tools/python-launcher.sh"
project_agent_select_python
if [[ -z "$PY" ]]; then
    echo "The configured Python interpreter is unavailable." >&2
    exit 5
fi
export PYTHONNOUSERSITE=1
unset PYTHONHOME
exec "$PY" -S "$SCRIPT_DIR/tmux_decide_status.py" "$@"
