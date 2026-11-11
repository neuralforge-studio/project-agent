"""A project's cron jobs: one marked section of the user's crontab per project (SESSION-015, spec 7 `cron`).

The crontab is the one copy of the jobs. This module reads and rewrites only the section of the selected
project; every other line (the user's own jobs, other projects' sections) is kept byte for byte. A section is

    # >>> project-agent: NAME >>>
    # job ID: description
    M H DOM MON DOW command
    # <<< project-agent: NAME <<<

`%` in a command is written `\\%`, the way cron wants it. The schedule rules (`Schedule`, `next_run`) are the
one owner of "when does a job run next"; other readers of the crontab (the Board's sidebar) follow them and
keep to `tests/fixtures/cron_next_run.json`.

Dependency direction: `lifecycle` imports this module for the check job it ensures when the Leader starts;
this module imports `errors`, `state` (the lock) and `watch` (`Cron` is the command, on the authorization of
`Watch`) and never `lifecycle`. `watch` imports it only inside the function that keeps a check run. It starts
only the `crontab` command found on PATH, so a test replaces it with a shim.
"""

import datetime as dt
import re
import shlex
import subprocess
import time
from pathlib import Path

from .errors import SessionError
from .state import locked
from .watch import Watch

CHECK_ID = "check"                     # the project's check job (agent-session check)
CHECK_SCHEDULE = "13,43 * * * *"       # every 30 minutes, off :00 and :30
CHECK_DESCRIPTION = "정체한 Worker·Leader와 Leader가 처리할 일을 점검합니다(agent-session check)"
JOB_ID = re.compile(r"[a-z][a-z0-9-]{0,31}")
RETRIES = 5                            # read-modify-write attempts when another editor changed the crontab
COMMAND_TIMEOUT = 30                   # seconds one `crontab` process may take
SEARCH_YEARS = 8                       # how far `next_run` looks for a match before it gives up
NO_CRONTAB = re.compile(r"no crontab for", re.I)

_FIELDS = (("minute", 0, 59), ("hour", 0, 23), ("day of month", 1, 31), ("month", 1, 12), ("day of week", 0, 7))


def _invalid(message, **details):
    return SessionError("cron_invalid", message, 2, details)


# ---------------------------------------------------------------- schedule

class Schedule:
    """A five-field cron expression: numbers, `*`, lists, ranges and steps (`*/n`, `a-b/n`).

    Names (`mon`, `jan`) and `@` macros are refused, so every reader needs only the number rules. Day of week
    is 0-7 with 0 and 7 for Sunday. When both day of month and day of week are restricted a day matches if
    either does (the classic cron rule), otherwise both must match."""

    def __init__(self, text):
        self.text = " ".join(str(text).split())
        parts = self.text.split(" ")
        if len(parts) != 5:
            raise _invalid("A schedule has five fields: minute hour day-of-month month day-of-week.", schedule=self.text)
        self.sets, self.star = [], []
        for (name, low, high), part in zip(_FIELDS, parts):
            values = self._field(name, low, high, part)
            if name == "day of week":
                values = {value % 7 for value in values}
            self.sets.append(values)
            self.star.append(part.startswith("*"))

    def _field(self, name, low, high, text):
        values = set()
        for item in text.split(","):
            base, slash, step = item.partition("/")
            if slash and (not step.isdigit() or int(step) < 1):
                raise _invalid(f"Bad step in the {name} field.", schedule=self.text)
            first, dash, last = base.partition("-")
            if base == "*":
                start, stop = low, high
            elif first.isdigit() and (last.isdigit() if dash else not last):
                start = int(first)
                stop = int(last) if dash else (high if slash else start)
            else:
                raise _invalid(f"Use numbers, *, lists, ranges and steps in the {name} field.", schedule=self.text)
            if not low <= start <= stop <= high:
                raise _invalid(f"The {name} field must stay within {low}-{high}.", schedule=self.text)
            values.update(range(start, stop + 1, int(step) if slash else 1))
        return values

    def _day_matches(self, day):
        month_day = day.day in self.sets[2]
        week_day = (day.weekday() + 1) % 7 in self.sets[4]
        if self.star[2] or self.star[4]:
            return month_day and week_day
        return month_day or week_day

    def next_run(self, after):
        """The first minute strictly after `after` (a naive local `datetime`) that matches, or None."""
        moment = after.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
        limit = moment.replace(year=moment.year + SEARCH_YEARS)
        minutes, hours = sorted(self.sets[0]), sorted(self.sets[1])
        day = moment.replace(hour=0, minute=0)
        while day < limit:
            if day.month in self.sets[3] and self._day_matches(day):
                for hour in hours:
                    for minute in minutes:
                        candidate = day.replace(hour=hour, minute=minute)
                        if candidate >= moment:
                            return candidate
            day += dt.timedelta(days=1)
        return None


