# TEAM-002: 할 일이 없으면 Leader 자기 점검이 Leader session에 들어가지 않습니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S3

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
