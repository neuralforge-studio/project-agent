//! `model.snapshot`: every project's facts from its files. Directory listings, file records and state files are
//! kept under file signatures, so a refresh stats what it has and reads only what changed (`model._cached`,
//! `model._unchanged`); the first read opens the files on several threads, because that is where the time goes.
use super::items::{self, DecisionHeaders, InProgress};
use super::par::par_map;
use super::pytext::{decode_error, os_error_message};
use super::registry::Project;
use super::stamp::{mtime_ns, now_ns, parse_utc, settled, sig_of, Sig};
use super::state::{self, State};
use crate::model::{self, CrCounts, Decide, Leader, ProjectError};
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::Arc;

const CR_STATES: [&str; 5] = ["open", "todo", "in-progress", "done", "deferred"];
const SHOWN_CR_STATES: usize = 3;
const DECIDE_STATES: [&str; 3] = ["open", "answered", "done"];

/// The directories below `base` that `model._tree_stamps` watches, and the item files `cr.files` lists.
struct Listing {
    stamps: Vec<(PathBuf, i64)>,
    files: Vec<PathBuf>,
}

fn is_item(name: &str) -> bool {
    name.ends_with(".md") && name != "README.md" && !name.starts_with("ORDER")
}

/// `cr.files(root, state)` with the stamps of `base` and of every directory below it; None when a stat fails.
fn walk(base: &Path) -> Option<Listing> {
    let mut listing = Listing {
        stamps: vec![(base.to_path_buf(), mtime_ns(&fs::metadata(base).ok()?))],
        files: Vec::new(),
    };
    let mut ok = true;
    let mut pending = vec![base.to_path_buf()];
    while let Some(dir) = pending.pop() {
        let Ok(entries) = fs::read_dir(&dir) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            let Ok(kind) = entry.file_type() else {
                continue;
            };
            if kind.is_dir() {
                match fs::metadata(&path) {
                    Ok(meta) => listing.stamps.push((path.clone(), mtime_ns(&meta))),
                    Err(_) => ok = false,
                }
                pending.push(path.clone());
            } else if kind.is_symlink() {
                match fs::metadata(&path) {
                    Ok(meta) if meta.is_dir() => {
                        listing.stamps.push((path.clone(), mtime_ns(&meta)))
                    }
                    Ok(_) => {}
                    Err(_) => {} // a broken link is still a file name
                }
            }
            if entry.file_name().to_str().is_some_and(is_item) {
                listing.files.push(path);
            }
        }
    }
    listing.files.sort();
    ok.then_some(listing)
}

/// One directory's listing: the kept one while no stamp changed, else a new one. The flag says whether to keep it.
fn list_dir(dir: &Path, kept: Option<&Arc<Listing>>, now: i64) -> (Arc<Listing>, bool) {
    if let Some(old) = kept {
        if old.stamps.iter().all(|(path, stamp)| {
            fs::metadata(path)
                .map(|m| mtime_ns(&m) == *stamp)
                .unwrap_or(false)
        }) {
            return (old.clone(), true);
        }
    }
    if !dir.is_dir() {
        return (
            Arc::new(Listing {
                stamps: Vec::new(),
                files: Vec::new(),
            }),
            false,
        );
    }
    match walk(dir) {
        Some(listing) => {
            let keep = listing.stamps.iter().all(|(_, stamp)| settled(*stamp, now));
            (Arc::new(listing), keep)
        }
        None => (
            Arc::new(Listing {
                stamps: Vec::new(),
                files: Vec::new(),
            }),
            false,
        ),
    }
}

#[derive(Clone, Copy, PartialEq)]
enum Kind {
    /// Read to see that it is text; nothing of it is shown.
    Plain,
    InProgressCr,
    DoneDecision,
}

#[derive(Clone)]
enum Rec {
    Plain,
    Cr(InProgress),
    Decision(DecisionHeaders),
}

struct Task<'a> {
    path: &'a Path,
    kind: Kind,
}

