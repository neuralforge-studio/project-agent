# project-board

`project-board` serves one local page that shows every registered project team: the
Leader, the seats and their Workers, the CR counts and the decisions that wait for the user.
The page can send a decision answer to the project's Leader.

- Rules: `docs/project-board-plan.md` (sources, screen states, review-wait rule, liveness,
  answer sending, security). The screen follows `docs/project-board-mockup.html`.
- Sources, read again on every request; the server keeps no state besides its token:
  - registry, `state.json` and run liveness through `agent_session.api`
    (`read_state`, `liveness`) of the sibling `codex/tools/agent-session`
  - CR and decision files through `project_item` of the sibling `codex/tools/project-item`
- Writes: none. An answer goes out through `agent-session send --job leader`. The Leader moves
  the decision item.
- Python: Workstation `/primehome/tools/Inhouse/Python3/latest`, WSL `~/python/.venv`,
  else `python3`. Standard library only.

## Install

```sh
ln -s <agent repo>/codex/tools/project-board/bin/project-board ~/.local/bin/project-board
```

## Run

```sh
project-board                 # http://127.0.0.1:8765/
project-board --port 8800 --config ~/.codex/project.json --verbose
```

Start the board from your own terminal. If it runs inside an unmanaged agent session (for
example Claude Code), `agent-session` refuses its answers with `caller_unbound`. Inside a
registered Leader or Worker the answer becomes a peer message, which is not a decision
approval. The server prints a warning at start when it sees an agent identity.

The server binds `127.0.0.1` only. Answers need the page's token in `X-Board-Token`, a JSON
body, a `Host` of `127.0.0.1:<port>` or `localhost:<port>` and a matching `Origin` when one
is sent. These checks stop other web sites from sending through the browser. They are not a
login: local processes are trusted, as they are by `agent-session` itself.

## Endpoints

| Method and path | Result |
| --- | --- |
| `GET /` | the page with this run's token |
| `GET /api/board` | every project: Leader, seats with derived states, CR lists (open, todo, in-progress), open decisions, per-project errors |
| `GET /api/live` | per project and bound slot: the judged `session_id` and `alive`, `stopped` or `unknown` |
| `POST /api/answer` | `{"project", "decide_id", "answer"}`; returns the `agent-session send` result |

The page polls `/api/board` every 2 seconds and `/api/live` every 10 seconds.

## Tests

```sh
~/python/.venv/bin/python -m pytest -q codex/tools/project-board/tests
```
