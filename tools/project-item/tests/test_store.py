"""ID issue under the per-root lock, transitions of `move`, and duplicate detection."""
import datetime as dt
import multiprocessing
import threading
import time
from pathlib import Path

import pytest

from project_item_testing import git, git_init
from wait_limit import command_timeout  # tools/conftest.py puts tools/tests on sys.path
from project_item import store
from project_item.kinds import CR, DECIDE
from project_item.registry import ItemError

CR_BODY = "## Symptom\ns\n\n## Evidence\n`a.py:1`\n\n## Contract\nc\n"


def cr_text(item_id, title="t", extra=""):
    return (f"# {item_id}: {title}\n\n- Opened: 2026-11-04\n- Scope: demo\n- Severity: S2\n{extra}\n"
            + CR_BODY)


def decision_text(item_id, extra=""):
    return (f"# {item_id}: 질문\n\n- Opened: 2026-11-04 10:00\n- Urgency: normal\n{extra}\n"
            "## Background\nb\n\n## Options\n| 선택지 | 내용 | 결과 |\n| --- | --- | --- |\n| A | a | r |\n\n"
            "## Recommendation\nA\n\n## Evidence\ne\n")


def new_cr(root, title):
    return store.new_cr(root, "TOOL", title, lambda item_id: cr_text(item_id, title))


def _process_new(args):
    root, title, home = args
    import os
    os.environ["HOME"] = home
    return str(new_cr(Path(root), title))


def test_concurrent_new_in_processes_gets_distinct_ids(tmp_path, isolated_home):
    root = tmp_path / "cr"
    titles = [f"title {n}" for n in range(8)]
    with multiprocessing.get_context("spawn").Pool(8) as pool:
        paths = pool.map(_process_new, [(str(root), t, str(isolated_home)) for t in titles])
    ids = sorted(store.file_id(CR, Path(p)) for p in paths)
    assert ids == [f"TOOL-{n:03d}" for n in range(1, 9)]


