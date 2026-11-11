# BOARD-024: 결정 답변 창에서 Ctrl+J로도 줄을 바꿉니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S3
- Base: 544198c38d9740aaff748805459797d0e350d883 2026-11-11T13:46:00+09:00
- Outcome: fixed

## Symptom
결정 창의 답변 입력란에서 Ctrl+J를 눌러도 줄이 바뀌지 않습니다. 줄바꿈은 Enter로만 됩니다.

사용자 요청(2026-11-11): "Decision 답변 창에서 ctrl+j도 개행이 되게 수정해줘."

## Evidence
- `tools/project-board/project_board/tui.py`:
  - `PopupApp`의 답변 입력란은 Textual 기본 `TextArea(id="answer")`입니다(1080행).
  - App binding은 `escape`(닫기)와 `ctrl+s`(전송)뿐입니다(1032행).
- 기본 `TextArea`는 Enter(`enter`)에만 줄바꿈을 넣습니다. terminal은 Ctrl+J를 LF로 보내고, Textual은 이를 `ctrl+j` 키로 받아 처리하지 않는 것으로 보입니다(가설, Implementation 1에서 확인).

## Contract
- 답변 입력란에 focus가 있을 때 Ctrl+J는 커서 위치에 줄바꿈을 넣습니다. Enter와 결과가 같습니다.
- 다른 키(Enter, Ctrl+S 전송, Esc 닫기)와 입력란 밖의 동작은 바뀌지 않습니다.

## Disposition
- 2026-11-11 Leader: 구현한다. 사용자 요청입니다(원문은 Symptom).
- 2026-11-11 Leader: open -> todo. 사용자 요청
- 2026-11-11 Leader: 제출 6d99566382b271201abb13259551c540a3883aea를 인수합니다. 검토 6d99566(main 544198c 기준, 그 뒤 main은 CR 이동만). AnswerArea(ctrl+j를 선택 영역 포함 커서 위치에 줄바꿈, read_only면 무시, 나머지 키는 TextArea로)와 #answer 교체, 계획 문서 결정 창 5항, test(Ctrl+J·Enter·커서 위치·Ctrl+S)를 읽었습니다. project-board 200 통과 + 고친 새 test 포함 7 통과(바뀐 것은 새 test의 기대값뿐이라 나머지 근거 재사용 인정), test_api_boundary 4 통과, 실제 tmux send-keys C-j 확인.
- 2026-11-11 Leader: in-progress -> done, Outcome fixed. 통합 11d1c64 (origin/main)

## Implementation
읽을 문서: `tools/project-board/project_board/tui.py`의 `PopupApp`, `tools/project-board/tests/test_tui.py`, [Board TUI 계획](../../project-board-tui-plan.md)의 결정 창 절, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. Textual `run_test`에서 Ctrl+J가 어떤 키로 들어오는지 확인합니다. 실제 tmux pane에서도 확인합니다(`send-keys C-j`).
2. 답변 입력란에서 Ctrl+J가 줄바꿈을 넣게 합니다. 입력란에만 적용합니다.
3. 계획 문서의 결정 창 키 설명에 Ctrl+J를 더합니다.
4. Test: Ctrl+J 줄바꿈, Enter 동작 유지, Ctrl+S 전송 유지.

의존: 없음.

위험 등급: 낮음.

## Verification
1. README 검증 표의 `tools/project-board/**` 행:
   - `python -m pytest -q tools/project-board/tests`
   - `python -m pytest -q tools/agent-session/tests/test_api_boundary.py`
2. 실제 tmux pane에서 `send-keys C-j`로 줄바꿈이 들어가는지 Result에 적습니다.

## Result
- 제출 commit: 6d99566382b271201abb13259551c540a3883aea

원인(확인): Textual 8.2.8 `run_test`에서 Ctrl+J는 `key="ctrl+j"`, `character=None`으로 들어옵니다. `TextArea._on_key`는 `enter`와 printable 문자만 삽입하므로 무시됩니다.

변경:
- `tools/project-board/project_board/tui.py`: `AnswerArea(TextArea)`를 추가해 `ctrl+j`를 Enter처럼 커서 위치(선택 영역 포함)에 `\n`으로 삽입합니다. `PopupApp`의 `#answer`만 이 클래스를 씁니다. 다른 키는 `super()._on_key`로 넘깁니다.
- `docs/project-board-tui-plan.md` 결정 창 5항에 Enter·Ctrl+J 줄바꿈과 Ctrl+S·Esc를 적었습니다.
- `tools/project-board/tests/test_tui.py`: `test_answer_box_ctrl_j_inserts_a_newline_like_enter_and_keeps_ctrl_s`가 Ctrl+J 줄바꿈, Enter 줄바꿈, 커서 위치 삽입, Ctrl+S 전송을 확인합니다.

검증:
- `python -m pytest -q tools/project-board/tests`: 201개 중 200 통과, 1 실패. 실패는 새 test의 기대 tuple이 config 인자를 빠뜨린 test 오류였고 동작 오류가 아니었습니다. 기대값을 고친 뒤 `-k "ctrl_j or answer"` 7개 통과를 확인했습니다. 나머지 200개는 코드 변경 없이 같은 commit 내용에서 통과했으므로 전체를 다시 돌리지 않았습니다(근거 재사용).
- `python -m pytest -q tools/agent-session/tests/test_api_boundary.py`: 4 통과.
- 실제 tmux pane(전용 socket, `PopupApp` 실행, 답변 입력란 focus): `send-keys a C-j b Enter c` 뒤 입력란에 `a`/`b`/`c` 세 줄이 표시됐습니다. 임시 tmux server는 정리했습니다.
