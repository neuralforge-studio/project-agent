# BOARD-026: CR 창을 열 때 Done 묶음은 접힌 상태로 엽니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S3
- Base: 036ccf1a7cd3f7d29bb82d701801fdbd4142b058 2026-11-11T15:06:05+09:00
- Outcome: fixed

## Symptom
CR 창을 열면 Open, Todo, In-Progress, Done 네 묶음이 모두 펼쳐져 있습니다. done CR이 많아서(이 project 72개, balvian 1,471개) 목록이 길어집니다.

사용자 요청(2026-11-11): "CR popup 창 열때 Done 창은 folded 상태로 열자. 괜히 많이 보이니까 오히려 부담스럽네."

## Evidence
- `tools/project-board/project_board/tui.py`의 `CRPopupApp`은 `collapsed`를 빈 집합으로 시작합니다. 그래서 네 묶음이 모두 펼쳐져 열립니다(BOARD-021, 사용자 예시에 따라 정한 동작).
- 묶음의 접힘은 창 단위 상태라서 ◀▶로 project를 옮겨도 유지됩니다(BOARD-021 Result).
- BOARD-025(seat 2)가 같은 창의 시동과 내용 바꾸기를 고치고 있습니다.

## Contract
1. CR 창을 처음 열면 Done 묶음은 접혀 있고(`Done ▶`), Open, Todo, In-Progress는 펼쳐져 있습니다. 맨 위 개수 줄(`Done N`)은 그대로입니다.
2. 사용자가 Done을 펼치면 그 창 안에서는 펼친 채로 유지됩니다(◀▶ 이동 포함, 지금 규칙).
3. 누른 상태(O·T·I)의 묶음이 처음 보이도록 scroll하는 동작은 그대로입니다.

## Disposition
- 2026-11-11 Leader: 구현한다. 사용자 요청입니다(원문은 Symptom).
- 2026-11-11 Leader: open -> todo. 사용자 요청
- 2026-11-11 Leader: 제출 433c027dbaeccc5ebd632ca0cef2e414772f895e를 인수합니다. 검토 433c027(main 036ccf1 기준, 그 뒤 main은 CR 이동만). collapsed 초기값 {done}, 계획 문서·README, test(Done만 접힘, 펼친 뒤 ◀▶ 유지, scroll test의 목록 길이를 In-Progress로)를 읽었습니다. project-board 205 passed(결정 창 test 1건 일시 실패 뒤 단독·전체 재실행 통과), test_api_boundary 4 passed.
- 2026-11-11 Leader: in-progress -> done, Outcome fixed. 통합 195dacf (origin/main)

## Implementation
읽을 문서: `tools/project-board/project_board/tui.py`의 `CRPopupApp`, `tools/project-board/tests/test_tui.py`의 BOARD-021 test, [Board TUI 계획](../../project-board-tui-plan.md)의 CR 창 절, `tools/project-board/README.md`, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. CR 창을 처음 열 때 Done을 접힌 상태로 둡니다.
2. 계획 문서와 README의 CR 창 설명을 고칩니다.
3. Test: 처음 열면 Done 접힘과 나머지 펼침, 펼친 뒤 ◀▶ 유지, 누른 묶음으로 scroll. BOARD-021 test 중 "모두 펼침"을 단언하는 것은 새 계약으로 바꿉니다.

의존: 없음. BOARD-025가 같은 파일을 고치고 있으니 제출 전에 `origin/main`을 merge합니다.

위험 등급: 낮음.

## Verification
1. README 검증 표의 `tools/project-board/**` 행:
   - `python -m pytest -q tools/project-board/tests`
   - `python -m pytest -q tools/agent-session/tests/test_api_boundary.py`

## Result
- 제출 commit: 433c027dbaeccc5ebd632ca0cef2e414772f895e

`cr/BOARD-026`을 `origin`에 push했습니다. 시작 이후 `origin/main`은 진행하지 않아 merge는 없었습니다.

변경:
- `tools/project-board/project_board/tui.py`: `CRPopupApp.collapsed`의 초기값을 `{"done"}`으로 합니다. 창 단위 상태라서 ◀▶ 이동 뒤에도 유지됩니다. 맨 위 개수 줄과 누른 묶음으로 scroll하는 코드는 바꾸지 않았습니다.
- `docs/project-board-tui-plan.md`의 CR 창 절, `tools/project-board/README.md`: 처음 열 때 `Done ▶`와 유지 규칙을 적었습니다.
- `tools/project-board/tests/test_tui.py`: BOARD-021 test 중 "모두 펼침" 단언을 새 계약(Done만 접힘)으로 바꿨습니다. 펼친 뒤 ◀▶ 이동에도 `Done ▼`가 유지되는 test(`test_cr_window_keeps_done_unfolded_when_moving_between_projects`)를 추가했습니다.
  - `test_cr_window_scrolls_to_the_pressed_group_first`는 Done을 늘려 목록을 길게 만들었는데, Done이 접히면 길이에 기여하지 않아 In-Progress CR을 늘리도록 고쳤습니다.

알려 둘 점: Done이 접히면 아래 내용이 짧은 project에서는 누른 묶음 제목이 목록 맨 위까지 올라가지 못하고 scroll 한계까지만 갑니다. scroll 동작 자체는 그대로입니다. 접힌 동안에도 Done 제목을 읽는 작업(`_fill_done_titles`)은 계속 실행합니다. 요청 밖이라 바꾸지 않았습니다.

검증(제출 commit에서 실행):
- `python -m pytest -q tools/project-board/tests` → 205 passed. 첫 실행에서는 `test_decision_window_moves_only_between_projects_with_decisions_and_keeps_drafts`가 한 번 실패했습니다(결정 창의 `#popup-message` NoMatches). 이 test는 CR 창과 무관하고 단독 2회 통과했으며 전체 재실행도 통과했습니다. 부하 때문에 생긴 일시 실패로 판단합니다.
- `python -m pytest -q tools/agent-session/tests/test_api_boundary.py` → 4 passed.
- `origin/main` merge가 없어 근거 재사용·재실행 판정은 해당 없습니다.
