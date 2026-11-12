//! Python text and path behavior that the Python reader relies on (`str.splitlines`, `str.strip`, `Path.resolve`,
//! the messages of `UnicodeDecodeError` and `OSError`). The data layer must give the same answers as the Python
//! model, so these follow Python and not the Rust standard library where the two differ.
use std::ffi::OsStr;
use std::os::unix::ffi::OsStrExt;
use std::path::{Component, Path, PathBuf};

/// `str.isspace()` of one character (Rust's `White_Space` plus the separators U+001C to U+001F).
pub fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\x1c'..='\x1f').contains(&c)
}

/// `str.strip()`.
pub fn strip(text: &str) -> &str {
    text.trim_matches(is_space)
}

/// `str.splitlines()` (no line ends kept): \n, \r, \r\n, \v, \f, \x1c-\x1e, \x85,  ,  .
pub fn splitlines(text: &str) -> Vec<&str> {
    let mut lines = Vec::new();
    let mut start = 0;
    let mut chars = text.char_indices();
    while let Some((index, c)) = chars.next() {
        match c {
            '\n' | '\x0b' | '\x0c' | '\x1c' | '\x1d' | '\x1e' | '\u{85}' | '\u{2028}'
            | '\u{2029}' => {
                lines.push(&text[start..index]);
                start = index + c.len_utf8();
            }
            '\r' => {
                lines.push(&text[start..index]);
                start = index + 1;
                if text[start..].starts_with('\n') {
                    start += 1;
                    chars.next();
                }
            }
            _ => {}
        }
    }
    if start < text.len() {
        lines.push(&text[start..]);
    }
    lines
}

/// `str(UnicodeDecodeError)` of decoding `bytes` as UTF-8.
pub fn decode_error(bytes: &[u8], error: &std::str::Utf8Error) -> String {
    let start = error.valid_up_to();
    let (end, reason) = match error.error_len() {
        None => (bytes.len(), "unexpected end of data"),
        Some(length) => {
            let first = bytes[start];
            let reason = if (0x80..=0xc1).contains(&first) || first >= 0xf5 {
                "invalid start byte"
            } else {
                "invalid continuation byte"
            };
            (start + length, reason)
        }
    };
    if end == start + 1 {
        format!(
            "'utf-8' codec can't decode byte 0x{:02x} in position {}: {}",
            bytes[start], start, reason
        )
    } else {
        format!(
            "'utf-8' codec can't decode bytes in position {}-{}: {}",
            start,
            end - 1,
            reason
        )
    }
}

