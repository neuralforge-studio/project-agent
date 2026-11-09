# TEST-001: agent-session test_codex_trust_dialog_returns_its_window_and_reuses_the_run이 load가 높을 때 6초 제한을 넘겨 실패합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3
- Base: ce1f4e2178e2d82b6e081f161373e206bf6ac412 2026-11-09T14:45:03+09:00

## Symptom
병렬 실행(`-n 8`)이나 host load가 높을 때 이 test가 간헐적으로 실패합니다. 단독 실행은 통과합니다. 매 검증에서 알려진 실패로 따로 확인해야 해서 회귀 판정을 흐립니다.

## Evidence
- `tools/agent-session/tests/test_lifecycle.py:328-341`: `env.manager(timeout=6).start(job)` 뒤 `assert time.monotonic() - started < 6`
- agent DIST-004 Result(2026-11-09, load average 30~60): `-n 8` 실행에서 6.24초로 실패, 단독 실행 통과(11.28초)
- REPO-001 Result: 같은 test가 이번에는 통과(간헐)

## Contract
- README의 검증 명령은 load와 무관하게 같은 결과를 내야 합니다. test는 관찰 가능한 동작을 검증하고, host 속도에 기대는 시간 단언은 그 동작의 계약일 때만 둡니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 여러 CR(agent DIST-004, REPO-001, TMUX-001)의 Result에 같은 간헐 실패가 재현 근거와 함께 남아 있습니다. 근거가 있는 결함 수정이므로 위임 범위입니다. 사용자 지시(2026-11-09 "남은 CR은 전부 등록해서 얼마나 남았는지 알 수 있게 해줘")에 따라 열었습니다.
- 2026-11-09 Leader: 제출 5d5cc7ca3e2425fd5ada63ec25e3521a06f9059c를 인수합니다. Leader review: test 두 개의 host 속도 단언만 지운 diff를 확인했습니다. 대기 한도를 다 쓰면 code가 timeout이 되므로 남은 code 단언(needs_user_action, registration_failed)이 '한도를 기다리지 않고 반환'을 계속 구분합니다. Result의 부하 재현(수정 전 23/24 실패, 수정 후 0/24)과 agent-session suite 704 passed를 근거로 인수합니다. Worker가 보고한 극한 부하(CPU 점유 64개+16개 동시)에서의 tmux client 10초 한도·fixture 15초 한도 만료는 CR 증거 범위(-n 8, load 30~60)를 크게 넘으므로 이번에는 CR을 열지 않습니다. 다시 볼 조건: 통상 검증(README 명령)에서 tmux_unknown 또는 timeout 실패가 재현될 때.

