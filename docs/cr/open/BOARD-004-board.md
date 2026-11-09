# BOARD-004: Board 화면이 깜빡입니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3

## Symptom
사용자 보고: "깜빡 거림 증상있음."
출처: 사용자 개선 요청 2026-11-09(대화, 11개 항목 중 3번).

## Evidence
- 창을 바꿀 때 sync가 sidebar pane을 만들거나 지우는지, sidebar가 갱신마다 전체를 다시 그리는지 미확인입니다.

## Contract
- 화면 갱신은 바뀐 부분만 보여야 하고 사용자가 깜빡임을 느끼지 않아야 합니다.

## Disposition
- 2026-11-09 Leader: 판정 보류(open 유지). 원인이 BOARD-002(느림)와 같을 수 있습니다. BOARD-002가 측정으로 원인을 확정한 뒤, 같은 원인이면 BOARD-002에 병합하고 다르면 Implementation을 써서 판정합니다. 사용자 지시(2026-11-09 대화): "위와 같이 11개의 개선 요청 사항이 있어."
