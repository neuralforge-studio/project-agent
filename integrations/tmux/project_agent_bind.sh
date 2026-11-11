#!/usr/bin/env bash
# Bind the Project Board keys unless the user has bound them to something else.
#
# usage: project_agent_bind.sh --socket SOCKET_PATH
#
# project-agent.conf runs this while it is read. The decision uses `tmux list-keys`, which tmux
# configuration syntax cannot do. The commands bound here run tmux_project_board.sh in the
# directory kept in the server option @project_agent_tmux_dir.
#
#   prefix <board key>   the key is @project_agent_board_key, B when it is not set
#   root MouseDown1Pane
#   root MouseDragEnd1Border   saves the Board width a user dragged (BOARD-019)
#
# A key is bound when it has no binding, when it has tmux's default (MouseDown1Pane only), or when
# its binding is this product's own (the command names tmux_project_board.sh, or for
# MouseDragEnd1Border the option @project_board_width). Any other binding
# is the user's and stays. The skipped keys are written to the server option
# @project_agent_board_skipped as space separated `<table>:<key>` words, empty when none.
set -euo pipefail

[ "${1:-}" = "--socket" ] && [ -n "${2:-}" ] || { echo "usage: $0 --socket SOCKET_PATH" >&2; exit 2; }
socket=$2
tm() { tmux -S "$socket" "$@"; }

KEY=$(tm show-options -gqv @project_agent_board_key)
KEY=${KEY:-B}
MOUSE_DEFAULT='select-pane -t = \; send-keys -M'
OWN=tmux_project_board.sh
WIDTH_OPTION=@project_board_width
RUN='#{q:@project_agent_tmux_dir}/project_agent_run.sh'

# The command of a key binding, empty when the key is not bound.
binding() {
    tm list-keys -T "$1" "$2" 2>/dev/null |
        sed -n '1s/^bind-key  *\(-r  *\)\{0,1\}-T  *[^ ][^ ]*  *[^ ][^ ]*  *//p' || true
}

skipped=
prefix_command=$(binding prefix "$KEY")
if [ -n "$prefix_command" ] && [[ $prefix_command != *"$OWN"* ]]; then
    skipped="prefix:$KEY"
    bind_prefix=0
else
    bind_prefix=1
fi
mouse_command=$(binding root MouseDown1Pane)
if [ -n "$mouse_command" ] && [ "$mouse_command" != "$MOUSE_DEFAULT" ] && [[ $mouse_command != *"$OWN"* ]]; then
    skipped="${skipped:+$skipped }root:MouseDown1Pane"
    bind_mouse=0
else
    bind_mouse=1
fi
drag_command=$(binding root MouseDragEnd1Border)
if [ -n "$drag_command" ] && [[ $drag_command != *"$WIDTH_OPTION"* ]]; then
    skipped="${skipped:+$skipped }root:MouseDragEnd1Border"
    bind_drag=0
else
    bind_drag=1
fi

{
    if [ "$bind_prefix" = 1 ]; then
        echo "bind-key $KEY run-shell -b '$RUN key #{q:socket_path} #{q:@project_agent_tmux_dir}/$OWN toggle --socket #{q:socket_path}'"
    fi
    if [ "$bind_mouse" = 1 ]; then
        # Clicks on the Board pane go to Board. Every other pane keeps tmux's default forwarding.
        # run-shell shows a job's output and a nonzero exit in the active pane, which is not the Board
        # pane (a click on it does not select it). Board reports a click that hit no item as an error,
        # so the job's output and status are dropped (project_agent_run.sh drop): a click on the Board
        # leaves nothing elsewhere.
        cat <<BINDING
bind-key -T root MouseDown1Pane if-shell -F '#{==:#{@project_board_pane},#{mouse_pane}}' {
    run-shell -b '$RUN drop #{q:socket_path} #{q:@project_agent_tmux_dir}/tmux_project_board.sh click --client #{q:client_name} --pane #{q:mouse_pane} --x #{mouse_x} --y #{mouse_y} --socket #{q:socket_path}'
} {
    select-pane -t =
    send-keys -M
}
BINDING
    fi
    if [ "$bind_drag" = 1 ]; then
        # after-resize-pane runs once when a border drag starts, not for each step or at its end, so
        # the width a drag leaves is recorded here. tmux has no hook for a user's drag alone:
        # window-layout-changed also runs when the terminal is resized, and that is not a width the
        # user chose. The mouse pane is the pane whose border was dragged.
        cat <<BINDING
bind-key -T root MouseDragEnd1Border if-shell -F '#{==:#{@project_board_managed},1}' {
    set-option -gF $WIDTH_OPTION '#{pane_width}'
}
BINDING
    fi
    echo "set-option -g @project_agent_board_skipped '$skipped'"
} | tm source-file -
