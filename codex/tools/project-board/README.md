# project-board

`project-board` is the tmux text interface for every registered project. One sidebar lists
each project's open, todo and in-progress CR counts, open decisions and Worker seats. A large
popup shows a decision's Markdown and accepts the operator's answer. The Board has no HTTP
server or browser page.

The current behavior is specified in `docs/project-board-tui-plan.md`. The registry and
team state are read through `agent_session`; CR and decision files are read through
`project_item`. The Board does not edit those sources. It sends an answer through
`agent-session send --job leader`; the Leader moves the decision item.

## Dependency and install

The launcher selects the Workstation global Python first, then `~/python/.venv/bin/python`,
then `python3`. Install `requirements.txt` into the interpreter it selects. On macOS and WSL
with the standard virtual environment:

```sh
~/python/.venv/bin/python -m pip install -r codex/tools/project-board/requirements.txt
ln -s <agent repo>/codex/tools/project-board/bin/project-board ~/.local/bin/project-board
```

Source `~/.tmux/scripts/project_board.conf` from a custom `~/.tmux.conf`. If that file
uses tmux's one-line default status, also source `project_board_home_status.conf` to add
the clickable `Board` range. The repository's `tmux/tmux.conf` already includes the Board
binding and status range.

On Workstation, use `/primehome/tools/Inhouse/Python3/latest/` and request a missing package
instead of creating a virtual environment.

## Run

```sh
project-board toggle                          # show or hide the tmux sidebar
project-board --config PATH toggle            # use a specific project registry
project-board sidebar                         # run the TUI in the current pane
project-board popup --project PROJECT_ID      # show that project's open decisions
project-board cr --project PROJECT_ID --state open  # show a CR list
```

The sidebar refreshes source files every 2 seconds and run liveness every 10 seconds.
The TUI keeps clicks and scrolling responsive during reads and answer delivery. Decision
answers require the `operator` caller classification from `agent-session`; a managed or
unmanaged agent session cannot submit an approval.

In tmux, prefix `B` or click `Board` in the status line to toggle the sidebar for every
attached client. The same window shares one Board pane. Each visible window has its own
floating Board pane over the left 30% of the window, so existing panes keep their size.
Click a project name to switch the clicking client to that project's tmux session and
current window. If that session is unavailable, the Board shows an error. Click a CR
count to read its list, `D` to read decisions, or an assigned seat to switch the clicking
client to its Worker window. The decision popup uses 90% of that client's
terminal; the CR popup uses 80%. Press `Esc` or the popup's close button to close it.
tmux keeps an open popup running if an external command changes the client's window.
If a managed pane is respawned while its client stays on the same window, run
`project-board sync` to restore that window's Board pane immediately.

## Check

```sh
~/python/.venv/bin/python -m pytest -q codex/tools/project-board/tests
git diff --check
```
