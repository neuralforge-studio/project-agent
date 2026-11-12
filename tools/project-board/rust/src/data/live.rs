//! Run liveness (docs/project-team/spec.md section 5, `agent_session.api.project_liveness` and
//! `project_pending_releases`): from tmux and /proc, whether each bound slot's current run is alive, stopped or
//! unknown, and which seats hold a pending release. The tmux server is read once for every project.
//!
//! A run on a remote seat needs SSH to be judged. That judgment stays in Python: this reads the same facts and
//! the same owner check, then asks `project-board liveness --project ID` (see `delegate`).
use super::err::Res;
use super::exec;
use super::process;
use super::registry::{Project, Seat};
use super::state::{self, Session, State};
use super::tmux::{Meta, ServerView, Tmux};
use crate::model::{Liveness, SlotLive};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

const DELEGATE_LIMIT: Duration = Duration::from_secs(15);

pub struct Judged {
    pub liveness: Liveness,
    /// Project -> JOB IDs whose stopped run waits for release.
    pub releases: HashMap<String, HashSet<String>>,
}

fn slot_name(index: usize) -> String {
    format!("seat-{index}")
}

fn all_slots(count: usize) -> Vec<String> {
    std::iter::once("leader".to_string())
        .chain((0..count).map(slot_name))
        .collect()
}

/// `tmux.check_owner`: the run is this base's run of the slot and the conversation the state names.
fn owned(project: &Project, slot: &str, session: &Session, meta: &Meta) -> bool {
    let field = |key: &str| meta.get(key).unwrap_or(&Value::Null);
    let Some(base) = field("base").as_str() else {
        return false;
    };
    if super::pytext::resolve(Path::new(base)) != project.base {
        return false;
    }
    if field("target").as_str() != Some(slot)
        || field("session_id").as_str() != Some(session.session_id.as_str())
    {
        return false;
    }
    let Some(number) = slot
        .strip_prefix("seat-")
        .and_then(|n| n.parse::<usize>().ok())
    else {
        return true;
    };
    let expected = match project.seats.get(number) {
        Some(Seat::Remote { host, path, python }) => {
            serde_json::json!({"host": host, "path": path, "python": python})
        }
        _ => Value::Null,
    };
    if field("remote_seat") != &expected {
        return false;
    }
    if !expected.is_null() {
        if let Some(endpoint) = &session.endpoint {
            if field("endpoint").as_str() != Some(endpoint.as_str()) {
                return false;
            }
        }
    }
    true
}

/// The `project-board` launcher that judges remote seats: `PROJECT_BOARD_LAUNCHER`, else the one beside this binary.
fn launcher() -> PathBuf {
    if let Some(path) = std::env::var_os("PROJECT_BOARD_LAUNCHER") {
        return PathBuf::from(path);
    }
    std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(|dir| dir.join("project-board")))
        .unwrap_or_else(|| PathBuf::from("project-board"))
}

/// `project-board [--config PATH] liveness --project ID`: slot -> {session_id, state}; None when it fails or is too slow.
fn delegate(config: Option<&Path>, project_id: &str) -> Option<Value> {
    let mut command = Command::new(launcher());
    if let Some(config) = config {
        command.arg("--config").arg(config);
    }
    command.args(["liveness", "--project", project_id]);
    let output = exec::run(command, None, DELEGATE_LIMIT).ok()?;
    if output.status != 0 {
        return None;
    }
    serde_json::from_slice::<Value>(&output.stdout)
        .ok()
        .filter(Value::is_object)
}

/// The verdict of one local slot: `alive`, `stopped`, or None when a fact cannot be read.
fn local_verdict(view: &ServerView, meta: &Meta) -> Res<&'static str> {
    let pane_id = meta.get("pane_id").and_then(Value::as_str).unwrap_or("");
    let pane = view.pane_info(pane_id)?;
    Ok(
        if process::cli_alive(meta, pane.pane_pid)? && !pane.pane_dead {
            "alive"
        } else {
            "stopped"
        },
    )
}

struct Slot {
    key: String,
    slot: String,
    session: Session,
}

fn slots_of(state: &State) -> Vec<Slot> {
    let mut slots = Vec::new();
    if let Some(leader) = &state.leader {
        slots.push(Slot {
            key: "leader".into(),
            slot: "leader".into(),
            session: leader.clone(),
        });
    }
    for (index, row) in state.seats.iter().enumerate() {
        if let Some(session) = &row.session {
            slots.push(Slot {
                key: index.to_string(),
                slot: slot_name(index),
                session: session.clone(),
            });
        }
    }
    slots
}

