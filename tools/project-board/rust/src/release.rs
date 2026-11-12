//! Which release this sidebar belongs to, and whether the installed `current` has moved on (BOARD-028).
//!
//! The identity of a release is the name of its directory, `releases/<version>-<hash>` (the installer makes the name
//! from `VERSION` and the commit; docs/project-team/install-contract.md, "release의 식별"). A process knows its own
//! release from where its file is (`<lib>/releases/<name>/tools/project-board/bin/<binary>`), and the installed one
//! is the directory `<lib>/current` points at. A binary that is not in such a place (a development checkout) belongs
//! to no release and never switches. `project_board/release.py` reads a Python process's place by the same rule;
//! `test_rust_release.py` holds the two equal.
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};

pub const SIDEBAR: &str = "project-board-sidebar";
/// Set (to `1`) by the process that replaces itself with the sidebar of another release: the click socket it leaves
/// behind is the predecessor's, not another sidebar's, so the successor takes it over.
pub const SUCCESSOR: &str = "PROJECT_BOARD_SUCCESSOR";

/// The place of a binary inside an installed release.
#[derive(Clone, Debug, PartialEq)]
pub struct Own {
    /// `~/.local/lib/project-agent` (the directory with `releases/` and `current`).
    pub lib: PathBuf,
    /// The release directory's name.
    pub name: String,
}

/// What a sidebar of release `own` should do now.
#[derive(Clone, Debug, PartialEq)]
pub enum Verdict {
    /// `current` is this release.
    Same,
    /// `current` is another release whose sidebar binary can be run.
    Switch { name: String, binary: PathBuf },
    /// This code stays and says why it cannot be replaced.
    Restart(String),
}

/// The release of the binary at `exe` (a resolved path), or None outside an installed release.
pub fn locate(exe: &Path) -> Option<Own> {
    let mut parents = exe.ancestors().skip(1);
    let names = ["bin", "project-board", "tools"];
    for expected in names {
        let directory = parents.next()?;
        if directory.file_name()?.to_str()? != expected {
            return None;
        }
    }
    let release = parents.next()?;
    let releases = release.parent()?;
    if releases.file_name()?.to_str()? != "releases" {
        return None;
    }
    let lib = releases.parent()?;
    if !std::fs::symlink_metadata(lib.join("current")).ok()?.file_type().is_symlink() {
        return None;
    }
    Some(Own { lib: lib.to_path_buf(), name: release.file_name()?.to_str()?.to_string() })
}

/// The release of this process.
pub fn own() -> Option<Own> {
    locate(&std::env::current_exe().ok()?)
}

fn runnable(path: &Path) -> bool {
    std::fs::metadata(path).map(|m| m.is_file() && m.permissions().mode() & 0o111 != 0).unwrap_or(false)
}

/// Compare `own` with the release `current` points at now: two path reads, no process.
pub fn check(own: &Own) -> Verdict {
    let current = match std::fs::canonicalize(own.lib.join("current")) {
        Ok(path) => path,
        Err(error) => return Verdict::Restart(format!("설치본 current를 읽을 수 없습니다({error})")),
    };
    let releases = own.lib.join("releases");
    let name = match (current.parent(), current.file_name().and_then(|n| n.to_str())) {
        (Some(parent), Some(name)) if parent == releases => name.to_string(),
        _ => return Verdict::Restart("설치본 current가 releases 밖을 가리킵니다".to_string()),
    };
    if name == own.name {
        return Verdict::Same;
    }
    let binary = current.join("tools").join("project-board").join("bin").join(SIDEBAR);
    if !runnable(&binary) {
        return Verdict::Restart(format!("새 release {name}에 {SIDEBAR}가 없거나 실행할 수 없습니다"));
    }
    Verdict::Switch { name, binary }
}

/// Replace this process with `binary` (same pid, same pane, same environment, same arguments). Returns only when
/// that failed, with the reason. `execv`, not `Command::exec`: the standard library's `execvp` runs a file that is
/// not a program through `/bin/sh` (`ENOEXEC`), which would end the sidebar instead of failing.
pub fn exec_into(binary: &Path) -> std::io::Error {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;
    let invalid = || std::io::Error::new(std::io::ErrorKind::InvalidInput, "path or argument with a NUL byte");
    let Ok(path) = CString::new(binary.as_os_str().as_bytes()) else { return invalid() };
    let mut arguments = vec![path.clone()];
    for argument in std::env::args_os().skip(1) {
        let Ok(argument) = CString::new(argument.as_bytes()) else { return invalid() };
        arguments.push(argument);
    }
    let mut argv: Vec<*const libc::c_char> = arguments.iter().map(|a| a.as_ptr()).collect();
    argv.push(std::ptr::null());
    std::env::set_var(SUCCESSOR, "1");
    unsafe { libc::execv(path.as_ptr(), argv.as_ptr()) };
    let error = std::io::Error::last_os_error();
    std::env::remove_var(SUCCESSOR);
    error
}

