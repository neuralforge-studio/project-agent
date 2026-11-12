//! A project's cron jobs as the sidebar needs them (BOARD-027): how many there are and when the nearest runs next.
//!
//! The rules are those of `agent_session.cron` (`Schedule`, `split`, `_parse_section`; docs/project-team/spec.md,
//! cron), which is the one owner. This module follows them and two tests keep it to them: the hand-written cases of
//! `tools/agent-session/tests/fixtures/cron_next_run.json` (read in place, not copied) and
//! `tools/project-board/tests/test_rust_cron.py`, which gives the Python and the Rust reader the same crontabs.
//! Times are local wall-clock minutes with no zone (`Civil`), as in the Python code.
use regex::Regex;
use std::collections::BTreeSet;
use std::sync::OnceLock;

/// How far `next_run` looks for a match before it gives up (`cron.SEARCH_YEARS`).
const SEARCH_YEARS: i32 = 8;

/// A local wall-clock minute. Seconds are dropped: a rule never needs them.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct Civil {
    pub year: i32,
    pub month: u32,
    pub day: u32,
    pub hour: u32,
    pub minute: u32,
}

/// Days since 1970-01-01 of a proleptic Gregorian date (H. Hinnant's `days_from_civil`).
fn days_from_civil(year: i32, month: u32, day: u32) -> i64 {
    let y = i64::from(year) - i64::from(month <= 2);
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let mp = (i64::from(month) + 9) % 12;
    let doy = (153 * mp + 2) / 5 + i64::from(day) - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

fn civil_from_days(days: i64) -> (i32, u32, u32) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let month = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    let year = (yoe + era * 400 + i64::from(month <= 2)) as i32;
    (year, month, day)
}

impl Civil {
    pub fn minutes(&self) -> i64 {
        days_from_civil(self.year, self.month, self.day) * 1440 + i64::from(self.hour) * 60 + i64::from(self.minute)
    }

    pub fn from_minutes(minutes: i64) -> Civil {
        let (year, month, day) = civil_from_days(minutes.div_euclid(1440));
        let rest = minutes.rem_euclid(1440);
        Civil { year, month, day, hour: (rest / 60) as u32, minute: (rest % 60) as u32 }
    }

    /// `YYYY-MM-DDTHH:MM` with optional `:SS` (the form of `next_run` in `cron ls`). None when it is not a real time.
    pub fn parse(text: &str) -> Option<Civil> {
        let (date, time) = text.split_once('T')?;
        let mut date = date.split('-');
        let (year, month, day) = (date.next()?.parse::<i32>().ok()?, date.next()?.parse::<u32>().ok()?, date.next()?.parse::<u32>().ok()?);
        let mut time = time.split(':');
        let (hour, minute) = (time.next()?.parse::<u32>().ok()?, time.next()?.parse::<u32>().ok()?);
        let seconds_ok = time.next().map_or(true, |s| s.parse::<u32>().map_or(false, |s| s < 60));
        let valid = (1..=12).contains(&month) && hour < 24 && minute < 60 && seconds_ok && time.next().is_none() && date.next().is_none();
        let civil = Civil { year, month, day, hour, minute };
        // a day that the month does not have comes back as another date
        (valid && day >= 1 && Civil::from_minutes(civil.minutes()) == civil).then_some(civil)
    }

    /// The local time of a Unix time in seconds (`localtime_r`); the sidebar's "now".
    pub fn local(unix_seconds: i64) -> Civil {
        // SAFETY: `tm` is written by localtime_r and read only after it returns a pointer.
        unsafe {
            let time = unix_seconds as libc::time_t;
            let mut tm: libc::tm = std::mem::zeroed();
            if libc::localtime_r(&time, &mut tm).is_null() {
                return Civil::from_minutes(unix_seconds.div_euclid(60));
            }
            Civil { year: tm.tm_year + 1900, month: (tm.tm_mon + 1) as u32, day: tm.tm_mday as u32, hour: tm.tm_hour as u32, minute: tm.tm_min as u32 }
        }
    }

