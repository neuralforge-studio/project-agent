//! Reading a tmux server the way `agent_session.tmux` does (`Tmux._observe`, `ServerView`): the sessions, windows
//! and panes of the whole server in one tmux process and the options of the current runs in one more, whatever
//! the number of projects and seats. Only reads; nothing here writes to the server.
use super::err::{error, Res, SessionError};
use super::exec::{self, RunError};
use super::process;
use super::pytext::{expanduser, resolve};
use regex::Regex;
use serde_json::{Map, Value};
use std::collections::{BTreeSet, HashMap};
use std::os::unix::fs::MetadataExt;
use std::process::Command;
use std::sync::{Mutex, OnceLock};
use std::time::Duration;

pub type Meta = Map<String, Value>;

const PREFIX: &str = "@agent_session_";
const TMUX_LIMIT: Duration = Duration::from_secs(10);
const IDENTITY: [&str; 11] = [
    "base",
    "target",
    "job_id",
    "run_id",
    "project_id",
    "window_id",
    "pane_id",
    "server_pid",
    "server_started",
    "server_birth",
    "socket_path",
];
/// `tmux._RUN_VALUES` and `tmux._WAITING_KEYS`: the option names a run is known to have. A guess that the listing
/// checks, so a name it lacks costs one more tmux process once and is asked for from then on.
const KNOWN_KEYS: [&str; 37] = [
    "cli_pid",
    "cli_birth",
    "process_group",
    "background_pids",
    "last_background_clear",
    "hook_observations",
    "controller_pid",
    "controller_birth",
    "control_pending",
    "control_operation",
    "session_id",
    "message_to",
    "start_error",
    "launch_file",
    "provider_name",
    "resume",
    "expected_session_id",
    "handoff_file",
    "leader_request",
    "remote_seat",
    "remote_native",
    "upstream",
    "upstream_bin",
    "moved_to_background",
    "last_sent",
    "last_received",
    "watch",
    "release_pending",
    "cwd",
    "provider_launch_attempted",
    "registered",
    "ready",
    "publishing",
    "stopping",
    "placeholder_pid",
    "placeholder_birth",
    "placeholder_process_group",
];
const VALUES_MARK: &str = "agent-session-values";
const CLIENT_MARK: &str = "agent-session-client";
const ID_MARK: &str = "agent-session-server";
const SESSION_MARK: &str = "agent-session-session";
const WINDOW_MARK: &str = "agent-session-window";
const PANE_MARK: &str = "agent-session-pane";
const PANE_FIELDS: [&str; 6] = [
    "window_id",
    "pane_id",
    "pane_pid",
    "pane_dead",
    "pane_dead_status",
    "pane_dead_signal",
];

fn meta_keys() -> &'static Mutex<BTreeSet<String>> {
    static KEYS: OnceLock<Mutex<BTreeSet<String>>> = OnceLock::new();
    KEYS.get_or_init(|| {
        Mutex::new(
            IDENTITY
                .iter()
                .chain(KNOWN_KEYS.iter())
                .map(|key| key.to_string())
                .collect(),
        )
    })
}

