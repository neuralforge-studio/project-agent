# SESSION-001: Leader start가 SessionStart 등록 성공 뒤 state를 게시하지 않은 채 끝났습니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Mode: read-only
- Base: aad704d7a9f4d0465d490262a5ed2c7f867997d9 2026-11-09T15:03:07+09:00

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
- 2026-11-09 Leader: in-progress -> open. Result 검토: 관찰은 현재 계약(게시는 시작 controller만 함)대로의 결과이며 기존 test가 같은 동작을 확인합니다. 원인은 시작 dialog 대기로 controller가 먼저 끝난 경우가 가장 유력하나, 시작 방법을 확인하지 못해 확정하지 않습니다. 빈틈을 메우는 방법(안내 보강, hook 게시, 유지)은 설계 선택이므로 사용자 결정 D-20261109-03으로 묻습니다. 결정 뒤 고칠 일은 이 CR을 todo로 옮겨 Implementation을 씁니다.

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

## Result
조사 결과 (Worker seat3, read-only, Base aad704d). 코드 변경·commit 없음. 제출 행 없음.

### 결론
**(b) 호출 방법의 문제로 보이는 쪽이 가장 유력하나, 시작 방법을 확인하지 못해 확정은 못 합니다. 동시에 (a)의 개선 여지가 있습니다.**
- 확인한 사실: 게시는 시작 controller 한 곳만 합니다. 등록 hook은 게시하지 않습니다. controller가 등록 전에 끝나면 다음 start가 올 때까지 `ready:false`, `leader:null`이 유지되는 것이 현재 계약입니다(spec 4절 Leader·5절). 관찰한 상태는 이 계약대로의 결과입니다.
- 가설(미확인): 이 run의 controller는 등록 전에 끝났습니다. 가장 가까운 원인은 시작 dialog 대기(`needs_user_action`, exit 3)입니다.

### 1. 게시 전에 controller가 끝나는 경우 (모두 `_wait_ready` 대기 중 또는 그 이전)
경로: `cli.py:140 main` → `lifecycle.py:~445 start(leader)` → `_launch`(`:325-338`) → `_wait_ready`(`:351-391`). 게시는 `:358-370`(`registered` 관찰 후 `store.update(publish)`, `write_meta(ready=True)`), 대기 loop 주기 0.1초(`:391`). 등록은 `internal.py:68-84 _register`가 `registered: true`만 씁니다. 게시는 하지 않습니다.

| # | 경우 | 코드 | 남는 흔적 |
| --- | --- | --- | --- |
| 1 | 시작 dialog 감지 → `needs_user_action`(exit 3) 반환, controller 종료. 사용자가 창에서 답하면 CLI는 계속 진행해 등록 | `lifecycle.py:385-390` | stdout JSON(`dialog`)만. window: `registered:true`, `ready:false`, `start_error:null`. state `leader:null`. diagnostics 없음 |
| 2 | 호출한 shell·tool이 시간 제한으로 controller를 SIGTERM/SIGKILL | `cli.py`에 signal handler 없음(`grep signal` 결과 `cli.py`·`lifecycle.py` 없음) | 출력 없음. 위와 같은 window·state. diagnostics 없음 |
| 3 | SIGHUP(터미널·ssh 끊김, tmux pane 닫힘) | 2와 같음. handler 없음 | 같음 |
| 4 | SIGINT(Ctrl-C) | `cli.py:200-203` `KeyboardInterrupt` → `interrupted` JSON, exit 4 | stdout JSON만. diagnostics 없음. 같은 window·state |
| 5 | `--timeout`(기본 600, `cli.py:64`) 만료 | `lifecycle.py:65-70 remaining` → `timeout` exit 4 | stdout JSON만. 같은 window·state |
| 6 | 등록 후 게시 중 오류: `_session` 검증, `_same`, `store.update`(`state_write_failed`, `target_changed` 등) | `lifecycle.py:358-370`, `state.py:202-231` | SessionError는 stdout JSON만. 비 SessionError는 `cli.py:204-210`이 `agent/diagnostics/`에 log를 남김 |
| 7 | `provider_exited`(`:381`), `registration_failed`(`:373-378`), `target_changed`(`:356`) | 같은 함수 | 6과 같은 방식. 이 셋은 `registered`가 아니거나 `start_error`가 있어 관찰과 다름 |

경우 1~5 이후 `registered:true`가 오면 아무도 게시하지 않습니다. 이 때 hook은 `internal.py:157-170 _wait_ready`에서 최대 120초 기다리다 `registration_timeout`으로 끝나지만(Claude hook 한도 30초가 먼저 자름), 이 실패는 `start_error`에 기록하지 않습니다(`_record_failure`는 `_bind` 실패만 호출, `internal.py:73-76`). 그래서 `start_error:null`이 관찰과 일치합니다.

