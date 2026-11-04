"""Commands of project-item."""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

from . import registry, render, store
from .kinds import CR, DECIDE, KINDS, kind_of_id
from .registry import ItemError


def _common() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="project registry (default: ~/.codex/project.json or ~/.claude/project.json)")
    common.add_argument("--project", help="project name (default: the project of the cwd)")
    return common


def _select(args):
    return registry.select(args.config, args.project)


def _counts(kind, root: Path) -> str:
    return " ".join(f"{s}={len(store.item_files(kind, root, s))}" for s in kind.states)


def _body(path_arg: str | None, empty: str) -> str:
    if not path_arg:
        return empty
    text = (sys.stdin.read() if path_arg == "-" else Path(path_arg).read_text(encoding="utf-8")).strip()
    if not text:
        raise ItemError("body_empty", "The body is empty.")
    return text + "\n"


def _report_format(kind, path: Path) -> None:
    for msg in kind.fmt.check(kind.fmt.parse(path, "open")):
        print(f"  format: {msg}")


def _render(project, root: Path) -> None:
    print(f"page {render.render(project.project_id, root)}")


# ---------------------------------------------------------------- commands
def cmd_projects(args) -> int:
    for project in registry.projects(args.config):
        print(f"{project.project_id:12s} base {project.base}")
        for name, kind in KINDS.items():
            key = registry.KEYS[name]
            try:
                root = registry.item_root(project, name)
            except ItemError as error:
                print(f"{'':12s} {name:6s} ({error.code}) {error.message}")
                continue
            state = _counts(kind, root) if root.is_dir() else "(no directory yet)"
            print(f"{'':12s} {name:6s} {root}  {state}")
    return 0


def cmd_ls(args) -> int:
    project = _select(args)
    for name in ([args.kind] if args.kind else list(KINDS)):
        kind = KINDS[name]
        try:
            root = registry.item_root(project, name)
        except ItemError as error:
            if args.kind:
                raise
            print(f"-- {name}: {error.code}")
            continue
        states = args.state or (kind.states if args.all else kind.listed)
        for state in states:
            if state not in kind.states:
                raise ItemError("invalid_state", f"{name} states are {', '.join(kind.states)}.")
            for path in store.item_files(kind, root, state):
                item = kind.fmt.parse(path, state)
                level = (item.headers.get("Severity") if kind is CR else item.headers.get("Urgency")) or "--"
                print(f"{name:6s} {state:8s} {level.split()[0]:6s} {kind.item_id(item) or path.stem:14s} "
                      f"{(item.title or '')[:90]}")
        print(f"-- {name}: {root}  {_counts(kind, root) if root.is_dir() else '(no directory yet)'}")
    return 0


def cmd_new_cr(args) -> int:
    project = _select(args)
    root = registry.item_root(project, "cr")
    if not re.fullmatch(r"[A-Z][A-Z0-9]*", args.area):
        raise ItemError("invalid_area", "--area must be upper-case letters and digits.")
    body = _body(args.body_file, CR.fmt.EMPTY_BODY)
    source = registry.project_of_cwd(args.config)
    source_name = source.project_id if source else "unknown"
    today = dt.date.today().isoformat()
    extra = ""
    if source_name != project.project_id:
        extra = f"- Requester: {source_name}, {os.getcwd()}, {today}\n"
    path = store.new_cr(root, args.area, args.title, lambda item_id: CR.fmt.TEMPLATE.format(
        cr_id=item_id, title=args.title, opened=today, scope=args.scope or project.project_id,
        severity=args.severity, extra=extra, body=body))
    print(f"opened {path}")
    if args.body_file:
        _report_format(CR, path)
    if source_name != project.project_id:
        owners = registry.owner_sessions(project)
        if owners:
            print(f"notify: SendMessage to='{owners[0]['name']}' message='[project-item] {project.project_id} "
                  f"{store.file_id(CR, path)} from {source_name}: {args.title}. {path}'")
        else:
            print("notify: no live owner session; the owner sees the CR with `project-item ls`.")
    return 0


def cmd_new_decide(args) -> int:
    project = _select(args)
    root = registry.item_root(project, "decide")
    body = _body(args.body_file, DECIDE.fmt.EMPTY_BODY)
    opened = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    extra = "".join(f"- {key}: {value}\n" for key, value in (("Blocks", args.blocks), ("Related", args.related))
                    if value)
    path = store.new_decide(root, lambda item_id: DECIDE.fmt.TEMPLATE.format(
        item_id=item_id, title=args.title, opened=opened, urgency=args.urgency, extra=extra, body=body))
    print(f"opened {path}")
    if args.body_file:
        _report_format(DECIDE, path)
    _render(project, root)
    return 0


