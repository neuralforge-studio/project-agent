"""The installed project-board command routes to the TUI and tmux controller."""
import board_testing  # noqa: F401  (adds this tool to sys.path like the other Board tests)

from project_board import cli, tmux_control, tui


def test_toggle_passes_the_registry_client_and_socket(monkeypatch):
    called = []

    def toggle(config, client, socket):
        called.append((config, client, socket))
        return {"ok": True, "data": {}, "error": None}

    monkeypatch.setattr(tmux_control, "toggle_sidebar", toggle)
    assert cli.main(["--config", "/tmp/projects.json", "toggle", "--client", "/dev/ttys1",
                     "--socket", "/tmp/tmux.sock"]) == 0
    assert called == [("/tmp/projects.json", "/dev/ttys1", "/tmp/tmux.sock")]


def test_sidebar_actions_keep_the_client_identity(monkeypatch):
    """The sidebar binary runs these commands for its clicks (BOARD-018); each reaches the same controller function
    the Textual sidebar called, with the clicking client."""
    called = []
    monkeypatch.setattr(tmux_control, "open_popup", lambda *args: called.append(("decision", args)) or {"ok": True})
    monkeypatch.setattr(tmux_control, "open_cr_popup", lambda *args: called.append(("cr", args)) or {"ok": True})
    monkeypatch.setattr(tmux_control, "switch_seat", lambda *args: called.append(("seat", args)) or {"ok": True})
    monkeypatch.setattr(tmux_control, "switch_project", lambda *args: called.append(("project", args)) or {"ok": True})
    monkeypatch.setattr(tmux_control, "toggle_expanded_project", lambda project_id: called.append(("fold", project_id)) or {"ProjectB"})
    config = ["--config", "/tmp/projects.json"]
    assert cli.main([*config, "switch-project", "--project", "Falcon2", "--client", "/dev/ttys2"]) == 0
    assert cli.main([*config, "open-decision", "--project", "Falcon2", "--client", "/dev/ttys1"]) == 0
    assert cli.main([*config, "open-cr", "--project", "Falcon2", "--state", "open", "--client", "/dev/ttys2"]) == 0
    assert cli.main([*config, "switch-seat", "--project", "Falcon2", "--seat", "0", "--client", "/dev/ttys1"]) == 0
    assert cli.main([*config, "switch-seat", "--project", "Falcon2", "--seat", "1"]) == 0
    assert cli.main([*config, "toggle-fold", "--project", "ProjectB"]) == 0
    assert called == [
        ("project", ("/tmp/projects.json", "Falcon2", "/dev/ttys2")),
        ("decision", ("/tmp/projects.json", "Falcon2", None, "/dev/ttys1")),
        ("cr", ("/tmp/projects.json", "Falcon2", "open", "/dev/ttys2")),
        ("seat", ("/tmp/projects.json", "Falcon2", 0, "/dev/ttys1")),
        ("seat", ("/tmp/projects.json", "Falcon2", 1, None)),
        ("fold", "ProjectB"),
    ]


def test_a_failed_sidebar_action_reports_its_message_and_fails(monkeypatch, capsys):
    monkeypatch.setattr(tmux_control, "switch_seat", lambda *args: {
        "ok": False, "data": None, "error": {"code": "seat_not_running", "message": "The seat has no Worker session."}})
    assert cli.main(["switch-seat", "--project", "Falcon2", "--seat", "0"]) == 1
    assert capsys.readouterr().err == "project-board: The seat has no Worker session.\n"

    def broken(project_id):
        raise ValueError("Project Board's expanded project option is invalid")

    monkeypatch.setattr(tmux_control, "toggle_expanded_project", broken)
    assert cli.main(["toggle-fold", "--project", "Falcon2"]) == 1
    assert "expanded project option is invalid" in capsys.readouterr().err


def test_the_command_without_a_name_prints_usage_instead_of_a_sidebar(capsys):
    assert cli.main([]) == 2
    assert "usage: project-board" in capsys.readouterr().err


def test_popup_commands_run_the_matching_tui(monkeypatch):
    called = []
    monkeypatch.setattr(tui, "run_popup", lambda *args: called.append(("decision", args)))
    monkeypatch.setattr(tui, "run_cr_popup", lambda *args: called.append(("cr", args)))
    assert cli.main(["--config", "/tmp/projects.json", "popup", "--project", "Falcon2",
                     "--decision", "D-1"]) == 0
    assert cli.main(["--config", "/tmp/projects.json", "cr", "--project", "Falcon2",
                     "--state", "todo"]) == 0
    assert called == [
        ("decision", ("/tmp/projects.json", "Falcon2", "D-1")),
        ("cr", ("/tmp/projects.json", "Falcon2", "todo")),
    ]
