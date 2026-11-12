//! Click actions that only move a tmux client: to a project's session or to a Worker's pane.
//! The rules live in `data::jump`; this is the entry the sidebar and the command line call.
use crate::data::jump;

/// Switch the clicking client to a registered project's tmux session (`tmux_control.switch_project`).
pub fn switch_project(
    config: Option<&str>,
    project_id: &str,
    client: Option<&str>,
) -> Result<(), String> {
    jump::project(config, project_id, client)
}

/// Switch the clicking client to the pane of a seat's Worker (`tmux_control.switch_seat`).
pub fn switch_seat(
    config: Option<&str>,
    project_id: &str,
    seat: usize,
    client: Option<&str>,
) -> Result<(), String> {
    jump::seat(config, project_id, seat, client)
}

const USAGE: &str = "usage: project-board-sidebar switch-project|switch-seat --config C --project P [--seat N] [--client X]";

/// `switch-project` or `switch-seat` with its options (`args[0]` is the command). A failure prints
/// `project-board: <message>` on stderr and exits 1; wrong options exit 2.
pub fn run(args: &[String]) -> i32 {
    let Some(command) = args.first().map(String::as_str) else {
        eprintln!("{USAGE}");
        return 2;
    };
    let (mut config, mut project, mut seat, mut client) = (None, None, None, None);
    let mut rest = args[1..].iter();
    while let Some(option) = rest.next() {
        let Some(value) = rest.next() else {
            eprintln!("{USAGE}");
            return 2;
        };
        match option.as_str() {
            "--config" => config = Some(value.as_str()),
            "--project" => project = Some(value.as_str()),
            "--seat" => match value.parse::<usize>() {
                Ok(number) => seat = Some(number),
                Err(_) => {
                    eprintln!("{USAGE}");
                    return 2;
                }
            },
            "--client" => client = Some(value.as_str()),
            _ => {
                eprintln!("{USAGE}");
                return 2;
            }
        }
    }
    let result = match (command, project, seat) {
        ("switch-project", Some(project), None) => switch_project(config, project, client),
        ("switch-seat", Some(project), Some(seat)) => switch_seat(config, project, seat, client),
        _ => {
            eprintln!("{USAGE}");
            return 2;
        }
    };
    match result {
        Ok(()) => 0,
        Err(message) => {
            eprintln!("project-board: {message}");
            1
        }
    }
}
