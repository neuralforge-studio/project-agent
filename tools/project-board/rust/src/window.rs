//! Telling a Board window (the CR list or the decisions) that is already open what to show.
//!
//! Starting a window costs seconds on a loaded host, so a click on a window of the same kind sends it one line of JSON
//! and starts nothing. The contract is docs/project-board-tui-plan.md, "열려 있는 창에 새 내용 알리기" (BOARD-025);
//! `tmux_control._popup` and `window_link.py` are the Python client and server, and test_window_protocol.py holds the
//! window to the same line. Everything this client cannot do (no window, another kind, a window that is still starting,
//! a window that does not answer) is left to `project-board`, which starts the window under the Board lock.
use crate::tmuxio::Tmux;
use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::fs::MetadataExt;
use std::os::unix::net::UnixStream;
use std::time::Duration;

const TIMEOUT: Duration = Duration::from_secs(2);
const MAX_LINE: usize = 4096;

#[derive(Debug, PartialEq)]
pub enum Outcome {
    /// The window showed the item.
    Done,
    /// The window cannot change what it shows (an answer is being sent); the message is for the user.
    Busy(String),
    /// Start the window the ordinary way.
    Fallback,
}

/// One pane row of `list-panes`: id, `@project_board_window`, kind, release and link options.
#[derive(Debug, PartialEq)]
pub struct Row {
    pub pane: String,
    pub is_window: bool,
    pub kind: String,
    /// The release of the process that started the window ('' when it was not in an installed release, or an older
    /// Board that did not say).
    pub release: String,
    pub link: String,
}

/// The window pane of the window `client` is in, from the tab-separated output of one tmux process:
/// `C\t<client>\t<window>` rows and `P\t<window>\t<pane>\t<marker>\t<kind>\t<release>\t<link>` rows.
pub fn window_pane(text: &str, client: &str) -> Option<Row> {
    let mut window: Option<&str> = None;
    for line in text.lines() {
        let fields: Vec<&str> = line.split('\t').collect();
        if let ["C", name, id] = fields[..] {
            if name == client {
                window = Some(id);
            }
        }
    }
    let window = window?;
    for line in text.lines() {
        let fields: Vec<&str> = line.splitn(7, '\t').collect();
        if let ["P", id, pane, marker, kind, release, link] = fields[..] {
            if id == window && marker == "1" {
                return Some(Row { pane: pane.to_string(), is_window: true, kind: kind.to_string(), release: release.to_string(), link: link.to_string() });
            }
        }
    }
    None
}

/// Send one request line to the window that listens on `path`; Err when nothing usable listens there.
pub fn send(path: &str, request: &Value) -> Result<Value, String> {
    let info = std::fs::symlink_metadata(path).map_err(|e| e.to_string())?;
    let is_socket = std::os::unix::fs::FileTypeExt::is_socket(&info.file_type());
    if !is_socket || info.uid() != unsafe { libc::getuid() } {
        return Err("the Board window socket is not private".into());
    }
    let mut stream = UnixStream::connect(path).map_err(|e| e.to_string())?;
    stream.set_read_timeout(Some(TIMEOUT)).map_err(|e| e.to_string())?;
    stream.set_write_timeout(Some(TIMEOUT)).map_err(|e| e.to_string())?;
    stream.write_all(format!("{request}\n").as_bytes()).map_err(|e| e.to_string())?;
    let mut line = String::new();
    BufReader::new(stream.take(MAX_LINE as u64)).read_line(&mut line).map_err(|e| e.to_string())?;
    serde_json::from_str::<Value>(line.trim_end()).map_err(|e| format!("the Board window gave no reply: {e}"))
}

/// What to do with the reply of a window.
pub fn judge(reply: &Value) -> Outcome {
    if reply.get("ok") == Some(&Value::Bool(true)) {
        return Outcome::Done;
    }
    if reply.get("code").and_then(Value::as_str) == Some("busy") {
        let message = reply.get("message").and_then(Value::as_str).filter(|m| !m.is_empty()).unwrap_or("The Board window is busy.");
        return Outcome::Busy(message.to_string());
    }
    Outcome::Fallback
}

/// The open window of the same kind in `client`'s window is told `request`; its title is set when it took it.
pub fn tell(kind: &str, request: &Value, client: &str, title: &str) -> Outcome {
    let tmux = Tmux::from_env();
    let listing = tmux.run(&[
        "list-clients", "-F", "C\t#{client_name}\t#{window_id}", ";",
        "list-panes", "-a", "-F", "P\t#{window_id}\t#{pane_id}\t#{@project_board_window}\t#{@project_board_window_kind}\t#{@project_board_window_release}\t#{@project_board_window_link}",
    ]);
    let Ok(listing) = listing else { return Outcome::Fallback };
    let Some(row) = window_pane(&listing, client) else { return Outcome::Fallback };
    // a window started by another release is not reused: `project-board` starts it again from this one (BOARD-028)
    let release = crate::release::own().map(|own| own.name).unwrap_or_default();
    if row.kind != kind || row.release != release || row.link.is_empty() {
        return Outcome::Fallback;
    }
    let mut request = request.clone();
    request["client"] = json!(client);
    let Ok(reply) = send(&row.link, &request) else { return Outcome::Fallback };
    let outcome = judge(&reply);
    if outcome == Outcome::Done {
        let _ = tmux.run(&["select-pane", "-t", &row.pane, "-T", title]);
    }
    outcome
}

