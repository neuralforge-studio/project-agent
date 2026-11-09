# Shared Python selection of the project-agent CLI entry points (agent-session, project-item,
# project-board). Entry points source this file; it is not executable by itself.
# Contract: docs/project-team/install-contract.md section 6.1.
#
#   PROJECT_AGENT_PYTHON      interpreter the installer chose. When set, it is the only candidate.
#   PROJECT_AGENT_PYTHONPATH  directories of the release's external packages (":"-separated).
#                             project-board adds them to PYTHONPATH; PYTHONNOUSERSITE hides user packages.
#
# Without PROJECT_AGENT_PYTHON (development checkout) the platform rule applies:
# macOS python3, WSL ~/python/.venv (no other candidate), otherwise the Workstation
# /primehome/tools/Inhouse/Python3/latest, ~/python/.venv, python3 in that order.
#
# Sets PY (empty when the selected interpreter does not exist) and, on the Workstation rule, LD_LIBRARY_PATH.
project_agent_select_python() {
    local inhouse=/primehome/tools/Inhouse/Python3/latest
    if [[ -n "${PROJECT_AGENT_PYTHON:-}" ]]; then
        PY="$PROJECT_AGENT_PYTHON"
        [[ -x "$PY" ]] || PY=
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