def test_lock_serializes_number_read_and_create(tmp_path, monkeypatch):
    """Without the lock both threads read the same highest number inside the pause."""
    root = tmp_path / "cr"
    monkeypatch.setattr(store, "_pause", lambda step: time.sleep(0.3))
    results = []
    threads = [threading.Thread(target=lambda t=t: results.append(new_cr(root, t))) for t in ("alpha", "beta")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(p.name for p in results) in (
        ["TOOL-001-alpha.md", "TOOL-002-beta.md"], ["TOOL-001-beta.md", "TOOL-002-alpha.md"])


def test_new_waits_for_a_move_of_the_same_root(tmp_path, monkeypatch):
    root = tmp_path / "cr"
    new_cr(root, "first")
    order = []

    def pause(step):
        if step == "move":
            order.append("move-start")
            time.sleep(0.4)
            order.append("move-end")

    monkeypatch.setattr(store, "_pause", pause)
    mover = threading.Thread(target=lambda: store.move(CR, root, "TOOL-001", "done", outcome="waived",
                                                       by="user", note="intended"))
    mover.start()
    time.sleep(0.1)
    created = new_cr(root, "second")
    order.append("new-end")
    mover.join()
    assert order == ["move-start", "move-end", "new-end"]
    assert created.name == "TOOL-002-second.md"
    assert sorted(p.name for p in root.rglob("*.md")) == ["TOOL-001-first.md", "TOOL-002-second.md"]
    assert (root / "done" / "TOOL-001-first.md").exists()


def test_decision_ids_count_per_day(tmp_path):
    root = tmp_path / "decide"
    day = dt.date(2026, 11, 4)
    first = store.new_decide(root, decision_text, day)
    (root / "done").mkdir()
    first.rename(root / "done" / first.name)
    second = store.new_decide(root, decision_text, day)
    third = store.new_decide(root, decision_text, dt.date(2026, 11, 5))
    assert [first.name, second.name, third.name] == [
        "D-20261104-01.md", "D-20261104-02.md", "D-20261105-01.md"]


def test_answer_is_recorded_once_and_preserves_exact_words(tmp_path):
    root = tmp_path / "decide"
    item_id = "D-20261104-01"
    store.new_decide(root, decision_text, dt.date(2026, 11, 4))
    words = "A\n이유: 첫째\n\n## 사용자 메모\n끝\n"
    answered = store.answer_decide(root, item_id, words)
    assert answered == root / "answered" / f"{item_id}.md"
    assert DECIDE.fmt.answer_text(DECIDE.fmt.parse(answered, "answered")) == words
    before = answered.read_text()
    with pytest.raises(ItemError) as error:
        store.answer_decide(root, item_id, words)
    assert error.value.code == "decide_not_open"
    assert answered.read_text() == before


@pytest.mark.parametrize("separator", ["\x85", "\u2028", "\u2029"])
def test_unicode_line_separator_survives_answer_and_leader_confirmation(tmp_path, separator):
    root = tmp_path / "decide"
    item_id = "D-20261104-01"
    answer = f"A{separator}B"
    store.new_decide(root, decision_text, dt.date(2026, 11, 4))
    answered = store.answer_decide(root, item_id, answer)
    assert DECIDE.fmt.answer_text(DECIDE.fmt.parse(answered, "answered")) == answer
    assert DECIDE.fmt.check(DECIDE.fmt.parse(answered, "answered")) == []
    done = store.move(DECIDE, root, item_id, "done", outcome="decided A", by="Leader")
    assert f'사용자 답변 원문: "A\\u{ord(separator):04x}B"' in done.read_text(encoding="utf-8")
    assert DECIDE.fmt.check(DECIDE.fmt.parse(done, "done")) == []


def test_concurrent_decision_answers_accept_only_one(tmp_path):
    root = tmp_path / "decide"
    item_id = "D-20261104-01"
    store.new_decide(root, decision_text, dt.date(2026, 11, 4))
    outcomes = []

    def answer(words):
        try:
            store.answer_decide(root, item_id, words)
            outcomes.append(("accepted", words))
        except ItemError as error:
            outcomes.append((error.code, words))

    threads = [threading.Thread(target=answer, args=(words,)) for words in ("A", "B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(code for code, _ in outcomes) == ["accepted", "decide_not_open"]
    answered = root / "answered" / f"{item_id}.md"
    assert DECIDE.fmt.answer_text(DECIDE.fmt.parse(answered, "answered")) == next(
        words for code, words in outcomes if code == "accepted")


@pytest.mark.parametrize("answer, code", [(None, "answer_invalid"), (" ", "answer_empty"),
                                          ("A\x00B", "answer_invalid"),
                                          ("가" * 5462, "answer_too_large")])
def test_invalid_answer_does_not_change_open_decision(tmp_path, answer, code):
    root = tmp_path / "decide"
    source = store.new_decide(root, decision_text, dt.date(2026, 11, 4))
    before = source.read_text()
    with pytest.raises(ItemError) as error:
        store.answer_decide(root, "D-20261104-01", answer)
    assert error.value.code == code
    assert source.read_text() == before
    assert not (root / "answered").exists()


@pytest.mark.parametrize("source, target", [("open", "open"), ("done", "deferred")])
def test_transitions_outside_the_table_change_nothing(tmp_path, source, target):
    root = tmp_path / "cr"
    path = root / source / "TOOL-001-t.md"
    path.parent.mkdir(parents=True)
    text = cr_text("TOOL-001", extra="- Outcome: waived\n" if source == "done" else "")
    path.write_text(text)
    with pytest.raises(ItemError) as error:
        store.move(CR, root, "TOOL-001", target, by="user", note="n")
    assert error.value.code == "invalid_transition"
    assert path.read_text() == text


def test_fixed_reaches_done_only_from_todo(tmp_path):
    root = tmp_path / "cr"
    new_cr(root, "t")
    with pytest.raises(ItemError) as error:
        store.move(CR, root, "TOOL-001", "done", outcome="fixed", by="owner")
    assert error.value.code == "invalid_transition"


def test_destination_format_is_checked_before_the_move(tmp_path):
    root = tmp_path / "cr"
    path = new_cr(root, "t")
    before = path.read_text()
    with pytest.raises(ItemError) as error:
        store.move(CR, root, "TOOL-001", "todo", by="owner", note="fix it")
    assert error.value.code == "format_invalid"
    assert "Implementation" in error.value.message
    assert path.read_text() == before
    assert not (root / "todo").exists()


def test_decision_round_trip_writes_outcome_and_disposition(tmp_path):
    root = tmp_path / "decide"
    store.new_decide(root, decision_text, dt.date(2026, 11, 4))
    store.answer_decide(root, "D-20261104-01", "D-20261104-01 A")
    done = store.move(DECIDE, root, "D-20261104-01", "done", outcome="decided A", by="Leader",
                      today=dt.date(2026, 11, 4))
    text = done.read_text()
    assert "- Outcome: decided A" in text.split("## Background")[0]
    assert text.rstrip().endswith('- 2026-11-04 Leader: answered -> done, Outcome decided A. '
                                    '사용자 답변 원문: "D-20261104-01 A"')
    assert DECIDE.fmt.check(DECIDE.fmt.parse(done, "done")) == []
    reopened = store.move(DECIDE, root, "D-20261104-01", "open", by="user", note="선택을 바꿈",
                          today=dt.date(2026, 11, 5))
    text = reopened.read_text()
    assert "Outcome" not in text.split("## Background")[0]
    assert "Answer" not in text.split("## Background")[0]
    assert "- 2026-11-05 user: done -> open. 선택을 바꿈" in text
    assert text.index("## Disposition") > text.index("## Evidence")
    assert DECIDE.fmt.check(DECIDE.fmt.parse(reopened, "open")) == []


def test_answered_decision_can_reopen_for_changed_answer(tmp_path):
    root = tmp_path / "decide"
    item_id = "D-20261104-01"
    store.new_decide(root, decision_text, dt.date(2026, 11, 4))
    store.answer_decide(root, item_id, "A\n이유")
    reopened = store.move(DECIDE, root, item_id, "open", by="user", note="B로 변경")
    assert DECIDE.fmt.answer_text(DECIDE.fmt.parse(reopened, "open")) is None
    assert "open -> answered" in reopened.read_text()
    assert 'answered -> open. B로 변경 이전 답변 원문: "A\\n이유"' in reopened.read_text()
    answered = store.answer_decide(root, item_id, "B")
    assert DECIDE.fmt.answer_text(DECIDE.fmt.parse(answered, "answered")) == "B"


def test_reopen_needs_a_reason(tmp_path):
    root = tmp_path / "decide"
    store.new_decide(root, decision_text, dt.date(2026, 11, 4))
    store.move(DECIDE, root, "D-20261104-01", "done", outcome="withdrawn", by="user", note="n")
    with pytest.raises(ItemError) as error:
        store.move(DECIDE, root, "D-20261104-01", "open")
    assert error.value.code == "reason_missing"


@pytest.mark.parametrize("options", [{"outcome": "fixed"}, {"note": "n"}])
def test_outcome_or_note_without_a_decider_is_refused(tmp_path, options):
    root = tmp_path / "cr"
    path = root / "todo" / "TOOL-001-t.md"
    path.parent.mkdir(parents=True)
    path.write_text(cr_text("TOOL-001"))
    with pytest.raises(ItemError) as error:
        store.move(CR, root, "TOOL-001", "done", **options)
    assert error.value.code == "decider_missing"
    assert path.read_text() == cr_text("TOOL-001") and not (root / "done").exists()


def test_disposition_goes_before_implementation_in_a_cr(tmp_path):
    root = tmp_path / "cr"
    path = root / "todo" / "TOOL-001-t.md"
    path.parent.mkdir(parents=True)
    path.write_text(cr_text("TOOL-001") + "\n## Implementation\ni\n\n## Verification\nv\n\n## Result\nr\n")
    moved = store.move(CR, root, "TOOL-001", "done", outcome="fixed", by="owner", note="abc123",
                       today=dt.date(2026, 11, 4))
    text = moved.read_text()
    assert text.index("## Contract") < text.index("## Disposition") < text.index("## Implementation")
    assert CR.fmt.check(CR.fmt.parse(moved, "done")) == []


FENCED_DISPOSITION = "Markdown example:\n```markdown\n## Disposition\n- example\n```\n"


def test_disposition_in_a_code_fence_is_not_the_section(tmp_path):
    root = tmp_path / "cr"
    path = root / "open" / "TOOL-001-t.md"
    path.parent.mkdir(parents=True)
    text = cr_text("TOOL-001").replace("## Symptom\ns\n", "## Symptom\n" + FENCED_DISPOSITION)
    path.write_text(text + "\n## Disposition\n- previous disposition\n")
    moved = store.move_locked(CR, root, "TOOL-001", "done", outcome="waived", by="review-user",
                              note="review-decision-token", today=dt.date(2026, 11, 5))
    out = moved.read_text()
    assert FENCED_DISPOSITION in out
    assert out.rstrip().endswith("- previous disposition\n- 2026-11-05 review-user: open -> done, "
                                 "Outcome waived. review-decision-token")
    assert out.count("review-decision-token") == 1
    assert out.index("review-decision-token") > out.rindex("\n## Disposition\n")
    assert CR.fmt.check(CR.fmt.parse(moved, "done")) == []


def test_fenced_example_only_gets_a_new_disposition_section_in_order(tmp_path):
    root = tmp_path / "cr"
    path = root / "todo" / "TOOL-001-t.md"
    path.parent.mkdir(parents=True)
    text = cr_text("TOOL-001").replace("## Symptom\ns\n", "## Symptom\n" + FENCED_DISPOSITION)
    path.write_text(text + "\n## Implementation\ni\n\n## Verification\nv\n\n## Result\nr\n")
    moved = store.move(CR, root, "TOOL-001", "done", outcome="fixed", by="owner", note="abc123",
                       today=dt.date(2026, 11, 5))
    out = moved.read_text()
    assert FENCED_DISPOSITION in out
    assert out.count("\n## Disposition\n") == 1 + 1      # the example and the new section
    real = out.rindex("\n## Disposition\n")
    assert out.index("## Contract") < real < out.index("## Implementation")
    assert out.index("abc123") > real
    assert CR.fmt.check(CR.fmt.parse(moved, "done")) == []


def test_decision_disposition_in_a_code_fence_is_not_the_section(tmp_path):
    root = tmp_path / "decide"
    path = store.new_decide(root, decision_text, dt.date(2026, 11, 4))
    text = path.read_text().replace("## Background\nb\n", "## Background\nb\n" + FENCED_DISPOSITION)
    path.write_text(text + "\n## Disposition\n- previous disposition\n")
    done = store.move(DECIDE, root, "D-20261104-01", "done", outcome="withdrawn", by="user",
                      note="decision-token", today=dt.date(2026, 11, 5))
    out = done.read_text()
    assert FENCED_DISPOSITION in out
    assert out.rstrip().endswith("- previous disposition\n- 2026-11-05 user: open -> done, "
                                 "Outcome withdrawn. decision-token")
    assert out.index("decision-token") > out.rindex("\n## Disposition\n")
    assert DECIDE.fmt.check(DECIDE.fmt.parse(done, "done")) == []


def test_tracked_file_moves_with_git_mv(tmp_path):
    repo = tmp_path / "repo"
    git_init(repo)
    root = repo / "cr"
    new_cr(root, "t")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "open")
    store.move(CR, root, "TOOL-001", "done", outcome="waived", by="owner", note="intended")
    status = git(repo, "status", "--porcelain")
    # git mv stages the rename; the new Outcome and Disposition stay an unstaged change.
    assert status == "RM cr/open/TOOL-001-t.md -> cr/done/TOOL-001-t.md\n"
    assert git(repo, "log", "--oneline").count("\n") == 1


def _commit_then_remove(repo, rel):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "add")
    git(repo, "rm", "-q", rel)
    git(repo, "commit", "-q", "-m", "remove")
    path.parent.mkdir(parents=True, exist_ok=True)    # git rm drops the emptied directories
    (repo / "cr").mkdir(exist_ok=True)


def test_number_of_a_removed_file_is_not_reused(tmp_path):
    repo = tmp_path / "repo"
    git_init(repo)
    _commit_then_remove(repo, "cr/done/TOOL-003-a.md")
    assert new_cr(repo / "cr", "t").name.startswith("TOOL-004-")


def test_removed_numbers_of_other_areas_and_new_areas_do_not_count(tmp_path):
    repo = tmp_path / "repo"
    git_init(repo)
    _commit_then_remove(repo, "cr/done/AXI-002-a.md")
    assert new_cr(repo / "cr", "t").name.startswith("TOOL-001-")


def test_outside_git_only_existing_files_count(tmp_path):
    root = tmp_path / "cr"
    assert new_cr(root, "t").name.startswith("TOOL-001-")


def test_history_of_other_directories_does_not_count(tmp_path):
    repo = tmp_path / "repo"
    git_init(repo)
    _commit_then_remove(repo, "other/done/TOOL-009-a.md")
    _commit_then_remove(repo, "cr/notes/TOOL-008-a.md")
    assert new_cr(repo / "cr", "t").name.startswith("TOOL-001-")


def test_duplicate_ids_across_states(tmp_path):
    root = tmp_path / "cr"
    for state, name in (("open", "TOOL-001-a.md"), ("done", "TOOL-001-b.md"), ("open", "TOOL-002-c.md")):
        path = root / state / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cr_text(name[:8]))
    assert {k: sorted(p.name for p in v) for k, v in store.duplicates(CR, root).items()} == {
        "TOOL-001": ["TOOL-001-a.md", "TOOL-001-b.md"]}
    with pytest.raises(ItemError) as error:
        store.move(CR, root, "TOOL-001", "todo", by="o", note="n")
    assert error.value.code == "item_duplicate"


