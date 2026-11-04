"""Commands through the CLI entry with a temporary registry."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from project_item import registry
from project_item.cli import main

ENTRY = Path(__file__).resolve().parents[1] / "bin" / "project-item"

BODY = """\
## Background
Haroo에 결정 기능이 없습니다.

## Options
| 선택지 | 내용 | 결과 |
| --- | --- | --- |
| A | <script>alert(1)</script> | 결과 A |

## Recommendation
- A를 추천합니다.

## Evidence
`tool/haroo_ops.py:985`
"""


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_decision_flow_renders_the_page(project, capsys, tmp_path):
    body = tmp_path / "body.md"
    body.write_text(BODY)
    config = str(project["config"])
    code, out, _ = run(capsys, "new", "decide", "--config", config, "--project", "demo",
                       "--title", "결정 페이지를 <공용>으로 둘까요?", "--urgency", "high",
                       "--blocks", "Haroo 이전", "--body-file", str(body))
    assert code == 0
    item = project["decide"] / "open" / f"{out.split()[1].rsplit('/', 1)[1]}"
    assert item.exists() and "format:" not in out
    page = project["decide"] / "decide.html"
    html = page.read_text()
    assert "결정 대기 1건" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html and "<script>" not in html
    assert "결정 페이지를 &lt;공용&gt;으로 둘까요?" in html
    item_id = item.stem
    code, out, _ = run(capsys, "move", "--config", config, "--project", "demo", item_id, "done",
                       "--outcome", "decided A", "--by", "user", "--note", f'"{item_id} A"')
    assert code == 0
    assert (project["decide"] / "done" / item.name).exists()
    html = page.read_text()
    assert "결정 대기 0건" in html and "결정된 항목 1건" in html
    code, out, _ = run(capsys, "ls", "decide", "--config", config, "--project", "demo", "--all")
    assert f"decide done     high   {item_id}" in out


def test_cwd_selects_the_project_and_requester_is_recorded(project, capsys, monkeypatch):
    monkeypatch.chdir(project["base"])
    config = str(project["config"])
    code, out, _ = run(capsys, "new", "cr", "--config", config, "--area", "TOOL", "--title", "Own finding")
    assert code == 0
    own = project["cr"] / "open" / "TOOL-001-own-finding.md"
    assert "Requester" not in own.read_text()
    monkeypatch.chdir(project["other"])
    code, out, _ = run(capsys, "new", "cr", "--config", config, "--project", "demo", "--area", "TOOL",
                       "--title", "Request from other")
    text = (project["cr"] / "open" / "TOOL-002-request-from-other.md").read_text()
    assert f"- Requester: other, {project['other']}," in text
    assert "notify:" in out


def test_check_exit_codes_and_duplicates(project, capsys):
    config = ["--config", str(project["config"]), "--project", "demo"]
    assert run(capsys, "new", "cr", *config, "--area", "TOOL", "--title", "a")[0] == 0
    code, out, _ = run(capsys, "check", "cr", *config)
    assert code == 0 and "-- cr: 1 checked, 0 duplicate IDs, 0 with violations" in out
    copy = project["cr"] / "open" / "TOOL-001-copy.md"
    copy.write_text((project["cr"] / "open" / "TOOL-001-a.md").read_text())
    code, out, _ = run(capsys, "check", "cr", *config)
    assert code == 1 and "duplicate ID TOOL-001: open/TOOL-001-a.md, open/TOOL-001-copy.md" in out
    code, out, _ = run(capsys, "check", "cr", str(copy), *config)
    assert code == 1


def test_unset_path_is_refused_without_a_default(project, capsys):
    code, _, err = run(capsys, "new", "decide", "--config", str(project["config"]), "--project", "other",
                       "--title", "q")
    assert code == 2 and "item_path_unset" in err
    assert not (project["other"] / "decide").exists()


def test_legacy_cr_directory_is_refused(project, capsys, no_legacy):
    no_legacy.write_text(json.dumps({"programs": {"demo_tool": {
        "repo": str(project["base"]), "cr_dir": "cr/open", "owner_cwd": [str(project["base"])]}}}))
    code, _, err = run(capsys, "ls", "cr", "--config", str(project["config"]), "--project", "demo")
    assert code == 2 and "item_path_duplicate" in err


def test_unknown_project_name(project, capsys):
    code, _, err = run(capsys, "ls", "--config", str(project["config"]), "--project", "missing")
    assert code == 2 and "project_not_found" in err


def test_entry_script_runs_the_package(project):
    env = {**os.environ, "HOME": os.environ["HOME"]}
    result = subprocess.run([str(ENTRY), "projects", "--config", str(project["config"])],
                            capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert "demo" in result.stdout and "other" in result.stdout
