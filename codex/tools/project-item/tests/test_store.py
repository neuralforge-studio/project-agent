"""ID issue under the per-root lock, transitions of `move`, and duplicate detection."""
import datetime as dt
import multiprocessing
import threading
import time
from pathlib import Path

import pytest

from project_item_testing import git, git_init
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
    done = store.move(DECIDE, root, "D-20261104-01", "done", outcome="decided A", by="user",
                      note='"D-20261104-01 A"', today=dt.date(2026, 11, 4))
    text = done.read_text()
    assert "- Outcome: decided A" in text.split("## Background")[0]
    assert text.rstrip().endswith('- 2026-11-04 user: open -> done, Outcome decided A. "D-20261104-01 A"')
    assert DECIDE.fmt.check(DECIDE.fmt.parse(done, "done")) == []
    reopened = store.move(DECIDE, root, "D-20261104-01", "open", by="user", note="선택을 바꿈",
                          today=dt.date(2026, 11, 5))
    text = reopened.read_text()
    assert "Outcome" not in text.split("## Background")[0]
    assert "- 2026-11-05 user: done -> open. 선택을 바꿈" in text
    assert text.index("## Disposition") > text.index("## Evidence")
    assert DECIDE.fmt.check(DECIDE.fmt.parse(reopened, "open")) == []


def test_reopen_needs_a_reason(tmp_path):
    root = tmp_path / "decide"
    store.new_decide(root, decision_text, dt.date(2026, 11, 4))
    store.move(DECIDE, root, "D-20261104-01", "done", outcome="withdrawn", by="user", note="n")
    with pytest.raises(ItemError) as error:
        store.move(DECIDE, root, "D-20261104-01", "open")
    assert error.value.code == "reason_missing"


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
    first_read.wait(5)

    def move_and_render():
        store.move(DECIDE, root, "D-20261104-01", "done", outcome="decided A", by="user", note="A")
        render.render("demo", root)

    newer = threading.Thread(target=move_and_render, name="newer")
    newer.start()
    late.join()
    newer.join()
    page = (root / render.PAGE_NAME).read_text()
    assert "결정 대기 0건 · 결정됨 1건" in page


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