    pub fn now() -> Civil {
        let seconds = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0);
        Civil::local(seconds)
    }

    /// `YYYY-MM-DDTHH:MM`, the form of `next_run` in `agent-session cron ls`.
    pub fn iso(&self) -> String {
        format!("{:04}-{:02}-{:02}T{:02}:{:02}", self.year, self.month, self.day, self.hour, self.minute)
    }

    /// 0 for Sunday ... 6 for Saturday.
    fn weekday(&self) -> u32 {
        // 1970-01-01 was a Thursday
        (days_from_civil(self.year, self.month, self.day) + 4).rem_euclid(7) as u32
    }
}

/// A five-field cron expression (`agent_session.cron.Schedule`).
#[derive(Clone, Debug, PartialEq)]
pub struct Schedule {
    minutes: BTreeSet<u32>,
    hours: BTreeSet<u32>,
    days: BTreeSet<u32>,
    months: BTreeSet<u32>,
    weekdays: BTreeSet<u32>,
    day_star: bool,
    weekday_star: bool,
}

const FIELDS: [(&str, u32, u32); 5] = [("minute", 0, 59), ("hour", 0, 23), ("day of month", 1, 31), ("month", 1, 12), ("day of week", 0, 7)];

fn ascii_number(text: &str) -> Option<u32> {
    (!text.is_empty() && text.bytes().all(|b| b.is_ascii_digit())).then(|| text.parse().ok()).flatten()
}

fn field(low: u32, high: u32, text: &str) -> Result<BTreeSet<u32>, ()> {
    let mut values = BTreeSet::new();
    for item in text.split(',') {
        let (base, step) = match item.split_once('/') {
            Some((base, step)) => (base, Some(step)),
            None => (item, None),
        };
        let step = match step {
            Some(step) => match ascii_number(step) {
                Some(step) if step >= 1 => Some(step),
                _ => return Err(()),
            },
            None => None,
        };
        let (first, last) = match base.split_once('-') {
            Some((first, last)) => (first, Some(last)),
            None => (base, None),
        };
        let (start, stop) = if base == "*" {
            (low, high)
        } else {
            let start = ascii_number(first).ok_or(())?;
            let stop = match last {
                Some(last) => ascii_number(last).ok_or(())?,
                None if step.is_some() => high,
                None => start,
            };
            (start, stop)
        };
        if !(low <= start && start <= stop && stop <= high) {
            return Err(());
        }
        values.extend((start..=stop).step_by(step.unwrap_or(1) as usize));
    }
    Ok(values)
}

impl Schedule {
    /// None when the text is not a schedule that `agent_session.cron.Schedule` accepts.
    pub fn parse(text: &str) -> Option<Schedule> {
        let parts: Vec<&str> = text.split_whitespace().collect();
        if parts.len() != 5 {
            return None;
        }
        let mut sets = Vec::new();
        for ((_, low, high), part) in FIELDS.iter().zip(&parts) {
            sets.push(field(*low, *high, part).ok()?);
        }
        let weekdays = sets[4].iter().map(|value| value % 7).collect();
        Some(Schedule {
            minutes: sets[0].clone(),
            hours: sets[1].clone(),
            days: sets[2].clone(),
            months: sets[3].clone(),
            weekdays,
            day_star: parts[2].starts_with('*'),
            weekday_star: parts[4].starts_with('*'),
        })
    }

    fn day_matches(&self, day: &Civil) -> bool {
        let month_day = self.days.contains(&day.day);
        let week_day = self.weekdays.contains(&day.weekday());
        if self.day_star || self.weekday_star {
            month_day && week_day
        } else {
            month_day || week_day
        }
    }

    /// The first minute strictly after `after` that matches, or None within `SEARCH_YEARS` years.
    pub fn next_run(&self, after: &Civil) -> Option<Civil> {
        let moment = after.minutes() + 1;
        let first_day = moment.div_euclid(1440);
        let start = Civil::from_minutes(moment);
        let limit = Civil { year: start.year + SEARCH_YEARS, ..start }.minutes();
        let mut day = first_day;
        while day * 1440 < limit {
            let date = Civil::from_minutes(day * 1440);
            if self.months.contains(&date.month) && self.day_matches(&date) {
                for hour in &self.hours {
                    for minute in &self.minutes {
                        let candidate = day * 1440 + i64::from(*hour) * 60 + i64::from(*minute);
                        if candidate >= moment {
                            return Some(Civil::from_minutes(candidate));
                        }
                    }
                }
            }
            day += 1;
        }
        None
    }
}

