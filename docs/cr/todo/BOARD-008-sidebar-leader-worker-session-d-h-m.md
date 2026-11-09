# BOARD-008: sidebar에 Leader·Worker session이 동작한 시간(??d ??h ??m)을 보입니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3

## Symptom
사용자 요청: "Leader/Worker의 Session 동작 중인 시간에 대한 표시가 필요한 ??d ??h ??m"
출처: 사용자 개선 요청 2026-11-09(대화, 11개 항목 중 6번).

## Evidence
- state의 session마다 `connected_at`(처음 게시한 UTC 시각)이 있습니다([명세 3절](../../project-team/spec.md#3-statejson)).

## Contract
- 표시 형식은 사용자가 정한 `??d ??h ??m`입니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 사용자가 표시 형식까지 정한 기능 요청이므로 위임 범위입니다. BOARD-002 뒤에 시작합니다. 사용자 지시(2026-11-09 대화): "위와 같이 11개의 개선 요청 사항이 있어."

## Implementation
읽을 문서: [project-board README](../../../tools/project-board/README.md), [TUI 계획](../../project-board-tui-plan.md), [설치 계약 5.3·5.4절](../../project-team/install-contract.md), [README 검증 표](../../../README.md#검증).

1. sidebar의 Leader와 각 Worker seat 줄에 그 session이 게시된 뒤 지난 시간을 `??d ??h ??m`으로 보입니다. 기준은 state의 `connected_at`입니다. 0인 앞자리 단위는 생략합니다(예: `3h 05m`, `12m`, `2d 01h 00m`). session이 없으면 표시하지 않습니다.
2. 갱신 주기는 sidebar의 기존 갱신과 같게 하고, 분이 바뀔 때만 다시 그려 깜빡임을 만들지 않습니다.
3. `connected_at`이 없는 이전 state(명세 3절)는 표시하지 않습니다.
4. 표시 규칙을 [TUI 계획](../../project-board-tui-plan.md)에 먼저 적습니다.

의존: 선행 BOARD-002.

## Verification
1. 경계 test: 0분, 59분, 1시간, 23시간 59분, 1일, 여러 날, `connected_at` 없음.
2. 화면 capture에서 Leader·Worker 줄에 시간이 보임.
3. README 검증 표의 `tools/project-board/**` 행.
