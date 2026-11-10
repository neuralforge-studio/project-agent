# SESSION-013: 부하에서 Claude MCP 서버 시동(8~32초)이 등록 hook 한도에 닿고 binding 재확인마다 서버를 새로 띄웁니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: SESSION-011, SESSION-012, PERF-004
- Base: 16fce569de54eec284550d1a6bb1a4b243f834b7 2026-11-10T19:54:37+09:00

## Symptom
host load가 높으면 등록 hook이 Claude MCP 서버를 띄우는 데만 8~32초가 걸립니다. 그래서 SESSION-011 뒤에도 hook 한도(Claude 30초, 우리 deadline 25초, binding 20초)에 닿아 Worker start가 `registration_failed`로 끝날 수 있습니다. binding을 다시 확인할 때마다 MCP 서버를 새로 띄웁니다.

## Evidence
- SESSION-011 Result: 실제 `claude mcp serve`의 시동(initialize)은 load 약 75에서 7.8~8.2초였고, 한 번은 31.8초였습니다(host load 최대 321). 후보도 load 80 측정에서 binding deadline에 한 번 걸렸습니다.
- `internal._verify_binding`은 retryable 실패마다 `provider.verify_binding`을 다시 부릅니다. `ClaudeProvider.verify_binding`은 부를 때마다 `claude mcp serve`를 새로 띄웁니다.
- SESSION-012가 stop의 대기 구간에서 서버 하나를 공유하는 `ClaudeProvider.reusing_client`를 만들었습니다.

