# BOARD-021: CR 창은 네 상태를 접을 수 있는 묶음으로 한 창에 보이고, CR·결정 창은 ◀▶로 project를 옮깁니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S3
- Base: ed7200addb6bb0f0415a16aac39fd6b67413ccd2 2026-11-11T10:39:41+09:00
- Outcome: fixed

## Symptom
- CR 창은 sidebar에서 누른 상태(open, todo, in-progress) 하나만 보입니다. done은 볼 수 없습니다. 위쪽 제목은 `<project> · <상태> <위치>/<개수> · <ID>`입니다.
- CR·결정 창은 연 project 하나만 보입니다. 다른 project를 보려면 창을 닫고 sidebar에서 다시 눌러야 합니다.

사용자 요청(2026-11-11):
- "2.5. Decision/CR의 project 단위로 보이는데, Project 좌우에 ◀▶ 이런 표시가 있어서 project 이동이 가능하고, project에 따른 내용을 볼 수 있게"
- "2.5.1 Decision의 경우 Decision 항목이 있는 Project로 바로 이동"
- "2.5.2 ◀▶ mouse over 시에 어느 project로 가는지 알 수 있게 tooltip window ( Decision / CR 모두 )"
- "2.6. CR 관련 창은 현재 open / todo / in-progress를 직접 클릭 해야하는데, O/T/I 어떤 것을 선택하더라도, 같은 CR 창이 생성되고 Open / Todo / In-Progress / Done이 모두 보이게 수정"
- "2.6.1 최상단에 현재 {STATUS} {N}인데, Open {N} , Todo {N}, In-Progress {N}, Done {N} 으로 표시."
- "2.6.2 CR List에서는 Open ▼ (folding 가능하게) .... < Open list > ... Todo ▼ (folding 가능하게) .... < Todo list > ... In-Progress ▼ (folding 가능하게) .... < In-Progress list > ... Done ▼ (folding 가능하게) .... < Done list > ..."

## Evidence
- `tools/project-board/project_board/tui.py`:
  - `CRPopupApp`은 `state` 하나의 목록만 mount합니다. 제목은 `_show_cr`·`_show_message`가 씁니다.
  - `PopupApp`(결정)은 `project_id` 하나의 `_visible_decisions`만 보입니다.
- `tools/project-board/project_board/model.py`:
  - `CR_STATES = ("open", "todo", "in-progress")`이고 주석은 "done and deferred are not shown"입니다.
  - `read_cr_markdown`은 `CR_STATES` 밖의 상태를 거절합니다(190행).
- sidebar의 `D` 버튼은 `_visible_decisions(project)`가 있을 때만 켜집니다. 결정 창에서 "결정 항목이 있는 project"의 기준은 이것과 같게 둡니다.

## Contract
1. CR 창
   - sidebar의 O·T·I 중 무엇을 눌러도 같은 CR 창이 열립니다. 목록은 Open, Todo, In-Progress, Done 네 묶음입니다.
   - 각 묶음 제목은 `Open ▼` 모양이고, 눌러 접고 펼칩니다. 처음에는 네 묶음이 모두 펼쳐져 있습니다. 누른 상태의 묶음과 그 첫 CR이 처음 보이게 scroll합니다.
   - 맨 위에는 `Open {N}, Todo {N}, In-Progress {N}, Done {N}`을 표시합니다.
   - done CR도 본문을 열어 볼 수 있습니다. deferred는 지금처럼 보이지 않습니다.
2. project 이동(CR·결정 창 공통)
   - project 이름 양옆에 ◀▶가 있고, 누르면 이전·다음 project의 내용으로 바뀝니다. 순서는 sidebar의 등록 순서이고, 끝에서는 반대쪽 끝으로 돕니다.
   - mouse를 ◀▶ 위에 올리면 갈 project 이름을 tooltip으로 보입니다.
   - CR 창은 모든 등록 project를 돕니다. 결정 창은 결정 항목이 있는 project(sidebar `D`가 켜지는 기준)만 돕니다.
   - project를 옮겨도 창은 닫히지 않고 같은 창에서 바뀝니다.
3. 결정 창의 답변 입력과 보내기 동작은 지금과 같습니다. 쓰던 답변 초안은 project를 옮겼다 돌아와도 남아 있습니다.
4. sidebar의 개수 규칙(O·T·I 숫자)은 바뀌지 않습니다. done 읽기는 CR 창에서만 합니다.

