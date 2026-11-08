"""Observe independent installation, conservative links, and recovery."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('project_agent_install', ROOT / 'project_agent_install.py')
installer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = installer
spec.loader.exec_module(installer)


@pytest.fixture
def distribution(tmp_path):
    source = tmp_path / 'download'
    source.mkdir()
    for relative in installer.product_files(ROOT):
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    return source


@pytest.fixture
def home(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    return home


def run_cli(source, home, *args):
    env = {**os.environ, 'HOME': str(home), 'PYTHONDONTWRITEBYTECODE': '1'}
    return subprocess.run([sys.executable, str(source / 'install.py'), *args],
                          env=env, cwd=home, capture_output=True, text=True, timeout=30)


def test_check_is_read_only_and_reports_missing_runtime(distribution, home, monkeypatch):
    monkeypatch.setenv('PATH', '')
    monkeypatch.setattr(installer.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(installer.shutil, 'which', lambda command: None)
    result = installer.check(distribution, home)
    assert result['action'] == 'check'
    assert result['runtime']['commands']['codex'] is None
    assert result['runtime']['launchers']['agent-session']['available'] is False
    assert list(home.iterdir()) == []
    installed = installer.install(distribution, home)
    assert installed['action'] == 'installed'
    assert (home / '.local/lib/project-agent/install.py').is_file()


def test_installation_results_do_not_verify_existing_consumer_cutover(distribution, home):
    tmux_config = home / '.tmux.conf'
    legacy_config = '# The environment owner selects the operational include.\nsource-file ~/legacy/project_board.conf\n'
    tmux_config.write_text(legacy_config, encoding='utf-8')
    for args, expected in ((('--check',), 'check'), ((), 'installed'),
                           ((), 'unchanged'), (('--rollback',), 'rolled_back')):
        completed = run_cli(distribution, home, *args)
        assert completed.returncode == 0, completed.stderr
        result = json.loads(completed.stdout)
        assert result['action'] == expected
        assert result['consumer_transition']['verified'] is False
        assert result['consumer_transition']['required_action']
        assert tmux_config.read_text(encoding='utf-8') == legacy_config


def test_payload_is_complete_and_excludes_operational_files(distribution, home):
    (distribution / '.git').mkdir()
    (distribution / '.git/config').write_text('private')
    (distribution / 'credentials.json').write_text('secret')
    (distribution / 'agent').mkdir()
    (distribution / 'agent/state.json').write_text('private')
    result = installer.install(distribution, home)
    payload = Path(result['installed_payload'])
    assert payload.is_dir() and not payload.is_symlink()
    assert not (payload / '.git').exists()
    assert not (payload / 'credentials.json').exists()
    assert not (payload / 'agent').exists()
    assert (payload / 'skills/project-item/references/decide.md').is_file()
    assert (payload / 'skills/project-team/agents/openai.yaml').is_file()
    assert (payload / 'project_agent_install.py').is_file()
    assert (payload / 'integrations/tmux/project_decide_status.conf').is_file()
    stable = home / '.local/lib/project-agent'
    assert stable.resolve() == payload
    for tool in installer.TOOLS:
        assert os.readlink(home / '.local/bin' / tool) == str(stable / 'tools' / tool / 'bin' / tool)
    assert (home / '.local/lib/agent-session').resolve() == payload / 'tools/agent-session'
    for provider in ('.codex', '.claude'):
        for skill in installer.SKILLS:
            assert (home / provider / 'skills' / skill).resolve() == payload / 'skills' / skill


def test_reinstall_keeps_record_and_unrelated_files(distribution, home):
    personal = home / '.codex/skills/personal'
    personal.mkdir(parents=True)
    (personal / 'SKILL.md').write_text('user skill')
    first = installer.install(distribution, home)
    record = (home / '.local/state/project-agent/install.json').read_bytes()
    second = installer.install(distribution, home)
    assert second['action'] == 'unchanged'
    assert second['content_hash'] == first['content_hash']
    assert (home / '.local/state/project-agent/install.json').read_bytes() == record
    assert (personal / 'SKILL.md').read_text() == 'user skill'


@pytest.mark.parametrize('nested', [False, True])
def test_installed_management_and_tools_survive_deleted_download(distribution, home, tmp_path, nested):
    if nested:
        source_target = tmp_path / 'incoming/vendor clone/releases/archive/project agent'
        source_target.parent.mkdir(parents=True)
        distribution.rename(source_target)
        distribution = source_target
        home_target = tmp_path / 'runtime/accounts/new user/profile/home'
        home_target.parent.mkdir(parents=True)
        home.rename(home_target)
        home = home_target
    result = run_cli(distribution, home)
    assert result.returncode == 0, result.stderr
    payload = Path(json.loads(result.stdout)['installed_payload'])
    shutil.rmtree(distribution)
    stable = home / '.local/lib/project-agent'
    expected_skills = {
        'project-team': ('SKILL.md', 'agents/openai.yaml', 'assets/commit-message.txt'),
        'project-item': ('SKILL.md', 'agents/openai.yaml', 'references/cr.md', 'references/decide.md'),
    }
    for provider in ('.codex', '.claude'):
        for skill, files in expected_skills.items():
            link = home / provider / 'skills' / skill
            assert link.resolve() == payload / 'skills' / skill
            for relative in files:
                assert (link / relative).read_text(encoding='utf-8').strip()
            assert (link / '../../docs/project-team/spec.md').resolve().is_file()
    env = {**os.environ, 'HOME': str(home), 'PYTHONPATH': '', 'PYTHONDONTWRITEBYTECODE': '1'}
    for tool in installer.TOOLS:
        command = subprocess.run([str(home / '.local/bin' / tool), '--help'],
                                 env=env, capture_output=True, text=True, timeout=30)
        assert command.returncode == 0, command.stdout + command.stderr
        assert 'usage' in (command.stdout + command.stderr).lower()
    imported = subprocess.run([sys.executable, '-I', '-c',
                              'import sys; sys.path.insert(0,sys.argv[1]); '
                              'import agent_session.api; from agent_session.remote import source_archive; '
                              'import base64,io,zipfile; '
                              'bundle=zipfile.ZipFile(io.BytesIO(base64.b64decode(source_archive()))); '
                              'assert "guidance/skills/project-item/references/decide.md" in bundle.namelist(); '
                              'print(agent_session.api.__file__)',
                              str(home / '.local/lib/agent-session')],
                             env=env, capture_output=True, text=True, timeout=20)
    assert imported.returncode == 0, imported.stderr
    assert str(home / '.local/lib/agent-session') in imported.stdout
    checked = run_cli(stable, home, '--check')
    assert checked.returncode == 0, checked.stderr
    rolled = run_cli(stable, home, '--rollback')
    assert rolled.returncode == 0, rolled.stderr
    assert not stable.exists()
    assert payload.is_dir()
    assert not (home / '.local/bin/agent-session').is_symlink()


def test_update_then_rollback_uses_retained_installs(distribution, home):
    first = installer.install(distribution, home)
    original = Path(first['installed_payload'])
    (distribution / 'README.md').write_text('Updated product documentation\n')
    updated = installer.install(distribution, home)
    latest = Path(updated['installed_payload'])
    assert original != latest
    assert (home / '.local/lib/project-agent').resolve() == latest
    shutil.rmtree(distribution)
    result = run_cli(latest, home, '--rollback')
    assert result.returncode == 0, result.stderr
    assert (home / '.local/lib/project-agent').resolve() == original
    assert original.is_dir() and latest.is_dir()
    assert (home / '.local/bin/project-item').resolve() == original / 'tools/project-item/bin/project-item'


@pytest.mark.parametrize('existing', ['file', 'foreign-link'])
def test_conflict_preserves_existing_entry_and_installs_nothing(distribution, home, existing):
    entry = home / '.local/bin/project-item'
    entry.parent.mkdir(parents=True)
    foreign = home / 'foreign'
    foreign.write_text('private')
    if existing == 'file':
        entry.write_text('user command')
    else:
        entry.symlink_to(foreign)
    with pytest.raises(installer.InstallError, match='not owned'):
        installer.install(distribution, home)
    assert entry.read_text() == ('user command' if existing == 'file' else 'private')
    assert not (home / '.local/lib/project-agent-installs').exists()


@pytest.mark.parametrize('provider', ['.codex', '.claude'])
@pytest.mark.parametrize('link_style', ['absolute', 'relative'])
def test_external_skills_directory_is_never_modified(distribution, home, tmp_path, provider, link_style):
    home_target = tmp_path / 'runtime/users/operator profile/home'
    home_target.parent.mkdir(parents=True)
    home.rename(home_target)
    home = home_target
    shared = tmp_path / 'arbitrary clone depth/owner checkout/config/codex/skills'
    shared.mkdir(parents=True)
    (shared / 'personal').mkdir()
    (home / provider).mkdir()
    (home / provider / 'skills').symlink_to(os.path.relpath(shared, home / provider), target_is_directory=True)
    with pytest.raises(installer.InstallError) as caught:
        installer.check(distribution, home)
    assert caught.value.code == 'skills_external'
    assert str(home / provider / 'skills/project-team') in str(caught.value)
    assert sorted(p.name for p in shared.iterdir()) == ['personal']
    stable = home / '.local/lib/project-agent'
    for skill in installer.SKILLS:
        target = stable / 'skills' / skill
        (shared / skill).symlink_to(os.path.relpath(target, shared) if link_style == 'relative' else target)
    before = {p.name: p.lstat().st_ino for p in shared.iterdir()}
    checked = installer.check(distribution, home)
    assert checked['action'] == 'check'
    installer.install(distribution, home)
    assert {p.name: p.lstat().st_ino for p in shared.iterdir()} == before
    for skill in installer.SKILLS:
        assert (shared / skill).resolve() == (stable / 'skills' / skill).resolve()
    installer.rollback(home)
    assert {p.name: p.lstat().st_ino for p in shared.iterdir()} == before
    assert all((shared / skill).is_symlink() for skill in installer.SKILLS)


@pytest.mark.parametrize(('provider', 'link_style'), [('.codex', 'absolute'), ('.claude', 'relative')])
def test_swapped_external_skill_links_are_rejected(distribution, home, tmp_path, provider, link_style):
    shared = tmp_path / 'nested/agent checkout/clone/skills'
    shared.mkdir(parents=True)
    (home / provider).mkdir()
    (home / provider / 'skills').symlink_to(shared, target_is_directory=True)
    stable = home / '.local/lib/project-agent'
    for skill, swapped in (('project-team', 'project-item'), ('project-item', 'project-team')):
        target = stable / 'skills' / swapped
        (shared / skill).symlink_to(os.path.relpath(target, shared) if link_style == 'relative' else target)
    before = {p.name: (p.lstat().st_ino, os.readlink(p)) for p in shared.iterdir()}
    for action in (installer.check, installer.install):
        with pytest.raises(installer.InstallError) as caught:
            action(distribution, home)
        assert caught.value.code == 'skills_external'
    assert {p.name: (p.lstat().st_ino, os.readlink(p)) for p in shared.iterdir()} == before
    assert not (home / '.local').exists()


def test_missing_previous_payload_refuses_rollback(distribution, home):
    old = installer.install(distribution, home)
    (distribution / 'README.md').write_text('new\n')
    current = installer.install(distribution, home)
    shutil.rmtree(old['installed_payload'])
    with pytest.raises(installer.InstallError) as caught:
        installer.rollback(home)
    assert caught.value.code == 'rollback_target_missing'
    assert (home / '.local/lib/project-agent').resolve() == Path(current['installed_payload'])


def test_transaction_failure_restores_links_and_record(distribution, home, monkeypatch):
    installer.install(distribution, home)
    record = (home / '.local/state/project-agent/install.json').read_bytes()
    original_root = os.readlink(home / '.local/lib/project-agent')
    (distribution / 'README.md').write_text('new\n')
    real_write = installer._write_state
    monkeypatch.setattr(installer, '_write_state', lambda *_: (_ for _ in ()).throw(OSError('injected record write failure')))
    with pytest.raises(OSError, match='injected record'):
        installer.install(distribution, home)
    assert os.readlink(home / '.local/lib/project-agent') == original_root
    assert (home / '.local/state/project-agent/install.json').read_bytes() == record
    monkeypatch.setattr(installer, '_write_state', real_write)


def test_first_install_partial_link_failure_restores_previous_state(distribution, home, monkeypatch):
    real_replace = installer._replace_link
    calls = []
    def fail_once(path, target):
        calls.append(path.name)
        if len(calls) == 3:
            raise OSError('injected link failure')
        return real_replace(path, target)
    monkeypatch.setattr(installer, '_replace_link', fail_once)
    with pytest.raises(OSError, match='injected link'):
        installer.install(distribution, home)
    assert not (home / '.local/lib/project-agent').is_symlink()
    assert not (home / '.local/bin/agent-session').is_symlink()
    assert not (home / '.local/state/project-agent/install.json').exists()


def test_changed_owned_link_is_not_overwritten(distribution, home):
    installer.install(distribution, home)
    command = home / '.local/bin/project-item'
    command.unlink()
    command.symlink_to('/unrelated-command')
    with pytest.raises(installer.InstallError) as caught:
        installer.install(distribution, home)
    assert caught.value.code == 'path_conflict'
    assert os.readlink(command) == '/unrelated-command'
    with pytest.raises(installer.InstallError) as caught:
        installer.rollback(home)
    assert caught.value.code == 'path_changed'


def test_missing_product_file_and_source_link_are_rejected(distribution, home, tmp_path):
    metadata = distribution / 'skills/project-team/agents/openai.yaml'
    metadata.unlink()
    with pytest.raises(installer.InstallError) as caught:
        installer.check(distribution, home)
    assert caught.value.code == 'payload_missing'
    metadata.symlink_to(tmp_path / 'outside')
    (tmp_path / 'outside').write_text('not product data')
    with pytest.raises(installer.InstallError) as caught:
        installer.check(distribution, home)
    assert caught.value.code == 'payload_link'


def test_unwritable_destination_is_rejected(distribution, home):
    parent = home / '.local'
    parent.mkdir()
    parent.chmod(0o555)
    try:
        with pytest.raises(installer.InstallError) as caught:
            installer.check(distribution, home)
        assert caught.value.code == 'path_unwritable'
    finally:
        parent.chmod(0o755)


def test_runtime_probe_never_invokes_provider_or_git(distribution, home, tmp_path, monkeypatch):
    commands = tmp_path / 'commands'
    commands.mkdir()
    marker = tmp_path / 'command-was-run'
    for name in ('git', 'tmux', 'codex', 'claude'):
        command = commands / name
        command.write_text(f'#!/bin/sh\nprintf invoked > "{marker}"\nexit 1\n')
        command.chmod(0o755)
    monkeypatch.setenv('PATH', str(commands))
    monkeypatch.setattr(installer.platform, 'system', lambda: 'Darwin')
    result = installer.install(distribution, home)
    assert result['runtime']['commands']['codex'] == str(commands / 'codex')
    assert result['runtime']['provider_login'].startswith('unchecked')
    assert not marker.exists()


def test_installer_python_requirement_is_a_file_install_condition(distribution, home, monkeypatch):
    with monkeypatch.context() as context:
        context.setattr(installer.sys, 'version_info', (3, 10, 0))
        with pytest.raises(installer.InstallError) as caught:
            installer.plan(distribution, home)
    assert caught.value.code == 'python_version'
    assert list(home.iterdir()) == []


def test_corrupted_installed_payload_is_not_reused(distribution, home):
    installed = installer.install(distribution, home)
    payload = Path(installed['installed_payload'])
    (payload / 'README.md').write_text('unexpected local edit')
    with pytest.raises(installer.InstallError) as caught:
        installer.install(distribution, home)
    assert caught.value.code == 'payload_conflict'
    assert (payload / 'README.md').read_text() == 'unexpected local edit'


@pytest.mark.parametrize('module', [
    'tools/agent-session/agent_session/lifecycle.py',
    'tools/project-item/project_item/store.py',
    'tools/project-board/project_board/tui.py',
])
def test_missing_runtime_module_rejects_distribution(distribution, home, module):
    (distribution / module).unlink()
    with pytest.raises(installer.InstallError) as caught:
        installer.check(distribution, home)
    assert caught.value.code == 'payload_missing'
    assert module in str(caught.value)
    assert list(home.iterdir()) == []


def test_transaction_reports_restore_failure_and_restores_other_links(distribution, home, monkeypatch):
    concurrent_file = home / '.local/bin/agent-session'
    def failed_record_write(*_):
        concurrent_file.unlink()
        concurrent_file.write_text('external replacement')
        raise OSError('injected record failure')
    monkeypatch.setattr(installer, '_write_state', failed_record_write)
    with pytest.raises(installer.InstallError) as caught:
        installer.install(distribution, home)
    assert caught.value.code == 'restore_failed'
    assert 'injected record failure' in str(caught.value)
    assert str(concurrent_file) in str(caught.value)
    assert concurrent_file.read_text() == 'external replacement'
    assert not (home / '.local/lib/project-agent').is_symlink()
    assert not (home / '.local/bin/project-item').is_symlink()
    assert not (home / '.local/state/project-agent/install.json').exists()


def test_rollback_refuses_skills_parent_moved_to_external_repository(distribution, home, tmp_path):
    installer.install(distribution, home)
    state = (home / '.local/state/project-agent/install.json').read_bytes()
    skills = home / '.codex/skills'
    shared = tmp_path / 'other-repository/skills'
    shared.parent.mkdir()
    skills.rename(shared)
    skills.symlink_to(shared, target_is_directory=True)
    links = {p.name: os.readlink(p) for p in shared.iterdir()}
    with pytest.raises(installer.InstallError) as caught:
        installer.rollback(home)
    assert caught.value.code == 'skills_external'
    assert {p.name: os.readlink(p) for p in shared.iterdir()} == links
    assert (home / '.local/state/project-agent/install.json').read_bytes() == state
    assert (home / '.local/lib/project-agent').exists()
    assert (home / '.local/bin/agent-session').exists()


def test_install_refuses_skills_parent_changed_after_plan(distribution, home, tmp_path, monkeypatch):
    skills = home / '.codex/skills'
    skills.mkdir(parents=True)
    shared = tmp_path / 'other-repository/skills'
    shared.parent.mkdir()
    real_copy = installer._copy_payload
    def copy_then_change_parent(prepared):
        created = real_copy(prepared)
        skills.rename(shared)
        skills.symlink_to(shared, target_is_directory=True)
        return created
    monkeypatch.setattr(installer, '_copy_payload', copy_then_change_parent)
    with pytest.raises(installer.InstallError) as caught:
        installer.install(distribution, home)
    assert caught.value.code == 'skills_external'
    assert list(shared.iterdir()) == []
    assert not (home / '.local/lib/project-agent').is_symlink()
    assert not (home / '.local/bin/agent-session').is_symlink()
    assert not (home / '.local/state/project-agent/install.json').exists()


def test_temporary_link_name_collision_preserves_existing_file(distribution, home):
    installer.install(distribution, home)
    stable = home / '.local/lib/project-agent'
    current_target = os.readlink(stable)
    record = (home / '.local/state/project-agent/install.json').read_bytes()
    collision = stable.with_name(f'.{stable.name}.{os.getpid()}.new')
    collision.write_text('existing user file\n')
    (distribution / 'README.md').write_text('updated distribution\n')

    with pytest.raises(FileExistsError):
        installer.install(distribution, home)

    assert collision.is_file()
    assert not collision.is_symlink()
    assert collision.read_text() == 'existing user file\n'
    assert os.readlink(stable) == current_target
    assert (home / '.local/state/project-agent/install.json').read_bytes() == record


def test_rollback_rejects_corrupted_previous_payload(distribution, home):
    first = installer.install(distribution, home)
    original = Path(first['installed_payload'])
    (distribution / 'README.md').write_text('updated distribution\n')
    latest = installer.install(distribution, home)
    current = Path(latest['installed_payload'])
    stable = home / '.local/lib/project-agent'
    record = (home / '.local/state/project-agent/install.json').read_bytes()
    corrupted = original / 'tools/agent-session/agent_session/lifecycle.py'
    corrupted.write_text('raise RuntimeError("corrupted old install")\n')

    with pytest.raises(installer.InstallError) as caught:
        installer.rollback(home)

    assert str(original) in str(caught.value)
    assert stable.resolve() == current
    assert (home / '.local/bin/agent-session').resolve() == current / 'tools/agent-session/bin/agent-session'
    assert (home / '.local/state/project-agent/install.json').read_bytes() == record
    assert corrupted.read_text() == 'raise RuntimeError("corrupted old install")\n'


@pytest.mark.parametrize('tool', ['agent-session', 'project-item', 'project-board'])
def test_nonexecutable_launcher_rejects_distribution(distribution, home, tool):
    launcher = distribution / 'tools' / tool / 'bin' / tool
    launcher.chmod(0o644)
    for action in (installer.check, installer.install):
        with pytest.raises(installer.InstallError) as caught:
            action(distribution, home)
        assert str(launcher) in str(caught.value)
        assert list(home.iterdir()) == []
    assert launcher.stat().st_mode & 0o111 == 0


def test_rollback_uses_the_previous_payload_inventory(distribution, home, monkeypatch):
    original = installer.install(distribution, home)
    added_file = 'docs/new-product-asset.md'
    (distribution / added_file).write_text('A new distribution asset.\n', encoding='utf-8')
    monkeypatch.setattr(installer, 'PRODUCT_FILES', (*installer.PRODUCT_FILES, added_file))
    updated = installer.install(distribution, home)
    assert updated['installed_payload'] != original['installed_payload']
    installer.rollback(home)
    assert (home / '.local/lib/project-agent').resolve() == Path(original['installed_payload'])
    assert not (home / '.local/lib/project-agent' / added_file).exists()


def test_rollback_accepts_initial_records_without_inventory(distribution, home):
    original = installer.install(distribution, home)
    (distribution / 'README.md').write_text('Updated distribution.\n', encoding='utf-8')
    installer.install(distribution, home)
    record = home / '.local/state/project-agent/install.json'
    saved = json.loads(record.read_text(encoding='utf-8'))
    for transaction in saved['history']:
        transaction.pop('files')
    record.write_text(json.dumps(saved), encoding='utf-8')
    installer.rollback(home)
    assert (home / '.local/lib/project-agent').resolve() == Path(original['installed_payload'])
