//! The facts the sidebar shows (what `tools/project-board/project_board/model.py` calls a snapshot, reduced to
//! what the sidebar draws). `data` produces these; `ui` and `app` consume them. The JSON form of these types is
//! the interface of the equivalence test (`tools/project-board/tests/test_rust_equivalence.py`).
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// One Worker seat of a project (`model.project_view()["seats"]`).
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Default)]
pub struct Seat {
    pub index: usize,
    pub job_id: Option<String>,
    /// empty | pending | release_pending | reviewing | review_wait | working
    pub status: String,
    /// A session is published for the seat (`seat["session"]`).
    pub session: bool,
    pub host: Option<String>,
    pub path: String,
    pub session_id: Option<String>,
    /// Seconds since the session was published; None without a session or without `connected_at`.
    pub elapsed: Option<i64>,
    /// Title of the seat's in-progress CR.
    pub title: Option<String>,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Default)]
pub struct Leader {
    pub elapsed: Option<i64>,
}

/// CR counts of the three shown states.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Default)]
pub struct CrCounts {
    pub open: usize,
    pub todo: usize,
    #[serde(rename = "in-progress")]
    pub in_progress: usize,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Default)]
pub struct Decide {
    /// Decisions in the `open` directory.
    pub open: usize,
    /// Decisions by `display_state`: 결정 대기, 답변 접수, 반영 중, 완료.
    pub stages: [usize; 4],
}

impl Decide {
    /// Decisions whose stage is not 완료 (the popup lists these; the D button is enabled when there are any).
    pub fn visible(&self) -> usize {
        self.stages[0] + self.stages[1] + self.stages[2]
    }
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Default)]
pub struct ProjectError {
    /// state | cr | decide
    pub source: String,
    pub message: String,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Default)]
pub struct Project {
    pub id: String,
    /// None when the CR tree is not registered or unreadable (an `errors` entry with source `cr` tells which).
    pub cr: Option<CrCounts>,
    /// None when the decision tree is not registered or unreadable.
    pub decide: Option<Decide>,
    pub errors: Vec<ProjectError>,
    /// None without a Leader in state.json.
    pub leader: Option<Leader>,
    pub seats: Vec<Seat>,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Default)]
pub struct Snapshot {
    /// The registry could not be read: `error.message` (`snapshot()["error"]["message"]`); `projects` is empty.
    pub error: Option<String>,
    pub projects: Vec<Project>,
}

/// One slot's verdict: the session it judged and `alive` | `stopped` | `unknown`.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
pub struct SlotLive {
    pub session_id: String,
    pub state: String,
}

/// Per project: slot (`leader` or the seat number as text) -> verdict. A project whose liveness raised an error
/// other than `state_not_found` is an empty map (the sidebar never shows the error).
pub type Liveness = BTreeMap<String, BTreeMap<String, SlotLive>>;

/// One project's cron jobs (BOARD-027): the schedule of each job in the project's crontab section, or why the section
/// could not be read (the crontab cannot be run, or this project's section is broken). A project that is not in a
/// `CronView` has not been read yet.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Default)]
pub struct CronEntry {
    pub schedules: Vec<String>,
    pub error: Option<String>,
}

/// Per project: its cron jobs, from one `crontab -l` for all of them.
pub type CronView = BTreeMap<String, CronEntry>;
