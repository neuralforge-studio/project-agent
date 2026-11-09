# TEST-005: test_registration_publishes_when_the_controller_ends_before_it[sigint]가 병렬 부하에서 반복해 실패합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3
- Base: 5af70aba1765dd5f043b6e4aaa1003d1e75d90e6 2026-11-09T20:55:46+09:00
- Outcome: fixed

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
- 2026-11-09 Leader: 제출 456f3d37347f8897966e492bd8d98eadd28ba112를 인수합니다. Leader review: 원인을 SIGINT 무시 상속(background로 띄운 pytest의 자식 controller가 KeyboardInterrupt 없이 시작)으로 확정한 근거를 확인했습니다. 부하 가설은 전경 실행에서 load 185~395에도 0 실패, 대기 계측(최대 25.1초 < 60초)으로 기각. 수정은 test CONTROLLER 첫머리의 SIGINT 기본 처리 복원 한 곳, 제품 코드·한도 변경 없음. 같은 조건 수정 전 8/8 실패 → 수정 뒤 0/8, agent-session -n 8 742 passed(원래 실패 조건), merge 뒤 해당 test 4 passed.
- 2026-11-09 Leader: in-progress -> done, Outcome fixed. 통합 58679c7(Merge cr/TEST-005, 제출 456f3d3). origin/main 반영 확인. CHANGELOG Unreleased에 더했습니다.

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

## Result
- 제출 commit: 456f3d37347f8897966e492bd8d98eadd28ba112

수정 commit은 4f31e93이고, 456f3d3은 그 위에 `origin/main`(d4911be)을 merge한 것입니다. merge가 `test_lifecycle.py`를 바꿨으므로(충돌 없음) 이 test 4개를 merge 상태에서 다시 실행했고(4 passed) 전체 suite 결과는 merge 전 상태의 것을 재사용했습니다.

### 원인: 부하가 아니라 SIGINT 무시 상속입니다 (분류: 이 CR의 (a)~(e) 밖의 test 환경 의존)
- `start_controller`가 띄우는 controller 자식은 pytest의 SIGINT 처리를 상속합니다. pytest가 `&`로 띄운 background 실행(비대화형 shell의 background job은 SIGINT가 무시 상태로 시작합니다)이면 자식도 SIGINT 무시로 시작합니다. 이때 Python은 `KeyboardInterrupt` 핸들러를 설치하지 않아 test의 SIGINT가 controller를 끝내지 못하고, `child.wait(timeout=60)`(`test_lifecycle.py:437`)이 `subprocess.TimeoutExpired`로 만료됩니다. INSTALL-005의 "subprocess 60초 시간 초과"가 이 줄입니다.
- `[sigint]`만 실패하는 이유: SIGTERM·SIGKILL은 무시할 수 없습니다. 세 CR의 "단독 재실행에서 통과"는 전경 실행이어서입니다. TEST-004가 본 `nohup … &` 상속과 같은 원인이고, 그 CR은 측정 방법만 바로잡고 test는 고치지 않았습니다.
- 제품 코드는 원인이 아닙니다(SIGINT가 도달하면 `cli.py`가 `interrupted`로 끝냅니다).

### 1. 수정 전 재현
- 부하 가설 검증(전경 실행, SIGINT 기본): host load average 185~395에서 `[sigint]` 단독 24개 동시, 세 signal 케이스 64개 동시(192 test), 전체 suite `-n 8` 3개 동시(742 passed ×3, 각 약 19분) 모두 실패 0번. 대기 시간 계측(`-n 8` 4개 동시, 96회): 어느 대기도 한도 60초에 못 미쳤습니다(controller가 dialog까지 p50 17.9초·최대 25.1초, SIGINT 후 종료 최대 1.1초, 등록 게시 최대 13.1초).
- 조건 재현(SIGINT 무시 상태로 시작한 pytest, 전경 아님): 같은 test 4개(returned·sigint·sigterm·sigkill)를 8개 동시에 실행해 8/8에서 `[sigint]` 1개가 위 `TimeoutExpired`로 실패, 나머지 3개는 통과(실패 빈도 8/8, 부하 없이도 단독 1/1).

### 2. 수정과 수정 뒤
- `test_lifecycle.py`의 `CONTROLLER` 코드 첫머리에서 `signal.signal(SIGINT, default_int_handler)`로 SIGINT를 Python 기본(`KeyboardInterrupt`)으로 되돌립니다. 한도는 바꾸지 않았습니다. 제품 코드·다른 test는 변경 없습니다.
- 같은 조건·같은 횟수(SIGINT 무시 시작, 4개 test 8개 동시): 실패 0번(8×4 passed).
- merge 상태에서 같은 조건 `-n 4`: 4 passed.

### 3. README 검증 표 `tools/agent-session/**` 행
- `python -m pytest -q -n 8 tools/agent-session/tests`를 원래 실패 조건(SIGINT 무시 상태로 시작)에서 수정 commit 4f31e93으로 실행: 742 passed, 1565.7초(host load 190~390). 같은 조건의 수정 전은 위 8/8 실패로 갈음합니다.
- `api.py`·`state.py`·tmux option 이름은 바꾸지 않아 다른 도구 test는 실행하지 않았습니다.

### 비고
- 이 test 한 곳을 고쳤습니다. 다른 test가 자식에게 SIGINT를 보내는지는 이 CR 범위 밖이라 조사하지 않았습니다.
- 계측용 임시 test와 script는 scratchpad·작업 중 삭제했고 저장소에 남기지 않았습니다.