fn re(cell: &'static OnceLock<Regex>, pattern: &str) -> &'static Regex {
    cell.get_or_init(|| Regex::new(pattern).unwrap())
}

fn safe_text(value: &str, what: &str) -> Res<()> {
    if value.is_empty() || value.contains(['\0', '\n', '\r', '\t']) {
        return Err(error(
            "tmux_input",
            format!("A nonempty {what} without control characters is required."),
        ));
    }
    Ok(())
}

fn session_name(value: &str) -> Res<()> {
    safe_text(value, "tmux session name")?;
    if value.contains([':', '.']) {
        return Err(error(
            "tmux_input",
            "Tmux session names must not contain ':' or '.'.",
        ));
    }
    Ok(())
}

/// `Tmux._is_target`: `leader` or `seat-N`.
fn is_target(target: &str) -> bool {
    static SEAT: OnceLock<Regex> = OnceLock::new();
    target == "leader" || re(&SEAT, r"^seat-(0|[1-9][0-9]*)$").is_match(target)
}

fn current_option(target: &str) -> String {
    format!("{}current_{}", PREFIX, target.replace('-', "_"))
}

/// What one `observe` asks tmux for besides the identity and the sessions.
#[derive(Clone, Copy)]
pub struct Scope {
    pub clients: bool,
    pub windows: bool,
    pub panes: bool,
}

#[derive(Clone)]
pub struct Tmux {
    socket: Option<String>,
}

impl Tmux {
    /// `tmux.control(socket)`: `socket` (default `AGENT_SESSION_SOCKET`) is a tmux socket path; none is the default server.
    pub fn control(socket: Option<String>) -> Res<Tmux> {
        Tmux::from_socket(socket.or_else(|| std::env::var("AGENT_SESSION_SOCKET").ok()))
    }

    /// `Tmux(socket_path=...)`: no fallback to the environment; an empty or missing path is the default server.
    pub fn from_socket(socket: Option<String>) -> Res<Tmux> {
        let socket = socket.filter(|s| !s.is_empty());
        let Some(socket) = socket else {
            return Ok(Tmux { socket: None });
        };
        safe_text(&socket, "socket path")?;
        let path = expanduser(&socket);
        if !path.is_absolute() {
            return Err(error("tmux_input", "A tmux socket path must be absolute."));
        }
        Ok(Tmux {
            socket: Some(resolve(&path).to_string_lossy().into_owned()),
        })
    }

    fn command(&self, arguments: &[String]) -> Command {
        let mut command = crate::tmuxprog::command();
        if let Some(socket) = &self.socket {
            command.arg("-S").arg(socket);
        }
        command.args(arguments);
        command
    }

    fn failed(error_kind: RunError) -> SessionError {
        match error_kind {
            RunError::Missing => error("tmux_unavailable", "The tmux executable is unavailable."),
            RunError::Failed => error("tmux_unknown", "Cannot confirm the tmux operation."),
        }
    }

    /// `Tmux._run`: the output without its last newlines; None when `allow_missing` and no server answers.
    fn run(&self, arguments: &[String], allow_missing: bool) -> Res<Option<String>> {
        let output = exec::run(self.command(arguments), None, TMUX_LIMIT).map_err(Self::failed)?;
        if output.status != 0 {
            let stderr = String::from_utf8_lossy(&output.stderr).into_owned();
            let absent = [
                "no server running",
                "No such file or directory",
                "can't find session",
            ]
            .iter()
            .any(|text| stderr.contains(text));
            if allow_missing && absent {
                return Ok(None);
            }
            return Err(error("tmux_command_failed", "Tmux rejected the operation."));
        }
        Ok(Some(
            String::from_utf8_lossy(&output.stdout)
                .trim_end_matches('\n')
                .to_string(),
        ))
    }

    /// One tmux process that lists the attached clients and the sessions (and, when asked, the windows).
    pub fn observe_clients(&self, windows: bool) -> Res<ServerView> {
        self.observe(
            &[],
            Scope {
                clients: true,
                windows,
                panes: false,
            },
        )
    }

    /// `switch-client -c CLIENT -t TARGET`.
    pub fn switch_client(&self, client: &str, target: &str) -> Res<()> {
        let arguments: Vec<String> = ["switch-client", "-c", client, "-t", target]
            .iter()
            .map(|s| s.to_string())
            .collect();
        self.run(&arguments, false).map(|_| ())
    }

    /// `Tmux._observe` for every session, window and pane, with the current pointers of `targets`.
    fn observe(&self, targets: &[String], scope: Scope) -> Res<ServerView> {
        let mut wanted: Vec<String> = Vec::new();
        for target in targets {
            if is_target(target) && !wanted.contains(target) {
                wanted.push(target.clone());
            }
        }
        let columns: String = wanted
            .iter()
            .map(|target| format!("\t#{{{}}}", current_option(target)))
            .collect();
        let words = |text: &[&str]| text.iter().map(|word| word.to_string()).collect::<Vec<_>>();
        let mut arguments = Vec::new();
        if scope.clients {
            arguments.extend(words(&["list-clients", "-F"]));
            arguments.push(format!("{CLIENT_MARK}\t#{{client_name}}"));
            arguments.push(";".to_string());
        }
        arguments.extend(words(&["display-message", "-p"]));
        arguments.push(format!(
            "{ID_MARK}\t#{{pid}}\t#{{start_time}}\t#{{socket_path}}"
        ));
        arguments.extend(words(&[";", "list-sessions", "-F"]));
        arguments.push(format!(
            "{SESSION_MARK}\t#{{session_id}}\t#{{{PREFIX}owner}}{columns}\t#{{session_name}}"
        ));
        if scope.windows {
            arguments.extend(words(&[";", "list-windows", "-a", "-F"]));
            arguments.push(format!("{WINDOW_MARK}\t#{{window_id}}\t#{{session_id}}"));
        }
        if scope.panes {
            arguments.extend(words(&[";", "list-panes", "-a", "-F"]));
            let fields: Vec<String> = PANE_FIELDS
                .iter()
                .map(|name| format!("#{{{name}}}"))
                .collect();
            arguments.push(format!("{PANE_MARK}\t{}", fields.join("\t")));
        }
        // A caller that asks for the clients needs a server: `list-clients` failing is an error, not an empty server.
        let raw = self.run(&arguments, !scope.clients)?;
        let mut view = ServerView {
            tmux: self.clone(),
            identity_raw: None,
            sessions: HashMap::new(),
            windows: HashMap::new(),
            window_order: Vec::new(),
            clients: Vec::new(),
            panes: HashMap::new(),
            identity: None,
            metas: HashMap::new(),
        };
        for line in raw.as_deref().unwrap_or("").split('\n') {
            let (mark, rest) = line.split_once('\t').unwrap_or((line, ""));
            match mark {
                CLIENT_MARK => view.clients.push(rest.to_string()),
                ID_MARK => view.identity_raw = Some(rest.to_string()),
                SESSION_MARK => {
                    let parts: Vec<&str> = rest.splitn(wanted.len() + 3, '\t').collect();
                    if parts.len() < 3 {
                        continue;
                    }
                    let name = parts[parts.len() - 1].to_string();
                    let pointers = wanted
                        .iter()
                        .cloned()
                        .zip(parts[2..parts.len() - 1].iter().map(|p| p.to_string()))
                        .collect();
                    view.sessions.insert(
                        name,
                        SessionRec {
                            handle: parts[0].to_string(),
                            owner: parts[1].to_string(),
                            pointers,
                        },
                    );
                }
                WINDOW_MARK => {
                    if let Some((window, session)) = rest.split_once('\t') {
                        view.window_order.push(window.to_string());
                        view.windows.insert(window.to_string(), session.to_string());
                    }
                }
                PANE_MARK => {
                    if let Some(pane) = rest.split('\t').nth(1) {
                        view.panes.insert(pane.to_string(), rest.to_string());
                    }
                }
                _ => {}
            }
        }
        Ok(view)
    }

    /// `Tmux.server_view`: two tmux processes in all.
    pub fn server_view(&self, project_ids: &[&str], targets: &[String]) -> Res<ServerView> {
        let mut view = self.observe(
            targets,
            Scope {
                clients: false,
                windows: true,
                panes: true,
            },
        )?;
        view.load(project_ids)?;
        Ok(view)
    }

    /// `Tmux._read_metas`: the run options of several windows in one tmux process. A window that is gone, or whose
    /// options are not valid, has the error that reading it gave.
    fn read_metas(&self, windows: &[String]) -> Res<HashMap<String, Res<Meta>>> {
        static GONE: OnceLock<Regex> = OnceLock::new();
        static NAME: OnceLock<Regex> = OnceLock::new();
        let mut pending: Vec<String> = Vec::new();
        for window in windows {
            safe_text(window, "window handle")?;
            if !pending.contains(window) {
                pending.push(window.clone());
            }
        }
        let invalid = || {
            error(
                "tmux_metadata_invalid",
                "The managed window has invalid runtime metadata.",
            )
        };
        let mut results: HashMap<String, Res<Meta>> = HashMap::new();
        while !pending.is_empty() {
            let keys: Vec<String> = meta_keys().lock().unwrap().iter().cloned().collect();
            let mark = format!(
                "{VALUES_MARK}\t#{{window_id}}{}",
                keys.iter()
                    .map(|key| format!("\t#{{{PREFIX}{key}}}"))
                    .collect::<String>()
            );
            let mut script = String::new();
            for window in &pending {
                script.push_str(&format!("'show-options' '-w' '-t' '{window}' ; 'display-message' '-p' '-t' '{window}' '{mark}'\n"));
            }
            let mut command = self.command(&["source-file".to_string(), "-".to_string()]);
            command.stdin(std::process::Stdio::piped());
            let output =
                exec::run(command, Some(script.as_bytes()), TMUX_LIMIT).map_err(Self::failed)?;
            let mut gone = Vec::new();
            for line in String::from_utf8_lossy(&output.stderr).lines() {
                match re(&GONE, r"(?:no such window|can't find window): (@[0-9]+)$").captures(line)
                {
                    Some(found) => gone.push(found[1].to_string()),
                    None => {
                        return Err(error("tmux_command_failed", "Tmux rejected the operation."))
                    }
                }
            }
            for window in gone {
                results.insert(
                    window,
                    Err(error("tmux_command_failed", "Tmux rejected the operation.")),
                );
            }
            let stdout = String::from_utf8_lossy(&output.stdout)
                .trim_end_matches('\n')
                .to_string();
            let mut blocks: HashMap<String, (Vec<String>, Vec<String>)> = HashMap::new();
            let mut listing: Vec<String> = Vec::new();
            for line in stdout.split('\n') {
                if let Some(rest) = line.strip_prefix(&format!("{VALUES_MARK}\t")) {
                    let fields: Vec<&str> = rest.split('\t').collect();
                    blocks.insert(
                        fields[0].to_string(),
                        (
                            std::mem::take(&mut listing),
                            fields[1..].iter().map(|f| f.to_string()).collect(),
                        ),
                    );
                } else {
                    listing.push(line.to_string());
                }
            }
            let mut again = Vec::new();
            for window in &pending {
                if results.contains_key(window) {
                    continue;
                }
                let block = blocks.get(window).or_else(|| {
                    if pending.len() == 1 && blocks.len() == 1 {
                        blocks.values().next()
                    } else {
                        None
                    }
                });
                let Some((lines, fields)) = block else {
                    results.insert(window.clone(), Err(invalid()));
                    continue;
                };
                let listed: Vec<String> = lines
                    .iter()
                    .filter(|line| line.starts_with(PREFIX))
                    .map(|line| line.split(' ').next().unwrap()[PREFIX.len()..].to_string())
                    .collect();
                if listed
                    .iter()
                    .any(|key| !re(&NAME, r"^[a-z][a-z0-9_]*$").is_match(key))
                {
                    results.insert(window.clone(), Err(invalid()));
                    continue;
                }
                if listed.is_empty() {
                    results.insert(window.clone(), Ok(Meta::new()));
                    continue;
                }
                if fields.len() != keys.len() {
                    results.insert(window.clone(), Err(invalid()));
                    continue;
                }
                let asked: HashMap<&str, &str> = keys
                    .iter()
                    .map(String::as_str)
                    .zip(fields.iter().map(String::as_str))
                    .collect();
                if listed.iter().any(|key| !asked.contains_key(key.as_str())) {
                    again.push(window.clone());
                    meta_keys().lock().unwrap().extend(listed);
                    continue;
                }
                let mut meta = Meta::new();
                let mut valid = true;
                for key in &listed {
                    match serde_json::from_str::<Value>(asked[key.as_str()]) {
                        Ok(value) => {
                            meta.insert(key.clone(), value);
                        }
                        Err(_) => valid = false,
                    }
                }
                results.insert(
                    window.clone(),
                    if valid { Ok(meta) } else { Err(invalid()) },
                );
            }
            pending = again;
        }
        Ok(results)
    }
}

struct SessionRec {
    handle: String,
    owner: String,
    pointers: HashMap<String, String>,
}

#[derive(Clone)]
struct Identity {
    server_pid: u64,
    server_started: String,
    server_birth: String,
    socket_path: String,
}

/// `pane_info` of a pane: only the facts the verdict needs.
pub struct Pane {
    pub pane_pid: Option<i64>,
    pub pane_dead: bool,
}

/// One read of a tmux server (`tmux.ServerView`); a snapshot that reads nothing again, except a window it did not know.
pub struct ServerView {
    tmux: Tmux,
    identity_raw: Option<String>,
    sessions: HashMap<String, SessionRec>,
    windows: HashMap<String, String>,
    window_order: Vec<String>,
    /// The attached clients (`list-clients`), when the read asked for them.
    pub clients: Vec<String>,
    panes: HashMap<String, String>,
    identity: Option<Res<Identity>>,
    metas: HashMap<String, Res<Meta>>,
}

fn same_json(left: &Value, right: &Value) -> bool {
    match (left.as_f64(), right.as_f64()) {
        (Some(a), Some(b)) if left.is_number() && right.is_number() => a == b,
        _ => left == right,
    }
}

fn field<'a>(meta: &'a Meta, key: &str) -> &'a Value {
    meta.get(key).unwrap_or(&Value::Null)
}