/// Read and parse a file. The error is the message Python gives (`str(error)` of an OSError or UnicodeDecodeError).
/// The signature is the one of the open file, taken before its content is read.
fn build(task: &Task) -> Result<(Rec, Option<fs::Metadata>), String> {
    let failed = |e: std::io::Error| os_error_message(&e, task.path);
    let mut file = fs::File::open(task.path).map_err(failed)?;
    let meta = file.metadata().ok();
    let mut bytes = Vec::with_capacity(meta.as_ref().map(|m| m.len() as usize + 1).unwrap_or(0));
    file.read_to_end(&mut bytes).map_err(failed)?;
    let text = std::str::from_utf8(&bytes).map_err(|e| decode_error(&bytes, &e))?;
    let rec = match task.kind {
        Kind::Plain => Rec::Plain,
        Kind::InProgressCr => {
            let name = task
                .path
                .file_name()
                .map(|n| n.to_string_lossy())
                .unwrap_or_default();
            Rec::Cr(items::in_progress(text, items::stem(&name)))
        }
        Kind::DoneDecision => Rec::Decision(items::decision_headers(text)),
    };
    Ok((rec, meta))
}

type FileCache = HashMap<PathBuf, (Sig, Rec)>;

/// The record of a file: the kept one while the signature is the same. The second value is what to keep.
/// A file that was not read before is not stat-ed first: opening it gives the signature.
fn load(task: &Task, kept: &FileCache, now: i64) -> (Result<Rec, String>, Option<(Sig, Rec)>) {
    if let Some((old, rec)) = kept.get(task.path) {
        if fs::metadata(task.path).ok().map(|meta| sig_of(&meta)) == Some(*old) {
            return (Ok(rec.clone()), Some((*old, rec.clone())));
        }
    }
    match build(task) {
        Ok((rec, meta)) => {
            let keep = match &meta {
                Some(meta) if settled(mtime_ns(meta), now) => Some((sig_of(meta), rec.clone())),
                _ => None,
            };
            (Ok(rec), keep)
        }
        Err(message) => (Err(message), None),
    }
}

#[derive(Default)]
pub struct Caches {
    listings: HashMap<PathBuf, Arc<Listing>>,
    files: FileCache,
    states: HashMap<PathBuf, state::Kept>,
}

/// Where one project's tasks are: CR files, then decisions.
struct Layout {
    /// For each directory of the project, in the order of `dirs`: the index into `listings`.
    cr: Vec<usize>,
    decide: Vec<usize>,
}

fn error_row(source: &str, message: String) -> ProjectError {
    ProjectError {
        source: source.to_string(),
        message,
    }
}

fn elapsed(connected_at: Option<&str>, now: i64) -> Option<i64> {
    let start = parse_utc(connected_at?)?;
    Some((now - start).max(0))
}

