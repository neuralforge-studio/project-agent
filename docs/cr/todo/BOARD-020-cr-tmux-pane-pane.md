# BOARD-020: CR·결정 창을 tmux 떠 있는 pane으로 열어 옮기기·크기 조절·뒤 pane 사용이 되게 합니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S2

## Symptom
CR·결정 창은 tmux `display-popup`으로 열립니다. popup이 떠 있는 동안에는 다음이 모두 되지 않습니다.
- 창을 옮기거나 크기를 바꿀 수 없습니다.
- 뒤의 sidebar를 scroll하거나 click할 수 없습니다.
- 뒤의 Claude pane에 입력할 수 없습니다.

사용자 요청(2026-11-11):
- "2.1. popup창 drag 가능하게"
- "2.2 popup창 크기 조절 가능하게"
- "2.3. popup창 떠 있는 상태에서 sidebar scroll, side item click 가능하게"
- "2.4. popup창 떠 있는 상태에서 뒤의 claude 쪽에 입력 가능하게. ( Decision / CR 창의 내용을 보면서 claude 대화창에 입력하고 싶은 것임 )"

## Evidence
- `tools/project-board/project_board/tmux_control.py`의 `_popup`은 `display-popup -E -c <client> -w/-h <크기>`를 background job으로 실행합니다. `open_popup`(결정)은 90%, `open_cr_popup`(CR)은 80%입니다.
- tmux popup은 modal입니다. 떠 있는 동안 그 client의 입력을 모두 받습니다.
- 설치 tmux는 3.8(`/primehome/tools/Inhouse/tmux/latest`)이고, integration은 3.8 이상만 지원합니다(`@project_agent_tmux_min`). tmux 3.8 man page에서 확인한 것:
  - `new-pane`이 떠 있는 pane(floating pane)을 만듭니다. `-x/-y`는 크기, `-X/-Y`는 위치, `%`도 됩니다. `-O`가 없으면 modal이 아니어서 다른 pane과 계속 상호작용할 수 있습니다.
  - 기본 root binding: `MouseDrag1Border` → `resize-pane -M`(경계를 끌어 크기 조절), `M-MouseDrag1Pane`·`M-MouseDrag1Border` → `move-pane -M`(Alt를 누른 채 끌어 옮기기).
  - `respawn-pane -k`는 pane의 위치와 크기를 유지한 채 실행 명령만 바꿉니다.

## Contract
1. sidebar에서 CR(O·T·I)이나 결정(D)을 누르면, 누른 client의 현재 window에 떠 있는 pane으로 창이 열립니다. 크기와 처음 위치는 지금 popup과 같습니다(결정 90%, CR 80%, 가운데).
2. 창은 mouse로 끌어 옮길 수 있고, 경계를 끌어 크기를 바꿀 수 있습니다.
   - Alt 없이 끌어 옮기는 방법(예: 제목 줄이나 위쪽 경계 끌기)은 Board 창에만 적용합니다. 다른 pane의 mouse 동작은 바꾸지 않습니다.
3. 창이 떠 있는 동안 sidebar의 scroll과 click, 뒤 pane(Claude)의 입력이 됩니다. 창은 계속 위에 보입니다.
4. 한 window에는 Board 창이 하나만 있습니다. 창이 떠 있을 때 sidebar에서 다른 항목을 누르면, 같은 창이 옮긴 위치와 바꾼 크기를 유지한 채 새 내용을 보여 줍니다.
5. 창의 닫기(버튼, Esc 등 지금 방법)는 그 pane만 닫습니다. 창을 닫거나 창이 있는 window를 닫아도 sidebar 폭, sidebar 동기화, 관리 pane(`@agent_session_pane_id`) 판정이 바뀌지 않습니다.
6. 실패 처리는 지금 popup과 같습니다. 실패는 누른 client에 표시하고 작업 pane에는 쓰지 않습니다(BOARD-011).

## Disposition
- 2026-11-11 Leader: 구현한다. 사용자 요청 2.1~2.4입니다(원문은 Symptom).
- 2026-11-11 Leader 판정: tmux popup은 modal이라 2.3·2.4를 만족할 수 없습니다. 그래서 tmux 3.8의 떠 있는 pane으로 바꿉니다. integration이 이미 3.8 이상을 요구하므로 지원 범위는 바뀌지 않습니다.
- 2026-11-11 Leader: open -> todo. 사용자 요청 2.1~2.4

## Implementation
읽을 문서: tmux 3.8 man page(`/primehome/tools/Inhouse/tmux/latest/share/man/man1/tmux.1`)의 `new-pane`, `move-pane`, `resize-pane`, `respawn-pane`, mouse binding 절. `tools/project-board/project_board/tmux_control.py`(`_popup`, `open_popup`, `open_cr_popup`, `_reconcile`, `route_click`), `integrations/tmux/project-agent-main.conf`, [설치 계약](../../project-team/install-contract.md) 3.1절, [Board TUI 계획](../../project-board-tui-plan.md), `tools/project-board/tests/test_tmux_control.py`, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 시험: test tmux server(`tools/tests/tmux_test_server.py`의 claim·release)에서 확인합니다.
   - 떠 있는 pane이 다른 pane 활성화 뒤에도 위에 보이는지
   - mouse 이동·크기 조절 binding
   - `respawn-pane -k`가 위치와 크기를 유지하는지
   - 떠 있는 pane이 있을 때 Board sync와 폭 저장 hook이 어떻게 동작하는지
2. 구현: `_popup`을 떠 있는 pane 방식으로 바꿉니다. window마다 Board 창 하나를 찾는 표시(예: pane option)를 둡니다.
3. Board 창 전용 mouse binding이 필요하면 조건부 binding으로 넣습니다. 설치 계약 3.1절에 적습니다.
4. Test: Contract 1~6마다 test를 둡니다(tmux test server).

의존: 없음.
- BOARD-018(Rust sidebar)은 클릭을 `project-board` 하위 명령으로 부르므로 이 CR의 바깥 인터페이스(하위 명령 이름·인자)는 바꾸지 않습니다.
- BOARD-019·BOARD-021과 같은 시기에 진행합니다. 제출 전에 `origin/main`을 merge합니다.

위험 등급: 중간. tmux binding과 sync에 닿습니다.

## Verification
1. README 검증 표에서 바꾼 경로의 행 명령 전부를 실행합니다. `tools/project-board/**` 행, `integrations/tmux/**` 행(바꾸면)입니다.
2. 실제 tmux 3.8에서 열기, 옮기기, 크기 조절, 뒤 pane 입력, 다른 항목 클릭(같은 창 재사용), 닫기를 `capture-pane`이나 tmux 상태 조회로 확인하고 Result에 적습니다.
