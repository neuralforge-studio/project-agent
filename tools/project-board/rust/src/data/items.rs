//! CR and decision files: the parts of the `project_item` rules that the sidebar needs. The format is owned by
//! `project_item.cr` and `project_item.decide` (headers, sections, code fences, the submission line), the
//! id rules by `project_item.kinds`, and the review wait by tools/project-board/README.md.
use super::pytext::{splitlines, strip};
use regex::Regex;
use std::collections::HashMap;
use std::sync::OnceLock;

fn re(cell: &'static OnceLock<Regex>, pattern: &str) -> &'static Regex {
    cell.get_or_init(|| Regex::new(pattern).unwrap())
}

const CR_ID: &str = r"[A-Z][A-Z0-9]*-\d{2,}";

fn cr_title() -> &'static Regex {
    static CELL: OnceLock<Regex> = OnceLock::new();
    re(&CELL, &format!(r"^#\s+({CR_ID}):\s+(\S.*?)\s*$"))
}

fn header() -> &'static Regex {
    static CELL: OnceLock<Regex> = OnceLock::new();
    re(&CELL, r"^-\s+([A-Z][A-Za-z ]*?):\s*(.*?)\s*$")
}

fn section() -> &'static Regex {
    static CELL: OnceLock<Regex> = OnceLock::new();
    re(&CELL, r"^##\s+(.+?)\s*$")
}

fn status_line() -> &'static Regex {
    static CELL: OnceLock<Regex> = OnceLock::new();
    re(&CELL, r"(?i)^-\s+\**Status\**\s*:")
}

fn submission() -> &'static Regex {
    static CELL: OnceLock<Regex> = OnceLock::new();
    re(&CELL, r"^- 제출 commit:\s*`?([0-9a-f]{40})\b")
}

fn hash_token() -> &'static Regex {
    static CELL: OnceLock<Regex> = OnceLock::new();
    re(&CELL, r"\b[0-9a-f]{7,40}\b")
}

fn cr_file_id() -> &'static Regex {
    static CELL: OnceLock<Regex> = OnceLock::new();
    re(&CELL, &format!(r"^({CR_ID})\b"))
}

fn related_start() -> &'static Regex {
    static CELL: OnceLock<Regex> = OnceLock::new();
    re(&CELL, &format!(r"^{CR_ID}"))
}

/// `cr.FENCE_RE` on one line: (fence character, run length, the rest of the line).
fn fence(line: &str) -> Option<(char, usize, &str)> {
    let trimmed = line.trim_start_matches(' ');
    if line.len() - trimmed.len() > 3 {
        return None;
    }
    let mark = trimmed.chars().next().filter(|c| *c == '`' || *c == '~')?;
    let run = trimmed.chars().take_while(|c| *c == mark).count();
    if run < 3 {
        None
    } else {
        Some((mark, run, &trimmed[run..]))
    }
}

/// `cr.outside_fence`: (index, line) of the lines outside code fences; the fence lines are skipped.
pub fn outside_fence<'a>(lines: &[&'a str]) -> Vec<(usize, &'a str)> {
    let mut open: Option<(char, usize)> = None;
    let mut kept = Vec::with_capacity(lines.len());
    for (index, line) in lines.iter().enumerate() {
        let marker = fence(line);
        match open {
            None => match marker {
                Some((mark, run, rest)) if mark == '~' || !rest.contains('`') => {
                    open = Some((mark, run))
                }
                _ => kept.push((index, *line)),
            },
            Some((mark, run)) => {
                if let Some((found, length, rest)) = marker {
                    if found == mark
                        && length >= run
                        && rest.trim_matches(|c| c == ' ' || c == '\t').is_empty()
                    {
                        open = None;
                    }
                }
            }
        }
    }
    kept
}

/// `cr.submitted_hash`: the hash of the last top-level `- 제출 commit: <40-hex>` line of a Result section.
pub fn submitted_hash(result: &str) -> Option<String> {
    let lines = splitlines(result);
    let mut found = None;
    for (_, line) in outside_fence(&lines) {
        if let Some(captures) = submission().captures(line) {
            found = Some(captures[1].to_string());
        }
    }
    found
}

/// `model.cited`: the Disposition names the commit by at least its first 7 characters.
fn cited(disposition: &str, commit: &str) -> bool {
    hash_token()
        .find_iter(disposition)
        .any(|token| commit.starts_with(token.as_str()))
}

