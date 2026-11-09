# SESSION-009: v0.2.0 Claude run의 stop이 자기 점검 session cron 때문에 CLI가 끝난 뒤에도 끝나지 않고 seat를 반납하지 못합니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S1
- Requester: agent, /primehome/swain/Utils/agent/agent.base, 2026-11-10


## Symptom
v0.2.0 설치본(`releases/0.2.0-e87364816d43`)에서 시작한 Claude Worker를 `agent-session stop`하면, CLI가 끝나고 pane·process group이 모두 사라진 뒤에도 stop이 종료를 확인하지 못하고 timeout으로 끝납니다. 배정은 남고 window option `@agent_session_stopping`이 true로 유지됩니다. v0.2.0이 모든 Claude Leader·Worker에게 첫 행동으로 등록시키는 자기 점검 session cron이 원인입니다. 그래서 v0.2.0에서 시작한 모든 Claude run에서 같은 일이 납니다.

## Evidence
- 재현(2026-11-10, agent project, seat 0, DIST-007, run `49b245817f7d491fbfd8f34cdaf1c2be`, window `@512`, Claude CLI, session `2dc497d1-a13b-4fe9-a99c-fc20ff3b6c2a`). Worker가 정리 완료를 보고한 뒤 Leader가 `agent-session stop --job DIST-007`를 실행했고, 300초 뒤 다음 결과가 나왔습니다.
  `{"ok": false, "error": {"code": "timeout", "details": {"stopping_restored": false, "stopping_kept": "cli_unconfirmed", "exit_wait": {"exit_requested": true, "observed": true, "provider_status": null, "idle": true, "background": [{"id": "585de34f"}], "cli_alive": false, "pane_dead": true, "group_alive": false, "tracked_alive": false}}}}`
  - `<base>/agent/runs/<run>/finish-result.json`은 `{"finished": false, "reason": "lock_timeout"}`입니다.
  - `state.json` seat 0은 `job_id: DIST-007`로 남았습니다.
- `585de34f`는 Worker가 최초 prompt의 지시(`launch_artifacts.self_check_text`, `skills/project-team/references/self-check.md` Worker 절)에 따라 `CronCreate`로 등록한 자기 점검 cron입니다(`13,43 * * * *`, recurring). Worker transcript `~/.claude/projects/-primehome-swain-Utils-agent-agent-seat0/2dc497d1-….jsonl` 73행에 있습니다. window option `@agent_session_hook_observations`의 `Stop` 관찰에 `"background_tasks": []`, `"session_crons": [{"id": "585de34f", …}]`이 남아 있습니다.
- 원인 경로(v0.2.0 코드)
  - `providers/claude.py` `observe` 466–467행은 `background = stopped["background_tasks"] + stopped["session_crons"]`으로 session cron을 background에 넣고, `terminal`을 `not background`일 때만 참으로 둡니다.
  - `lifecycle.py` 316–319행의 `stopped`도 `not observed.get("background")`를 요구합니다.
  - CLI가 SIGTERM으로 끝나면 Stop hook이 다시 오지 않습니다. 그래서 마지막 `session_crons`가 그대로 남고 `stopped`는 끝내 참이 되지 않습니다.
- 대화가 옮겨진 것은 아닙니다. transcript 끝에 `continued-in`이 없고, `launch.sh`에 `CLAUDE_DISABLE_ADOPT`가 있으며, `claude daemon` process도 없습니다.
- 명세 7절 자기 점검: "session cron은 그 instance가 쉬고 있을 때만 실행되고 instance가 끝나면 사라지므로". 등록 지시만 있고 종료 전 `CronDelete` 지시는 없습니다. 3절 "Claude Worker에 background 작업이 남으면 … 그 작업을 멈추면 같은 stop이 끝납니다"는 background shell에 대한 설명이고, 제품이 등록시킨 cron에 대한 설명은 없습니다.
- 0.1.0 run(자기 점검 없음)의 stop은 같은 날 정상 종료했습니다(agent TOOL-002, `released: true`).

