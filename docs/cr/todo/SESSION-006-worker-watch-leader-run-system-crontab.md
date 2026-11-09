# SESSION-006: Worker 감시(watch)가 Leader run과 무관한 system crontab에 기대고, 감시 자체가 멈춰도 알 수 없습니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2

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

## Implementation
읽을 문서: [동작 명세](../../project-team/spec.md) 3절(실행 근거와 잠금)·4절 Leader·7절 watch·shutdown·resume, `tools/agent-session/agent_session/watch.py`, `tools/tests/tmux_test_server.py`(수명 묶기 선례), [README 검증 표](../../../README.md#검증).

1. Leader run이 감시를 소유합니다. Leader의 게시가 끝나면(SESSION-001의 등록 게시, 또는 start의 결과) agent-session이 감시 process 하나를 띄웁니다. 감시는 그 project에 대해 정해진 주기(기본 10분, 등록 파일 또는 option으로 바꿀 수 있음)로 `watch` 판정을 실행합니다.
2. 수명: 감시는 매 주기마다 자기 Leader run이 아직 slot의 현재 run이고 살아 있는지 확인하고, 아니면 스스로 끝납니다(Leader stop·restart·window 종료·tmux server 종료). restart·resume로 새 Leader run이 게시되면 새 감시가 시작되고 옛 감시는 위 확인으로 끝납니다. 한 project에 감시는 하나뿐입니다(잠금 또는 window option의 pid·birth로 중복 방지).
3. 감시의 감시: 감시는 실행할 때마다 Leader window option에 마지막 실행 시각과 결과 요약을 남깁니다. Board sidebar가 project 줄에 그 경과 시간을 보이고, 주기의 2배를 넘으면 경고로 표시합니다. Leader 명령(`start`·`send`·`review` 등 Leader가 부르는 agent-session 명령)이 감시가 없거나 멈춘 것을 보면 다시 띄웁니다.
4. system crontab 방식(`watch --all`의 cron 안내)은 명세·skill·README에서 없애고, `watch` 명령은 수동 점검용으로 남깁니다.
5. 명세 7절 watch와 project-team skill에 위 수명·표시를 적습니다.

의존: 선행 SESSION-005(done). 병렬 SESSION-003(같은 `lifecycle.py`를 고칠 수 있으므로 제출 전 `origin/main` merge).

위험 등급: 중간. Leader 시작 경로에 process를 하나 더합니다. 감시가 남거나 겹치지 않음을 test로 확인합니다.

## Verification
README 검증 표의 `tools/agent-session/**` 행(Board 표시를 바꾸므로 `tools/project-board/**` 행도).
1. Leader start 뒤 감시가 하나 뜨고, 주기마다 watch를 실행하며 window option에 마지막 실행 시각이 남습니다.
2. Leader stop, restart, window kill, tmux server kill, SIGKILL로 Leader CLI 종료 각각에서 감시가 주기 안에 스스로 끝나고 남는 process가 없습니다. restart·resume 뒤에는 새 감시 하나만 있습니다.
3. 감시를 강제로 끝내면 Board에 경고가 나오고, 다음 Leader 명령이 감시를 다시 띄웁니다.
4. 감시가 두 번 뜨지 않습니다(동시 start, 재게시).