/// `model.liveness()` for `projects`, and the release holds it refreshes.
pub fn judge(projects: &[Project], config: Option<&Path>) -> Judged {
    let tmux = Tmux::control(None);
    let seat_count = projects
        .iter()
        .map(|project| project.seats.len())
        .max()
        .unwrap_or(0);
    let ids: Vec<&str> = projects.iter().map(|project| project.id.as_str()).collect();
    let mut shared: Option<ServerView> = tmux
        .as_ref()
        .ok()
        .and_then(|tmux| tmux.server_view(&ids, &all_slots(seat_count)).ok());
    let mut liveness = Liveness::new();
    let mut releases: HashMap<String, HashSet<String>> = HashMap::new();
    let mut remote: Vec<(usize, Vec<(String, String)>)> = Vec::new();
    for (index, project) in projects.iter().enumerate() {
        let state = state::read_state_value(project, None)
            .0
            .and_then(|value| state::validate(project, &value));
        let mut verdicts: BTreeMap<String, SlotLive> = BTreeMap::new();
        let mut held: HashSet<String> = HashSet::new();
        if let Ok(state) = state {
            // Without a view of the whole server each project reads the server for itself.
            let mut own: Option<ServerView> = None;
            if shared.is_none() {
                own = tmux.as_ref().ok().and_then(|tmux| {
                    tmux.server_view(&[project.id.as_str()], &all_slots(project.seats.len()))
                        .ok()
                });
            }
            let mut view = shared.as_mut().or(own.as_mut());
            let mut pending_remote = Vec::new();
            for slot in slots_of(&state) {
                let mut verdict = "unknown";
                if let Some(view) = view.as_deref_mut() {
                    if let Ok(Some(meta)) = view.current(&project.id, &slot.slot) {
                        if meta.get("session_id").and_then(Value::as_str)
                            == Some(slot.session.session_id.as_str())
                        {
                            if meta.get("remote_seat").is_some_and(process::truthy) {
                                if owned(project, &slot.slot, &slot.session, &meta) {
                                    pending_remote
                                        .push((slot.key.clone(), slot.session.session_id.clone()));
                                }
                            } else if let Ok(found) = local_verdict(view, &meta) {
                                verdict = found;
                            }
                        }
                    }
                }
                verdicts.insert(
                    slot.key,
                    SlotLive {
                        session_id: slot.session.session_id,
                        state: verdict.to_string(),
                    },
                );
            }
            if let Some(view) = view {
                for (seat, row) in state.seats.iter().enumerate() {
                    let Some(job) = &row.job_id else { continue };
                    if let Ok(Some(meta)) = view.current(&project.id, &slot_name(seat)) {
                        if meta.get("job_id").and_then(Value::as_str) == Some(job.as_str())
                            && meta.get("release_pending").is_some_and(process::truthy)
                        {
                            held.insert(job.clone());
                        }
                    }
                }
            }
            if !pending_remote.is_empty() {
                remote.push((index, pending_remote));
            }
        }
        liveness.insert(project.id.clone(), verdicts);
        releases.insert(project.id.clone(), held);
    }
    // The remote seats of every project are judged at the same time: SSH is slow and the projects are independent.
    let answers = super::par::par_map(&remote, remote.len().max(1), |(index, _)| {
        delegate(config, &projects[*index].id)
    });
    for ((index, wanted), answer) in remote.iter().zip(answers) {
        let Some(answer) = answer else { continue };
        let verdicts = liveness.get_mut(&projects[*index].id).unwrap();
        for (key, session_id) in wanted {
            let entry = &answer[key.as_str()];
            let state = entry
                .get("state")
                .and_then(Value::as_str)
                .filter(|s| matches!(*s, "alive" | "stopped" | "unknown"));
            if let (Some(state), true) = (
                state,
                entry.get("session_id").and_then(Value::as_str) == Some(session_id.as_str()),
            ) {
                verdicts.get_mut(key).unwrap().state = state.to_string();
            }
        }
    }
    Judged { liveness, releases }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    /// A launcher script that prints `output`, exits with `status` and records its arguments.
    fn fake_launcher(name: &str, output: &str, status: i32) -> (PathBuf, PathBuf) {
        let directory =
            std::env::temp_dir().join(format!("live-test-{}-{}", std::process::id(), name));
        let _ = std::fs::remove_dir_all(&directory);
        std::fs::create_dir_all(&directory).unwrap();
        let (script, record) = (directory.join("project-board"), directory.join("arguments"));
        std::fs::write(
            &script,
            format!(
                "#!/bin/sh\necho \"$@\" > '{}'\nprintf '%s' '{}'\nexit {}\n",
                record.display(),
                output,
                status
            ),
        )
        .unwrap();
        std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o755)).unwrap();
        (script, record)
    }

    #[test]
    fn the_launcher_is_called_with_the_config_and_its_answer_is_parsed() {
        // This is the only test that sets PROJECT_BOARD_LAUNCHER; the others never read it.
        let (script, record) =
            fake_launcher("ok", r#"{"1": {"session_id": "S", "state": "alive"}}"#, 0);
        std::env::set_var("PROJECT_BOARD_LAUNCHER", &script);
        let answer = delegate(Some(Path::new("/x/project.json")), "p0").unwrap();
        assert_eq!(answer["1"]["state"], "alive");
        assert_eq!(
            std::fs::read_to_string(&record).unwrap().trim(),
            "--config /x/project.json liveness --project p0"
        );
        let answer = delegate(None, "p0").unwrap();
        assert_eq!(answer["1"]["session_id"], "S");
        assert_eq!(
            std::fs::read_to_string(&record).unwrap().trim(),
            "liveness --project p0"
        );
        let (script, _) = fake_launcher("fail", "{}", 1);
        std::env::set_var("PROJECT_BOARD_LAUNCHER", &script);
        assert!(delegate(None, "p0").is_none());
        let (script, _) = fake_launcher("garbage", "not json", 0);
        std::env::set_var("PROJECT_BOARD_LAUNCHER", &script);
        assert!(delegate(None, "p0").is_none());
        std::env::set_var("PROJECT_BOARD_LAUNCHER", "/nonexistent/project-board");
        assert!(delegate(None, "p0").is_none());
        std::env::remove_var("PROJECT_BOARD_LAUNCHER");
    }
}
