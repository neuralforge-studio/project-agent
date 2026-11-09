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
- 2026-11-10 Leader: Worker 보고(원인 (e) 제품 경합) 검토와 판정. 원인: stop 뒤 관리 pane이 죽으면 SESSION-007의 `pane-died` hook이 `finish_ended` process를 띄우고, 이 process가 이미 현재 run이 아닌 run을 확인하려고 seat의 대상 제어 잠금을 잠깐 잡습니다. 그 사이 다음 start가 그 seat를 non-blocking으로 시도하면 "target control is busy"로 건너뜁니다(계측 순서 일치, 시작 commit 0ab12a1). 제품 영향: seat가 하나인 project에서 stop 직후 start가 `no_available_seat`가 될 수 있습니다. 수정 방향 승인(Leader 판정, 근거 있는 결함 수정): `finish_ended`가 잠금 전에 현재 pointer를 잠금 없이 보고, 이 run이 현재 run이 아니면 잠금 없이 `not_current`로 끝냅니다. 한 번 현재 run이 아니게 된 run은 다시 현재 run이 되지 않으므로 안전하고, 현재 run(사용자 `/exit`)은 지금처럼 잠금 안에서 마무리합니다. start의 seat 선택 의미를 바꾸는 대안과 test에서 기다리는 대안은 쓰지 않습니다. 명세 3절 '스스로 끝난 run의 마무리'에 이 순서를 적습니다.

## Implementation
1. 재현: 같은 test를 평소 부하와 단독 실행에서 반복해 실패 빈도와 실패 지점을 기록합니다. SESSION-003(2cb82bc) 이전·이후, SESSION-007(0ab12a1) 이전·이후 commit에서 같은 절차로 돌려 언제부터인지 찾습니다.
2. 원인 확정과 수정: TEST-003의 분류((a) 고정 시간, (b) fixture 한도, (c) 제품 한도, (d) 공유 자원, (e) 제품 경합)로 정하고 원인대로 고칩니다. (e)이면 Leader에게 먼저 보고합니다.

의존: 없음. SESSION-008이 `watch.py`·명세를 고치므로 제출 전 `origin/main` merge.

위험 등급: 낮음~중간(원인이 제품이면 중간).

## Verification
1. 수정 전 1단계 조건의 실패 빈도와 시작 commit.
2. 수정 뒤 같은 조건·같은 횟수에서 실패 0번.
3. README 검증 표의 `tools/agent-session/**` 행.

## Result
- 제출 commit: PLACEHOLDER

### 원인 (e 제품 경합, 계측으로 확정)
- stop이 관리 pane을 죽이면 tmux `pane-died` hook이 `finish_ended`를 별도 process로 띄웁니다(SESSION-007). 이 process가 seat-0 제어 lock을 잡고 `get_current`로 확인한 뒤 `not_current`로 끝냈습니다(stop이 이미 포인터를 지움). 그 사이 다음 `start`가 seat 0을 non-blocking으로 시도하면 "target control is busy"로 건너뛰고 seat 1을 받았습니다(`lifecycle.py` start의 candidate lock).
- 계측(임시 로그, 되돌림): 실패한 3번 모두 `finish_ended got lock` 직후 10~30ms 안에 `start busy seat 0`. 통과한 회에는 busy 줄이 없었습니다. 실패 지점은 test의 `second["seat"] == 0`(결과 1).
- 시작 commit: SESSION-003(2cb82bc)·SESSION-007 직전(1fb9f5b)은 같은 부하에서 6/6 통과, hook가 들어온 SESSION-007(0ab12a1)은 6번 중 2번 통과. SESSION-003이 아니라 SESSION-007 hook이 원인입니다. 부하가 요동쳐서(load 330~350) 이후 commit 빈도는 4/6~통과 사이를 오갔습니다.
- 제품 영향: seat가 하나뿐인 project는 stop 직후 start가 `no_available_seat`가 될 수 있고, 여럿이면 낮은 번호의 빈 seat를 건너뜁니다. 부하 의존이 아니라 test가 제품 경합을 드러낸 것입니다.
- Leader 승인: 수정 전 (e) 보고, Leader가 같은 방향으로 진행하라고 회신했습니다(Leader 판정, 위 Disposition 기록은 Leader가 합니다).

### 변경
1. `agent_session/lifecycle.py`: `finish_ended`가 제어 lock 전에 `_is_current`로 포인터를 lock 없이 읽고, 현재가 아니면 lock 없이 `not_current`로 끝냅니다. 현재 run(사용자 /exit)은 기존처럼 lock 안에서 마무리합니다. 포인터를 읽지 못하면 현재로 보고 기존 절차로 갑니다. 한도·start 의미는 바꾸지 않았습니다.
2. `docs/project-team/spec.md` 3절 '스스로 끝난 run의 마무리'에 이 순서와 이유를 적었습니다.
3. `tests/test_self_ended.py`: 제품 동작 test `test_the_wrap_up_of_a_stopped_run_does_not_take_the_slots_control_lock`(stop한 run의 마무리가 lock을 쥔 상태에서도 `not_current`를 바로 돌려주고, 이어지는 start가 seat 0을 받음). 수정 전 commit에서 실패, 수정 뒤 통과를 확인했습니다.

### 검증
- 같은 부하(load 약 338, 두 쪽을 동시에 실행), `test_lifecycle.py -k seats_next_cr_opens` 12번: 수정 전(ce7050f) 통과 5·실패 6·요약 없음 1, 수정 뒤 12번 모두 통과(실패 0). 수정 중간 코드로도 12/12 통과.
- README 표 `tools/agent-session/**`+ 명세 변경(`spec.md`: test_remote 포함)·`tools/test_distribution_boundary.py`: `python -m pytest -q -n 8 tools/agent-session/tests tools/test_distribution_boundary.py` → 782 passed, 1 failed (539초, load 약 338).
- 그 1개 `test_control_queue.py::test_external_control_cannot_overtake_a_pending_self_request`는 이 CR과 무관한 기존 실패입니다. 수정 전 ce7050f에서도 단독 실행으로 같은 오류(`AttributeError: 'Tmux' object has no attribute 'require_version'`, `lifecycle.py:826`, test의 fake Tmux에 SESSION-007이 `control(restart)`에 더한 호출이 없음)로 실패합니다. 별도 CR 후보로 Leader에게 알립니다.
- `origin/main`(b2038ee)을 merge했습니다(a404b10). merge로 들어온 변경은 `tools/project-board`·CR 문서이고 `tools/agent-session`·`docs/project-team`은 바뀌지 않아서 위 검증을 재사용했습니다.
