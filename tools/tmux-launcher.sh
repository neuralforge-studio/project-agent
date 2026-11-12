# Shared tmux selection of the shell scripts of integrations/tmux (project_agent_run.sh, project_agent_bind.sh,
# project_board_visibility.sh, tmux_decide_status.sh). The scripts source this file; it is not executable by itself.
# POSIX sh: the scripts run under sh and bash. Contract: docs/project-team/install-contract.md section 6.2.
#
# The tmux of project-agent is chosen once, by the installer, and recorded in `tmux.env` next to this file (the
# release's `tools/`). The Python modules (`agent_session/tmux_program.py`) and the Rust sidebar read the same
# record by the same rule; tools/tests/test_tmux_record.py keeps the three equal.
#
#   PROJECT_AGENT_TMUX                  absolute path of the tmux executable
#   PROJECT_AGENT_TMUX_LD_LIBRARY_PATH  library directories that executable needs (empty: none)
#
# A variable of the environment that has a value wins over the file (per name). The file is parsed, never
# sourced: one `NAME=value` per line, the value is the rest of the line, the last line of a name wins.
# Without the file (development checkout) the tmux is `tmux` in PATH. A file that names no program says that
# the installer found no tmux of the minimum version.
#
# usage: project_agent_select_tmux TOOLS_DIRECTORY
# Sets TMUX_BIN (empty when the record names no tmux), exports PROJECT_AGENT_TMUX and
# PROJECT_AGENT_TMUX_LD_LIBRARY_PATH (so a child process reads the same choice), and puts the library
# directories in front of LD_LIBRARY_PATH.
project_agent_select_tmux() {
    pa_file="$1/tmux.env" pa_program="" pa_library="" pa_line="" pa_recorded=""
    if [ -f "$pa_file" ]; then
        pa_recorded=1
        while IFS= read -r pa_line || [ -n "$pa_line" ]; do
            case "$pa_line" in
                PROJECT_AGENT_TMUX=*) pa_program=${pa_line#PROJECT_AGENT_TMUX=} ;;
                PROJECT_AGENT_TMUX_LD_LIBRARY_PATH=*) pa_library=${pa_line#PROJECT_AGENT_TMUX_LD_LIBRARY_PATH=} ;;
            esac
        done < "$pa_file"
    fi
    PROJECT_AGENT_TMUX=${PROJECT_AGENT_TMUX:-$pa_program}
    PROJECT_AGENT_TMUX_LD_LIBRARY_PATH=${PROJECT_AGENT_TMUX_LD_LIBRARY_PATH:-$pa_library}
    if [ -n "$PROJECT_AGENT_TMUX" ]; then
        TMUX_BIN=$PROJECT_AGENT_TMUX
    elif [ -n "$pa_recorded" ]; then
        TMUX_BIN=
    else
        TMUX_BIN=tmux
    fi
    export PROJECT_AGENT_TMUX PROJECT_AGENT_TMUX_LD_LIBRARY_PATH
    if [ -n "$PROJECT_AGENT_TMUX_LD_LIBRARY_PATH" ]; then
        LD_LIBRARY_PATH="$PROJECT_AGENT_TMUX_LD_LIBRARY_PATH${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
        export LD_LIBRARY_PATH
    fi
    unset pa_file pa_program pa_library pa_line pa_recorded
}