impl ServerView {
    /// `ServerView.load`: the options of every current run of these projects, in one batch.
    fn load(&mut self, project_ids: &[&str]) -> Res<()> {
        let mut wanted: Vec<String> = Vec::new();
        for (name, entry) in &self.sessions {
            if !project_ids.contains(&name.as_str()) {
                continue;
            }
            for raw in entry.pointers.values() {
                let Some(window) = pointer_window(raw) else {
                    continue;
                };
                if window_id_text(&window)
                    && !self.metas.contains_key(&window)
                    && self.windows.contains_key(&window)
                    && !wanted.contains(&window)
                {
                    wanted.push(window);
                }
            }
        }
        if !wanted.is_empty() {
            let found = self.tmux.read_metas(&wanted)?;
            self.metas.extend(found);
        }
        Ok(())
    }

    /// `ServerView.identity`: the server's pid, start time, birth and socket, checked.
    fn identity(&mut self) -> Res<Identity> {
        if self.identity.is_none() {
            self.identity = Some(identity_from(self.identity_raw.as_deref().unwrap_or("")));
        }
        self.identity.clone().unwrap()
    }

    /// `ServerView.owner`: the session's owner marker when it is this server's and this project's.
    pub fn check_owner_marker(&mut self, project_id: &str) -> Res<Meta> {
        let Some(entry) = self.sessions.get(project_id) else {
            return Err(error(
                "tmux_session_not_found",
                "The exact tmux session is unavailable.",
            ));
        };
        if entry.owner.is_empty() {
            return Err(error(
                "tmux_owner_mismatch",
                "The named tmux session is not managed by agent-session.",
            ));
        }
        let owner: Value = serde_json::from_str(&entry.owner).map_err(|_| {
            error(
                "tmux_owner_mismatch",
                "The managed tmux session has an invalid owner marker.",
            )
        })?;
        let owner = match owner {
            Value::Object(owner)
                if owner.get("project_id").and_then(Value::as_str) == Some(project_id) =>
            {
                owner
            }
            _ => {
                return Err(error(
                    "tmux_owner_mismatch",
                    "The managed tmux session belongs to another project.",
                ))
            }
        };
        let actual = self.identity()?;
        let same = same_json(field(&owner, "server_pid"), &Value::from(actual.server_pid))
            && field(&owner, "server_started") == &Value::from(actual.server_started.clone())
            && field(&owner, "server_birth") == &Value::from(actual.server_birth.clone())
            && field(&owner, "socket_path") == &Value::from(actual.socket_path.clone());
        if !same {
            return Err(error(
                "tmux_owner_mismatch",
                "The tmux session was restored or its server identity changed.",
            ));
        }
        Ok(owner)
    }