# ---------------------------------------------------------------- V3 review regressions (B1-B4)
def test_failed_parent_creation_leaves_the_source_unchanged(tmp_path):
    """B1: a plain file named done/ makes the parent creation fail after the checks."""
    root = tmp_path / "cr"
    path = new_cr(root, "alpha")
    before = path.read_text()
    (root / "done").write_text("not a directory")
    with pytest.raises(ItemError) as error:
        store.move(CR, root, "TOOL-001", "done", outcome="waived", by="user", note="review")
    assert error.value.code == "move_failed"
    assert path.read_text() == before
    assert CR.fmt.check(CR.fmt.parse(path, "open")) == []


def test_failed_git_mv_keeps_text_path_and_index(tmp_path):
    """B1: git mv fails on a held index lock; the source text, path and index stay."""
    repo = tmp_path / "repo"
    git_init(repo)
    root = repo / "cr"
    path = new_cr(root, "alpha")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "open")
    before = path.read_text()
    (repo / ".git" / "index.lock").write_text("")
    try:
        with pytest.raises(ItemError) as error:
            store.move(CR, root, "TOOL-001", "done", outcome="waived", by="user", note="review")
    finally:
        (repo / ".git" / "index.lock").unlink()
    assert error.value.code == "git_mv_failed"
    assert path.read_text() == before
    assert not (root / "done").exists()
    assert git(repo, "status", "--porcelain") == ""