/// `model.snapshot()` of the loaded `projects`. `releases` are the holds the last liveness read.
pub fn snapshot(
    projects: &[Project],
    caches: &mut Caches,
    releases: &HashMap<String, HashSet<String>>,
    now: i64,
    threads: usize,
) -> Vec<model::Project> {
    let clock = now_ns();
    // Threads pay off only while the files are opened for the first time (file system latency). A refresh that
    // finds its caches full only stats, and starting threads then costs more CPU than the stats do.
    let threads = if caches.listings.is_empty() && caches.files.is_empty() {
        threads
    } else {
        1
    };
    // 1. The listings of every directory a project reads: done and deferred only for the decisions' sake.
    let mut dirs: Vec<PathBuf> = Vec::new();
    let mut layouts: Vec<Layout> = Vec::new();
    for project in projects {
        let mut layout = Layout {
            cr: Vec::new(),
            decide: Vec::new(),
        };
        if let Some(root) = &project.path_cr {
            let count = if project.path_decide.is_some() {
                CR_STATES.len()
            } else {
                SHOWN_CR_STATES
            };
            for state in &CR_STATES[..count] {
                layout.cr.push(dirs.len());
                dirs.push(root.join(state));
            }
        }
        if let Some(root) = &project.path_decide {
            for state in DECIDE_STATES {
                layout.decide.push(dirs.len());
                dirs.push(root.join(state));
            }
        }
        layouts.push(layout);
    }
    let listed = par_map(&dirs, threads, |dir| {
        list_dir(dir, caches.listings.get(dir), clock)
    });
    let mut kept_listings = HashMap::new();
    let mut listings: Vec<Arc<Listing>> = Vec::with_capacity(listed.len());
    for (dir, (listing, keep)) in dirs.iter().zip(listed) {
        if keep {
            kept_listings.insert(dir.clone(), listing.clone());
        }
        listings.push(listing);
    }
    caches.listings = kept_listings;
    // 2. The records of the files whose content is read: open, todo and in-progress CRs, and every decision.
    let mut tasks: Vec<Task> = Vec::new();
    let mut ranges: Vec<(usize, usize, usize)> = Vec::new(); // per project: start of CRs, start of decisions, end
    for layout in &layouts {
        let first = tasks.len();
        for (position, index) in layout.cr.iter().take(SHOWN_CR_STATES).enumerate() {
            let kind = if position == 2 {
                Kind::InProgressCr
            } else {
                Kind::Plain
            };
            tasks.extend(
                listings[*index]
                    .files
                    .iter()
                    .map(|path| Task { path, kind }),
            );
        }
        let decisions = tasks.len();
        for (position, index) in layout.decide.iter().enumerate() {
            let kind = if position == 2 {
                Kind::DoneDecision
            } else {
                Kind::Plain
            };
            tasks.extend(
                listings[*index]
                    .files
                    .iter()
                    .map(|path| Task { path, kind }),
            );
        }
        ranges.push((first, decisions, tasks.len()));
    }
    let loaded = par_map(&tasks, threads, |task| load(task, &caches.files, clock));
    let mut kept_files = FileCache::new();
    let mut records: Vec<Result<Rec, String>> = Vec::with_capacity(loaded.len());
    for (task, (result, keep)) in tasks.iter().zip(loaded) {
        if let Some(entry) = keep {
            kept_files.insert(task.path.to_path_buf(), entry);
        }
        records.push(result);
    }
    caches.files = kept_files;
    // 3. The state files, one per project.
    let state_reads = par_map(projects, threads, |project| {
        let path = project.base.join("agent").join("state.json");
        (
            path.clone(),
            state::read_state_value(project, caches.states.get(&path)),
        )
    });
    let mut kept_states = HashMap::new();
    let mut state_values: Vec<Result<Value, super::err::SessionError>> = Vec::new();
    for (path, (result, keep)) in state_reads {
        if let Some(entry) = keep {
            kept_states.insert(path, entry);
        }
        state_values.push(result);
    }
    caches.states = kept_states;
    // 4. One project at a time.
    let mut views = Vec::with_capacity(projects.len());
    for (index, project) in projects.iter().enumerate() {
        let layout = &layouts[index];
        let (cr_from, decide_from, end) = ranges[index];
        let mut errors: Vec<ProjectError> = Vec::new();
        let state: Option<State> = match &state_values[index] {
            Ok(value) => match state::validate(project, value) {
                Ok(state) => Some(state),
                Err(e) => {
                    errors.push(error_row("state", e.message));
                    None
                }
            },
            Err(e) if e.code == "state_not_found" => None,
            Err(e) => {
                errors.push(error_row("state", e.message.clone()));
                None
            }
        };
        let mut cr = None;
        let mut in_progress: HashMap<String, InProgress> = HashMap::new();
        if project.path_cr.is_some() {
            let mut counts = [0usize; 3];
            let mut at = cr_from;
            let mut failure = None;
            for (position, slot) in layout.cr.iter().take(SHOWN_CR_STATES).enumerate() {
                let files = listings[*slot].files.len();
                counts[position] = files;
                for record in &records[at..at + files] {
                    match record {
                        Ok(Rec::Cr(item)) => {
                            in_progress.insert(item.id.clone(), item.clone());
                        }
                        Ok(_) => {}
                        Err(message) if failure.is_none() => failure = Some(message.clone()),
                        Err(_) => {}
                    }
                }
                at += files;
            }
            match failure {
                Some(message) => {
                    errors.push(error_row("cr", message));
                    in_progress.clear();
                }
                None => {
                    cr = Some(CrCounts {
                        open: counts[0],
                        todo: counts[1],
                        in_progress: counts[2],
                    })
                }
            }
        }
        let mut decide = None;
        if project.path_decide.is_some() {
            // `cr_states`: the directory state of each CR ID; a later state wins, as in `all_files`.
            let mut cr_states: HashMap<&str, &'static str> = HashMap::new();
            for (position, slot) in layout.cr.iter().enumerate() {
                for path in &listings[*slot].files {
                    if let Some(id) = path
                        .file_name()
                        .and_then(|n| n.to_str())
                        .and_then(items::cr_file_id_of)
                    {
                        cr_states.insert(id, CR_STATES[position]);
                    }
                }
            }
            let mut stages = [0usize; 4];
            let mut open = 0;
            let mut at = decide_from;
            let mut failure = None;
            for (position, slot) in layout.decide.iter().enumerate() {
                let files = listings[*slot].files.len();
                if position == 0 {
                    open = files;
                }
                for record in &records[at..at + files] {
                    match record {
                        Ok(Rec::Decision(headers)) => {
                            stages[items::done_stage(headers, |id| cr_states.get(id).copied())] += 1
                        }
                        Ok(_) => stages[position] += 1,
                        Err(message) if failure.is_none() => failure = Some(message.clone()),
                        Err(_) => {}
                    }
                }
                at += files;
            }
            debug_assert!(at == end);
            match failure {
                Some(message) => errors.push(error_row("decide", message)),
                None => decide = Some(Decide { open, stages }),
            }
        }
        views.push(project_view(
            project,
            state,
            cr,
            decide,
            errors,
            &in_progress,
            releases,
            now,
        ));
    }
    views
}

