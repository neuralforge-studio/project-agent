# SESSION-006: Worker 감시(watch)가 Leader run과 무관한 system crontab에 기대고, 감시 자체가 멈춰도 알 수 없습니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Base: afc5dc25ff13e85251ff5e46ebfd3fb33f0653ca 2026-11-09T21:09:33+09:00
- Outcome: fixed

## Symptom
SESSION-005가 만든 `agent-session watch --all`은 운영자가 system crontab에 한 줄을 넣어야 동작합니다. 설치기는 crontab을 고치지 않으므로(설치 계약 3절: 고치는 기존 파일은 tmux 설정 하나) 사람이 따로 등록·해제해야 하고, 팀이 없을 때도 계속 돌며, Leader·tmux window의 수명과 묶여 있지 않습니다. 또 감시하는 process가 멈추거나 등록이 빠져도 아무도 알 수 없습니다.

사용자 지적(2026-11-09 대화): "agnet 자체적인 cron있는거 아니였어? cron을 매번 등록하고 해제하는 방식으로 운영하려고? 나는 tmux windows가 종료될 때, 자동으로 종료되는 cron을 상상하고 있어. 문제 없다고 생각하는거야?? worker가 멈추는 것에 대해 모니터링 하는 것에 대한 모니터링 방식을 어떻게 하기로 결정한거야?"

## Evidence
- SESSION-005 Result·명세 7절 watch: 실행 방식은 cron(`*/10 * * * * agent-session watch --all`), 운영자가 crontab에 넣음. Leader가 인수 때 이 수명 문제를 검토하지 않았습니다.
- Claude Code의 session cron(CronCreate)은 그 Claude session 안에서만 살고 session이 끝나면 사라지지만, REPL이 쉬고 있을 때만 실행되고(긴 turn 중에는 실행되지 않음), 주기의 최대 50%(최대 30분)까지 늦을 수 있으며, 반복 작업은 7일 뒤 만료됩니다(도구 설명). Codex에는 같은 기능이 없습니다.
- TEST-004의 test tmux server watchdog은 소유 process가 사라지면 스스로 끝나는 수명 묶기를 이미 씁니다(`tools/tests/tmux_test_server.py`).

## Contract
- 감시는 그것이 지키는 팀(Leader run)과 같은 수명을 가져야 합니다. Leader window가 끝나면 감시도 끝나고, Leader가 시작·재개되면 감시도 따라 시작됩니다. 사람이 등록·해제하는 단계가 없어야 합니다.
- 감시가 동작 중인지 보여야 합니다(마지막 실행 시각). 멈추면 드러나야 합니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). SESSION-005 인수 때 실행 방식의 수명 문제를 검토하지 않은 Leader의 누락입니다. 사용자가 원한 동작(window가 끝나면 함께 끝나는 주기 실행)을 결정적으로 만드는 방법으로, Claude session cron 대신 agent-session이 Leader run에 묶인 감시 process를 직접 띄우는 방식을 택합니다. 이유: session cron은 Leader가 긴 turn 중이면 실행되지 않고, 최대 30분 늦고, 7일 뒤 만료되며, Codex에 없고, Leader 모델이 만들어야만 생깁니다. 사용자는 이 판정을 되돌릴 수 있습니다.
- 2026-11-09 Leader: 이전 판정(agent-session이 Leader run에 묶인 감시 process를 띄움)을 철회합니다. 사용자 원문: "아니야 잘못되었어. TUI 자체적인 cron 기능은 없나? 정확하게 instance적으로 돌아가길 바래. WOrker의 cron을 이용해도 되잖아." 새 판정: 감시는 각 Claude instance(Leader와 각 Worker)가 자기 TUI의 session cron(CronCreate)으로 스스로 합니다. session cron은 그 instance가 쉬고 있을 때만 실행되고(turn 중에는 끼어들지 않음) instance가 끝나면 사라지므로, 잡으려는 상태(turn이 끝난 채 멈춤)에만 깨어나고 수명이 instance와 정확히 같습니다. 중앙 감시 process와 system crontab은 두지 않습니다.
- 2026-11-09 Leader: 제출 a4490fcef4ab0596fc7399edf554ef3f4da708d4를 인수합니다. Leader review: self-check.md가 cron 식·점검 prompt의 유일한 원본이고, Claude Leader·Worker 첫 prompt와 모든 resume 메시지가 그것을 가리킴(Codex 제외), watch의 Leader 실행 허용(자기 project 하나, 나머지 거절)과 Leader 호출 시 자기에게 메시지 없이 evidence 반환, system crontab 안내 제거를 확인했습니다. Worker 확인 요청 2건(Leader 호출 watch의 evidence 반환, 반납 대기·빈 seat는 project-item ls·state로)은 맞는 판정입니다. 바꾼 모듈에 닿는 test 325 passed(merge 뒤), 경계 test 9. 실제 CronList 확인은 upgrade 뒤.
- 2026-11-09 Leader: in-progress -> done, Outcome fixed. 통합 189d1e7(Merge cr/SESSION-006, 제출 a4490fc). origin/main 반영 확인. CHANGELOG Unreleased에 더했습니다.

