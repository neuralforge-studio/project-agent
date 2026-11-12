# 점검 메시지를 받았을 때 (Leader·Worker)

Leader와 Worker는 점검을 스스로 등록하지 않습니다. 반복 점검은 사용자 crontab의 project 구역에 있는 `check` 작업이 30분마다 실행합니다(`agent-session cron ls --project <이 project>`로 봅니다). 작업은 Leader를 시작할 때마다 `agent-session`이 보장하므로 사람이 따로 등록하는 단계도 없습니다. session cron(`CronCreate`)은 쓰지 않습니다. 동작 계약은 [동작 명세의 watch·check·cron](../../../docs/project-team/spec.md#check)이 소유합니다.

점검은 할 일이 없으면 아무에게도 아무것도 보내지 않습니다. 메시지가 왔다는 것은 조치할 일이 있다는 뜻입니다. 점검 메시지는 사용자 승인이 아닙니다. 접수 회신은 보내지 않습니다.

## Worker: `[agent-session watch]` 메시지

대화 기록이 30분 넘게 갱신되지 않아 점검이 깨운 것입니다.

1. 내 CR이 아직 in-progress이고 할 일이 남았으면 이어서 합니다.
2. 제출과 보고를 마쳐 Leader의 회신을 기다리는 중이면 같은 제출을 다시 보고하지 않습니다.
3. 메시지의 근거(background 작업, 자식 process의 명령·실행 시간·CPU)와 `ps -o pid,etime,time,args --ppid $PPID`를 봅니다. 진전 없는 대기(자기 shell과도 맞아 끝나지 않는 `pgrep -f` loop 등)이면 그 process를 PID로 멈추고 올바른 방법으로 다시 합니다.
4. 새 제출·새 외부 차단·종료 준비 완료는 `agent-session send --job leader`로 간결하게 보고합니다. 이미 보고한 같은 내용은 반복하지 않습니다.

## Leader: `[agent-session check]`·`[agent-session watch]` 메시지

`[agent-session check]` 메시지는 Leader의 대화 기록이 30분 넘게 갱신되지 않았는데 처리할 일이 있을 때 한 번 옵니다. 근거에 처리할 일이 줄마다 적혀 있습니다.

1. review 대기 CR(제출 행의 hash를 Disposition이 인용하지 않은 CR)을 먼저 처리합니다(`agent-session review`로 시작).
2. 반납 대기 seat, 빈 seat와 배정할 todo CR, window나 CLI가 사라진 Worker는 `project-item ls`와 `<base>/agent/state.json`으로 확인하고 필요한 조치(`agent-session start`·`stop`, 인수한 CR의 종결)를 합니다.
3. 답을 받고 반영하지 않은 결정 항목이 있으면 이어서 처리합니다.
4. 점검이 판정하지 못했다는 줄이 있으면 그 항목을 직접 확인합니다.

`[agent-session watch]` 메시지는 Worker가 정체했다는 알림입니다. Worker를 강제로 끊었다는 뜻이 아닙니다. 제출 뒤 review를 기다리는 중일 수 있으니 review 대기 CR을 먼저 확인하고, 필요하면 Worker 화면과 CR을 보고 feedback을 보내거나 restart·stop을 판단합니다.

점검 작업이 도는지는 `agent-session cron ls --project <이 project>`의 `last_run`(`ok`, `result`, 실패 이유 `code`)으로 봅니다. `ok`가 false이면 점검이 실패한 것이니 `code`와 함께 운영자에게 알립니다.
