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
- 2026-11-09 Leader: 제출 e23ebb8ab86f02a5c1980b8fc3d529cc945ea65e를 인수합니다. Leader review: 수정 판정대로 쉬는 Worker를 근거와 함께 한 번 깨우고 Leader에게 같은 근거를 알리며 강제로 끊지 않음, 같은 상태 반복 전송 없음, Leader 회신 대기·review 중 제외, CPU를 쓰는 자식은 working(측정 근거 2%)을 확인했습니다. 실제 pgrep -f 자기 일치 loop가 메시지 근거로 전달됨, agent-session 741 passed(기대값 1개 고친 test 재실행), README 표대로 관련 test 37 passed. 새 window option(last_sent·last_received·watch)은 이전 release가 무시하는 추가라 형식 버전 1 유지. 통합은 v0.1.0 tag(확인한 코드 그대로) 뒤에 합니다. 운영 적용에는 upgrade와 crontab 한 줄이 필요합니다.

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

## Result
- 제출 commit: e23ebb8ab86f02a5c1980b8fc3d529cc945ea65e

구현(Leader의 수정 판정 반영: 쉬는 Worker를 근거와 함께 깨워 스스로 판단하게 하고, 별도의 '멈춘 대기' 분기는 두지 않음):
- `agent-session watch (--project NAME | --all) [--minutes 30]`(운영자 전용, 한 번 실행). 쉬고 있음 = CR in-progress, turn 종료(idle 또는 Claude `shell`), `--minutes` 동안 입력 없음(마지막 Stop hook·마지막 받은 메시지·watch가 마지막으로 busy를 본 시각 중 늦은 때), Leader 회신 대기 아님(마지막 send가 Leader에게 갔고 회신이 없음, 또는 `leader.reviewing`), CPU를 쓰는 자식 없음(직전 점검 뒤 core의 2% 미만. 자식이 있는데 직전 점검이 없으면 `observing`으로 한 번 미룸).
- 하는 일은 메시지 전송뿐: Worker에게 점검 메시지 1회(근거: CR, 마지막 turn 종료·입력·보고 시각, background 작업 명령, 자식 process의 명령·실행 시간·CPU 누적·직전 점검 뒤 CPU), Leader에게 같은 근거. 같은 상태에서는 Worker에게 다시 보내지 않고 Leader에게만 `--minutes`마다 재알림. 보고·Leader 메시지를 받으면 새 상태. 신호 전송·state·CR 변경 없음.
- 새 기록: `send`가 받는 window의 `last_received`·보내는 window의 `last_sent`를 남김(기존 send 기록이 없었음). watch의 중복 방지 기록은 window option `watch`. `process.tree`·`process.started` 추가(Linux, 자식의 CPU·명령·시작 시각).
- 실행 방식은 cron(`*/10 * * * * agent-session watch --all`). Board 루프를 고르지 않은 이유는 명세 7절 watch에 적음. 명세(1·3·6·7절)·project-team skill·두 README에 반영.
- 측정 근거: `sleep 1` 간격의 `pgrep -f` loop가 이 workstation에서 5.6% CPU를 써서(`sleep 5`는 약 1%) 기준을 2%로 둠. 잘못 깨워도 메시지 한 통이고 놓치면 계속 멈추므로 낮게 잡음.

검증(제출 commit 기준):
- `python -m pytest -q -n 8 tools/agent-session/tests`: 741 passed, 1 failed(`test_tmux.py::test_a_retired_window_goes_to_the_next_run...`가 window 초기값 목록을 열거하는데 새 option 3개 미반영). test 기대값을 고치고 그 test만 다시 실행해 통과. 새 `tests/test_watch.py` 12개 포함.
- Verification 1: 쉬고 있음(Stop 1시간 전, 보고 없음)은 Worker 1·Leader 1 메시지, 멈춘 대기(실제 bash `while pgrep -f marker; do sleep 30; done`, 자기 일치 loop)는 같은 메시지에 그 명령이 담겨 전달, CPU를 쓰는 실제 자식(`while True: pass`)과 CPU 증가가 있는 fake 자식은 `working`으로 메시지 없음.
- Verification 2: 같은 상태 반복 look·`watch` 명령 두 번 실행에서 Worker 메시지 1회(`test_resting_worker_is_woken_once...`, `test_watch_command_is_the_operators...`). 보고 뒤 새 상태는 다시 1회.
- Verification 3: Worker가 Leader에게 send한 뒤(회신 없음)와 `review` 중인 JOB은 `awaiting_leader`로 메시지 없음. Leader 회신 뒤 다시 쉬면 깨움.
- Verification 4: README 표 `tools/agent-session/**` 행 + 바꾼 `tmux` option 쪽 영향으로 `tools/project-board/tests/test_tmux_control.py`, `tools/project-item/tests/test_doc_contract.py`, `tools/test_distribution_boundary.py` 37 passed. 문서 link 검사 이상 없음. 원격 guidance 문서(spec·skills)를 바꿔 `test_remote.py`는 위 전체 실행에 포함.
- 근거 재사용: origin/main merge(INSTALL-006: install·launcher·docs/install 등)는 agent-session·spec·skill 입력을 바꾸지 않아 agent-session test를 다시 돌리지 않았고, merge 뒤 `tools/test_distribution_boundary.py`만 다시 실행해 통과(9 passed).

Leader 참고:
- `tools/formats.json`의 형식 버전은 올리지 않았습니다(`last_sent`·`last_received`·`watch`는 이전 release가 무시하는 window option 추가로 MINOR 항목). 통합 때 CHANGELOG `Unreleased`에 SESSION-005를 더해 주십시오.
- 운영자가 crontab에 한 줄을 넣어야 동작합니다(명세 7절 watch). 이 CR은 설치하지 않았습니다.
- Claude의 turn 안에서 진전 없는 대기를 직접 감지하지는 않습니다(판정 수정 내용대로 foreground 명령이 background로 넘어가 쉬는 상태로 모인다는 전제). Codex는 Stop hook이 없어 watch가 그 run을 처음 본 시각부터 잽니다.