    /// The tmux handle (`$N`) of a session, by name.
    pub fn session_handle(&self, name: &str) -> Option<&str> {
        self.sessions.get(name).map(|entry| entry.handle.as_str())
    }

    /// `ServerView.windows_of`: the windows of the project's session, in tmux's order.
    pub fn windows_of(&self, project_id: &str) -> Vec<String> {
        let Some(handle) = self.session_handle(project_id) else {
            return Vec::new();
        };
        self.window_order
            .iter()
            .filter(|window| self.windows.get(*window).map(String::as_str) == Some(handle))
            .cloned()
            .collect()
    }

    /// `Tmux._read_metas` for windows of this view: one tmux process, whatever the number of windows.
    pub fn read_window_metas(&self, windows: &[String]) -> Res<HashMap<String, Res<Meta>>> {
        self.tmux.read_metas(windows)
    }

    fn meta(&mut self, window_id: &str) -> Res<Meta> {
        if !self.metas.contains_key(window_id) {
            let found = if !self.windows.contains_key(window_id) {
                Err(error("tmux_command_failed", "Tmux rejected the operation."))
            } else {
                match self.tmux.read_metas(&[window_id.to_string()]) {
                    Ok(mut found) => found.remove(window_id).unwrap_or_else(|| {
                        Err(error(
                            "tmux_metadata_invalid",
                            "The managed window has invalid runtime metadata.",
                        ))
                    }),
                    Err(e) => Err(e),
                }
            };
            self.metas.insert(window_id.to_string(), found);
        }
        self.metas[window_id].clone()
    }

