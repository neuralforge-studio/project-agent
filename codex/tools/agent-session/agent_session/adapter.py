"""Load the selected project's single policy adapter."""

import importlib.util
import re
from pathlib import Path

from .errors import SessionError


REQUIRED = (
    "job_file", "read_job", "check_workspace", "prepare_workspace",
    "record_assignment", "prepare_session", "record_baseline", "prepare_restart",
    "record_ready", "check_release", "record_release",
)


def load_adapter(project):
    path = project.base / "agent" / "adapter.py"
    if not path.is_file():
        raise SessionError("adapter_not_found", f"Project adapter is missing: {path}", 2)
    spec = importlib.util.spec_from_file_location("project_session_adapter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    missing = [name for name in REQUIRED if not callable(getattr(module, name, None))]
    if missing:
        raise SessionError("adapter_invalid", "Project adapter is incomplete.", 2,
                           {"missing": missing})
    for name in REQUIRED:
        original = getattr(module, name)
        def guarded(*args, _function=original, _name=name, **kwargs):
            try:
                return _function(*args, **kwargs)
            except SessionError:
                raise
            except Exception as error:
                code = getattr(error, "code", "adapter_failed")
                message = getattr(error, "message", f"Project callback {_name} failed.")
                details = getattr(error, "details", {})
                raise SessionError(code, message, 3 if hasattr(error, "code") else 5,
                                   {"callback": _name, **details}) from error
        setattr(module, name, guarded)
    return module


def read_job(adapter, path):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise SessionError("job_not_found", f"JOB document is missing: {path}", 2)
    job = adapter.read_job(path)
    required = {"job_id", "role", "mode", "cwd", "task", "scope", "checks",
                "branch", "approved", "baseline"}
    if not isinstance(job, dict) or not required <= job.keys():
        raise SessionError("job_invalid", "JOB metadata is incomplete.", 2)
    for key in ("job_id", "role", "task"):
        if not isinstance(job[key], str) or not job[key].strip():
            raise SessionError("job_invalid", f"JOB {key} must be a nonempty string.", 2)
    if job["job_id"] == "leader":
        raise SessionError("job_invalid", "The JOB ID leader is reserved.", 2)
    if Path(adapter.job_file(job["job_id"])).resolve() != path:
        raise SessionError("job_invalid", "Use the project's official JOB document.", 2)
    if job["mode"] not in ("write", "read-only") or not isinstance(job["cwd"], str):
        raise SessionError("job_invalid", "JOB mode or cwd is invalid.", 2)
    cwd = Path(job["cwd"])
    if cwd.is_absolute() or ".." in cwd.parts:
        raise SessionError("job_invalid", "JOB cwd must stay inside its seat.", 2)
    for key in ("scope", "checks", "submodules"):
        value = job.get(key, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise SessionError("job_invalid", f"JOB {key} must contain strings.", 2)
    body = path.read_text(encoding="utf-8")
    approval = re.search(r"^## 사용자 승인 근거\s*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    if job["approved"] is not True or not approval or not approval.group(1).strip():
        raise SessionError("job_not_approved", "JOB approval and its evidence are required.")
    job["path"] = str(path)
    job.setdefault("submodules", [])
    return job