## Contract
- Claude CLI와의 계약(`claude mcp serve`, ListAgents)과 등록의 판정·결과(`registration_failed`, `start_error`, `registration_hook_ended`)는 바꾸지 않습니다.
- hook은 Claude가 hook을 끝내기 전에 스스로 실패를 기록합니다. 우리 deadline은 Claude 한도보다 짧습니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). SESSION-011 Result가 남긴 한도 조정 제안입니다. 우리 쪽 일을 줄인 뒤에도 Claude MCP 시동이 부하에서 8~32초라는 측정 근거가 있습니다.
- 2026-11-10 Leader: open -> todo. 부하에서 hook 한도 초과, 측정 근거 있음
- 2026-11-10 Leader: 제출 a6eda8bb6ee8e0328137d34499ea3cfa3eea5625를 인수합니다. 검토 a6eda8b(구현 b1766a9 + main 1b0ea72 merge). binding 재확인을 reusing_client 블록 하나에서 돌림(verify_binding이 _peer_of 경유), HOOK_TIMEOUT 60 한 상수에서 settings timeout과 deadline 50·binding 40·reserve 12·startup cap 20, 명세 문장을 읽었습니다. main(PERF-004)과의 merge에서 spec.md 한 곳이 충돌해 Leader가 두 문장을 모두 두어 풀었습니다(2fd84c7). merge commit에서 Leader가 tools/agent-session/tests 837 passed, 네 번째 명령 130 passed를 실행했습니다. 고친 문서의 상대 link 0 broken. 측정은 start 성공 BASE 4/5 대 후보 5/5, wall·CPU same(n=3)이며 이 CR은 부하에서의 실패를 막는 변경이라 속도 개선을 판정 기준으로 삼지 않습니다.

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), [실행 경로 계약](../../project-team/README.md#실행-경로-계약), [동작 명세](../../project-team/spec.md)의 등록(5절), 측정 도구 [`tools/tests/perf/perf_bench.py`](../../../tools/tests/perf/perf_bench.py) 머리말(가짜 `claude`의 `hooks.log`), [project-team Worker 절](../../../skills/project-team/SKILL.md), `tools/agent-session/agent_session/internal.py`(`_bind`, `_verify_binding`, 한도 상수), `providers/claude.py`(`verify_binding`, `reusing_client`, `_peer_of`, `registration_hooks`), SESSION-011·SESSION-012 Result.

1. binding 재확인이 MCP 서버 하나를 공유하게 합니다. SESSION-012의 `reusing_client`를 씁니다. 공유 서버가 닫혔을 때의 처리는 SESSION-012와 같습니다.
2. 한도를 올립니다. Claude hook의 settings timeout은 30초에서 60초로, `_HOOK_BUDGET`은 25초에서 50초로 올립니다. `_BINDING_TIMEOUT`·`_PUBLISH_RESERVE`·`_STARTUP_CAP`도 같은 비율로 검토합니다. SessionStart 외 event(Stop 등)의 timeout을 함께 올릴지는 Worker가 정하고 이유를 적습니다.
3. hook 종료 감지(`registration_hook_ended`)와 `start --timeout`의 관계가 여전히 맞는지 확인합니다. start는 hook 한도에 관찰 간격을 더한 시간 안에 끝나야 합니다.
4. 명세의 한도 문장을 고칩니다.

의존: 없음. PERF-004와 `registration_hooks`가 겹칠 수 있습니다.

위험 등급: 높음. 모든 run의 등록 경로입니다.

## Verification
1. 측정 도구로 현재 `origin/main`과 후보를 비교합니다. `--scales 16x16 --groups lifecycle --reps 3 --cold-reps 0` 한 번만 잽니다. `start`의 성공 수, wall·CPU, host load를 적습니다. load가 70을 넘는 때의 성공을 보이면 좋습니다. 그런 때를 얻지 못하면 그렇다고 적습니다.
2. 다음 test를 둡니다. binding 재확인 여러 번이 MCP 서버를 한 번 띄우는 호출 수 test, 우리 deadline이 settings timeout보다 짧다는 test, 늘린 한도에서도 hook 종료 감지가 start를 한도 안에 끝내는 test입니다.
3. README 검증 표에서 바꾼 경로의 행을 모두 실행합니다(`-rf`). 측정을 기다리지 말고 측정과 동시에 돌립니다.
4. 제출 전에 `origin/main`을 merge합니다. merge가 입력을 바꾼 명령만 merge commit에서 다시 실행합니다. 측정은 merge 뒤에 다시 하지 않습니다.
5. 측정 도구가 바뀌어도 진행 중인 측정을 다시 시작하지 않습니다. 사용자가 빠른 반영을 요구했습니다. 위 범위 밖의 측정(4×4, A/A, cold)은 하지 않습니다.

## Result
- 제출 commit: a6eda8bb6ee8e0328137d34499ea3cfa3eea5625

`origin/main`(1b0ea72, release 0.5.0)을 merge한 commit입니다. 변경 commit은 b1766a9이고 `cr/SESSION-013`을 push했습니다.

### 변경
1. binding 재확인이 서버 하나를 공유합니다. `internal._bind`가 `_verify_binding` 루프를 `reusing_client` 안에서 돌리고(provider에 없으면 건너뜁니다), `ClaudeProvider.verify_binding`이 `_peer_of`를 거칩니다. 공유 서버가 끊겼을 때는 SESSION-012와 같은 규칙(한 번 새 서버로 다시 묻기)입니다.
2. 한도. settings `timeout`의 원본을 `hook_started.HOOK_TIMEOUT = 60` 하나로 두고, `_HOOK_BUDGET = HOOK_TIMEOUT - 10`(50), `_BINDING_TIMEOUT` 20→40, `_PUBLISH_RESERVE` 6→12, `_STARTUP_CAP` 10→20으로 올렸습니다. 이전에는 30과 25가 두 파일에 따로 있었습니다.
   - Stop·StopFailure·SessionEnd도 같은 60초입니다. 이 hook들도 같은 부하에서 interpreter 시동과 tmux 읽기를 하므로 30초에 걸릴 수 있고, 하나의 상수로 두면 어긋날 곳이 없습니다. 이 hook들은 오래 걸려도 Claude를 막는 시간이 늘 뿐 등록에는 영향이 없습니다.
   - Codex의 deadline도 같은 `_HOOK_BUDGET`을 쓰므로 25초에서 50초가 됩니다(Codex에는 hook 한도가 없고 기존 명세가 같은 값을 공유했습니다). 호환 영향: 관측 가능한 변화는 이 한도뿐입니다.
3. `registration_hook_ended`: 코드 변경 없음. hook 프로세스가 끝난 것을 보고 판정하므로 한도 값에 의존하지 않고, start는 hook 종료 시각 + 관찰 간격에 끝납니다. 명세의 "hook 제한(30초)"을 60초로 고쳤습니다.
4. 명세 5절(`docs/project-team/spec.md`)의 deadline·binding·공유 서버·start 한도 문장을 고쳤습니다.

### 검증
- 새 test: `test_providers.py` 2개(binding 재확인 4번이 서버 1번, 끊긴 공유 서버를 한 번 교체), `test_internal.py` 2개(재확인 루프가 `reusing_client` 블록 하나 안에서 4번 조회, deadline 단계가 settings timeout보다 짧고 네 event의 timeout이 `HOOK_TIMEOUT`과 같음). `test_lifecycle.py`의 `--kill-hook` test는 start 종료 한도를 `HOOK_TIMEOUT`으로 바꿨습니다. 기존 test의 하드코딩(20초, 25초)은 상수로 바꿨습니다.
- `python -m pytest -q -rf -n 8 tools/agent-session/tests`: 836 passed, 1 failed(내 새 test의 잘못된 부등식 `_BINDING_TIMEOUT + _PUBLISH_RESERVE <= _HOOK_BUDGET`, binding은 deadline-reserve로 잘리므로 성립할 필요가 없음). 고친 뒤 `test_internal.py`·`test_providers.py` 99 passed. 전체 suite를 다시 돌리지는 않았습니다(수정은 test 하나의 단언뿐).
- `tools/test_distribution_boundary.py` 9 passed(docs 행). 고친 문서의 상대 link는 바꾸지 않았습니다.
- merge가 `VERSION`·`CHANGELOG.md`를 바꿔 merge commit에서 네 번째 명령(130 passed)과 `install/tests`(276 passed, 2 skipped)를 다시 실행했습니다.

### 측정 (`--scales 16x16 --groups lifecycle --reps 3 --cold-reps 0`, BASE=origin/main 16fce56, CANDIDATE=이 branch의 merge 전 작업 트리)
`agent_start_worker`의 행별 결과(rc 0 성공, rc 4 실패):

| 구분 | BASE | CANDIDATE |
| --- | --- | --- |
| warm 성공 수 | 4/5 (rep2 한 번 rc 4, host load 89) | 5/5 |
| warm wall 중앙값 | 27.2초 | 36.5초 |
| warm CPU 중앙값 | 3.08초 | 3.25초 |
| count 단계(1회씩) | rc 4 (load 113, 52.5초) | rc 0 두 번 (load 181, 85) |

- warm의 wall·CPU는 `same`(ratio 구간이 1을 포함, wall 0.39-2.50, CPU 0.67-1.39)입니다. 표본이 3이라 속도 차이는 말할 수 없습니다. host load는 rep마다 43~104였습니다.
- load가 70을 넘는 때의 성공: CANDIDATE는 load 103.6, 93.1, 88.0(warm)과 181, 85(count)에서 성공했고 70 아래는 rep3의 두 번(53, 43)뿐입니다. BASE의 실패 1건(load 89)은 같은 load대에서 CANDIDATE가 성공한 구간입니다. 다만 BASE 실패의 원인(hook 한도인지)은 이 측정으로 확인하지 못했습니다(rc 4만 기록). 표본이 작아 개선이라고 단정하지 않습니다.
- 측정은 merge 전 트리에서 했고 merge 뒤에는 다시 하지 않았습니다. 4×4, A/A, cold는 하지 않았습니다.
