//! `project-board-sidebar dump --config PATH [--now ISO]`: the JSON the equivalence test compares with the Python model.
use super::{parse_utc, Reader};
use std::path::PathBuf;

const USAGE: &str =
    "usage: project-board-sidebar dump [--config PATH] [--now YYYY-MM-DDTHH:MM:SSZ] [--timing]";

/// Prints `{"before": snapshot, "liveness": liveness, "after": snapshot}` as one line: the snapshot, then the
/// liveness (which sets the release holds), then the snapshot again. Returns the process exit status.
///
/// The liveness of a project whose state cannot be read is `{}` (the Python model gives `{"error": ...}` for
/// every cause but a missing state; the sidebar never shows it).
pub fn run(args: &[String]) -> i32 {
    if args.first().map(String::as_str) == Some("cron") {
        return cron(&args[1..]);
    }
    let mut config: Option<PathBuf> = None;
    let mut now: Option<i64> = None;
    let mut timing = false;
    let mut rest = args.iter().peekable();
    while let Some(arg) = rest.next() {
        if arg == "--timing" {
            timing = true;
            continue;
        }
        match (arg.as_str(), rest.next()) {
            ("--config", Some(value)) => config = Some(PathBuf::from(value)),
            ("--now", Some(value)) => match parse_utc(value) {
                Some(seconds) => now = Some(seconds),
                None => {
                    eprintln!("dump: --now must be YYYY-MM-DDTHH:MM:SSZ\n{USAGE}");
                    return 2;
                }
            },
            _ => {
                eprintln!("{USAGE}");
                return 2;
            }
        }
    }
    let now = now.unwrap_or_else(|| {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs() as i64)
            .unwrap_or(0)
    });
    let reader = Reader::new(config);
    if timing {
        return measure(&reader, now);
    }
    let before = reader.snapshot(now);
    let liveness = reader.liveness();
    let after = reader.snapshot(now);
    let output = serde_json::json!({"before": before, "liveness": liveness, "after": after});
    println!("{output}");
    0
}

/// CPU seconds (user and system, all threads) this process has used.
fn cpu_seconds() -> f64 {
    // SAFETY: `usage` is written by getrusage and read only after it succeeds.
    unsafe {
        let mut usage: libc::rusage = std::mem::zeroed();
        if libc::getrusage(libc::RUSAGE_SELF, &mut usage) != 0 {
            return 0.0;
        }
        let seconds = |t: libc::timeval| t.tv_sec as f64 + t.tv_usec as f64 / 1e6;
        seconds(usage.ru_utime) + seconds(usage.ru_stime)
    }
}

/// `dump --timing`: the cost of the first snapshot, of a refresh that finds nothing changed, and of the liveness read.
/// The files are given 3 seconds to age past the settle time first, so the refreshes are the steady state.
fn measure(reader: &Reader, now: i64) -> i32 {
    use std::time::{Duration, Instant};
    let (cpu_start, started) = (cpu_seconds(), Instant::now());
    let first = reader.snapshot(now);
    let (first_wall, first_cpu) = (started.elapsed().as_secs_f64(), cpu_seconds() - cpu_start);
    std::thread::sleep(Duration::from_secs(3));
    reader.snapshot(now);
    let runs = 10;
    let (cpu_before, wall_before) = (cpu_seconds(), Instant::now());
    for _ in 0..runs {
        reader.snapshot(now);
    }
    let (refresh_wall, refresh_cpu) = (
        wall_before.elapsed().as_secs_f64() / runs as f64,
        (cpu_seconds() - cpu_before) / runs as f64,
    );
    let (cpu_before, wall_before) = (cpu_seconds(), Instant::now());
    reader.liveness();
    let (live_wall, live_cpu) = (
        wall_before.elapsed().as_secs_f64(),
        cpu_seconds() - cpu_before,
    );
    println!(
        "{}",
        serde_json::json!({"projects": first.projects.len(), "first_wall": first_wall, "first_cpu": first_cpu,
            "refresh_wall": refresh_wall, "refresh_cpu": refresh_cpu, "liveness_wall": live_wall, "liveness_cpu": live_cpu})
    );
    0
}

/// `dump cron --crontab FILE --now YYYY-MM-DDTHH:MM --project ID ...`: what the sidebar makes of a crontab text for each
/// project, `{id: {"count": n, "next_run": "YYYY-MM-DDTHH:MM" | null}}` or `{id: {"error": message}}` for a broken
/// section. The equivalence test gives the same text to `agent_session.cron` (`tests/test_rust_cron.py`).
fn cron(args: &[String]) -> i32 {
    let (mut file, mut now, mut ids) = (None, None, Vec::new());
    let mut rest = args.iter();
    while let Some(arg) = rest.next() {
        match (arg.as_str(), rest.next()) {
            ("--crontab", Some(value)) => file = Some(value.clone()),
            ("--now", Some(value)) => now = crate::cron::Civil::parse(value),
            ("--project", Some(value)) => ids.push(value.as_str()),
            _ => {
                eprintln!("usage: project-board-sidebar dump cron --crontab FILE --now YYYY-MM-DDTHH:MM --project ID ...");
                return 2;
            }
        }
    }
    let (Some(file), Some(now)) = (file, now) else {
        eprintln!("dump cron: --crontab and --now are required");
        return 2;
    };
    let Ok(text) = std::fs::read_to_string(&file) else {
        eprintln!("dump cron: cannot read {file}");
        return 2;
    };
    let view = super::crontab::view_of(&text, &ids);
    let mut out = serde_json::Map::new();
    for id in ids {
        let entry = &view[id];
        let value = match &entry.error {
            Some(message) => serde_json::json!({"error": message}),
            None => serde_json::json!({
                "count": entry.schedules.len(),
                "next_run": crate::cron::nearest(&entry.schedules, &now).map(|next| next.iso()),
            }),
        };
        out.insert(id.to_string(), value);
    }
    println!("{}", serde_json::Value::Object(out));
    0
}