def test_uncommitted_terminal_files_under_a_korean_root_are_checked(tmp_path):
    """B2: git status quotes non-ASCII paths; modified, untracked and renamed files count."""
    repo = tmp_path / "repo"
    git_init(repo)
    root = repo / "결정과변경"
    done = root / "done"
    done.mkdir(parents=True)
    for name in ("TOOL-001-a.md", "TOOL-002-b.md", "TOOL-003-c.md"):
        (done / name).write_text(cr_text(name[:8], extra="- Outcome: waived\n") + "\n## Disposition\n- d\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "done")
    assert store.check_targets(CR, root) == []
    (done / "TOOL-001-a.md").write_text(cr_text("TOOL-001"))
    (done / "TOOL-004-d.md").write_text(cr_text("TOOL-004", extra="- Outcome: waived\n"))
    git(repo, "mv", str(done / "TOOL-003-c.md"), str(done / "TOOL-003-renamed.md"))
    targets = sorted(path.name for _, path in store.check_targets(CR, root))
    assert targets == ["TOOL-001-a.md", "TOOL-003-renamed.md", "TOOL-004-d.md"]


@pytest.mark.parametrize("state, outcome", [
    ("done", "moved other TOOL-999"),
    ("deferred", "waived"),
])
def test_outcome_must_fit_the_destination(tmp_path, state, outcome):
    """B3: moved belongs to deferred/ only; deferred/ takes only moved."""
    root = tmp_path / "cr"
    path = new_cr(root, "alpha")
    before = path.read_text()
    with pytest.raises(ItemError) as error:
        store.move(CR, root, "TOOL-001", state, outcome=outcome, by="leader", note="n")
    assert error.value.code == "invalid_outcome"
    assert path.read_text() == before
    assert not (root / state).exists()


def test_decision_outcome_must_fit_done(tmp_path):
    root = tmp_path / "decide"
    store.new_decide(root, decision_text, dt.date(2026, 11, 4))
    with pytest.raises(ItemError) as error:
        store.move(DECIDE, root, "D-20261104-01", "done", outcome="fixed", by="user", note="n")
    assert error.value.code == "invalid_outcome"


def test_late_render_does_not_restore_an_old_page(tmp_path, monkeypatch):
    """B4: a render that read the open item before a move must not write after the newer render."""
    from project_item import render
    root = tmp_path / "decide"
    store.new_decide(root, decision_text, dt.date(2026, 11, 4))
    render.render("demo", root)
    first_read = threading.Event()

    def pause(step):
        if step == "render" and threading.current_thread().name == "late":
            first_read.set()
            time.sleep(0.5)

    monkeypatch.setattr(store, "_pause", pause)
    late = threading.Thread(target=lambda: render.render("demo", root), name="late")
    late.start()
    first_read.wait(command_timeout())

    def move_and_render():
        store.answer_decide(root, "D-20261104-01", "A")
        store.move(DECIDE, root, "D-20261104-01", "done", outcome="decided A", by="user", note="A")
        render.render("demo", root)

    newer = threading.Thread(target=move_and_render, name="newer")
    newer.start()
    late.join()
    newer.join()
    page = (root / render.PAGE_NAME).read_text()
    assert "결정 대기 0건 · 답변 접수 0건 · 반영 중 0건 · 완료 1건" in page


def _index_write_fails(monkeypatch):
    """Run only the `git mv` child with a 1 KiB file size limit: git renames the work tree file,
    then dies (SIGXFSZ) while it writes the index."""
    import resource
    import subprocess

    real = store._git

    def limit():
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024, 1024))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    def fake(root, *args):
        if args and args[0] == "mv":
            return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                                  preexec_fn=limit)
        return real(root, *args)

    monkeypatch.setattr(store, "_git", fake)


