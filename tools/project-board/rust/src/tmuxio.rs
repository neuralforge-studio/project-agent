//! The tmux reads of the sidebar pane and the Python helper commands its clicks run.
//!
//! The socket is `PROJECT_BOARD_SOCKET` when set (as `tmux_control._control`), otherwise the tmux server the
//! pane runs in. The option names are those of `tmux_control.py`.
use crate::ui::Active;
use serde_json::Value;
use std::collections::HashSet;
use std::path::PathBuf;
use std::process::Command;

const EXPANDED: &str = "@project_board_expanded";
const PANE_READY: &str = "@project_board_ready";
const MARK: &str = "project-board-context";

pub struct Tmux {
    socket: Option<String>,
    pane: Option<String>,
}

impl Tmux {
    pub fn from_env() -> Self {
        Tmux {
            socket: std::env::var("PROJECT_BOARD_SOCKET").ok().filter(|v| !v.is_empty()),
            pane: std::env::var("TMUX_PANE").ok().filter(|v| !v.is_empty()),
        }
    }

    fn run(&self, args: &[&str]) -> Result<String, String> {
        let mut command = Command::new("tmux");
        if let Some(socket) = &self.socket {
            command.arg("-S").arg(socket);
        }
        let output = command.args(args).output().map_err(|e| e.to_string())?;
        if !output.status.success() {
            return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
        }
        Ok(String::from_utf8_lossy(&output.stdout).trim_end_matches('\n').to_string())
    }

    /// The folded-open projects, shared by every Board pane of the server; and with `context` also the managed
    /// window of this pane, in the same tmux process.
    pub fn refresh(&self, context: bool) -> (Result<HashSet<String>, String>, Option<Option<Active>>) {
        let mut args: Vec<String> = vec!["show-options".into(), "-sqv".into(), EXPANDED.into()];
        let want_context = context && self.pane.is_some();
        if want_context {
            let pane = self.pane.clone().unwrap_or_default();
            args.extend([";".into(), "display-message".into(), "-p".into(), "-t".into(), pane,
                         format!("{MARK}\t#{{@agent_session_project_id}}\t#{{@agent_session_target}}")]);
        }
        let refs: Vec<&str> = args.iter().map(String::as_str).collect();
        let text = match self.run(&refs) {
            Ok(text) => text,
            Err(error) => return (Err(error), None),
        };
        let mut expanded_text = String::new();
        let mut active = None;
        for line in text.lines() {
            if let Some(rest) = line.strip_prefix(MARK).and_then(|r| r.strip_prefix('\t')) {
                active = Some(parse_slot(rest));
            } else {
                expanded_text.push_str(line);
            }
        }
        (parse_expanded(&expanded_text), active)
    }

    /// `mark_ready`: tell project_board_visibility.sh that this pane handles SIGUSR1, then return whether it is shown.
    pub fn mark_ready(&self) -> bool {
        if let Some(pane) = &self.pane {
            let _ = self.run(&["set-option", "-p", "-t", pane, PANE_READY, "1"]);
        }
        self.visible()
    }

    /// `board_visible`: whether a client shows the window of this pane. Unknown is not hidden.
    pub fn visible(&self) -> bool {
        let Some(pane) = &self.pane else { return true };
        let Ok(window) = self.run(&["display-message", "-p", "-t", pane, "#{window_id}"]) else { return true };
        match self.run(&["list-clients", "-F", "#{window_id}"]) {
            Ok(clients) => clients.lines().any(|line| line == window),
            Err(_) => true,
        }
    }
}

pub fn parse_expanded(text: &str) -> Result<HashSet<String>, String> {
    if text.trim().is_empty() {
        return Ok(HashSet::new());
    }
    match serde_json::from_str::<Value>(text) {
        Ok(Value::Array(items)) if items.iter().all(Value::is_string) => {
            Ok(items.into_iter().filter_map(|v| v.as_str().map(String::from)).collect())
        }
        _ => Err("Project Board's expanded project option is invalid".into()),
    }
}

/// `pane_slot`: the values are the JSON of the window's `project_id` and `target` options; a missing or malformed
/// project id means the window is not managed.
pub fn parse_slot(text: &str) -> Option<Active> {
    let mut parts = text.split('\t');
    let project = serde_json::from_str::<Value>(parts.next()?).ok()?;
    let project_id = project.as_str().filter(|p| !p.is_empty())?.to_string();
    let slot = parts.next().and_then(|t| serde_json::from_str::<Value>(t).ok()).and_then(|v| v.as_str().map(String::from))
        .filter(|t| t == "leader" || is_seat_target(t));
    Some(Active { project_id, slot })
}

fn is_seat_target(target: &str) -> bool {
    match target.strip_prefix("seat-") {
        Some("0") => true,
        Some(n) => !n.starts_with('0') && !n.is_empty() && n.chars().all(|c| c.is_ascii_digit()),
        None => false,
    }
}

/// The `project-board` launcher next to this binary (`PROJECT_BOARD_LAUNCHER` overrides it, for tests).
pub fn launcher() -> PathBuf {
    if let Ok(path) = std::env::var("PROJECT_BOARD_LAUNCHER") {
        return PathBuf::from(path);
    }
    std::env::current_exe().ok().and_then(|exe| exe.parent().map(|dir| dir.join("project-board")))
        .unwrap_or_else(|| PathBuf::from("project-board"))
}

/// Run `project-board [--config PATH] <args>`; the error text is what the command reported.
pub fn run_helper(config: Option<&str>, args: &[String]) -> Result<String, String> {
    let mut command = Command::new(launcher());
    if let Some(config) = config {
        command.arg("--config").arg(config);
    }
    let output = command.args(args).output().map_err(|e| format!("project-board: {e}"))?;
    if output.status.success() {
        return Ok(String::from_utf8_lossy(&output.stdout).to_string());
    }
    let stderr = String::from_utf8_lossy(&output.stderr);
    let message = stderr.trim().strip_prefix("project-board: ").unwrap_or(stderr.trim());
    Err(if message.is_empty() { "tmux 동작 실패".to_string() } else { message.to_string() })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn expanded_is_a_json_list_of_strings() {
        assert_eq!(parse_expanded("").unwrap(), HashSet::new());
        assert_eq!(parse_expanded("[\"a\",\"b\"]").unwrap(), ["a", "b"].iter().map(|s| s.to_string()).collect());
        assert!(parse_expanded("{\"a\":1}").is_err());
        assert!(parse_expanded("[1]").is_err());
    }

    #[test]
    fn slot_follows_pane_slot() {
        let active = parse_slot("\"falcon2\"\t\"seat-3\"").unwrap();
        assert_eq!((active.project_id.as_str(), active.slot.as_deref()), ("falcon2", Some("seat-3")));
        assert_eq!(parse_slot("\"falcon2\"\t\"leader\"").unwrap().slot.as_deref(), Some("leader"));
        assert_eq!(parse_slot("\"falcon2\"\t\"seat-03\"").unwrap().slot, None);
        assert_eq!(parse_slot("\"falcon2\"\t\"other\"").unwrap().slot, None);
        assert_eq!(parse_slot("\"falcon2\"\t").unwrap().slot, None);
        assert!(parse_slot("\t").is_none());
        assert!(parse_slot("falcon2\t\"leader\"").is_none());
        assert!(parse_slot("\"\"\t\"leader\"").is_none());
    }
}
