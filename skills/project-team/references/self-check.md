# 자기 점검 (Claude Leader·Worker)

Claude Leader와 Worker는 각자 자기 TUI의 session cron(`CronCreate`)으로 30분마다 스스로 점검합니다. session cron은 그 instance가 쉬고 있을 때만 실행되고(turn 중에는 끼어들지 않음) instance가 끝나면 사라집니다. 그래서 점검은 "turn이 끝난 채 멈춘" 상태에만 깨어나고, 수명이 instance와 같습니다. 사람이나 system crontab이 등록·해제하는 단계는 없습니다.

이 문서가 cron 식과 점검 prompt의 원본입니다. 첫 prompt와 resume 메시지는 이 문서를 가리키기만 합니다([동작 명세 7절 watch](../../../docs/project-team/spec.md#watch)).

## 등록

- 등록이 끝난 뒤 첫 행동으로 `CronList`를 보고, 이 점검이 없으면 아래 자기 역할 절의 cron 식과 prompt를 그대로 `CronCreate`에 줍니다(`recurring: true`). 있으면 다시 등록하지 않습니다.
- 대화를 재개(resume)하면 session cron이 사라지므로 같은 방법으로 다시 등록합니다. restart는 새 대화이므로 첫 prompt의 지시로 등록됩니다.
- 반복 작업은 7일 뒤 만료됩니다. 점검이 실행될 때 `CronList`로 자기 점검의 남은 기간을 보고, 만료가 가까우면 같은 식으로 다시 등록합니다(prompt 끝의 마지막 항목).
- 식의 분은 `:00`·`:30`을 피한 값입니다. 실제 실행은 주기의 최대 절반까지 늦을 수 있습니다(도구의 규칙).
- Codex에는 session cron이 없으므로 Codex Leader·Worker는 등록하지 않습니다. Codex Worker가 멈추면 운영자가 수동으로 `agent-session watch --project NAME`을 실행해 점검합니다.

## Worker

cron 식: `13,43 * * * *`

점검 prompt:

```text
[자기 점검] 사용자 입력이 아닙니다. 쉬는 동안 30분마다 실행하는 자기 점검입니다(project-team skill의 references/self-check.md). 아래를 순서대로 봅니다.
1. 내 CR이 아직 in-progress이고 할 일이 남았으면 이어서 합니다.
2. 제출해서 Leader의 회신을 기다리는 중(CR의 `## Result`에 제출 행이 있고 그 뒤 Leader의 feedback이 없음)이면 아무것도 하지 않고 메시지도 보내지 않습니다.
3. background 작업과 자식 process(`ps -o pid,etime,time,args --ppid $PPID`)를 봅니다. 진전 없는 대기(자기 shell과도 맞아 끝나지 않는 `pgrep -f` loop 등)이면 그 process를 PID로 멈추고 올바른 방법으로 다시 합니다.
4. 스스로 풀 수 없게 막혔으면 `agent-session send --job leader`로 이유를 한 번 보고합니다. 이미 보고한 같은 내용은 반복하지 않습니다.
5. `CronList`로 이 자기 점검이 남아 있는지 봅니다. 없거나 등록한 지 6일이 넘었으면 같은 식으로 다시 `CronCreate`합니다.
할 일이 없으면 사용자나 Leader에게 아무것도 보고하지 않고 끝냅니다.
```

## Leader

cron 식: `8,38 * * * *`

점검 prompt:

```text
[자기 점검] 사용자 입력이 아닙니다. 쉬는 동안 30분마다 실행하는 Leader 자기 점검입니다(project-team skill의 references/self-check.md). 아래를 순서대로 봅니다.
1. `agent-session watch --project <이 base의 등록 항목의 project 이름>`을 실행합니다. 결과의 `resting` target은 쉬는 Worker이고(이미 점검 메시지를 받았으며 `evidence`에 근거가 있음) Worker 화면과 CR을 보고 feedback·restart·stop을 판단합니다.
2. `project-item ls`와 `<base>/agent/state.json`으로 반납 대기 seat, 비어 있는 seat와 배정 가능한 todo CR, window나 CLI가 사라진 Worker를 봅니다. 필요한 조치(`agent-session start`·`stop`, 인수한 CR의 종결)를 합니다.
3. 결정 대기 항목 중 답을 받고 반영하지 않은 것이 있으면 이어서 처리합니다.
4. `CronList`로 이 자기 점검이 남아 있는지 봅니다. 없거나 등록한 지 6일이 넘었으면 같은 식으로 다시 `CronCreate`합니다.
조치할 일이 없으면 사용자에게 아무것도 보고하지 않고 끝냅니다.
```
