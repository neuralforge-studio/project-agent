#!/bin/bash
# Print the decision status line for the tmux status line (@project_agent_decide_status).
#
# While the cache of tmux_decide_status.py is valid this prints the stored status line and starts no
# Python. The view file (VIEW_NAME in the .py) has the epoch second until which it is valid on its
# first line and the status line after it; the .py owns CACHE_TTL and writes that line. Otherwise
# this runs tmux_decide_status.py with the interpreter of the release (install contract 6.1).
# The status line option calls this file, never the .py directly.
set -euo pipefail

view="${XDG_CACHE_HOME:-$HOME/.cache}/tmux-decide-status.view"
expires="" body=""
if [[ -r "$view" ]]; then
    { IFS= read -r expires && { IFS= read -r -d '' body || true; }; } < "$view" 2>/dev/null || expires=""
    if [[ "$expires" =~ ^[0-9]+$ ]] && (( $(date +%s) <= expires )); then
        printf '%s' "$body"
        exit 0
    fi
fi

script="${BASH_SOURCE[0]}"
[[ "$script" == */* ]] || script="./$script"
SCRIPT_DIR="$(CDPATH= cd -P -- "${script%/*}" && pwd -P)"
source "$SCRIPT_DIR/../../tools/python-launcher.sh"
project_agent_select_python
if [[ -z "$PY" ]]; then
    echo "The configured Python interpreter is unavailable." >&2
    exit 5
fi
. "$SCRIPT_DIR/../../tools/tmux-launcher.sh"
project_agent_select_tmux "$SCRIPT_DIR/../../tools"
if [[ -z "$TMUX_BIN" ]]; then
    echo "No tmux of the minimum version is recorded for this release." >&2
    exit 5
fi
export PYTHONNOUSERSITE=1
unset PYTHONHOME
exec "$PY" -S "$SCRIPT_DIR/tmux_decide_status.py" "$@"