def next_run(schedule, after):
    return Schedule(schedule).next_run(after)


# ---------------------------------------------------------------- crontab text

_BEGIN = ("# >>> project-agent: ", " >>>")
_END = ("# <<< project-agent: ", " <<<")


def _begin(name):
    return f"{_BEGIN[0]}{name}{_BEGIN[1]}"


def _end(name):
    return f"{_END[0]}{name}{_END[1]}"


_JOB_COMMENT = re.compile(r"^# job ([a-z][a-z0-9-]*):[ ]?(.*)$")


def _escape(command):
    return command.replace("%", "\\%")


def _unescape(command):
    return command.replace("\\%", "%")


def _parse_section(name, lines):
    jobs, pending = [], None
    for line in lines:
        if not line.strip():
            continue
        comment = _JOB_COMMENT.match(line)
        if comment:
            if pending:
                raise _invalid("A job comment is not followed by its schedule line.", project=name)
            pending = comment.groups()
            continue
        if pending is None or line.lstrip().startswith("#"):
            raise _invalid("The project's crontab section holds a line that is not a job.", project=name, line=line)
        fields = line.split(None, 5)
        if len(fields) < 6:
            raise _invalid("A job line needs a schedule and a command.", project=name, line=line)
        Schedule(" ".join(fields[:5]))
        jobs.append({"id": pending[0], "description": pending[1], "schedule": " ".join(fields[:5]),
                     "command": _unescape(fields[5])})
        pending = None
    if pending:
        raise _invalid("A job comment is not followed by its schedule line.", project=name)
    return jobs


def _lines(text):
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()                               # the terminator of the last line, not an empty line
    return lines


def split(text, name):
    """`(before, jobs, after)` of the project's section in the crontab `text`; `jobs` is None without a section.

    `before` and `after` are the lines outside the section, exactly as they were."""
    lines = _lines(text)
    begin, end = _begin(name), _end(name)
    starts = [n for n, line in enumerate(lines) if line == begin]
    stops = [n for n, line in enumerate(lines) if line == end]
    if not starts and not stops:
        return lines, None, []
    if len(starts) != 1 or len(stops) != 1 or stops[0] < starts[0]:
        raise _invalid("The project's crontab section is incomplete or repeated. Fix it by hand.", project=name)
    return lines[:starts[0]], _parse_section(name, lines[starts[0] + 1:stops[0]]), lines[stops[0] + 1:]


def sections(text):
    """Every project section in the crontab `text`, in order: `{"project", "begin", "end", "jobs": [{id, command}],
    "error"}`; `begin` and `end` are the section's marker lines.

    A section that `split` refuses (incomplete, repeated, a line that is not a job) is listed with its
    error code and no jobs, so a reader can tell a person to fix it by hand."""
    found = []
    for line in _lines(text):
        if line.startswith(_BEGIN[0]) and line.endswith(_BEGIN[1]) and len(line) > len("".join(_BEGIN)):
            name = line[len(_BEGIN[0]):-len(_BEGIN[1])]
            if name not in found:
                found.append(name)
    result = []
    for name in found:
        try:
            jobs = split(text, name)[1] or []
            result.append({"project": name, "begin": _begin(name), "end": _end(name), "error": None,
                           "jobs": [{"id": job["id"], "command": job["command"]} for job in jobs]})
        except SessionError as error:
            result.append({"project": name, "begin": _begin(name), "end": _end(name), "error": error.code,
                           "jobs": []})
    return result


def render(name, jobs):
    lines = [_begin(name)]
    for job in jobs:
        lines += [f"# job {job['id']}: {job['description']}", f"{job['schedule']} {_escape(job['command'])}"]
    return lines + [_end(name)]


