# TEST-003: 여러 seat가 동시에 검증하는 평소 부하에서 agent-session suite(-n 8)가 timing으로 여러 개 실패합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Base: 3781d7baf6dcb7569834bb4c4e3c82f053ce1acf 2026-11-09T15:24:38+09:00

## Symptom
project-agent seat 3~4개가 동시에 test를 돌리는 평소 운영 부하에서, README의 `python -m pytest -q -n 8 tools/agent-session/tests`가 여러 test를 실패시킵니다. 병렬 수를 줄이면 통과합니다. 검증 결과가 실행 때의 부하에 따라 달라져 회귀 판정을 흐립니다. TEST-001은 시간 단언 두 개만 고쳤고, 같은 부하에서 남은 실패는 원인이 다릅니다.

## Evidence
- INSTALL-002 Result(2026-11-09, 제출 5c41f2d, Base 9458aba): `-n 8` 첫 실행 695 passed·9 failed. `test_suspend.py`·`test_lifecycle.py`를 `-n 2`로 다시 돌리면 1개(`test_the_most_recent_runs_window_is_the_one_a_slot_takes`)만 실패, 그 test는 단독 실행에서 변경본·base 모두 통과. `-n 4` 전체는 704 passed. 실패한 9개의 이름과 오류 code는 기록되지 않았습니다.
- TEST-001 Result(2026-11-09): 극한 부하(CPU 점유 64개+16개 동시)에서 제품 tmux client 명령 한도 `subprocess.run(..., timeout=10)` 만료로 `tmux_unknown` 3번, fixture 기본 한도 15초(`AGENT_SESSION_TEST_TIMEOUT`) 소진으로 `timeout` 1번. TEST-001 인수 Disposition의 다시 볼 조건("통상 검증에서 tmux_unknown 또는 timeout 실패가 재현될 때")에 해당합니다.
- README 검증 절: load가 높으면 `AGENT_SESSION_TEST_TIMEOUT`을 지정하라는 안내가 있습니다.

## Contract
- README의 검증 명령은 이 workstation의 평소 운영 부하(seat 4개 동시 검증)에서 같은 결과를 내야 합니다. 원인마다 근거를 확정하고 그 원인을 고칩니다. 한도 값을 올리는 것만으로 끝내지 않습니다. 한도가 원인이면 그 한도가 무엇을 보장하는지와 값의 근거를 적습니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). INSTALL-002·TEST-001 Result에 재현 근거가 있는 검증 신뢰성 결함이므로 위임 범위입니다. TEST-001 인수 때 정한 다시 볼 조건이 충족되었습니다.

## Implementation
읽을 문서: [README의 검증](../../../README.md#검증), [agent-session README](../../../tools/agent-session/README.md)의 test 절, `tools/agent-session/tests/fixtures/`.

1. 재현과 목록: seat 3~4개가 동시에 검증하는 평소 부하를 재현합니다(예: 같은 suite를 `-n 8`로 3~4개 동시에 실행). 실패한 test의 이름·오류 code·걸린 시간을 모두 적습니다. 반복 실행에서 실패 빈도를 test별로 적습니다.
2. 원인 분류: 실패마다 원인을 하나로 확정하고 근거(`path:line`, 관찰한 값)를 적습니다. 분류는 (a) test가 host 속도를 단언하거나 고정 시간만 기다림, (b) fixture의 대기 한도(`AGENT_SESSION_TEST_TIMEOUT` 기본 15초)가 부하에서 부족함, (c) 제품의 한도(tmux client 10초 등)가 부하에서 만료됨, (d) test 사이 공유 자원 경합(tmux server·socket·임시 디렉터리·port), (e) 제품의 실제 경합 결함입니다.
3. 원인별로 고칩니다.
   - (a)는 TEST-001처럼 관찰 가능한 동작을 기다리게 바꿉니다.
   - (b)·(c)는 그 한도가 무엇을 보장하는지 먼저 적습니다. 값을 바꾸면 근거(측정한 분포)를 적고, 제품 한도면 운영에 미치는 영향(응답 지연, 오판)을 적습니다. 한도를 test에서만 늘리는 것이 맞는지, 제품 한도가 틀린 것인지 구분합니다.
   - (d)는 test 격리를 고칩니다.
   - (e)는 제품 결함이므로 Leader에게 먼저 보고하고 별도 CR로 다룰지 Leader가 정합니다.
4. README 검증 절의 안내를 결과에 맞춥니다.

의존: 없음. 다른 CR과 병렬로 진행합니다. 같은 host의 다른 seat 부하가 재현 조건이므로, 측정 때 함께 돌던 작업을 Result에 적습니다.

위험 등급: 중간. test 또는 제품 한도를 바꿉니다. 제품 한도 변경은 운영 응답에 영향을 줍니다.

## Verification
1. 재현(수정 전): 1단계 조건에서 실패 목록과 빈도를 기록합니다.
2. 수정 뒤 같은 조건, 같은 횟수에서 실패 0번입니다.
3. 부하 없이 `-n 8` 전체 suite가 통과합니다. 수정 전후 전체 실행 시간을 적습니다(대기 방식 변경으로 크게 느려지지 않았는지).
4. 고친 한도마다 근거(측정값)와 보장하는 내용이 Result와 코드 주석 또는 README에 있습니다.
