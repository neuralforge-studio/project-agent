# project-board

`project-board` is the tmux text interface for every registered project. One sidebar lists
each project's open, todo and in-progress CR counts, open decisions and Worker seats. A large
popup shows a decision's Markdown and accepts the operator's answer. A CR popup shows the
selected CR's full Markdown. The Board has no HTTP server or browser page.

The sidebar is the Rust binary `project-board-sidebar` (`rust/`, built with ratatui). The popups and
the `project-board` command are Python (Textual). The current behavior is specified in
`docs/project-board-tui-plan.md`. The sidebar reads the registry, `state.json`, the CR and
decision files and the run liveness itself, with the rules of `agent_session` and `project_item`
(the exception and its equivalence test are in `docs/project-team/README.md`). The popups read them
through `agent_session` and `project_item`. The Board does not edit those sources. It sends an
answer through `agent-session send --job leader`; the Leader moves the decision item.

## Dependency and install

The launcher selects the Workstation global Python first, then `~/python/.venv/bin/python`,
then `python3`. Install `requirements.txt` into the interpreter it selects (the popups need
Textual). On macOS and WSL with the standard virtual environment:

```sh
~/python/.venv/bin/python -m pip install -r tools/project-board/requirements.txt
ln -s <project-agent 저장소>/tools/project-board/bin/project-board ~/.local/bin/project-board
```

The sidebar needs its binary. An installation builds it (`install-contract.md` section 2.1 owns the
cargo and vendored crate rules) and puts it at `tools/project-board/bin/project-board-sidebar`. A
development checkout builds it once; the Board then finds `rust/target/release/project-board-sidebar`:

```sh
cd tools/project-board/rust && cargo build --release --offline --locked
```

`PROJECT_BOARD_SIDEBAR_BIN` names another binary for the Board to run.

Read `integrations/tmux/project-agent.conf` with `source-file`. An installation reads it
through `~/.local/lib/project-agent/current/integrations/tmux/project-agent.conf`; a
development checkout reads the file in the repository. The file finds its helpers next to
itself and needs no copy under `~/.tmux`.

It binds prefix `B` (set the option `@project_agent_board_key` before reading to use another
key), root `MouseDown1Pane` and root `MouseDragEnd1Border` (it saves the Board width you
dragged) only when they are unbound or have tmux's default. A key
that has another binding is left as it is and is listed in `@project_agent_board_skipped`.
Its hooks are named `[project-agent]`, so other hooks stay. It does not change your status
layout. To show the open decisions, add one line to your own tmux configuration:

```tmux
set-option -ag status-right '#{E:@project_agent_decide_status}'
```

