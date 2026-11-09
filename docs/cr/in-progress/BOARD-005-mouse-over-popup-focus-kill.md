# BOARD-005: mouse over로 뜬 popup이 focus를 잃어도 남아 있어 따로 kill해야 합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Base: f3182143ab5b3c436d1c2f975c28fe784e4eadb9 2026-11-10T00:03:56+09:00

## Symptom
사용자 보고: "mouse over 에 따른 pop up 창이 focus를 잃어버렸을 때, 남아있는 경우가 있음. ( kill을 따로 한번 더 해줘야 함 )"
출처: 사용자 개선 요청 2026-11-09(대화, 11개 항목 중 1번).

## Evidence
- popup은 `display-popup`(tmux 3.2+)과 Board의 popup TUI(`project-board popup`·`cr`)로 열립니다(`tools/project-board/project_board/tmux_control.py`, `tui.py`). 어느 경로에서 남는지 미확인입니다.

## Contract
- popup은 사용자가 닫거나 focus를 잃으면 process까지 끝나야 합니다. 남은 popup을 사용자가 손으로 정리할 일이 없어야 합니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 재현 가능한 동작 결함이므로 위임 범위입니다. BOARD-002가 popup 경로를 바꿀 수 있으므로 그 뒤에 시작합니다. 사용자 지시(2026-11-09 대화): "위와 같이 11개의 개선 요청 사항이 있어."
- 2026-11-10 Leader: 선행 BOARD-002가 61e881e로 통합되었습니다(BOARD-003·004 병합). 그 구조를 따르십시오: Board pane은 본 window에 남고(최대 8개, 최근 본 순서), 보이지 않는 pane은 갱신하지 않으며(`project_board_visibility.sh`의 SIGUSR1), 파일은 바뀐 것만 다시 읽습니다(TUI 계획 2·5절). Board CR 다섯 개가 같은 `tui.py`·`tmux_control.py`를 고칠 수 있으므로 제출 전에 `origin/main`을 merge하십시오.
- 2026-11-10 Leader: 제출 b7c44ec 검토. 원인(sidebar hover tooltip이 AppBlur에 지워지지 않음, display-popup은 원인 아님)과 focus 이동 때 지우는 수정, 수정 전 실패 test를 확인했습니다. 수정 요청: 알려진 한계로 둔 '마우스만 다른 pane으로 나감'(focus 그대로, tmux가 이 pane에 event를 주지 않음)은 사용자 보고("mouse over 에 따른 pop up 창이 … 남아있는 경우가 있음")의 흔한 경우이므로 이 CR에서 다룹니다. pane에 mouse event가 오지 않아도 tooltip이 남지 않게, 마지막 mouse motion 뒤 일정 시간(값과 근거를 TUI 계획에 적음)이 지나면 tooltip을 지우십시오.

## Implementation
읽을 문서: [project-board README](../../../tools/project-board/README.md), [TUI 계획](../../project-board-tui-plan.md), [설치 계약 5.3·5.4절](../../project-team/install-contract.md), [README 검증 표](../../../README.md#검증).

1. 재현: mouse over로 popup이 뜨는 조건과, focus를 잃었을 때 popup이 남는 경우를 재현합니다. 남는 것이 tmux popup인지 그 안의 Board process인지, 어떤 경로(다른 pane click, client 전환, window 전환)에서 남는지 구분합니다.
2. 원인 확정: popup의 수명이 무엇에 묶여 있는지(`display-popup -E`, TUI 종료 조건, 신호)와 남는 이유를 근거로 적습니다.
3. 고침: popup이 focus를 잃거나 닫히면 tmux popup과 process가 함께 끝나게 합니다. 사용자가 따로 kill할 일이 없어야 합니다.

의존: 선행 BOARD-002.

## Verification
1. 재현 절차가 수정 전에 popup·process가 남음을 보이고, 수정 뒤에는 남지 않음(격리 tmux server, helper 사용).
2. README 검증 표의 `tools/project-board/**` 행.

## Result

- 제출 commit: b7c44ecc32146fb286b62f48032ba65e63be1966

원인(확인): "mouse over로 뜬 popup"은 Board 사이드바의 hover tooltip(Textual `Tooltip`)입니다. Textual은 tooltip을 그 pane 안의 다음 mouse move에서만 지웁니다. tmux가 focus를 다른 pane·client로 옮기면 그 pane에는 mouse event가 오지 않고 `AppBlur`만 오는데, Textual은 `AppBlur`에서 tooltip을 지우지 않습니다(`textual/screen.py`의 `_clear_tooltip` 호출은 screen suspend와 `app.py:4133`뿐). 그래서 tooltip이 남고 mouse를 되돌려 움직여야 사라집니다.

`display-popup` 경로는 원인이 아닙니다(확인): 격리 tmux server에서 pty client를 붙여 CR popup을 열고 바깥을 클릭하면 popup은 modal이라 그대로 있고, client를 끊으면 popup의 Board process도 함께 끝났습니다(남은 process 없음). popup 안에는 tooltip이 없습니다(`tooltip`은 `SidebarApp`에서만 설정).

수정: `SidebarApp.on_app_blur`가 보이는 tooltip과 delay를 기다리는 tooltip을 모두 지웁니다(`tools/project-board/project_board/tui.py`).

검증:
1. 재현(격리 tmux server `tmux_test_server.claim`, `focus-events on`, pty client attach, 사이드바 pane에 SGR mouse motion을 보내 tooltip 표시 뒤 `select-pane`으로 다른 pane에 focus 이동). 수정 전: focus 이동 뒤에도 tooltip 줄(`  Falcon2    I:0   ▸`)이 남음. 수정 뒤: 사라지고 원래 화면(`D:0`/`O:1 T:0 I:0 ▸`)으로 돌아옴. client 없이 돌리면 tmux가 focus event를 보내지 않아 재현이 성립하지 않으므로 client를 붙여야 합니다.
2. 새 test `test_hover_tooltip_does_not_outlive_pane_focus`(Pilot, `tooltips=True`): 표시된 tooltip이 `AppBlur`에 사라짐, delay 전 blur이면 뒤늦게 뜨지 않음, `AppFocus` 뒤 새 hover는 다시 표시. 수정 전 코드에서 실패(timed out), 수정 뒤 통과.
3. README 검증 표 `tools/project-board/**` 행: `python3 -m pytest -q tools/project-board/tests` 131 passed. `git diff --check` 통과.
4. `origin/main`에 새 commit이 없어 merge 없음(`HEAD`가 `origin/main`을 포함). 근거 재사용 해당 없음.

알려진 한계: pane의 focus는 그대로인 채 mouse만 다른 pane으로 나가면 tmux가 이 pane에 아무 event도 주지 않아 tooltip이 남습니다. 이는 focus를 잃는 경우가 아니어서 이 CR 범위 밖으로 두었습니다. 필요하면 별도 CR(tooltip idle 만료)로 다룹니다.
