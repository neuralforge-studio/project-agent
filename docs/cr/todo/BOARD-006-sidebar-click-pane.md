# BOARD-006: sidebar의 빈 곳을 click하면 지금 활성 pane에서 오류가 납니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2

## Symptom
사용자 보고: "side bar 빈곳을 click 하면 현재 활성화 되어 있는 pane에서 error 발생"
출처: 사용자 개선 요청 2026-11-09(대화, 11개 항목 중 2번).

## Evidence
- root `MouseDown1Pane` binding이 Board pane의 click을 `tmux_project_board.sh click --client … --pane … --x … --y …`로 보냅니다(`project_agent_bind.sh`). 항목이 없는 좌표의 처리와 오류가 나는 pane은 미확인입니다.

## Contract
- Board pane의 click은 Board만 처리하고, 다른 pane에 출력이나 입력을 남기지 않아야 합니다. 항목이 없는 곳의 click은 아무 일도 하지 않습니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 재현 가능한 동작 결함이므로 위임 범위입니다. BOARD-002 뒤에 시작합니다. 사용자 지시(2026-11-09 대화): "위와 같이 11개의 개선 요청 사항이 있어."

## Implementation
읽을 문서: [project-board README](../../../tools/project-board/README.md), [TUI 계획](../../project-board-tui-plan.md), [설치 계약 5.3·5.4절](../../project-team/install-contract.md), [README 검증 표](../../../README.md#검증).

1. 재현: sidebar의 항목이 없는 곳(빈 줄, 여백, 경계)을 click해 어느 pane에 어떤 오류가 나는지 기록합니다.
2. 원인 확정: click 좌표가 항목이 아닐 때의 처리 경로(`project_agent_bind.sh`의 binding, `tmux_project_board.sh click`, `tmux_control.py`, `tui.py`)에서 오류가 다른 pane으로 가는 이유를 근거로 적습니다.
3. 고침: 항목이 없는 곳의 click은 아무 일도 하지 않고, 어떤 경우에도 Board 밖 pane에 출력·입력을 남기지 않습니다.

의존: 선행 BOARD-002.

## Verification
1. 수정 전 재현(오류가 다른 pane에 남음)과 수정 뒤 같은 click에서 아무 출력도 없음. 항목 위 click은 지금처럼 동작.
2. README 검증 표의 `tools/project-board/**` 행(바꾸면 `integrations/tmux/**` 행).
