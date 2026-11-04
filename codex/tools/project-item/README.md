# project-item

`project-item` creates, lists, checks and moves the CR and decision items of a registered
project. Codex and Claude Code use the same copy.

- Rules: `codex/skills/project-item/SKILL.md` (common skeleton, states, transitions,
  commands). Kind rules: `codex/skills/project-item/references/cr.md` (CR) and
  `codex/skills/project-item/references/decide.md` (decisions). This tool does not define
  rules.
- Executable copies of the formats: `project_item/cr.py` and `project_item/decide.py`.
  The legacy `cr` tool re-exports `project_item/cr.py`.
- Registry: the project registry of agent-session (`~/.codex/project.json`, contract in
  `docs/project-team/spec.md` section 2). The keys `path_cr` and `path_decide` give the item
  roots. This tool imports the registry parser from the sibling `codex/tools/agent-session`.
- Python: Workstation `/primehome/tools/Inhouse/Python3/latest`, WSL `~/python/.venv`,
  else `python3`. Standard library only.

## Install

```sh
ln -s <agent repo>/codex/tools/project-item/bin/project-item ~/.local/bin/project-item
```

`~/.local/bin` must be in `PATH`. The entry resolves its own link, so the source tree is
the only copy.

## Commands

| Command | What it does |
| --- | --- |
| `projects` | projects, item roots and counts per state |
| `ls [cr\|decide] [--state S] [--all]` | items (default: cr open/todo/deferred, decide open) |
| `new cr --area A --title T [--severity S] [--scope X] [--body-file F]` | open a CR with the next number |
| `new decide --title T [--urgency U] [--blocks B] [--related R] [--body-file F]` | open a decision with the next number of the day, then write the page |
| `move ID STATE [--outcome O] [--by B] [--note N]` | check the transition and the destination format, then move |
| `check [cr\|decide] [paths]` | format check and duplicate IDs; exit 1 on a violation |
| `render decide [--out F]` | write the decision page (default `<path_decide>/decide.html`) |
| `owner PROJECT` | live interactive Claude Code sessions under the base or a seat |

Every command takes `--config PATH` and `--project NAME`. Without `--project`, the
project of the working directory is used (the agent-session rule).

`check` without paths reads every file in a non-terminal state and the terminal files
that are not committed. Outside a git work tree it reads every file. It reports an ID that
has more than one file in any state.

## Errors

Errors print `project-item: <code>: <message>` and exit 2.

| Code | Cause |
| --- | --- |
| `item_path_unset` | the project has no `path_cr` or `path_decide` |
| `item_path_duplicate` | the item root overlaps a CR directory in the legacy `programs.json` |
| `project_not_found` | no project with that name, or the cwd is outside every project |
| `invalid_transition` | the move is not in the transition table, or `fixed` does not come from `todo` |
| `invalid_outcome` | the Outcome does not fit the destination (for example `moved` outside `deferred/`) |
| `format_invalid` | the item does not meet the format of the destination state |
| `reason_missing`, `decider_missing` | a move needs `--by` and `--note` |
| `item_not_found`, `item_duplicate` | no file, or several files, for the ID |
| `target_exists`, `git_mv_failed`, `move_failed` | the move could not take place; the text, path and index did not change |
| `move_partial` | the move failed and could not be undone; the message names the paths and index entries that are left |
| `registry_invalid`, `registry_not_found` | registry errors from agent-session |

## Lock

`new`, `move` and the page write of `render` hold one `flock` per item root:
`~/.cache/project-item/locks/<first 16 hex of SHA-256 of the root path>.lock`. The lock
orders sessions of one machine. It does not order two machines that write the same network
path; `check` finds the duplicate IDs that such a race can make.

## Tests

```sh
~/python/.venv/bin/python -m pytest -q codex/tools/project-item/tests
```
