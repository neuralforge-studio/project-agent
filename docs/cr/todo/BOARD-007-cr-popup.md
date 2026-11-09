# BOARD-007: 결정·CR popup의 항목 목록과 선택한 항목 표시가 이상합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3

## Symptom
사용자 보고: "Decision / CR을 위한 popup 창에서 item의 list, selected item에 대한 표시가 너무 이상함." 구체적인 화면은 아직 받지 않았습니다.
출처: 사용자 개선 요청 2026-11-09(대화, 11개 항목 중 8번).

## Evidence
- popup TUI는 `tools/project-board/project_board/tui.py`의 `PopupApp`·`CRPopupApp`입니다.

## Contract
- 목록에서 각 항목을 알아볼 수 있고, 지금 선택한 항목이 분명히 구별되어야 합니다([TUI 계획](../../project-board-tui-plan.md)).

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 사용자가 표시 결함을 보고했고 위임 범위입니다. 구체 화면이 없으므로 Worker가 지금 화면을 capture해 문제를 목록으로 만들고, 고친 화면과 함께 Result에 둡니다. BOARD-002 뒤에 시작합니다. 사용자 지시(2026-11-09 대화): "위와 같이 11개의 개선 요청 사항이 있어."

## Implementation
읽을 문서: [project-board README](../../../tools/project-board/README.md), [TUI 계획](../../project-board-tui-plan.md), [설치 계약 5.3·5.4절](../../project-team/install-contract.md), [README 검증 표](../../../README.md#검증).

1. 지금 화면: 결정 popup과 CR popup을 실제 크기의 격리 tmux에서 열어 목록·선택 표시를 text capture로 남기고, 읽기 어려운 점(정렬, 잘림, 선택 강조, 상태 구분, 긴 제목)을 목록으로 적습니다.
2. 고침: 각 항목을 한 줄에 알아볼 수 있게(ID·상태·제목, 긴 제목은 정해진 방식으로 줄임), 선택한 항목을 색과 표시로 분명히 구별하게 합니다. 규칙을 [TUI 계획](../../project-board-tui-plan.md)에 먼저 적습니다.

의존: 선행 BOARD-002.

## Verification
1. 고치기 전·뒤 화면 capture(80열·120열 두 크기)와 1단계 목록의 항목마다 해결 여부.
2. README 검증 표의 `tools/project-board/**` 행.
