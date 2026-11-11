# BOARD-019: terminal 크기를 바꾼 뒤 sidebar 폭을 mouse로 바꿔도 저장되지 않습니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S2

## Symptom
사용자 보고(2026-11-11): "Side bar width가 저장이 제대로 안됨. terminal 축소 / 확대에 따른 변화 이후에, width를 mouse drag로 변경하더라도 저장이 안되는 듯함."

## Evidence
- 폭 저장은 `integrations/tmux/project-agent-main.conf`의 `after-resize-pane` hook 하나가 합니다. hook 대상 pane의 `@project_board_managed`가 1일 때만 `@project_board_width`에 `#{pane_width}`를 씁니다.
- 기본 mouse binding은 `MouseDrag1Border` → `resize-pane -M`입니다(tmux 3.8 `list-keys -T root`). 경계를 끌 때 hook 대상이 Board pane인지, 옆의 작업 pane인지는 확인하지 않았습니다.
- terminal 크기가 바뀌면 tmux가 layout을 비율대로 다시 나눕니다. 이때 `after-resize-pane`이 불리는지, `@project_agent_sync_needed`(Board pane 폭 ≠ 저장 폭)로 sync가 폭을 되돌리는지는 확인하지 않았습니다.
- 가설(미확인): terminal 크기 변경 뒤의 sync가 폭을 저장값으로 되돌리거나, mouse drag의 hook이 Board pane이 아닌 pane을 대상으로 불려 저장을 건너뜁니다. Implementation 1단계의 재현으로 확인합니다.

## Contract
- 사용자가 mouse로 Board 경계를 끌어 정한 폭은 어떤 순서로 terminal 크기를 바꾼 뒤에도 저장되고, 다른 window의 Board에도 같은 폭으로 쓰입니다.
- terminal 크기 변경 자체는 저장 폭을 바꾸지 않습니다. 사용자가 정한 폭만 저장합니다.
- terminal이 저장 폭보다 좁아 Board를 그 폭으로 둘 수 없을 때의 동작(`_can_fit_width`)은 지금과 같습니다.

## Disposition
- 2026-11-11 Leader: 고친다(Leader 판정). 사용자가 보고한 결함입니다. 원인이 어떤 경로든 사용자가 정한 폭이 저장되게 고칩니다.
- 2026-11-11 Leader: open -> todo. Leader 판정: 사용자 보고 결함

## Implementation
읽을 문서: [Board TUI 계획](../../project-board-tui-plan.md)의 폭 관련 절, `integrations/tmux/project-agent-main.conf`, `tools/project-board/project_board/tmux_control.py`(`_reconcile`, `_create`, `_can_fit_width`, sync), [설치 계약](../../project-team/install-contract.md) 3.1절, `tools/project-board/tests/test_tmux_control.py`, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 재현: test tmux server(`tools/tests/tmux_test_server.py`의 claim·release)에서 다음을 재현하고 `@project_board_width`와 각 window의 Board 폭을 기록합니다.
   - (a) 경계 drag(`resize-pane -M`과 같은 대상으로 resize)
   - (b) client 크기를 줄였다 늘린 뒤 drag
   - (c) drag 뒤 다른 window로 이동
   원인을 Result에 적습니다.
2. 수정: Contract를 모든 경로에서 지키게 고칩니다. hook, sync, 폭을 맞추는 코드 중 원인이 있는 곳을 고칩니다.
3. Test: 1단계의 (a)~(c)를 test로 만듭니다. 수정 전 실패, 수정 후 통과를 확인합니다.

의존: 없음. BOARD-018(Rust sidebar)이 같은 시기에 `tmux_control.py`를 바꿉니다. 제출 전에 `origin/main`을 merge합니다.

위험 등급: 낮음.

## Verification
1. README 검증 표에서 바꾼 경로의 행 명령 전부를 실행합니다. `integrations/tmux/**`를 바꾸면 네 번째 명령, `test_tmux_control.py`, `install/tests`도 실행합니다.
2. 수정 전 실패와 수정 후 통과를 Result에 적습니다.
