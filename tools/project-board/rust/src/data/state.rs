//! state.json of a project: read, validate against the registry, and the connection facts the Board shows.
//! The rules and messages are those of `agent_session.state` (`StateStore.read`, `validate_state`).
use super::err::{error, Res, SessionError};
use super::json::parse_strict;
use super::pytext::strip;
use super::registry::Project;
use super::stamp::{mtime_ns, now_ns, settled, sig_of, Sig};
use regex::Regex;
use serde_json::Value;
use std::path::Path;
use std::sync::OnceLock;

/// A published conversation of a slot.
#[derive(Clone, Debug, PartialEq)]
pub struct Session {
    pub session_id: String,
    pub connected_at: Option<String>,
    pub reviewing: Option<String>,
    pub endpoint: Option<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct SeatState {
    pub job_id: Option<String>,
    pub session: Option<Session>,
}

#[derive(Clone, Debug)]
pub struct State {
    pub leader: Option<Session>,
    /// One row per registered seat.
    pub seats: Vec<SeatState>,
}

fn invalid(message: &str) -> SessionError {
    error("state_invalid", message)
}

/// `config.require_base`: the registered base directory exists.
pub fn require_base(project: &Project) -> Res<()> {
    if project.base.is_dir() {
        Ok(())
    } else {
        Err(error(
            "base_unavailable",
            "The registered project base is unavailable.",
        ))
    }
}

fn is_symlink(path: &Path) -> bool {
    std::fs::symlink_metadata(path)
        .map(|meta| meta.file_type().is_symlink())
        .unwrap_or(false)
}

/// A read of the state file kept under the file's signature.
pub type Kept = (Sig, Value);

/// The JSON of the project's state file (`StateStore.read` up to the parse). `old` is the earlier read of this file:
/// it is reused while the file has the signature it was read under. The second value is what to keep for the next call.
pub fn read_state_value(project: &Project, old: Option<&Kept>) -> (Res<Value>, Option<Kept>) {
    if let Err(e) = require_base(project) {
        return (Err(e), None);
    }
    let path = project.base.join("agent").join("state.json");
    if is_symlink(&path) || is_symlink(path.parent().unwrap()) {
        return (
            Err(invalid(
                "The per-project state path must not be a symbolic link.",
            )),
            None,
        );
    }
    let unreadable = || invalid("Cannot read a valid project state. Preserve the file.");
    let meta = std::fs::metadata(&path);
    let signature = meta.as_ref().ok().map(sig_of);
    if let (Some(signature), Some((kept, value))) = (signature, old) {
        if *kept == signature {
            return (Ok(value.clone()), Some((signature, value.clone())));
        }
    }
    let bytes = match std::fs::read(&path) {
        Ok(bytes) => bytes,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            return (
                Err(error(
                    "state_not_found",
                    "The project state has not been initialized.",
                )),
                None,
            )
        }
        Err(_) => return (Err(unreadable()), None),
    };
    let Some(text) = std::str::from_utf8(&bytes).ok() else {
        return (Err(unreadable()), None);
    };
    match parse_strict(text) {
        None => (Err(unreadable()), None),
        Some(value) => {
            let keep = match (&meta, signature) {
                (Ok(meta), Some(signature)) if settled(mtime_ns(meta), now_ns()) => {
                    Some((signature, value.clone()))
                }
                _ => None,
            };
            (Ok(value), keep)
        }
    }
}

fn connected_at_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$").unwrap()
    })
}

/// Days of a month (Gregorian).
fn month_days(year: i64, month: i64) -> i64 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        _ if year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) => 29,
        _ => 28,
    }
}

/// `_connected_at`: the format and what `time.strptime("%Y-%m-%dT%H:%M:%SZ")` accepts (seconds up to 61).
fn valid_connected_at(text: &str) -> bool {
    if !connected_at_re().is_match(text) {
        return false;
    }
    let number = |from: usize, to: usize| text[from..to].parse::<i64>().unwrap();
    let (year, month, day) = (number(0, 4), number(5, 7), number(8, 10));
    year >= 1
        && (1..=12).contains(&month)
        && day >= 1
        && day <= month_days(year, month)
        && number(11, 13) <= 23
        && number(14, 16) <= 59
        && number(17, 19) <= 61
}

fn nonblank(value: &Value) -> Option<&str> {
    value.as_str().filter(|text| !strip(text).is_empty())
}

