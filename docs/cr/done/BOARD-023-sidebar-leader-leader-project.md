# BOARD-023: sidebar의 Leader 줄을 지우고 Leader 경과 시간을 project 이름 옆에 둡니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S3
- Base: d027205cfbb5208cea3a9174e2cae01128755592 2026-11-11T13:10:56+09:00
- Outcome: fixed

## Symptom
펼친 project에는 `  Leader 1d 01h 31m` 줄이 따로 있어서 줄이 늘어납니다.

사용자 요청(2026-11-11): "project들 마다 Leader 시간 이렇게 되어 있는데, {proejct} {time}로 간략화 하고, Leader {time} 라인은 삭제하자. 괜히 line만 늘어나서 오히려 불편한거 같아."

## Evidence
- 설치본 0.8.0 `tools/project-board/project_board/tui.py`:
  - `_project_block`은 펼친 project이고 Leader 경과(`format_elapsed(project["leader"]["elapsed"])`)가 있을 때만 `.leader` 줄을 만듭니다. tooltip은 "Leader session이 게시된 뒤 지난 시간"입니다.
  - 현재 창이 Leader window이면 그 줄이 `slot-active`로 강조됩니다. 접힌 project에서는 접기 버튼이 `slot-active`이고, tooltip은 "현재 창: Leader"입니다.
- `_project_signature`와 `_shape`(BOARD-013·BOARD-017)는 펼친 project의 Leader 경과만 넣습니다.
- 경과 형식은 [Board TUI 계획](../../project-board-tui-plan.md) 3절(BOARD-008)이 소유합니다.
- BOARD-018이 sidebar를 Rust로 옮기고 있습니다. Rust sidebar도 이 모양을 따라야 합니다.

## Contract
1. project 이름 줄은 `{project} {time}`입니다. time은 Leader 경과이고 형식은 지금과 같습니다. 펼침과 접힘에 관계없이 보입니다. Leader session이 게시되지 않았으면 이름만 보입니다. 현재 창의 project이면 `▶ {project} {time}`입니다.
2. `Leader {time}` 줄은 없습니다.
3. 현재 창이 Leader window이면 project 이름 줄의 강조(`project-active`)로 나타냅니다. 접기 버튼의 `slot-active`와 "현재 창" tooltip은 seat slot일 때만 씁니다.
4. 이름 줄 tooltip에 Leader 경과의 뜻("Leader session이 게시된 뒤 지난 시간")을 함께 적습니다.
5. 경과 분이 바뀌면 그 이름 줄의 글자만 바뀝니다(BOARD-017 제자리 갱신). 바뀐 것이 없으면 그리지 않습니다(BOARD-013).

## Disposition
- 2026-11-11 Leader: 구현한다. 사용자 요청입니다(원문은 Symptom).
- 2026-11-11 Leader 판정: Leader 줄이 없어지므로 현재 창이 Leader일 때는 이름 줄 강조로 나타냅니다. 경과 시간은 접힌 project에도 보입니다.
- 2026-11-11 Leader: open -> todo. 사용자 요청
- 2026-11-11 Leader: 제출 3bc69d3d8f535adbb84a2d56262c921b951a5fa0를 인수합니다. 검토 3bc69d3(main d027205 기준, 그 뒤 main은 CR 이동만). 이름 줄 글자·tooltip, .leader 줄과 CSS 제거, _shape에서 Leader 제외와 signature의 접힘 포함, Leader slot의 이름 줄 강조와 접기 버튼 slot-active의 seat 한정, 계획 3절·README를 읽었습니다. project-board tests 200 passed, test_api_boundary 통과. 폭 25 화면 /primehome/swain/tmp/board023/(긴 이름은 잘리고 가로 스크롤로 전체 확인).
- 2026-11-11 Leader: in-progress -> done, Outcome fixed. 통합 13439ea (origin/main)

