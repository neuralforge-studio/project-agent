//! The project registry: where it is, and what it says. The rules and the messages are those of
//! `agent_session.config` (`registry_path`, `load_registry`), which owns them (docs/project-team/spec.md section 2).
use super::err::{error, Res, SessionError};
use super::json::parse_strict;
use super::pytext::{expanduser, resolve, strip};
use serde_json::Value;
use std::collections::HashSet;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};

pub const REGISTRY_LOCATIONS: [&str; 3] = [
    "~/.config/project-agent/project.json",
    "~/.codex/project.json",
    "~/.claude/project.json",
];

#[derive(Clone, Debug, PartialEq)]
pub enum Seat {
    Local(PathBuf),
    Remote {
        host: String,
        path: String,
        python: String,
    },
}

impl Seat {
    /// `str(seat)` of the Python seat: the local path, or the remote path.
    pub fn path(&self) -> String {
        match self {
            Seat::Local(path) => path.to_string_lossy().into_owned(),
            Seat::Remote { path, .. } => path.clone(),
        }
    }

    pub fn host(&self) -> Option<&str> {
        match self {
            Seat::Local(_) => None,
            Seat::Remote { host, .. } => Some(host),
        }
    }
}

#[derive(Clone, Debug)]
pub struct Project {
    pub base: PathBuf,
    pub id: String,
    pub provider: String,
    pub seats: Vec<Seat>,
    pub path_cr: Option<PathBuf>,
    pub path_decide: Option<PathBuf>,
}

/// `registry_path(config)`: the one registry file.
pub fn registry_path(config: Option<&Path>) -> Res<PathBuf> {
    if let Some(config) = config {
        let path = expanduser(&config.to_string_lossy());
        if !path.is_file() {
            return Err(error(
                "registry_not_found",
                "The selected project registry is unavailable.",
            ));
        }
        return Ok(resolve(&path));
    }
    let existing: Vec<PathBuf> = REGISTRY_LOCATIONS
        .iter()
        .map(|location| expanduser(location))
        .filter(|path| path.is_file())
        .collect();
    if existing.is_empty() {
        return Err(error(
            "registry_not_found",
            format!(
                "Register projects in {} or {}.",
                REGISTRY_LOCATIONS[..2].join(", "),
                REGISTRY_LOCATIONS[2]
            ),
        ));
    }
    let mut distinct = HashSet::new();
    for path in &existing {
        match std::fs::metadata(path) {
            Ok(meta) => {
                distinct.insert((meta.dev(), meta.ino()));
            }
            Err(_) => {
                return Err(error(
                    "registry_unavailable",
                    "Cannot compare the project registries.",
                ))
            }
        }
    }
    if distinct.len() > 1 {
        return Err(error(
            "registry_ambiguous",
            "Use --config when the standard registry paths are separate files.",
        ));
    }
    Ok(resolve(&existing[0]))
}

fn invalid(message: impl Into<String>) -> SessionError {
    error("registry_invalid", message)
}

/// `config._text`: a nonblank string without NUL or line breaks.
fn text(value: &Value) -> Option<&str> {
    let text = value.as_str()?;
    if strip(text).is_empty() || text.chars().any(|c| matches!(c, '\0' | '\n' | '\r')) {
        None
    } else {
        Some(text)
    }
}

/// `config._path`: absolute, `~/`, or relative to the base.
fn item_path(value: &str, base: &Path) -> PathBuf {
    let path = expanduser(value);
    resolve(&if path.is_absolute() {
        path
    } else {
        base.join(path)
    })
}

/// `str(PurePosixPath(path))` of an absolute path without `..`.
fn posix_normal(path: &str) -> String {
    let lead = if path.starts_with("//") && !path.starts_with("///") {
        "//"
    } else {
        "/"
    };
    let parts: Vec<&str> = path
        .split('/')
        .filter(|part| !part.is_empty() && *part != ".")
        .collect();
    format!("{}{}", lead, parts.join("/"))
}

fn safe_host(host: &str) -> bool {
    let bytes = host.as_bytes();
    !bytes.is_empty()
        && bytes[0].is_ascii_alphanumeric()
        && bytes
            .iter()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'.' | b'@' | b'-'))
}

fn has_control(text: &str) -> bool {
    text.chars().any(|c| (c as u32) < 32 || c as u32 == 127)
}

