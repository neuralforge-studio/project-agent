"""Small fixture domain writer with explicit failure injection."""

import json
from pathlib import Path
import re
import subprocess

from agent_session.errors import SessionError
from agent_session.util import write_json


BASE = Path(__file__).resolve().parents[1]
DOMAIN = BASE / ".fixture-domain.json"
CONTROLS = BASE / ".fixture-controls.json"


def _domain():
    if DOMAIN.exists():
        return json.loads(DOMAIN.read_text())
    return {"assignments": {}, "ready": {}, "accepted": {}, "releases": {}, "events": []}


def _fail(name):
    controls = json.loads(CONTROLS.read_text()) if CONTROLS.exists() else {}
    if controls.get(name):
        controls[name] = False
        write_json(CONTROLS, controls)
        raise SessionError("fixture_" + name, "The fixture injected a project failure.")


def _git(root, *args):
    return subprocess.check_output(["git", "-c", "submodule.recurse=false", "-C", str(root), *args], text=True).strip()


def job_file(job_id):
    return BASE / "jobs" / (job_id + ".md")


def read_job(path):
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(re.search(r"```json\n(.*?)\n```", text, re.S).group(1))


def _write_job(job):
    path = job_file(job["job_id"])
    path.write_text("# Fixture JOB\n\n```json\n" + json.dumps(job, ensure_ascii=False, indent=2)
                    + "\n```\n\n## 사용자 승인 근거\n\nThe test operator approved this temporary fixture task.\n", encoding="utf-8")


def check_workspace(context):
    if context["job"] is None:
        return {"allowed": True, "reasons": []}
    dirty = _git(context["seat_root"], "status", "--porcelain", "--untracked-files=all")
    return {"allowed": not dirty, "reasons": ["unpreserved files"] if dirty else []}


def prepare_workspace(context, phase):
    if context["job"] is None:
        return {}
    if phase == "before_sync":
        _fail("git_prepare_once")
        return {"sync_main": context["job"]["mode"] == "read-only"}
    return {}


def record_assignment(context):
    _fail("assignment_once")
    domain = _domain()
    old = domain["assignments"].get(context["job_id"])
    if old is None:
        domain["assignments"][context["job_id"]] = {"seat": context["seat"], "prepared": False}
    elif old["seat"] != context["seat"]:
        raise SessionError("assignment_mismatch", "The fixture JOB changed seats.")
    domain["events"].append(["assignment", context["job_id"], context["run_id"]])
    write_json(DOMAIN, domain)


def record_baseline(context, baseline):
    job = read_job(job_file(context["job_id"]))
    if job["baseline"] and baseline and job["baseline"]["base_hash"] != baseline["base_hash"]:
        raise SessionError("baseline_mismatch", "The fixture's saved baseline must not change.")
    job["baseline"] = baseline
    _write_job(job)
    _fail("baseline_after_save_once")
    domain = _domain()
    row = domain["assignments"][context["job_id"]]
    branch = _git(context["seat_root"], "branch", "--show-current")
    row["prepared"] = context["job"]["mode"] == "read-only" or branch == context["job"]["branch"]
    domain["events"].append(["baseline", context["job_id"], baseline["base_hash"] if baseline else None])
    write_json(DOMAIN, domain)


def prepare_session(context, hooks, prompt):
    directory = BASE / "agent" / "runs" / context["run_id"]
    directory.mkdir(parents=True, exist_ok=True)
    prompt_file = directory / "prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    return {"prompt_file": str(prompt_file), "settings_file": None, "env": {}, "unset_env": [], "provider_args": []}


def record_ready(context, session):
    _fail("ready_once")
    domain = _domain()
    target = context["job_id"] or "leader"
    domain["ready"].setdefault(target, [])
    if session["session_id"] not in domain["ready"][target]:
        domain["ready"][target].append(session["session_id"])
    domain["events"].append(["ready", target, context["run_id"]])
    write_json(DOMAIN, domain)


def prepare_restart(context):
    path = BASE / "handoff" / (context["job_id"] or "leader")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Fixture handoff", "", "Previous session: " + context["session_id"],
             "JOB: " + str(context["job_id"]), "HEAD: " + _git(context["seat_root"], "rev-parse", "HEAD"),
             "Changes:", _git(context["seat_root"], "status", "--porcelain", "--untracked-files=all")]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"handoff_file": str(path)}


def check_release(context):
    if context["job_id"] is None:
        return {"allowed": True, "reasons": [], "evidence": {}}
    domain = _domain()
    expected = domain["accepted"].get(context["job_id"])
    head = _git(context["seat_root"], "rev-parse", "HEAD")
    dirty = _git(context["seat_root"], "status", "--porcelain", "--untracked-files=all")
    allowed = expected == head and not dirty
    return {"allowed": allowed, "reasons": [] if allowed else ["work is not accepted and clean"],
            "evidence": {"head": head, "branch": _git(context["seat_root"], "branch", "--show-current")}}


def record_release(context, evidence):
    _fail("release_once")
    domain = _domain()
    if context["job_id"] is not None:
        domain["releases"][context["job_id"]] = {**evidence, "run_id": context["run_id"]}
    write_json(DOMAIN, domain)
