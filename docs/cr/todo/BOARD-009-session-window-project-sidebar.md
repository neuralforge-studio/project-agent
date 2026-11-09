# BOARD-009: 지금 활성 session·window의 project를 sidebar에서 강조합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3

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
