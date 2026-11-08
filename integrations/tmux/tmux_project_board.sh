#!/usr/bin/env bash
# Compatibility helper for the installed public CLI.
set -euo pipefail
exec "$HOME/.local/bin/project-board" "$@"