def test_git_mv_that_fails_after_the_work_tree_rename_is_rolled_back(tmp_path, monkeypatch):
    """B1 (rest): git mv renamed the file and then failed to write the index."""
    repo = tmp_path / "repo"
    git_init(repo)
    root = repo / "cr"
    path = new_cr(root, "alpha")
    fixtures = repo / "fixtures"
    fixtures.mkdir()
    for n in range(100):
        (fixtures / f"f{n:03d}.txt").write_text(str(n))
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "open")
    assert (repo / ".git" / "index").stat().st_size > 1024
    before = path.read_text()
    index_before = (repo / ".git" / "index").read_bytes()
    _index_write_fails(monkeypatch)
    with pytest.raises(ItemError) as error:
        store.move(CR, root, "TOOL-001", "done", outcome="waived", by="user", note="review")
    assert error.value.code == "git_mv_failed"
    assert path.read_text() == before
    assert not (root / "done").exists()
    assert (repo / ".git" / "index").read_bytes() == index_before
    assert git(repo, "status", "--porcelain") == ""


def test_rollback_that_cannot_finish_names_the_paths_left(tmp_path, monkeypatch):
    """When the file cannot go back, the error says where the file is; it never claims no change."""
    root = tmp_path / "cr"
    new_cr(root, "alpha")
    real_rename = store.os.rename
    calls = []

    def rename(src, dst):
        calls.append((src, dst))
        if len(calls) == 1:
            real_rename(src, dst)
            raise OSError("disk went away")          # the move took place, then failed
        raise OSError("still away")                  # the rollback fails too

    monkeypatch.setattr(store.os, "rename", rename)
    with pytest.raises(ItemError) as error:
        store.move(CR, root, "TOOL-001", "done", outcome="waived", by="user", note="review")
    assert error.value.code == "move_partial"
    assert str(root / "done" / "TOOL-001-alpha.md") in error.value.message
    assert (root / "done" / "TOOL-001-alpha.md").exists()


