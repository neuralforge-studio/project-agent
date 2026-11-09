# TEST-005: test_registration_publishes_when_the_controller_ends_before_it[sigint]가 병렬 부하에서 반복해 실패합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3

## Symptom
SESSION-001이 더한 `tools/agent-session/tests/test_lifecycle.py::test_registration_publishes_when_the_controller_ends_before_it[sigint]`가 `-n 8` 병렬 실행에서 실패하고 단독 실행에서는 통과합니다. 세 CR의 검증에서 같은 실패가 나왔고 매번 단독 재실행으로 넘어갔습니다.

## Evidence
- INSTALL-005 Result(2026-11-09): host 부하(다른 seat의 pytest 동시 실행)에서 subprocess 60초 시간 초과, 단독 재실행 4 passed.
- TEST-004 Result: 첫 측정에서 실패. 원인 하나는 `nohup … &`로 띄워 자식이 SIGINT 무시 상태를 상속한 측정 방법이었음(전경 실행에서는 통과).
- SESSION-004 Result: `-n 8` 전체에서 실패, 단독 4 passed.
- release gate(2026-11-09, 9887c2a, 전경 실행): 730 passed(이번에는 통과). 간헐적입니다.

## Contract
- README 검증 표: agent-session test는 평소 부하(seat 여럿 동시 검증)에서 같은 결과를 내야 합니다(TEST-003). 원인을 확정해 고치고, 한도를 늘리는 것만으로 끝내지 않습니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 재현 근거가 세 번 있는 검증 신뢰성 결함이므로 위임 범위입니다.

## Implementation
읽을 문서: [README 검증 표](../../../README.md#검증), `tools/agent-session/tests/test_lifecycle.py`의 해당 test와 그 fixture, TEST-003 Result(부하 원인 분류 방법).

1. 재현: 평소 부하(같은 suite를 `-n 8`로 2~3개 동시에)에서 이 test를 반복해 실패 빈도와 실패 지점(어느 대기가 만료되는지)을 기록합니다. background 실행 시 SIGINT 무시 상속(TEST-004)과 구분하기 위해 전경 실행에서도 재현합니다.
2. 원인 확정: test가 기다리는 것(별도 process controller의 시작, SIGINT 전달 시점, 등록 hook, 게시)과 걸린 시간을 근거로 적습니다. TEST-003의 분류((a) 고정 시간, (b) fixture 한도, (c) 제품 한도, (d) 공유 자원, (e) 제품 경합) 중 무엇인지 정합니다.
3. 원인대로 고칩니다. (e)이면 Leader에게 먼저 보고합니다.

의존: 없음.

위험 등급: 낮음.

## Verification
1. 수정 전 1단계 조건의 실패 빈도.
2. 수정 뒤 같은 조건·같은 횟수에서 실패 0번.
3. README 검증 표의 `tools/agent-session/**` 행.