/// The nearest next run of these schedules (texts that `Schedule::parse` accepts); None when none runs again.
pub fn nearest(schedules: &[String], now: &Civil) -> Option<Civil> {
    schedules.iter().filter_map(|text| Schedule::parse(text)).filter_map(|schedule| schedule.next_run(now)).min()
}

/// The time from `now` to `next` as one unit, the largest that fits and rounded down: `Nd` from 1440 minutes, `Nh` from
/// 60, else `Nm`. `next` is a whole minute and `now` is taken as the minute it is in, so 30 seconds before `next` is
/// `1m` (docs/project-board-tui-plan.md section 3).
pub fn remaining(next: &Civil, now: &Civil) -> String {
    let minutes = (next.minutes() - now.minutes()).max(0);
    if minutes >= 1440 {
        format!("{}d", minutes / 1440)
    } else if minutes >= 60 {
        format!("{}h", minutes / 60)
    } else {
        format!("{minutes}m")
    }
}

fn begin(name: &str) -> String {
    format!("# >>> project-agent: {name} >>>")
}

fn end(name: &str) -> String {
    format!("# <<< project-agent: {name} <<<")
}

fn job_comment() -> &'static Regex {
    static COMMENT: OnceLock<Regex> = OnceLock::new();
    COMMENT.get_or_init(|| Regex::new(r"^# job [a-z][a-z0-9-]*:").unwrap())
}

/// Why a project's section cannot be read; the sidebar shows it as a tooltip.
pub const BROKEN: &str = "crontab의 이 project 구역이 깨졌습니다. 직접 고치세요";

