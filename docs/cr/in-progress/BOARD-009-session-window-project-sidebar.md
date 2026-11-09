# BOARD-009: 지금 활성 session·window의 project를 sidebar에서 강조합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3
- Base: 9680c181adfe8581eac20844e8c00998be5de8b6 2026-11-10T00:29:30+09:00

## Symptom
사용자 요청: "현재 활성화 중인 session, window가 sidebar에 있는 것이 라면 해당 부분 high light ( ex: project-agent leader window가 활성화 되어 있으면 side bar에서 project-agent 부분이 highlight )"
출처: 사용자 개선 요청 2026-11-09(대화, 11개 항목 중 7번).

## Evidence
- 관리 window는 `@agent_session_project_id`·`@agent_session_role`·`@agent_session_seat` option을 가집니다([명세 3절](../../project-team/spec.md#실행-근거와-잠금)).

## Contract
- 사용자가 보고 있는 window가 관리 window이면 sidebar에서 그 project(와 slot)를 강조합니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 사용자가 동작을 정한 기능 요청이므로 위임 범위입니다. BOARD-002 뒤에 시작합니다. 사용자 지시(2026-11-09 대화): "위와 같이 11개의 개선 요청 사항이 있어."
- 2026-11-10 Leader: 선행 BOARD-002가 61e881e로 통합되었습니다(BOARD-003·004 병합). 그 구조를 따르십시오: Board pane은 본 window에 남고(최대 8개, 최근 본 순서), 보이지 않는 pane은 갱신하지 않으며(`project_board_visibility.sh`의 SIGUSR1), 파일은 바뀐 것만 다시 읽습니다(TUI 계획 2·5절). Board CR 다섯 개가 같은 `tui.py`·`tmux_control.py`를 고칠 수 있으므로 제출 전에 `origin/main`을 merge하십시오.
- 2026-11-10 Leader: 제출 60dc6f8 검토. 동작(지금 보는 관리 window의 project와 slot 강조, 숨은 pane은 읽지 않음, 읽기 실패 시 이전 강조 유지)과 test 157 passed를 확인했습니다. CR Evidence의 option 이름(`@agent_session_role`·`@agent_session_seat`)은 Leader가 잘못 적은 것이며 실제 이름(`@agent_session_project_id`·`@agent_session_target`)을 쓴 것이 맞습니다. 수정 요청 한 가지: option 이름과 `leader|seat-N` 문법을 `tmux_control`에 같은 문자열로 따로 두면 원본이 둘이 되어, agent-session이 바꿀 때 Board가 말없이 깨집니다(SSOT, 도구 경계 규칙: 다른 도구는 `agent_session.api`만 씀). `PANE_ID_OPTION` 선례대로 `agent_session.api`에 이름 또는 window의 (project, slot)을 돌려주는 함수를 공개하고(`__all__`, 명세 5절 표), Board는 그것을 쓰십시오.
- 2026-11-10 Leader: 수정 제출 74e52c7 검토. `Tmux.pane_slot`·`api.pane_slot`(`__all__`, 명세 5절 표)과 Board가 반환값만 쓰는 구조, option 이름·`leader|seat-N` 문법이 `tmux.py` 한 곳에만 있는 것을 확인했습니다. 코드 수정 요청은 없습니다. 검증 보완 요청 두 가지: (1) 제출 뒤 `origin/main`(8d070b2)이 `integrations/tmux/**`(BOARD-010, `test_tmux_control.py`가 읽는 통합 파일)와 `tools/agent-session/**`를 바꿨으므로 merge하고 그 commit에서 다시 검증하십시오. (2) 직전 Leader 지시가 README 검증 표보다 좁았습니다(Leader 잘못). `agent_session/api.py`를 바꾼 행의 명령 전부, 곧 `tools/agent-session/tests` 전체·`tools/project-item/tests`·`tools/project-board/tests`·`install/tests`를 merge commit에서 실행하십시오. `test_control_queue`의 `require_version` 실패는 TEST-007이 다루는 기존 실패로 인정합니다.

## Implementation
읽을 문서: [project-board README](../../../tools/project-board/README.md), [TUI 계획](../../project-board-tui-plan.md), [설치 계약 5.3·5.4절](../../project-team/install-contract.md), [README 검증 표](../../../README.md#검증).

1. sidebar가 보이는 client의 활성 window가 관리 window(`@agent_session_project_id`가 있음)이면 sidebar에서 그 project를 강조하고, 그 slot(Leader 또는 seat 번호)도 구별합니다. 관리 window가 아니면 강조하지 않습니다.
2. client가 여럿이면 그 sidebar를 보는 client의 활성 window를 기준으로 합니다.
3. 창을 바꾸면 강조가 바로 따라옵니다(BOARD-002의 이벤트 경로를 씁니다).
4. 규칙을 [TUI 계획](../../project-board-tui-plan.md)에 먼저 적습니다.

의존: 선행 BOARD-002.

## Verification
1. 격리 tmux에서 관리 window(Leader, seat)와 일반 window를 오가며 강조가 맞게 바뀌는 test.
2. README 검증 표의 `tools/project-board/**` 행.

## Result

- 제출 commit: 74e52c78453653ca16eef4c289ef6ce4e9ca8fc2

구현 (`cr/BOARD-009`, 기능 commit은 merge의 첫 부모, 두 번째 부모는 `origin/main` 3581f1f):
- 규칙을 [TUI 계획](../../project-board-tui-plan.md) 3절 "지금 보는 창 강조"에 먼저 적었고 README에 요약을 더했습니다.
- `tmux_control.active_context`가 Board pane의 window에서 `@agent_session_project_id`·`@agent_session_target`을 읽습니다. `TUI`는 `▶` 표식과 파란 배경으로 project 이름 줄을, 펼친 project에서는 Leader 줄 또는 해당 seat 줄을 강조합니다. 접힌 project는 `▸` 버튼을 칠하고 도움말에 `현재 창: …`을 붙입니다. 접힘 상태(서버 option)는 바꾸지 않습니다.
- 기준 window는 Board pane 자신의 window입니다. pane은 window마다 하나이고 같은 window를 보는 client가 공유하므로 그 sidebar를 보는 client의 활성 window와 항상 같습니다(구현 2항). 읽는 때는 pane 시작, 창이 보이게 되는 SIGUSR1 읽기(BOARD-002 경로), 10초 주기입니다. 2초 파일 읽기에는 tmux 호출을 넣지 않았습니다. 보이지 않는 window는 읽지 않고, 읽기 실패는 이전 강조를 유지합니다.

CR 본문과 다른 점(확인 필요):
- Evidence의 `@agent_session_role`·`@agent_session_seat` option은 코드와 명세에 없습니다. 실제 option은 `@agent_session_project_id`와 `@agent_session_target`(`leader` 또는 `seat-N`, JSON 값)입니다. 후자를 썼고 CR의 Evidence는 고치지 않았습니다.
- (1차 제출 60dc6f8의 "option 이름을 `tmux_control`에 따로 둠"은 Leader 검토로 고쳤습니다. 아래 수정 제출 참고.)
- Leader 줄은 기존 규칙대로 Leader session의 `connected_at`이 있을 때만 있습니다. 그 전에는 Leader slot 줄이 없고 project만 강조됩니다.
- Board pane이 관리 window보다 먼저 만들어지는 경우(`window-created`) 강조는 최대 10초 뒤에 나타납니다.

검증:
- `python -m pytest -q tools/project-board/tests` (README 검증 표의 `tools/project-board/**` 행), 기능 commit에서 157 passed. 새 test: `test_tui.py` 3건(project·slot 강조, 읽기 실패 유지·숨김 중 미읽기, 같은 값 재그리기 없음), `test_tmux_control.py` 2건(격리 tmux에서 Leader·seat·다른 project·잘못된 target·일반 window·비 JSON 값의 `active_context`, Leader·seat·일반 window를 `select-window`로 오가며 보이는 Board pane의 `board_visible`과 실제 `SidebarApp` 강조가 맞게 바뀜), `test_cli.py` 배선 갱신. `git diff --check` 깨끗.
- `origin/main` merge(BOARD-006: `integrations/tmux/**`, 설치 계약, CHANGELOG, CR 문서)는 `tools/project-board`를 바꾸지 않았습니다. 그래서 전체 재실행 대신 merge된 commit에서 새 test 포함 focused 14건(`test_cli.py`·`test_tui.py -k "highlight or sidebar"` 12건, `test_tmux_control.py -k "active_context or highlight_follows"` 2건)만 다시 돌려 통과했고, 나머지 근거는 재사용했습니다. 새 격리 tmux test는 4회 반복해도 통과했습니다.
- 실제 사용 중인 tmux server에는 적용하지 않았습니다.

### 수정 제출 (Leader 검토 피드백: option 이름·`leader|seat-N` 문법의 원본을 agent-session에 둠)

- 제출 commit은 위 `74e52c7`입니다(1차 60dc6f8 위의 commit 하나).
- `agent_session.api.pane_slot(pane, tmux=None)`을 공개했습니다(`__all__`, 명세 5절 표). `Tmux.pane_slot`(`agent_session/tmux.py`)이 window option의 JSON을 한 번의 tmux 호출로 읽고 `(project_id, slot)`을 돌려줍니다. slot은 `leader`·`seat-N`(`caller`와 같은 어휘)이고, target이 slot이 아니면 None, 관리 window가 아니면 전체가 None입니다. option 이름과 `_SEAT_TARGET` 문법은 `tmux.py`에만 있습니다.
- Board는 `tmux_control.active_context`에서 `api.pane_slot`을 불러 반환값만 씁니다. `MANAGED_*` 상수와 `_SLOT` 정규식을 지웠고, TUI는 seat 행을 `slot == f"seat-{index}"`로 맞춥니다(문법을 다시 풀지 않음). 계획 문서·README에서 option 이름을 지우고 소유를 agent-session으로 적었습니다.
- 새 test: `tools/agent-session/tests/test_tmux.py::test_pane_slot_names_the_project_and_slot_of_a_managed_window_only`(실제 `create_window`가 쓴 option으로 seat·Leader·일반 window·slot이 아닌 target·JSON이 아닌 project_id). Board test는 slot 값을 `seat-N`으로 바꿨습니다.

수정 제출의 검증:
- `test_api_boundary.py`·`test_import_cycle.py`·`test_tmux.py`: 67 passed.
- `python -m pytest -q -n 8 tools/agent-session/tests` (README 표의 `tools/agent-session/**` 행): 773 passed, 1 failed. 실패는 `test_control_queue.py::test_external_control_cannot_overtake_a_pending_self_request`(`AttributeError: 'Tmux' object has no attribute 'require_version'`, `lifecycle.py:826`)입니다. 이 변경 전 HEAD(60dc6f8의 기능 commit 상태)와 `origin/main` 3581f1f를 각각 `git archive`로 푼 사본에서도 같은 오류로 실패하므로 이 CR의 변경과 무관한 기존 실패입니다. 고치지 않았습니다. Leader 판단이 필요합니다.
- `python -m pytest -q tools/project-board/tests`: 157 passed. `git diff --check` 깨끗.
- `api.py`에는 이름만 더했고 기존 함수는 바꾸지 않았으므로 `project-item`·`install/tests`는 재실행하지 않았습니다(Leader 지시: `tools/project-board/**`, `test_api_boundary`, `test_import_cycle`, 공개 API 사용 test).
