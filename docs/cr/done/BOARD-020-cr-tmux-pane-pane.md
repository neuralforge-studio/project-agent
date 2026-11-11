# BOARD-020: CR·결정 창을 tmux 떠 있는 pane으로 열어 옮기기·크기 조절·뒤 pane 사용이 되게 합니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S2
- Base: ed7200addb6bb0f0415a16aac39fd6b67413ccd2 2026-11-11T10:39:41+09:00
- Outcome: fixed

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
- 2026-11-11 Leader: 제출 5572551을 검토했습니다. 구현과 Contract 1~6의 test는 인수 가능합니다. 수정 요청은 셋입니다. 제출 뒤 통합된 BOARD-019(51c5ce6, MouseDragEnd1Border 폭 저장 binding)를 merge하고, Board 창 경계 drag가 sidebar 폭을 바꾸지 않음을 test로 확인하고, merge commit에서 project-board tests와 test_api_boundary를 다시 실행합니다.
- 2026-11-11 Leader: 제출 6dc01401a5846755bc4419b7f4c51e8123481cef를 인수합니다. 검토 6dc0140(앞 검토 5572551 + main 5273052 merge + 7842031 test). 새로 본 것: README 충돌 해결(BOARD-021 CR 창 설명 보존), test_moving_or_resizing_the_board_window_never_changes_the_saved_sidebar_width(창 경계 이동·크기 조절은 폭 불변, sidebar 경계는 BOARD-019 binding이 저장), 기본 binding 불변 test가 통합 파일 없는 server라 충돌 없음. main 대비 남은 변경은 BOARD-020 파일 5개뿐. merge commit에서 project-board tests 199, test_api_boundary·test_distribution_boundary 13 passed. 앞 검토 근거는 재사용합니다.
- 2026-11-11 Leader: in-progress -> done, Outcome fixed. 통합 cc6a897 (origin/main)

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

## Result
- 제출 commit: 557255108e6cd87c7ef5ef96cf3d9a291a1dde67

변경(`edba652` + `origin/main` merge. merge는 CR 파일 위치 이동뿐이라 검증 입력이 같아 재실행하지 않았습니다):
- `tools/project-board/project_board/tmux_control.py`: `_popup`을 `new-pane -W`로 바꿨습니다. 크기·위치는 popup과 같습니다(결정 90%, CR 80%, 가운데). 하위 명령 이름·인자는 그대로입니다. 창은 열 때 자기 pane에 `@project_board_window`=1을 쓰고 pane의 `remain-on-exit`을 끕니다. 관리 window는 `remain-on-exit on`이어서 그대로 두면 닫은 창이 죽은 pane으로 남기 때문입니다. 창이 있으면 `respawn-pane -k`로 내용과 제목만 바꿉니다. 열기는 Board 잠금 안에서 표시를 기다려 동시 클릭도 창 하나만 만듭니다. 실패 기록은 BOARD-011의 `run_quiet` 그대로이고, tmux가 닫은 창의 종료 상태 129만 실패로 기록하지 않습니다.
- `_restore`: 떠 있는 pane이 있으면 저장한 layout의 `select-layout`이 "have N panes but need M"으로 실패해 sidebar를 끌 때 `sidebar_partial`이 됩니다. 저장한 layout에서 떠 있는 pane을 빼고 지금의 떠 있는 pane을 더해 복원합니다. 떠 있는 pane이 활성이면 focus를 뺏지 않습니다.
- 문서: project-board README, `docs/project-board-tui-plan.md`, 설치 계약 5.3절. 새 binding·hook은 없어 3.1절은 바꾸지 않았습니다.
- 계약 2의 이동·크기 조절은 tmux 3.8 기본 root binding(위쪽 경계 `MouseDrag1Border`, Alt `M-MouseDrag1Pane`)이 합니다. 그래서 Board 전용 binding을 더하지 않았고 다른 pane의 mouse는 바뀌지 않습니다(테스트가 `list-keys -T root` 불변을 확인). 위쪽 경계 끌기는 Board 창뿐 아니라 사용자가 만든 다른 떠 있는 pane에도 tmux가 적용합니다.
- 알려진 차이: pane 경계 제목 줄(`pane-border-status`)은 켜지 않았습니다(사용자 window option을 바꾸지 않기 위해). 창 제목은 pane title(`CR · 프로젝트`, `Decision · 프로젝트`)에만 있습니다. 경계의 닫기 button(`Control9`)으로 닫아도 그 pane만 닫힙니다.

