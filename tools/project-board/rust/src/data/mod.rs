//! Reading the project facts: registry, state.json, CR and decision files, and run liveness.
//! (stub: the data layer fills this in)
pub mod dump;

use crate::model::{Liveness, Snapshot};
use std::path::PathBuf;

pub struct Reader {
    #[allow(dead_code)]
    config: Option<PathBuf>,
}

impl Reader {
    pub fn new(config: Option<PathBuf>) -> Self {
        Reader { config }
    }

    /// `model.snapshot()`. `now` is the Unix time (seconds) used for the elapsed times.
    pub fn snapshot(&mut self, _now: i64) -> Snapshot {
        Snapshot::default()
    }

    /// `model.liveness()`; it also refreshes the release holds the next `snapshot` shows.
    pub fn liveness(&mut self) -> Liveness {
        Liveness::new()
    }
}