/// `repr()` of a Python `str`.
pub fn repr(text: &str) -> String {
    let quote = if text.contains('\'') && !text.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::from(quote);
    for c in text.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if (c as u32) < 0x20 || c as u32 == 0x7f => {
                out.push_str(&format!("\\x{:02x}", c as u32))
            }
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// `str(OSError)` as Python prints it: `[Errno 2] No such file or directory: '/path'`.
pub fn os_error_message(error: &std::io::Error, path: &Path) -> String {
    let code = error.raw_os_error().unwrap_or(0);
    let text = error.to_string();
    let reason = text.split(" (os error").next().unwrap_or(&text);
    format!(
        "[Errno {}] {}: {}",
        code,
        reason,
        repr(&path.to_string_lossy())
    )
}

/// The home directory `Path.expanduser()` uses: `$HOME`, else the password database.
fn home() -> Option<PathBuf> {
    if let Some(home) = std::env::var_os("HOME") {
        return Some(PathBuf::from(home));
    }
    // SAFETY: getpwuid returns a pointer into static storage that is read at once.
    unsafe {
        let entry = libc::getpwuid(libc::getuid());
        if entry.is_null() || (*entry).pw_dir.is_null() {
            return None;
        }
        Some(PathBuf::from(OsStr::from_bytes(
            std::ffi::CStr::from_ptr((*entry).pw_dir).to_bytes(),
        )))
    }
}

/// `Path(text).expanduser()` for `~` and `~/...`; another `~user` form is left as it is.
pub fn expanduser(text: &str) -> PathBuf {
    if text == "~" || text.starts_with("~/") {
        if let Some(home) = home() {
            let home = home.to_string_lossy().trim_end_matches('/').to_string();
            let rest = &text[1..];
            let joined = format!("{}{}", home, rest);
            return PathBuf::from(if joined.is_empty() {
                "/".to_string()
            } else {
                joined
            });
        }
    }
    PathBuf::from(text)
}

/// `Path.resolve()` (non-strict): resolve symbolic links of the part that exists, and keep the rest as written.
pub fn resolve(path: &Path) -> PathBuf {
    let mut pending: Vec<std::ffi::OsString> = Vec::new();
    let mut result = PathBuf::from("/");
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .unwrap_or_else(|_| PathBuf::from("/"))
            .join(path)
    };
    for component in absolute.components().rev() {
        match component {
            Component::Normal(name) => pending.push(name.to_os_string()),
            Component::ParentDir => pending.push("..".into()),
            _ => {}
        }
    }
    let mut hops = 0;
    while let Some(name) = pending.pop() {
        if name == ".." {
            result.pop();
            continue;
        }
        let next = result.join(&name);
        match std::fs::symlink_metadata(&next) {
            Ok(meta) if meta.file_type().is_symlink() => {
                hops += 1;
                let target = std::fs::read_link(&next);
                match target {
                    Ok(target) if hops <= 40 => {
                        if target.is_absolute() {
                            result = PathBuf::from("/");
                        }
                        for component in target.components().rev() {
                            match component {
                                Component::Normal(part) => pending.push(part.to_os_string()),
                                Component::ParentDir => pending.push("..".into()),
                                _ => {}
                            }
                        }
                    }
                    _ => result = next, // a loop or an unreadable link stays as it is
                }
            }
            _ => result = next,
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splitlines_follows_python() {
        // Python: "a\r\nb\rc\x0bd e\n".splitlines() == ['a', 'b', 'c', 'd', 'e']; "\n".splitlines() == ['']; "".splitlines() == []
        assert_eq!(
            splitlines("a\r\nb\rc\x0bd\u{2028}e\n"),
            vec!["a", "b", "c", "d", "e"]
        );
        assert_eq!(splitlines("\n"), vec![""]);
        assert!(splitlines("").is_empty());
        assert_eq!(splitlines("a\n\nb"), vec!["a", "", "b"]);
    }

    #[test]
    fn strip_removes_python_whitespace() {
        assert_eq!(strip("\x1f a \u{3000}"), "a");
    }

    #[test]
    fn decode_error_messages_equal_python() {
        // Each expectation is `str(UnicodeDecodeError)` from CPython 3.12 (bytes(...).decode("utf-8")).
        let message = |bytes: &[u8]| decode_error(bytes, &std::str::from_utf8(bytes).unwrap_err());
        assert_eq!(
            message(b"\xff"),
            "'utf-8' codec can't decode byte 0xff in position 0: invalid start byte"
        );
        assert_eq!(
            message(b"ab\xe3\x81"),
            "'utf-8' codec can't decode bytes in position 2-3: unexpected end of data"
        );
        assert_eq!(
            message(b"\xe3"),
            "'utf-8' codec can't decode byte 0xe3 in position 0: unexpected end of data"
        );
        assert_eq!(
            message(b"\xe3\x81A"),
            "'utf-8' codec can't decode bytes in position 0-1: invalid continuation byte"
        );
        assert_eq!(
            message(b"\xe3A"),
            "'utf-8' codec can't decode byte 0xe3 in position 0: invalid continuation byte"
        );
        assert_eq!(
            message(b"a\x80"),
            "'utf-8' codec can't decode byte 0x80 in position 1: invalid start byte"
        );
    }

    #[test]
    fn repr_picks_the_quote_like_python() {
        assert_eq!(repr("/a/b"), "'/a/b'");
        assert_eq!(repr("it's"), "\"it's\"");
        assert_eq!(repr("a\\b"), "'a\\\\b'");
    }

    #[test]
    fn resolve_keeps_a_missing_tail_and_follows_links() {
        let dir = std::env::temp_dir().join(format!("pytext-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("real")).unwrap();
        std::os::unix::fs::symlink("real", dir.join("link")).unwrap();
        let real = std::fs::canonicalize(&dir).unwrap();
        assert_eq!(resolve(&dir.join("link/x/../y")), real.join("real/y"));
        assert_eq!(resolve(&dir.join("./real//z")), real.join("real/z"));
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