검증(저장소 루트, 실제 tmux 3.8 test server):
- `python -m pytest -q tools/project-board/tests` → 184 passed (3분 13초)
- `python -m pytest -q tools/agent-session/tests/test_api_boundary.py tools/test_distribution_boundary.py` → 13 passed
- `integrations/tmux/**`는 바꾸지 않아 그 행은 실행하지 않았습니다.
- 새 test(`tools/project-board/tests/test_tmux_control.py`), 계약마다 하나:
  1. `test_a_cr_or_decision_window_opens_as_a_floating_pane_of_the_clicking_clients_window`: 누른 client의 window에만 뜸, 크기·가운데·실행 인자·env·제목
  2. `test_the_board_window_is_moved_and_resized_with_the_mouse_by_tmux_defaults`: pty로 SGR mouse를 보내 위쪽 경계 끌기=이동, 모서리 끌기=크기, Alt 끌기=이동
  3. `test_while_the_board_window_is_open_the_pane_behind_it_takes_input_and_the_sidebar_stays`: 뒤 pane을 click하면 활성이 되고 창은 위(`pane_z`=0)에 남으며, client가 입력한 글이 뒤 pane에만 들어감. `test_a_click_on_the_sidebar_reaches_the_board_while_its_window_is_open`: 통합 파일의 click binding으로 sidebar click이 client·좌표와 함께 Board socket에 도달하고 focus는 안 옮겨짐
  4. `test_another_item_reuses_the_window_with_its_place_and_size`(같은 pane id·위치·크기·제목 갱신, 실패 기록 없음), `test_two_clicks_at_once_open_one_window`
  5. `test_closing_the_board_window_closes_only_that_pane_even_in_a_window_that_keeps_dead_panes`: `remain-on-exit on` window에서 죽은 pane이 안 남음. sidebar pane·폭·`@agent_session_pane_id` 불변. 창 resize는 폭을 안 바꿈. 창이 있는 window를 `kill-window`해도 폭 불변이고 실패 기록 없음. `test_removing_the_sidebar_restores_the_layout_around_an_open_board_window`(분할 없음·있음)
  6. `test_a_failing_board_window_never_covers_the_work_pane_and_the_client_is_told`(BOARD-011 test를 `new-pane -W`로 바꿈, bare 대조 포함), `test_a_board_window_that_cannot_be_opened_is_reported_to_the_caller`
- 실제 `project-board` TUI로 한 수동 확인(test server, `capture-pane`·`list-panes`): CR 창이 뜨고 목록·본문이 그려짐(이 host에서 시작에 약 10초), 위쪽 경계 끌기로 (9,3)→(13,5) 이동, 다른 항목(`todo`) 열기가 같은 pane·같은 위치·크기를 유지하며 내용만 바꿈, `Escape`로 그 pane만 닫히고 `@project_agent_last_error` 없음.
- 근거 재사용: merge 뒤 재실행 없음(바뀐 것은 CR 파일 이동뿐).

### 수정 제출 (Leader feedback: BOARD-019·BOARD-021 통합 반영)
- 제출 commit: 6dc01401a5846755bc4419b7f4c51e8123481cef

- `origin/main`(BOARD-019 `51c5ce6`, BOARD-021 `8ef27bd` 포함)을 `cr/BOARD-020`에 merge했습니다. 충돌은 `tools/project-board/README.md` 한 곳이었고, 이 CR의 창 설명 뒤에 BOARD-021의 CR 창(네 상태 접힘·project 이동) 설명을 이어 붙여 풀었습니다.
- 두 기능이 만나는 경우: `test_moving_or_resizing_the_board_window_never_changes_the_saved_sidebar_width`(focus가 창·뒤 pane인 두 경우)를 더했습니다. 통합 파일을 읽은 server에서 Board 창(`@project_board_managed` 없음)의 경계를 끌어 옮기고 크기를 바꿔도 `@project_board_width`가 그대로이고, sidebar 자신의 경계를 끌면 BOARD-019 binding이 폭을 저장합니다. 기존 `..._by_tmux_defaults` test는 통합 파일을 읽지 않는 server에서 root binding 불변을 확인하므로 BOARD-019 binding과 충돌하지 않습니다.
- 재실행(merge commit): `python -m pytest -q tools/project-board/tests` → 199 passed, `python -m pytest -q tools/agent-session/tests/test_api_boundary.py tools/test_distribution_boundary.py` → 13 passed. `integrations/tmux/**`는 이 CR이 바꾸지 않아 실행하지 않았습니다.
