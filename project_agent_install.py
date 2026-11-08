"""Copied payload, installation plan, link transaction, and rollback ownership.

The manifest below is the distribution file owner. Runtime dependencies are
reported separately and never installed. Project registration and run state are
outside this module's write set.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile


TOOLS = ('agent-session', 'project-item', 'project-board')
SKILLS = ('project-team', 'project-item')
PRODUCT_MODULES = {
    'agent-session': (
        '__init__', '__main__', 'api', 'cli', 'config', 'errors', 'git_ops',
        'internal', 'jobs', 'lifecycle', 'process', 'registry', 'remote',
        'remote_bridge', 'remote_lifecycle', 'remote_runtime', 'state', 'suspend',
        'tmux', 'util', 'workspace', 'providers/__init__', 'providers/claude',
        'providers/codex', 'providers/common', 'providers/mcp', 'providers/websocket',
    ),
    'project-item': (
        '__init__', '__main__', 'api', 'assign', 'cli', 'cr', 'decide', 'errors',
        'guard', 'kinds', 'registry', 'render', 'store',
    ),
    'project-board': ('__init__', '__main__', 'answer', 'cli', 'model', 'tmux_control', 'tui'),
}
PRODUCT_FILES = (
    'install.py', 'project_agent_install.py', 'README.md', 'AGENTS.md',
    'docs/architecture.md', 'docs/project-board-tui-plan.md',
    'docs/project-team/spec.md', 'docs/project-team/project-registry.example.json',
    'docs/project-team/state.example.json',
    'skills/project-team/SKILL.md', 'skills/project-team/agents/openai.yaml',
    'skills/project-team/assets/commit-message.txt',
    'skills/project-item/SKILL.md', 'skills/project-item/agents/openai.yaml',
    'skills/project-item/references/cr.md', 'skills/project-item/references/decide.md',
    'integrations/tmux/project_board.conf', 'integrations/tmux/project_decide_status.conf',
    'integrations/tmux/tmux_project_board.sh', 'integrations/tmux/tmux_decide_status.py',
    'tools/project-board/requirements.txt',
)


class InstallError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def product_files(source: Path) -> tuple[Path, ...]:
    """Return allowlisted payload paths; reject missing files and source links."""
    files = set(PRODUCT_FILES)
    for tool in TOOLS:
        package = tool.replace('-', '_')
        files.update((f'tools/{tool}/bin/{tool}', f'tools/{tool}/README.md'))
        files.update(f'tools/{tool}/{package}/{module}.py' for module in PRODUCT_MODULES[tool])
    files.add('tools/agent-session/agent_session.py')
    for name in sorted(files):
        path = source / name
        if not path.is_file():
            raise InstallError('payload_missing', f'Required product file is missing: {path}')
        cursor = path
        while cursor != source:
            if cursor.is_symlink():
                raise InstallError('payload_link', f'Product source must contain real files: {cursor}')
            cursor = cursor.parent
    return tuple(Path(name) for name in sorted(files))


def _digest(source: Path, files: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for relative in files:
        path = source / relative
        mode = b'x' if path.stat().st_mode & 0o111 else b'-'
        content = path.read_bytes()
        digest.update(str(relative).encode() + b'\0' + mode + b'\0')
        digest.update(str(len(content)).encode() + b'\0' + content)
    return digest.hexdigest()


def _lexical_target(path: Path, target: str) -> Path:
    # A relative link starts at the physical parent, even when skills itself is a link.
    # Keep the final target lexical so the two product skill names stay distinct.
    return Path(os.path.abspath(path.parent.resolve() / target))


def _readlink(path: Path) -> str | None:
    if path.is_symlink():
        return os.readlink(path)
    if path.exists():
        raise InstallError('path_conflict', f'Existing non-link is not owned by the installer: {path}')
    return None


def _state_path(home: Path) -> Path:
    return home / '.local/state/project-agent/install.json'


def _links(home: Path, copied_root: Path) -> dict[Path, Path]:
    stable = home / '.local/lib/project-agent'
    result = {stable: copied_root}
    result.update({home / '.local/bin' / tool: stable / 'tools' / tool / 'bin' / tool
                   for tool in TOOLS})
    result[home / '.local/lib/agent-session'] = stable / 'tools/agent-session'
    for provider in ('.codex', '.claude'):
        result.update({home / provider / 'skills' / skill: stable / 'skills' / skill
                       for skill in SKILLS})
    return result


def _load_state(home: Path) -> dict:
    path = _state_path(home)
    if path.is_symlink():
        raise InstallError('state_conflict', f'Installation record must be a real file: {path}')
    if not path.exists():
        return {'version': 1, 'history': []}
    try:
        state = json.loads(path.read_text())
        if state.get('version') != 1 or not isinstance(state['history'], list):
            raise ValueError('Unsupported installation record')
        allowed = {str(p) for p in _links(home, home)}
        for entry in state['history']:
            if not isinstance(entry['changes'], list):
                raise ValueError('Invalid transaction')
            for change in entry['changes']:
                if (change['path'] not in allowed or
                        not isinstance(change['after'], str) or
                        change['before'] is not None and not isinstance(change['before'], str)):
                    raise ValueError('Invalid link record')
        return state
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise InstallError('state_invalid', f'Invalid installation record: {path}: {exc}') from exc


def _check_writable(path: Path):
    cursor = path
    while not cursor.exists():
        cursor = cursor.parent
    if (not cursor.is_dir() or not os.access(cursor, os.W_OK | os.X_OK)
            or not cursor.stat().st_mode & 0o222):
        raise InstallError('path_unwritable', f'Installation parent is not writable: {cursor}')


def _external_skills(path: Path, home: Path) -> bool:
    cursor = path.parent
    while cursor != home:
        if cursor.is_symlink():
            return True
        cursor = cursor.parent
    return False


def _require_local_skill_destination(path: Path, home: Path):
    if path.parent.name == 'skills' and _external_skills(path, home):
        raise InstallError('skills_external', f'Shared skills directory is not an installer write destination: {path}')


@dataclass(frozen=True)
class InstallPlan:
    source: Path
    home: Path
    files: tuple[Path, ...]
    digest: str
    copied_root: Path
    changes: tuple[dict, ...]
    state: dict


def plan(source: Path, home: Path) -> InstallPlan:
    """Read-only validation of payload and explicit installer destinations."""
    if sys.version_info < (3, 11):
        raise InstallError('python_version', 'Python 3.11 or later is required.')
    source, home = source.resolve(), home.resolve()
    files = product_files(source)
    digest = _digest(source, files)
    copied_root = home / '.local/lib/project-agent-installs' / digest
    state = _load_state(home)
    previous = {}
    for entry in state['history']:
        previous.update({change['path']: change['after'] for change in entry['changes']})
    changes = []
    for path, target in _links(home, copied_root).items():
        before = _readlink(path)
        same = before is not None and _lexical_target(path, before) == target
        if path.parent.name == 'skills' and _external_skills(path, home):
            if not same:
                raise InstallError('skills_external',
                                   f'Prepare a product link without changing the shared skills directory: {path} -> {target}')
            continue
        if same:
            continue
        if before is not None and previous.get(str(path)) != before:
            raise InstallError('path_conflict', f'Existing link is not owned by the installer: {path} -> {before}')
        _check_writable(path.parent)
        changes.append({'path': str(path), 'before': before, 'after': str(target)})
    _check_writable(copied_root.parent)
    _check_writable(_state_path(home).parent)
    if copied_root.is_symlink() or copied_root.exists() and not copied_root.is_dir():
        raise InstallError('payload_conflict', f'Installed payload path is not a real directory: {copied_root}')
    if copied_root.exists() and _digest(copied_root, product_files(copied_root)) != digest:
        raise InstallError('payload_conflict', f'Installed payload content differs from its hash: {copied_root}')
    return InstallPlan(source, home, files, digest, copied_root, tuple(changes), state)


def runtime_readiness(source: Path, home: Path) -> dict:
    """Probe command/module availability; never run or authenticate a provider."""
    commands = {name: shutil.which(name) for name in ('git', 'tmux', 'codex', 'claude')}
    inhouse = Path('/primehome/tools/Inhouse/Python3/latest/bin/python3')
    venv = home / 'python/.venv/bin/python'
    fallback = shutil.which('python3')
    common = str(inhouse) if os.access(inhouse, os.X_OK) else str(venv) if os.access(venv, os.X_OK) else fallback
    if platform.system() == 'Darwin':
        session = fallback
    elif os.environ.get('WSL_DISTRO_NAME') or os.environ.get('WSL_INTEROP') or 'microsoft' in platform.release().lower():
        session = str(venv)
    else:
        session = str(inhouse)
    pythons = {'agent-session': session, 'project-item': common, 'project-board': common}
    checks = {}
    for tool, executable in pythons.items():
        item = {'python': executable, 'available': bool(executable and os.access(executable, os.X_OK))}
        if item['available']:
            probe = ('import json,sys,importlib.metadata as m; '
                     'print(json.dumps({"version":list(sys.version_info[:3]), '
                     '"textual": m.version("textual") if "textual" in '
                     '{d.metadata["Name"].lower() for d in m.distributions()} else None}))')
            try:
                env = os.environ.copy()
                env.pop('PYTHONHOME', None)
                if executable == str(inhouse):
                    env['LD_LIBRARY_PATH'] = '/primehome/tools/Inhouse/Python3/latest/lib' + (':' + env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
                output = subprocess.run([executable, '-I', '-c', probe], capture_output=True,
                                        text=True, timeout=5, env=env)
                item.update(json.loads(output.stdout))
                item['available'] = item['version'] >= [3, 10, 0]
            except (OSError, ValueError, subprocess.TimeoutExpired):
                item['available'] = False
        checks[tool] = item
    requirement = (source / 'tools/project-board/requirements.txt').read_text().strip()
    textual = checks['project-board'].get('textual')
    return {'commands': commands, 'launchers': checks,
            'board_requirement': requirement,
            'board_requirement_met': requirement == f'textual=={textual}',
            'provider_login': 'unchecked; checked when the provider runs',
            'ssh': 'unchecked; depends on the registered host, path, Python, and connection',
            'note': 'Runtime readiness does not block file installation. No packages were installed.'}


def _describe(prepared: InstallPlan, action: str) -> dict:
    return {'action': action, 'content_hash': prepared.digest,
            'product_root': str(prepared.home / '.local/lib/project-agent'),
            'installed_payload': str(prepared.copied_root),
            'changes': list(prepared.changes),
            'runtime': runtime_readiness(prepared.source, prepared.home)}


def check(source: Path, home: Path) -> dict:
    return _describe(plan(source, home), 'check')


def _replace_link(path: Path, target: str | None):
    if target is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.{os.getpid()}.new')
    try:
        temporary.symlink_to(target)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_state(home: Path, state: dict):
    path = _state_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.install-', suffix='.json', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(state, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _installation_lock(home: Path):
    path = _state_path(home).parent / 'install.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield


def _copy_payload(prepared: InstallPlan) -> bool:
    if prepared.copied_root.exists():
        return False
    prepared.copied_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.copy-', dir=prepared.copied_root.parent))
    try:
        for relative in prepared.files:
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(prepared.source / relative, target)
        if _digest(temporary, product_files(temporary)) != prepared.digest:
            raise InstallError('copy_mismatch', 'Product files changed while the installer copied them.')
        temporary.rename(prepared.copied_root)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return True


def _apply_transaction(home: Path, changes: list[dict], state: dict):
    applied = []
    try:
        for change in changes:
            path = Path(change['path'])
            _require_local_skill_destination(path, home)
            if _readlink(path) != change['before']:
                raise InstallError('path_changed', f'Installation link changed during transaction: {path}')
            _replace_link(path, change['after'])
            applied.append(change)
        _write_state(home, state)
    except BaseException as original:
        failures = []
        for change in reversed(applied):
            try:
                path = Path(change['path'])
                _require_local_skill_destination(path, home)
                if _readlink(path) != change['after']:
                    raise OSError(f'Link changed before restoration: {path}')
                _replace_link(path, change['before'])
            except (OSError, InstallError) as exc:
                failures.append(str(exc))
        if failures:
            raise InstallError('restore_failed', f'{original}; link restoration failed: {failures}') from original
        raise


def install(source: Path, home: Path) -> dict:
    prepared = plan(source, home)
    with _installation_lock(prepared.home):
        prepared = plan(prepared.source, prepared.home)
        created = _copy_payload(prepared)
        if prepared.changes:
            entry = {'content_hash': prepared.digest, 'installed_payload': str(prepared.copied_root),
                     'created_payload': created, 'changes': list(prepared.changes)}
            state = {'version': 1, 'history': [*prepared.state['history'], entry]}
            _apply_transaction(prepared.home, list(prepared.changes), state)
    return _describe(prepared, 'installed' if prepared.changes else 'unchanged')


def rollback(home: Path) -> dict:
    home = home.resolve()
    state = _load_state(home)
    if not state['history']:
        raise InstallError('rollback_missing', 'No installer-owned transaction is available to restore.')
    with _installation_lock(home):
        state = _load_state(home)
        if not state['history']:
            raise InstallError('rollback_missing', 'No installer-owned transaction is available to restore.')
        previous = state['history'][-1]
        changes = []
        for change in reversed(previous['changes']):
            path = Path(change['path'])
            _require_local_skill_destination(path, home)
            if _readlink(path) != change['after']:
                raise InstallError('path_changed', f'Rollback link has changed since installation: {path}')
            before = change['before']
            if before is not None and not _lexical_target(path, before).exists():
                raise InstallError('rollback_target_missing', f'Previous link target no longer exists: {path} -> {before}')
            changes.append({'path': str(path), 'before': change['after'], 'after': before})
        _apply_transaction(home, changes, {'version': 1, 'history': state['history'][:-1]})
    return {'action': 'rolled_back', 'restored_links': [c['path'] for c in changes],
            'retained_payload': previous['installed_payload'],
            'note': 'Copied payloads are retained for existing runs. Parent repository migration is managed by its owner.'}