### 2. 관찰한 흔적과 맞는 경우
- `agent/diagnostics/` 없음 → 6의 비 SessionError 예외는 아닙니다.
- run 시작 13:52:27.9(`runs/df0fad.../launch.sh` mtime) → 등록 hook 13:53:30.6(`hook_observations.SessionStart.observed_at`). 63초. 같은 base의 다른 run은 6~8초입니다(`@389` 14:41:01→05:41:07Z, `@395` 14:45:42→14:45:50, `@398` 15:03:47→15:03:55). 이 run만 약 55초 늦었습니다.
- controller가 등록 시점(13:53:30)에 살아 있었다면 0.1초 안에 게시했을 것입니다. 따라서 controller는 13:52:27~13:53:30 사이에 끝났습니다. 이 구간 동안 CLI는 정상 속도로 뜨지 못했습니다.
- 가장 자연스러운 설명은 경우 1입니다. `--permission-mode bypassPermissions`로 시작하므로 `bypass_permissions` dialog(`providers/claude.py:73-77`)에서 CLI가 멈췄고, controller는 1~2초 안에 `needs_user_action`으로 끝났으며, 사용자가 약 1분 뒤 창에서 답해 hook이 등록했을 가능성입니다. 이 경우 spec 4절·5절·README 72행의 절차(답한 뒤 같은 start 재실행)가 게시를 맡습니다. Leader가 재실행하자 게시된 것과 맞습니다.
- 경우 2·3(호출 tool·shell의 중간 종료)도 같은 흔적을 남기며, CLI 지연 55초가 별도 원인이어야 합니다. 현재 근거로 1과 구분할 수 없습니다. 구분에 필요한 것은 처음 start 호출의 stdout(`needs_user_action` 또는 무출력), 호출한 곳(터미널·Board·다른 session의 Bash tool), 13:52~13:54의 pane 화면입니다. 시작 방법은 CR 본문대로 사용자 확인 대기 중입니다.

### 3. 동결 사본과의 차이
실행한 사본(`/primehome/swain/Utils/agent/agent.base/codex/tools/agent-session`)과 이 저장소 `tools/agent-session`을 `diff -r`했습니다. `lifecycle.py`·`cli.py`·`internal.py`·`state.py`는 동일합니다(위 줄 번호는 양쪽에 같음). 다른 파일은 `remote.py`·`remote_runtime.py`·`tmux.py`(주석의 `project_board.conf`→`project-agent.conf`) 뿐이며 이 현상과 무관합니다.

### 4. 재현 (격리 tmux server + fake provider)
저장소의 테스트 fixture(`tests/fixtures/agent_session_fixture.py`의 `session_env`, `agent_session_fake_provider.py`의 `FakeProvider(dialog=True)`)로 경우 1을 재현했습니다. 이 재현은 경우 1의 상태를 만들 뿐 실제 원인이 1임을 증명하지 않습니다. 임시 test는 scratchpad에 두었고 저장소에는 없습니다.
1. `FakeProvider(dialog=True)`로 `manager.start("leader")` → `needs_user_action`(exit 3), controller 종료.
2. 창에 `approve`+Enter를 보내 CLI 등록.
3. 관찰: `registered=True ready=False start_error=None leader=None` (3초 뒤에도 유지). Leader state를 게시하는 process 없음.
4. `manager.start("leader")` 재실행 → `ready=True`, `leader={session_id, connected_at,...}`.
이 결과는 이번 관찰과 같습니다. 같은 현상을 보이는 기존 test: `tools/agent-session/tests/test_lifecycle.py:302-325 test_start_held_at_a_startup_dialog_needs_the_user_and_resumes`(`leader is None` 단언 후 재실행 start가 `ready` 확인). 즉 현재 계약의 의도된 동작입니다. 경우 2·3(signal)은 같은 상태로 이어지는 것을 코드로 확인했고 별도 재현은 하지 않았습니다.

### 5. 판단과 제안 (결정은 Leader 몫)
- 호출 방법 안내(b): `start --job leader`의 stdout이 `needs_user_action`이거나 출력 없이 끝났다면 같은 start를 다시 실행해야 게시됩니다. 호출한 shell·tool의 시간 제한(600초 `--timeout`보다 짧은 제한)과 dialog 대기 시간에 주의합니다. 게시 여부는 `agent/state.json`의 `leader`가 null인지로 확인합니다.
- 제품 개선(a, 범위·정책 선택이라 사용자 결정 대상일 수 있음): 등록과 게시 사이에 원인과 무관한 빈틈이 있습니다. dialog 반환 뒤 사용자가 답하면 등록은 되지만, 사용자가 이를 알 방법은 Leader가 `send`를 못 받는다는 간접 증상뿐입니다. 후보:
  1. 등록 hook(`_register` 뒤)이 같은 게시를 대상 제어 잠금 아래 수행(spec 5절의 "시작 controller만 게시" 계약 변경 필요).
  2. `send --job leader`·Worker 보고가 `registered && !ready`인 현재 run을 보면 게시를 마쳐 줌(`_wait_ready`의 publish 재사용).
  3. 변경 없이 `needs_user_action` 메시지에 "답한 뒤 같은 start 재실행" 안내를 강화하고 `registered && !ready` 상태를 진단 출력에 노출.
  어느 쪽도 이 CR 범위(조사)에서 구현하지 않았습니다.

### 검증 (CR Verification 대응)
1. 경우마다 코드 위치와 흔적: 위 1절 표.
2. 결론 (b)의 근거: 2절 시간 대조(63초 vs 6~8초)와 4절 재현. 확정에 필요한 처음 start의 stdout과 시작 방법이 없음을 명시했습니다. 확정은 아닙니다(c 성격이 일부 남음).
- 실행 명령: `pytest <scratchpad>/test_repro_session001.py -s` 통과(1 passed). 저장소 파일과 `__pycache__`는 정리했고 `git status` clean입니다.
