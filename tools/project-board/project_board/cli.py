"""Command-line entry points for the tmux Project Board."""
from __future__ import annotations

import argparse
import json
import sys


def _result(value: dict) -> int:
    if value.get("ok"):
        return 0
    error = value.get("error") or {}
    print(f"project-board: {error.get('message', 'operation failed')}", file=sys.stderr)
    return 1


def _liveness(config, project_id: str) -> int:
    """One project's `model.liveness` entry as JSON, for the sidebar: it asks for the seats on a remote host,
    whose run is judged over SSH (`agent_session.remote`)."""
    from . import model

    project = model.find_project(config, project_id)
    if project is None:
        print(f"project-board: the project {project_id} is not registered", file=sys.stderr)
        return 1
    try:
        print(json.dumps(model.liveness_of(project)))
    except Exception as error:
        print(f"project-board: {error}", file=sys.stderr)
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="project-board", description="Show every registered project in tmux.")
    parser.add_argument("--config", metavar="PATH", help="project registry (default: agent-session's standard paths)")
    commands = parser.add_subparsers(dest="command")
    popup = commands.add_parser("popup", help="run a decision popup TUI")
    popup.add_argument("--project", required=True, help="registered project ID")
    popup.add_argument("--decision", help="open decision ID")
    cr = commands.add_parser("cr", help="run a read-only CR list popup TUI")
    cr.add_argument("--project", required=True, help="registered project ID")
    cr.add_argument("--state", required=True, choices=("open", "todo", "in-progress"))
    cron = commands.add_parser("cron", help="run a read-only cron job list window TUI")
    cron.add_argument("--project", required=True, help="registered project ID")
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
    # The sidebar (the `project-board-sidebar` binary) runs these for its clicks. It switches a client to a project or a
    # Worker pane itself (rust/src/switch.rs).
    for name, text in (("open-decision", "open a project's decision window on the client"),
                       ("open-cr", "open a project's CR window on the client"),
                       ("open-cron", "open a project's cron window on the client")):
        action = commands.add_parser(name, help=text)
        action.add_argument("--project", required=True, help="registered project ID")
        action.add_argument("--client", help="tmux client that clicked")
        if name == "open-cr":
            action.add_argument("--state", required=True, choices=("open", "todo", "in-progress"))
    fold = commands.add_parser("toggle-fold", help="fold or expand one project's seats in every Board pane")
    fold.add_argument("--project", required=True, help="registered project ID")
    liveness = commands.add_parser("liveness", help="print one project's run liveness as JSON (remote seats are judged here)")
    liveness.add_argument("--project", required=True, help="registered project ID")
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    if args.command == "popup":
        from . import tmux_control, tui

        tui.run_popup(args.config, args.project, args.decision, mark_link=tmux_control.mark_window_ready)
        return 0
    if args.command == "cr":
        from . import tmux_control, tui

        tui.run_cr_popup(args.config, args.project, args.state, mark_link=tmux_control.mark_window_ready)
        return 0
    if args.command == "cron":
        from . import tmux_control, tui

        tui.run_cron_popup(args.config, args.project, mark_link=tmux_control.mark_window_ready)
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
    if args.command in ("open-decision", "open-cr", "open-cron", "toggle-fold", "liveness"):
        from . import tmux_control

        if args.command == "open-decision":
            return _result(tmux_control.open_popup(args.config, args.project, None, args.client))
        if args.command == "open-cr":
            return _result(tmux_control.open_cr_popup(args.config, args.project, args.state, args.client))
        if args.command == "open-cron":
            return _result(tmux_control.open_cron_popup(args.config, args.project, args.client))
        if args.command == "toggle-fold":
            try:
                tmux_control.toggle_expanded_project(args.project)
            except Exception as error:
                return _result({"ok": False, "error": {"message": str(error)}})
            return 0
        return _liveness(args.config, args.project)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