## Disposition
- 2026-11-11 Leader: 구현한다. 사용자 요청 2.5·2.6입니다(원문은 Symptom).
- 2026-11-11 Leader 판정: 사용자 예시에 따라 묶음은 처음에 모두 펼칩니다. 끝에서 돌기, 누른 상태로 처음 scroll하기, 초안 유지는 Leader가 정한 세부입니다.
- 2026-11-11 Leader: open -> todo. 사용자 요청 2.5·2.6
- 2026-11-11 Leader: 제출 7d849aea9eec6ece48e184d56e094f1ce1016725를 인수합니다. 검토 7d849ae(구현 3922a27·0626e7c + main 28641d5 merge). model의 READABLE_STATES·done_items·done_title·popup_snapshot(sidebar의 CR_STATES·snapshot 불변), CRPopupApp의 네 묶음·접기·개수 줄·처음 scroll·◀▶(등록 순서, 끝에서 돌기, tooltip), PopupApp의 D 기준 project 이동·초안 (project, 결정)별 유지, 계획 문서를 읽었습니다. done 제목을 파일 이름으로 먼저 그리고 한 파일씩 바꾸는 것(balvian 1471개 19초 회피), 결정 창 ◀▶가 background 읽기 동안 약 5초 꺼지는 것, 접힘 유지는 Worker 판단으로 받아들입니다. merge 뒤 제출 commit에서 project-board tests + test_api_boundary 191 passed. 화면 capture /primehome/swain/tmp/board021/.
- 2026-11-11 Leader: in-progress -> done, Outcome fixed. 통합 8ef27bd (origin/main)

## Implementation
읽을 문서: [Board TUI 계획](../../project-board-tui-plan.md)의 CR·결정 창 절, `tools/project-board/project_board/tui.py`(`CRPopupApp`, `PopupApp`, `_visible_decisions`), `model.py`(`CR_STATES`, `cr_items`, `read_cr_markdown`, `snapshot(project_id=...)`), `cli.py`(`cr`·`popup` 하위 명령), `tools/project-board/tests/test_tui.py`·`test_model.py`, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. model: CR 창이 쓸 done 목록과 done 본문 읽기를 더합니다. sidebar snapshot(`CR_STATES`의 의미와 sidebar 개수)은 바꾸지 않습니다. BOARD-018(Rust sidebar)이 이 규칙을 옮기고 있기 때문입니다.
2. CR 창을 Contract 1·2로 바꿉니다.
   - `cr` 하위 명령의 `--state`는 처음 scroll할 묶음으로 씁니다. 하위 명령 이름과 인자는 유지합니다. BOARD-018·BOARD-020이 이 하위 명령을 부르기 때문입니다.
3. 결정 창을 Contract 2·3으로 바꿉니다.
4. 계획 문서의 CR·결정 창 절을 고칩니다.
5. Test: Contract 1~4마다 Textual `run_test` test를 둡니다(묶음 접기, 개수 줄, ◀▶ 이동과 끝에서 돌기, tooltip 내용, 결정 창의 project 걸러내기, 초안 유지).

의존: 없음. BOARD-018이 `tui.py`에서 `SidebarApp`을 지우는 동안 진행합니다. 제출 전에 `origin/main`을 merge합니다.

위험 등급: 낮음. popup 화면만 바뀝니다.

## Verification
1. README 검증 표의 `tools/project-board/**` 행:
   - `python -m pytest -q tools/project-board/tests`
   - `python -m pytest -q tools/agent-session/tests/test_api_boundary.py`
2. 실제 등록에서 CR 창과 결정 창 화면을 `tmux capture-pane -p -e`로 `/primehome/swain/tmp/board021/`에 저장합니다. 경우는 네 묶음, 접힌 묶음, ◀▶ 이동 뒤입니다.

## Result
- 제출 commit: 7d849aea9eec6ece48e184d56e094f1ce1016725

`cr/BOARD-021`(origin에 push). Base `ed7200a`에서 시작해 `origin/main`(`28641d5`, BOARD-019 통합까지)을 merge한 상태입니다. 충돌은 없었고 merge가 들여온 변경(tmux binding·installer·`test_tmux_control.py`)은 이 변경과 겹치지 않습니다.

