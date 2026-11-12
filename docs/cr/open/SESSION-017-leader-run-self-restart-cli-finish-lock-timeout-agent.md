# SESSION-017: 동결 코드로 시작한 Leader run을 self-restart하면 CLI는 끝나지만 finish가 lock_timeout으로 끝나 새 대화가 뜨지 않습니다(agent 요청)

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S2
- Requester: agent, /primehome/swain/Utils/agent/agent.base, 2026-11-12

## Symptom
2026-11-11 01:51(KST)에 pm_vip Leader가 자기 restart(`agent-session restart --job leader`)를 요청했습니다. 이전 CLI는 끝났지만 새 대화가 시작되지 않았습니다. controller는 600초 뒤 `timeout`으로 끝났습니다. window `pm_vip:pm_vip-leader`에는 shell만 남았고, state의 leader session은 이전 값으로 남았습니다(stopping 유지). 사용자가 일반 터미널에서 다시 시작해 복구했습니다(2026-11-11T02:18Z, run `1d1647e5…`).

이전 run은 agent 저장소의 동결 코드(`/primehome/swain/Utils/agent/agent.base/codex/tools/agent-session`)로 시작했습니다(hook·launch 모두). restart controller는 release `0.7.0-213331ec0c5b`였습니다. 지금도 falcon2·fc2_cpu·fc2_npu·ipweaver Leader가 동결 코드로 떠 있습니다. 이 Leader들이 restart하면 같은 일이 생길 수 있어 agent는 재시작 요청을 보류했습니다(agent DIST-006: 동결 경로 삭제 대기).

## Evidence
- run 디렉터리: `/primehome/swain/Project/pm_vip.v3/pm_vip.base/agent/runs/df679e048a1c49208702fada6d082527/`
  - `control-request.json`(01:51:50): `operation: restart`, `job: leader`.
  - `finish-result.json`(01:52:07): `{"finished": false, "reason": "lock_timeout"}`.
  - `control-result.json`(02:01:51): `ok: false`, `error.code: timeout`, `details.stopping_restored: false`, `stopping_kept: cli_unconfirmed`, `exit_wait`: `exit_requested: true`, `observed: true`, `provider_status: null`, `idle: true`, `background: [{"id": "e27091e1"}]`, `cli_alive: false`, `pane_dead: true`, `group_alive: false`, `tracked_alive: false`.
  - `controller.sh`: `releases/0.7.0-213331ec0c5b/tools/agent-session`. `launch.sh`·`settings.json`: 동결 경로.
- 이전 대화 기록 `/primehome/swain/.claude/projects/-primehome-swain-Project-pm-vip-v3-pm-vip-base/50e8745e-4e25-441c-a67d-8eff248bc1dc.jsonl`에 `CronCreate` 13회, `CronDelete` 4회, `e27091e1` 503회가 나옵니다. session cron이 남은 상태였던 것으로 보입니다.
- 비슷한 표지의 이전 결함: project-agent SESSION-009(session cron 때문에 stop이 종료를 확인하지 못하고 `finish lock_timeout`, 0.3.0에서 수정). 이번 건은 restart이고, 이전 run의 hook이 동결 코드라는 점이 다릅니다.
- 가설(확인하지 않음): 이전 run의 SessionEnd hook(동결 코드)이 하는 finish와 release controller가 lock이나 상태 형식에서 맞지 않거나, controller가 종료를 기다리는 동안 finish가 lock을 얻지 못했습니다.

## Contract
- 요청: 원인을 판정하고, 동결 코드 run·옛 release run을 현재 release로 restart(자기 restart와 operator restart)할 때 새 대화가 뜨거나, 뜨지 못하면 이전 대화를 보존한 채 Leader가 복구 방법을 알 수 있게 합니다.
- 남은 동결 Leader 네 개를 안전하게 옮기는 방법(그대로 restart해도 되는지, 먼저 할 일이 있는지)을 agent Leader에게 알려 주십시오. agent는 그 답을 받은 뒤 네 Leader에게 재시작을 요청합니다.
- 형식·version은 담당 project가 정합니다.
