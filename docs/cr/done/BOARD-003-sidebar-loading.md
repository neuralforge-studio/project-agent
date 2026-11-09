# BOARD-003: 여러 창을 빠르게 이동하면 한동안 sidebar가 나오지 않고 loading이 중복되는 것처럼 보입니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Outcome: merged BOARD-002

## Symptom
사용자 보고: "여러 창을 빠르게 계속 이동하면 한동안 sidebar가 나오지 않음. 뭐가 loading이 계속 중복되는 느낌임."
출처: 사용자 개선 요청 2026-11-09(대화, 11개 항목 중 4번).

## Evidence
- 창마다 hook이 `sync`를 `run-shell -b`로 띄웁니다. 빠르게 이동하면 sync process가 여러 개 겹쳐 실행되고 Board 잠금(`control.lock`)을 차례로 기다리는 것으로 보입니다(가설, 미확인).

## Contract
- 사용자가 보는 창에는 Board가 곧바로 한 번만 나타나야 합니다([TUI 계획](../../project-board-tui-plan.md)).

## Disposition
- 2026-11-09 Leader: 판정 보류(open 유지). 원인이 BOARD-002(느림)와 같을 수 있습니다. BOARD-002가 측정으로 원인을 확정한 뒤, 같은 원인이면 BOARD-002에 병합하고 다르면 Implementation을 써서 판정합니다. 사용자 지시(2026-11-09 대화): "위와 같이 11개의 개선 요청 사항이 있어."
- 2026-11-09 Leader: open -> done, Outcome merged BOARD-002. BOARD-002 수정 제출 b9294bd의 Result(요청 4)로 같은 원인임을 확인했습니다: 창 이동마다 Board pane을 지우고 새 TUI process를 만든 것. 이미 본 window 4개를 0.3초 간격으로 24번 전환한 측정에서 수정 전 Python sync 24개·pane 생성/제거 11/11·빈 화면 97%(깜빡임과 loading 반복), 수정 후 0개·0/0·0%, 24번 모두 0.3초 안에 행 표시. 남는 처음 보는 window의 첫 표시 비용은 RUST-001의 근거입니다. 증상은 BOARD-002에서 함께 해소됩니다.