/// `_session`: a connection has exact transport fields; connected_at and the Leader's reviewing are optional.
fn session(value: &Value, provider: &str, leader: bool) -> Option<Option<Session>> {
    if value.is_null() {
        return Some(None);
    }
    let object = value.as_object()?;
    let transport = if provider == "claude" {
        "message_to"
    } else {
        "endpoint"
    };
    let optional: &[&str] = if leader {
        &["connected_at", "reviewing"]
    } else {
        &["connected_at"]
    };
    if !object.contains_key("session_id") || !object.contains_key(transport) {
        return None;
    }
    if !object
        .keys()
        .all(|key| key == "session_id" || key == transport || optional.contains(&key.as_str()))
    {
        return None;
    }
    let session_id = nonblank(&object["session_id"])?.to_string();
    nonblank(&object[transport])?;
    if let Some(connected) = object.get("connected_at") {
        if !valid_connected_at(connected.as_str()?) {
            return None;
        }
    }
    let reviewing = match object.get("reviewing") {
        None | Some(Value::Null) => None,
        Some(value) => {
            let text = nonblank(value)?;
            if text == "leader" {
                return None;
            }
            Some(text.to_string())
        }
    };
    Some(Some(Session {
        session_id,
        connected_at: object
            .get("connected_at")
            .and_then(|v| v.as_str())
            .map(String::from),
        reviewing,
        endpoint: object
            .get("endpoint")
            .and_then(|v| v.as_str())
            .map(String::from),
    }))
}

fn unassigned(row: &Value) -> bool {
    row.as_object().is_some_and(|row| {
        row.len() == 3
            && ["job_id", "git_hash", "session"]
                .iter()
                .all(|key| row.get(*key).is_some_and(Value::is_null))
    })
}

