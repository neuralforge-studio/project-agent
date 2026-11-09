# SESSION-008: 정체 판정을 pane text 비교로 바꾸고, Leader 회신을 기다리다 함께 멈추는 경우를 없앱니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Base: 2a2406201f0cd4a66f7b49ffcdb16888e8374792 2026-11-10T00:02:14+09:00
- Outcome: fixed

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
- 2026-11-10 Leader: 사용자 결정 D-20261110-01 A(대화 transcript 기록으로 판정). 사용자 원문: "A가 좋은데 전체를 평가할 필요는 없을 것 같네. 1번 평가 마지막 한줄, 2번 평가 20줄 이렇게 하면 대부분 아닐거라 생각하고, 평가 시간자체도 많이 줄일 수 있을거라 생각해." 평가 방법: transcript는 끝에 덧붙이기만 하므로 마지막 줄이 같으면 그 앞 줄도 같습니다. 그래서 마지막 완전한 기록 한 줄만 읽고(파일 끝 최대 64KB, `providers/claude.py`의 기존 tail 읽기), 그 기록의 시각이 `--minutes`(30분)보다 오래됐으면 정체입니다. 이전 결과를 저장해 비교하지 않습니다. transcript를 찾을 수 없거나(대화 ID가 바뀜 등) 마지막 줄이 쓰는 중이면 그 앞 완전한 줄을 쓰고, 그래도 없으면 정체로 보지 않고 결과에 이유를 남깁니다. Codex는 자기 session 기록 파일의 마지막 기록으로 같은 판정을 합니다. Implementation 1의 pane text hash와 빼는 줄 규칙은 쓰지 않습니다.
- 2026-11-10 Leader: 제출 57e2f91c8bb3c9c492948bd15fb64dc8692ea645를 인수합니다. Leader review: D-20261110-01 A대로 시각이 있는 마지막 완전한 transcript 기록(파일 끝 64KB)으로 정체를 판정하고 CPU 판정·awaiting_leader 제외를 없앰, 깨우는 메시지의 '회신 대기면 Leader에게 다시 알림', Leader 정체(진행 중 CR이 있을 때만), self-check.md Worker 2번·Leader 2번을 확인했습니다. 가정 2건(Leader 자기 호출은 자신을 판정하지 않음, 시각 없는 bookkeeping 줄 건너뜀)은 받아들입니다. Codex 경로는 실제 파일 미확인(명세에 한계 기록). agent-session 781 passed·1 failed(같은 기존 실패, TEST-007).
- 2026-11-10 Leader: in-progress -> done, Outcome fixed. 통합 81b3aef. origin/main 반영 확인. CHANGELOG Unreleased에 더했습니다.

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

## Result
- 제출 commit: 57e2f91c8bb3c9c492948bd15fb64dc8692ea645

사용자 결정 D-20261110-01 A(대화 transcript 기록)에 따라 구현했습니다. pane text hash와 빼는 줄 규칙은 만들었다가(첫 구현 `b1d7fc9`) 결정 뒤 지웠고 최종 코드에 남지 않았습니다.

변경:
1. 정체 판정(`watch.py`): provider의 `last_record(session_id)`가 돌려주는 가장 새 기록 시각이 `--minutes`보다 오래되면 정체입니다. 이전 점검의 결과를 저장해 비교하지 않습니다. 자식 process CPU 판정(`working`·`observing`, 2%)과 `awaiting_leader` 제외, `busy`·`idle`은 없앴습니다. status는 `skipped`·`active`·`resting`·`error`입니다.
2. 기록 읽기: `providers/common.py`의 `last_record_time`(파일 끝 최대 64KB, 시각이 있는 가장 마지막 완전한 JSON 줄). `TRANSCRIPT_TAIL`을 이 모듈로 옮겨 `claude.py`가 import합니다. Claude는 기존 `transcript_files`로 파일을 찾고(`ClaudeProvider.last_record`), Codex는 `$CODEX_HOME/sessions/*/*/*/rollout-*-<thread id>.jsonl`입니다(`CodexProvider.last_record`). 기록을 판정할 수 없으면(`transcript_not_found`·`transcript_unreadable`·`no_record_with_time`) 정체로 보지 않고 target을 `skipped`로, 이유를 `reason`에 남깁니다.
3. 깨우는 메시지: 정체한 Worker에게 한 번 보내고(내용에 "제출해서 Leader 회신을 기다리는 중이면 Leader에게 CR ID와 제출 commit을 짧게 다시 알리라" 포함), Leader에게도 같은 근거로 알립니다. 보낸 시각(`nudged_at`) 뒤에 기록이 더 생기면 새 상태이므로 다시 정체하면 다시 깨우고, 같은 정체에는 반복 전송하지 않습니다(window option `watch`는 `resting`만 남기며 옛 key는 버립니다).
4. Leader 정체: 운영자의 `watch`가 Leader도 같은 방식으로 판정합니다. in-progress CR이 있을 때만 깨우고(없으면 `skipped`, `no_cr_in_progress`), 메시지에 in-progress CR 목록과 review 대기 CR 처리 지시를 담습니다. Leader가 호출한 `watch`는 Leader 자신을 판정하지 않습니다. 이 점은 CR에 없어 제가 정한 가정입니다(잊을 일이 없는 Leader를 30분마다 깨우지 않으려는 것).
5. 문서: `self-check.md` Worker 2번(30분 넘게 기다렸으면 제출 hash와 함께 짧게 다시 알림, 점검마다 한 번)과 Leader 2번(review 대기 CR을 먼저 처리), 명세 7절 watch, project-team SKILL.md, 두 README의 설명을 새 판정에 맞췄습니다.

