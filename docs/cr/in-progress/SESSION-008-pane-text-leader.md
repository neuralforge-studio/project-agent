# SESSION-008: 정체 판정을 pane text 비교로 바꾸고, Leader 회신을 기다리다 함께 멈추는 경우를 없앱니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Base: 2a2406201f0cd4a66f7b49ffcdb16888e8374792 2026-11-10T00:02:14+09:00

## Symptom
Worker가 제출하고 Leader의 review를 기다리는데 Leader가 잊으면, 지금 설계에서는 양쪽 모두 멈춥니다. Worker 자기 점검(`skills/project-team/references/self-check.md` Worker 2번)은 "회신을 기다리는 중이면 아무것도 하지 않고 메시지도 보내지 않는다"이고, `agent-session watch`(SESSION-005)도 Leader 회신 대기를 `awaiting_leader`로 제외합니다. 또 `watch`는 자식 process의 CPU 사용으로 '일하는 중'을 판정하므로, 자식 process가 없는 대화의 정체는 그 신호로 보지 못합니다.

사용자 지적(2026-11-10 대화): "child process의 cpu 점유량이 아니고, tmux 특정 session, window, pane(대화형 claude session 실행 중인) 의 text를 비교하는게 맞아. 만약 child process가 없고, leader에 review 요청했는데, 만약 leader가 까먹었다고 했을 때, 이 방식은 그것도 해결이 될거라 생각해."

## Evidence
- `skills/project-team/references/self-check.md` Worker 점검 2번, Leader 점검(review 대기 CR 확인 항목 없음).
- 명세 7절 watch: '쉬고 있음' 4번(`awaiting_leader` 제외), CPU 2% 기준.
- Claude 화면은 turn이 진행되는 동안 경과 시간 표시가 계속 바뀌고, 맨 아래 status 줄(사용량 %, 갱신 시각)은 turn과 무관하게 바뀝니다(2026-11-09 Worker pane capture).

## Contract
- 정체는 원인과 무관하게 "대화 화면이 일정 시간 바뀌지 않음"으로 판정합니다. 정체한 instance는 깨워서 스스로 판단하게 합니다(SESSION-005·006의 원칙).
- 서로를 기다리며 함께 멈추는 상태가 남지 않아야 합니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 사용자가 지적한 시나리오(자식 process 없음, review 요청 뒤 Leader가 잊음)는 지금 설계가 명시적으로 깨우지 않는 경우라 함께 멈춥니다. 사용자 방식(pane text 비교)은 원인과 무관하게 '아무 일도 일어나지 않음'을 보므로 이 경우와 자식 process가 없는 정체를 모두 잡습니다. 앞서 걱정한 '화면이 계속 바뀜'은 turn이 진행 중일 때(실제로 일하는 중)뿐이고, turn과 무관하게 바뀌는 status 줄만 비교에서 빼면 됩니다.

## Implementation
읽을 문서: [동작 명세](../../project-team/spec.md) 7절 watch, `skills/project-team/references/self-check.md`, `tools/agent-session/agent_session/watch.py`, [README 검증 표](../../../README.md#검증).

1. 정체 판정: `watch`가 관리 pane의 화면 text(`capture-pane`)를 읽어, turn과 무관하게 바뀌는 부분(맨 아래 status·footer 줄: 사용량 %, 갱신 시각, 권한 mode 표시 등)을 뺀 나머지의 hash를 시각과 함께 window option에 남깁니다. 같은 hash가 `--minutes`(기본 30분) 이상 이어지면 정체입니다. 자식 process CPU 판정(`working`, 2% 기준)과 `awaiting_leader` 제외는 없앱니다. 빼는 줄의 규칙은 실제 Claude 화면 capture로 정하고 근거를 명세에 적습니다(Codex 화면도 같은 방식으로 정함).
2. 깨우는 메시지: 정체한 Worker에게 한 번 보냅니다. 내용에 "제출해서 Leader 회신을 기다리는 중이면 Leader에게 짧게 다시 알리라"를 포함합니다. 깨운 뒤 화면이 바뀌면 새 상태이고, 다시 정체하면 다시 깨웁니다(같은 정체 상태에 반복 전송하지 않음).
3. Leader 정체: Leader의 화면도 같은 방식으로 판정합니다. Worker가 다시 알리면 그 메시지가 Leader를 깨웁니다. Leader의 자기 점검(session cron)에는 "review 대기 CR(제출 행의 hash가 Disposition에 없는 것)"을 먼저 처리하는 항목을 더합니다.
4. 자기 점검 원본(`self-check.md`): Worker 2번을 "Leader 회신을 30분 넘게 기다렸으면 Leader에게 제출 hash와 함께 짧게 다시 알림(점검마다 한 번)"으로 바꿉니다.
5. 명세 7절 watch, self-check.md, project-team skill을 새 판정에 맞춥니다.

의존: 선행 SESSION-005·006(done). BOARD-002가 통합 대기 중이므로 제출 전에 `origin/main`을 merge합니다.

위험 등급: 중간. 판정 신호를 바꿉니다. 빼는 줄 규칙이 틀리면 정체를 놓치거나 일하는 instance를 깨웁니다.

## Verification
README 검증 표의 `tools/agent-session/**` 행과 문서 행.
1. 실제 Claude 화면 capture(turn 진행 중, 쉬는 중, status 줄만 바뀐 경우)로 빼는 줄 규칙을 test fixture로 만들고, status 줄만 바뀐 화면은 '바뀌지 않음', turn 진행 중 화면은 '바뀜'으로 판정함을 확인합니다.
2. fake provider로: (a) 자식 process 없이 제출하고 Leader 회신을 기다리는 Worker의 화면이 30분 그대로면 깨우고, 메시지에 Leader에게 다시 알리라는 내용이 있음, (b) 깨운 뒤 화면이 바뀌면 같은 상태에 다시 보내지 않음, (c) 일하는 중(화면이 바뀜)이면 보내지 않음.
3. self-check.md의 Worker·Leader prompt가 새 항목을 담음(문서 test).