fn seat(value: &Value, base: &Path, provider: &str) -> Res<Seat> {
    if let Some(path) = text(value) {
        return Ok(Seat::Local(item_path(path, base)));
    }
    let object = value.as_object().filter(|object| {
        provider == "codex"
            && object.contains_key("host")
            && object.contains_key("path")
            && object
                .keys()
                .all(|key| matches!(key.as_str(), "host" | "path" | "python"))
    });
    let Some(object) = object else {
        return Err(invalid(
            "Seats must be local paths or Codex SSH seat objects.",
        ));
    };
    let unsafe_seat =
        || invalid("SSH seats require a safe host, absolute path and Python executable.");
    let host = object["host"]
        .as_str()
        .filter(|host| safe_host(host))
        .ok_or_else(unsafe_seat)?;
    let path = text(&object["path"])
        .filter(|path| !has_control(path))
        .ok_or_else(unsafe_seat)?;
    if !path.starts_with('/') || path.split('/').any(|part| part == "..") {
        return Err(unsafe_seat());
    }
    let python_value = object
        .get("python")
        .cloned()
        .unwrap_or_else(|| Value::String("python3".into()));
    let python = text(&python_value)
        .filter(|python| !python.starts_with('-') && !has_control(python))
        .ok_or_else(unsafe_seat)?;
    Ok(Seat::Remote {
        host: host.to_string(),
        path: posix_normal(path),
        python: python.to_string(),
    })
}

const RESERVED_ARGS: [&str; 9] = [
    "--remote",
    "--cd",
    "--session-id",
    "--settings",
    "--append-system-prompt-file",
    "-n",
    "--name",
    "--resume",
    "--continue",
];

fn check_launch(value: &Value) -> Res<()> {
    let bad = |message: String| Err(invalid(format!("launch: {message}")));
    let object = match value.as_object() {
        Some(object)
            if !object.is_empty()
                && object
                    .keys()
                    .all(|k| matches!(k.as_str(), "args" | "leader_args" | "worker_args")) =>
        {
            object
        }
        _ => return bad("use an object with only args, leader_args and worker_args.".into()),
    };
    for key in ["args", "leader_args", "worker_args"] {
        let Some(args) = object.get(key) else {
            continue;
        };
        let Some(list) = args
            .as_array()
            .filter(|list| list.iter().all(|arg| text(arg).is_some()))
        else {
            return bad(format!("{key} must be nonempty strings."));
        };
        if list
            .iter()
            .any(|arg| RESERVED_ARGS.contains(&arg.as_str().unwrap().split('=').next().unwrap()))
        {
            return bad(format!(
                "{key} must not set the arguments that the common runtime owns."
            ));
        }
    }
    Ok(())
}