    /// `ServerView.current`: the slot's current run (its window options), or None.
    pub fn current(&mut self, project_id: &str, target: &str) -> Res<Option<Meta>> {
        session_name(project_id)?;
        if !self.sessions.contains_key(project_id) {
            return Ok(None);
        }
        self.check_owner_marker(project_id)?;
        let raw = match self.sessions[project_id].pointers.get(target) {
            Some(raw) => raw.clone(),
            None => {
                let handle = self.sessions[project_id].handle.clone();
                self.tmux
                    .run(
                        &[
                            "show-options".into(),
                            "-qv".into(),
                            "-t".into(),
                            handle,
                            current_option(target),
                        ],
                        false,
                    )?
                    .unwrap_or_default()
            }
        };
        if raw.is_empty() {
            return Ok(None);
        }
        let pointer: Value = serde_json::from_str(&raw).map_err(|_| {
            error(
                "tmux_metadata_invalid",
                "The current execution pointer is invalid.",
            )
        })?;
        let incomplete = || {
            error(
                "tmux_metadata_invalid",
                "The current execution pointer is incomplete.",
            )
        };
        let pointer = pointer.as_object().ok_or_else(incomplete)?;
        let window = pointer
            .get("window_id")
            .filter(|w| process::truthy(w))
            .ok_or_else(incomplete)?;
        let window = window.as_str().ok_or_else(|| {
            error(
                "tmux_input",
                "A nonempty window handle without control characters is required.",
            )
        })?;
        let actual = self.meta(window).map_err(|e| {
            if e.code == "tmux_command_failed" {
                error(
                    "execution_evidence_missing",
                    "The current execution window is unavailable.",
                )
            } else {
                e
            }
        })?;
        if IDENTITY
            .iter()
            .any(|key| !same_json(field(&actual, key), field(pointer, key)))
        {
            return Err(error(
                "target_changed",
                "The runtime identity no longer matches the current pointer.",
            ));
        }
        if field(&actual, "target").as_str() != Some(target)
            || field(&actual, "project_id").as_str() != Some(project_id)
        {
            return Err(error(
                "target_changed",
                "The current execution points to another target.",
            ));
        }
        Ok(Some(actual))
    }

