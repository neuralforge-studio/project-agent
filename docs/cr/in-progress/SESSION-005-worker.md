# SESSION-005: Worker가 일하지 않거나 무한 대기에 빠진 것을 감지하고 깨우는 장치가 없습니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Base: 7e35d2411a827df482e386643624eb7663330833 2026-11-09T19:53:55+09:00

## Symptom
사용자 요청: "worker가 일을 안하는 상황, 잘못된 psgrep 등을 통해 무한 대기중인 상황에 대해 체크할 수 있는 방안 필요. cron으로 tui 창을 30분에 한번씩 비교하고, 변화가 없으면 worker에게 message를 보내는 script를 만들어서 해당 worker session을 깨우게 하는 것은 어떨까?"
출처: 사용자 개선 요청 2026-11-09(대화, 11개 항목 중 11번).

## Evidence
- project-team skill Worker 절은 `pgrep -f`·`pkill -f`가 자기 shell과도 맞아 대기 loop가 끝나지 않는 위험을 적었습니다. 지침만 있고 감지 장치는 없습니다.
- 관리 window의 hook 관찰(`@agent_session_hook_observations`)에 `Stop`(turn 종료) 시각이 남습니다. 대화가 turn 안에 있는지, 쉬고 있는지는 이것과 provider 관찰로 알 수 있습니다([명세 5절](../../project-team/spec.md#claude-실행전송관찰)).
- Claude 화면은 turn이 진행되는 동안 경과 시간 표시가 계속 바뀝니다(2026-11-09 Worker pane capture). 화면 비교만으로는 turn 안에서 멈춘 대기를 '변화 있음'으로 봅니다.

## Contract
- in-progress CR을 맡은 Worker가 제출·보고 없이 쉬고 있거나, turn 안에서 진전 없이 오래 기다리면 Leader가 알 수 있고 Worker가 다시 일하게 되어야 합니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 운영 결함(멈춘 Worker를 아무도 모름)이므로 위임 범위입니다. 사용자가 제안한 "30분마다 TUI 화면 비교"는 Leader가 검토했습니다. 화면은 turn이 진행되는 동안 경과 시간 표시가 계속 바뀌어, turn 안에서 멈춘 대기(잘못된 `pgrep -f` loop 등)를 '변화 있음'으로 봅니다. 그래서 화면 대신 이미 있는 신호(turn 상태, 자식 process, 보고 기록)로 판정합니다. 사용자는 이 판정을 되돌릴 수 있습니다. 사용자 지시(2026-11-09 대화): "위와 같이 11개의 개선 요청 사항이 있어."
- 2026-11-09 Leader: 판정을 고칩니다. 사용자 질문 원문: "11번은 TUI 화면을 비교해서 worker를 깨우고, worker보고 잘 동작 중인지 다시 한번 확인해보라고 보내면, worker가 판단하지 않을까라고 생각했는데 별로인것인가?" 앞선 판단("화면 비교는 turn 안의 멈춘 대기를 못 잡는다")은 과장이었습니다. foreground 명령은 tool 시간 제한(최대 10분)을 넘으면 background로 넘어가고, 그 뒤 Worker는 turn을 끝내고 완료 알림을 기다립니다. 그래서 실제로 막히는 경우는 대부분 'turn이 끝난 채 오래 쉬는 상태'로 모이고, 이것은 사용자가 말한 '화면 변화 없음'과 같습니다. 따라서 사용자 방식대로 감지 시 Worker를 깨워 스스로 확인·판단하게 하는 것을 주 동작으로 합니다. 보완 두 가지: (1) 판정은 화면 대신 같은 뜻의 정확한 신호(마지막 `Stop` hook 뒤 새 입력 없는 시간)로 하고, 제출 뒤 검토 대기는 제외합니다. 화면의 status 줄은 저절로 바뀌는 부분이 있어 그대로 비교하면 틀립니다. (2) 깨우는 메시지에 근거(CR, 마지막 보고 시각, background·자식 process의 명령·경과 시간·CPU 사용)를 담아 Worker가 판단하게 하고, Leader에게도 같은 내용을 알립니다. 강제로 끊지 않습니다. Implementation 2의 '멈춘 대기 → Leader에게만 알림'은 '깨우는 메시지에 그 근거를 담음'으로 바꿉니다.

## Implementation
읽을 문서: [동작 명세](../../project-team/spec.md) 3·7절, [project-team skill](../../../skills/project-team/SKILL.md), [README 검증 표](../../../README.md#검증).

1. 판정 신호(모두 이미 있는 근거): (a) 배정·CR 상태(state, CR이 in-progress), (b) turn 상태(관리 window의 hook 관찰: 마지막 `Stop` 시각과 그 뒤 들어온 메시지), (c) provider process의 자식(command line, 실행 시간, CPU 사용 변화), (d) 마지막 보고(CR Result의 제출 행, Leader에게 보낸 `send` 기록).
2. 두 상태를 구분합니다.
   - 쉬고 있음: CR이 in-progress인데 turn이 끝난 채 일정 시간(기본 30분, 설정 가능) 새 입력·보고가 없음. → Worker에게 "CR 진행 상황을 확인하고 이어서 하라"는 메시지를 `agent-session send`로 한 번 보내고, Leader에게도 알립니다. 같은 상태가 이어지면 다시 보내지 않고 Leader 알림만 남깁니다.
   - 멈춘 대기: turn이 진행 중인데 자식 process가 일정 시간 CPU를 쓰지 않고 같은 명령(예: `pgrep -f`를 담은 loop, `sleep` loop)만 돌거나, 그 사이 hook·출력 진전이 없음. → Worker를 강제로 끊지 않고 Leader에게 seat·명령·경과 시간을 알립니다(끊을지는 Leader가 판단).
3. 실행 방식: `agent-session`에 이 판정을 하는 명령(예: `agent-session watch --once`)을 두고, 주기 실행은 cron 한 줄 또는 Board의 갱신 loop 중 하나로 합니다. 선택과 이유를 명세에 적습니다. 판정은 읽기만 하고, 하는 일은 메시지 전송과 알림뿐입니다.
4. 거짓 경보를 줄이는 조건: 긴 test·build처럼 CPU를 쓰며 진행하는 자식은 멈춤으로 보지 않습니다. Worker가 Leader의 회신을 기다리는 경우(보고 뒤 피드백 대기)는 쉬고 있음에서 뺍니다.
5. 명세와 project-team skill에 동작을 적습니다.

의존: 선행 없음.

위험 등급: 중간. Worker에게 자동으로 메시지를 보냅니다. 같은 상태에 반복 전송하지 않음을 test로 확인합니다.

## Verification
1. fake provider로 세 경우를 만듭니다: 쉬고 있음(turn 끝, 보고 없음), 멈춘 대기(`pgrep -f` 자기 일치 loop), 정상 진행(CPU를 쓰는 긴 자식). 앞의 둘은 각각 메시지·알림, 셋째는 아무것도 하지 않음.
2. 같은 상태에서 두 번 실행해도 Worker 메시지는 한 번.
3. 보고 뒤 피드백을 기다리는 Worker는 쉬고 있음으로 보지 않음.
4. README 검증 표의 `tools/agent-session/**` 행(Board 쪽을 쓰면 그 행).
