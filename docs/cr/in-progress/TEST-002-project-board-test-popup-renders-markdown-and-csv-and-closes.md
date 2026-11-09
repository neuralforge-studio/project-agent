# TEST-002: project-board test_popup_renders_markdown_and_csv_and_closes_editor_after_acceptance가 간헐적으로 NoMatches '#answer'로 실패합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3
- Base: 9458aba01535c1a12ee034ce725048aca5448c10 2026-11-09T14:40:54+09:00

## Symptom
이 test가 Base와 수정본 모두에서 실행마다 통과와 실패가 번갈아 나옵니다. 실패는 textual `NoMatches '#answer'`입니다. 매 검증에서 알려진 실패로 따로 확인해야 해서 회귀 판정을 흐립니다.

## Evidence
- `tools/project-board/tests/test_tui.py:914`(test), `:947`(`app.query_one("#answer", TextArea)`)
- agent DIST-004 Result: 단독 3번 실행에서 추출본 통과 1·실패 2, agent seat 통과 2·실패 1
- REPO-001 Result, TMUX-001 Result: 같은 실패, 단독 재실행에서 통과

## Contract
- README의 검증 명령은 실행마다 같은 결과를 내야 합니다. test가 화면 상태를 기다리는 방식이 textual의 비동기 갱신과 맞아야 합니다. 제품의 popup 동작이 원인이면 제품을 고칩니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 여러 CR(agent DIST-004, REPO-001, TMUX-001)의 Result에 같은 간헐 실패가 재현 근거와 함께 남아 있습니다. 근거가 있는 결함 수정이므로 위임 범위입니다. 사용자 지시(2026-11-09 "남은 CR은 전부 등록해서 얼마나 남았는지 알 수 있게 해줘")에 따라 열었습니다.
- 2026-11-09 Leader: 제출 8cc91cfb6d4a19483e551519e8c10b287a5cfe2e를 인수합니다. Leader review: 고정 pause를 화면 상태 대기(wait_until)로 바꾼 test diff를 확인했습니다. 제품 PopupApp._send(tui.py:827-869)에서 await는 832·845행뿐이고 message 갱신(856)과 _sync_answer_controls(869) 사이에는 없으므로, message를 본 시점에 editor 비활성화도 끝나 있어 새 대기 조건에 경합이 없습니다. Result의 부하 재현(수정 전 15/20 실패, 수정 후 0/20)과 project-board suite 114 passed를 근거로 인수합니다.

## Implementation
읽을 문서: [README의 검증](../../../README.md#검증), 해당 도구의 README.

1. 근본 원인을 찾습니다. 실패가 test의 기다리는 방식(고정 시간, 화면 갱신 전 조회) 때문인지, 제품 동작(시간 제한, popup 생성 순서) 때문인지 구분하고 근거를 Result에 적습니다.
2. test가 원인이면 관찰 가능한 동작을 기다리는 방식으로 고칩니다. host 속도에 기대는 시간 단언은 그 시간이 제품 계약일 때만 남기고, 남기면 계약 위치를 적습니다. 제품이 원인이면 제품을 고치고 그 동작의 test를 둡니다.
3. 같은 원인의 다른 test가 있으면 같은 방식으로 고치고 목록을 Result에 적습니다. 원인이 다른 실패는 고치지 않고 Leader에게 보고합니다.

의존: 없음. 다른 CR과 병렬로 진행합니다.

위험 등급: 낮음. test 또는 좁은 제품 경로만 바꿉니다.

## Verification
1. 재현(수정 전 실패): load가 높은 조건(예: 해당 suite를 `-n 8`로 돌리면서 같은 test를 반복, 또는 CPU 부하 process를 함께 실행)에서 그 test를 20번 이상 실행해 실패 횟수를 기록합니다.
2. 수정 뒤 같은 조건, 같은 횟수에서 실패 0번입니다.
3. 영향 회귀: 해당 suite 전체(README의 명령)가 통과합니다.

## Result

- 제출 commit: 8cc91cfb6d4a19483e551519e8c10b287a5cfe2e

### 근본 원인 (확인된 사실)
test의 기다리는 방식입니다. 제품 동작이 아닙니다.
- 실패 test는 `#send` click 뒤 고정 `pilot.pause(0.1)`만 기다리고 `editor.disabled`·message를 단언했습니다. 전송 결과는 `asyncio.to_thread`와 `refresh_decisions`를 거친 task가 갱신하므로, 부하가 높으면 pause가 먼저 끝납니다.
- 부하 조건에서 실제 실패한 단언은 `assert editor.text == "" and editor.disabled`(`editor.disabled`가 False)입니다. 그 직후 `async with`가 끝나 app이 내려간 뒤에도 `_send` task가 계속 돌아 `query_one("#answer")`에서 `NoMatches '#answer'`를 냅니다. CR에 적힌 `NoMatches`는 이 2차 증상입니다. test가 먼저 실패하지 않으면 task가 끝까지 돌아 발생하지 않습니다.
- 제품 `_send`의 순서(수락 → editor 비움 → 목록 갱신 → message → controls 동기화)는 정상이라 제품은 고치지 않았습니다.

### 수정
- `tools/project-board/tests/board_testing.py`: `wait_until(pilot, condition, timeout=10)`를 추가했습니다. 화면 상태가 관찰될 때까지 기다리며, 시간 단언이 아니라 제한 시간 안의 대기입니다.
- `tools/project-board/tests/test_tui.py`: 고정 pause를 관찰 가능한 상태 대기로 바꿨습니다.
  - `test_popup_renders_markdown_and_csv_and_closes_editor_after_acceptance`(대상)
  - 같은 원인의 다른 test: `test_accepted_answer_closes_editor_even_when_notification_is_uncertain`(4 parametrize), `test_unconfirmed_acceptance_response_keeps_the_draft`, `test_percent_encoded_local_csv_link_opens_a_table`, `test_cr_popup_opens_selected_cr_markdown`(두 번째 CR 본문 렌더 대기).
- 원인이 다른 실패는 발견하지 못했습니다. 위 목록 밖의 고정 pause(`SidebarApp` click 뒤 0.1s 등)는 이번 부하에서 실패하지 않아 건드리지 않았습니다.
- 제품·시간 계약 단언은 없습니다(남긴 시간 단언 없음).

### 검증
부하: CPU busy loop 8개를 띄운 채 `python -m pytest -q -x <test>`를 순차 20회(`-n 8` 대신 이 조건. 같은 host의 다른 seat도 부하를 냈습니다).
1. 수정 전(Base 9458aba): 대상 test 20회 중 실패 15, 통과 5.
2. 수정 후: 대상 test 20회 실패 0. 고친 5개 test 군(`-k "accepted_answer_closes or unconfirmed_acceptance or percent_encoded_local_csv or popup_renders_markdown or cr_popup"`)도 같은 조건 20회 실패 0.
3. 영향 회귀: `python -m pytest -q tools/project-board/tests` → 114 passed (제출 commit 기준).

`origin/main`은 Base 9458aba에서 진행하지 않아 merge가 없습니다. 근거 재사용·재실행 판정: 제출 commit 이후 변경이 없어 위 검증이 모두 제출 commit의 것입니다. 제출 commit은 `origin/cr/TEST-002`에 push했습니다.