fn git_hash_ok(text: &str) -> bool {
    (text.len() == 40 || text.len() == 64)
        && text
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// `validate_state(project, value)`: the state fitted to the registered seat count.
pub fn validate(project: &Project, value: &Value) -> Res<State> {
    let root = invalid("The state root or leader connection does not match the registry.");
    let object = value
        .as_object()
        .filter(|object| object.contains_key("leader"))
        .ok_or_else(|| root.clone())?;
    let count = object.len() - 1;
    if !(0..count).all(|n| object.contains_key(&n.to_string())) {
        return Err(invalid(
            "The state seat keys must be consecutive numbers from 0.",
        ));
    }
    let wanted = project.seats.len();
    for n in wanted..count {
        if !unassigned(&object[&n.to_string()]) {
            return Err(invalid(
                "A seat removed from the registry is still assigned.",
            ));
        }
    }
    let empty = serde_json::json!({"job_id": null, "git_hash": null, "session": null});
    let rows: Vec<&Value> = (0..wanted)
        .map(|n| {
            if n < count {
                &object[&n.to_string()]
            } else {
                &empty
            }
        })
        .collect();
    let leader = session(&object["leader"], &project.provider, true).ok_or(root)?;
    let mut jobs: Vec<&str> = Vec::new();
    let mut seats = Vec::new();
    for row in rows {
        let bad = || invalid("A seat record has invalid fields.");
        let row = row
            .as_object()
            .filter(|row| {
                row.len() == 3
                    && ["job_id", "git_hash", "session"]
                        .iter()
                        .all(|key| row.contains_key(*key))
            })
            .ok_or_else(bad)?;
        let job = match &row["job_id"] {
            Value::Null => None,
            value => match nonblank(value) {
                Some(job) if job != "leader" => Some(job),
                _ => return Err(invalid("The seat JOB ID is invalid.")),
            },
        };
        let git = match &row["git_hash"] {
            Value::Null => None,
            Value::String(text) if git_hash_ok(text) => Some(text.as_str()),
            _ => return Err(invalid("The seat Git hash must be a full commit hash.")),
        };
        let connection = session(&row["session"], &project.provider, false)
            .ok_or_else(|| invalid("The seat provider connection is invalid."))?;
        if job.is_none() && (git.is_some() || connection.is_some()) {
            return Err(invalid(
                "An unassigned seat must not retain a Git hash or connection.",
            ));
        }
        if let Some(job) = job {
            if jobs.contains(&job) {
                return Err(invalid("A JOB is assigned to more than one seat."));
            }
            jobs.push(job);
        }
        seats.push(SeatState {
            job_id: job.map(String::from),
            session: connection,
        });
    }
    if let Some(reviewing) = leader
        .as_ref()
        .and_then(|leader| leader.reviewing.as_deref())
    {
        if !jobs.contains(&reviewing) {
            return Err(invalid("The Leader reviews a JOB that no seat holds."));
        }
    }
    Ok(State { leader, seats })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::data::registry::Seat;
    use serde_json::json;
    use std::path::PathBuf;

    fn project(seats: usize, provider: &str) -> Project {
        Project {
            base: PathBuf::from("/b"),
            id: "p".into(),
            provider: provider.into(),
            seats: (0..seats)
                .map(|n| Seat::Local(PathBuf::from(format!("/s{n}"))))
                .collect(),
            path_cr: None,
            path_decide: None,
        }
    }

    fn leader() -> Value {
        json!({"session_id": "L", "endpoint": "e", "connected_at": "2026-11-04T09:00:00Z", "reviewing": null})
    }

    fn row(job: &str) -> Value {
        json!({"job_id": job, "git_hash": null, "session": {"session_id": "W", "endpoint": "e"}})
    }

    fn rejected(value: Value, provider: &str) -> String {
        validate(&project(1, provider), &value).unwrap_err().message
    }

    #[test]
    fn a_valid_state_is_fitted_to_the_registered_seats() {
        let state = validate(
            &project(2, "codex"),
            &json!({"leader": leader(), "0": row("T-001")}),
        )
        .unwrap();
        assert_eq!(state.seats.len(), 2);
        assert_eq!(state.seats[0].job_id.as_deref(), Some("T-001"));
        assert_eq!(
            state.seats[1],
            SeatState {
                job_id: None,
                session: None
            }
        );
        assert_eq!(
            state.leader.unwrap().connected_at.as_deref(),
            Some("2026-11-04T09:00:00Z")
        );
    }

    #[test]
    fn rejections_carry_the_python_messages() {
        let root = "The state root or leader connection does not match the registry.";
        assert_eq!(rejected(json!([]), "codex"), root);
        assert_eq!(rejected(json!({"0": row("T-001")}), "codex"), root);
        assert_eq!(
            rejected(json!({"leader": null, "1": row("T-001")}), "codex"),
            "The state seat keys must be consecutive numbers from 0."
        );
        assert_eq!(
            rejected(
                json!({"leader": null, "0": row("T-001"), "1": row("T-002")}),
                "codex"
            ),
            "A seat removed from the registry is still assigned."
        );
        assert_eq!(
            rejected(
                json!({"leader": {"session_id": "L"}, "0": row("T-001")}),
                "codex"
            ),
            root
        );
        assert_eq!(
            rejected(
                json!({"leader": leader(), "0": {"job_id": "T-001"}}),
                "codex"
            ),
            "A seat record has invalid fields."
        );
        assert_eq!(
            rejected(
                json!({"leader": leader(), "0": {"job_id": "leader", "git_hash": null, "session": null}}),
                "codex"
            ),
            "The seat JOB ID is invalid."
        );
        assert_eq!(
            rejected(
                json!({"leader": leader(), "0": {"job_id": "T-1", "git_hash": "abc", "session": null}}),
                "codex"
            ),
            "The seat Git hash must be a full commit hash."
        );
        assert_eq!(
            rejected(
                json!({"leader": leader(), "0": {"job_id": "T-1", "git_hash": null, "session": {"session_id": "W"}}}),
                "codex"
            ),
            "The seat provider connection is invalid."
        );
        assert_eq!(
            rejected(
                json!({"leader": leader(), "0": {"job_id": null, "git_hash": null, "session": {"session_id": "W", "endpoint": "e"}}}),
                "codex"
            ),
            "An unassigned seat must not retain a Git hash or connection."
        );
        let reviewing = json!({"session_id": "L", "endpoint": "e", "reviewing": "T-9"});
        assert_eq!(
            rejected(json!({"leader": reviewing, "0": row("T-001")}), "codex"),
            "The Leader reviews a JOB that no seat holds."
        );
        // A claude project names its transport message_to, not endpoint.
        assert_eq!(
            rejected(json!({"leader": leader(), "0": row("T-001")}), "claude"),
            root
        );
    }

    #[test]
    fn connected_at_follows_strptime() {
        assert!(valid_connected_at("2026-02-28T23:59:61Z"));
        assert!(!valid_connected_at("2026-02-29T00:00:00Z"));
        assert!(valid_connected_at("2024-02-29T00:00:00Z"));
        assert!(!valid_connected_at("2026-13-01T00:00:00Z"));
        assert!(!valid_connected_at("2026-01-01T24:00:00Z"));
        assert!(!valid_connected_at("0000-01-01T00:00:00Z"));
        assert!(!valid_connected_at("2026-01-01 00:00:00Z"));
    }
}
