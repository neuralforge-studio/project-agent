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


def test_sidebar_click_callbacks_keep_the_client_identity(monkeypatch):
    called = []
    monkeypatch.setattr(tmux_control, "open_popup", lambda *args: called.append(("decision", args)))
    monkeypatch.setattr(tmux_control, "open_cr_popup", lambda *args: called.append(("cr", args)))
    monkeypatch.setattr(tmux_control, "switch_seat", lambda *args: called.append(("seat", args)))
    monkeypatch.setattr(tmux_control, "switch_project", lambda *args: called.append(("project", args)))

    def sidebar(config, *, on_project, on_decision, on_cr, on_seat):
        assert config == "/tmp/projects.json"
        on_project("Falcon2", client="/dev/ttys2")
        on_decision("Falcon2", "D-1", client="/dev/ttys1")
        on_cr("Falcon2", "open", client="/dev/ttys2")
        on_seat("Falcon2", 0, client="/dev/ttys1")

    monkeypatch.setattr(tui, "run_sidebar", sidebar)
    assert cli.main(["--config", "/tmp/projects.json", "sidebar"]) == 0
    assert called == [
        ("project", ("/tmp/projects.json", "Falcon2", "/dev/ttys2")),
        ("decision", ("/tmp/projects.json", "Falcon2", "D-1", "/dev/ttys1")),
        ("cr", ("/tmp/projects.json", "Falcon2", "open", "/dev/ttys2")),
        ("seat", ("/tmp/projects.json", "Falcon2", 0, "/dev/ttys1")),
    ]


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
