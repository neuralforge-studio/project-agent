"""Command-line entry points for the tmux Project Board."""
from __future__ import annotations

import argparse
import sys


def _result(value: dict) -> int:
    if value.get("ok"):
        return 0
    error = value.get("error") or {}
    print(f"project-board: {error.get('message', 'operation failed')}", file=sys.stderr)
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="project-board", description="Show every registered project in tmux.")
    parser.add_argument("--config", metavar="PATH", help="project registry (default: agent-session's standard paths)")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("sidebar", help="run the sidebar TUI in this pane")
    popup = commands.add_parser("popup", help="run a decision popup TUI")
    popup.add_argument("--project", required=True, help="registered project ID")
    popup.add_argument("--decision", help="open decision ID")
    cr = commands.add_parser("cr", help="run a read-only CR list popup TUI")
    cr.add_argument("--project", required=True, help="registered project ID")
    cr.add_argument("--state", required=True, choices=("open", "todo", "in-progress"))
    toggle = commands.add_parser("toggle", help="show or hide the sidebar in tmux")
    toggle.add_argument("--client", help="tmux client that requested the global toggle")
    toggle.add_argument("--socket", help="tmux socket path")
    sync = commands.add_parser("sync", help="reconcile visible tmux windows with the global sidebar state")
    sync.add_argument("--socket", help="tmux socket path")
    click = commands.add_parser("click", help="route a tmux mouse click to a Board pane")
    click.add_argument("--client", required=True, help="tmux client name")
    click.add_argument("--pane", required=True, help="clicked pane ID")
    click.add_argument("--x", type=int, required=True, help="pane-relative column")
    click.add_argument("--y", type=int, required=True, help="pane-relative row")
    click.add_argument("--socket", help="tmux socket path")
    args = parser.parse_args(argv)

    if args.command in (None, "sidebar"):
        from . import tmux_control, tui

        def on_project(project_id, client=None):
            return tmux_control.switch_project(args.config, project_id, client)

        def on_decision(project_id, decide_id=None, client=None):
            return tmux_control.open_popup(args.config, project_id, decide_id, client)

        def on_seat(project_id, seat_index, client=None):
            return tmux_control.switch_seat(args.config, project_id, seat_index, client)

        def on_cr(project_id, state, client=None):
            return tmux_control.open_cr_popup(args.config, project_id, state, client)

        tui.run_sidebar(args.config, on_project=on_project, on_decision=on_decision,
                        on_seat=on_seat, on_cr=on_cr,
                        expanded_reader=tmux_control.expanded_projects,
                        expanded_toggler=tmux_control.toggle_expanded_project,
                        mark_ready=tmux_control.mark_ready,
                        visibility_reader=tmux_control.board_visible,
                        context_reader=tmux_control.active_context)
        return 0
    if args.command == "popup":
        from . import tui

        tui.run_popup(args.config, args.project, args.decision)
        return 0
    if args.command == "cr":
        from . import tui

        tui.run_cr_popup(args.config, args.project, args.state)
        return 0
    if args.command == "toggle":
        from . import tmux_control

        return _result(tmux_control.toggle_sidebar(args.config, args.client, args.socket))
    if args.command == "sync":
        from . import tmux_control

        return _result(tmux_control.reconcile(args.config, args.socket))
    if args.command == "click":
        from . import tmux_control

        return _result(tmux_control.route_click(args.client, args.pane, args.x, args.y, args.socket))
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
