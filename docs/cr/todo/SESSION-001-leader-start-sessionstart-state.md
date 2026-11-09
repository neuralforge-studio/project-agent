# SESSION-001: Leader start가 SessionStart 등록 성공 뒤 state를 게시하지 않은 채 끝났습니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Mode: read-only

## Symptom
2026-11-09 13:52 project-agent Leader(run `df0fad2994a0410095a7024e7c34585d`)를 시작했습니다. SessionStart 내부 등록은 성공했습니다(window option `registered: true`, `start_error: null`, hook의 session_id가 기대값과 같음). 그러나 `agent/state.json`의 `leader`가 null이고 `ready: false`였습니다. 게시를 맡는 시작 controller process는 이미 없었습니다. Leader가 같은 `agent-session start --job leader`를 다시 실행하자 `_wait_ready`가 게시했습니다(`connected_at` 2026-11-09T04:55:03Z). 게시 전까지 Worker는 `send --job leader`로 보고할 수 없습니다.

## Evidence
- window `@379` option: `@agent_session_registered true`, `@agent_session_ready false`, `@agent_session_start_error null`, `@agent_session_hook_observations`의 SessionStart `observed_at` 2026-11-09T04:53:30Z, `source: startup`
- `agent/state.json` mtime 13:52:27(예약 기록), 내용 `"leader": null`
- 13:54 `ps`에 `agent_session` 관련 controller process 없음. `agent/diagnostics/` 없음
- 명세 `docs/project-team/spec.md` 5절 "Provider 내부 등록"(시작 controller가 등록을 기다려 게시), 4절 Leader(다시 실행한 start는 등록을 기다려 게시)
- 코드: 실행한 library는 agent 저장소의 동결 사본(`/primehome/swain/Utils/agent/agent.base/codex/tools/agent-session`), `lifecycle.py:351-375`(`_wait_ready`), `:461-475`(Leader start)
- 시작 방법(터미널 명령, Board, 다른 session의 Bash tool 등)은 아직 확인하지 않았습니다.

## Contract
- 명세 4절·5절: start는 등록을 기다려 canonical state에 게시한 뒤 시작 완료를 반환합니다. 게시 전에 controller가 끝나면 다음 start가 게시합니다.

## Disposition
- 2026-11-09 Leader: 조사한다(Leader 판정, read-only). 이 project의 Leader 시작에서 관찰한 이상이며 원인은 확인하지 않았습니다. 조사는 위임 범위입니다. 결과에 따라 Leader가 고치기(todo), 판정 보류(open), 문제 없음(done waived)으로 옮깁니다. 시작 방법은 사용자에게 확인을 요청했습니다(2026-11-09 대화). 답을 받으면 이 절에 적습니다.

## Implementation
- Mode는 read-only입니다. 업무 branch를 만들거나 commit·push하지 않습니다. 결과는 `## Result`에 씁니다.
- 읽을 문서: [동작 명세](../../project-team/spec.md) 4절 Leader, 5절 "Provider 내부 등록", 7절 shutdown·resume.

1. Leader start가 등록을 기다려 게시하는 경로(`lifecycle.py`의 Leader start, `_wait_ready`, CLI의 timeout·signal 처리)를 따라, 게시 전에 controller가 끝날 수 있는 경우를 모두 나열합니다. 예: 호출한 shell·tool이 시간 제한으로 process를 끝냄, 사용자 중단(SIGINT·SIGHUP), timeout, 예외. 경우마다 window option·state·diagnostics에 남는 흔적을 적습니다.
2. 관찰한 흔적(Evidence)과 맞는 경우를 고릅니다. 실행한 library는 agent 저장소의 동결 사본입니다. 이 저장소 코드와 다르면 그 차이를 적습니다.
3. 결론을 셋 중 하나로 적습니다. (a) 제품 결함: 게시 전에 controller가 끝나는 것을 막거나, 끝나도 다음 행동(예: Worker의 `send`, Leader 자신의 hook)이 게시를 마치게 할 방법. (b) 호출 방법의 문제: 안내할 내용. (c) 판정 불가: 더 필요한 근거.
4. 같은 현상을 격리 tmux server와 fake provider로 재현할 수 있으면 재현 절차를 적습니다.

의존: 없음. 다른 CR과 병렬로 진행합니다.

위험 등급: 낮음(read-only).

## Verification
1. Result에 나열한 경우마다 코드 위치(`path:line`)와 흔적이 있습니다.
2. 결론이 (a)·(b)이면 재현 절차 또는 그 경우를 뒷받침하는 근거가 있습니다.
