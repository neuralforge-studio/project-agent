"""The decision page: escaping, order and the markdown subset."""
import datetime as dt

from project_item import render


def item(item_id, urgency, state="open", title="질문", sections=None, **headers):
    return {"id": item_id, "title": title, "state": state,
            "headers": {"Urgency": urgency, "Opened": "2026-11-04 10:00", **headers},
            "sections": sections or [("Recommendation", "- A를 추천합니다.")]}


def test_open_items_sorted_by_urgency_and_done_items_folded():
    html = render.page("demo", [item("D-20261104-01", "low"), item("D-20261104-02", "high"),
                                item("D-20261103-01", "normal", state="done", Outcome="decided B")],
                       now=dt.datetime(2026, 11, 4, 12, 0))
    assert html.index('href="#D-20261104-02"') < html.index('href="#D-20261104-01"')
    assert "결정 대기 2건 · 답변 접수 0건 · 반영 중 0건 · 완료 1건 · 갱신 2026-11-04 12:00" in html
    folded = html.split('<details class="closed">')[1]
    assert "D-20261103-01" in folded and "decided B" in folded
    assert "<td>A를 추천합니다.</td>" in html


def test_every_text_is_escaped():
    html = render.page("<demo>", [item("D-20261104-01", "high", title="<b>x</b>",
                                       sections=[("Background", "a <img src=x> `<code>`"),
                                                 ("Options", "| A | <i>y</i> |\n| --- | --- |\n| 1 | 2 |")],
                                       Blocks="<script>")])
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html
    assert "<img" not in html and "<i>" not in html and "<script>" not in html
    assert "<code>&lt;code&gt;</code>" in html
    assert "<title>&lt;demo&gt; 결정 현황</title>" in html


def test_decision_stages_follow_related_cr_without_copying_its_state():
    waiting = item("D-20261107-01", "high", Related="SESSION-020")
    received = item("D-20261107-02", "normal", state="answered", Related="SESSION-020")
    confirmed = item("D-20261107-03", "normal", state="done", Related="SESSION-020")
    assert render.decision_stage(waiting, {"SESSION-020": "open"}) == "결정 대기"
    assert render.decision_stage(received, {"SESSION-020": "todo"}) == "답변 접수"
    for cr_state in ("open", "todo", "in-progress"):
        assert render.decision_stage(confirmed, {"SESSION-020": cr_state}) == "반영 중"
    assert render.decision_stage(confirmed, {"SESSION-020": "done"}) == "완료"
    assert render.decision_stage(confirmed, {}) == "반영 중"
    assert render.decision_stage(item("D-20261107-04", "low", state="done"), {}) == "완료"
    assert render.decision_stage(item("D-20261107-05", "low", state="done",
                                      Related="D-20261107-01"), {}) == "완료"


def test_withdrawn_decision_is_complete_while_related_cr_waits():
    withdrawn = item("D-20261107-06", "normal", state="done", Outcome="withdrawn", Related="TOOL-001")
    merged = item("D-20261107-07", "normal", state="done", Outcome="merged D-20261107-08",
                  Related="TOOL-001")
    states = {"TOOL-001": "todo"}
    assert render.decision_stage(withdrawn, states) == "완료"
    assert render.decision_stage(merged, states) == "반영 중"
    html = render.page("demo", [withdrawn], states=states)
    assert "반영 중 0건 · 완료 1건" in html
    assert "<dt>결론</dt><dd>withdrawn</dd>" in html


def test_markdown_subset():
    out = render.markdown("p1\np2\n\n- a\n  - b\n- c\n\n1. x\n\n```\n<raw>\n```\n\n| h |\n| --- |\n| v |")
    assert "<p>p1 p2</p>" in out
    assert out.count("<ul>") == 2 and "<ol>" in out
    assert "<pre>&lt;raw&gt;</pre>" in out
    assert "<th>h</th>" in out and "<td>v</td>" in out


def test_markdown_blockquote():
    out = render.markdown("앞\n\n> 제목 <b>\n>\n> - 하나\n> - 둘\n>\n> 끝\n\n뒤")
    assert out.count("<blockquote>") == 1 and out.count("</blockquote>") == 1
    inner = out.split("<blockquote>")[1].split("</blockquote>")[0]
    assert "<p>제목 &lt;b&gt;</p>" in inner
    assert inner.count("<li>") == 2 and "<ul>" in inner
    assert "<p>끝</p>" in inner
    assert "&gt;" not in out.replace("&lt;b&gt;", "")
    assert out.startswith("<p>앞</p>") and out.endswith("<p>뒤</p>")


def test_sections_keep_fenced_markdown_headings_in_their_body(tmp_path):
    path = tmp_path / "D-20261107-01.md"
    path.write_text("# D-20261107-01: 질문\n\n"
                    "## Background\n실제 배경.\n\n"
                    "~~~md\n## Disposition\n예시입니다.\n~~~\n\n"
                    "````md\n## Recommendation\n```\n## Result\n````\n\n"
                    "## Options\n실제 선택지.\n", encoding="utf-8")
    parts = render.sections(path)
    assert [name for name, _ in parts] == ["Background", "Options"]
    assert "## Disposition" in parts[0][1] and "## Result" in parts[0][1]
    assert parts[1][1] == "실제 선택지."
