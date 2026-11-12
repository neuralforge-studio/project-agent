# SESSION-017: 동결 코드로 시작한 Leader run을 self-restart하면 CLI는 끝나지만 finish가 lock_timeout으로 끝나 새 대화가 뜨지 않습니다(agent 요청)

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S2
- Requester: agent, /primehome/swain/Utils/agent/agent.base, 2026-11-12
- Base: 4b47d4a2ebe4b8d4ccb1cb49db89f0330d6853d6 2026-11-12T12:45:47+09:00
- Outcome: fixed

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

## Disposition
- 2026-11-12 Leader 판정: 구현한다. 근거가 있는 결함입니다(pm_vip run `df679e04…`의 `finish-result.json` `lock_timeout`, `control-result.json` `timeout`). 다른 project(agent)가 요청했고, 남은 동결 Leader 네 개의 재시작이 이 답을 기다립니다.
  - 판단 기준은 사용자 지시 "판단의 주요관점은 ** Root cause & SSOT **"입니다. 이번 증상만 피하는 우회가 아니어야 합니다. run을 시작한 코드(동결 경로·옛 release)와 restart controller의 코드가 다를 때 어떤 계약이 깨지는지 원인을 판정하고, 그 계약을 명세에 정합니다.
- 2026-11-12 Leader: open -> todo.
- 2026-11-12 Leader 검토(제출 1252414569a8f4cd6bf6cd4fabb1c802fac9f121): 인수.
  - 원인 판정이 근본 원인을 짚었습니다. 같은 사실(CLI가 끝났는지)에 종료 판정이 둘이었습니다. stop·restart의 `_observe`는 provider 보고만 봤고, `finish_ended`는 process 사실을 봤습니다. 동결 run은 launch 선언(`CLAUDE_DISABLE_ADOPT`)이 없어서, 끝난 CLI의 마지막 Stop 보고에 남은 session cron이 종료를 영원히 막았습니다. `finish-result`의 `lock_timeout`은 그 결과(control 잠금을 controller가 쥠)이고 별개 결함이 아닙니다.
  - 수정은 판정을 `_observe` 하나로 모읍니다(`basis`: provider·process). `_ended_basis`는 그 판정을 그대로 씁니다. `report_background`는 끝난 CLI의 cron을 세지 않습니다. 두 곳 모두 같은 `process.alive(cli_pid, cli_birth)`를 씁니다. 명세 3절·7절과 새 절 "run을 시작한 코드와 제어하는 코드가 다를 때"가 규칙을 적습니다.
  - 재현: 수정 전에는 3건 모두 `timeout`이었고, 수정 후에는 stop 종료, restart 새 대화로 통과합니다. agent-session test는 b47aa3b에서 933 passed, 1 failed였습니다. 실패한 1건은 옛 동작을 고정한 test였고, 그 test만 고친 1252414에서 단독으로 통과합니다. 나머지 근거는 재사용합니다(1252414는 그 test만 바꿈). `test_distribution_boundary.py` 9 passed.
  - 동결 Leader 네 개를 옮기는 방법(Result 5절)을 agent Leader에게 전달합니다. 0.11.0에는 이 수정이 없으므로, 이 수정이 든 release를 설치한 뒤에 restart하라고 안내합니다.
- 2026-11-12 Leader: 제출 1252414569a8f4cd6bf6cd4fabb1c802fac9f121를 인수합니다.
- 2026-11-12 Leader: in-progress -> done, Outcome fixed. 통합 46ab2e6 (origin/main)