# ---------------------------------------------------------------- in-progress and assignment calls
PLAN = "\n## Implementation\ni\n\n## Verification\nv\n"


def todo_cr(root, item_id="TOOL-001", extra=""):
    path = root / "todo" / f"{item_id}-t.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cr_text(item_id, extra=extra) + "\n## Disposition\n- d\n" + PLAN)
    return path


def test_claim_moves_todo_to_in_progress_and_reads_the_job(tmp_path):
    from project_item import assign
    root = tmp_path / "cr"
    todo_cr(root, extra="- Mode: read-only\n- Cwd: server\n")
    job = assign.claim(root, "TOOL-001")
    assert job["state"] == "in-progress" and (root / "in-progress" / "TOOL-001-t.md").exists()
    assert (job["mode"], job["cwd"], job["base"]) == ("read-only", "server", None)
    assert assign.claim(root, "TOOL-001")["state"] == "in-progress"
    assign.set_base(root, "TOOL-001", {"base_hash": "a" * 40, "base_commit_time": "2026-11-04T10:00:00+09:00"})
    assert assign.lookup(root, "TOOL-001")["base"] == {"base_hash": "a" * 40,
                                                         "base_commit_time": "2026-11-04T10:00:00+09:00"}
    assign.unclaim(root, "TOOL-001")
    assert assign.lookup(root, "TOOL-001")["state"] == "todo"