/// The bodies of the wanted `## <name>` sections (`read.text_sections`; a repeated name keeps the last).
fn sections(lines: &[&str], wanted: &[&str]) -> HashMap<String, String> {
    let kept = outside_fence(lines);
    let heads: Vec<(usize, String)> = kept
        .iter()
        .filter(|(_, line)| line.starts_with("##"))
        .filter_map(|(index, line)| section().captures(line).map(|c| (*index, c[1].to_string())))
        .collect();
    let mut out = HashMap::new();
    for (position, (start, name)) in heads.iter().enumerate() {
        if !wanted.contains(&name.as_str()) {
            continue;
        }
        let end = heads
            .get(position + 1)
            .map(|head| head.0)
            .unwrap_or(lines.len());
        out.insert(
            name.clone(),
            strip(&lines[start + 1..end].join("\n")).to_string(),
        );
    }
    out
}

/// What the Board keeps of an in-progress CR.
#[derive(Clone, Debug, PartialEq)]
pub struct InProgress {
    pub id: String,
    pub title: String,
    pub review_wait: bool,
}

/// `path.stem`.
pub fn stem(name: &str) -> &str {
    match name.rfind('.') {
        Some(index) if index > 0 => &name[..index],
        _ => name,
    }
}

/// Parse the header block of CR text (`cr.parse_text`): (id, title, headers with the first value of each key).
fn parse_cr_header(lines: &[&str]) -> (Option<String>, Option<String>, HashMap<String, String>) {
    let (mut id, mut title) = (None, None::<String>);
    let mut headers: HashMap<String, String> = HashMap::new();
    let mut in_header = false;
    for (_, line) in outside_fence(lines) {
        if title.is_none() {
            if let Some(captures) = cr_title().captures(line) {
                id = Some(captures[1].to_string());
                title = Some(captures[2].to_string());
                in_header = true;
                continue;
            }
            if let Some(rest) = line.strip_prefix("# ") {
                title = Some(strip(rest).to_string());
                in_header = true;
                continue;
            }
        }
        if in_header {
            if let Some(captures) = header().captures(line) {
                headers
                    .entry(captures[1].to_string())
                    .or_insert_with(|| captures[2].to_string());
                continue;
            }
            if status_line().is_match(line) || strip(line).is_empty() {
                continue;
            }
            in_header = false;
        }
    }
    (id, title, headers)
}

/// `model._cr_item` for an in-progress CR (`file_stem` is the file name without its last suffix).
pub fn in_progress(text: &str, file_stem: &str) -> InProgress {
    let lines = splitlines(text);
    let (id, title, headers) = parse_cr_header(&lines);
    let parts = sections(&lines, &["Result", "Disposition"]);
    let result = parts.get("Result").map(String::as_str).unwrap_or("");
    let review_wait = if headers.get("Mode").map(String::as_str) == Some("read-only") {
        !strip(result).is_empty()
    } else {
        match submitted_hash(result) {
            Some(commit) => !cited(
                parts.get("Disposition").map(String::as_str).unwrap_or(""),
                &commit,
            ),
            None => false,
        }
    };
    InProgress {
        id: id.unwrap_or_else(|| file_stem.to_string()),
        title: title
            .filter(|title| !title.is_empty())
            .unwrap_or_else(|| file_stem.to_string()),
        review_wait,
    }
}

/// The headers of a decision that decide its stage.
#[derive(Clone, Debug, PartialEq)]
pub struct DecisionHeaders {
    pub outcome: Option<String>,
    pub related: Option<String>,
}

/// `decide.parse_text`, reduced to the headers `decision_stage` reads.
pub fn decision_headers(text: &str) -> DecisionHeaders {
    let lines = splitlines(text);
    let mut headers: HashMap<String, String> = HashMap::new();
    let mut titled = false;
    let mut in_header = false;
    for (_, line) in outside_fence(&lines) {
        if !titled && line.starts_with("# ") {
            titled = true;
            in_header = true;
            continue;
        }
        if in_header {
            if let Some(captures) = header().captures(line) {
                headers
                    .entry(captures[1].to_string())
                    .or_insert_with(|| captures[2].to_string());
                continue;
            }
            if status_line().is_match(line) || strip(line).is_empty() {
                continue;
            }
            in_header = false;
        }
    }
    DecisionHeaders {
        outcome: headers.remove("Outcome"),
        related: headers.remove("Related"),
    }
}

/// `store.file_id(CR, path)`: the CR ID that a file name starts with.
pub fn cr_file_id_of(name: &str) -> Option<&str> {
    cr_file_id()
        .captures(name)
        .map(|captures| captures.get(1).unwrap().as_str())
}