판정 규칙의 근거: 실제 Claude Code 2.1.319 transcript(이 Worker 자신의 대화 파일)는 줄 434개 가운데 232개에 `timestamp`가 없습니다(`session-owner`·`atis-latch`·`mode`·`permission-mode`·`custom-title`·`last-prompt`·`api-request-blob` 등 bookkeeping 줄이 대화와 무관하게 덧붙음). 그래서 "마지막 한 줄"이 아니라 "시각이 있는 마지막 완전한 줄"을 읽습니다(결정의 '쓰는 중이면 그 앞 줄' 규칙의 확장). 실제 파일에 `ClaudeProvider().last_record`를 실행해 현재 시각과 0.5초 차이의 기록 시각을 읽는 것을 확인했습니다.

검증(제출 commit의 agent-session 코드와 test 기준):
- `python -m pytest -q -n 8 tools/agent-session/tests`: 781 passed, 1 failed. 실패 `test_control_queue.py::test_external_control_cannot_overtake_a_pending_self_request`(`'Tmux' object has no attribute 'require_version'`)는 이 변경과 무관합니다. `origin/main`의 `tools`만 풀어 같은 test를 실행해도 같은 오류로 실패함을 확인했습니다(별도 CR 필요, 아래). 첫 실행에서 실패한 `test_lifecycle.py::test_the_seats_next_cr_opens_a_new_window_after_the_released_ones_pane_was_closed`는 두 번째 전체 실행에서 통과했습니다(TEST-006이 다루는 간헐 실패로 보이며 제가 확인한 것은 통과/실패 관찰뿐).
- `tools/test_distribution_boundary.py`: 9 passed. 고친 문서의 상대 link를 검사해 깨진 것이 없습니다. 원격 guidance 문서(`skills/**`, spec)를 바꿨으므로 `test_remote.py`는 위 전체 실행에 포함되어 통과했습니다.
- 마지막 `origin/main` merge(BOARD-006)는 `tools/agent-session`·`skills`·spec을 바꾸지 않아 다시 실행하지 않았습니다.
- 검증 항목 1(`Verification` 1): CR이 정한 pane capture fixture는 결정으로 쓰지 않게 되어, 대신 transcript 기록 판정 test로 대체했습니다. 오래된 마지막 기록·최근 기록·쓰는 중인 마지막 줄·시각 없는 줄·기록 없음·64KB 꼬리 절단(`test_watch.py` 앞부분), Claude는 실제 모양의 JSONL, Codex는 문서화된 배치의 JSONL.
- 검증 항목 2: fake provider로 (a) 자식 process 없이 제출하고 Leader 회신을 기다리는 Worker가 30분 기록 없음이면 깨우고 메시지에 Leader에게 다시 알리라는 문구가 있음, (b) 깨운 뒤 기록이 생기면 새 상태이고 같은 정체에는 다시 보내지 않음, (c) 기록이 계속 생기면 보내지 않음. Leader 정체와 in-progress CR 없음 test도 추가했습니다.
- 검증 항목 3: `test_self_check_prompts_carry_the_review_wait_items`.

검증하지 않은 것 / 남은 위험:
- Codex 경로: 이 host에 Codex session 파일이 없어 `rollout-*-<thread id>.jsonl`과 줄의 `timestamp`는 실제 파일로 확인하지 못했습니다(명세에 그렇게 적음). 다른 모양이면 Codex는 `transcript_not_found`로 `skipped`가 되어 정체를 놓칠 뿐 잘못 깨우지는 않습니다.
- 실제 Claude·Codex CLI로 `watch`를 끝까지 돌리지는 않았습니다(fixture CLI와 실제 transcript 읽기만).
- watch를 호출한 process의 `CLAUDE_CONFIG_DIR`이 CLI가 쓰는 것과 다르면 transcript를 못 찾아 `skipped`입니다(기존 `continued_into`와 같은 한계).
- 기록 없이 30분 넘게 이어지는 turn(하위 agent가 오래 도는 경우 등)은 정체로 판정해 깨웁니다(명세 한계 절).

Leader 확인 요청: `test_control_queue.py` 실패는 `origin/main`에 이미 있는 결함이라 이 CR에서 고치지 않았습니다.