#[allow(clippy::too_many_arguments)]
fn project_view(
    project: &Project,
    state: Option<State>,
    cr: Option<CrCounts>,
    decide: Option<Decide>,
    errors: Vec<ProjectError>,
    in_progress: &HashMap<String, InProgress>,
    releases: &HashMap<String, HashSet<String>>,
    now: i64,
) -> model::Project {
    let empty = HashSet::new();
    let waiting = if state.is_some() {
        releases.get(&project.id).unwrap_or(&empty)
    } else {
        &empty
    };
    let leader_state = state.as_ref().and_then(|state| state.leader.as_ref());
    let reviewing = leader_state.and_then(|leader| leader.reviewing.as_deref());
    let mut seats = Vec::with_capacity(project.seats.len());
    for (index, root) in project.seats.iter().enumerate() {
        let row = state.as_ref().map(|state| &state.seats[index]);
        let job = row.and_then(|row| row.job_id.as_deref());
        let session = row.and_then(|row| row.session.as_ref());
        let item = job.and_then(|job| in_progress.get(job));
        let status = match job {
            None => "empty",
            Some(job) if waiting.contains(job) => "release_pending",
            Some(_) if session.is_none() => "pending",
            Some(job) if reviewing == Some(job) => "reviewing",
            Some(_) if item.is_some_and(|item| item.review_wait) => "review_wait",
            Some(_) => "working",
        };
        seats.push(model::Seat {
            index,
            job_id: job.map(String::from),
            status: status.to_string(),
            session: session.is_some(),
            host: root.host().map(String::from),
            path: root.path(),
            session_id: session.map(|session| session.session_id.clone()),
            elapsed: session.and_then(|session| elapsed(session.connected_at.as_deref(), now)),
            title: item.map(|item| item.title.clone()),
        });
    }
    model::Project {
        id: project.id.clone(),
        cr,
        decide,
        errors,
        leader: leader_state.map(|leader| Leader {
            elapsed: elapsed(leader.connected_at.as_deref(), now),
        }),
        seats,
    }
}

