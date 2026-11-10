# BOARD-017: Board sidebar가 project 단위로 widget을 다시 mount해 열 때와 갱신 때 화면이 깜빡입니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S2
- Base: d092c3f69bd7529c8027ebff27c47e80deee2eb4 2026-11-11T02:01:42+09:00
- Outcome: fixed

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
- 2026-11-11 Leader: 제출 26acbd339d2a4bf99282e4a6ca58062a20bf0647를 인수합니다. 검토 26acbd3(main d092c3f 기준, merge 없음). tui.py의 제자리 갱신(_fill_summary·_fill_rows 공용), 행 구성(_shape) 변경과 목록 변경의 batch_update 적용, render lock, plan 3절 규칙, test(Frames 기록기는 Textual 8.2.8의 _display가 _batch_count 동안 그리지 않는 것과 같게 기록)를 읽었습니다. project-board 174·test_api_boundary 4 통과, 중간 frame 3회 합 16x16 39→9, 25x16 42→6, 25x40 36→0. 남은 frame은 목록 길이가 화면 높이를 넘나들 때 Textual이 scrollbar를 정하는 layout 한 번이며, 없애려면 scrollbar-gutter로 모양이 바뀌므로 Contract(모양 유지)에 따라 남깁니다. main은 그 뒤 CR 문서(291be12)만 진행해 검증 입력이 같습니다.
- 2026-11-11 Leader: in-progress -> done, Outcome fixed. 통합 cdfb000 (origin/main)

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

## Result
- 제출 commit: 26acbd339d2a4bf99282e4a6ca58062a20bf0647

### 원인 (1단계 재현, 가설 확인)
수정 전 코드에서 Textual이 그리는 frame을 직접 기록했습니다(`App._display` 호출마다 compositor 전체 화면과 style을 저장). 가설대로입니다. 바뀐 project block은 옛 block 앞에 `mount`되어 다음 `await`에서 `remove`되므로, 그 사이 frame에는 위쪽 빈 줄과 밀린 행이 그려집니다. 목록 변경과 첫 그리기는 `remove_children`과 `mount`가 다른 `await`라서 빈 목록 frame이 그려집니다. 여는 동안(snapshot → liveness → context)과 1분마다 같은 block이 반복해서 교체되므로 갱신마다 깜빡입니다.

### 수정 (`tools/project-board/project_board/tui.py`)
- 값만 바뀌면(글자, class, tooltip, disabled, Leader·error 행의 글자) 이미 mount한 widget에 씁니다(`_update_block`). 같은 값은 다시 쓰지 않습니다. 쓰는 코드(`_fill_summary`, `_fill_rows`)는 새 block을 만드는 `_project_block`과 같습니다.
- 행이 생기거나 없어지는 변경(`_shape`가 달라질 때: 펼치기·접기, Leader·seat·error 행의 증감)은 block을 바꿉니다. project 목록의 변경(추가·삭제·순서·첫 그리기)은 전체를 다시 만듭니다. 두 경우 모두 `App.batch_update()` 하나 안에서 적용합니다.
- `_render_projects`에 `asyncio.Lock`을 추가했습니다. 두 render가 `await`에서 섞여 `_blocks`·`_actions`가 어긋나는 것을 막습니다.
- 유지한 것: widget id(`project-<n>-...`), `_actions`(갱신 때마다 새 project dict로 다시 등록), scroll·focus 복원, tooltip 규칙, BOARD-013의 signature(바뀐 것이 없으면 그리지 않음), 색·행 구성.
- docs: `docs/project-board-tui-plan.md` 3절에 다시 그리기 규칙 한 줄을 추가했습니다.