/// The schedules of the jobs in `name`'s section of the crontab `text`, in order; empty without a section. Err(`BROKEN`) when
/// the section is incomplete or repeated, holds a line that is not a job, or a job has no valid schedule
/// (`agent_session.cron.split`, which is `cron_invalid`).
pub fn project_schedules(text: &str, name: &str) -> Result<Vec<String>, String> {
    if name.is_empty() || name.contains('\n') || name.contains('\r') {
        return Err(BROKEN.into());
    }
    let mut lines: Vec<&str> = text.split('\n').collect();
    if lines.last() == Some(&"") {
        lines.pop();
    }
    let (begin, end) = (begin(name), end(name));
    let starts: Vec<usize> = lines.iter().enumerate().filter(|(_, line)| **line == begin).map(|(n, _)| n).collect();
    let stops: Vec<usize> = lines.iter().enumerate().filter(|(_, line)| **line == end).map(|(n, _)| n).collect();
    if starts.is_empty() && stops.is_empty() {
        return Ok(Vec::new());
    }
    if starts.len() != 1 || stops.len() != 1 || stops[0] < starts[0] {
        return Err(BROKEN.into());
    }
    let mut schedules = Vec::new();
    let mut pending = false;
    for line in &lines[starts[0] + 1..stops[0]] {
        if line.trim().is_empty() {
            continue;
        }
        if job_comment().is_match(line) {
            if pending {
                return Err(BROKEN.into());
            }
            pending = true;
            continue;
        }
        if !pending || line.trim_start().starts_with('#') {
            return Err(BROKEN.into());
        }
        let fields: Vec<&str> = line.split_whitespace().collect();
        if fields.len() < 6 {
            return Err(BROKEN.into());
        }
        let schedule = fields[..5].join(" ");
        if Schedule::parse(&schedule).is_none() {
            return Err(BROKEN.into());
        }
        schedules.push(schedule);
        pending = false;
    }
    if pending {
        return Err(BROKEN.into());
    }
    Ok(schedules)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    fn civil(text: &str) -> Civil {
        Civil::parse(text).unwrap_or_else(|| panic!("{text}"))
    }

    fn fixture(relative: &str) -> Value {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join(relative);
        serde_json::from_str(&std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))).unwrap()
    }

    #[test]
    fn the_hand_written_next_runs_of_agent_session_come_out() {
        let cases = fixture("../../agent-session/tests/fixtures/cron_next_run.json");
        let cases = cases["next_run"].as_array().unwrap();
        assert!(cases.len() >= 16);
        for case in cases {
            let schedule = Schedule::parse(case["schedule"].as_str().unwrap()).unwrap_or_else(|| panic!("{case}"));
            let next = schedule.next_run(&civil(case["after"].as_str().unwrap()));
            assert_eq!(next, Some(civil(case["next"].as_str().unwrap())), "{case}");
        }
    }

    #[test]
    fn every_invalid_schedule_of_agent_session_is_refused() {
        let cases = fixture("../../agent-session/tests/fixtures/cron_next_run.json");
        let invalid = cases["invalid"].as_array().unwrap();
        assert!(invalid.len() >= 15);
        for text in invalid {
            assert!(Schedule::parse(text.as_str().unwrap()).is_none(), "{text}");
        }
    }

    #[test]
    fn a_schedule_that_never_matches_has_no_next_run() {
        // February 30th does not exist
        let never = Schedule::parse("0 0 30 2 *").unwrap();
        assert_eq!(never.next_run(&civil("2026-11-12T10:00")), None);
        assert_eq!(nearest(&["0 0 30 2 *".into()], &civil("2026-11-12T10:00")), None);
    }

    #[test]
    fn the_nearest_of_several_schedules_and_the_remaining_time_in_one_unit() {
        let now = civil("2026-11-12T10:00");
        let schedules = vec!["0 12 * * *".to_string(), "13,43 * * * *".to_string(), "0 0 1 1 *".to_string()];
        assert_eq!(nearest(&schedules, &now), Some(civil("2026-11-12T10:13")));
        assert_eq!(remaining(&civil("2026-11-12T10:13"), &now), "13m");
    }

    #[test]
    fn the_remaining_time_follows_the_hand_written_cases_of_the_board_tests() {
        let cases = fixture("../tests/fixtures/cron_remaining.json");
        let cases = cases["cases"].as_array().unwrap();
        assert!(cases.len() >= 7);
        for case in cases {
            let (now, next) = (civil(case["now"].as_str().unwrap()), civil(case["next"].as_str().unwrap()));
            assert_eq!(remaining(&next, &now), case["text"].as_str().unwrap(), "{case}");
        }
    }

    #[test]
    fn a_civil_time_goes_through_minutes_and_back_across_month_year_and_leap_days() {
        for text in ["1970-01-01T00:00", "2026-11-12T23:59", "2028-02-29T00:00", "2100-03-01T12:30", "2027-12-31T23:59"] {
            let time = civil(text);
            assert_eq!(Civil::from_minutes(time.minutes()), time);
        }
        assert_eq!(civil("2026-11-12T10:00").weekday(), 4); // a Thursday
        assert_eq!(civil("2028-02-29T00:00").minutes() + 1440, civil("2028-03-01T00:00").minutes());
        assert_eq!(Civil::parse("2026-02-30T10:00"), None);
        assert_eq!(Civil::parse("2026-11-12T24:00"), None);
        assert_eq!(Civil::parse("2026-11-12T10:00:45"), Some(civil("2026-11-12T10:00")));
        assert_eq!(Civil::parse("nonsense"), None);
    }

    const CRONTAB: &str = "MAILTO=me\n0 1 * * * backup\n\n# >>> project-agent: a >>>\n# job check: look at things\n13,43 * * * * /x/agent-session check --project a >/dev/null 2>&1\n# job nightly: n\n0 3 * * * run\n# <<< project-agent: a <<<\n# >>> project-agent: b >>>\n# <<< project-agent: b <<<\n# >>> project-agent: broken >>>\n# job x: y\n";

    #[test]
    fn sections_are_read_per_project_and_a_user_line_outside_them_is_not_a_job() {
        assert_eq!(project_schedules(CRONTAB, "a").unwrap(), ["13,43 * * * *", "0 3 * * *"]);
        assert_eq!(project_schedules(CRONTAB, "b").unwrap(), Vec::<String>::new());
        assert_eq!(project_schedules(CRONTAB, "none").unwrap(), Vec::<String>::new());
        assert_eq!(project_schedules(CRONTAB, "broken").unwrap_err(), BROKEN);
        assert_eq!(project_schedules("", "a").unwrap(), Vec::<String>::new());
    }
}