#[cfg(test)]
mod tests {
    use super::super::Reader;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::time::{Duration, SystemTime};

    const NOW: i64 = 1793874600; // 2026-11-05T10:30:00Z

    struct Tree(PathBuf);

    impl Tree {
        fn new(name: &str) -> Tree {
            let root =
                std::env::temp_dir().join(format!("read-test-{}-{}", std::process::id(), name));
            let _ = fs::remove_dir_all(&root);
            for dir in [
                "cr/open",
                "cr/todo",
                "cr/in-progress",
                "cr/done",
                "cr/deferred",
                "decide/open",
                "decide/answered",
                "decide/done",
            ] {
                fs::create_dir_all(root.join("main/agent").join(dir)).unwrap();
            }
            let registry = format!(
                r#"{{"{}":{{"project":"p","provider":"codex","seats":["{}"],"path_cr":"agent/cr","path_decide":"agent/decide"}}}}"#,
                root.join("main").display(),
                root.join("seat0").display()
            );
            fs::write(root.join("project.json"), registry).unwrap();
            Tree(root)
        }

        fn reader(&self) -> Reader {
            Reader::new(Some(self.0.join("project.json")))
        }

        fn write(&self, relative: &str, text: &str) -> PathBuf {
            let path = self.0.join("main/agent").join(relative);
            fs::write(&path, text).unwrap();
            path
        }
    }

    impl Drop for Tree {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    /// Give a file or directory a modification time long ago, so the Reader trusts (keeps) what it read.
    fn age(path: &Path) {
        let old = SystemTime::now() - Duration::from_secs(3600);
        let file = fs::File::open(path).unwrap();
        file.set_modified(old).unwrap();
    }

    fn age_all(tree: &Tree) {
        let mut paths = vec![tree.0.join("project.json")];
        let mut pending = vec![tree.0.join("main")];
        while let Some(dir) = pending.pop() {
            for entry in fs::read_dir(&dir).unwrap().flatten() {
                paths.push(entry.path());
                if entry.path().is_dir() {
                    pending.push(entry.path());
                }
            }
        }
        // Children before parents: aging a file changes nothing above it, but listing a directory must not touch it.
        paths.sort_by_key(|path| std::cmp::Reverse(path.components().count()));
        for path in paths {
            age(&path);
        }
    }

    const CR: &str = "# TOOL-001: First\n\n- Opened: 2026-11-05\n\n## Result\n\n- 제출 commit: `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`\n";
    const STATE: &str = r#"{"leader":null,"0":{"job_id":"TOOL-001","git_hash":null,"session":{"session_id":"W","endpoint":"e","connected_at":"2026-11-05T08:00:00Z"}}}"#;

    #[test]
    fn counts_stages_and_seats_of_a_small_tree() {
        let tree = Tree::new("small");
        tree.write("cr/in-progress/TOOL-001-x.md", CR);
        tree.write("cr/open/TOOL-002-x.md", "# TOOL-002: Open\n");
        tree.write("cr/done/TOOL-003-x.md", "# TOOL-003: Done\n");
        tree.write("decide/open/D-20261105-01.md", "# D-20261105-01: q\n");
        tree.write(
            "decide/done/D-20261105-02.md",
            "# D-20261105-02: q\n\n- Related: TOOL-001\n- Outcome: decided A\n",
        );
        tree.write(
            "decide/done/D-20261105-03.md",
            "# D-20261105-03: q\n\n- Related: TOOL-003\n- Outcome: decided A\n",
        );
        tree.write("state.json", STATE);
        let snapshot = tree.reader().snapshot(NOW);
        let project = &snapshot.projects[0];
        assert_eq!(snapshot.error, None);
        assert_eq!(project.errors, vec![]);
        let cr = project.cr.as_ref().unwrap();
        assert_eq!((cr.open, cr.todo, cr.in_progress), (1, 0, 1));
        let decide = project.decide.as_ref().unwrap();
        assert_eq!((decide.open, decide.stages), (1, [1, 0, 1, 1]));
        assert_eq!(project.seats[0].status, "review_wait");
        assert_eq!(project.seats[0].title.as_deref(), Some("First"));
        assert_eq!(project.seats[0].elapsed, Some(9000));
    }

