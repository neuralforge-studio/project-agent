//! Switching the clicking tmux client to a project's session or a Worker's pane, without Python
//! (`project_board.tmux_control.switch_project` and `switch_seat`, which own the rules and the messages).
//! Three tmux processes at most: the clients and sessions in one, the options of the project's windows in one
//! (a seat only), and the `switch-client`.
use super::err::SessionError;
use super::registry::{load_registry, registry_path, Project};
use super::state;
use super::tmux::Tmux;
use serde_json::Value;
use std::path::Path;

/// The tmux the Board controls: `PROJECT_BOARD_SOCKET`, else the default server (`tmux_control._control`).
fn control() -> Result<Tmux, SessionError> {
    Tmux::from_socket(std::env::var("PROJECT_BOARD_SOCKET").ok()).map_err(|e| e)
}

/// `tmux_control._client` on the attached clients: the selected one, or the only one.
fn pick_client(attached: &[String], selected: Option<&str>) -> Result<String, String> {
    match selected {
        None if attached.len() == 1 => Ok(attached[0].clone()),
        None => Err("Select a tmux client when none or several are attached".to_string()),
        Some(client) if attached.iter().any(|name| name == client) => Ok(client.to_string()),
        Some(_) => Err("The selected tmux client is not attached".to_string()),
    }
}

/// `model.find_project(config, project_id)`.
fn find_project(config: Option<&str>, project_id: &str) -> Result<Option<Project>, SessionError> {
    let path = registry_path(config.map(Path::new))?;
    Ok(load_registry(&path)?
        .into_iter()
        .find(|project| project.id == project_id))
}

/// `Tmux.find_by_session`: the pane of the one window of this project base that holds the session.
fn find_pane(
    view: &mut super::tmux::ServerView,
    project: &Project,
    session_id: &str,
) -> Result<Option<String>, SessionError> {
    if view.session_handle(&project.id).is_none() {
        return Ok(None);
    }
    let owner = view.check_owner_marker(&project.id)?;
    let base = project.base.to_string_lossy().into_owned();
    if owner.get("base").and_then(Value::as_str) != Some(base.as_str()) {
        return Err(super::err::error(
            "tmux_owner_mismatch",
            "The tmux session belongs to another project base.",
        ));
    }
    let windows = view.windows_of(&project.id);
    let mut metas = view.read_window_metas(&windows)?;
    let mut found = Vec::new();
    for window in &windows {
        let Some(meta) = metas.remove(window) else {
            continue;
        };
        let meta = meta?;
        if meta.get("base").and_then(Value::as_str) == Some(base.as_str())
            && meta.get("session_id").and_then(Value::as_str) == Some(session_id)
        {
            found.push(meta);
        }
    }
    if found.len() > 1 {
        return Err(super::err::error(
            "tmux_owner_mismatch",
            "The provider session matches more than one managed window.",
        ));
    }
    Ok(match found.pop() {
        Some(meta) => Some(
            meta.get("pane_id")
                .and_then(Value::as_str)
                .ok_or_else(|| super::err::error("key_error", "'pane_id'"))?
                .to_string(),
        ),
        None => None,
    })
}

/// `switch_project`: the message of the failure, as the Python `error["message"]`.
pub fn project(config: Option<&str>, project_id: &str, client: Option<&str>) -> Result<(), String> {
    let tmux = control().map_err(|e| e.message)?;
    let view = tmux.observe_clients(false).map_err(|e| e.message)?;
    let selected = pick_client(&view.clients, client)?;
    if find_project(config, project_id)
        .map_err(|e| e.message)?
        .is_none()
    {
        return Err("The project is not registered.".to_string());
    }
    let Some(session) = view.session_handle(project_id) else {
        return Err("The project tmux session is unavailable.".to_string());
    };
    tmux.switch_client(&selected, session)
        .map_err(|e| e.message)
}

/// `switch_seat`: the message of the failure, as the Python `error["message"]`.
pub fn seat(
    config: Option<&str>,
    project_id: &str,
    seat: usize,
    client: Option<&str>,
) -> Result<(), String> {
    let tmux = control().map_err(|e| e.message)?;
    let mut view = tmux.observe_clients(true).map_err(|e| e.message)?;
    let selected = pick_client(&view.clients, client)?;
    let Some(project) = find_project(config, project_id).map_err(|e| e.message)? else {
        return Err("The project is not registered.".to_string());
    };
    if seat >= project.seats.len() {
        return Err("The seat does not exist in this project.".to_string());
    }
    let value = state::read_state_value(&project, None)
        .0
        .map_err(|e| e.message)?;
    let state = state::validate(&project, &value).map_err(|e| e.message)?;
    let Some(session) = state.seats[seat].session.as_ref() else {
        return Err("The seat has no Worker session.".to_string());
    };
    let Some(pane) = find_pane(&mut view, &project, &session.session_id).map_err(|e| e.message)?
    else {
        return Err("The Worker window is unavailable.".to_string());
    };
    tmux.switch_client(&selected, &pane).map_err(|e| e.message)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_client_is_the_selected_one_or_the_only_one() {
        let one = vec!["/dev/pts/1".to_string()];
        let two = vec!["/dev/pts/1".to_string(), "/dev/pts/2".to_string()];
        assert_eq!(pick_client(&one, None), Ok("/dev/pts/1".into()));
        assert_eq!(
            pick_client(&two, Some("/dev/pts/2")),
            Ok("/dev/pts/2".into())
        );
        assert_eq!(
            pick_client(&two, None).unwrap_err(),
            "Select a tmux client when none or several are attached"
        );
        assert_eq!(
            pick_client(&[], None).unwrap_err(),
            "Select a tmux client when none or several are attached"
        );
        assert_eq!(
            pick_client(&one, Some("")).unwrap_err(),
            "The selected tmux client is not attached"
        );
    }
}