    /// `ServerView.pane_info`.
    pub fn pane_info(&self, pane_id: &str) -> Res<Pane> {
        safe_text(pane_id, "pane handle")?;
        let Some(raw) = self.panes.get(pane_id) else {
            return Err(error("tmux_command_failed", "Tmux rejected the operation."));
        };
        let parts: Vec<&str> = raw.split('\t').collect();
        let digits = |text: &str| !text.is_empty() && text.bytes().all(|b| b.is_ascii_digit());
        if parts.len() != PANE_FIELDS.len()
            || !(parts[3] == "0" || parts[3] == "1")
            || !(digits(parts[2]) || (parts[2].is_empty() && parts[3] == "1"))
        {
            return Err(error(
                "tmux_unknown",
                "The managed pane observation is incomplete.",
            ));
        }
        Ok(Pane {
            pane_pid: parts[2].parse().ok(),
            pane_dead: parts[3] == "1",
        })
    }
}

fn window_id_text(window: &str) -> bool {
    static WINDOW: OnceLock<Regex> = OnceLock::new();
    re(&WINDOW, r"^@[0-9]+$").is_match(window)
}

/// `tmux._pointer_window`: the window a current pointer text names, or None when the text is not a pointer.
fn pointer_window(raw: &str) -> Option<String> {
    let pointer: Value = serde_json::from_str(raw).ok()?;
    pointer
        .get("window_id")?
        .as_str()
        .filter(|w| !w.is_empty())
        .map(String::from)
}

