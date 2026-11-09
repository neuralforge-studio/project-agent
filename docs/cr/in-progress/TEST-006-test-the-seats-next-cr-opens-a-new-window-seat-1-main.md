# TEST-006: test_the_seats_next_cr_opens_a_new_window(seat=1)가 main에서 부하 아래 계속 실패합니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Base: ce7050f5545f939fb068232a86b389a5840b3180 2026-11-10T00:03:28+09:00

## Symptom
`tools/agent-session/tests/test_lifecycle.py`의 `test_the_seats_next_cr_opens_a_new_window…`(seat=1)가 origin/main에서 load 320 아래 6번 중 0번 통과했습니다. BOARD-002 branch에서는 6번 중 1번 통과했습니다. 간헐이 아니라 그 조건에서 계속 실패합니다.

## Evidence
- BOARD-002 수정 제출 2 Result(2026-11-10, `docs/cr/done/BOARD-002-board.md`): 순수 origin/main 0/6, BOARD-002 branch 1/6, load 320.
- 이 test는 SESSION-003(2cb82bc, 반납 뒤 사용자 pane이 있으면 관리 pane만 닫음)에서 기대가 바뀌었고, SESSION-007(0ab12a1, 스스로 끝난 run의 마무리)이 같은 정리 경로를 씁니다.

## Contract
- README 검증 표: agent-session test는 평소 부하에서 같은 결과를 내야 합니다(TEST-003). 원인을 확정하고 그 원인을 고칩니다. 부하 의존이라고 판단하기 전에 test와 제품 중 어느 쪽이 원인인지 근거를 남깁니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 재현 근거가 있는 결함입니다. 원인이 test의 기다림인지, SESSION-003·007이 바꾼 정리 경로의 실제 경합인지부터 확정합니다.

## Implementation
1. 재현: 같은 test를 평소 부하와 단독 실행에서 반복해 실패 빈도와 실패 지점을 기록합니다. SESSION-003(2cb82bc) 이전·이후, SESSION-007(0ab12a1) 이전·이후 commit에서 같은 절차로 돌려 언제부터인지 찾습니다.
2. 원인 확정과 수정: TEST-003의 분류((a) 고정 시간, (b) fixture 한도, (c) 제품 한도, (d) 공유 자원, (e) 제품 경합)로 정하고 원인대로 고칩니다. (e)이면 Leader에게 먼저 보고합니다.

의존: 없음. SESSION-008이 `watch.py`·명세를 고치므로 제출 전 `origin/main` merge.

위험 등급: 낮음~중간(원인이 제품이면 중간).

## Verification
1. 수정 전 1단계 조건의 실패 빈도와 시작 commit.
2. 수정 뒤 같은 조건·같은 횟수에서 실패 0번.
3. README 검증 표의 `tools/agent-session/**` 행.
