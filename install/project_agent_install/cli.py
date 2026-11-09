"""Command line of the installer. Output is text for people; `--json` gives the same result as one object.

Exit codes: 0 done (or nothing to do), 1 `check` found a failure, 2 unknown or missing options,
3 refused before changing anything, 4 failed while changing and undid what it had done.
"""

import argparse
import json
from pathlib import Path
import sys

from . import commands, release as releases
from .layout import Env, InstallerError

COMMANDS = {
    "install": "Install this checkout as a new release with its links and the tmux include block.",
    "upgrade": "Install this checkout as a new release and point `current` at it.",
    "rollback": "Point `current` at the previous release.",
    "uninstall": "Remove what the installer made (refused while managed runs are alive).",
    "check": "Verify the installation (read-only).",
}


def build_parser():
    parser = argparse.ArgumentParser(prog="project-agent-install", description="Install project-agent into your HOME "
                                     "without touching your other settings (docs/project-team/install-contract.md).")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in COMMANDS.items():
        command = sub.add_parser(name, help=text, description=text)
        command.add_argument("--dry-run", action="store_true", help="make no change; list what would change")
        command.add_argument("--json", action="store_true", help="print the result as JSON")
        if name in ("install", "upgrade"):
            command.add_argument("--source", metavar="PATH", help="Git checkout to release (default: the checkout "
                                 "that holds this installer)")
    return parser


def _describe(env, step):
    text = "%-8s %s" % (step.action, env.display(step.path))
    return text + (" (%s)" % step.detail if step.detail else "")


def _emit(env, arguments, plan=None, applied=False, failures=(), notices=(), error=None):
    """One result for both formats."""
    changes = [] if plan is None else [{"action": step.action, "path": env.display(step.path), "kind": step.kind,
                                        "detail": step.detail} for step in plan.steps]
    notes = list(plan.notes if plan else []) + list(notices)
    ok = error is None and not failures
    if arguments.json:
        value = {"ok": ok, "command": arguments.command, "dry_run": arguments.dry_run, "changes": changes,
                 "notes": notes, "failures": list(failures)}
        if error:
            value["error"] = {"code": error.code, "message": error.message, "details": error.details}
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return
    if error:
        print("%s: %s" % (error.code, error.message), file=sys.stderr)
        for item in error.details.get("conflicts", []):
            print("  conflict %s: %s" % (item["path"], item["reason"]), file=sys.stderr)
        for item in error.details.get("runs", []):
            print("  run %s %s (%s)" % (item["project"], item["slot"], item["state"]), file=sys.stderr)
        for key in ("files", "paths"):
            for item in error.details.get(key, []):
                print("  %s" % item, file=sys.stderr)
        return
    if arguments.command != "check":
        if changes:
            print(("Would change:" if arguments.dry_run else "Changed:"))
            for step in plan.steps:
                print("  " + _describe(env, step))
        else:
            print("No change.")
    for item in failures:
        print("FAIL: " + item)
    for item in notes:
        print("Note: " + item)
    if arguments.command == "check" and ok:
        print("OK")


def main(argv=None):
    parser = build_parser()
    arguments = parser.parse_args(argv)
    env = Env()
    try:
        if arguments.command == "check":
            failures, notices = commands.run_check(env)
            _emit(env, arguments, failures=failures, notices=notices)
            return 1 if failures else 0
        root = Path(__file__).resolve().parents[2]
        if arguments.command in ("install", "upgrade"):
            source = releases.load_source(arguments.source or root)
            python = releases.installer_python()
            plan = (commands.plan_install if arguments.command == "install" else commands.plan_upgrade)(
                env, source, python)
        elif arguments.command == "rollback":
            plan = commands.plan_rollback(env)
        else:
            plan = commands.plan_uninstall(env, root)
        if not arguments.dry_run:
            commands.execute(plan)
        _emit(env, arguments, plan)
        return 0
    except InstallerError as error:
        _emit(env, arguments, error=error)
        return error.exit_code