/// `load_registry(path)`: the validated projects, in registry order.
pub fn load_registry(path: &Path) -> Res<Vec<Project>> {
    let unreadable = || invalid("Cannot read a valid project registry.");
    let bytes = std::fs::read(path).map_err(|_| unreadable())?;
    let content = std::str::from_utf8(&bytes).map_err(|_| unreadable())?;
    let raw = parse_strict(content).ok_or_else(unreadable)?;
    let Some(entries) = raw.as_object() else {
        return Err(invalid(
            "The project registry must be an object of base entries.",
        ));
    };
    let mut projects: Vec<Project> = Vec::new();
    let mut names: HashSet<String> = HashSet::new();
    let mut roots: HashSet<(Option<String>, String)> = HashSet::new();
    let mut item_roots: Vec<PathBuf> = Vec::new();
    for (base_key, entry) in entries {
        if text(&Value::String(base_key.clone())).is_none()
            || !(Path::new(base_key).is_absolute() || base_key.starts_with("~/"))
        {
            return Err(invalid(
                "Each base key must be an absolute path or start with ~/.",
            ));
        }
        let allowed = |key: &str| {
            matches!(
                key,
                "project" | "provider" | "seats" | "path_cr" | "path_decide" | "launch"
            )
        };
        let Some(entry) = entry.as_object().filter(|entry| {
            ["project", "provider", "seats"]
                .iter()
                .all(|key| entry.contains_key(*key))
                && entry.keys().all(|key| allowed(key))
        }) else {
            return Err(invalid(
                "Each project entry must contain project, provider, and seats, and may add only path_cr, path_decide and launch.",
            ));
        };
        let name = match text(&entry["project"]) {
            Some(name) if !names.contains(name) => name.to_string(),
            _ => return Err(invalid("Project names must be nonempty and unique.")),
        };
        let provider = match entry["provider"].as_str() {
            Some(provider @ ("claude" | "codex")) => provider.to_string(),
            _ => return Err(invalid("The provider must be claude or codex.")),
        };
        let Some(seat_values) = entry["seats"].as_array() else {
            return Err(invalid(
                "Seats must be an array of paths or SSH seat objects.",
            ));
        };
        let base = resolve(&expanduser(base_key));
        let seats = seat_values
            .iter()
            .map(|value| seat(value, &base, &provider))
            .collect::<Res<Vec<Seat>>>()?;
        let identities = std::iter::once((None, base.to_string_lossy().into_owned())).chain(
            seats.iter().map(|seat| match seat {
                Seat::Remote { host, path, .. } => (Some(host.clone()), path.clone()),
                Seat::Local(path) => (None, path.to_string_lossy().into_owned()),
            }),
        );
        for identity in identities {
            if !roots.insert(identity) {
                return Err(error(
                    "project_ambiguous",
                    "A base or seat path is registered more than once.",
                ));
            }
        }
        let mut items: [Option<PathBuf>; 2] = [None, None];
        for (slot, key) in ["path_cr", "path_decide"].iter().enumerate() {
            let Some(value) = entry.get(*key) else {
                continue;
            };
            let Some(value) = text(value) else {
                return Err(invalid(format!("{key} must be a nonempty path.")));
            };
            let path = item_path(value, &base);
            if item_roots
                .iter()
                .any(|other| path.starts_with(other) || other.starts_with(&path))
            {
                return Err(invalid("Item paths must not be equal or nested."));
            }
            item_roots.push(path.clone());
            items[slot] = Some(path);
        }
        if let Some(launch) = entry.get("launch") {
            check_launch(launch)?;
        }
        names.insert(name.clone());
        let [path_cr, path_decide] = items;
        projects.push(Project {
            base,
            id: name,
            provider,
            seats,
            path_cr,
            path_decide,
        });
    }
    Ok(projects)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn load(json: &str) -> Res<Vec<Project>> {
        let dir = std::env::temp_dir().join(format!(
            "registry-test-{}-{:p}",
            std::process::id(),
            json.as_ptr()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let file = dir.join("project.json");
        std::fs::write(&file, json).unwrap();
        let result = load_registry(&file);
        std::fs::remove_dir_all(&dir).unwrap();
        result
    }

    fn message(json: &str) -> String {
        load(json).unwrap_err().message
    }

    #[test]
    fn messages_equal_the_python_registry() {
        // Messages of agent_session.config.load_registry, one input each.
        assert_eq!(message("{"), "Cannot read a valid project registry.");
        assert_eq!(
            message(r#"{"/a":{"project":"x","project":"y"}}"#),
            "Cannot read a valid project registry."
        );
        assert_eq!(
            message("[]"),
            "The project registry must be an object of base entries."
        );
        assert_eq!(
            message(r#"{"rel":{}}"#),
            "Each base key must be an absolute path or start with ~/."
        );
        assert!(message(r#"{"/a":{"project":"x"}}"#)
            .starts_with("Each project entry must contain project, provider, and seats"));
        assert_eq!(
            message(r#"{"/a":{"project":"x","provider":"gemini","seats":[]}}"#),
            "The provider must be claude or codex."
        );
        assert_eq!(
            message(r#"{"/a":{"project":" ","provider":"claude","seats":[]}}"#),
            "Project names must be nonempty and unique."
        );
        assert_eq!(
            message(r#"{"/a":{"project":"x","provider":"claude","seats":"s"}}"#),
            "Seats must be an array of paths or SSH seat objects."
        );
        assert_eq!(
            message(
                r#"{"/a":{"project":"x","provider":"claude","seats":[{"host":"h","path":"/p"}]}}"#
            ),
            "Seats must be local paths or Codex SSH seat objects."
        );
        assert_eq!(
            message(
                r#"{"/a":{"project":"x","provider":"codex","seats":[{"host":"h","path":"rel"}]}}"#
            ),
            "SSH seats require a safe host, absolute path and Python executable."
        );
        assert_eq!(
            message(r#"{"/a":{"project":"x","provider":"claude","seats":["/a"]}}"#),
            "A base or seat path is registered more than once."
        );
        assert_eq!(
            message(
                r#"{"/a":{"project":"x","provider":"claude","seats":[],"path_cr":"/c","path_decide":"/c/d"}}"#
            ),
            "Item paths must not be equal or nested."
        );
        assert_eq!(
            message(
                r#"{"/a":{"project":"x","provider":"claude","seats":[],"launch":{"args":["--cd"]}}}"#
            ),
            "launch: args must not set the arguments that the common runtime owns."
        );
        assert_eq!(
            message(r#"{"/a":{"project":"x","provider":"claude","seats":[],"launch":{}}}"#),
            "launch: use an object with only args, leader_args and worker_args."
        );
    }

    #[test]
    fn a_valid_entry_resolves_seats_and_item_roots() {
        let projects = load(
            r#"{"/tmp/zz-reg/main":{"project":"p","provider":"codex","seats":["../s0",{"host":"h1","path":"/r//x/./y"}],"path_cr":"./cr/"}}"#,
        )
        .unwrap();
        let project = &projects[0];
        assert_eq!(
            project.seats[0],
            Seat::Local(PathBuf::from("/tmp/zz-reg/s0"))
        );
        assert_eq!(
            project.seats[1],
            Seat::Remote {
                host: "h1".into(),
                path: "/r/x/y".into(),
                python: "python3".into()
            }
        );
        assert_eq!(project.path_cr, Some(PathBuf::from("/tmp/zz-reg/main/cr")));
        assert_eq!(project.path_decide, None);
    }
}
