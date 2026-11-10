# SESSION-011: 16 project × seat 16에서 등록 hook이 한도에 닿아 Worker start가 실패하거나 600초를 기다립니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: PERF-001, SESSION-010, SESSION-012
- Base: 78e6f77fb5e9bbc28d361fe8c9af9bdddfd0050b 2026-11-10T15:56:42+09:00

## Symptom
project 16개 × seat 16개에서 Worker `start`의 등록 hook(SessionStart)이 seat 수와 host 부하에 비례해 길어져 한도(`_HOOK_BUDGET` 25초, settings의 hook timeout 30초)에 닿습니다. 부하가 높으면 `start`가 `registration_failed`로 실패합니다. hook이 timeout으로 강제 종료되면 실패 기록이 남지 않아 `start`가 약 600초를 기다린 뒤에야 끝납니다. 사용자가 물은 규모(2026-11-10: "project가 굉장히 여러개 일때도? 예를 들어 각 seat가 16개씩 project 16개?")에서 Worker를 시작할 수 없는 결함입니다.

## Evidence
- PERF-001 측정(2026-11-10, `tools/tests/perf`, 격리 tmux server, 가짜 `claude`):
  - shim 없는 timing 환경, load 34~74:
    - v0.3.0: hook 15.5초·13.8초, `start` 38.6초·30.1초
    - v0.4.0(main d417943): hook 8.5초, `start` 24.0초
    - load 73일 때 v0.4.0 hook이 25.97초 만에 rc=1로 끝나고 `start`가 `registration_failed`("Claude MCP did not reply before the deadline")로 실패했습니다.
    - 4×4에서는 둘 다 정상입니다(v0.4.0 `start` tmux 177번, 4.8초).
  - shim이 붙은 counting pass: 둘 다 hook이 30초를 넘었고, `start`는 604초·608초 뒤 timeout으로 끝났습니다. v0.4.0의 `start` tmux 2208번은 등록 완료를 0.1초 간격으로 기다린 조회입니다.
- 코드(`tools/agent-session/agent_session/internal.py`):
  - `_run`(24행)은 `leader`와 모든 seat를 돌며 slot마다 `get_current`를 부릅니다. seat 16개면 tmux 실행이 34번입니다. `mark_process`와 등록 hook이 모두 이 함수를 지납니다. SESSION-010의 `server_view`를 쓰지 않는 반복 조회입니다.
  - `_bind` → `_verify_binding`은 provider의 binding 확인(Claude MCP 시동과 ListAgents)을 1초 간격으로 되풀이할 수 있습니다(`_BINDING_TIMEOUT` 20초).
  - `_record_failure`는 hook이 SessionError로 끝날 때만 실패를 남깁니다. hook process가 Claude의 hook timeout으로 죽으면 아무것도 남지 않습니다.

## Contract
- 16×16 규모에서 host load 70 이상일 때도 Worker `start`가 성공합니다.
- 등록 hook이 결과(게시 또는 실패 기록) 없이 끝나면 `start`는 hook 한도에 짧은 여유를 더한 시간 안에 오류로 끝납니다. 오류는 이유를 담은 `registration_failed`입니다. 600초를 그냥 기다리지 않습니다.
- CLI JSON·state 형식·tmux option의 의미는 바꾸지 않습니다. 새 필드나 option이 필요하면 동작 명세와 형식 버전 규칙(release.md 3절)을 따릅니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 재현 측정이 있는 결함입니다. 사용자가 물은 규모에서 Worker 시작이 실패합니다.
- 2026-11-10 Leader: open -> todo. 16x16에서 start 실패, 재현 측정 있음

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), [동작 명세](../../project-team/spec.md)의 등록·게시(3절, 5절), `tools/agent-session/agent_session/internal.py`, `providers/claude.py`, SESSION-010의 `ServerView`, 측정 도구 `tools/tests/perf/perf_bench.py` 머리말(가짜 `claude`의 `hooks.log`), [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 시간 분해: 4×4와 16×16에서 등록 hook의 단계별 시간을 잽니다. 단계는 interpreter 시동, `_run`, provider binding 확인(MCP 시동·ListAgents·close), 잠금 대기, 게시입니다. 각 단계의 tmux·subprocess 수도 함께 잽니다.
2. hook 경로의 반복 조회를 없앱니다. `_run`이 slot마다 `get_current`를 부르지 않게 하고, `server_view` 같은 한 번의 읽기로 run을 찾습니다. `mark_process` 등 같은 함수를 지나는 다른 경로도 함께 바뀝니다. 그 밖에 hook 안에서 slot·project 수에 비례하는 일이 있으면 함께 고칩니다.
3. provider 확인의 비용을 1단계 근거로 줄입니다. 예: 되풀이 확인에서 MCP client를 다시 띄우지 않기, 불필요한 close 대기 없애기. Claude CLI와의 계약(`claude mcp serve`, ListAgents)은 바꾸지 않습니다.
4. hook이 결과 없이 끝나면 `start`가 hook 한도에 짧은 여유를 더한 시간 안에 `registration_failed`로 끝나게 합니다. hook이 시작했고 결과 없이 끝났다는 사실이 남아야 합니다. 예: hook이 자기 시작 시각과 process를 run 기록에 남기고, `start`가 그 process의 종료를 봅니다. 방법은 Worker가 정하고 명세에 적습니다.
5. 1~4로도 부하가 높을 때 한도가 부족하다는 근거가 나오면, 한도(`_HOOK_BUDGET`, settings timeout)의 조정을 근거와 함께 제안합니다. 한도만 늘리는 것은 해법이 아닙니다.

의존: 없음. SESSION-012와 `lifecycle.py`·`providers/claude.py`가 겹칠 수 있습니다. 제출 전에 `origin/main`을 merge합니다.

위험 등급: 높음. 모든 run의 시작 등록 경로입니다.

## Verification
1. 측정 도구로 v0.4.0과 후보를 비교합니다. 규모는 16×16과 4×4이고, `start`(Leader·Worker), 등록 hook 단계 시간, tmux 수를 봅니다. host load도 함께 적습니다.
2. 16×16에서 load가 높은 때(70 이상)에 `start`가 성공함을 보입니다. 그런 때를 얻기 어려우면 CPU 부하를 걸어 재현합니다.
3. hook이 결과 없이 끝나는 경우(예: hook을 강제로 죽이는 test)에 `start`가 한도 안에서 `registration_failed`로 끝나는 test. 수정 전에 실패해야 합니다.
4. hook 경로의 tmux 실행 수가 seat 수와 무관하다는 호출 수 test.
5. README 검증 표에서 바꾼 경로의 행을 모두 실행합니다(`-rf`). `api.py`·state 형식·tmux option을 바꾸면 project-item·project-board·`install/tests`도 실행합니다.
6. 제출 전에 `origin/main`이 움직여 위 명령의 입력을 바꿨으면 merge하고 merge commit에서 다시 실행합니다.