## Implementation
읽을 문서: [README의 검증](../../../README.md#검증), 해당 도구의 README.

1. 근본 원인을 찾습니다. 실패가 test의 기다리는 방식(고정 시간, 화면 갱신 전 조회) 때문인지, 제품 동작(시간 제한, popup 생성 순서) 때문인지 구분하고 근거를 Result에 적습니다.
2. test가 원인이면 관찰 가능한 동작을 기다리는 방식으로 고칩니다. host 속도에 기대는 시간 단언은 그 시간이 제품 계약일 때만 남기고, 남기면 계약 위치를 적습니다. 제품이 원인이면 제품을 고치고 그 동작의 test를 둡니다.
3. 같은 원인의 다른 test가 있으면 같은 방식으로 고치고 목록을 Result에 적습니다. 원인이 다른 실패는 고치지 않고 Leader에게 보고합니다.

의존: 없음. 다른 CR과 병렬로 진행합니다.

위험 등급: 낮음. test 또는 좁은 제품 경로만 바꿉니다.

## Verification
1. 재현(수정 전 실패): load가 높은 조건(예: 해당 suite를 `-n 8`로 돌리면서 같은 test를 반복, 또는 CPU 부하 process를 함께 실행)에서 그 test를 20번 이상 실행해 실패 횟수를 기록합니다.
2. 수정 뒤 같은 조건, 같은 횟수에서 실패 0번입니다.
3. 영향 회귀: 해당 suite 전체(README의 명령)가 통과합니다.

## Result
- 제출 commit: 5d5cc7ca3e2425fd5ada63ec25e3521a06f9059c

### 근본 원인
- 원인은 test입니다. 제품은 고장나지 않았습니다. 확인한 사실:
  - 제품(`lifecycle.py`의 start 대기 loop)은 `DIALOG_SCREEN_SECONDS=1`마다 pane을 읽어 dialog를 감지하면 한도를 기다리지 않고 `needs_user_action`을 반환합니다. 감지하지 못하면 Manager 한도를 다 쓰고 `timeout` 오류가 납니다.
  - test는 `env.manager(timeout=6)`으로 한도를 줄이고 `assert time.monotonic() - started < 6`을 둡니다. 이 시간은 start 전체(worktree·window 준비 포함)가 host 속도로 걸린 값이라 제품 계약이 아닙니다. "한도를 기다리지 않고 반환"이라는 동작은 error code 단언(`timeout`이 아님)이 이미 구분합니다.
- 수정 전 재현: 단일 test 8개 동시 × 3회, CPU 점유 process 24개를 함께 실행 → 24번 중 23번 실패. 실패는 모두 `test_lifecycle.py:341` 시간 단언(경과 6.1~7.0초)입니다. 부하 process 64개·16개 동시 × 2회에서는 32번 중 32번이 같은 단언으로 실패했습니다. 부하 없이 8개 동시 × 3회(host load 60 안팎)는 24번 모두 통과해 재현되지 않았습니다.

### 수정
- `test_codex_trust_dialog_returns_its_window_and_reuses_the_run`: `timeout=6`과 시간 단언을 지우고 fixture 기본 한도(`AGENT_SESSION_TEST_TIMEOUT`, README 문서화)를 씁니다. 감지 실패는 `needs_user_action` code 단언이 잡습니다. 시간 단언은 남기지 않았습니다(제품 계약이 아님).
- 같은 원인의 다른 test: `test_lifecycle.py`의 registration_failed start test(`start must not wait for its timeout`, `timeout=60`, `< 30` 단언)를 같은 방식으로 고쳤습니다. 증거에 나온 실패는 아니지만 같은 형태의 host 속도 단언입니다. 목록은 이 둘입니다.
- 고치지 않은 것: `manager(timeout=2/3/5)`를 쓰는 stop 관련 test(`test_lifecycle.py` 814·838·918·937·1001행 부근)는 짧은 한도 자체가 `timeout`·`pane_input_blocked` 오류를 일으키는 자극이라 원인이 다릅니다.

### 검증
1. 수정 전(같은 조건: 8개 동시 × 3회, CPU 점유 process 24개): 24번 중 23번 실패. 부하 64개·16개 동시 × 2회: 32번 중 32번 실패.
2. 수정 후 같은 조건·같은 횟수: 24번 중 0번 실패.
3. 영향 회귀: `python -m pytest -q -n 8 tools/agent-session/tests` → 704 passed (411.92초).

### 남은 문제(이 CR 범위 밖, Leader 보고)
- 수정 후 가장 가혹한 조건(CPU 점유 process 64개 + 16개 동시, test 1회에 46초)에서는 32번 중 4번이 다른 원인으로 실패했습니다. 3번은 제품의 tmux client 명령 한도 `subprocess.run(..., timeout=10)`이 만료되어 `tmux_unknown`이 났고, 1번은 fixture 기본 한도 15초가 소진되어 `timeout`이 났습니다. 이 부하는 CR 증거(`-n 8`, load 30~60)를 크게 넘고, 15초 한도는 README가 `AGENT_SESSION_TEST_TIMEOUT`으로 올리라고 안내한 경우입니다. 고치지 않았습니다.
