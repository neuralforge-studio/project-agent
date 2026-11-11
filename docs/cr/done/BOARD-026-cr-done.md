# BOARD-026: CR 창을 열 때 Done 묶음은 접힌 상태로 엽니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S3

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
