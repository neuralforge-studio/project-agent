"""Public item integrations keep domain reads and writes independent of session control."""
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from project_item import api, decide, render, store
from project_item.errors import ItemError


CR_TEXT = """# TOOL-001: Public assignment

- Opened: 2026-11-08
- Scope: public item integration
- Severity: S3
- Mode: write

## Symptom

Existing CR.

## Evidence

`source.py:1`

## Contract

Keep one authoritative CR.

## Disposition

## Implementation

Assign this CR.

## Verification

Read its state and baseline.

## Result

Original.
"""


def test_domain_imports_do_not_load_session_or_provider_adapters():
    tool = Path(__file__).resolve().parents[1]
    program = ("import sys; sys.path.insert(0, sys.argv[1]); "
               "from project_item import store, assign, cr, decide, api; "
               "assert not any(name == 'agent_session' or name.startswith('agent_session.') "
               "for name in sys.modules)")
    result = subprocess.run([sys.executable, "-I", "-c", program, str(tool)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_legacy_error_import_is_the_domain_error():
    from project_item.registry import ItemError as LegacyItemError
    assert LegacyItemError is ItemError is api.ItemError


def test_assignment_public_boundary_preserves_state_and_baseline(tmp_path):
    root = tmp_path / "cr"
    source = root / "todo/TOOL-001-public.md"
    source.parent.mkdir(parents=True)
    source.write_text(CR_TEXT, encoding="utf-8")
    job = api.lookup_cr(root, "TOOL-001")
    assert (job["state"], job["title"], job["mode"], job["base"]) == (
        "todo", "Public assignment", "write", None)
    assigned = api.claim_cr(root, "TOOL-001")
    assert assigned["state"] == "in-progress" and not source.exists()
    baseline = {"base_hash": "a" * 40, "base_commit_time": "2026-11-08T09:00:00+09:00"}
    api.set_cr_base(root, "TOOL-001", baseline)
    assert api.lookup_cr(root, "TOOL-001")["base"] == baseline
    (row,) = api.cr_items(root)["in-progress"]
    assert row["id"] == "TOOL-001" and row["sections"]["Result"] == "Original."
    assert api.read_cr_markdown(root, row, "in-progress").startswith("# TOOL-001:")
    api.unclaim_cr(root, "TOOL-001")
    assert api.lookup_cr(root, "TOOL-001")["state"] == "todo"


def test_result_sync_preserves_other_sections_and_refuses_conflicts(tmp_path):
    root = tmp_path / "cr"
    source = root / "in-progress/TOOL-001-public.md"
    source.parent.mkdir(parents=True)
    source.write_text(CR_TEXT.replace("Existing CR.", "Leader addition."), encoding="utf-8")
    remote = CR_TEXT.replace("Original.", "Worker report.")
    previous = api.sync_cr_result(root, "TOOL-001", CR_TEXT, remote)
    assert "Leader addition." in source.read_text(encoding="utf-8")
    assert source.read_text(encoding="utf-8").endswith("Worker report.\n")
    source.write_text(source.read_text(encoding="utf-8").replace("Worker report.", "Another report."), encoding="utf-8")
    before = source.read_bytes()
    with pytest.raises(ItemError) as caught:
        api.sync_cr_result(root, "TOOL-001", CR_TEXT, remote, previous)
    assert caught.value.code == "remote_result_conflict" and source.read_bytes() == before
    with pytest.raises(ItemError) as caught:
        api.sync_cr_result(root, "TOOL-001", CR_TEXT, remote.replace("Existing CR.", "Remote change."))
    assert caught.value.code == "remote_result_invalid" and source.read_bytes() == before


def test_open_decision_query_does_not_read_closed_history(tmp_path, monkeypatch):
    root = tmp_path / "decide"
    path = root / "open/D-20261108-01.md"
    path.parent.mkdir(parents=True)
    path.write_text("# D-20261108-01: Waiting\n\n- Opened: 2026-11-08\n- Urgency: high\n\n"
                    "## Background\n\nContext.\n", encoding="utf-8")
    original = store.item_files

    def only_open(kind, item_root, state):
        assert state == "open", "An open-only query must not read closed history."
        return original(kind, item_root, state)

    monkeypatch.setattr(store, "item_files", only_open)
    (item,) = api.decision_items(root, states=("open",))
    assert (item["id"], item["title"], item["display_state"]) == (
        "D-20261108-01", "Waiting", "결정 대기")
    assert item["headers"]["Urgency"] == "high"


def test_status_query_retains_an_id_when_its_title_read_fails(tmp_path, monkeypatch):
    root = tmp_path / "decide"
    path = root / "open/D-20261108-01.md"
    path.parent.mkdir(parents=True)
    path.write_text("# D-20261108-01: Waiting\n", encoding="utf-8")

    def unreadable(*args, **kwargs):
        raise OSError("temporarily unreadable")

    monkeypatch.setattr(decide, "parse", unreadable)
    assert api.open_decisions(root) == {"D-20261108-01": ""}
    monkeypatch.setattr(store, "item_files", unreadable)
    with pytest.raises(OSError, match="temporarily unreadable"):
        api.open_decisions(root)


def test_answer_receipt_survives_a_page_failure(tmp_path, monkeypatch):
    root = tmp_path / "decide"
    path = root / "open/D-20261108-01.md"
    path.parent.mkdir(parents=True)
    path.write_text("# D-20261108-01: Waiting\n\n- Opened: 2026-11-08 09:00\n- Urgency: high\n- Blocks: Review\n\n"
                    "## Background\n\nContext.\n\n## Options\n\nA.\n\n## Recommendation\n\nA.\n\n"
                    "## Evidence\n\n`a.py:1`\n", encoding="utf-8")
    project = SimpleNamespace(project_id="demo", path_decide=root, path_cr=None)

    def fail_page(*args, **kwargs):
        raise OSError("read-only page")

    monkeypatch.setattr(render, "render", fail_page)
    receipt = api.answer_decision(project, "D-20261108-01", "A\nSecond line")
    assert receipt["page_error"] == {"code": "OSError", "message": "read-only page"}
    assert not path.exists() and Path(receipt["path"]).is_file()
    parsed = api.DECIDE.fmt.parse(Path(receipt["path"]), "answered")
    assert api.DECIDE.fmt.answer_text(parsed) == "A\nSecond line"
