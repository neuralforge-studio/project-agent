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
- 2026-11-09 Leader: 제출 56b7035efb5477623b5bc424eabfd10432d6eb45를 인수합니다. Leader review: fixture 한도·test UUID·README만 바꾼 diff를 확인했습니다. 원인 (b)는 3개 동시 실행의 실패 285건 전부가 같은 timeout code이고 Manager 명령 1350개 계측(p99 29.8초, 최대 38.0초)으로 확정, 120초는 측정 최대의 약 3배이며 보장 내용(끝나지 않는 명령을 실패로 바꿈)이 fixture 주석과 README에 있습니다. 원인 (d)는 host 전체 /proc 검색과 고정 UUID로 확정. 수정 후 같은 조건 3회 704 passed. 제품 한도는 바꾸지 않음.

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

## Result
- 제출 commit: 56b7035efb5477623b5bc424eabfd10432d6eb45

수정 commit은 a74b038이고, 56b7035는 그 위에 `origin/main`(7686b7f)을 merge한 것입니다. merge로 들어온 변경은 `tools/agent-session`과 README를 건드리지 않아서 전체 검증은 merge 전 상태의 결과를 재사용했고, 바뀐 test 파일 두 개(`test_process.py`·`test_fixture_timeout.py`)만 merge 상태에서 다시 돌렸습니다(14 passed).

### 변경
1. `tests/fixtures/agent_session_fixture.py`: 기본 대기 한도 15초 → 120초, 근거를 주석에 적었습니다.
2. `tests/test_process.py`: `test_session_holders_finds_a_process_that_names_the_conversation_and_not_this_one`의 고정 conversation ID를 실행마다 새 UUID로 바꿨습니다.
3. `tests/test_fixture_timeout.py`: 기본값 단언을 120으로 맞췄습니다.
4. `README.md`·`tools/agent-session/README.md` 검증 안내를 결과에 맞췄습니다. 제품 코드와 제품 한도는 바꾸지 않았습니다.

### 측정 조건
이 workstation은 측정 전부터 다른 사용자의 VCS 시뮬레이션 수십 개가 돌아 load average가 75~110(64 core)이었습니다(`uptime`: 15:25 82.9, 15:44 75.4, 16:21 64.4). 그 위에 `-n 8` suite를 3개 동시에 돌렸습니다(worker 24개). seat 4개가 동시에 검증하는 조건보다 같거나 무겁습니다.

### 1. 재현(수정 전)과 원인
같은 suite(`python -m pytest -q -n 8 tools/agent-session/tests`, base 3781d7b) 3개 동시 실행입니다.

| 실행 | 결과 | 시간 |
| --- | --- | --- |
| r1 | 94 failed, 610 passed | 848.7초 |
| r2 | 93 failed, 611 passed | 847.9초 |
| r3 | 98 failed, 606 passed | 814.2초 |

- 실패 285건(서로 다른 test 107개) 전부 오류 code가 같았습니다: `SessionError: The command's total wait limit expired.`(`timeout`, `lifecycle.py:68`). 실패한 test의 `call` 시간은 29~34초였습니다.
- 3번 모두 실패한 test가 82개, 1~2번 실패가 25개입니다. 파일별로는 `test_lifecycle` 58, `test_suspend` 38, `test_background` 10, `test_start_seat` 1입니다.
- tmux client 10초 한도(`tmux_unknown`)는 이 부하에서 한 번도 나오지 않았습니다. 이 한도는 `tmux_unknown`을 내는 제품 한도라 바꾸지 않았습니다. TEST-001이 본 `tmux_unknown`은 CPU 점유 80개를 추가한 극한 부하였고, 평소 부하에서는 재현되지 않았습니다.

