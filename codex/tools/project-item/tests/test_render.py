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
    assert "결정 대기 2건 · 결정됨 1건 · 갱신 2026-11-04 12:00" in html
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
    assert "<title>&lt;demo&gt; 결정 대기</title>" in html


def test_markdown_subset():
    out = render.markdown("p1\np2\n\n- a\n  - b\n- c\n\n1. x\n\n```\n<raw>\n```\n\n| h |\n| --- |\n| v |")
    assert "<p>p1 p2</p>" in out
    assert out.count("<ul>") == 2 and "<ol>" in out
    assert "<pre>&lt;raw&gt;</pre>" in out
    assert "<th>h</th>" in out and "<td>v</td>" in out