The binding, hook and option list is in
[the install contract](../../docs/project-team/install-contract.md#53-tmux-server).

On Workstation, use `/primehome/tools/Inhouse/Python3/latest/` and request a missing package
instead of creating a virtual environment.

## Run

```sh
project-board toggle                          # show or hide the tmux sidebar
project-board --config PATH toggle            # use a specific project registry
project-board-sidebar [--config PATH]         # run the sidebar in the current pane (tmux runs this)
project-board popup --project PROJECT_ID      # show that project's unfinished decisions
project-board cr --project PROJECT_ID --state open  # show a CR list
```

The sidebar refreshes source files every 2 seconds, run liveness and the window it is in every 10
seconds. Its first read opens the files in parallel, so a 16 x 16 Board is drawn with current data
within a second. A later refresh parses again only the CR and decision files whose size or
modification time changed, and lists a directory tree again only when the modification time of one
of its directories changed (the same for the registry file). It writes to the terminal only the
cells that changed; a popup reads only its own project.
The sidebar keeps clicks and scrolling responsive during reads. It switches a client to a project or a
Worker pane itself (`rust/src/switch.rs`, the same rules as `tmux_control.switch_project` and
`switch_seat`, compared by `tests/test_rust_switch.py`). A CR or decision click tells an open window of the same kind what to show over
its socket (`rust/src/window.rs`, the BOARD-025 line); otherwise, and for the fold button, it runs a
`project-board` subcommand from the start bundle (`open-decision`, `open-cr`, `toggle-fold`); the `liveness`
subcommand judges the runs of SSH seats for it. Every periodic read starts one tmux process
(the run liveness two). Decision
answers require the `operator` caller classification from `agent-session`; a managed or
unmanaged agent session cannot submit an approval.

In tmux, prefix `B` or click `Board` in the status line to toggle the sidebar for every
attached client. The same window shares one Board pane. A window keeps its Board pane after
the last client leaves it, so returning to a window shows the Board at once instead of starting
it again; turning the Board off removes every Board pane. A window that no client has watched
has none. At most 8 Board panes are kept (about 13 MB each); a ninth removes the pane of the
window that no client showed for longest. A pane whose window no client shows stops reading and
reads once as soon as the window is shown. Each visible window gives the Board
25 columns by default and shows existing panes in the remaining space. A width adjusted in
tmux is used when the Board pane moves to another window or is created again. Turning the
Board off restores the previous pane layout and focus. Turning it on or off takes one tmux process per window; when that takes longer than
half a second, every attached client shows `Board 끄는 중 3/8` (or `켜는 중`) in the tmux message line,
which disappears by itself when the work is done. The pane's own first picture, a second or more
later, is the Board's start-up and not part of that count. A window with too little space for
the chosen width shows a smaller Board pane; another window with room restores that width.
Each project shows its decision count above the CR counts. Seats start folded. Click
`▸` to expand one project's seats, or `▾` to fold them. The fold state is shared by
Board panes in the same tmux server and survives window changes and Board off/on. Use Tab
and Enter for the same action from the keyboard. The list scrolls vertically when many
projects are present;
long names and CR IDs can be read in tooltips and by scrolling horizontally. An empty seat
shows its number followed by `-`.
A project name line ends with the Leader's elapsed time (`{project} {time}`) once its Leader session is
published, folded or expanded; there is no separate Leader row.
An SSH seat shows `number@host` before its CR ID. Its tooltip shows the registered
host and remote path. An unavailable execution check keeps the seat assigned and shows
`실행 확인 불가` with the unknown-state color.
When the window a client is viewing is a managed `agent-session` window (it has
a project option), the sidebar highlights that project with a blue name row (no mark
before the name). For a Leader window that is all. For a seat window it marks the slot too: the seat's row when the seats are expanded, or
the `▸` button (with `현재 창: seat N` in its tooltip) when they are folded. Each window's Board
pane marks its own window, so the mark follows the client when it changes window. It reads the
window options when the pane starts, when its window is shown again, and every 10 seconds. A
plain window, or a project that is not registered, highlights nothing. The rule is in
`docs/project-board-tui-plan.md` section 3.
Click a project name to switch the clicking client to that project's tmux session and
current window. If that session is unavailable, the Board shows an error. Click a CR
count to open its CR list, `D` to read decisions, or a seat with a Worker session to switch
the clicking client to its Worker window. For an SSH seat, that window contains the SSH
connection to the remote Worker's tmux screen. The Board uses the same local window switch
as for a local seat. A seat with a CR but no Worker session shows `대기` and ignores clicks,
as does an empty seat. The decision window and the CR window are floating tmux panes in
the clicking client's current window, not popups: the decision window starts at 90% of that
window, the CR window at 80%, both centred. While one is open the sidebar scrolls and
clicks, and the pane behind it (the Worker's Claude) takes input once you click it; the
window stays on top. Drag its top border to move it (or hold Alt and drag inside it) and
drag any other border to resize it. These are tmux's default mouse bindings and need
`mouse on`. A window holds one Board window: clicking another item shows it in the same
pane, where you moved it and as large as you made it. An open window of the same kind (CR or decision) is
told what to show and starts no new process, so the item appears at once; the other kind starts again in the
same pane. A window says `읽는 중…` while it reads (BOARD-025). Press `Esc` or the close button to
close it; that closes only that pane.
The CR popup is the same window whichever of `O`, `T` or `I` opened it: it lists the Open,
Todo, In-Progress and Done CRs as groups headed `Open ▼` (click to fold or unfold; Done opens
folded as `Done ▶`, and stays as you leave it while you move between projects), starts
at the group that was pressed, and shows `Open N, Todo N, In-Progress N, Done N` at the top.
Click a CR row or focus it with Tab and press Enter to read its full Markdown, done CRs
included. Select another row to change CRs. In both popups the `◀ project ▶` buttons at the
top move the same window to the previous or next project (registration order, wrapping; the
tooltip names the target). The CR popup visits every project; the decision popup visits only
projects the sidebar's `D` can open, and keeps unsent answers per decision. In either popup, `목록` is shown only below
70 columns. Use it to switch between the list and the selected item. Wider popups show
both panes and hide the button. After a popup grows and shrinks again, it shows the selected
item's body. If a listed CR file moves, is deleted, or cannot be read, the
popup shows an error for that row and stays open.

`D` is red when one or more decisions are open. `D:0`, unconfigured `D:-`, and read-error
`D:!` are always drawn faded, like a disabled button, whether or not a later-stage decision can still be opened
by clicking. The count includes only open decisions. The decision popup
shows decisions whose display stage is not `완료`, including answered decisions and decisions
whose related CRs are still in progress. These items remain accessible at `D:0` (faded, but a click opens them). If all
decisions are complete, `D:0` ignores clicks. A completed selection moves to the first
remaining item, or an empty view when none remain. CR counts of `0`, `-`, or `!`, and
decision counts of `-` or `!`, ignore clicks without opening a popup or showing an error.
An open Board window belongs to the window it was opened in; changing the client's window
leaves it there.
If a managed pane is respawned while its client stays on the same window, run
`project-board sync` to restore that window's Board pane immediately.

## Review wait

A seat shows `review_wait` when its Worker submitted and the Leader has not answered that
submission. The owner of this rule is this section; `review_wait` and `cited` in
`project_board/model.py` implement it, `tests/test_model.py` covers it, and
`rust/src/data/items.rs` follows it (`tests/test_rust_equivalence.py` compares the two).

- Only a CR in `in-progress/` can wait. A CR in any other state does not.
- A write CR waits when the last submission line of its `## Result` has a hash that its
  `## Disposition` does not cite. The syntax of the submission line
  (`- 제출 commit: <40-hex>`) is owned by `skills/project-item/references/cr.md`;
  `project_item.cr.submitted_hash` reads it. A CR without a submission line does not wait.
- A Disposition cites a hash when it contains a word of 7 to 40 hex characters that starts
  the submitted hash. Any Disposition text that names the hash answers the submission:
  an acceptance or a request for changes. A new submission hash makes the seat wait again.
- A read-only CR (`- Mode: read-only`) has no commit. It waits when its `## Result` has
  text. Known limit: after the Leader asks for changes, it still waits until the Leader
  moves the CR.
- This rule answers "has the Leader responded to the submission". It is not the acceptance
  check of `project-item move` (`project_item.cr.accepted`), which needs the exact 40-hex
  acceptance entry that `project-item accept` writes.
- The seat status is chosen in this order: no job (`empty`), a stopped Worker whose release
  waits for its CR to leave in-progress (`release_pending`, from `agent_session.api.project_pending_releases` as the 10-second run-fact refresh read it),
  no session (`pending`), the Leader's `reviewing` job (`reviewing`), `review_wait`, else `working`. The `R` mark and the
  colors are owned by `docs/project-board-tui-plan.md`.

## Check

```sh
~/python/.venv/bin/python -m pytest -q tools/project-board/tests
(cd tools/project-board/rust && cargo test --offline --locked)
git diff --check
```
