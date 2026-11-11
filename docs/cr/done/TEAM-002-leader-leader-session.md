# TEAM-002: 할 일이 없으면 Leader 자기 점검이 Leader session에 들어가지 않습니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S3
- Base: 036ccf1a7cd3f7d29bb82d701801fdbd4142b058 2026-11-11T15:06:05+09:00
- Outcome: fixed

## Symptom
Leader의 자기 점검(session cron, 30분마다)은 할 일이 없어도 매번 Leader session에 prompt로 들어와 turn을 엽니다. 사용자 화면에 점검 메시지와 "조치할 일 없음" 응답이 쌓입니다.

사용자 요청(2026-11-11): "leader session용 cron 같은 경우에, 30분동안 아무런 변화가 없더라도, open / todo / in progress CR이 없고, Decisio 사항도 없으면 leader session에 message를 보내지 않도록 수정이 필요할 것 같아."

## Evidence
- 점검 cron 식과 prompt의 원본은 [self-check.md](../../../skills/project-team/references/self-check.md)입니다. Leader 식은 `8,38 * * * *`입니다.
- `CronCreate`는 정해진 시각에 prompt를 무조건 넣습니다. 조건을 걸 수 없습니다.
- 실행 방식은 사용자 결정으로 정해져 있습니다. SESSION-006 Disposition의 사용자 원문은 "TUI 자체적인 cron 기능은 없나? 정확하게 instance적으로 돌아가길 바래."입니다. 그래서 중앙 감시 process와 system crontab은 두지 않습니다([동작 명세 watch](../../project-team/spec.md#watch)).
- Leader run의 Claude settings(`agent/runs/<run>/settings.json`)에는 agent-session이 넣는 hook(SessionStart, Stop 등)이 있습니다.
- 이 project에는 사용자 지시로 보류한 SESSION-002가 open에 있습니다.

## Contract
1. Leader의 project에 open·todo·in-progress CR이 없고, open·answered 결정 항목도 없으면, 자기 점검은 Leader session에 아무것도 넣지 않습니다. prompt, turn, 화면 출력이 모두 없습니다.
2. 그런 항목이 하나라도 있으면 자기 점검은 지금처럼 실행됩니다.
3. 할 일이 없다가 생기면, 누가 다시 등록하는 것을 기억하지 않아도 다음 주기에 점검이 다시 실행됩니다. 할 일이 없는 동안에도 session cron 등록과 만료 갱신(7일)이 끊기지 않습니다.
4. 실행 방식(각 instance의 session cron, 중앙 process 없음)은 바꾸지 않습니다. Worker 자기 점검은 바꾸지 않습니다.

## Disposition
- 2026-11-11 Leader: 구현한다. 사용자 요청입니다(원문은 Symptom). 방법은 Leader 판정이고, 조사 결과에 따라 고릅니다. 사용자는 바꿀 수 있습니다. 조건은 두 가지입니다. SESSION-006의 사용자 결정(instance의 session cron)을 지키고, 점검이 다시 실행되는 것이 누구의 기억에도 의존하지 않아야 합니다.
- 2026-11-11 Leader: open -> todo. 사용자 요청
- 2026-11-11 Leader: 제출 4235c7615500a123c44d4adfb38c1d13aaccb3b8를 인수합니다. 검토 4235c76(구현 c188f12 + main 4e011ba merge, merge는 CR·CHANGELOG·project-board만). 조사(session cron prompt도 UserPromptSubmit을 거침, block 시 turn·user 기록 없음, 화면에 두 줄 남음, timeout이면 통과), self_check_gate.py(첫 줄로 Leader 점검만 판정, project-item의 상태 목록 재사용, 모든 예외 통과, 24시간 heartbeat로 7일 갱신 유지), claude.py의 Leader run 한정 hook, spec·README·self-check.md를 읽었습니다. agent-session 872 passed, distribution boundary 9, 문서 link 검사, 실제 Claude Code 2.1.322 막힘·통과·timeout 확인. Contract 1의 '화면 출력 없음'은 만족하지 못합니다(30분마다 두 줄, 하루 한 번 실제 점검). 다른 방법은 SESSION-006 사용자 결정(instance session cron)이나 Contract 3에 어긋나므로, 이 차이를 인수하고 사용자에게 알립니다.
- 2026-11-11 Leader: in-progress -> done, Outcome fixed. 통합 39a82bc (origin/main)

## Implementation
읽을 문서:
- [self-check.md](../../../skills/project-team/references/self-check.md), [동작 명세 watch](../../project-team/spec.md#watch)
- `tools/agent-session/agent_session/launch_artifacts.py`(`self_check_text`, settings 생성), `providers/claude.py`(hook 설치)
- SESSION-006·SESSION-009 CR
- Claude Code의 hook 문서(UserPromptSubmit의 block 동작). `claude-code-guide` agent에 물어도 됩니다.
- [project-team Worker 절](../../../skills/project-team/SKILL.md)

1. 조사: 다음을 실제 Claude Code 2.1.319에서 시험하고 Result에 적습니다.
   - session cron이 넣는 prompt도 `UserPromptSubmit` hook을 거치는지
   - hook이 막으면(block 또는 exit 2) 화면·대화 기록·turn에 무엇이 남는지
   - 그 밖에 조건부로 넣지 않을 방법이 있는지
2. Contract 1~3을 만족하는 방법을 고릅니다. 예를 들면 Leader run의 settings에 hook을 넣어, 자기 점검 prompt이고 할 일이 없을 때 막는 방법입니다. 할 일 판정은 `project-item`의 상태 목록과 같은 원본을 씁니다. hook의 시동 비용과 실패할 때의 동작(판정 실패면 점검을 통과시킴)도 정합니다.
3. self-check.md와 명세를 고칩니다. cron prompt의 원본은 계속 self-check.md입니다.
4. Test: 할 일 없음이면 막음, 각 항목(open, todo, in-progress, open 결정, answered 결정)이 하나라도 있으면 통과, 판정 실패면 통과, Worker 점검과 일반 사용자 입력은 영향 없음.

의존: 없음.

위험 등급: 중간. Leader 감시가 멈추는 쪽으로 틀리면 안 됩니다. 판정이 불확실하면 점검을 통과시킵니다.

## Verification
1. README 검증 표에서 바꾼 경로의 행 명령 전부를 실행합니다. `tools/agent-session/**`, `skills/**`·`docs/**`(문서 link 검사, `tools/test_distribution_boundary.py`, `tools/agent-session/tests/test_remote.py`) 행입니다.
2. 실제 Claude Code에서 session cron prompt가 막히는 것과 통과하는 것을 한 번씩 확인하고 Result에 적습니다.

## Result
- 제출 commit: 4235c7615500a123c44d4adfb38c1d13aaccb3b8

`origin/cr/TEAM-002`에 push했습니다(구현 commit `c188f12` + `origin/main`(4e011ba) merge). Merge는 CR 파일·CHANGELOG·project-board만 바꿔서 agent-session·skills·docs 검증 입력이 달라지지 않았고, 아래 검증 근거를 재사용했습니다(merge 뒤 `test_distribution_boundary.py`와 새 test만 다시 실행해 통과).

### 조사 (실제 Claude Code 2.1.322, 격리 tmux server에서 `CronCreate` `* * * * *`로 시험)
1. **session cron이 넣는 prompt도 `UserPromptSubmit` hook을 거칩니다.** hook이 받은 event는 `{session_id, transcript_path, cwd, prompt_id, permission_mode, hook_event_name: "UserPromptSubmit", prompt}`이고 `prompt`가 cron prompt 원문입니다. 사용자 입력과 구별하는 필드는 없어서 prompt 첫 줄로 알아봅니다.
2. **hook이 막으면:**
   - `{"decision":"block","reason":...}`와 exit 2는 같습니다. 모델 호출(`api-request`)과 `user` 기록이 없고 turn이 열리지 않습니다. cron은 다음 주기에도 계속 실행됩니다.
   - 화면에 `✻ Running scheduled task (...)` 줄과 `● UserPromptSubmit operation blocked by hook: <reason>` + `Original prompt: ...`가 남습니다. 대화 기록에는 시각이 있는 `queue-operation`(enqueue·dequeue), `system`(`scheduled_task_fire`, `informational`)이 남습니다.
   - `suppressOutput: true`를 더해도 그 줄들이 남습니다. `{"continue": false, "suppressOutput": true}`는 `● Operation stopped by hook` 한 줄로 더 짧지만 `user` 기록이 두 줄 남아서 쓰지 않았습니다.
   - **그래서 Contract 1의 "화면 출력이 모두 없습니다"는 이 방법으로 만족하지 못합니다.** 없어지는 것은 prompt 입력·모델 turn·응답이고, 화면에는 30분마다 두 줄(알림 한 줄 + 원문 한 줄)이 남습니다. 화면을 완전히 비우려면 cron이 넣는 prompt 자체를 없애야 하는데, 그러면 등록이 사람의 기억에 기대게 되어(Contract 3, SESSION-006) 맞지 않습니다. **이 차이는 Leader가 수용 여부를 판정해 주십시오.** 수용하지 않으면 다른 방법이 없다는 것이 이 조사의 결론이라 CR 범위를 다시 정해야 합니다.
3. 그 밖의 방법: (a) cron을 할 일이 있을 때만 등록하고 없으면 지우기 — 다시 등록하는 주체가 필요해서 Contract 3 위반. (b) `CronCreate`의 `durable`은 효과가 없음(도구 설명). (c) 중앙 감시 process·system crontab — SESSION-006의 사용자 결정에 어긋남. (d) hook이 prompt를 바꾸는 방법은 없음(`additionalContext`만 더함). 그래서 hook으로 막는 방법을 골랐습니다.
4. **hook이 시간 제한(settings `timeout`)을 넘기면 prompt가 통과합니다.** record 파일을 FIFO로 바꿔 hook을 멈추게 한 시험에서 cron fire 10초 뒤(`timeout` 10)에 모델 호출이 일어났고 응답했습니다.

### 구현
- `tools/agent-session/agent_session/self_check_gate.py`(새 파일): Leader run의 `UserPromptSubmit` hook. 첫 줄이 `[자기 점검]`으로 시작하고 `Leader 자기 점검`을 담은 prompt만 판정하고 나머지(사용자 입력·동료 메시지·Worker 점검)는 출력 없이 통과합니다.
- 할 일 판정은 project-item api의 `CR.listed`에서 `CR.terminal`을 뺀 상태(open·todo·in-progress)와 `DECIDE.listed`(open·answered)의 `item_files`입니다(상태 목록을 다시 적지 않음. test가 이 목록을 고정). `jobs.item_api()`로 project-item을 지연 import하므로 다른 prompt는 interpreter 시동과 JSON 읽기만 합니다(`test_the_gate_stays_light_to_start`).
- 판정할 수 없으면(registry·item root 미설정·읽기 실패·입력 이상·모든 예외) 통과합니다(fail-open). hook 시간 제한은 10초이고 넘기면 위 4처럼 통과합니다.
- **7일 갱신(Contract 3):** 모든 점검을 막으면 cron이 등록 7일 뒤 만료하고 점검 prompt의 마지막 항목(재등록)도 실행되지 않아 cron이 사라지고, 할 일이 생겨도 다시 등록하는 주체가 없습니다. 그래서 `HEARTBEAT`(24시간)마다 할 일이 없어도 한 번 통과시킵니다. 통과 시각은 `<base>/agent/runs/<run_id>/self-check-gate.json`(`passed_at`)에 쓰고, run의 첫 점검과 기록을 못 읽거나 못 쓰는 경우는 통과합니다. 하루 한 번 통과하면 등록 뒤 6~7일 사이에 점검이 실행되어 마지막 항목이 갱신합니다. 이 하루 한 번의 점검은 "할 일이 없으면 아무것도 넣지 않음"(Contract 1)의 예외이고 Contract 3을 위한 최소 비용입니다.
- `providers/claude.py`: `registration_hooks`가 `context["target"] == "leader"`일 때만 `UserPromptSubmit` hook을 더합니다. Worker run·target 없는 context는 이전과 같고 기존 lifecycle hook 검사(`_configuration`)는 바뀌지 않습니다.
- 문서: `docs/project-team/spec.md`(watch의 "Leader 자기 점검의 gate", settings 설명 두 곳), `docs/project-team/README.md`(모듈 표), `skills/project-team/references/self-check.md`(새 절. cron 식·prompt 원본은 그대로 이 문서). prompt 첫 줄을 바꾸면 `test_self_check_gate.py`가 실패하도록 test가 self-check.md의 Leader prompt를 읽습니다.
- 알아 둘 점: 막은 점검도 시각 있는 `system` 기록을 남겨 Leader의 가장 새 기록 시각이 갱신됩니다. `watch`는 in-progress CR이 있을 때만 Leader를 판정하고 그때는 gate가 통과시키므로 충돌하지 않습니다(spec에 적음). 이미 떠 있는 Leader run은 settings를 시작 때 쓰므로 restart 뒤부터 적용됩니다.

### 검증
- `python -m pytest -q -n 8 tools/agent-session/tests` → **872 passed** (682초, `test_remote.py`·`test_watch.py`·`test_providers.py`·`test_startup_imports.py` 포함). 새 `test_self_check_gate.py` 26개: 할 일 없음이면 막음, open·todo·in-progress CR과 open·answered 결정 각각이 있으면 통과, done·deferred CR과 done 결정·README는 할 일이 아님, 판정 실패(registry 읽기 실패, 한 root 미설정, 입력 이상, 항목 읽기 OSError)이면 통과, Worker 점검·사용자 입력·다른 event 영향 없음, 24시간 heartbeat(기록 없음·오래됨·미래·손상·쓰기 불가), Leader run만 hook을 설치하고 생성된 command를 `python -S -c`로 실행해 막힘·통과 확인.
- `python -m pytest -q tools/test_distribution_boundary.py` → 9 passed. 바꾼 세 문서(spec.md, README.md, self-check.md)의 상대 link 검사 → 끊어진 link 없음.
- **실제 Claude Code 2.1.322(Haiku, `--settings`에 `registration_hooks`가 만든 Leader hook만 넣음, 가짜 project의 registry·item root):** (1) 할 일 없음 → 15:52 fire가 막힘(대화 기록에 모델 호출·user 기록 없음, 화면에 알림 한 줄) (2) `cr/todo/X-001-t.md` 하나 추가 → 15:53 fire가 통과해 모델이 `ok`로 응답(`api-request` 있음) (3) 파일을 지우자 다음 fire가 다시 막힘 (4) record를 FIFO로 바꿔 hook을 멈춤 → 10초 뒤 통과. 시험 뒤 시험용 tmux server를 내렸고 남은 process는 없습니다.
- 실행하지 않은 것: `install/tests`와 다섯 명령 전체(바꾼 경로 `tools/agent-session/**`의 행이 `agent_session/api.py`·`state.py`·tmux option을 바꾸지 않아 요구하지 않음).
