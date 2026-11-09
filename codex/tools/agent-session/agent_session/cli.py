"""Parse the four public commands and emit one structured command result."""

import argparse
from contextlib import redirect_stdout
import datetime as dt
import json
import os
from pathlib import Path
import sys
import traceback

from .errors import SessionError


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise SessionError("invalid_arguments", "Invalid command arguments. Use --help for command options.", 2)


def _nonempty(value):
    if not value.strip() or "\x00" in value:
        raise argparse.ArgumentTypeError("A nonempty value is required.")
    return value


def _seconds(value):
    try:
        seconds = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Use a positive integer number of seconds.") from None
    if seconds <= 0:
        raise argparse.ArgumentTypeError("Use a positive integer number of seconds.")
    return seconds


def _seat(value):
    try:
        seat = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Use a seat number of 0 or more.") from None
    if seat < 0:
        raise argparse.ArgumentTypeError("Use a seat number of 0 or more.")
    return seat


def _target(parser):
    choices = parser.add_mutually_exclusive_group(required=True)
    choices.add_argument("--job", type=_nonempty, metavar="LEADER_OR_CR_ID")
    choices.add_argument("--seat", type=_seat, metavar="N")


def build_parser():
    parser = Parser(prog="agent-session", description="Manage project agent sessions in tmux.")
    parser.add_argument("--config", type=_nonempty, metavar="PATH")
    sockets = parser.add_mutually_exclusive_group()
    sockets.add_argument("--socket-name", type=_nonempty, metavar="NAME")
    sockets.add_argument("--socket-path", type=_nonempty, metavar="PATH")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)

    start = commands.add_parser("start", help="Start a Leader or assign a Worker to a free seat.")
    start.add_argument("--job", required=True, type=_nonempty, metavar="LEADER_OR_CR_ID")
    start.add_argument("--seat", type=_seat, metavar="N", help="Choose one Worker seat instead of automatic allocation.")
    start.add_argument("--prompt-file", type=_nonempty, metavar="FILE")
    start.add_argument("--timeout", type=_seconds, default=600, metavar="SECONDS")

    send = commands.add_parser("send", help="Send a message to a current Leader or Worker.")
    _target(send)
    body = send.add_mutually_exclusive_group(required=True)
    body.add_argument("message", nargs="?", type=_nonempty, metavar="MESSAGE")
    body.add_argument("--file", type=_nonempty, metavar="FILE")
    send.add_argument("--project", type=_nonempty, metavar="PROJECT")
    send.add_argument("--timeout", type=_seconds, default=30, metavar="SECONDS")

    for name, description in (("stop", "Stop a session and release it when its work is preserved."),
                              ("restart", "Replace a session with a new conversation and retain its work.")):
        command = commands.add_parser(name, help=description)
        _target(command)
        command.add_argument("--timeout", type=_seconds, default=600, metavar="SECONDS")

    review = commands.add_parser("review", help="Mark the Worker JOB the Leader reviews now, or clear the mark.")
    marks = review.add_mutually_exclusive_group(required=True)
    marks.add_argument("--job", type=_nonempty, metavar="CR_ID")
    marks.add_argument("--clear", action="store_true")
    review.add_argument("--timeout", type=_seconds, default=30, metavar="SECONDS")

    for name, description in (("shutdown", "End every Claude session of the selected projects and record them for resume."),
                              ("resume", "Reopen the sessions that shutdown recorded, in the same conversations.")):
        command = commands.add_parser(name, help=description)
        selection = command.add_mutually_exclusive_group(required=True)
        selection.add_argument("--project", type=_nonempty, metavar="NAME")
        selection.add_argument("--all", action="store_true")
        command.add_argument("--timeout", type=_seconds, default=600, metavar="SECONDS")
        if name == "shutdown":
            command.add_argument("--force", action="store_true")

    return parser


