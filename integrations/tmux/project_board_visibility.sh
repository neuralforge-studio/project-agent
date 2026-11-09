#!/bin/sh
# Tell each Board pane whether a client shows its window (BOARD-002).
#
# A Board pane stays in a window after the last client leaves it, so that coming back finds the
# Board already running. A pane nobody sees must not read the project files every two seconds, so
# this script records which panes are seen and wakes a pane whose state changed. Plain sh and tmux,
# no Python: the hooks run it on every window change and it has to cost milliseconds.
#
# For each Board pane (pane option @project_board_managed):
#   @project_board_visible  1 when some client's current window is the pane's window, else 0.
#                           A pane that does not have the option yet counts as 1.
#   @project_board_seen     (window option) the time a client last showed the window, which orders
#                           the windows when the number of kept Board panes is limited.
#   SIGUSR1                 sent only to a pane whose state changed and that marked itself ready
#                           (@project_board_ready, set by the TUI once its handler is installed);
#                           the pane reads @project_board_visible and stops or resumes its refresh.
#
# usage: project_board_visibility.sh --socket SOCKET_PATH
[ "${1:-}" = "--socket" ] && [ -n "${2:-}" ] || { echo "usage: $0 --socket SOCKET_PATH" >&2; exit 2; }
socket=$2
tm() { tmux -S "$socket" "$@"; }

shown=" $(tm list-clients -F '#{window_id}' 2>/dev/null | tr '\n' ' ')"
now=$(date +%s)
# Each option is written as name=value so that an unset option leaves a field, not a gap.
tm list-panes -a -F '#{pane_id} #{pane_pid} #{window_id} m=#{@project_board_managed} v=#{@project_board_visible} r=#{@project_board_ready}' 2>/dev/null |
while read -r pane pid window managed current ready; do
    [ "$managed" = "m=1" ] || continue
    current=${current#v=}
    case "$shown" in
        *" $window "*) want=1; tm set-option -w -t "$window" @project_board_seen "$now" ;;
        *) want=0 ;;
    esac
    [ "${current:-1}" = "$want" ] && continue
    tm set-option -p -t "$pane" @project_board_visible "$want"
    if [ "$ready" = "r=1" ]; then
        kill -USR1 "$pid" 2>/dev/null || true
    fi
done
