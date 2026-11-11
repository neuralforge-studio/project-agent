# BOARD-019: terminal 크기를 바꾼 뒤 sidebar 폭을 mouse로 바꿔도 저장되지 않습니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S2
- Base: ed7200addb6bb0f0415a16aac39fd6b67413ccd2 2026-11-11T10:39:41+09:00
- Outcome: fixed

## Symptom
사용자 보고(2026-11-11): "Side bar width가 저장이 제대로 안됨. terminal 축소 / 확대에 따른 변화 이후에, width를 mouse drag로 변경하더라도 저장이 안되는 듯함."

## Evidence
- 폭 저장은 `integrations/tmux/project-agent-main.conf`의 `after-resize-pane` hook 하나가 합니다. hook 대상 pane의 `@project_board_managed`가 1일 때만 `@project_board_width`에 `#{pane_width}`를 씁니다.
- 기본 mouse binding은 `MouseDrag1Border` → `resize-pane -M`입니다(tmux 3.8 `list-keys -T root`). 경계를 끌 때 hook 대상이 Board pane인지, 옆의 작업 pane인지는 확인하지 않았습니다.
- terminal 크기가 바뀌면 tmux가 layout을 비율대로 다시 나눕니다. 이때 `after-resize-pane`이 불리는지, `@project_agent_sync_needed`(Board pane 폭 ≠ 저장 폭)로 sync가 폭을 되돌리는지는 확인하지 않았습니다.
- 가설(미확인): terminal 크기 변경 뒤의 sync가 폭을 저장값으로 되돌리거나, mouse drag의 hook이 Board pane이 아닌 pane을 대상으로 불려 저장을 건너뜁니다. Implementation 1단계의 재현으로 확인합니다.

## Contract
- 사용자가 mouse로 Board 경계를 끌어 정한 폭은 어떤 순서로 terminal 크기를 바꾼 뒤에도 저장되고, 다른 window의 Board에도 같은 폭으로 쓰입니다.
- terminal 크기 변경 자체는 저장 폭을 바꾸지 않습니다. 사용자가 정한 폭만 저장합니다.
- terminal이 저장 폭보다 좁아 Board를 그 폭으로 둘 수 없을 때의 동작(`_can_fit_width`)은 지금과 같습니다.