def _default_fleet(**kwargs):
    from .lifecycle import Manager
    from .suspend import Fleet
    return Fleet(Manager, **kwargs)


def _default_manager(**kwargs):
    from .lifecycle import Manager
    return Manager(**kwargs)


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    raise TypeError("Command results must contain JSON values.")


def _emit(ok, data=None, error=None):
    raw = json.dumps({"ok": ok, "data": data, "error": error}, ensure_ascii=False, default=_json_default)
    print(raw, flush=True)


def _diagnostic(manager, operation):
    """Write the current traceback to a private file of the selected project. Return None on any failure."""
    try:
        directory = manager.project.runtime_path / "diagnostics"
        directory.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        path = directory / f"{stamp}-{operation}-{os.getpid()}.log"
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as stream:
            stream.write(traceback.format_exc())
        return str(path)
    except Exception:
        return None


def main(argv=None, manager_factory=None, fleet_factory=None):
    """Run one command. A factory can supply an isolated manager (or, for shutdown and resume, fleet) in tests."""
    parsing = True
    operation = None
    effects_possible = False
    manager = None
    try:
        arguments = build_parser().parse_args(argv)
        parsing = False
        operation = arguments.command
        if os.environ.get("AGENT_SESSION_UPLINK") and manager_factory is None:
            from .remote_bridge import forward
            _emit(True, data=forward(arguments))
            return 0
        with redirect_stdout(sys.stderr):
            effects_possible = True
            if operation in ("shutdown", "resume"):
                fleet = (fleet_factory or _default_fleet)(
                    config_path=arguments.config, socket_name=arguments.socket_name,
                    socket_path=arguments.socket_path, timeout=arguments.timeout)
                if operation == "shutdown":
                    result = fleet.shutdown(project=arguments.project, everything=arguments.all, force=arguments.force)
                else:
                    result = fleet.resume(project=arguments.project, everything=arguments.all)
            else:
                manager = (manager_factory or _default_manager)(
                    cwd=None, config_path=arguments.config, socket_name=arguments.socket_name,
                    socket_path=arguments.socket_path, timeout=getattr(arguments, "timeout", 600))
                if operation == "start":
                    result = manager.start(arguments.job, prompt_file=arguments.prompt_file, seat=arguments.seat)
                elif operation == "send":
                    result = manager.send(job=arguments.job, seat=arguments.seat,
                                          message=arguments.message, file=arguments.file,
                                          project=arguments.project)
                elif operation == "review":
                    result = manager.review(job=arguments.job, clear=arguments.clear)
                else:
                    result = manager.control(operation, job=arguments.job, seat=arguments.seat)
        if not isinstance(result, dict):
            raise SessionError("internal_error", "The command did not return a structured result.", 5,
                               {"operation": operation, "effects_possible": effects_possible})
        _emit(True, data=result)
        return 0
    except SessionError as exc:
        try:
            _emit(False, error=exc.as_dict())
        except (TypeError, ValueError):
            _emit(False, error={"code": "internal_error", "message": "Cannot encode the command error.",
                                "details": {"operation": operation, "effects_possible": effects_possible}})
            return 5
        return exc.exit_code
    except SystemExit as exc:
        if parsing and exc.code == 0:
            return 0
        _emit(False, error={"code": "internal_error", "message": "The command exited without a result.",
                            "details": {"operation": operation, "effects_possible": effects_possible}})
        return 5
    except KeyboardInterrupt:
        _emit(False, error={"code": "interrupted", "message": "Command interrupted. Read project state before retrying.",
                            "details": {"operation": operation, "effects_possible": effects_possible}})
        return 4
    except Exception:
        details = {"operation": operation, "effects_possible": effects_possible}
        diagnostic = _diagnostic(manager, operation)
        if diagnostic:
            details["diagnostic"] = diagnostic
        _emit(False, error={"code": "internal_error", "message": "The command failed. Check the retained project state.",
                            "details": details})
        return 5
