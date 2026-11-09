#!/bin/sh
# Run the job of one `run-shell` so that nothing of it reaches the pane the user is working in (BOARD-010).
#
# usage: project_agent_run.sh MODE SOCKET_PATH COMMAND [ARG...]
#
# tmux shows the output and a nonzero exit status of a `run-shell` job in the active pane, which is
# the user's work pane. Every `run-shell` job of the integration goes through this script, which
# prints nothing and exits 0 whatever COMMAND does. What it does with a failure depends on MODE:
#
#   hook  an event of tmux (a window change, a client attaching): the failure is written to the server
#         option @project_agent_last_error, one line, replaced by the next failure (the option is
#         bounded, a hook that fails at every window change does not fill a file).
#   key   something the user pressed (the Board key, reading the integration): the same record, and a
#         short message (display-message) on every attached client, which covers no pane.
#   drop  a failure that is expected (a click on the Board that hit no item): nothing is recorded.
#
# The rule for a new `run-shell` is in the install contract, 5.3. The test of this directory checks it.
[ $# -ge 3 ] && case "$1" in hook|key|drop) true ;; *) false ;; esac || { echo "usage: $0 hook|key|drop SOCKET_PATH COMMAND [ARG...]" >&2; exit 2; }
mode=$1 socket=$2
shift 2

output=$("$@" 2>&1)
status=$?
[ "$status" = 0 ] && exit 0
[ "$mode" = drop ] && exit 0

line=$(printf '%s\n' "$output" | sed -n '/[^[:space:]]/{s/^[[:space:]]*//;p;q;}' | cut -c1-200)
text="${1##*/} failed (exit $status)${line:+: $line}"
tm() { tmux -S "$socket" "$@" 2>/dev/null; }
tm set-option -g @project_agent_last_error "$(date '+%F %T') $text" || true
if [ "$mode" = key ]; then
    # display-message expands formats, so a # in the text is doubled.
    message="project-agent: $(printf '%s' "$text" | sed 's/#/##/g') (tmux show-options -gv @project_agent_last_error)"
    tm list-clients -F '#{client_name}' | while read -r client; do
        tm display-message -c "$client" -d 5000 "$message" || true
    done
fi
exit 0