/// `--version`: the program and its release.
pub fn version_line() -> String {
    match own() {
        Some(own) => format!("{SIDEBAR} {}", own.name),
        None => format!("{SIDEBAR} (not in an installed release)"),
    }
}

/// `project-board-sidebar release`: this binary's release as one JSON line, `{"release": name | null}`, for the
/// equivalence test with the Python reader.
pub fn print() -> i32 {
    println!("{}", serde_json::json!({"release": own().map(|o| o.name)}));
    0
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::symlink;

    struct Lib(PathBuf);
    impl Lib {
        fn new(label: &str) -> Lib {
            let dir = std::env::temp_dir().join(format!("pbr-{label}-{}", std::process::id()));
            let _ = std::fs::remove_dir_all(&dir);
            std::fs::create_dir_all(dir.join("releases")).unwrap();
            Lib(std::fs::canonicalize(&dir).unwrap())
        }
        fn release(&self, name: &str, with_binary: bool) -> PathBuf {
            let bin = self.0.join("releases").join(name).join("tools/project-board/bin");
            std::fs::create_dir_all(&bin).unwrap();
            let binary = bin.join(SIDEBAR);
            if with_binary {
                std::fs::write(&binary, "#!/bin/sh\n").unwrap();
                std::fs::set_permissions(&binary, std::fs::Permissions::from_mode(0o755)).unwrap();
            }
            binary
        }
        fn point(&self, target: &str) {
            let link = self.0.join("current");
            let _ = std::fs::remove_file(&link);
            symlink(target, link).unwrap();
        }
    }
    impl Drop for Lib {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn the_release_is_the_directory_the_binary_is_in() {
        let lib = Lib::new("locate");
        let binary = lib.release("0.11.0-aaaaaaaaaaaa", true);
        assert_eq!(locate(&binary), None, "no `current` yet: not an installed layout");
        lib.point("releases/0.11.0-aaaaaaaaaaaa");
        assert_eq!(locate(&binary), Some(Own { lib: lib.0.clone(), name: "0.11.0-aaaaaaaaaaaa".into() }));
        assert_eq!(locate(Path::new("/x/tools/project-board/rust/target/release/project-board-sidebar")), None);
        assert_eq!(locate(Path::new("/project-board-sidebar")), None);
    }

    #[test]
    fn the_same_release_does_nothing() {
        let lib = Lib::new("same");
        lib.release("0.11.0-aaaaaaaaaaaa", true);
        lib.point("releases/0.11.0-aaaaaaaaaaaa");
        let own = Own { lib: lib.0.clone(), name: "0.11.0-aaaaaaaaaaaa".into() };
        assert_eq!(check(&own), Verdict::Same);
    }

    #[test]
    fn another_release_with_a_runnable_binary_is_switched_to_and_an_absolute_link_counts() {
        let lib = Lib::new("switch");
        lib.release("0.11.0-aaaaaaaaaaaa", true);
        let new = lib.release("0.12.0-bbbbbbbbbbbb", true);
        let own = Own { lib: lib.0.clone(), name: "0.11.0-aaaaaaaaaaaa".into() };
        lib.point("releases/0.12.0-bbbbbbbbbbbb");
        assert_eq!(check(&own), Verdict::Switch { name: "0.12.0-bbbbbbbbbbbb".into(), binary: new.clone() });
        lib.point(lib.0.join("releases/0.12.0-bbbbbbbbbbbb").to_str().unwrap());
        assert_eq!(check(&own), Verdict::Switch { name: "0.12.0-bbbbbbbbbbbb".into(), binary: new });
    }

    #[test]
    fn a_new_release_without_a_runnable_binary_says_why() {
        let lib = Lib::new("missing");
        lib.release("0.11.0-aaaaaaaaaaaa", true);
        let own = Own { lib: lib.0.clone(), name: "0.11.0-aaaaaaaaaaaa".into() };
        let new = lib.release("0.12.0-bbbbbbbbbbbb", false);
        lib.point("releases/0.12.0-bbbbbbbbbbbb");
        assert!(matches!(check(&own), Verdict::Restart(reason) if reason.contains("0.12.0-bbbbbbbbbbbb")));
        std::fs::write(&new, "x").unwrap();
        std::fs::set_permissions(&new, std::fs::Permissions::from_mode(0o644)).unwrap();
        assert!(matches!(check(&own), Verdict::Restart(_)), "not executable");
    }

    #[test]
    fn a_current_that_cannot_be_read_or_leaves_releases_is_a_restart() {
        let lib = Lib::new("odd");
        lib.release("0.11.0-aaaaaaaaaaaa", true);
        let own = Own { lib: lib.0.clone(), name: "0.11.0-aaaaaaaaaaaa".into() };
        lib.point("releases/gone");
        assert!(matches!(check(&own), Verdict::Restart(_)));
        std::fs::create_dir_all(lib.0.join("elsewhere")).unwrap();
        lib.point("elsewhere");
        assert!(matches!(check(&own), Verdict::Restart(reason) if reason.contains("releases")));
    }
}