def cmd_check(args) -> int:
    """Exit 0 = every checked file follows the format and IDs are unique, 1 = violations."""
    project = _select(args)
    words = list(args.targets)
    kind_name = words.pop(0) if words and words[0] in KINDS else None
    names = [kind_name] if kind_name else [n for n in KINDS if getattr(project, registry.KEYS[n]) is not None]
    if not names:
        raise ItemError("item_path_unset", f"Project '{project.project_id}' has no item paths.")
    if words and len(names) != 1:
        raise ItemError("kind_missing", "Name the kind (cr or decide) before the paths.")
    total = 0
    for name in names:
        kind = KINDS[name]
        root = registry.item_root(project, name)
        failed = 0
        if words:
            targets = []
            for raw in words:
                path = Path(raw).resolve()
                state = next((s for s in kind.states if (root / s).resolve() in path.parents), None)
                targets.append((state, path))
        else:
            targets = store.check_targets(kind, root)
        for state, path in targets:
            if state is None:
                print(f"{path}: not under {root}/<{'|'.join(kind.states)}>/")
                failed += 1
                continue
            bad = kind.fmt.check(kind.fmt.parse(path, state))
            if bad:
                failed += 1
                print(path.relative_to(root.resolve()) if path.is_relative_to(root.resolve()) else path)
                for msg in bad:
                    print(f"  - {msg}")
        dups = store.duplicates(kind, root)
        for item_id, paths in sorted(dups.items()):
            failed += 1
            print(f"duplicate ID {item_id}: " + ", ".join(str(p.relative_to(root)) for p in paths))
        print(f"-- {name}: {len(targets)} checked, {len(dups)} duplicate IDs, {failed} with violations")
        total += failed
    return 1 if total else 0


def cmd_move(args) -> int:
    project = _select(args)
    kind = kind_of_id(args.id)
    root = registry.item_root(project, kind.name)
    if args.state == "in-progress" and project.seats:
        raise ItemError("agent_session_only", "In a team project, `agent-session start --job <CR-ID>` "
                        "moves a CR to in-progress with its seat assignment.")
    target = store.move(kind, root, args.id, args.state, outcome=args.outcome, by=args.by, note=args.note)
    print(f"moved {target}")
    if kind is DECIDE:
        _render(project, root)
    return 0


def cmd_render(args) -> int:
    project = _select(args)
    root = registry.item_root(project, "decide")
    out = Path(args.out).resolve() if args.out else None
    print(f"page {render.render(project.project_id, root, out)}")
    return 0


def cmd_owner(args) -> int:
    project = registry.select(args.config, args.name)
    rows = registry.owner_sessions(project)
    if not rows:
        print(f"{project.project_id}: no live owner session under {project.base} or its seats.", file=sys.stderr)
        return 1
    for row in rows:
        print(row["name"])
    return 0


# ---------------------------------------------------------------- parser
def parser() -> argparse.ArgumentParser:
    common = _common()
    ap = argparse.ArgumentParser(prog="project-item", description=(
        "CR and decision items of a registered project. "
        "Rules: codex/skills/project-item/SKILL.md."))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("projects", parents=[common], help="projects, item roots and counts")
    p.set_defaults(run=cmd_projects)

    p = sub.add_parser("ls", parents=[common], help="items (default: cr open/todo/deferred, decide open)")
    p.add_argument("kind", nargs="?", choices=KINDS)
    p.add_argument("--state", action="append", help="repeatable")
    p.add_argument("--all", action="store_true", help="every state")
    p.set_defaults(run=cmd_ls)

    p = sub.add_parser("new", help="create an item in open/")
    new = p.add_subparsers(dest="kind", required=True)
    q = new.add_parser("cr", parents=[common], epilog=(
        "Body (markdown, from --body-file or stdin '-'): ## Symptom, ## Evidence, ## Contract, in this "
        "order. Without a body the command writes empty sections."),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    q.add_argument("--area", required=True, help="AREA of the ID, for example TOOL")
    q.add_argument("--title", required=True)
    q.add_argument("--severity", default="S2", choices=CR.fmt.SEVERITIES)
    q.add_argument("--scope", help="review scope (default: the project name)")
    q.add_argument("--body-file", help="markdown body; '-' = stdin")
    q.set_defaults(run=cmd_new_cr)
    q = new.add_parser("decide", parents=[common], epilog=(
        "Body (markdown, from --body-file or stdin '-'): ## Background, ## Options (table), "
        "## Recommendation, ## Evidence, in this order."),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    q.add_argument("--title", required=True, help="the question in one line")
    q.add_argument("--urgency", default="normal", choices=DECIDE.fmt.URGENCIES)
    q.add_argument("--blocks", help="what waits for the decision")
    q.add_argument("--related", help="related CR, JOB or decision IDs")
    q.add_argument("--body-file", help="markdown body; '-' = stdin")
    q.set_defaults(run=cmd_new_decide)

    p = sub.add_parser("check", parents=[common], usage="project-item check [cr|decide] [paths ...]",
                       help="format and ID check (exit 1 on a violation)")
    p.add_argument("targets", nargs="*", metavar="cr|decide|path",
                   help="optional kind, then file paths (default: every kind and the files to check)")
    p.set_defaults(run=cmd_check)

    p = sub.add_parser("move", parents=[common], help="move an item to another state")
    p.add_argument("id")
    p.add_argument("state")
    p.add_argument("--outcome", help="Outcome header for done/ or deferred/")
    p.add_argument("--by", help="decider; writes one Disposition entry")
    p.add_argument("--note", help="reason or the user's words for the Disposition entry")
    p.set_defaults(run=cmd_move)

    p = sub.add_parser("render", parents=[common], help="write the decision page")
    p.add_argument("kind", choices=("decide",))
    p.add_argument("--out", help="page path (default: <path_decide>/decide.html)")
    p.set_defaults(run=cmd_render)

    p = sub.add_parser("owner", parents=[common], help="live owner session names of a project")
    p.add_argument("name")
    p.set_defaults(run=cmd_owner)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.run(args)
    except ItemError as error:
        print(f"project-item: {error.code}: {error.message}", file=sys.stderr)
        return 2
