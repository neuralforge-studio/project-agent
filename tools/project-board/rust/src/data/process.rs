//! Process facts from /proc (Linux), as `agent_session.process` reads them: identity by creation time, so a
//! reused PID is not taken for the run's process.
use super::err::{error, Res};
use serde_json::{Map, Value};

pub struct Row {
    pub state: String,
    pub birth: String,
}

fn unknown(message: &str) -> super::err::SessionError {
    error("process_unknown", message)
}

fn positive(pid: i64) -> Res<u64> {
    if pid > 0 {
        Ok(pid as u64)
    } else {
        Err(unknown("A positive process ID is required."))
    }
}

/// `process._linux_row`: None when the process does not exist.
fn linux_row(pid: u64) -> Res<Option<Row>> {
    let bytes = match std::fs::read(format!("/proc/{pid}/stat")) {
        Ok(bytes) => bytes,
        Err(e)
            if e.kind() == std::io::ErrorKind::NotFound
                || e.raw_os_error() == Some(libc::ESRCH) =>
        {
            return Ok(None)
        }
        Err(_) => return Err(unknown("Cannot observe the process identity.")),
    };
    let data =
        String::from_utf8(bytes).map_err(|_| unknown("Cannot observe the process identity."))?;
    let incomplete = || unknown("The process identity record is incomplete.");
    let tail = data.rsplit_once(')').ok_or_else(incomplete)?.1;
    let fields: Vec<&str> = tail.split_whitespace().collect();
    if fields.len() < 20 || fields[1].parse::<i64>().is_err() || fields[2].parse::<i64>().is_err() {
        return Err(incomplete());
    }
    Ok(Some(Row {
        state: fields[0].to_string(),
        birth: fields[19].to_string(),
    }))
}

/// `process.birth`: a creation fingerprint, or None if the PID is absent.
pub fn birth(pid: i64) -> Res<Option<String>> {
    let Some(row) = linux_row(positive(pid)?)? else {
        return Ok(None);
    };
    let boot = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")
        .map_err(|_| unknown("Cannot identify the current boot."))?;
    let boot = super::pytext::strip(&boot);
    if boot.is_empty() {
        return Err(unknown("The current boot identity is unavailable."));
    }
    Ok(Some(format!("linux:{}:{}", boot, row.birth)))
}

/// `process.alive`: a zombie or a PID with a different creation fingerprint is not alive.
pub fn alive(pid: i64, expected_birth: Option<&str>, birth_given: bool) -> Res<bool> {
    let Some(row) = linux_row(positive(pid)?)? else {
        return Ok(false);
    };
    if row.state.starts_with('Z') || row.state.starts_with('X') {
        return Ok(false);
    }
    if !birth_given {
        return Ok(true);
    }
    Ok(match expected_birth {
        Some(expected) => birth(pid)?.as_deref() == Some(expected),
        None => false, // a recorded value that is not text never equals a fingerprint
    })
}

/// Python truthiness of a JSON value.
pub fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_some_and(|f| f != 0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

fn as_pid(value: &Value) -> Res<i64> {
    match value {
        Value::Number(n) => n.as_i64().or_else(|| n.as_f64().map(|f| f as i64)),
        Value::String(s) => super::pytext::strip(s).parse::<i64>().ok(),
        Value::Bool(b) => Some(*b as i64),
        _ => None,
    }
    .ok_or_else(|| unknown("A process ID is required."))
}

/// `process.cli_alive(meta, pane)`: the run's CLI process (or the pane process before it marked one) still runs.
pub fn cli_alive(meta: &Map<String, Value>, pane_pid: Option<i64>) -> Res<bool> {
    let marked = meta.get("cli_pid").filter(|value| truthy(value));
    let pid = match (marked, pane_pid) {
        (Some(value), _) => as_pid(value)?,
        (None, Some(pid)) if pid != 0 => pid,
        _ => return Ok(false),
    };
    let recorded = meta.get("cli_birth").filter(|value| !value.is_null());
    alive(pid, recorded.and_then(Value::as_str), recorded.is_some())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn this_process_is_alive_with_its_own_birth_and_a_missing_one_is_not() {
        let me = std::process::id() as i64;
        let born = birth(me).unwrap().unwrap();
        assert!(born.starts_with("linux:"));
        assert!(alive(me, Some(&born), true).unwrap());
        assert!(!alive(me, Some("linux:other:1"), true).unwrap());
        assert!(alive(me, None, false).unwrap());
        assert!(!alive(4_000_000_000, None, false).unwrap());
        assert!(alive(0, None, false).is_err());
    }

    #[test]
    fn cli_alive_prefers_the_marked_pid_and_falls_back_to_the_pane_pid() {
        let me = std::process::id() as i64;
        let mut meta = Map::new();
        assert!(!cli_alive(&meta, None).unwrap());
        assert!(cli_alive(&meta, Some(me)).unwrap());
        meta.insert("cli_pid".into(), Value::from(4_000_000_000i64));
        assert!(!cli_alive(&meta, Some(me)).unwrap());
        meta.insert("cli_pid".into(), Value::from(me));
        meta.insert("cli_birth".into(), Value::from(birth(me).unwrap().unwrap()));
        assert!(cli_alive(&meta, None).unwrap());
    }
}