## Implementation
읽을 문서:
- [동작 명세](../../project-team/spec.md)의 stop·restart·controller·SessionEnd hook(finish)·잠금 절과 release 고정 정책.
- [SESSION-009 CR](../done/SESSION-009-v0-2-0-claude-run-stop-session-cron-cli-seat.md) (session cron 때문에 stop이 종료를 확인하지 못한 결함, 0.3.0).
- 코드: `tools/agent-session/agent_session/`의 lifecycle·internal(finish)·controller 경로. 비교 대상은 release `0.7.0-213331ec0c5b`(`~/.local/lib/project-agent/releases/`)와 동결 코드 `/primehome/swain/Utils/agent/agent.base/codex/tools/agent-session`(읽기만 함. 그 저장소는 다른 project 소유이므로 고치지 않음).
- 증거: 위 run 디렉터리와 이전 대화 기록(요청서 Evidence).
- 절차: [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 원인 판정: run 디렉터리의 기록 순서(control-request 01:51:50 → finish-result 01:52:07 → control-result 02:01:51)와 두 코드의 잠금·상태 처리를 대조합니다. 누가 어느 잠금을 언제 잡고 기다렸는지를 확인한 사실과 가설로 나눠 Result에 적습니다. session cron(`e27091e1`)이 관여했는지도 판정합니다.
2. 재현: 격리 tmux server와 fake provider로, run을 옛 코드(동결 경로 또는 옛 release)로 시작하고 현재 release로 restart(자기 restart와 operator restart)합니다.
3. 수정: 현재 release로 restart할 때 두 가지를 보장합니다. 새 대화가 뜨거나, 뜨지 못하면 이전 대화를 보존한 채 Leader가 복구 방법을 알 수 있어야 합니다. run과 controller의 코드가 다를 때의 규칙은 명세에 적습니다.
4. 남은 동결 Leader 네 개(falcon2·fc2_cpu·fc2_npu·ipweaver)를 옮기는 방법을 Result의 별도 절에 적습니다(agent Leader에게 전달할 답). 그대로 restart해도 되는지, 먼저 할 일이 있는지(session cron 정리 등), 실패했을 때의 복구를 적습니다.

위험 등급: 중간~높음(restart·finish 경로, 실행 중인 다른 project run에 영향).

## Verification
- README 검증 표에서 바꾼 경로의 행 명령을 모두 제출 commit에서 실행합니다.
  - `tools/agent-session/**`: `python -m pytest -q -n 8 tools/agent-session/tests`.
  - `agent_session/api.py`·state 형식·tmux option 이름을 바꾸면 `python -m pytest -q tools/project-item/tests`, `python -m pytest -q tools/project-board/tests`, `python -m pytest -q -n 8 install/tests`도 실행합니다.
- 문서: 고친 문서의 상대 link 검사, `python -m pytest -q tools/test_distribution_boundary.py`. `docs/project-team/spec.md`를 바꾸면 `python -m pytest -q tools/agent-session/tests/test_remote.py`도 실행합니다.
- 재현 결과: 옛 코드 run을 현재 release로 restart하는 경우의 전후 결과를 Result에 적습니다.
- 실제로 떠 있는 다른 project의 run은 restart하지 않습니다.

## Result
- 제출 commit: 1252414569a8f4cd6bf6cd4fabb1c802fac9f121

### 1. 원인 판정
확인한 사실(pm_vip run `df679e04…` 파일과 코드 대조):
- 이 run의 `launch.sh`에는 `export CLAUDE_DISABLE_ADOPT=1` 줄이 없습니다(동결 코드가 만든 launch). 대화는 background로 옮겨지지 않았습니다(transcript 끝에 `continued-in` 없음).
- `control-result.json`의 `exit_wait`: `cli_alive`·`group_alive`·`tracked_alive` false, `pane_dead` true인데 `background: [{"id":"e27091e1"}]`. 이 항목은 마지막 Stop 보고의 `session_crons`입니다. `report_background`(SESSION-009)는 `launch.sh`에 그 줄이 없으면 cron을 background로 세므로 `Manager._observe`의 `stopped`가 영원히 false였습니다. restart controller는 `stopped`를 기다리며 control 잠금을 쥔 채 600초 뒤 `timeout`으로 끝났습니다.
- `finish-result.json`(01:52:07)의 `lock_timeout`은 별개 결함이 아닙니다. pane이 죽자 server의 `pane-died` hook(`finish_ended`)이 돌았지만 control 잠금을 controller가 쥐고 있어 5초 뒤 "그 명령에 맡기고 끝남"(명세 3절)으로 끝난 것입니다. 명령이 종료를 확인하지 못하면 아무도 마무리하지 않는 것이 문제였습니다.
- release 0.7.0과 현재 `providers/claude.py`는 같습니다(diff 없음). 현재 코드에서도 같은 조건이면 재현합니다.
- 비교: `finish_ended`는 "pane dead + CLI·group·추적 PID 없음 + 옮겨지지 않음"을 종료로 보는데(`_ended_basis`의 process 근거), stop·restart의 `_observe`는 provider 보고만 봤습니다. 같은 사실에 종료 판정이 둘이었고, 보고(옛 run은 launch 선언에 의존)가 process 사실보다 우선한 것이 근본 원인입니다.
- session cron `e27091e1`은 관여했습니다(위 보고 항목). 다만 cron 자체가 아니라 "끝난 CLI의 마지막 보고가 종료를 막은" 것이 원인이라, background task가 보고에 남은 경우도 같습니다(재현 아래).

가설(확인하지 않음): 동결 run의 hook이 쓰는 관찰값 형식과 현재 코드의 호환은 이 run에서 `SessionEnd`가 `observed: true`로 읽힌 것으로만 확인했습니다.

### 2. 재현(전후)
`drop_adopt_record`(launch.sh에서 줄 제거)로 옛 run을 만들고 현재 코드로 제어합니다. fake Claude provider, 격리 tmux.
- 수정 전 → 3개 모두 `timeout`(stop 1: cron, restart 2: cron·background task). `start`는 `leader_exists`(details 없음)로 거절.
- 수정 후 → 3개 모두 통과: stop이 종료하고, restart가 새 conversation으로 교체합니다(state의 leader session이 새 ID).
자기 restart controller 경로(`run_controller`)는 같은 `Manager.control` 대기 loop를 쓰며, 기존 `self_control` test는 fake Codex provider만 씁니다. Claude 자기 restart의 end-to-end test는 추가하지 않았습니다(같은 함수를 operator restart test가 지나감).

### 3. 수정
- `providers/claude.py` `report_background`: CLI process가 이미 끝났으면(`_cli_ended`) session cron을 세지 않습니다. 옮겨졌다면 `continued-in`이며 호출자(`_observe`)가 그것을 먼저 읽습니다.
- `lifecycle.py` `_observe`: Claude run은 pane dead + CLI·group·추적 PID 없음(옮겨지지 않음)이면 provider 보고에 남은 작업이 있어도 `stopped`(`basis: process`). `_ended_basis`는 그 `basis`를 그대로 씁니다(종료 판정을 한 곳에: stop·restart·start·`finish_ended`).
- 명세: 3절 마무리(`lock_timeout`의 뜻), 7절 session cron·process 규칙, 7절 자기 종료 아래 새 절 "run을 시작한 코드와 제어하는 코드가 다를 때"(판정은 선언이 아니라 사실로, 실패 때 이전 대화·`stopping` 보존, 복구 읽는 법).
- 바뀌지 않는 것: CLI·JSON 필드·파일 형식·exit code. `_observe` 결과에 내부 키 `basis`만 더했습니다(출력되지 않음). 형식 version 변경 없음. CHANGELOG는 Leader가 통합 때 씁니다.
- 동작 변화(의도): CLI·group·추적 PID가 모두 없는 Claude run은 stale한 background task 보고가 있어도 종료입니다(이전엔 stop이 `timeout`). 같은 근거를 `finish_ended`가 이미 썼습니다. 이 변화에 맞춰 `test_claude_stop_that_times_out_after_the_signal…`는 추적 PID를 살려 두는 방식으로 고쳤습니다.
- 복구 가능성: 종료를 확인하지 못하는 경우(CLI·group·추적 PID 중 하나가 살아 있음, 옮겨짐)는 이전과 같이 `timeout`·`conversation_backgrounded`와 `stopping_kept`·`exit_wait`가 `control-result.json`에 남고 state의 이전 대화 연결은 보존됩니다. 살아 있는 것이 없으면 이제 `start`가 새 대화로 진행합니다. `leader_exists`의 details 추가는 범위 밖이라 하지 않았습니다.

### 4. 검증
제출 commit 1252414 기준(마지막 변경은 test 한 개의 재작성):
- `python -m pytest -q -n 8 tools/agent-session/tests`: b47aa3b에서 933 passed, 1 failed(`test_claude_stop_that_times_out_after_the_signal…`가 옛 동작을 고정). 그 test만 고쳐 1252414에서 단독 실행해 통과했습니다. 나머지 933개의 근거는 재사용합니다(1252414가 바꾼 것은 그 test 파일의 그 test뿐).
- 신규 test: `test_lifecycle.py` 3개(stop·restart cron·restart task), `test_providers.py` 1개. 수정 전 실패 확인(위 2절, 수정을 되돌린 상태).
- `python -m pytest -q tools/test_distribution_boundary.py`: 9 passed. 명세에 새 link는 없고 기존 anchor 검사에서 누락 없음. `agent_session/api.py`·state 형식·tmux option 이름은 바꾸지 않아 project-item·project-board·install test는 실행하지 않았습니다. `docs/project-team/spec.md`를 바꿨으므로 `test_remote.py`는 위 agent-session 전체 실행에 포함되어 통과했습니다.
- 이 계정의 실제 run은 restart하지 않았습니다.

### 5. 남은 동결 Leader 네 개(falcon2·fc2_cpu·fc2_npu·ipweaver)를 옮기는 방법 (agent Leader에게 전달할 답)
- 원인과 조건: 동결 run은 `launch.sh`에 `CLAUDE_DISABLE_ADOPT` 줄이 없고 hook도 동결 코드입니다. 그 Leader의 마지막 Stop 보고에 session cron(자기 점검 cron 등)이나 background task가 있으면, 이번 수정 전 release의 restart는 위처럼 종료를 못 확인합니다.
- 먼저 할 일: 이 수정이 든 release를 설치해 `~/.local/lib/project-agent/current`가 그것을 가리키게 한 뒤 restart를 요청하십시오. controller는 요청 때 `agent-session`이 가리키는 release의 코드를 씁니다(pm_vip 사례: `controller.sh`가 release 0.7.0). release를 올리기 전에는 요청하지 마십시오.
- 수정 전 release로 해야 한다면(확인하지 않은 추정): restart 요청 전에 Leader가 session cron을 모두 `CronDelete`하고 background 작업을 끝낸 뒤 한 turn을 끝내 Stop 보고를 비운 다음 요청합니다. 이 경로는 이번에 검증하지 않았습니다.
- 요청 전제는 그대로입니다: `<base>/agent/handoff/leader.md`를 현재 실행 중에 갱신해야 합니다(`handoff_required`). 자기 restart는 `accepted:true, completed:false`를 받고 turn을 끝내면 됩니다.
- 그대로 restart해도 되는 이유: 수정 뒤에는 CLI·group·추적 PID가 사라지고 옮겨지지 않았으면 보고 내용과 무관하게 종료로 판정하고, 새 run은 현재 release의 launch.sh·hook으로 뜹니다(전환 완료).
- 실패했을 때: `agent/runs/<기존 run_id>/control-result.json`의 `error.details`를 봅니다. `exit_wait`의 `cli_alive`·`group_alive`·`tracked_alive`가 모두 false, `pane_dead`가 true이면 같은 release에서 일반 터미널로 `agent-session start --job leader`(새 대화, 이전 대화는 transcript와 state에 보존). 하나라도 true이면 그 process를 확인해 끝낸 뒤 다시 실행합니다. `conversation_backgrounded`는 명세 7절 "Background로 옮겨진 대화의 복구"를 따릅니다. state·tmux option을 직접 편집하지 않습니다.
