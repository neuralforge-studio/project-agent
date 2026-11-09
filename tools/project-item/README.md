# project-item

`project-item` creates, lists, checks and moves the CR and decision items of a registered
project. Codex and Claude Code use the same copy.

- Rules: this tool does not define rules. The owners are
  `skills/project-item/SKILL.md` (states, transitions, who moves an item, when to use
  which command) and, per kind, `skills/project-item/references/cr.md` (CR) and
  `skills/project-item/references/decide.md` (decisions): headers, sections and
  Outcome values.
- Executable copies: `project_item/kinds.py`, `project_item/cr.py` and
  `project_item/decide.py`. `tests/test_doc_contract.py` fails when they differ from the
  documents.
- Registry: the project registry of agent-session (standard locations in `docs/project-team/install-contract.md` section 6, contract in
  `docs/project-team/spec.md` section 2). The keys `path_cr` and `path_decide` give the item
  roots. This tool imports the registry parser from the sibling `tools/agent-session`.
- Product map: `docs/project-team/README.md`.
- Python: Workstation `/primehome/tools/Inhouse/Python3/latest`, WSL `~/python/.venv`,
  else `python3`. Standard library only.

## Install

```sh
ln -s <project-agent 저장소>/tools/project-item/bin/project-item ~/.local/bin/project-item
```

`~/.local/bin` must be in `PATH`. The entry resolves its own link, so the source tree is
the only copy.

## Layers and public API

Other tools and tmux scripts import `project_item.api` and nothing else of this package.
The names in `api.__all__` are the public interface (`project_item/api.py`);
`tests/test_api_boundary.py` checks the consumers. A consumer that needs another name asks for
it in `api.py`.

| Layer | Modules | Rule |
| --- | --- | --- |
| Public API | `api.py` | lists what a consumer may use; owns no logic |
| Domain core | `errors.py`, `cr.py`, `decide.py`, `kinds.py`, `read.py` | formats, transitions, the rules a move applies (`prepare_move`, `check_outcome` of each format module), reads (sections, CR states, decision stage). Imports neither `render` nor `cli` (tested) |
| Files and project | `store.py`, `assign.py`, `guard.py`, `registry.py` | files, the root lock, git, project selection and caller checks; `store.move_locked` applies the core rules and moves the file |
| Output | `render.py`, `cli.py` | the decision page and the command line |

`project_item.registry.ItemError` remains importable; `errors.ItemError` is the definition.

## Commands

`project-item --help` and `project-item <command> --help` own the options and inputs. This
table names the commands only.

| Command | What it does |
| --- | --- |
| `projects` | projects, item roots and counts per state |
| `ls` | list items. The default states of each kind are `Kind.listed` in `project_item/kinds.py` |
| `new` | open a CR (`new cr`) or a decision (`new decide`) with the next number; a decision also writes the page |
| `answer` | record the answer of an open decision and move it to `answered/` |
| `accept` | record the Leader's acceptance of a submitted CR commit in the Disposition |
| `move` | check the transition and the destination format, then move |
| `check` | format check and duplicate IDs; exit 1 on a violation |
| `render` | write the decision page |
| `owner` | live interactive Claude Code sessions under the base or a seat |

Every command takes `--config PATH` and `--project NAME`. Without `--project`, the
project of the working directory is used (the agent-session rule).

`check` without paths reads every file in a non-terminal state and the terminal files
that are not committed. Outside a git work tree it reads every file. It reports an ID that
has more than one file in any state.

## What `move` does

1. It checks that the pair of source and destination states is in the transition table of
   SKILL.md.
2. With `--outcome`, it writes the Outcome header. With `--by`, it writes a Disposition entry
   with `--note` as the reason. A decision needs a decider, so `--outcome` and `--note`
   need `--by`; without it the move stops with `decider_missing`. An Outcome that does not
   fit the destination stops with `invalid_outcome` (for example `moved` outside
   `deferred/`).
3. It checks the format of the destination state. On a violation the file does not change.
4. A file that git tracks moves with `git mv`; an untracked file is renamed. If the move
   fails, the text and path return to the original state and the index is not written. If
   they cannot return, `move_partial` names the paths and index entries that are left.
5. The tool does not commit. The session in charge commits under the project rules.

## Errors

Errors print `project-item: <code>: <message>` and exit 2.

| Code | Cause |
| --- | --- |
| `item_path_unset` | the project has no `path_cr` or `path_decide` |
| `project_not_found` | no project with that name, or the cwd is outside every project |
| `invalid_transition` | the move is not in the transition table, or `fixed` does not come from `todo` or `in-progress` |
| `invalid_outcome` | the Outcome does not fit the destination (for example `moved` outside `deferred/`) |
| `format_invalid` | the item does not meet the format of the destination state |
| `reason_missing`, `decider_missing` | a move back to `open` needs `--by` and `--note`; `--outcome` and `--note` need `--by` |
| `item_not_found`, `item_duplicate` | no file, or several files, for the ID |
| `target_exists`, `git_mv_failed`, `move_failed` | the move could not take place; the text, path and index did not change |
| `move_partial` | the move failed and could not be undone; the message names the paths and index entries that are left |
| `agent_session_only` | in a team project, only `agent-session start` moves a CR to `in-progress` |
| `role_denied` | the caller may not do this. In a team project, `answer` and `accept` need the current Leader. A move out of `in-progress` needs the current Leader or an operator; `--by Leader` needs the current Leader |
| `review_missing` | a write CR does not go from `in-progress` to `done` with `fixed` without the recorded submission, the Leader's acceptance and the commit on `origin/main` |
| `not_team_project`, `commit_invalid` | `accept` outside a team project, or `--commit` is not the 40-hex submitted commit |
| `decide_not_open`, `answer_empty`, `answer_invalid`, `answer_too_large` | `answer` rejects the decision state or the answer text |
| `registry_invalid`, `registry_not_found` | registry errors from agent-session |

## Lock

`new`, `answer`, `move` and the page write of `render` hold one `flock` per item root:
`~/.cache/project-item/locks/<first 16 hex of SHA-256 of the root path>.lock`. The lock
orders sessions of one machine. It does not order two machines that write the same network
path; `check` finds the duplicate IDs that such a race can make.

## Tests

```sh
~/python/.venv/bin/python -m pytest -q tools/project-item/tests
```