변경:
- `model.py`: `READABLE_STATES`(done 포함)로 `read_cr_markdown`이 done 본문을 읽습니다. `done_items`·`done_title`·`popup_snapshot(config, project_id, done=False)`를 더했습니다. `popup_snapshot`은 연 project 하나의 `snapshot`에 등록 순서 `order`를 붙이고, `done=True`면 `crs["done"]`을 붙입니다. `CR_STATES`·`snapshot`·sidebar 개수는 그대로입니다(BOARD-018 영향 없음).
- `tui.py`: `CRPopupApp`은 Open/Todo/In-Progress/Done 네 묶음(`Open ▼` 접기·펼치기), 맨 위 `Open N, Todo N, In-Progress N, Done N`, `◀ project ▶`(모든 등록 project, 끝에서 돌기, tooltip `이전/다음 project: NAME`)입니다. `cr --state`는 처음 scroll할 묶음과 그 첫 CR 선택에만 씁니다(하위 명령 이름·인자 그대로). `PopupApp`(결정)에도 `◀ project ▶`를 두고, 갈 project는 sidebar `D` 기준(`_visible_decisions`)입니다. 답변 초안은 (project, 결정 ID)별로 남고 돌아오면 떠날 때 보던 결정이 열립니다. 전송 중에는 옮기지 않습니다.
- 문서: `docs/project-board-tui-plan.md`(CR popup·Project 이동 절), `tools/project-board/README.md`.

설계 판단(Leader가 알아야 할 것):
1. done 목록은 파일을 열지 않고 파일 이름의 제목으로 먼저 그린 뒤 첫 줄을 한 파일씩 읽어 진짜 제목으로 바꿉니다. 실제 등록에서 done 파일 하나를 여는 데 약 13 ms(공유 disk)가 걸려 balvian 1471개를 모두 열면 19초이기 때문입니다.
2. 두 popup 모두 전체 project를 읽지 않고 연 project 하나만 읽어 바로 뜹니다(전체 snapshot은 실제 등록 10개에서 cold 5초). CR 창의 ◀▶는 등록 순서만 필요해 즉시 켜집니다. 결정 창은 다른 project의 결정 여부를 창이 뜬 뒤 background로 읽으므로 약 5초 동안 ◀▶가 꺼져 있다가 켜집니다(`navigation_reader`).
3. 묶음 접힘은 project를 옮겨도 유지합니다(창 단위 상태). 누른 상태의 묶음이 비어 있으면 첫 CR로 선택합니다. 이 두 가지는 CR 문구에 없어 정했습니다.

검증:
- `python -m pytest -q -n 8 tools/project-board/tests tools/agent-session/tests/test_api_boundary.py` → 191 passed (merge 뒤 제출 commit에서 실행). 새 Textual `run_test` test 12건: 네 묶음·개수 줄(O/T/I 각각), 처음 scroll, 접기·펼치기와 done 본문 읽기, 빈 묶음, sidebar snapshot에 done 없음, done 읽기 경로 거절, CR 창 ◀▶ 이동·끝에서 돌기·tooltip·창 유지, project 하나일 때 꺼짐, 결정 창 project 걸러내기·tooltip·초안 유지·전송 project, background로 project 목록 읽기.
- 실제 등록(10 project)에서 격리 tmux server(`tools/tests/tmux_test_server.claim`)에 `project-board cr`·`popup`을 띄워 mouse click(SGR 입력)으로 조작하고 `tmux capture-pane -p -e`를 `/primehome/swain/tmp/board021/`에 저장했습니다: `cr-four-groups`(In-Progress가 맨 위로 scroll, done 65개), `cr-folded-groups`(In-Progress 접힘), `cr-next-project-wraps`(project-agent → 끝에서 agent로 돌기, 접힘 유지), `cr-back`, `decision-first`·`decision-next-project`(agent → socsim)·`decision-back`. 격리 server는 `release`로 정리했습니다. Tooltip은 tmux 화면에 나타나지 않아 Textual `tooltips=True` test로 확인했습니다.
- 근거 재사용: 변경 전·후 비교용 전체 검증은 하지 않았고, merge 입력(BOARD-019)이 바뀌어 제출 commit에서 위 두 명령을 다시 실행했습니다.