/// `tmux._identity_from`: the server identity from `pid<TAB>start_time<TAB>socket_path`.
fn identity_from(raw: &str) -> Res<Identity> {
    let unknown = |message: &str| error("tmux_unknown", message);
    let parts: Vec<&str> = raw.split('\t').collect();
    let digits = |text: &str| !text.is_empty() && text.bytes().all(|b| b.is_ascii_digit());
    if parts.len() != 3 || !digits(parts[0]) || !digits(parts[1]) || parts[2].is_empty() {
        return Err(unknown("Tmux did not return a complete server identity."));
    }
    let pid: u64 = parts[0]
        .parse()
        .map_err(|_| unknown("Tmux did not return a complete server identity."))?;
    let birth = process::birth(pid as i64)?
        .ok_or_else(|| unknown("The tmux server process identity is unavailable."))?;
    let socket = resolve(std::path::Path::new(parts[2]));
    let meta = std::fs::metadata(&socket)
        .map_err(|_| unknown("The selected tmux socket is unavailable."))?;
    use std::os::unix::fs::FileTypeExt;
    // SAFETY: getuid has no preconditions.
    if !meta.file_type().is_socket() || meta.uid() != unsafe { libc::getuid() } {
        return Err(error(
            "tmux_owner_mismatch",
            "The selected tmux socket is not owned by the current user.",
        ));
    }
    Ok(Identity {
        server_pid: pid,
        server_started: parts[1].to_string(),
        server_birth: birth,
        socket_path: socket.to_string_lossy().into_owned(),
    })
}
