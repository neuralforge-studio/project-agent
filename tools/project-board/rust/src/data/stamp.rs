//! File signatures and times. A file system stamps a change with a clock that ticks coarsely, so a stamp that is
//! younger than `SETTLE_NS` is not trusted (the rule of `model._unchanged` and `model._cached`).
use std::fs::Metadata;
use std::os::unix::fs::MetadataExt;
use std::time::{SystemTime, UNIX_EPOCH};

/// (modification time in ns, size, inode): what a read of a file is kept under.
pub type Sig = (i64, u64, u64);

pub const SETTLE_NS: i64 = 2_000_000_000;

pub fn mtime_ns(meta: &Metadata) -> i64 {
    meta.mtime() * 1_000_000_000 + meta.mtime_nsec()
}

pub fn sig_of(meta: &Metadata) -> Sig {
    (mtime_ns(meta), meta.size(), meta.ino())
}

pub fn now_ns() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos() as i64)
        .unwrap_or(0)
}

/// Whether a stamp is old enough to be trusted at `now`.
pub fn settled(stamp_ns: i64, now: i64) -> bool {
    now - stamp_ns >= SETTLE_NS
}

/// Days since 1970-01-01 of a civil date (proleptic Gregorian).
fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    let y = if month <= 2 { year - 1 } else { year };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * (if month > 2 { month - 3 } else { month + 9 }) + 2) / 5 + day - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

/// Unix seconds of `YYYY-MM-DDTHH:MM:SSZ` (the connection time format, UTC); None for any other text.
pub fn parse_utc(text: &str) -> Option<i64> {
    let bytes = text.as_bytes();
    if bytes.len() != 20
        || bytes[4] != b'-'
        || bytes[7] != b'-'
        || bytes[10] != b'T'
        || bytes[13] != b':'
        || bytes[16] != b':'
        || bytes[19] != b'Z'
    {
        return None;
    }
    let number = |from: usize, to: usize| -> Option<i64> {
        let part = text.get(from..to)?;
        if part.bytes().all(|b| b.is_ascii_digit()) {
            part.parse().ok()
        } else {
            None
        }
    };
    let (year, month, day) = (number(0, 4)?, number(5, 7)?, number(8, 10)?);
    let (hour, minute, second) = (number(11, 13)?, number(14, 16)?, number(17, 19)?);
    Some(days_from_civil(year, month, day) * 86400 + hour * 3600 + minute * 60 + second)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn utc_times_equal_python() {
        // datetime(2026, 11, 5, 10, 30, tzinfo=utc).timestamp() == 1793874600; 1970-01-01 is 0; 2024-02-29T00:00:00Z is 1709164800.
        assert_eq!(parse_utc("2026-11-05T10:30:00Z"), Some(1793874600));
        assert_eq!(parse_utc("1970-01-01T00:00:00Z"), Some(0));
        assert_eq!(parse_utc("2024-02-29T00:00:00Z"), Some(1709164800));
        assert_eq!(parse_utc("2026-11-05 10:30:00Z"), None);
    }
}
