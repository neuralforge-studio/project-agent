"""The SSH capsule contains all product guidance without a parent checkout."""

import base64
import io
from pathlib import Path
import re
import zipfile

from agent_session.remote import source_archive


def test_ssh_archive_contains_complete_skills_and_resolvable_guidance(tmp_path):
    encoded = source_archive()
    assert source_archive() == encoded
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(encoded))) as archive:
        names = set(archive.namelist())
        assert {
            'agent-session/agent_session/remote_runtime.py',
            'project-item/project_item/decide.py',
            'guidance/skills/project-team/SKILL.md',
            'guidance/skills/project-team/agents/openai.yaml',
            'guidance/skills/project-team/assets/commit-message.txt',
            'guidance/skills/project-item/SKILL.md',
            'guidance/skills/project-item/agents/openai.yaml',
            'guidance/skills/project-item/references/cr.md',
            'guidance/skills/project-item/references/decide.md',
            'guidance/docs/project-team/spec.md',
            'guidance/docs/project-team/project-registry.example.json',
            'guidance/docs/project-team/state.example.json',
        } <= names
        assert not any('codex/skills/' in name or '__pycache__' in name for name in names)
        archive.extractall(tmp_path)
    for document in (tmp_path / 'guidance').rglob('*.md'):
        for target in re.findall(r'\]\(([^)]+)\)', document.read_text()):
            path = target.split('#', 1)[0]
            if not path or path.startswith(('https:', 'http:', '~/', '/')):
                continue
            assert (document.parent / path).exists(), (document, target)


def test_product_document_links_resolve_without_parent_checkout():
    root = Path(__file__).resolve().parents[3]
    documents = [root / 'README.md', root / 'AGENTS.md']
    documents.extend((root / 'docs').rglob('*.md'))
    documents.extend((root / 'skills').rglob('*.md'))
    documents.extend((root / 'tools').glob('*/README.md'))
    for document in documents:
        for target in re.findall(r'\]\(([^)]+)\)', document.read_text()):
            path = target.split('#', 1)[0]
            if not path or path.startswith(('https:', 'http:', '~/', '/')):
                continue
            assert (document.parent / path).exists(), (document, target)
