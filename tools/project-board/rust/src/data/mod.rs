//! Reading the project facts: registry, state.json, CR and decision files, and run liveness. The rules are those
//! of the Python model (`project_board.model`, `agent_session`, `project_item`); the equivalence test
//! (`tools/project-board/tests/test_rust_equivalence.py`) holds the two to the same answers on the same files.
//!
//! One `Reader` is shared by the threads of the sidebar: `snapshot` (every 2 seconds) and `liveness` (every 10
//! seconds, and slow when it waits for a remote seat) lock separate state, and meet only in the release holds
//! that `liveness` writes and `snapshot` reads.
mod crontab;
pub mod dump;
mod err;
mod exec;
mod items;
mod json;
pub mod jump;
mod live;
mod par;
mod process;
mod pytext;
mod read;
mod registry;
mod stamp;
mod state;
mod tmux;

use crate::model::{CronView, Liveness, Snapshot};
use registry::Project;
use stamp::{mtime_ns, now_ns, settled, sig_of, Sig};
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

pub use stamp::parse_utc;

/// The loaded registry, kept while the registry file is the same file with the same size and modification time.
type KeptRegistry = (PathBuf, Sig, Arc<Vec<Project>>);

pub struct Reader {
    config: Option<PathBuf>,
    threads: usize,
    registry: Mutex<Option<KeptRegistry>>,
    caches: Mutex<read::Caches>,
    releases: Mutex<HashMap<String, HashSet<String>>>,
}

impl Reader {
    /// `config` is the registry file; None looks in the standard places. Files are opened on 32 threads on a first
    /// read (`PROJECT_BOARD_THREADS` changes that).
    pub fn new(config: Option<PathBuf>) -> Self {
        let threads = std::env::var("PROJECT_BOARD_THREADS")
            .ok()
            .and_then(|n| n.parse().ok())
            .filter(|n| *n > 0)
            .unwrap_or(32);
        Reader {
            config,
            threads,
            registry: Mutex::new(None),
            caches: Mutex::new(read::Caches::default()),
            releases: Mutex::new(HashMap::new()),
        }
    }

    /// `model._registry(config)`: `load_registry`, reused while the registry file is unchanged.
    fn registry(&self) -> Result<Arc<Vec<Project>>, String> {
        let path = registry::registry_path(self.config.as_deref()).map_err(|e| e.message)?;
        let Ok(meta) = std::fs::metadata(&path) else {
            return registry::load_registry(&path)
                .map(Arc::new)
                .map_err(|e| e.message); // it reports what is wrong
        };
        let signature = sig_of(&meta);
        let mut kept = self.registry.lock().unwrap();
        if let Some((kept_path, kept_sig, projects)) = kept.as_ref() {
            if *kept_path == path && *kept_sig == signature {
                return Ok(projects.clone());
            }
        }
        let projects = Arc::new(registry::load_registry(&path).map_err(|e| e.message)?);
        *kept = if settled(mtime_ns(&meta), now_ns()) {
            Some((path, signature, projects.clone()))
        } else {
            None
        };
        Ok(projects)
    }

    /// `model.snapshot()`. `now` is the Unix time (seconds) used for the elapsed times.
    pub fn snapshot(&self, now: i64) -> Snapshot {
        let projects = match self.registry() {
            Ok(projects) => projects,
            Err(message) => {
                return Snapshot {
                    error: Some(message),
                    projects: Vec::new(),
                }
            }
        };
        let releases = self.releases.lock().unwrap().clone();
        let mut caches = self.caches.lock().unwrap();
        Snapshot {
            error: None,
            projects: read::snapshot(&projects, &mut caches, &releases, now, self.threads),
        }
    }

    /// `model.liveness()`; it also refreshes the release holds the next `snapshot` shows. A registry that cannot be
    /// read gives an empty result and leaves the holds as they were.
    pub fn liveness(&self) -> Liveness {
        let Ok(projects) = self.registry() else {
            return Liveness::new();
        };
        let judged = live::judge(&projects, self.config.as_deref());
        *self.releases.lock().unwrap() = judged.releases;
        judged.liveness
    }

    /// Every project's cron jobs from one `crontab -l` (BOARD-027). A registry that cannot be read gives an empty view.
    pub fn cron(&self) -> CronView {
        let Ok(projects) = self.registry() else {
            return CronView::new();
        };
        let ids: Vec<&str> = projects.iter().map(|project| project.id.as_str()).collect();
        crontab::view(crontab::read(), &ids)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn assert_send_sync<T: Send + Sync>() {}

    #[test]
    fn a_reader_can_be_shared_between_threads() {
        assert_send_sync::<Reader>();
    }
}
