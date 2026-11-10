# SESSION-013: 부하에서 Claude MCP 서버 시동(8~32초)이 등록 hook 한도에 닿고 binding 재확인마다 서버를 새로 띄웁니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: SESSION-011, SESSION-012, PERF-004

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
