# BOARD-024: 결정 답변 창에서 Ctrl+J로도 줄을 바꿉니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S3

## Symptom
결정 창의 답변 입력란에서 Ctrl+J를 눌러도 줄이 바뀌지 않습니다. 줄바꿈은 Enter로만 됩니다.

사용자 요청(2026-11-11): "Decision 답변 창에서 ctrl+j도 개행이 되게 수정해줘."

## Evidence
- `tools/project-board/project_board/tui.py`:
  - `PopupApp`의 답변 입력란은 Textual 기본 `TextArea(id="answer")`입니다(1080행).
  - App binding은 `escape`(닫기)와 `ctrl+s`(전송)뿐입니다(1032행).
- 기본 `TextArea`는 Enter(`enter`)에만 줄바꿈을 넣습니다. terminal은 Ctrl+J를 LF로 보내고, Textual은 이를 `ctrl+j` 키로 받아 처리하지 않는 것으로 보입니다(가설, Implementation 1에서 확인).

## Contract
- 답변 입력란에 focus가 있을 때 Ctrl+J는 커서 위치에 줄바꿈을 넣습니다. Enter와 결과가 같습니다.
- 다른 키(Enter, Ctrl+S 전송, Esc 닫기)와 입력란 밖의 동작은 바뀌지 않습니다.

## Disposition
- 2026-11-11 Leader: 구현한다. 사용자 요청입니다(원문은 Symptom).
- 2026-11-11 Leader: open -> todo. 사용자 요청

## Implementation
읽을 문서: `tools/project-board/project_board/tui.py`의 `PopupApp`, `tools/project-board/tests/test_tui.py`, [Board TUI 계획](../../project-board-tui-plan.md)의 결정 창 절, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. Textual `run_test`에서 Ctrl+J가 어떤 키로 들어오는지 확인합니다. 실제 tmux pane에서도 확인합니다(`send-keys C-j`).
2. 답변 입력란에서 Ctrl+J가 줄바꿈을 넣게 합니다. 입력란에만 적용합니다.
3. 계획 문서의 결정 창 키 설명에 Ctrl+J를 더합니다.
4. Test: Ctrl+J 줄바꿈, Enter 동작 유지, Ctrl+S 전송 유지.

의존: 없음.

위험 등급: 낮음.

## Verification
1. README 검증 표의 `tools/project-board/**` 행:
   - `python -m pytest -q tools/project-board/tests`
   - `python -m pytest -q tools/agent-session/tests/test_api_boundary.py`
2. 실제 tmux pane에서 `send-keys C-j`로 줄바꿈이 들어가는지 Result에 적습니다.
