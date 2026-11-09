# BOARD-005: mouse over로 뜬 popup이 focus를 잃어도 남아 있어 따로 kill해야 합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2

## Symptom
사용자 보고: "mouse over 에 따른 pop up 창이 focus를 잃어버렸을 때, 남아있는 경우가 있음. ( kill을 따로 한번 더 해줘야 함 )"
출처: 사용자 개선 요청 2026-11-09(대화, 11개 항목 중 1번).

## Evidence
- popup은 `display-popup`(tmux 3.2+)과 Board의 popup TUI(`project-board popup`·`cr`)로 열립니다(`tools/project-board/project_board/tmux_control.py`, `tui.py`). 어느 경로에서 남는지 미확인입니다.

## Contract
- popup은 사용자가 닫거나 focus를 잃으면 process까지 끝나야 합니다. 남은 popup을 사용자가 손으로 정리할 일이 없어야 합니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 재현 가능한 동작 결함이므로 위임 범위입니다. BOARD-002가 popup 경로를 바꿀 수 있으므로 그 뒤에 시작합니다. 사용자 지시(2026-11-09 대화): "위와 같이 11개의 개선 요청 사항이 있어."

## Implementation
읽을 문서: [project-board README](../../../tools/project-board/README.md), [TUI 계획](../../project-board-tui-plan.md), [설치 계약 5.3·5.4절](../../project-team/install-contract.md), [README 검증 표](../../../README.md#검증).

1. 재현: mouse over로 popup이 뜨는 조건과, focus를 잃었을 때 popup이 남는 경우를 재현합니다. 남는 것이 tmux popup인지 그 안의 Board process인지, 어떤 경로(다른 pane click, client 전환, window 전환)에서 남는지 구분합니다.
2. 원인 확정: popup의 수명이 무엇에 묶여 있는지(`display-popup -E`, TUI 종료 조건, 신호)와 남는 이유를 근거로 적습니다.
3. 고침: popup이 focus를 잃거나 닫히면 tmux popup과 process가 함께 끝나게 합니다. 사용자가 따로 kill할 일이 없어야 합니다.

의존: 선행 BOARD-002.

## Verification
1. 재현 절차가 수정 전에 popup·process가 남음을 보이고, 수정 뒤에는 남지 않음(격리 tmux server, helper 사용).
2. README 검증 표의 `tools/project-board/**` 행.
