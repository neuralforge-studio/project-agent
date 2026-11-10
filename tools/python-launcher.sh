# Shared Python selection of the project-agent CLI entry points (agent-session, project-item,
# project-board). Entry points source this file; it is not executable by itself.
# Contract: docs/project-team/install-contract.md section 6.1.
#
#   PROJECT_AGENT_PYTHON      interpreter the installer chose. When set, it is the only candidate.
#   PROJECT_AGENT_PYTHONPATH  directories of the release's external packages (":"-separated).
#                             project-board adds them to PYTHONPATH; PYTHONNOUSERSITE hides user packages.
#   PROJECT_AGENT_LD_LIBRARY_PATH  library directory the installer's interpreter needs to start as itself
#                             (same sys.prefix). Put in front of LD_LIBRARY_PATH when PROJECT_AGENT_PYTHON is used.
#
# A variable that is empty or unset is read from `python.env` next to this file (the installer writes
# it into the release). Format: one `NAME=value` per line, only these three names, the value is the rest
# of the line without quotes. The file is parsed, never sourced: other lines (the installer also writes
# PROJECT_AGENT_PYTHON_PREFIX for `check`) are ignored and nothing in a value is expanded. An environment
# variable that has a value wins over the file.
#
# Without PROJECT_AGENT_PYTHON (development checkout) the platform rule applies:
# macOS python3, WSL ~/python/.venv (no other candidate), otherwise the Workstation
# /primehome/tools/Inhouse/Python3/latest, ~/python/.venv, python3 in that order.
#
# Sets PY (empty when the selected interpreter does not exist) and LD_LIBRARY_PATH (the installer's library
# directory, or on the Workstation rule the inhouse one).
# The directory of this file is found without exec-ing `dirname`: this runs in every command, and each
# exec on the Workstation searches PATH and LD_LIBRARY_PATH on NFS. Only a launcher that is itself a
# symlink needs `readlink`.
project_agent_launcher_source="${BASH_SOURCE[0]}"
[[ ! -L "$project_agent_launcher_source" ]] || project_agent_launcher_source="$(readlink -f -- "$project_agent_launcher_source")"
[[ "$project_agent_launcher_source" == */* ]] || project_agent_launcher_source="./$project_agent_launcher_source"
PROJECT_AGENT_LAUNCHER_DIR="$(CDPATH= cd -P -- "${project_agent_launcher_source%/*}" && pwd -P)"
unset project_agent_launcher_source

# Fills the three PROJECT_AGENT_* names above from python.env where the environment has no value.
project_agent_read_python_env() {
    local file="$PROJECT_AGENT_LAUNCHER_DIR/python.env" line python="" pythonpath="" library=""
    [[ -f "$file" ]] || return 0
    while IFS= read -r line || [[ -n "$line" ]]; do
        case "$line" in
            PROJECT_AGENT_PYTHON=*) python="${line#PROJECT_AGENT_PYTHON=}" ;;
            PROJECT_AGENT_PYTHONPATH=*) pythonpath="${line#PROJECT_AGENT_PYTHONPATH=}" ;;
            PROJECT_AGENT_LD_LIBRARY_PATH=*) library="${line#PROJECT_AGENT_LD_LIBRARY_PATH=}" ;;
        esac
    done < "$file"
    PROJECT_AGENT_PYTHON="${PROJECT_AGENT_PYTHON:-$python}"
    PROJECT_AGENT_PYTHONPATH="${PROJECT_AGENT_PYTHONPATH:-$pythonpath}"
    PROJECT_AGENT_LD_LIBRARY_PATH="${PROJECT_AGENT_LD_LIBRARY_PATH:-$library}"
}

project_agent_select_python() {
    local inhouse=/primehome/tools/Inhouse/Python3/latest
    project_agent_read_python_env
    if [[ -n "${PROJECT_AGENT_PYTHON:-}" ]]; then
        PY="$PROJECT_AGENT_PYTHON"
        [[ -x "$PY" ]] || PY=
        if [[ -n "${PROJECT_AGENT_LD_LIBRARY_PATH:-}" ]]; then
            export LD_LIBRARY_PATH="$PROJECT_AGENT_LD_LIBRARY_PATH${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
        fi
    elif [[ "$(uname -s)" == Darwin ]]; then
        PY=$(command -v python3 || true)
    elif [[ -n "${WSL_DISTRO_NAME:-}" || -n "${WSL_INTEROP:-}" || "$(uname -r)" == *[Mm]icrosoft* ]]; then
        PY="$HOME/python/.venv/bin/python"
        [[ -x "$PY" ]] || PY=
    elif [[ -x "$inhouse/bin/python3" ]]; then
        PY="$inhouse/bin/python3"
        export LD_LIBRARY_PATH="$inhouse/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    elif [[ -x "$HOME/python/.venv/bin/python" ]]; then
        PY="$HOME/python/.venv/bin/python"
    else
        PY=$(command -v python3 || true)
    fi
}

# Reads the bundle reader (bundle_boot.py, install contract 6.1) into PROJECT_AGENT_BOOT, the first part of
# the `-c` program of an entry point. `read` is a builtin: no process and no `cat`. Without that file the
# program gets a reader that does nothing, and the modules are imported one by one.
project_agent_read_boot() {
    local code=
    IFS= read -r -d '' code 2> /dev/null < "$PROJECT_AGENT_LAUNCHER_DIR/bundle_boot.py" || true
    PROJECT_AGENT_BOOT="${code:-def _project_agent_bundle(tools_directory): pass}"
}
