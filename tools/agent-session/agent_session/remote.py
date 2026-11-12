"""SSH transport for a registered Codex seat. Assignment and CR ownership stay local."""

import json
from pathlib import Path
import re
import shlex
import subprocess

from .errors import SessionError


# The directories in front of the remote host's PATH: the one place that says which tmux (and CLIs) the remote
# runtime and the SSH display command find there. The local installer's record (`tmux_program`) cannot name a tmux
# of another host, so a remote runtime, which has no such record, uses the `tmux` first in this PATH.
REMOTE_PATH = ("$HOME/.local/bin", "/opt/homebrew/bin")

BOOTSTRAP = """import base64,fcntl,hashlib,io,json,os,pathlib,sys,zipfile
r=json.load(sys.stdin)
b=base64.b64decode(r.pop('source'))
d=pathlib.Path.home()/'.cache/agent-session/runtime'/hashlib.sha256(b).hexdigest()
d.parent.mkdir(parents=True,exist_ok=True)
with (d.parent/(d.name+'.lock')).open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 if not (d/'ready').is_file():
  d.mkdir(parents=True,exist_ok=True)
  with zipfile.ZipFile(io.BytesIO(b)) as z:
   for n in z.namelist():
    p=pathlib.PurePosixPath(n)
    if p.is_absolute() or '..' in p.parts: raise ValueError('invalid runtime member')
   z.extractall(d)
  (d/'ready').touch()
sys.path.insert(0,str(d/'agent-session'))
os.environ['PATH']=os.path.expandvars('@REMOTE_PATH@:/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin:')+os.environ.get('PATH','')
from agent_session.remote_runtime import respond
respond(r,d)
""".replace("@REMOTE_PATH@", ":".join(REMOTE_PATH))

# Repository-relative documents that a remote Worker follows (shipped under `guidance/`).
# Every link of these documents that points into skills or docs/project-team must name a
# file in this list; tests/test_remote.py checks it. Tool READMEs stay in the source tree.
GUIDANCE_FILES = (
    "skills/project-team/SKILL.md",
    "skills/project-team/assets/commit-message.txt",
    "skills/project-team/references/self-check.md",
    "skills/project-item/SKILL.md",
    "skills/project-item/references/cr.md",
    "skills/project-item/references/decide.md",
    "docs/project-team/spec.md",
    "docs/project-team/project-registry.example.json",
    "docs/project-team/state.example.json",
)


def source_archive():
    """Ship only maintained Python helpers, never project files or user credentials."""
    import base64, io, zipfile      # only a remote call needs them: zipfile is a large import
    root = Path(__file__).resolve().parents[2]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for tool, package in (("agent-session", "agent_session"), ("project-item", "project_item")):
            for path in sorted((root / tool / package).rglob("*.py")):
                info = zipfile.ZipInfo(str(path.relative_to(root)))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
        repository = root.parent
        for relative in GUIDANCE_FILES:
            path = repository / relative
            if path.is_file():
                info = zipfile.ZipInfo("guidance/" + relative)
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
    return base64.b64encode(output.getvalue()).decode("ascii")


def seat_for(meta):
    from .config import RemoteSeat
    return RemoteSeat(**meta["remote_seat"])


def call(seat, operation, payload=None, timeout=120):
    """One authenticated SSH request. A failed transport never means a stopped Worker."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]*", seat.host):
        raise SessionError("registry_invalid", "Invalid SSH seat host.", 2)
    request = {"seat": str(seat), "operation": operation, "payload": payload or {}, "source": source_archive()}
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=5",
            "-o", "ServerAliveCountMax=2", "--", seat.host, shlex.join([seat.python, "-c", BOOTSTRAP])]
    try:
        result = subprocess.run(argv, input=json.dumps(request), text=True, capture_output=True,
                                timeout=max(0.001, timeout))
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SessionError("remote_unknown", "Cannot confirm the remote seat operation.", 4,
                           {"host": seat.host, "operation": operation}) from error
    if result.returncode:
        raise SessionError("remote_unknown", "SSH did not confirm the remote operation.", 4,
                           {"host": seat.host, "operation": operation, "reason": result.stderr.strip()[-1000:]})
    try:
        response = json.loads(result.stdout)
        if not response["ok"]:
            error = response["error"]
            raise SessionError(error["code"], error["message"], error.get("exit_code", 4), error.get("details"))
        return response["data"]
    except (ValueError, KeyError, TypeError) as error:
        raise SessionError("remote_unknown", "The remote response is incomplete.", 4,
                           {"host": seat.host, "operation": operation}) from error


def run_call(meta, operation, payload=None, timeout=30):
    return call(seat_for(meta), operation, {"run_id": meta["run_id"],
                "native": meta.get("remote_native"), **(payload or {})}, timeout=timeout)


def observe(meta, timeout=30):
    return run_call(meta, "observe", timeout=timeout)


def liveness(meta):
    result = run_call(meta, "liveness", timeout=10)
    if result not in ("alive", "stopped"):
        raise SessionError("remote_unknown", "The remote liveness response is incomplete.", 4)
    return result
