"""Command line of the installer. Output is text for people; `--json` gives the same result as one object.

Exit codes: 0 done (or nothing to do), 1 `check` found a failure, 2 unknown or missing options,
3 refused before changing anything, 4 failed while changing and undid what it had done.
"""

import argparse
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True      # importing the product's agent_session must not write into the checkout or a release

from . import commands, journal, release as releases, tmuxrecord
from .layout import Env, InstallerError

COMMANDS = {
    "install": "Install this checkout as a new release with its links and the tmux include block.",
    "upgrade": "Install this checkout as a new release and point `current` at it.",
    "rollback": "Point `current` at the previous release.",
    "prune": "Remove the releases that are not current, previous or used by a run that is up.",
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
        if name == "install":
            command.add_argument("--adopt-dev-links", metavar="CHECKOUT", help="take over the links of the old "
                                 "development checkout CHECKOUT (shims and skills; see contract section 2, rule 8)")
    return parser


def _describe(env, step):
    text = "%-8s %s" % (step.action, env.display(step.path))
    return text + (" (%s)" % step.detail if step.detail else "")


def _emit(env, arguments, plan=None, applied=False, failures=(), notices=(), error=None):
    """One result for both formats."""
    shown = [] if plan is None else [step for step in plan.steps if not step.internal]
    changes = [{"action": step.action, "path": env.display(step.path), "kind": step.kind, "detail": step.detail}
               for step in shown]
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
            print("  run %s %s (%s)%s" % (item["project"], item["slot"], item["state"],
                                          ": " + item["note"] if item.get("note") else ""), file=sys.stderr)
        for key in ("files", "paths"):
            for item in error.details.get(key, []):
                print("  %s" % item, file=sys.stderr)
        return
    if arguments.command != "check":
        if changes:
            print(("Would change:" if arguments.dry_run else "Changed:"))
            for step in shown:
                print("  " + _describe(env, step))
        else:
            print("No change.")
    for item in failures:
        print("FAIL: " + item)
    for item in notes:
        print("Note: " + item)
    if arguments.command == "check" and ok:
        print("OK")


def _pending(env, arguments):
    """An interrupted run is dealt with before anything else. Returns (note, notes about what was left alone);
    the note is "finished" when an interrupted uninstall or prune was completed (that is then the whole command)."""
    if arguments.command != "check" and not arguments.dry_run:
        journal.clean_temporary(env)
    path = journal.find(env)
    if path is None:
        return None, []
    pending = journal.read(env, path)
    if arguments.dry_run:
        raise InstallerError("run_interrupted", "A previous %s was interrupted (%s). Run the command without "
                             "--dry-run to recover first." % (pending.command, env.display(path)))
    if pending.mode == "redo":
        if arguments.command != pending.command:
            raise InstallerError("%s_interrupted" % pending.command, "A previous %s was interrupted. Run `%s` "
                                 "to finish it before anything else." % (pending.command, pending.command))
        return "finished", journal.resume(env, pending)
    failures, notes = journal.recover(env, pending)
    if failures:
        raise InstallerError("recovery_failed", "The interrupted %s could not be undone (%s). Nothing else was "
                             "done; run the command again." % (pending.command, "; ".join(failures)), exit_code=4)
    return "A previous %s was interrupted; it was undone." % pending.command, notes


def main(argv=None):
    parser = build_parser()
    arguments = parser.parse_args(argv)
    env = Env()
    try:
        recovered, left = (None, []) if arguments.command == "check" else _pending(env, arguments)
        if recovered == "finished":
            _emit(env, arguments, commands.Plan(arguments.command),
                  notices=["The interrupted %s was finished." % arguments.command] + left)
            return 0
        root = Path(__file__).resolve().parents[2]
        if arguments.command == "check":
            failures, notices = commands.run_check(env, root)
            _emit(env, arguments, failures=failures, notices=notices)
            return 1 if failures else 0
        if arguments.command in ("install", "upgrade"):
            source = releases.load_source(arguments.source or root)
            python = releases.installer_python()
            tmux = tmuxrecord.choose(source.root)
            if arguments.command == "install":
                adopt = arguments.adopt_dev_links
                plan = commands.plan_install(env, source, python, tmux,
                                             os.path.abspath(os.path.expanduser(adopt)) if adopt else None)
            else:
                plan = commands.plan_upgrade(env, source, python, tmux, root)
        elif arguments.command == "rollback":
            plan = commands.plan_rollback(env, root)
        elif arguments.command == "prune":
            plan = commands.plan_prune(env, root)
        else:
            plan = commands.plan_uninstall(env, root)
        if not arguments.dry_run:
            left += journal.execute(env, plan)
        _emit(env, arguments, plan, notices=([recovered] if recovered else []) + left)
        return 0
    except InstallerError as error:
        _emit(env, arguments, error=error)
        return error.exit_code
