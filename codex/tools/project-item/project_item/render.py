"""Render the decision items of one project as one self-contained HTML page.

The page is derived output. The item files stay the source; the page never takes input.
The reads and the decision stage come from read.py and decide.py.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
from pathlib import Path
from typing import Mapping

from . import store
from .decide import decision_stage
from .read import cr_states, load

PAGE_NAME = "decide.html"
LABELS = {"Background": "배경", "Options": "선택지", "Recommendation": "추천", "Evidence": "근거",
          "Disposition": "판정 기록", "Result": "반영", "Draft": "게시 초안"}
URGENCY_KO = {"high": "높음", "normal": "보통", "low": "낮음"}
URGENCY_ORDER = {"high": 0, "normal": 1, "low": 2}
HEADER_FACTS = (("Blocks", "막는 것"), ("Related", "관련"), ("Opened", "요청"), ("Outcome", "결론"))


# ---------------------------------------------------------------- markdown subset
def inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)


LIST_RE = re.compile(r"^(\s*)(-|\d+\.)\s+(.*)$")


def markdown(text: str) -> str:
    """Paragraphs, nested lists, tables, code fences and blockquotes. Everything else is plain text."""
    out: list[str] = []
    para: list[str] = []
    lines = text.splitlines()
    i = 0

    def flush():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            flush()
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append("<pre>" + html.escape("\n".join(lines[i + 1:j])) + "</pre>")
            i = j + 1
        elif line.startswith(">"):
            flush()
            quoted = []
            while i < len(lines) and lines[i].startswith(">"):
                quoted.append(re.sub(r"^> ?", "", lines[i]))
                i += 1
            out.append("<blockquote>" + markdown("\n".join(quoted)) + "</blockquote>")
        elif line.lstrip().startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                head = "".join(f"<th>{inline(c)}</th>" for c in rows[0])
                body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
                               for r in rows[1:])
                out.append(f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
                           f"<tbody>{body}</tbody></table></div>")
        elif LIST_RE.match(line):
            flush()
            stack: list[tuple[int, str]] = []
            while i < len(lines) and LIST_RE.match(lines[i]):
                m = LIST_RE.match(lines[i])
                depth = len(m.group(1).expandtabs(4)) // 2
                tag = "ol" if m.group(2)[0].isdigit() else "ul"
                while stack and stack[-1][0] > depth:
                    out.append(f"</li></{stack.pop()[1]}>")
                if stack and stack[-1][0] == depth:
                    out.append("</li>")
                else:
                    out.append(f"<{tag}>")
                    stack.append((depth, tag))
                out.append("<li>" + inline(m.group(3)))
                i += 1
            while stack:
                out.append(f"</li></{stack.pop()[1]}>")
        elif line.startswith("### "):
            flush()
            out.append(f"<h4>{inline(line[4:])}</h4>")
            i += 1
        elif not line.strip():
            flush()
            i += 1
        else:
            para.append(line.strip())
            i += 1
    flush()
    return "\n".join(out)


# ---------------------------------------------------------------- items
def _first_line(body: str) -> str:
    for line in body.splitlines():
        if line.strip() and not line.lstrip().startswith("|"):
            return re.sub(r"^\s*(-|\d+\.)\s+", "", line).strip()
    return ""


def _article(item: dict, stage: str) -> str:
    urgency = item["headers"].get("Urgency", "normal")
    facts = "".join(f"<dt>{label}</dt><dd>{inline(item['headers'][key])}</dd>"
                    for key, label in HEADER_FACTS if item["headers"].get(key))
    parts = []
    encoded_answer = item["headers"].get("Answer")
    if encoded_answer:
        try:
            answer = json.loads(encoded_answer)
        except ValueError:
            answer = None
        if isinstance(answer, str):
            parts.append(f'<section><div class="sh">답변 원문</div><pre>{html.escape(answer)}</pre></section>')
    for name, body in item["sections"]:
        if not body:
            continue
        cls = ' class="rec"' if name == "Recommendation" else ""
        parts.append(f'<section{cls}><div class="sh">{html.escape(LABELS.get(name, name))}</div>'
                     f"{markdown(body)}</section>")
    return (f'<article id="{html.escape(item["id"])}" class="u-{html.escape(urgency)}">'
            f'<div class="ahead"><span class="id">{html.escape(item["id"])}</span>'
            f'<span class="pill stage">{stage}</span>'
            f'<span class="pill u-{html.escape(urgency)}">긴급도 {URGENCY_KO.get(urgency, html.escape(urgency))}</span>'
            f"<h3>{inline(item['title'])}</h3></div>"
            f'<dl class="facts">{facts}</dl>{"".join(parts)}</article>')


CSS = """
:root{--bg:#f5f6f8;--surface:#fff;--fg:#1b2230;--muted:#5b6577;--line:#d9dde5;--accent:#1f5f8b;
--accent-soft:#e3eef6;--hi:#b3261e;--hi-soft:#fbe7e5;--mid:#8a5a00;--mid-soft:#fbf0d9;--lo:#3d6b45;
--lo-soft:#e4f1e6;--code:#eef0f4}
@media (prefers-color-scheme:dark){:root{--bg:#12161d;--surface:#1a2029;--fg:#e4e8ef;--muted:#9aa4b5;
--line:#2e3644;--accent:#7fb6dc;--accent-soft:#1d3346;--hi:#f28b82;--hi-soft:#3d1f1d;--mid:#e6b85c;
--mid-soft:#3a2f17;--lo:#8cc79a;--lo-soft:#1d3323;--code:#232a35;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--fg);font-family:system-ui,"Noto Sans KR",sans-serif;
font-size:15px;line-height:1.6}
.wrap{max-width:980px;margin:0 auto;padding:28px 16px 64px;display:flex;flex-direction:column;gap:24px}
h1{font-size:1.5rem;margin:0}.meta{color:var(--muted);font-size:.9rem}
.how{background:var(--accent-soft);border-radius:8px;padding:10px 14px;font-size:.92rem}
h2{font-size:1rem;margin:0 0 8px;color:var(--muted)}
.scroll{overflow-x:auto;max-width:100%}
table{border-collapse:collapse;width:100%;font-size:.92rem}
th,td{text-align:left;vertical-align:top;padding:6px 10px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600}
a{color:var(--accent)}
.pill{display:inline-block;border-radius:999px;padding:1px 9px;font-size:.78rem;font-weight:600}
.pill.stage{background:var(--accent-soft);color:var(--accent)}
.pill.u-high{background:var(--hi-soft);color:var(--hi)}.pill.u-normal{background:var(--mid-soft);color:var(--mid)}
.pill.u-low{background:var(--lo-soft);color:var(--lo)}
article{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px 20px;
display:flex;flex-direction:column;gap:10px;min-width:0}
article.u-high{border-left:4px solid var(--hi)}article.u-normal{border-left:4px solid var(--mid)}
article.u-low{border-left:4px solid var(--lo)}
.ahead{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 12px}
.ahead .id{font-family:ui-monospace,monospace;font-size:.85rem;color:var(--muted)}
.ahead h3{flex-basis:100%;margin:0;font-size:1.1rem}
.facts{display:grid;grid-template-columns:max-content 1fr;gap:2px 14px;font-size:.9rem;margin:0}
.facts dt{color:var(--muted)}.facts dd{margin:0;min-width:0}
.sh{font-size:.82rem;font-weight:700;color:var(--accent)}
section p,section ul,section ol{margin:4px 0}section ul,section ol{padding-left:1.3em}
.rec{background:var(--accent-soft);border-radius:8px;padding:8px 12px}
code{font-family:ui-monospace,monospace;font-size:.86em;background:var(--code);padding:1px 5px;border-radius:4px;
overflow-wrap:anywhere}
blockquote{margin:6px 0;padding:2px 0 2px 12px;border-left:3px solid var(--line);color:var(--muted)}
blockquote>:first-child{margin-top:0}blockquote>:last-child{margin-bottom:0}
pre{font-family:ui-monospace,monospace;font-size:.84rem;background:var(--code);padding:12px;border-radius:6px;
white-space:pre-wrap}
details.closed{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 16px}
details.closed summary{cursor:pointer;font-weight:600}
.empty{color:var(--muted)}
@media (max-width:560px){.facts{grid-template-columns:1fr}}
"""


def page(project_id: str, items: list[dict], now: dt.datetime | None = None,
         states: Mapping[str, str] | None = None) -> str:
    stamp = (now or dt.datetime.now()).strftime("%Y-%m-%d %H:%M")
    states = states or {}
    live = sorted((it for it in items if it["state"] == "open"),
                  key=lambda it: (URGENCY_ORDER.get(it["headers"].get("Urgency"), 9),
                                  it["headers"].get("Opened", ""), it["id"]))
    received = sorted((it for it in items if it["state"] == "answered"), key=lambda it: it["id"], reverse=True)
    processing = sorted((it for it in items if it["state"] == "done" and
                         decision_stage(it, states) == "반영 중"), key=lambda it: it["id"], reverse=True)
    closed = sorted((it for it in items if it["state"] == "done" and
                     decision_stage(it, states) == "완료"), key=lambda it: it["id"], reverse=True)
    rows = "".join(
        f'<tr><td><a href="#{html.escape(it["id"])}">{html.escape(it["id"])}</a></td>'
        f"<td>{inline(it['title'])}</td>"
        f'<td>{URGENCY_KO.get(it["headers"].get("Urgency", ""), "")}</td>'
        f"<td>{inline(it['headers'].get('Blocks', ''))}</td>"
        f"<td>{inline(_first_line(dict(it['sections']).get('Recommendation', '')))}</td></tr>"
        for it in live)
    summary = (f'<div class="scroll"><table><thead><tr><th>ID</th><th>질문</th><th>긴급도</th>'
               f"<th>막는 것</th><th>추천</th></tr></thead><tbody>{rows}</tbody></table></div>"
               if live else '<p class="empty">결정을 기다리는 항목이 없습니다.</p>')
    closed_html = ""
    if closed:
        closed_html = (f'<details class="closed"><summary>완료 {len(closed)}건</summary>'
                       + "".join(_article(it, "완료") for it in closed) + "</details>")
    title = f"{html.escape(project_id)} 결정 현황"
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<header>
<h1>{title}</h1>
<div class="meta">결정 대기 {len(live)}건 · 답변 접수 {len(received)}건 · 반영 중 {len(processing)}건 · 완료 {len(closed)}건 · 갱신 {stamp}</div>
</header>
<div class="how">답하는 방법: 담당 session의 터미널에 <code>D-YYYYMMDD-NN A</code>처럼 ID와 선택을 입력하십시오.
이 페이지는 입력을 받지 않습니다.</div>
<section><h2>요약</h2>{summary}</section>
<section style="display:flex;flex-direction:column;gap:16px"><h2>결정 대기</h2>{"".join(_article(it, "결정 대기") for it in live)}</section>
<section style="display:flex;flex-direction:column;gap:16px"><h2>답변 접수</h2>{"".join(_article(it, "답변 접수") for it in received)}</section>
<section style="display:flex;flex-direction:column;gap:16px"><h2>반영 중</h2>{"".join(_article(it, "반영 중") for it in processing)}</section>
{closed_html}
</div>
</body>
</html>
"""


def render(project_id: str, root: Path, out: Path | None = None, cr_root: Path | None = None) -> Path:
    """Read the items and write the page under the root lock, so that a late render cannot
    write an older state over a newer page."""
    target = out or root / PAGE_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    with store.root_lock(root):
        text = page(project_id, load(root), states=cr_states(cr_root))
        store._pause("render")
        temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, target)
    return target