def test_claim_refuses_other_states(tmp_path):
    from project_item import assign
    root = tmp_path / "cr"
    new_cr(root, "t")
    with pytest.raises(ItemError) as error:
        assign.claim(root, "TOOL-001")
    assert error.value.code == "cr_not_assignable"


def test_in_progress_transitions_and_format(tmp_path):
    root = tmp_path / "cr"
    todo_cr(root)
    store.move(CR, root, "TOOL-001", "in-progress", by="leader", note="assign")
    with pytest.raises(ItemError) as error:
        store.move(CR, root, "TOOL-001", "done", outcome="fixed", by="leader", note="n")
    assert error.value.code == "format_invalid" and "Result" in error.value.message
    store.move(CR, root, "TOOL-001", "todo", by="leader", note="park")
    store.move(CR, root, "TOOL-001", "in-progress", by="leader", note="resume")
    path = root / "in-progress" / "TOOL-001-t.md"
    path.write_text(path.read_text() + "\n## Result\ncommit abc\n")
    done = store.move(CR, root, "TOOL-001", "done", outcome="fixed", by="leader", note="merged")
    assert CR.fmt.check(CR.fmt.parse(done, "done")) == []


@pytest.mark.parametrize("header, message", [
    ("- Mode: draft\n", "Mode 'draft' is not write or read-only"),
    ("- Cwd: ../x\n", "Cwd '../x' is not a relative path inside the seat"),
    ("- Base: abc 2026\n", "Base 'abc 2026' is not '<40-hex commit> <ISO time>'"),
])
def test_job_headers_are_checked(tmp_path, header, message):
    path = todo_cr(tmp_path / "cr", extra=header)
    assert message in CR.fmt.check(CR.fmt.parse(path, "todo"))


# ---------------------------------------------------------------- number cache (ITEM-001)
@pytest.fixture
def git_log_calls(monkeypatch):
    """The `git log` runs of the number decision: (stdin revs, whether `--all` was used)."""
    real = store.subprocess.run
    calls = []

    def spy(cmd, *args, **kwargs):
        if "log" in cmd and "-C" in cmd:
            calls.append(((kwargs.get("input") or b"").decode().split(), "--all" in cmd))
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(store.subprocess, "run", spy)
    return calls


def _head(repo):
    return git(repo, "rev-parse", "HEAD").strip()


def _number(repo):
    return int(new_cr(repo / "cr", "t").name.split("-")[1])


def _cache_file(repo):
    return store.number_cache_path(repo / "cr")


def test_second_new_after_a_removed_number_reads_no_git_history(tmp_path, git_log_calls):
    repo = tmp_path / "repo"
    git_init(repo)
    _commit_then_remove(repo, "cr/done/TOOL-003-a.md")
    assert _number(repo) == 4
    assert len(git_log_calls) == 1 and git_log_calls[0][0] == [_head(repo)]    # first call: whole history
    assert _number(repo) == 5                                                  # TOOL-004 is a file now
    assert len(git_log_calls) == 1                                             # nothing new: no git log
    assert store.history_high(repo / "cr", "TOOL") == 3


def test_cache_with_a_removed_number_still_blocks_reuse(tmp_path):
    repo = tmp_path / "repo"
    git_init(repo)
    _commit_then_remove(repo, "cr/done/TOOL-003-a.md")
    new_cr(repo / "cr", "first").unlink()                    # the cache exists, the file does not
    assert _number(repo) == 4                                # 3 is in the history, 4 only was a file
    assert store.history_high(repo / "cr", "TOOL") == 3


def test_number_on_another_branch_only_is_not_reused(tmp_path):
    repo = tmp_path / "repo"
    git_init(repo)
    _commit_then_remove(repo, "cr/done/TOOL-001-a.md")
    main = git(repo, "branch", "--show-current").strip()
    git(repo, "switch", "-q", "-c", "other")
    _commit_then_remove(repo, "cr/done/TOOL-007-b.md")
    git(repo, "switch", "-q", main)
    assert _number(repo) == 8                                # no cache: full read of every ref