### Test
- `test_tui.py`: 옛 test 두 개(block 교체 횟수를 단언)를 새 계약으로 바꿨습니다(같은 widget 유지, 값 갱신, 바뀐 것이 없으면 그리지 않음).
- 추가: 변경 전·후 화면 사이의 frame이 없음을 (a) snapshot → liveness → context, (b) 분·seat job·현재 창, (c) 접기·펼치기·project 추가·error 행 증감에서 확인합니다. 값이 바뀌어도 click 대상·scroll·focus가 유지됨을 확인하고, 겹친 render에서 project당 block 하나가 남음을 확인합니다. `board_testing.Frames`가 frame 기록기입니다.
- 새 frame test는 수정 전 `tui.py`에서 실패합니다(liveness 단계에서 중간 frame). 값 갱신 test도 수정 전에는 widget이 교체되어 실패합니다.

### 검증 (제출 commit에서, 측정과 동시에 실행)
- `python -m pytest -q tools/project-board/tests` → 174 passed
- `python -m pytest -q tools/agent-session/tests/test_api_boundary.py` → 4 passed

### 중간 frame 수 비교
방법은 scenario 12개(a1 snapshot, a2 liveness, a3 context, b1 분, b2 seat 배정, b3 liveness 변경, b4 현재 창, c1 접기, c2 펼치기, c3 project 추가, c4·c5 error 행 증감)를 단계마다 실행하는 것입니다. 변경 전 화면이나 변경 후 화면과 다른 frame을 중간 frame으로 셉니다. 반복은 3회입니다. 비교할 때 오른쪽 4칸(세로 scrollbar와 그 옆에서 잘리는 글자)은 제외합니다. 수정 전은 `d092c3f`의 `tui.py`입니다.

| 터미널 크기 | 수정 전 중간 frame (3회 합) | 수정 후 중간 frame (3회 합) |
| --- | --- | --- |
| 16×16 (CR 지정) | 39 | 9 |
| 25×16 (Board 기본 폭) | 42 | 6 |
| 25×40 (scrollbar 없음) | 36 | **0** |

- 수정 전은 12개 중 11개 단계에서 매번 1~2개씩(b1 분 갱신 포함) 중간 frame이 있었고, 수정 후 값만 바뀌는 단계(a2·a3·b1~b4)는 모든 크기에서 0입니다. c3~c5도 0입니다.
- 수정 후 남은 것은 scrollbar가 생기거나 없어지는 단계(a1 첫 그리기, c1·c2 접기·펼치기 중 목록 길이가 화면 높이를 넘나드는 경우)에서 Textual이 scrollbar를 정하려고 한 번 더 layout하는 frame입니다. 이때 행의 위치와 내용은 최종 화면과 같고, scrollbar 칸과 맨 아래 줄만 한 번 다릅니다. 25×40처럼 scrollbar가 없으면 나타나지 않습니다. 이 frame을 없애려면 `scrollbar-gutter`로 scrollbar 칸을 늘 남겨야 하고 화면 모양이 바뀝니다. Contract의 "화면 모양은 지금과 같다"를 지키려고 하지 않았습니다. plan 3절에도 이 한계를 적었습니다.
- 수정 전 16×16의 a1이 0으로 나오는 것은 비교에서 오른쪽 4칸을 제외하기 때문입니다.

### 연속 capture (5단계)
`/primehome/swain/tmp/board017/`
- `before/<크기>/run<N>/<scenario>/`, `after/<크기>/run<N>/<scenario>/`에 `before.txt`, `frameNN-{final|intermediate}.txt`, `after.txt`가 있습니다. `final`은 변경 전·후와 같은 frame입니다.
- 크기별 `summary.json`과 측정 스크립트 `measure_frames.py`(`measure_frames.py <label> <repo> [반복] [열x행]`)가 같은 폴더에 있습니다. 예: `before/25x40/run1/b1-minute/frame01-intermediate.txt`(위가 비고 아래 행이 밀린 frame).

### 근거 재사용·재실행 판정
`origin/main`은 시작 뒤 CR 상태 docs commit(`291be12`)만 진행해 merge하지 않았습니다. 코드·검증 입력이 같아 위 검증을 그대로 씁니다. idle CPU는 Verification 3에 따라 재지 않았습니다.
