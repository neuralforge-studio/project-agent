# BOARD-006: sidebar의 빈 곳을 click하면 지금 활성 pane에서 오류가 납니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Base: 183f619e84aa8972de73df498ca348cf0a463c52 2026-11-10T00:12:20+09:00

## Symptom
사용자 보고: "side bar 빈곳을 click 하면 현재 활성화 되어 있는 pane에서 error 발생"
출처: 사용자 개선 요청 2026-11-09(대화, 11개 항목 중 2번).

## Evidence
- root `MouseDown1Pane` binding이 Board pane의 click을 `tmux_project_board.sh click --client … --pane … --x … --y …`로 보냅니다(`project_agent_bind.sh`). 항목이 없는 좌표의 처리와 오류가 나는 pane은 미확인입니다.

## Contract
- Board pane의 click은 Board만 처리하고, 다른 pane에 출력이나 입력을 남기지 않아야 합니다. 항목이 없는 곳의 click은 아무 일도 하지 않습니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 재현 가능한 동작 결함이므로 위임 범위입니다. BOARD-002 뒤에 시작합니다. 사용자 지시(2026-11-09 대화): "위와 같이 11개의 개선 요청 사항이 있어."
- 2026-11-10 Leader: 선행 BOARD-002가 61e881e로 통합되었습니다(BOARD-003·004 병합). 그 구조를 따르십시오: Board pane은 본 window에 남고(최대 8개, 최근 본 순서), 보이지 않는 pane은 갱신하지 않으며(`project_board_visibility.sh`의 SIGUSR1), 파일은 바뀐 것만 다시 읽습니다(TUI 계획 2·5절). Board CR 다섯 개가 같은 `tui.py`·`tmux_control.py`를 고칠 수 있으므로 제출 전에 `origin/main`을 merge하십시오.
- 2026-11-10 Leader: 제출 f66e65a213fb063d28e1fb5c55f53f5e7986e47b를 인수합니다. Leader review: 원인(Board pane click은 활성 pane을 바꾸지 않고, run-shell이 job의 출력과 0이 아닌 종료를 활성 작업 pane에 view-mode로 보임)과 수정(click 명령의 출력·종료 상태를 버림, 항목 click 동작·CLI·JSON 계약 불변, 계약 5.3절 한 줄)을 확인했습니다. 격리 tmux 재현과 수정 전 실패 test, integrations/tmux 94·test_tmux_control 17·install 261·project-board 146 passed, merge 뒤 영향 test 재실행. 범위 밖 관찰(toggle·hook의 run-shell도 같은 경로)은 BOARD-010으로 엽니다.

## Implementation
읽을 문서: [project-board README](../../../tools/project-board/README.md), [TUI 계획](../../project-board-tui-plan.md), [설치 계약 5.3·5.4절](../../project-team/install-contract.md), [README 검증 표](../../../README.md#검증).

1. 재현: sidebar의 항목이 없는 곳(빈 줄, 여백, 경계)을 click해 어느 pane에 어떤 오류가 나는지 기록합니다.
2. 원인 확정: click 좌표가 항목이 아닐 때의 처리 경로(`project_agent_bind.sh`의 binding, `tmux_project_board.sh click`, `tmux_control.py`, `tui.py`)에서 오류가 다른 pane으로 가는 이유를 근거로 적습니다.
3. 고침: 항목이 없는 곳의 click은 아무 일도 하지 않고, 어떤 경우에도 Board 밖 pane에 출력·입력을 남기지 않습니다.

의존: 선행 BOARD-002.

## Verification
1. 수정 전 재현(오류가 다른 pane에 남음)과 수정 뒤 같은 click에서 아무 출력도 없음. 항목 위 click은 지금처럼 동작.
2. README 검증 표의 `tools/project-board/**` 행(바꾸면 `integrations/tmux/**` 행).

## Result

- 제출 commit: f66e65a213fb063d28e1fb5c55f53f5e7986e47b

원인(확정): root `MouseDown1Pane` binding이 Board pane click을 `run-shell -b '…tmux_project_board.sh click …'`으로 실행합니다. Board pane은 click해도 선택되지 않으므로 활성 pane은 사용자의 작업 pane입니다. `run-shell`은 job의 출력과 0이 아닌 종료 상태를 활성 pane에 view-mode로 표시합니다. 항목이 없는 좌표는 TUI가 `no_widget`/`not_clickable`로 답하고 `cli._result`가 stderr 출력과 exit 1을 내므로, 작업 pane에 `'…click --client … ' returned 1`과 메시지가 남았습니다(`click_stale` 등 다른 오류도 같은 경로).

고침: `integrations/tmux/project_agent_bind.sh`의 click 명령 끝에 `>/dev/null 2>&1; true`를 붙여 출력과 종료 상태를 버립니다. 항목 click의 동작과 `click` CLI·JSON·socket 계약은 바꾸지 않았습니다. Board 안의 오류 표시(예: 세션 없음)는 TUI가 그대로 합니다. `docs/project-team/install-contract.md` 5.3절 binding 행에 이 사실을 한 줄 적었습니다.

검증:
1. 재현(수정 전): 격리 tmux server(`-L`, 실제 Board TUI, pty client가 SGR click 전송)에서 sidebar의 빈 곳(예: 5,20)을 click → 활성 작업 pane `%0`이 `pane_mode=view-mode`, `capture-pane -M`에 `'…click --client /dev/pts/53 --pane \%1 --x 4 --y 19 …' returned 1`. 수정 뒤 같은 click → `pane_mode` 비어 있고 `capture-pane -M` 빈 출력. 항목 위 click(`▸`)은 `@project_board_expanded`를 바꾸고, 세션 없음 오류는 Board pane 안에 표시됨(수정 전과 같음).
2. 회귀 test 추가: `integrations/tmux/test_project_agent_conf.py::test_a_click_on_the_board_leaves_no_output_in_the_active_pane` (항상 exit 1과 stderr를 내는 가짜 Board로 click). 수정 전 실패(`'view-mode' == ''`), 수정 뒤 통과.
3. README 검증 표 `integrations/tmux/**` 행(수정 commit c7da6b8에서 실행): `integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py` 94 passed, `tools/project-board/tests/test_tmux_control.py` 17 passed, `install/tests` 261 passed·2 skipped. `tools/project-board/**` 행: `tools/project-board/tests` 146 passed. `git diff --check` 깨끗함.
4. `origin/main`(BOARD-007, `tui.py`·`test_tui.py`) merge 뒤 제출 commit f66e65a: 이 변경의 입력(`integrations/tmux`)을 merge가 바꾸지 않았으므로 `integrations/tmux`+`test_distribution_boundary` 47 passed와 `test_tmux_control.py` 17 passed만 다시 실행. 나머지(`install/tests`, project-board 전체)는 c7da6b8 근거를 재사용합니다.
- 범위 밖 관찰: prefix `B`·status line의 `Board` toggle 등 다른 `run-shell` binding도 실패하면 같은 방식으로 활성 pane에 출력될 수 있습니다. 이 CR에서는 고치지 않았습니다.