def join(before, existing, jobs, after, name):
    """The crontab text with the project's section set to `jobs` (empty removes it).

    A new section goes at the end after one blank separator line (none for an empty crontab); removing a
    section takes one blank line before it away, so that adding and removing restore the crontab exactly.
    A section that exists keeps its place."""
    before = list(before)
    if jobs and existing is None:
        lines = before + ([""] if before else []) + render(name, jobs) + after
    elif jobs:
        lines = before + render(name, jobs) + after
    else:
        if before and before[-1] == "":
            before.pop()
        lines = before + after
    return "\n".join(lines) + "\n" if lines else ""


# ---------------------------------------------------------------- the crontab command

class Crontab:
    """Read and write the user's crontab through the `crontab` command (`crontab -l`, `crontab -`)."""

    def __init__(self, lock_path, timeout=60):
        self.lock_path = Path(lock_path)
        self.timeout = timeout

    @staticmethod
    def _run(args, stdin=None):
        try:
            return subprocess.run(["crontab", *args], input=stdin, capture_output=True, text=True,
                                  timeout=COMMAND_TIMEOUT, encoding="utf-8", errors="surrogateescape")
        except FileNotFoundError as error:
            raise SessionError("crontab_unavailable", "The crontab command is not available.", 5) from error
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SessionError("crontab_unavailable", "The crontab command failed to run.", 5,
                               {"reason": type(error).__name__}) from error

    def read(self):
        """The crontab text. No crontab yet is an empty text; any other failure is an error, never an empty text."""
        result = self._run(["-l"])
        if result.returncode == 0:
            return result.stdout
        if NO_CRONTAB.search(result.stderr or "") and not (result.stdout or "").strip():
            return ""
        raise SessionError("crontab_unreadable", "Cannot read the crontab; nothing was written.", 5,
                           {"reason": (result.stderr or "").strip()[:300]})

    def write(self, text):
        result = self._run(["-"], stdin=text)
        if result.returncode != 0:
            raise SessionError("crontab_unwritable", "The crontab command refused the new crontab.", 5,
                               {"reason": (result.stderr or "").strip()[:300]})

    def edit(self, name, change):
        """Apply `change(jobs) -> jobs` to the project's section and write the crontab back.

        The lock serializes the Python editors of this user. Another editor (`crontab -e`) cannot be locked
        out, so the crontab is read again just before the write and the whole step repeats when it changed:
        a line is lost only if that second read and the write itself are interleaved. Return the jobs and
        whether the crontab was written (an unchanged section is not written)."""
        with locked(self.lock_path, self.timeout):
            for _ in range(RETRIES):
                text = self.read()
                before, jobs, after = split(text, name)
                updated = change([dict(job) for job in (jobs or [])])
                if updated == (jobs or []):
                    return updated, False
                new = join(before, jobs, updated, after, name)
                if self.read() != text:
                    continue
                self.write(new)
                return updated, True
        raise SessionError("crontab_busy", "The crontab kept changing; nothing was written.", 4)


def crontab_sections(crontab=None):
    """`sections` of the user's crontab (`crontab -l`). A crontab that cannot be read is an error, never an empty list."""
    return sections((crontab or crontab_for()).read())


def crontab_for(lock_path=None):
    """The `Crontab` of the current user. `lock_path` defaults to `~/.cache/agent-session/crontab.lock`."""
    return Crontab(lock_path or Path.home() / ".cache" / "agent-session" / "crontab.lock")


# ---------------------------------------------------------------- the commands

def _check_job_id(job_id):
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        raise _invalid("A job ID is lowercase letters, digits and hyphens, starting with a letter.", id=job_id)
    return job_id


def _check_text(value, what):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise _invalid(f"The {what} must be one nonempty line.")
    return value.strip()


def _project_name(name):
    if not name or "\n" in name or "\r" in name:
        raise _invalid("The project name cannot name a crontab section.", project=name)
    return name


def runs_directory(project):
    """Where a job's last run is kept: `<base>/agent/cron/<job id>.json`, written by the job's command."""
    return project.runtime_path / "cron"


