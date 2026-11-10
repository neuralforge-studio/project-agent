# BOARD-017: Board sidebar가 project 단위로 widget을 다시 mount해 열 때와 갱신 때 화면이 깜빡입니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S2

## Symptom
0.7.0 설치 뒤 사용자 보고(2026-11-11, Leader restart 뒤 Board 사용): "화면 깜빡임도 그대로고, project 단위로 그리면서 생기는 문제 같네. 고쳐진게 없어."
BOARD-004의 계약("화면 갱신은 바뀐 부분만 보여야 하고 사용자가 깜빡임을 느끼지 않아야 합니다")이 pane 안의 다시 그리기에서 지켜지지 않습니다.

## Evidence
- 설치본 0.7.0의 `tools/project-board/project_board/tui.py` `SidebarApp._render_projects`(570~608행) 코드에서 확인한 사실:
  - project 하나의 signature가 바뀌면 새 block을 옛 block 앞에 `mount`합니다. 옛 block의 `remove`는 다음 `await`에서 합니다. 바뀐 project마다 이 두 단계를 반복합니다.
  - 목록·순서가 바뀌거나 첫 그리기이면 `remove_children()`을 하고, 다른 `await`에서 `mount(*blocks)`를 합니다.
  - 여는 직후 snapshot, liveness, context(현재 창)가 따로 도착하고, 각각 `_render_projects`를 부릅니다. 펼친 project의 signature에는 liveness와 현재 창이 들어 있어서 여는 동안 같은 block이 여러 번 교체됩니다.
  - 펼친 project의 seat 행(`_seat_text`)과 Leader 행에는 경과 분이 들어 있습니다. 그래서 1분마다 그 project block 전체가 다시 mount됩니다.
- BOARD-004는 pane 재생성(창 이동마다 pane 삭제·생성)이 원인이라는 판정으로 BOARD-002에 병합되어 닫혔습니다. pane 안의 다시 그리기는 그때 확인하지 않았습니다.
- BOARD-013(0.7.0)은 idle CPU를 줄이려고 "전체 다시 그리기"를 "바뀐 project block 교체"로 바꿨습니다. 깜빡임은 다루지 않았습니다.
- 가설(미확인): mount와 remove 사이, `remove_children`과 mount 사이에 Textual이 frame을 그립니다. 그 frame에서는 아래 project 행이 block 높이만큼 밀렸다가 돌아오거나 빈 목록이 잠깐 보입니다. Implementation 1단계의 재현으로 확인합니다.
- CR popup과 결정 popup도 `remove_children` 뒤 `mount`를 쓰지만, 열 때 한 번만 읽고 주기 갱신은 하지 않습니다(732·895행). 이 CR의 범위는 sidebar입니다.

## Contract
- sidebar 갱신은 바뀐 글자·색·강조만 바꿉니다. 갱신 도중의 중간 상태(빈 목록, 같은 project가 두 번 있는 목록, 밀렸다 돌아오는 행)는 화면에 그려지지 않습니다.
- 화면 모양은 지금과 같습니다(색, 행 구성, 강조, tooltip, click 동작, scroll·focus 유지).
- BOARD-013의 규칙(바뀐 것이 없으면 그리지 않음)을 유지합니다.

## Disposition
- 2026-11-11 Leader: 고친다(Leader 판정). 사용자가 보고한 결함이고, 코드에 근거가 있으며, BOARD-004 계약을 지키지 못하고 있습니다. 고치는 방법도 Leader가 정합니다. 중간 frame이 생길 수 있는 경로를 남기지 않는 방법을 고릅니다.
  - 값이 바뀌면(글자, class, tooltip, disabled) 이미 mount한 widget을 제자리에서 갱신합니다. 다시 mount하지 않습니다.
  - 행이 생기거나 없어지는 구조 변경(펼치기·접기, seat·Leader·error 행의 증감, project 추가·삭제·순서 변경, 첫 그리기)은 Textual `App.batch_update()` 하나 안에서 모두 적용합니다. 화면은 적용이 끝난 상태만 그립니다.
  - BOARD-016(Rust 전환 여부 비교)의 결정을 기다리지 않습니다. 지금 Board의 결함이고, 전환을 고르더라도 시간이 걸립니다.
- 2026-11-11 Leader: open -> todo. Leader 판정: 재현 근거가 있는 결함(BOARD-004 계약 미충족)

## Implementation
읽을 문서: [project-board README](../../../tools/project-board/README.md), [Board TUI 계획](../../project-board-tui-plan.md) 3절, `tools/project-board/project_board/tui.py`, `tools/project-board/tests/test_tui.py`·`board_testing.py`, BOARD-013·BOARD-004 CR, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 재현: 수정 전 코드에서 중간 frame을 관찰 가능한 방법으로 확인합니다. 예를 들어 Textual `run_test`에서 갱신마다 실제로 그린 화면을 기록하거나, test tmux server(`tools/tests/tmux_test_server.py`의 claim·release)에서 `tmux capture-pane`을 짧은 간격으로 연속 저장합니다. 대상 경우는 세 가지입니다.
   - (a) 여는 동안: snapshot → liveness → context
   - (b) 펼친 project의 seat 값(경과 분, 상태)이 바뀔 때
   - (c) project 추가나 펼치기·접기
   가설이 틀렸으면 실제 원인을 Result에 적고 Leader에게 보고합니다.
2. 수정: `SidebarApp._render_projects`와 `_project_block`을 Disposition의 방법으로 바꿉니다. `_actions`(click 대상), widget id, scroll·focus 복원, tooltip 규칙은 지금과 같게 유지합니다.
3. Test: 기대값은 Contract에서 얻습니다. 구현을 복제하는 검사는 쓰지 않습니다.
   - 값만 바뀐 갱신에서 같은 widget이 유지되고 글자·class가 바뀌는지
   - (a)·(b)·(c)와 error 행 증감, 현재 창 변경에서 중간 상태가 그려지지 않는지
   - 바뀐 것이 없으면 그리지 않는지(BOARD-013)
   - click 대상과 scroll·focus가 유지되는지
4. 1단계의 재현을 수정 후 코드에서 다시 실행해 중간 frame 수를 비교합니다. 16×16, 반복 3회입니다. test는 이 측정과 동시에 돌립니다.
5. 사용자가 볼 수 있게 수정 전후의 연속 capture를 `/primehome/swain/tmp/board017/`에 둡니다. seat 밖이며 정리 때 지우지 않습니다.

의존: 없음. BOARD-016은 read-only라 같은 파일을 고치지 않습니다.

위험 등급: 중간. Board의 모든 갱신 경로를 바꿉니다.

## Verification
1. README 검증 표의 `tools/project-board/**` 행:
   - `python -m pytest -q tools/project-board/tests`
   - `python -m pytest -q tools/agent-session/tests/test_api_boundary.py`
2. Implementation 4의 중간 frame 수 비교(수정 전, 수정 후)와 capture 경로를 Result에 적습니다.
3. idle CPU를 따로 재지 않습니다. 바뀐 것이 없으면 그리지 않는다는 규칙은 3번 test로 확인합니다.