/// `project-board-sidebar tell --kind K --client C --title T --request JSON`: `tell` for the equivalence test, which gives
/// the Python client (`tmux_control._reuse`) and this one the same window and compares what each does. Prints
/// `{"outcome": "done" | "busy" | "fallback", "message": ...}` (`fallback` is what makes the sidebar run `project-board`).
pub fn run(args: &[String]) -> i32 {
    let value = |name: &str| args.iter().position(|a| a == name).and_then(|i| args.get(i + 1)).cloned();
    let (Some(kind), Some(client), Some(title), Some(request)) = (value("--kind"), value("--client"), value("--title"), value("--request")) else {
        eprintln!("usage: project-board-sidebar tell --kind K --client C --title T --request JSON");
        return 2;
    };
    let Ok(request) = serde_json::from_str::<Value>(&request) else {
        eprintln!("tell: --request is not JSON");
        return 2;
    };
    let answer = match tell(&kind, &request, &client, &title) {
        Outcome::Done => json!({"outcome": "done", "message": null}),
        Outcome::Busy(message) => json!({"outcome": "busy", "message": message}),
        Outcome::Fallback => json!({"outcome": "fallback", "message": null}),
    };
    println!("{answer}");
    0
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::net::UnixListener;

    const LISTING: &str = "C\t/dev/pts/3\t@1\nC\t/dev/pts/4\t@2\nP\t@1\t%5\t\t\t\t\nP\t@1\t%6\t1\tcr\t0.11.0-aaaaaaaaaaaa\t/tmp/x.win\nP\t@2\t%7\t1\tdecision\t\t\n";

    #[test]
    fn the_window_pane_is_the_marked_pane_of_the_clients_window() {
        let row = window_pane(LISTING, "/dev/pts/3").unwrap();
        assert_eq!((row.pane.as_str(), row.kind.as_str(), row.release.as_str(), row.link.as_str()), ("%6", "cr", "0.11.0-aaaaaaaaaaaa", "/tmp/x.win"));
        let starting = window_pane(LISTING, "/dev/pts/4").unwrap();
        assert_eq!((starting.pane.as_str(), starting.kind.as_str(), starting.release.as_str(), starting.link.as_str()), ("%7", "decision", "", ""));
        assert_eq!(window_pane(LISTING, "/dev/pts/9"), None);
        assert_eq!(window_pane("C\tc\t@1\nP\t@1\t%1\t\t\t\t\n", "c"), None);
    }

    #[test]
    fn replies_are_judged_as_the_plan_says() {
        assert_eq!(judge(&json!({"ok": true})), Outcome::Done);
        assert_eq!(judge(&json!({"ok": false, "code": "busy", "message": "sending"})), Outcome::Busy("sending".into()));
        assert_eq!(judge(&json!({"ok": false, "code": "busy"})), Outcome::Busy("The Board window is busy.".into()));
        assert_eq!(judge(&json!({"ok": false, "code": "invalid", "message": "x"})), Outcome::Fallback);
        assert_eq!(judge(&json!({"ok": false, "code": "closing"})), Outcome::Fallback);
        assert_eq!(judge(&json!([])), Outcome::Fallback);
    }

    #[test]
    fn a_request_is_one_json_line_and_the_reply_one_json_line() {
        let dir = std::env::temp_dir().join(format!("pbw-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("a.win");
        let _ = std::fs::remove_file(&path);
        let listener = UnixListener::bind(&path).unwrap();
        let server = std::thread::spawn(move || {
            let (stream, _) = listener.accept().unwrap();
            let mut line = String::new();
            BufReader::new(&stream).read_line(&mut line).unwrap();
            (&stream).write_all(b"{\"ok\": true}\n").unwrap();
            line
        });
        let reply = send(path.to_str().unwrap(), &json!({"kind": "cr", "project": "p", "state": "todo"})).unwrap();
        assert_eq!(reply, json!({"ok": true}));
        let line = server.join().unwrap();
        assert!(line.ends_with('\n') && line.matches('\n').count() == 1);
        assert_eq!(serde_json::from_str::<Value>(&line).unwrap()["state"], "todo");
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn nothing_listening_or_not_a_socket_is_an_error() {
        let dir = std::env::temp_dir().join(format!("pbw2-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        assert!(send(dir.join("none.win").to_str().unwrap(), &json!({})).is_err());
        let file = dir.join("file.win");
        std::fs::write(&file, "x").unwrap();
        assert!(send(file.to_str().unwrap(), &json!({})).is_err());
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