#### 원인 (b): fixture 대기 한도 15초가 부하에서 부족함
- `Manager(timeout=command_timeout())`의 `self.end`는 만들 때 정해지고 `remaining()`(`lifecycle.py:65`)이 그 남은 시간으로 모든 대기를 제한합니다. fixture의 15초(`agent_session_fixture.py:27`)는 `start` 한 번의 전체 시간 상한입니다. 계측한 1329개 Manager 중 명령을 2개 이상 부른 것은 3개뿐이라 사실상 명령당 한도입니다.
- `start`는 tmux pane에서 fake provider Python을 띄우고, 이 자식이 `agent_session` 전체를 import해 등록할 때까지 `_wait_ready`(`lifecycle.py:351`)가 기다립니다. `test_the_force_alarm_names_the_kill_time` 한 개를 프로파일하면 subprocess 약 500개와 `start` 2번 15.6초였고, import 시간이 0.66~3.85초로 흔들렸습니다(`python -X importtime`: `json` 하나가 0.42초). 소스와 stdlib가 NFS에 있고 CPU를 다투기 때문입니다.
- 계측(Manager 명령 시간, 한도 300초로 3개 동시 실행, 1350개 명령): p50 9.8초, p90 21.4초, p99 29.8초, 최대 38.0초. 15초를 넘은 명령이 368개(27%)였습니다.
- 이 한도가 보장하는 것은 끝나지 않는 명령을 test 실패로 바꾸는 것입니다. 속도는 단언하지 않습니다. 그래서 값은 측정한 최대 38초의 약 3배인 120초로 정했고, 근거를 fixture 주석에 적었습니다. 값을 올리는 것만으로 끝낸 것이 아니라, 15초가 실제 작업 시간보다 짧은 것이 원인임을 위 측정으로 확인했습니다. 제품 코드 한도는 그대로입니다.
- 실제로 멈춘 명령은 120초 뒤에 실패하므로 실패 판정이 늦어집니다. 한도를 일부러 줄여 timeout 동작을 확인하는 test는 `env.manager(timeout=2~5)`로 명시해서 영향이 없습니다.

#### 원인 (d): test 사이 공유 자원 경합 (한도를 올려도 남은 실패)
- 한도 300초 계측에서 3번 중 2번 `test_process.py::test_session_holders_finds_a_process_that_names_the_conversation_and_not_this_one`이 `assert [478456] == []`로 실패했습니다.
- `process.session_holders`는 host 전체 `/proc/*/cmdline`에서 ID를 찾습니다(`process.py:172`). test가 고정 UUID `5d0c3a2e-…`를 쓰므로 동시에 도는 다른 suite(다른 seat)의 같은 test 자식이 걸립니다. 실행마다 새 UUID를 쓰도록 고쳤습니다.
- 같은 계측에서 `test_control_queue::test_external_control_cannot_overtake_a_pending_self_request`가 3번 실패했으나, 계측 plugin이 `Manager.__new__`로 만든 객체의 `_spy_calls`를 읽은 것으로 제 계측의 결함입니다(오류가 `AttributeError: 'Manager' object has no attribute '_spy_calls'`). 계측 없는 수정 후 실행 3번 모두 통과했습니다.
- (a)(c)(e)로 분류되는 실패는 없었습니다.

### 2. 수정 후 같은 조건, 같은 횟수
같은 조건(suite 3개 동시, 각 `-n 8`, 한도는 새 기본값 120초)입니다.

| 실행 | 결과 | 시간 |
| --- | --- | --- |
| r1 | 704 passed | 1032.9초 |
| r2 | 704 passed | 1029.5초 |
| r3 | 704 passed | 1031.3초 |

실패 0번입니다(수정 전 93~98개). 시간은 수정 전보다 길었습니다(848초 → 1031초). 수정 전에는 실패한 test가 한도에서 일찍 끝났고, 수정 후에는 그 test들이 끝까지 실행되기 때문입니다. 같은 부하에서 통과한 test 수가 610 → 704입니다.

### 3. 추가 부하 없는 `-n 8` 전체 suite (suite 하나만 실행)
host의 다른 사용자 부하는 그대로입니다(load average 58~64).
- 수정 후(기본 120초): 704 passed, 641.3초.
- 수정 전 한도(`AGENT_SESSION_TEST_TIMEOUT=15`로 지정): 10 failed, 694 passed, 600.1초. 한도만 15초면 suite 하나만 돌려도 이 host에서는 실패합니다.
- 수정 전과 후의 전체 시간은 host 부하 변동 범위의 차이로 대기 방식은 바꾸지 않았습니다.
- 수정은 한도 값과 test ID뿐이라 느려질 원인이 없습니다.

### 4. 한도의 근거와 보장
위 "원인 (b)"의 측정값과 보장 내용이 fixture 주석(`agent_session_fixture.py`의 `DEFAULT_TIMEOUT`)과 `tools/agent-session/README.md`·`README.md` 검증 절에 있습니다.

### 검증 명령
- `python -m pytest -q -n 8 -p no:cacheprovider -rf tools/agent-session/tests`를 수정 전 3개 동시, 계측 3개 동시(한도 300초, 계측 plugin은 scratchpad), 수정 후 3개 동시, 단독 2회(수정 후, 한도 15초 지정)로 실행했습니다.
- merge 후 `python -m pytest -q -n 2 tools/agent-session/tests/test_process.py tools/agent-session/tests/test_fixture_timeout.py`: 14 passed.
- 이 CR이 README 명령 중 첫 줄(agent-session suite)만 바꾸므로 다른 세 명령(`project-item`, `project-board`, integrations)은 실행하지 않았습니다. 해당 test와 코드는 바뀌지 않았습니다.
