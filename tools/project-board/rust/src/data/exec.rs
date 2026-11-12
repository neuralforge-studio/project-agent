//! Run a child process with a time limit and capture its output (Python `subprocess.run(..., timeout=...)`).
use std::io::{Read, Write};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

pub struct Output {
    pub status: i32,
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
}

pub enum RunError {
    /// The program could not be started because it does not exist.
    Missing,
    /// Any other failure to start, or the limit passed (the child is killed).
    Failed,
}

pub fn run(
    mut command: Command,
    input: Option<&[u8]>,
    limit: Duration,
) -> Result<Output, RunError> {
    command.stdin(if input.is_some() {
        Stdio::piped()
    } else {
        Stdio::null()
    });
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = command.spawn().map_err(|error| {
        if error.kind() == std::io::ErrorKind::NotFound {
            RunError::Missing
        } else {
            RunError::Failed
        }
    })?;
    let writer = input.map(|bytes| {
        let mut stdin = child.stdin.take().unwrap();
        let bytes = bytes.to_vec();
        std::thread::spawn(move || {
            let _ = stdin.write_all(&bytes);
        })
    });
    let mut out = child.stdout.take().unwrap();
    let mut err = child.stderr.take().unwrap();
    let out_reader = std::thread::spawn(move || {
        let mut bytes = Vec::new();
        let _ = out.read_to_end(&mut bytes);
        bytes
    });
    let err_reader = std::thread::spawn(move || {
        let mut bytes = Vec::new();
        let _ = err.read_to_end(&mut bytes);
        bytes
    });
    let deadline = Instant::now() + limit;
    let mut pause = Duration::from_micros(500);
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status.code().unwrap_or(-1)),
            Ok(None) => {}
            Err(_) => break None,
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            break None;
        }
        std::thread::sleep(pause);
        pause = (pause * 2).min(Duration::from_millis(10));
    };
    if let Some(writer) = writer {
        let _ = writer.join();
    }
    let stdout = out_reader.join().unwrap_or_default();
    let stderr = err_reader.join().unwrap_or_default();
    match status {
        Some(status) => Ok(Output {
            status,
            stdout,
            stderr,
        }),
        None => Err(RunError::Failed),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn captures_output_and_status() {
        let mut command = Command::new("sh");
        command.args(["-c", "cat; echo err >&2; exit 3"]);
        let output = run(command, Some(b"in"), Duration::from_secs(5))
            .ok()
            .unwrap();
        assert_eq!(
            (output.status, output.stdout, output.stderr),
            (3, b"in".to_vec(), b"err\n".to_vec())
        );
    }

    #[test]
    fn a_child_past_the_limit_is_killed() {
        let mut command = Command::new("sleep");
        command.arg("30");
        let started = Instant::now();
        assert!(matches!(
            run(command, None, Duration::from_millis(200)),
            Err(RunError::Failed)
        ));
        assert!(started.elapsed() < Duration::from_secs(5));
        assert!(matches!(
            run(Command::new("/nonexistent/x"), None, Duration::from_secs(1)),
            Err(RunError::Missing)
        ));
    }
}