## Disposition
- 2026-11-11 Leader: 고친다(Leader 판정). 사용자가 보고한 결함입니다. 원인이 어떤 경로든 사용자가 정한 폭이 저장되게 고칩니다.
- 2026-11-11 Leader: open -> todo. Leader 판정: 사용자 보고 결함
- 2026-11-11 Leader: 제출 54875845535074e29ee2843c62999862153fa89f를 인수합니다. 검토 5487584(구현 80a53e0 + main 6713c30 merge, merge는 CR 이동만). 원인(after-resize-pane이 drag 시작에 한 번만 불림)과 root MouseDragEnd1Border의 Board 한정 저장 binding, 사용자 binding 건너뜀·uninstall 되돌림, 설치 계약 3.1·5.3과 README를 읽었습니다. 수정 전 실패(25≠37)·수정 후 통과, integrations/tmux 행 132·test_tmux_control 25·install/tests 280. tools/project-board/** 행 중 Worker가 빠뜨린 두 명령은 Leader가 제출 commit에서 실행했습니다: project-board tests 175 passed, test_api_boundary 4 passed.
- 2026-11-11 Leader: in-progress -> done, Outcome fixed. 통합 51c5ce6 (origin/main)

## Implementation
읽을 문서: [Board TUI 계획](../../project-board-tui-plan.md)의 폭 관련 절, `integrations/tmux/project-agent-main.conf`, `tools/project-board/project_board/tmux_control.py`(`_reconcile`, `_create`, `_can_fit_width`, sync), [설치 계약](../../project-team/install-contract.md) 3.1절, `tools/project-board/tests/test_tmux_control.py`, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 재현: test tmux server(`tools/tests/tmux_test_server.py`의 claim·release)에서 다음을 재현하고 `@project_board_width`와 각 window의 Board 폭을 기록합니다.
   - (a) 경계 drag(`resize-pane -M`과 같은 대상으로 resize)
   - (b) client 크기를 줄였다 늘린 뒤 drag
   - (c) drag 뒤 다른 window로 이동
   원인을 Result에 적습니다.
2. 수정: Contract를 모든 경로에서 지키게 고칩니다. hook, sync, 폭을 맞추는 코드 중 원인이 있는 곳을 고칩니다.
3. Test: 1단계의 (a)~(c)를 test로 만듭니다. 수정 전 실패, 수정 후 통과를 확인합니다.

의존: 없음. BOARD-018(Rust sidebar)이 같은 시기에 `tmux_control.py`를 바꿉니다. 제출 전에 `origin/main`을 merge합니다.

위험 등급: 낮음.

## Verification
1. README 검증 표에서 바꾼 경로의 행 명령 전부를 실행합니다. `integrations/tmux/**`를 바꾸면 네 번째 명령, `test_tmux_control.py`, `install/tests`도 실행합니다.
2. 수정 전 실패와 수정 후 통과를 Result에 적습니다.

## Result
- 제출 commit: 54875845535074e29ee2843c62999862153fa89f

원인(확정): `after-resize-pane` hook은 `resize-pane -M`(경계 mouse drag)에서 drag를 시작할 때 한 번만 불리고, drag의 각 단계와 끝에서는 불리지 않습니다. 그래서 `@project_board_width`는 drag가 정한 폭이 아니라 drag 초반 폭으로 남고(재현: Board 25 → 35로 끌면 pane은 35, 저장은 28), 다음 sync(`@project_agent_sync_needed`)가 Board를 저장 폭으로 되돌립니다. terminal 크기 변경은 `after-resize-pane`을 부르지 않고(layout만 다시 나눔) 저장 폭을 바꾸지 않음을 확인했습니다. 가설이던 "sync가 크기 변경 뒤 폭을 되돌림"은 원인이 아니고, "hook 대상이 Board가 아님"도 아닙니다(대상은 Board pane이고 시점이 문제).
- 쓰지 않은 대안: `window-layout-changed` hook은 drag 단계마다 불리지만 terminal 크기 변경에도 불려 사용자가 정하지 않은 폭을 저장하므로 Contract 2항에 어긋납니다.

수정: `integrations/tmux/project_agent_bind.sh`가 root `MouseDragEnd1Border`(tmux 기본 binding 없음)에 `if-shell -F '#{==:#{@project_board_managed},1}' { set-option -gF @project_board_width '#{pane_width}' }`을 binding합니다(drag 대상 pane이 Board일 때만 저장). 사용자가 이 키를 다른 명령으로 binding했으면 건너뛰고 `@project_agent_board_skipped`에 `root:MouseDragEnd1Border`를 남깁니다. 따라서 `install/project_agent_install/commands.py`의 `binding_undo`가 이 키의 `unbind-key`를 더하고, `docs/project-team/install-contract.md` 3.1·5.3절과 `tools/project-board/README.md`를 맞췄습니다. `tmux_control.py`는 바꾸지 않았습니다(BOARD-018과 충돌 없음).

검증(제출 commit 기준, `origin/main` 6713c30 merge 뒤 검증 입력 변경 없음 — merge로 들어온 것은 CR 파일 이동뿐):
- 재현·회귀 test: `tools/project-board/tests/test_tmux_control.py::test_a_width_dragged_with_the_mouse_is_saved_after_the_terminal_was_resized`(실제 tmux + pty에 SGR mouse 전달). (a) 경계 drag, (b) client 50열→80열 변경 뒤 저장 폭 불변·다시 drag, (c) 다른 window로 이동 뒤 같은 폭. 수정 전 binding(HEAD의 bind script)으로 실행하면 `assert '25' == '37'`로 실패, 수정 후 통과.
- 새 test: `integrations/tmux/test_project_agent_conf.py`의 drag-end binding(없음→제품 binding, 재읽기 동일, 사용자 binding 건너뜀)과 `install/tests/test_tmux.py` uninstall 되돌림 확인(두 경로 변형 포함).
- README 표 `integrations/tmux/**` 행: `pytest -q integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py` 132 passed; `pytest -q tools/project-board/tests/test_tmux_control.py` 25 passed; `pytest -q -n 8 install/tests` 280 passed, 2 skipped.
- 한계: 실제 terminal 창을 mouse로 끈 수동 확인은 하지 않았고, pty로 보낸 SGR mouse 입력으로 대신했습니다.