    #[test]
    fn a_refresh_follows_changes_whether_or_not_the_files_have_aged() {
        let tree = Tree::new("changes");
        tree.write("cr/in-progress/TOOL-001-x.md", CR);
        tree.write("state.json", STATE);
        let reader = tree.reader();
        assert_eq!(
            reader.snapshot(NOW).projects[0].seats[0].status,
            "review_wait"
        );
        // Recent files are read again each time, so a rewrite of the same size shows at once.
        tree.write(
            "cr/in-progress/TOOL-001-x.md",
            &CR.replace("aaaaaaaa", "bbbbbbbb").replace("First", "First"),
        );
        assert_eq!(
            reader.snapshot(NOW).projects[0].seats[0].status,
            "review_wait"
        );
        // Aged files are kept by their signature: a new file (new inode and size) replaces what was kept.
        age_all(&tree);
        assert_eq!(
            reader.snapshot(NOW).projects[0].seats[0].title.as_deref(),
            Some("First")
        );
        let replacement = CR.replace("First", "Renamed title");
        let staged = tree.write("cr/in-progress/new.tmp", &replacement);
        age(&staged);
        fs::rename(
            &staged,
            tree.0.join("main/agent/cr/in-progress/TOOL-001-x.md"),
        )
        .unwrap();
        assert_eq!(
            reader.snapshot(NOW).projects[0].seats[0].title.as_deref(),
            Some("Renamed title")
        );
        // A CR that moves to done/ leaves in-progress (the directories' times changed), and a new state is read.
        fs::rename(
            tree.0.join("main/agent/cr/in-progress/TOOL-001-x.md"),
            tree.0.join("main/agent/cr/done/TOOL-001-x.md"),
        )
        .unwrap();
        let after = reader.snapshot(NOW);
        assert_eq!(after.projects[0].seats[0].title, None);
        assert_eq!(after.projects[0].cr.as_ref().unwrap().in_progress, 0);
        tree.write(
            "state.json",
            r#"{"leader":null,"0":{"job_id":null,"git_hash":null,"session":null}}"#,
        );
        assert_eq!(reader.snapshot(NOW).projects[0].seats[0].status, "empty");
    }

    #[test]
    fn a_broken_project_does_not_hide_the_registry_error_rules() {
        let tree = Tree::new("errors");
        tree.write("state.json", "{");
        tree.write("cr/open/TOOL-001-x.md", "ok\n");
        fs::write(tree.0.join("main/agent/cr/todo/TOOL-002-x.md"), b"\xff").unwrap();
        let project = tree.reader().snapshot(NOW).projects.remove(0);
        let rows: Vec<(String, String)> = project
            .errors
            .iter()
            .map(|e| (e.source.clone(), e.message.clone()))
            .collect();
        assert_eq!(
            rows,
            vec![
                (
                    "state".to_string(),
                    "Cannot read a valid project state. Preserve the file.".to_string()
                ),
                (
                    "cr".to_string(),
                    "'utf-8' codec can't decode byte 0xff in position 0: invalid start byte"
                        .to_string()
                ),
            ]
        );
        assert!(project.cr.is_none() && project.decide.is_some());
        fs::write(tree.0.join("project.json"), "[]").unwrap();
        assert_eq!(
            tree.reader().snapshot(NOW).error.as_deref(),
            Some("The project registry must be an object of base entries.")
        );
    }
}