/// `decide.RELATED_CR_RE.findall(text)`: CR IDs that are not part of a longer word (`(?<![\w-])ID(?![\w-])`).
pub fn related_ids(text: &str) -> Vec<&str> {
    let is_word = |c: char| c.is_alphanumeric() || c == '_' || c == '-';
    let mut found = Vec::new();
    let mut at = 0;
    while at < text.len() {
        let rest = &text[at..];
        let c = rest.chars().next().unwrap();
        let blocked = text[..at].chars().next_back().is_some_and(is_word);
        if !blocked {
            if let Some(m) = related_start().find(rest) {
                let after = rest[m.end()..].chars().next();
                if !after.is_some_and(is_word) {
                    found.push(m.as_str());
                    at += m.end();
                    continue;
                }
            }
        }
        at += c.len_utf8();
    }
    found
}

/// `decide.decision_stage` of a confirmed (done) decision: 3 for 완료, 2 for 반영 중.
/// `cr_state` gives the directory state of a CR ID.
pub fn done_stage(
    headers: &DecisionHeaders,
    cr_state: impl Fn(&str) -> Option<&'static str>,
) -> usize {
    let withdrawn = headers.outcome.as_deref().and_then(|outcome| {
        outcome
            .split(super::pytext::is_space)
            .find(|part| !part.is_empty())
    }) == Some("withdrawn");
    if withdrawn {
        return 3;
    }
    let pending = related_ids(headers.related.as_deref().unwrap_or(""))
        .into_iter()
        .any(|id| !matches!(cr_state(id), Some("done") | Some("deferred")));
    if pending {
        2
    } else {
        3
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const SUBMIT: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const OTHER: &str = "cccccccccccccccccccccccccccccccccccccccc";

    #[test]
    fn the_submission_is_the_last_top_level_line_outside_fences() {
        // The cases of tools/project-board/tests/test_model.py::test_the_submission_is_the_last_submission_line.
        let cases: Vec<(String, Option<&str>)> = vec![
            ("".into(), None),
            (format!("- 제출 commit: `{SUBMIT}` (`cr/TOOL-001`)."), Some(SUBMIT)),
            (format!("- 제출 commit: {SUBMIT}"), Some(SUBMIT)),
            (format!("- 제출 commit: `{SUBMIT}`\n- 검증: `git diff {OTHER}..{SUBMIT}`\n- 비교 기준: `{OTHER}`"), Some(SUBMIT)),
            (format!("- 제출 commit: `{OTHER}`\n\n### 두 번째 제출\n\n- 제출 commit: `{SUBMIT}`"), Some(SUBMIT)),
            (format!("```\n- 제출 commit: {SUBMIT}\n```"), None),
            ("- 제출 commit: `abc1234`".into(), None),
            (format!("- 제출 commit: `{SUBMIT}`\n- 검증 입력:\n  ```md\n  - 제출 commit: {OTHER}\n  ```"), Some(SUBMIT)),
            (format!("- 제출 commit: `{SUBMIT}`\n~~~\n- 제출 commit: {OTHER}\n~~~"), Some(SUBMIT)),
            (format!("- 제출 commit: `{SUBMIT}`\n```\n~~~\n- 제출 commit: {OTHER}\n```"), Some(SUBMIT)),
            (format!("- 제출 commit: `{SUBMIT}`\n- 예시:\n  - 제출 commit: {OTHER}"), Some(SUBMIT)),
            (format!("- 제출 commit: {SUBMIT}\n````md\n```text\n- 제출 commit: {OTHER}\n```\n````\n"), Some(SUBMIT)),
            (format!("- 제출 commit: {SUBMIT}\n```md\n```python\n- 제출 commit: {OTHER}\n```\n"), Some(SUBMIT)),
            (format!("- 제출 commit: {OTHER}\n```md\nexample\n````  \n- 제출 commit: {SUBMIT}\n"), Some(SUBMIT)),
        ];
        for (result, expected) in cases {
            assert_eq!(submitted_hash(&result).as_deref(), expected, "{result}");
        }
    }

    fn cr(disposition: &str, result: &str, mode: Option<&str>) -> String {
        let mode = mode.map(|m| format!("- Mode: {m}\n")).unwrap_or_default();
        format!(
            "# TOOL-001: Title here\n\n- Opened: 2026-11-05\n{mode}\n## Disposition\n\n{disposition}\n\n## Result\n\n{result}\n"
        )
    }

    #[test]
    fn a_write_cr_waits_until_the_disposition_cites_its_submission() {
        // The cases of test_a_write_cr_waits_until_the_disposition_cites_its_submission.
        let result = format!("- 제출 commit: `{SUBMIT}`\n- 비교 기준: `{OTHER}`");
        let waiting = |disposition: String| {
            in_progress(&cr(&disposition, &result, None), "TOOL-001-x").review_wait
        };
        assert!(waiting("- 2026-11-05 leader: 판정합니다.".into()));
        assert!(!waiting(format!(
            "- 2026-11-05 leader: `{}` 검토, 수정 요청.",
            &SUBMIT[..12]
        )));
        assert!(!waiting(format!(
            "- 2026-11-05 leader: {} 인수.",
            &SUBMIT[..7]
        )));
        assert!(waiting(format!(
            "- 2026-11-05 leader: {} 인수.",
            &SUBMIT[..6]
        )));
        assert!(waiting(format!("- 2026-11-05 leader: {OTHER} 검토.")));
    }

    #[test]
    fn a_read_only_cr_waits_once_it_has_a_result() {
        assert!(!in_progress(&cr("", "  \n", Some("read-only")), "x").review_wait);
        assert!(in_progress(&cr("", "조사 결과입니다.", Some("read-only")), "x").review_wait);
    }

    #[test]
    fn id_and_title_come_from_the_title_line_or_the_file_name() {
        let item = in_progress(
            "# TOOL-001: Fix the thing  \n\n- Opened: x\n",
            "TOOL-001-fix",
        );
        assert_eq!(
            (item.id.as_str(), item.title.as_str()),
            ("TOOL-001", "Fix the thing")
        );
        let item = in_progress("# Just a title\n", "TOOL-002-stem");
        assert_eq!(
            (item.id.as_str(), item.title.as_str()),
            ("TOOL-002-stem", "Just a title")
        );
        let item = in_progress("no title\n", "TOOL-003-stem");
        assert_eq!(
            (item.id.as_str(), item.title.as_str()),
            ("TOOL-003-stem", "TOOL-003-stem")
        );
        assert_eq!(stem("a.b.md"), "a.b");
        assert_eq!(stem(".md"), ".md");
    }

    #[test]
    fn headers_keep_the_first_value_and_stop_at_the_first_other_line() {
        let text = "# D-20261105-01: Q\n\n- Opened: 2026-11-05 09:30\n- Outcome: withdrawn\n- Outcome: decided A\n- Related: TOOL-001\n- Status: x\nbody\n- Related: TOOL-002\n";
        assert_eq!(
            decision_headers(text),
            DecisionHeaders {
                outcome: Some("withdrawn".into()),
                related: Some("TOOL-001".into())
            }
        );
        // A header line inside a fence before the block ends is not a header.
        let fenced = "# D-20261105-01: Q\n\n```\n- Outcome: withdrawn\n```\n- Related: TOOL-001\n";
        assert_eq!(decision_headers(fenced).outcome, None);
    }

    #[test]
    fn related_ids_are_not_part_of_longer_words() {
        // RELATED_CR_RE.findall("TOOL-002, SESSION-020 X-1 aTOOL-003 TOOL-004x TOOL-005-1 (TOOL-006)")
        assert_eq!(
            related_ids("TOOL-002, SESSION-020 X-1 aTOOL-003 TOOL-004x TOOL-005-1 (TOOL-006)"),
            vec!["TOOL-002", "SESSION-020", "TOOL-006"]
        );
    }

    #[test]
    fn file_ids_need_a_word_boundary() {
        assert_eq!(
            cr_file_id_of("BOARD-018-board-sidebar.md"),
            Some("BOARD-018")
        );
        assert_eq!(cr_file_id_of("BOARD-018.md"), Some("BOARD-018"));
        assert_eq!(cr_file_id_of("BOARD-018x.md"), None);
        assert_eq!(cr_file_id_of("board-018.md"), None);
        assert_eq!(cr_file_id_of("B-1.md"), None);
    }

    #[test]
    fn a_withdrawn_decision_is_complete_and_a_missing_cr_is_pending() {
        let headers = |outcome: Option<&str>, related: Option<&str>| DecisionHeaders {
            outcome: outcome.map(String::from),
            related: related.map(String::from),
        };
        let state = |id: &str| if id == "TOOL-001" { Some("done") } else { None };
        assert_eq!(
            done_stage(&headers(Some("withdrawn"), Some("TOOL-009")), state),
            3
        );
        assert_eq!(
            done_stage(&headers(Some("decided A"), Some("TOOL-001")), state),
            3
        );
        assert_eq!(
            done_stage(
                &headers(Some("decided A"), Some("TOOL-001 TOOL-002")),
                state
            ),
            2
        );
        assert_eq!(done_stage(&headers(Some("decided A"), None), state), 3);
    }
}