def record_run(project, job_id, ok, result, at=None):
    """Keep the last run of a job (its command calls this). A failure to keep it never fails the job."""
    import json
    directory = runs_directory(project)
    stamp = dt.datetime.fromtimestamp(time.time() if at is None else at, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{_check_job_id(job_id)}.json"
        temporary = path.with_name(f".{path.name}.{time.monotonic_ns()}")
        temporary.write_text(json.dumps({"at": stamp, "ok": bool(ok), "result": result}, ensure_ascii=False),
                             encoding="utf-8")
        temporary.replace(path)
    except OSError:
        pass


def last_run(project, job_id):
    """The kept last run `{at, ok, result}` of a job, or None."""
    import json
    try:
        value = json.loads((runs_directory(project) / f"{job_id}.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) and {"at", "ok"} <= set(value) else None
    except (OSError, ValueError):
        return None


def describe(project, job, now):
    """A job for `cron ls`: the stored fields, the next run (local time, ISO) and the last run."""
    following = Schedule(job["schedule"]).next_run(now)
    return {**job, "next_run": following.isoformat(timespec="minutes") if following else None,
            "last_run": last_run(project, job["id"])}


def listing(project, crontab, now=None, summary=False):
    """The project's jobs. With `summary` only their count and the nearest next run (what a status line needs)."""
    now = now or dt.datetime.now()
    _, jobs, _ = split(crontab.read(), _project_name(project.project_id))
    items = [describe(project, job, now) for job in jobs or []]
    if summary:
        times = [item["next_run"] for item in items if item["next_run"]]
        return {"project": project.project_id, "count": len(items), "next_run": min(times) if times else None}
    return {"project": project.project_id, "jobs": items}


def add(project, crontab, job_id, schedule, description, command, now=None, replace=False):
    """Add a job to the project's section. An existing ID is an error unless `replace` is true."""
    job = {"id": _check_job_id(job_id), "schedule": Schedule(schedule).text,
           "description": _check_text(description, "description"), "command": _check_text(command, "command")}

    def change(jobs):
        if any(item["id"] == job["id"] for item in jobs):
            if not replace:
                raise SessionError("cron_exists", "A job with this ID already exists.", 3, {"id": job["id"]})
            return [job if item["id"] == job["id"] else item for item in jobs]
        return jobs + [job]

    _, written = crontab.edit(_project_name(project.project_id), change)
    return {"project": project.project_id, "job": describe(project, job, now or dt.datetime.now()), "written": written}


def remove(project, crontab, job_id):
    """Remove a job. The section goes with its last job. A missing job is an error."""
    _check_job_id(job_id)

    def change(jobs):
        kept = [item for item in jobs if item["id"] != job_id]
        if len(kept) == len(jobs):
            raise SessionError("cron_not_found", "No job has this ID.", 3, {"id": job_id})
        return kept

    _, written = crontab.edit(_project_name(project.project_id), change)
    return {"project": project.project_id, "removed": job_id, "written": written}


def check_command(project, socket_name=None, socket_path=None):
    """The command line of the project's check job: this release's `agent-session check` for the project."""
    from .launch_artifacts import library_path
    parts = [str(library_path() / "bin" / "agent-session"), "--config", str(project.config_path)]
    if socket_name:
        parts += ["--socket-name", socket_name]
    if socket_path:
        parts += ["--socket-path", str(socket_path)]
    # cron mails whatever a job prints; the result of a run is kept in `last_run`, so the output is dropped.
    return shlex.join(parts + ["check", "--project", project.project_id]) + " >/dev/null 2>&1"


def ensure_check(project, crontab, socket_name=None, socket_path=None, now=None):
    """Make sure the project has its check job (idempotent). Start, restart and resume of the Leader call it.

    A job that exists keeps its schedule and description (a person may have changed them); only its command
    follows this release, so that a release update does not leave the job running an old path. Return
    `{"check": "present" | "added" | "updated"}`."""
    command = check_command(project, socket_name, socket_path)
    outcome = {}

    def change(jobs):
        for index, item in enumerate(jobs):
            if item["id"] == CHECK_ID:
                outcome["check"] = "present" if item["command"] == command else "updated"
                jobs[index] = {**item, "command": command}
                return jobs
        outcome["check"] = "added"
        return jobs + [{"id": CHECK_ID, "schedule": CHECK_SCHEDULE, "description": CHECK_DESCRIPTION,
                        "command": command}]

    crontab.edit(_project_name(project.project_id), change)
    return outcome


class Cron(Watch):
    """`agent-session cron ls|add|rm --project NAME`: the operator's, or the project's Leader's, over one project."""

    def perform(self, action, project, job_id=None, schedule=None, description=None, command=None, summary=False):
        registry, selected = self._select(project, False)
        self._authorize(registry, selected, "cron")
        item, crontab = selected[0], crontab_for()
        if action == "ls":
            return listing(item, crontab, summary=summary)
        if action == "add":
            return add(item, crontab, job_id, schedule, description, command)
        return remove(item, crontab, job_id)