## Contract
1. 제품이 등록시킨 자기 점검 cron만 남은 Claude run은 CLI 종료 근거(pane dead, `cli_pid`·`cli_birth` 일치 process 없음, process group 없음)가 확인되면 stop이 종료로 판정하고 반납합니다. 사용자가 만든 다른 session cron이나 background shell이 남은 경우의 동작은 지금 명세를 따릅니다. 방법(자기 점검 cron 식별, 종료 전 `CronDelete` 지시, CLI가 끝난 뒤 session cron 무시 등)은 project-agent가 정합니다.
2. 이미 이 상태에 빠진 run(위 agent seat 0)은 고친 release가 설치된 뒤 같은 `agent-session stop --job DIST-007`로 반납할 수 있어야 합니다. 상태 파일을 손으로 고치지 않습니다.
3. 회귀 test가 위 관찰 조합(`session_crons`에 자기 점검 cron 하나, `background_tasks` 비어 있음, pane dead, CLI·group 없음)에서 stop이 종료로 끝나는 것을 확인합니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 재현과 원인 경로의 근거가 있는 S1 결함이며, 0.2.0이 들인 자기 점검(SESSION-006)에서 나온 하위 결함입니다. Leader가 확인한 영향 범위는 요청보다 넓습니다.
  - stop·restart(`lifecycle.py`의 같은 대기 loop): CLI가 idle이면 SIGTERM을 보낸 뒤, 끝난 CLI의 마지막 Stop 관찰에 남은 `session_crons` 때문에 `stopped`가 참이 되지 않습니다. 0.2.0으로 시작한 Claude Leader의 restart도 같습니다.
  - shutdown(`suspend.py` `_end_for_shutdown`): `idle and terminal`일 때만 종료를 요청하는데 `terminal`이 session cron을 background로 셉니다. 그래서 `--force` 없이는 0.2.0 Claude run마다 `target_busy`입니다.
  - session cron을 background로 센 이유는 CLI가 session cron을 가진 채 끝나면 대화를 background session으로 넘기기(exit handoff, 명세 3절) 때문이었습니다. 관리 Claude CLI는 `CLAUDE_DISABLE_ADOPT=1`로 그 이전을 막습니다. 그러면 session cron은 instance와 함께 사라집니다(명세 7절). 그 근거가 바뀌었는데 판정이 따라가지 않은 것이 근본 원인입니다.
  - 지금 할 수 있는 회피: stop·restart·shutdown 전에 그 대화가 `CronList`의 자기 점검 cron을 `CronDelete`하면 걸리지 않습니다(project-agent INSTALL-007 Worker가 그렇게 해서 정상 반납). 이미 걸린 agent seat 0은 고친 release로 다시 stop합니다(Contract 2).

## Implementation
읽을 문서: [동작 명세 3절](../../project-team/spec.md)(background로 옮겨진 대화, stop의 종료 판정, 스스로 끝난 run의 마무리), [명세 7절 자기 점검](../../project-team/spec.md), [self-check](../../../skills/project-team/references/self-check.md), [README 검증](../../../README.md#검증), [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. exit handoff가 꺼진 관리 Claude run에서는 session cron을 종료를 막는 background로 세지 않습니다. 그 run이 handoff 방지 환경으로 시작했다는 근거를 실행 기록에서 읽습니다. 근거가 없는 run은 지금 판정을 유지합니다. 관찰 결과에는 session cron을 따로 보고해 진단에 남깁니다.
2. 이 판정을 provider 한 곳(`providers/claude.py`)에 둡니다. stop·restart·shutdown·`finish_ended`가 같은 판정을 쓰게 합니다. background shell(`background_tasks`)의 규칙은 바꾸지 않습니다.
3. 이미 걸린 run을 확인합니다. `stopping`이 남고, pane이 dead이고, CLI·group이 없고, 마지막 Stop 관찰에 session cron만 있는 run은 고친 release의 같은 `stop`이 종료로 판정하고 반납해야 합니다. 상태 파일을 손으로 고치지 않습니다.
4. 명세(3절의 종료 판정, 7절 자기 점검)를 동작에 맞춥니다.

의존: 없음.

위험 등급: 중간(종료 판정 경로).

## Verification
1. 수정 전 재현 test: `session_crons`에 cron 하나, `background_tasks` 비어 있음, pane dead, CLI·group 없음. 이 조합에서 stop이 끝나지 않고, shutdown(force 없음)은 `target_busy`입니다.
2. 수정 뒤: 같은 조합에서 stop·restart가 종료로 끝나고 반납합니다. shutdown은 force 없이 끝납니다. 이미 `stopping`이 남은 run을 다시 stop하면 반납합니다. background shell이 남은 경우의 동작은 그대로입니다.
3. README 검증 표의 `tools/agent-session/**` 행(`tools/agent-session/tests` 전체, `-n 8`). `api.py`·state 형식·tmux option 이름을 바꾸면 그 행의 나머지 명령도 실행합니다. 명세 등 원격 guidance 문서를 고치면 그 행의 test도 실행합니다(표의 docs 행).

