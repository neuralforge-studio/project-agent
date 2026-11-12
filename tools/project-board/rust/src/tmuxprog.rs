//! The tmux the sidebar runs: the installer's record, read by the rule of `agent_session/tmux_program.py` (TMUX-004).
//!
//! `tools/tmux.env` of the release names the tmux executable (`PROJECT_AGENT_TMUX`) and the library directories it
//! needs (`PROJECT_AGENT_TMUX_LD_LIBRARY_PATH`). An environment variable with a value wins over the file, per name.
//! Without the file (a development checkout) the program is `tmux` in PATH. A file that names no program says that
//! the installer found no tmux of the minimum version: the program is then empty and cannot be started. The Python
//! module and `tools/tmux-launcher.sh` read the same record; `test_tmux_record.py` holds the three equal.
use std::path::PathBuf;
use std::process::Command;

const PROGRAM: &str = "PROJECT_AGENT_TMUX";
const LIBRARY: &str = "PROJECT_AGENT_TMUX_LD_LIBRARY_PATH";

/// `(program, library)` from the environment values, the record text (None: no record file) and the record's
/// rule. An empty program means "the record names no tmux".
pub fn resolve(
    env_program: Option<String>,
    env_library: Option<String>,
    record: Option<&str>,
) -> (String, String) {
    let (mut program, mut library) = (String::new(), String::new());
    for line in record.unwrap_or("").lines() {
        if let Some((name, value)) = line.split_once('=') {
            match name {
                PROGRAM => program = value.to_string(),
                LIBRARY => library = value.to_string(),
                _ => {}
            }
        }
    }
    let program = env_program.filter(|v| !v.is_empty()).unwrap_or(program);
    let library = env_library.filter(|v| !v.is_empty()).unwrap_or(library);
    if program.is_empty() && record.is_none() {
        return ("tmux".to_string(), library);
    }
    (program, library)
}

/// `tools/tmux.env` of the release this binary is in: the binary is `tools/project-board/bin/<name>`.
fn record_path() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    Some(exe.parent()?.parent()?.parent()?.join("tmux.env"))
}

pub fn settings() -> (String, String) {
    let record = record_path().and_then(|path| std::fs::read(path).ok())
        .map(|bytes| String::from_utf8_lossy(&bytes).into_owned());
    resolve(std::env::var(PROGRAM).ok(), std::env::var(LIBRARY).ok(), record.as_deref())
}

/// A `Command` for the recorded tmux, with its library directories in front of `LD_LIBRARY_PATH`.
pub fn command() -> Command {
    let (program, library) = settings();
    let mut command = Command::new(program);
    if !library.is_empty() {
        let value = match std::env::var("LD_LIBRARY_PATH") {
            Ok(old) if !old.is_empty() => format!("{library}:{old}"),
            _ => library,
        };
        command.env("LD_LIBRARY_PATH", value);
    }
    command
}

/// `project-board-sidebar tmux-program`: the choice as one JSON line, `{"program": ..., "library": ...}`. The
/// equivalence test of the three readers compares it with the Python module and the shell launcher.
pub fn print() -> i32 {
    let (program, library) = settings();
    println!("{}", serde_json::json!({"program": program, "library": library}));
    0
}

#[cfg(test)]
mod tests {
    use super::*;

    fn some(text: &str) -> Option<String> {
        Some(text.to_string())
    }

    #[test]
    fn without_a_record_the_program_is_tmux_in_path() {
        assert_eq!(resolve(None, None, None), ("tmux".to_string(), String::new()));
    }

    #[test]
    fn the_record_names_the_program_and_the_library() {
        let record = "PROJECT_AGENT_TMUX=/a b/tmux\nPROJECT_AGENT_TMUX_LD_LIBRARY_PATH=/l1:/l2\nOTHER=x\n";
        assert_eq!(resolve(None, None, Some(record)), ("/a b/tmux".to_string(), "/l1:/l2".to_string()));
    }

    #[test]
    fn the_last_line_of_a_name_wins_and_the_value_is_kept_as_written() {
        let record = "PROJECT_AGENT_TMUX=/first\nPROJECT_AGENT_TMUX=/$HOME/`x`/tmux";
        assert_eq!(resolve(None, None, Some(record)).0, "/$HOME/`x`/tmux");
    }

    #[test]
    fn an_environment_value_wins_per_name_and_an_empty_one_is_no_value() {
        let record = "PROJECT_AGENT_TMUX=/rec/tmux\nPROJECT_AGENT_TMUX_LD_LIBRARY_PATH=/rec/lib\n";
        assert_eq!(resolve(some("/env/tmux"), None, Some(record)), ("/env/tmux".to_string(), "/rec/lib".to_string()));
        assert_eq!(resolve(some(""), some("/env/lib"), Some(record)), ("/rec/tmux".to_string(), "/env/lib".to_string()));
    }

    #[test]
    fn a_record_without_a_program_names_no_tmux() {
        assert_eq!(resolve(None, None, Some("PROJECT_AGENT_TMUX=\n")).0, "");
        assert_eq!(resolve(some("/env/tmux"), None, Some("PROJECT_AGENT_TMUX=\n")).0, "/env/tmux");
    }
}