## Implementation
읽을 문서: `tools/project-board/project_board/tui.py`(`SidebarApp._project_block`, `_fill_summary`, `_fill_rows`, `_shape`, `_project_signature`), [Board TUI 계획](../../project-board-tui-plan.md) 3절, `tools/project-board/README.md`, `tools/project-board/tests/test_tui.py`, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. Contract 1~5로 Python sidebar를 고칩니다. 계획 문서와 README의 화면 설명을 고칩니다.
2. Test: 이름 줄 글자(펼침·접힘·Leader 없음·현재 창), Leader 줄 없음, Leader window 강조, 경과 분 변경 때 제자리 갱신.
3. 폭 25에서 긴 이름과 `2d 01h 00m`이 넘치는 경우의 화면을 `tmux capture-pane -p -e`로 `/primehome/swain/tmp/board023/`에 남깁니다. 가로 스크롤로 전체를 볼 수 있는지 확인합니다.

의존: 없음. BOARD-018(Rust sidebar)이 같은 화면을 옮기고 있습니다. Leader가 BOARD-018에 이 모양을 따르라고 알립니다.

위험 등급: 낮음.

## Verification
1. README 검증 표의 `tools/project-board/**` 행:
   - `python -m pytest -q tools/project-board/tests`
   - `python -m pytest -q tools/agent-session/tests/test_api_boundary.py`

## Result

- 제출 commit: 3bc69d3d8f535adbb84a2d56262c921b951a5fa0

변경: `tui.py`에서 `.leader` 줄과 CSS를 지우고 이름 버튼 글자를 `[▶ ]{project}[ {time}]`로 합니다(펼침·접힘 무관). 이름 tooltip에 "Leader session이 게시된 뒤 지난 시간"을 붙입니다. `_shape`에서 Leader 항목을 빼고 `_project_signature`의 Leader 시간은 접힌 project에도 넣습니다(분이 바뀌면 이름 줄 글자만 제자리 갱신, 바뀐 것이 없으면 그리지 않음). Leader window는 이름 줄 강조(`project-active`)만 쓰고, 접기 버튼의 `slot-active`·"현재 창" tooltip은 seat slot일 때만 씁니다. [Board TUI 계획](../../project-board-tui-plan.md) 3절과 `tools/project-board/README.md`를 고쳤습니다.

검증:
- `python -m pytest tools/project-board/tests` → 200 passed (제출 commit, 부하 없이 단독 실행). 앞선 중복 실행 한 번에서 `test_cr_window_scrolls_to_the_pressed_group_first`가 실패했지만 CR 창 테스트이고, 단독 3회·전체 재실행에서 통과했습니다(동시 pytest 부하로 인한 일시 실패로 판단).
- `python -m pytest tools/agent-session/tests/test_api_boundary.py` → 통과.
- 새·고친 test(`test_tui.py`·`test_tmux_control.py`): 이름 줄 글자(펼침·접힘·Leader 없음·현재 창 `▶`), Leader 줄 없음, Leader window 강조와 seat window의 slot 표시, 경과 분 변경 때 이름 위젯 제자리 갱신(같은 widget, `built == []`), 변경 없을 때 그리지 않음.
- 폭 25 실제 화면: `tmux capture-pane -p -e`를 `/primehome/swain/tmp/board023/`에 남겼습니다(`folded.txt`, `expanded.txt`, `folded-scrolled-right.txt`, `expanded-scrolled-right.txt`, 각 `.plain.txt`). 긴 이름 `A-very-long-project-name-exceeding` + `2d 01h 00m`은 폭 25에서 잘리고, 가로 스크롤(마우스 오른쪽 scroll)로 `me-exceeding 2d 01h 00m`까지 전체를 볼 수 있음을 확인했습니다. 펼치면 Leader 줄 없이 seat 행만 늘어납니다.
- 근거 재사용·재실행: main merge 없음(Base 그대로). Rust sidebar(BOARD-018)는 범위 밖입니다.