def test_commits_after_the_cache_are_read_and_merged(tmp_path, git_log_calls):
    repo = tmp_path / "repo"
    git_init(repo)
    _commit_then_remove(repo, "cr/done/TOOL-003-a.md")
    assert _number(repo) == 4
    old = _head(repo)
    main = git(repo, "branch", "--show-current").strip()
    git(repo, "switch", "-q", "-c", "other")
    _commit_then_remove(repo, "cr/done/TOOL-010-b.md")       # a new commit on a new branch
    git(repo, "switch", "-q", main)
    _commit_then_remove(repo, "cr/done/AXI-002-c.md")        # and one on the old branch
    git_log_calls.clear()
    assert _number(repo) == 11
    (revs, used_all), = git_log_calls
    assert not used_all and f"^{old}" in revs                # only what the cached commit does not reach
    assert store.history_high(repo / "cr", "AXI") == 2       # the cache keeps every AREA it has seen


def test_second_call_does_not_read_before_the_remembered_commit(tmp_path, monkeypatch):
    """Observed with GIT_TRACE2_EVENT: the commits git walks are the new ones only."""
    repo = tmp_path / "repo"
    git_init(repo)
    for n in range(1, 6):
        _commit_then_remove(repo, f"cr/done/TOOL-00{n}-a.md")
    assert _number(repo) == 6
    _commit_then_remove(repo, "cr/done/TOOL-020-b.md")
    trace = tmp_path / "trace.json"
    monkeypatch.setenv("GIT_TRACE2_EVENT", str(trace))
    assert store.history_high(repo / "cr", "TOOL") == 20
    argv = [line for line in trace.read_text().splitlines() if '"event":"start"' in line and '"log"' in line]
    assert len(argv) == 1 and "--stdin" in argv[0] and "--all" not in argv[0]


@pytest.mark.parametrize("content", [
    "", "not json", "[]", "{}", '{"version": 2, "root": "R", "tips": [], "high": {}}',
    '{"version": 1, "root": "elsewhere", "tips": [], "high": {"TOOL": 99}}',
    '{"version": 1, "root": "R", "tips": ["zz"], "high": {"TOOL": 99}}',
    '{"version": 1, "root": "R", "tips": [], "high": {"TOOL": "9"}}',
    '{"version": 1, "root": "R", "tips": [], "high": {"TOOL": -1}}',
    '{"version": 1, "root": "R", "tips": [], "high": []}',
])
def test_unusable_cache_means_a_full_read_and_a_new_cache(tmp_path, git_log_calls, content):
    repo = tmp_path / "repo"
    git_init(repo)
    _commit_then_remove(repo, "cr/done/TOOL-003-a.md")
    cache = _cache_file(repo)
    cache.parent.mkdir(parents=True)
    cache.write_text(content.replace("R", str((repo / "cr").resolve())), encoding="utf-8")
    assert _number(repo) == 4
    assert git_log_calls and git_log_calls[0][0] == [_head(repo)]      # no `^known` line: nothing trusted
    assert store._read_number_cache(repo / "cr") == ([_head(repo)], {"TOOL": 3})


def test_remembered_commit_that_git_cannot_find_means_a_full_read(tmp_path, git_log_calls):
    repo = tmp_path / "repo"
    git_init(repo)
    _commit_then_remove(repo, "cr/done/TOOL-003-a.md")
    main = git(repo, "branch", "--show-current").strip()
    git(repo, "switch", "-q", "-c", "doomed")
    _commit_then_remove(repo, "cr/done/TOOL-009-b.md")
    git(repo, "switch", "-q", main)
    new_cr(repo / "cr", "t")
    assert store.history_high(repo / "cr", "TOOL") == 9
    for stale in (repo / "cr" / "open").glob("*.md"):
        stale.unlink()
    git(repo, "branch", "-q", "-D", "doomed")                # a force push and a gc, in effect
    git(repo, "reflog", "expire", "--expire=now", "--all")
    git(repo, "gc", "-q", "--prune=now")
    git_log_calls.clear()
    assert _number(repo) == 4        # TOOL-009 is gone with the branch; the cache that held it is not trusted
    assert len(git_log_calls) == 2 and git_log_calls[0][0][1:2] != [] and git_log_calls[0][0][1].startswith("^")
    assert git_log_calls[1][0] == [_head(repo)]                         # git refused the `^gone`: full read
    assert store._read_number_cache(repo / "cr") == ([_head(repo)], {"TOOL": 3})
