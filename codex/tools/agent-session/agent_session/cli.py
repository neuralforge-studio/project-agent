"""Parse the four public commands and emit one structured command result."""

import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys

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
        raise argparse.ArgumentTypeError("Use a seat number from 0 to 9.") from None
    if seat not in range(10):
        raise argparse.ArgumentTypeError("Use a seat number from 0 to 9.")
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
    start.add_argument("--prompt-file", type=_nonempty, metavar="FILE")
    start.add_argument("--timeout", type=_seconds, default=600, metavar="SECONDS")

    send = commands.add_parser("send", help="Send a message to a current Leader or Worker.")
    _target(send)
    body = send.add_mutually_exclusive_group(required=True)
    body.add_argument("message", nargs="?", type=_nonempty, metavar="MESSAGE")
    body.add_argument("--file", type=_nonempty, metavar="FILE")
    send.add_argument("--timeout", type=_seconds, default=30, metavar="SECONDS")

    for name, description in (("stop", "Stop a session and release it when its work is preserved."),
                              ("restart", "Replace a session with a new conversation and retain its work.")):
        command = commands.add_parser(name, help=description)
        _target(command)
        command.add_argument("--timeout", type=_seconds, default=600, metavar="SECONDS")

    return parser


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


def main(argv=None, manager_factory=None):
    """Run one command. A factory can supply an isolated manager in tests."""
    parsing = True
    operation = None
    effects_possible = False
    try:
        arguments = build_parser().parse_args(argv)
        parsing = False
        operation = arguments.command
        if operation == "start" and arguments.prompt_file is not None and arguments.job != "leader":
            raise SessionError("invalid_arguments", "--prompt-file is only valid for --job leader.", 2)
        with redirect_stdout(sys.stderr):
            effects_possible = True
            manager = (manager_factory or _default_manager)(
                cwd=None, config_path=arguments.config, socket_name=arguments.socket_name,
                socket_path=arguments.socket_path, timeout=getattr(arguments, "timeout", 600))
            if operation == "start":
                result = manager.start(arguments.job, prompt_file=arguments.prompt_file)
            elif operation == "send":
                result = manager.send(job=arguments.job, seat=arguments.seat,
                                      message=arguments.message, file=arguments.file)
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
        _emit(False, error={"code": "internal_error", "message": "The command failed. Check the retained project state.",
                            "details": {"operation": operation, "effects_possible": effects_possible}})
        return 5