## Implementation
읽을 문서: [동작 명세](../../project-team/spec.md) 4절·7절 watch·resume, [project-team skill](../../../skills/project-team/SKILL.md), `tools/agent-session/agent_session/launch_artifacts.py`의 `prompt_text`, [README 검증 표](../../../README.md#검증).

1. 자기 점검의 원본 한 곳: Worker용·Leader용 점검 prompt와 cron 식을 한 곳(예: `skills/project-team/references/self-check.md`)에 둡니다. 첫 prompt·resume 메시지·skill은 이것을 가리키거나 그대로 싣고, 같은 문장을 여러 곳에서 따로 관리하지 않습니다.
2. 등록: Claude Leader·Worker의 첫 prompt(`prompt_text`)에 "등록이 끝나면 첫 행동으로 CronCreate로 자기 점검을 반복 등록하라"를 넣습니다. 주기는 30분(사용자가 처음 제안한 값), 정각·30분을 피한 분(예: `13,43 * * * *`), `recurring: true`. resume run은 session cron이 사라진 채 다시 열리므로 resume 메시지에도 같은 등록을 넣습니다. restart는 새 대화이므로 첫 prompt로 다시 등록됩니다.
3. Worker 점검 prompt(쉬고 있을 때만 실행됨)가 하는 일:
   - 배정 CR이 아직 in-progress이고 할 일이 남았으면 이어서 합니다.
   - background 작업과 자식 process(`ps -o pid,etime,time,args --ppid $PPID`)를 보고, 진전 없는 대기(자기와도 맞는 `pgrep -f` loop, 끝나지 않는 대기)면 그 process를 멈추고 올바른 방법으로 다시 합니다.
   - 제출하고 Leader 회신을 기다리는 중이면 아무것도 하지 않습니다(메시지를 보내지 않음).
   - 막혀서 스스로 풀 수 없으면 Leader에게 한 번 보고합니다. 같은 내용을 반복 보고하지 않습니다.
   - CronList로 자기 점검이 남아 있는지 보고, 7일 만료가 가까우면 다시 등록합니다.
4. Leader 점검 prompt가 하는 일: `agent-session watch --project <자기 project>`로 팀 상태를 판정해 봅니다(쉬는 Worker, 반납 대기 seat, 빈 seat와 todo CR, 사라진 Worker window). 필요한 조치(배정, 반납, 깨우기)를 합니다. 이를 위해 `watch`를 그 project의 현재 Leader도 실행할 수 있게 바꿉니다(지금은 운영자만). Worker에게 메시지를 보내는 판정은 SESSION-005 그대로입니다.
5. SESSION-005가 적은 system crontab 실행 안내(명세 7절 watch의 "실행 방식: cron", skill·README의 cron 줄)를 없애고 위 방식으로 바꿉니다. `watch`는 Leader 점검과 운영자의 수동 점검에 쓰는 명령으로 남깁니다.
6. Codex에는 session cron이 없습니다. Codex Leader·Worker에는 이 등록을 넣지 않고, 그 한계를 명세에 적습니다(지금 등록된 project는 모두 Claude).

의존: 선행 SESSION-005(done). 병렬 SESSION-003(`lifecycle.py`가 겹칠 수 있으니 제출 전 `origin/main` merge).

위험 등급: 낮음. 첫 prompt·resume 메시지·문서와 `watch`의 호출자 판정만 바꿉니다.

## Verification
README 검증 표의 `tools/agent-session/**` 행과 문서 행.
1. `prompt_text`가 Claude Leader·Worker의 첫 prompt와 resume 메시지에 자기 점검 등록(원본을 가리키거나 그 내용)을 넣고, Codex에는 넣지 않음을 test로 확인합니다.
2. `watch`를 그 project의 현재 Leader가 실행할 수 있고, 다른 project의 Leader·Worker는 여전히 거절됨을 test로 확인합니다.
3. 명세·skill·README에 system crontab 안내가 남지 않음.
4. 이 workstation에서의 실제 동작 확인은 upgrade 뒤 Leader가 새 Worker 하나로 합니다(CronList로 등록 확인). 이 CR의 Result에는 계획만 적습니다.

## Result
- 제출 commit: a4490fcef4ab0596fc7399edf554ef3f4da708d4

변경(`origin/cr/SESSION-006`, 최종 commit은 `origin/main`(daa8c90)을 merge한 상태):
- `skills/project-team/references/self-check.md`(신규): Worker·Leader의 cron 식(`13,43 * * * *`, `8,38 * * * *`, 30분, `recurring`)과 점검 prompt, 등록·재등록·7일 만료 갱신·Codex 한계의 유일한 원본.
- `launch_artifacts.self_check_text`(한 곳): Claude Leader·Worker의 첫 prompt(`prompt_text`)와 모든 resume 메시지(`suspend.resume_text`, resumed 문구 포함)가 이것으로 "등록 뒤 첫 행동으로 self-check.md의 자기 역할 절을 읽고 CronCreate로 반복 등록(CronList에 있으면 생략)"을 지시합니다. prompt에는 cron 식을 복사하지 않고 문서를 가리킵니다. Codex prompt에는 넣지 않습니다. restart는 새 대화이므로 첫 prompt로 등록됩니다.
- `watch` 호출자(`Manager._authorize`, `Watch._authorize`): 운영자는 전과 같고, 그 project의 현재 Leader는 자기 project 하나만(`--project` 또는 등록이 그 하나일 때의 `--all`) 실행할 수 있습니다. Worker는 role_denied, 다른 project의 Leader·등록 밖 agent는 caller_unbound, 여러 project를 고르는 `--all`은 Leader에게 거절합니다. 차단은 아무것도 바꾸기 전에 합니다.
- Leader가 호출한 `watch`는 쉬는 Worker를 깨우는 판정(SESSION-005)은 그대로이지만 Leader에게 메시지를 보내지 않습니다(자기 자신에게 가는 메시지가 됩니다). 대신 `resting` target 결과에 `evidence`를 담고 `notified_at` 기록을 남기지 않습니다. Leader 점검 prompt의 반납 대기·빈 seat·사라진 Worker 확인은 `watch`가 아니라 `project-item ls`·state로 하게 했습니다(`watch`의 판정 범위는 넓히지 않음).
- 명세 7절 watch(실행 방식을 자기 점검으로 교체, 호출자 규칙, `evidence`, 한계), resume 7항, project-team SKILL.md, agent-session README, `remote.py`의 `GUIDANCE_FILES`(SKILL.md가 새 문서를 link하므로 test_remote 요구)를 고쳤습니다. system crontab 줄·안내는 없앴습니다(남은 "crontab" 문구는 "두지 않는다"는 설명뿐).

검증(merge된 최종 commit a4490fc에서 실행, host load 약 230):
- `python -m pytest -q -n 8 tools/agent-session/tests/test_watch.py test_run_modules.py test_remote.py test_config.py test_api_boundary.py test_import_cycle.py test_suspend.py test_lifecycle.py` → 325 passed.
- 검증 1: `test_a_claude_prompt_tells_each_role...`(Claude Leader·Worker prompt에 등록 지시, cron 식 복사 없음, 등록이 CR 지시보다 앞, Codex에 없음), `test_every_resume_message_asks_for_the_session_cron_again`, `test_suspend`의 실제 resume 흐름(Worker·Leader 메시지에 각자 절).
- 검증 2: `test_the_leader_watches_its_own_project_and_gets_the_evidence...`(Leader 실행 성공, Worker 점검 1회, Leader 메시지 없음, `evidence`, `notified_at` 없음), `test_only_this_projects_leader_may_watch_it_and_never_several_projects`(`--all`·다른 project·다른 project의 Leader·Worker·등록 밖 agent 거절).
- 검증 3: 문서 상대 link 검사(spec·SKILL·self-check·README), `tools/test_distribution_boundary.py` 9 passed, `grep crontab`로 안내 없음 확인.
- 검증 4(이 workstation 실제 동작): 하지 않았습니다. upgrade 뒤 Leader가 새 Worker 하나로 CronList를 확인하는 계획입니다.
- 근거 재사용·재실행: 첫 제출 전 `origin/main`(TEST-005) merge로 lifecycle·spec·test_run_modules가 합쳐져 위 묶음을 merge 뒤 commit에서 다시 실행했습니다. README 검증 표의 `tools/agent-session/**` 행 전체(`tests` 전부)는 돌리지 않았고 바꾼 모듈에 직접 닿는 test 파일만 실행했습니다. `tools/project-board`·`install`은 건드리지 않았습니다.
- 이전 계획(감시 process) 변경은 Leader 지시로 모두 버렸고 push하지 않았습니다.
