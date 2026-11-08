# project-board

`project-board` is the tmux text interface for every registered project. One sidebar lists
each project's open, todo and in-progress CR counts, open decisions and Worker seats. A large
popup shows a decision's Markdown and accepts the operator's answer. A CR popup shows the
selected CR's full Markdown. The Board has no HTTP server or browser page.

The current behavior is specified in `docs/project-board-tui-plan.md`. The registry and
team state are read through `agent_session`; CR and decision files are read through
`project_item`. The Board does not edit those sources. It sends an answer through
`agent-session send --job leader`; the Leader moves the decision item.

## Dependency and install

Follow the [copy installation guide](../../README.md). The launcher selects the
Workstation global Python first, then `~/python/.venv/bin/python`, then `python3`.
The dependency version is owned by [requirements.txt](requirements.txt). Prepare it
in the interpreter selected by the launcher. On Workstation, request a missing package
instead of creating a virtual environment.

Source `~/.local/lib/project-agent/integrations/tmux/project_board.conf` from your
`~/.tmux.conf`. It binds prefix `B`, click handling, and Board lifecycle hooks to the
installed public CLI. Your status layout remains in your tmux configuration.
For optional decision counts and alerts, source
`~/.local/lib/project-agent/integrations/tmux/project_decide_status.conf`.
The compatibility helper `integrations/tmux/tmux_project_board.sh` also calls the public CLI.

## Run

```sh
project-board toggle                          # show or hide the tmux sidebar
project-board --config PATH toggle            # use a specific project registry
project-board sidebar                         # run the TUI in the current pane
project-board popup --project PROJECT_ID      # show that project's unfinished decisions
project-board cr --project PROJECT_ID --state open  # show a CR list
```

The sidebar refreshes source files every 2 seconds and run liveness every 10 seconds.
The TUI keeps clicks and scrolling responsive during reads and answer delivery. Decision
answers require the `operator` caller classification from `agent-session`; a managed or
unmanaged agent session cannot submit an approval.

In tmux, prefix `B` or click `Board` in the status line to toggle the sidebar for every
attached client. The same window shares one Board pane. Each visible window gives the Board
25 columns by default and shows existing panes in the remaining space. A width adjusted in
tmux is used when the Board pane moves to another window or is created again. Turning the
Board off restores the previous pane layout and focus. A window with too little space for
the chosen width shows a smaller Board pane; another window with room restores that width.
Each project shows its decision count above the CR counts. Seats start folded. Click
`▸` to expand one project's seats, or `▾` to fold them. The fold state is shared by
Board panes in the same tmux server and survives window changes and Board off/on. Use Tab
and Enter for the same action from the keyboard. The list scrolls vertically when many
projects are present;
long names and CR IDs can be read in tooltips and by scrolling horizontally. An empty seat
shows its number followed by `-`.
An SSH seat shows `number@host` before its CR ID. Its tooltip shows the registered
host and remote path. An unavailable execution check keeps the seat assigned and shows
`실행 확인 불가` with the unknown-state color.
Click a project name to switch the clicking client to that project's tmux session and
current window. If that session is unavailable, the Board shows an error. Click a CR
count to open its CR list, `D` to read decisions, or a seat with a Worker session to switch
the clicking client to its Worker window. For an SSH seat, that window contains the SSH
connection to the remote Worker's tmux screen. The Board uses the same local window switch
as for a local seat. A seat with a CR but no Worker session shows `대기` and ignores clicks,
as does an empty seat. The decision popup uses 90% of that client's
terminal; the CR popup uses 80%. Press `Esc` or the popup's close button to close it.
In the CR popup, click a CR row or focus it with Tab and press Enter to read its full
Markdown. Select another row to change CRs. In either popup, `목록` is shown only below
70 columns. Use it to switch between the list and the selected item. Wider popups show
both panes and hide the button. After a popup grows and shrinks again, it shows the selected
item's body. If a listed CR file moves, is deleted, or cannot be read, the
popup shows an error for that row and stays open.

`D` is red when one or more decisions are open. `D:0`, unconfigured `D:-`, and read-error
`D:!` keep the yellow color. The count includes only open decisions. The decision popup
shows decisions whose display stage is not `완료`, including answered decisions and decisions
whose related CRs are still in progress. These items remain accessible at `D:0`. If all
decisions are complete, `D:0` ignores clicks. A completed selection moves to the first
remaining item, or an empty view when none remain. CR counts of `0`, `-`, or `!`, and
decision counts of `-` or `!`, ignore clicks without opening a popup or showing an error.
tmux keeps an open popup running if an external command changes the client's window.
If a managed pane is respawned while its client stays on the same window, run
`project-board sync` to restore that window's Board pane immediately.

## Check

```sh
~/python/.venv/bin/python -m pytest -q tools/project-board/tests
git diff --check
```
