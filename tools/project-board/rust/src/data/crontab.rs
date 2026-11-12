//! The user's crontab (`crontab -l`), read once for every project (BOARD-027). The rules of reading it are those of
//! `agent_session.cron.Crontab.read` and `split`; `crate::cron` holds the section and schedule rules.
use super::exec::{self, RunError};
use crate::cron;
use crate::model::{CronEntry, CronView};
use regex::Regex;
use std::process::Command;
use std::time::Duration;

/// `cron.COMMAND_TIMEOUT`: how long the `crontab` process may take.
const LIMIT: Duration = Duration::from_secs(30);

/// The crontab text. No crontab yet is an empty text; any other failure is the reason, never an empty text.
pub fn read() -> Result<String, String> {
    let mut command = Command::new("crontab");
    command.arg("-l");
    let output = match exec::run(command, None, LIMIT) {
        Ok(output) => output,
        Err(RunError::Missing) => return Err("crontab 명령을 쓸 수 없습니다".into()),
        Err(RunError::Failed) => return Err("crontab 명령을 실행하지 못했습니다".into()),
    };
    let stdout = String::from_utf8_lossy(&output.stdout);
    if output.status == 0 {
        return Ok(stdout.into_owned());
    }
    let stderr = String::from_utf8_lossy(&output.stderr);
    let none = Regex::new(r"(?i)no crontab for").unwrap();
    if none.is_match(&stderr) && stdout.trim().is_empty() {
        return Ok(String::new());
    }
    let reason: String = stderr.trim().chars().take(300).collect();
    Err(format!("crontab을 읽을 수 없습니다: {reason}"))
}

/// Every project's jobs from the crontab `text`; a project whose section is broken is the only one with an error.
pub fn view_of(text: &str, ids: &[&str]) -> CronView {
    ids.iter()
        .map(|id| {
            let entry = match cron::project_schedules(text, id) {
                Ok(schedules) => CronEntry { schedules, error: None },
                Err(message) => CronEntry { schedules: Vec::new(), error: Some(message) },
            };
            (id.to_string(), entry)
        })
        .collect()
}

/// `view_of` for a crontab that was read, or an error entry for every project when it could not be.
pub fn view(read: Result<String, String>, ids: &[&str]) -> CronView {
    match read {
        Ok(text) => view_of(&text, ids),
        Err(message) => ids
            .iter()
            .map(|id| (id.to_string(), CronEntry { schedules: Vec::new(), error: Some(message.clone()) }))
            .collect(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_crontab_that_cannot_be_read_is_an_error_for_every_project_and_a_broken_section_for_one() {
        let failed = view(Err("x".into()), &["a", "b"]);
        assert!(failed.values().all(|entry| entry.error.as_deref() == Some("x") && entry.schedules.is_empty()));
        let text = "# >>> project-agent: a >>>\n# job c: d\n0 1 * * * run\n# <<< project-agent: a <<<\n# >>> project-agent: b >>>\n";
        let view = view_of(text, &["a", "b", "c"]);
        assert_eq!(view["a"], CronEntry { schedules: vec!["0 1 * * *".into()], error: None });
        assert_eq!(view["b"].error.as_deref(), Some(cron::BROKEN));
        assert_eq!(view["c"], CronEntry::default());
    }
}
