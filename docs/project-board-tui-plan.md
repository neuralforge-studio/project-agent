# Project Board TUI 계획

- 상태: 구현 완료. 격리 tmux 서버와 실제 TUI 화면에서 주요 동작을 확인했습니다.
- 기준: `dc9103a`의 Project Board, project-item, agent-session, tmux 설정. tmux는 [공식 GitHub `master`](https://github.com/tmux/tmux) 커밋 `a73616d`를 빌드한 `next-3.9`입니다.
- 관계: 이 문서가 현행 Board의 TUI 계약을 소유합니다. [기존 웹 Board 계획](project-board-plan.md)은 이전 구현의 기록입니다.

## 1. 목표와 범위

사용자는 tmux sidebar **하나에 모든 등록 project**의 CR, 결정 대기, Worker seat를 연속해서 봅니다. 현재 tmux session의 project만 표시하지 않습니다. 사용자는 키와 마우스 클릭으로 sidebar를 켜고 끕니다. 사용자는 큰 popup에서 결정 항목을 읽고 답을 접수합니다.

TUI는 답변 접수에만 `project_item`의 Decision 기록 경로를 사용합니다. CR과 배정은 고치지 않습니다. 기존 HTML server와 브라우저 화면은 TUI로 교체합니다. 최종 상태에는 Board HTTP server, 포트, API, HTML 화면이 없습니다. 결정 대기 알림은 이미 있는 `tmux_decide_status.py`가 맡습니다. TUI는 같은 알림을 다시 만들지 않습니다.

## 2. 데이터 원본과 책임

| 정보 | 원본과 읽기 경로 | TUI의 책임 |
| --- | --- | --- |
| Project와 seat 수 | 등록 파일, `agent_session.config.load_registry` | 등록 순서대로 표시 |
| 배정과 검토 대상 | `<base>/agent/state.json`, `agent_session.api` | seat 행의 CR ID와 `R` 표시 |
| 실행 확인 | `agent_session.api.liveness` | 멈춤·확인 불가를 색과 설명으로 표시 |
| CR 개수 | `project_item`이 읽는 `path_cr/open`, `todo`, `in-progress` | `O`, `T`, `I`에 표시 |
| 결정 상태와 답변 | `project_item`이 읽는 `path_decide/open`, `answered`, `done` | `D`와 popup에 표시하고 `open → answered` 접수를 기록 |
| 반영 진행 | Decision의 `Related`가 가리키는 `path_cr` 상태 | `반영 중`과 `완료`를 계산 |
| Leader 알림 | `agent-session send --job leader` | 저장한 사용자 답을 알리고 결과를 표시 |

기존 [`project_board.model`](../tools/project-board/project_board/model.py)의 `snapshot()`과 `liveness()`를 재사용합니다. TUI는 개수나 상태의 별도 원본을 만들지 않습니다. Sidebar의 켜짐 상태, 폭, 선택 위치를 tmux UI 상태로 유지합니다. 좌석 펼침 상태의 원본은 tmux server option 하나입니다. Board pane은 project별 상태를 공유하며 새 pane도 이를 읽습니다.

### 갱신과 실행 단위

TUI 프로세스를 새로 띄우는 비용은 Python·Textual 기동과 첫 읽기입니다. 이 host에서 수 초이므로 사용자의 조작(창 이동, 클릭)마다 프로세스를 새로 만들지 않습니다. 조작은 이미 떠 있는 프로세스에 도달하거나 읽기만 하는 짧은 명령이 되게 합니다(BOARD-002).

Sidebar를 한 번 표시한 tmux window마다 TUI 프로세스 하나를 둡니다. 이 프로세스는 Board를 끄거나 window가 닫힐 때까지, 동시에 8개까지 유지합니다(5절). 어느 client도 보지 않는 window의 프로세스는 읽지 않습니다. 같은 window를 보는 client는 같은 pane과 화면을 봅니다. 각 프로세스의 이벤트 루프가 화면과 마우스·키보드 입력을 처리합니다. 별도 상주 HTTP server나 project별 감시 프로세스를 두지 않습니다. 결정 popup을 열 때만 별도의 단기 TUI 프로세스를 실행합니다. Popup은 같은 파일 원본을 직접 읽습니다. 제출 경로는 Decision root 잠금 안에서 `open`을 다시 확인합니다.

Sidebar TUI는 파일 상태를 2초마다, 실행 상태를 10초마다 다시 읽습니다. 실행 상태는 tmux 서버를 읽는 일(project·slot 수와 무관하게 tmux process 둘, `agent_session.api.server_view`)이므로 2초 읽기에 넣지 않습니다. 반납 대기(`release_pending`)도 10초 읽기가 갱신합니다(`model.liveness`가 채우고 `snapshot`이 씁니다). 어느 client에도 보이지 않는 window의 TUI는 두 읽기를 모두 멈추고, 보이게 되면 각각 곧바로 한 번 읽습니다. tmux hook이 보임 상태가 바뀐 pane에 SIGUSR1을 보내고, pane이 tmux에 자기 window가 보이는지 묻습니다(`tmux_control.board_visible`). 2초마다 tmux를 새로 부르지 않습니다. 읽기는 바뀐 것만 다시 파싱합니다. CR·결정 파일은 크기와 수정 시각이 이전 읽기와 같으면 이전 결과를 씁니다(`project_board.model._cached`). 파일 목록은 그 디렉터리 트리(하위 디렉터리 포함)의 수정 시각이 이전 읽기와 같으면 이전 목록을 씁니다(`project_board.model._unchanged`, BOARD-013). 수정 시각이 방금(2초 안) 바뀐 디렉터리는 시계가 아직 넘어가지 않았을 수 있어 믿지 않고 다음 읽기에서 다시 읽습니다. `state.json`·실행 상태는 매번 읽습니다. 등록 파일은 크기·수정 시각·inode가 이전 읽기와 같으면 이전 결과를 쓰고(`model._registry`), 다르면 한 번 읽어 그 project 객체로 상태와 실행 상태를 읽으므로(`agent_session.api.project_state`·`project_liveness`) project마다 등록 파일을 다시 읽지 않습니다. 화면은 project마다 보이는 내용이 바뀐 project의 위젯만 다시 만듭니다(project 목록이나 순서가 바뀌면 전부). 접힌 project의 좌석과 Leader 시간은 보이지 않으므로 바뀌어도 다시 그리지 않습니다. 접힘 상태를 읽는 `tmux_control.expanded_projects`는 lock 없이 `show-options` 한 번입니다. Popup은 자기 project 하나만 읽습니다(`model.snapshot(project_id=…)`). 파일 조회와 `agent_session.api.liveness`처럼 대기할 수 있는 호출은 최대 2개의 조회 worker thread에서 실행합니다. 화면 갱신은 UI 이벤트 루프에서만 합니다. 이전 조회가 끝나지 않았으면 같은 조회를 중복 시작하지 않습니다. 새 배정의 session ID와 맞지 않는 실행 결과는 버립니다. 닫힌 popup이나 sidebar에 늦게 도착한 결과도 버립니다.

답변 알림의 `agent-session send`는 오래 걸릴 수 있습니다. Popup은 접수와 알림 중에도 화면과 스크롤이 멈추지 않게 이 동작을 백그라운드에서 실행합니다. 잠금 안에서 첫 답변만 접수하므로 다시 누르거나 다른 client에서 동시에 제출해도 중복 전송하지 않습니다.

## 3. Sidebar 화면

```text
Falcon2
D:2
O:2 T:1 I:1 ▸

ProjectB
D:1
O:0 T:3 I:0 ▾
R 0 GPU-007
  1 -
```

- 모든 등록 project를 하나의 목록에 순서대로 표시합니다. Project를 바꾸는 탭이나 필터를 두지 않습니다. 화면 높이가 부족하면 목록 전체를 세로로 스크롤합니다.
- 각 project는 이름, `D`, `O/T/I`와 좌석 버튼 순서로 표시합니다. 좌석은 기본으로 접습니다. `▸`와 `▾` 버튼으로 project별 좌석을 펼치거나 접습니다. 창 전환과 Board OFF/ON 뒤에도 상태를 유지합니다. 다른 Board pane에서 바꾼 상태는 다음 snapshot 갱신 때 반영합니다.
- `O/T/I`는 CR의 `open/todo/in-progress` 개수입니다. `D`는 열린 결정 항목 개수입니다. 두 종류를 합산하지 않습니다.
- 열린 결정 항목이 하나 이상이면 `D`를 빨간색으로 표시합니다. `D:0`, 미설정 `D:-`, 읽기 오류 `D:!`는 기존 노란색으로 표시합니다. `D:0`이어도 답변 접수·반영 중 항목이 있으면 popup을 열 수 있습니다. 표시 상태가 `완료`인 항목만 있으면 열지 않습니다.
- Seat 번호는 등록 순서의 0부터 시작합니다. 빈 seat는 번호 뒤에 `-`를 회색으로 표시합니다. 배정된 seat는 같은 행에 CR ID를 표시합니다. Worker session이 없는 배정은 `대기`를 붙여 시작 대기를 표시합니다. Worker가 종료했지만 CR이 in-progress라 반납하지 못한 seat는 `반납대기`를 붙입니다(`agent_session.api.pending_releases`). CR을 옮기면 사라집니다.
- 동작 시간(BOARD-008): session이 있는 Worker seat 행은 CR ID 뒤에 그 session이 게시된 뒤 지난 시간을 `??d ??h ??m`으로 붙입니다. 펼친 project의 첫 줄에는 Leader session이 있을 때 `Leader`와 같은 형식의 시간을 한 줄로 표시합니다. 기준은 state의 `connected_at`(명세 3절)이고, 지난 시간은 `snapshot`의 `elapsed`(초)입니다. 분 단위로 내림하고 0인 앞자리 단위는 생략합니다: `0m`, `12m`, `3h 05m`, `2d 01h 00m`(시와 분은 두 자리, 일은 자릿수 그대로). session이 없는 seat와 `connected_at`이 없는 이전 state는 시간을 표시하지 않습니다(Leader는 줄 자체를 두지 않습니다). 시간은 기존 snapshot 갱신(2초)에서 읽으며, 화면에 보이는 문자열(분)이 바뀔 때만, 그 project만 다시 그립니다(접힌 project는 시간이 보이지 않으므로 그리지 않습니다).
- SSH seat는 번호 뒤에 `@호스트`를 붙입니다. Tooltip은 호스트와 원격 경로를 표시합니다. 실행 관찰이 실패하면 확인 불가로 표시합니다. 등록과 실행 근거의 계약은 [Agent Session 명세](project-team/spec.md)가 소유합니다.
- `R`은 Leader의 `reviewing` 값이 그 seat의 CR ID와 같을 때만 붙입니다. Review 행을 별도로 만들거나 CR ID를 중복 표시하지 않습니다.
- 제출 후 검토 대기(`review_wait`)는 `R`이 아닙니다. 필요하면 행의 색과 도움말로 구분합니다.
- 지금 보는 창 강조(BOARD-009): sidebar가 보이는 client의 활성 window가 관리 window이면 그 project와 slot을 강조합니다. 관리 window는 window option으로 project ID와 target(`leader` 또는 `seat-N`)을 가집니다([명세 3절](project-team/spec.md#실행-근거와-잠금)).
  - 기준 window는 Board pane 자신의 window입니다(`tmux_control.active_context`가 `TMUX_PANE`으로 `agent_session.api.pane_slot`을 불러 읽습니다. option 이름과 `leader`·`seat-N` 문법은 agent-session이 소유하며 Board는 반환값 `(project_id, slot)`만 씁니다). Board pane은 window마다 하나이고 같은 window를 보는 client는 그 pane을 공유하므로, 그 sidebar를 보는 client의 활성 window는 항상 이 window입니다. client가 여럿이어도 client마다 판정하지 않으며, 다른 window를 보는 client는 그 window의 Board pane이 자기 window를 기준으로 강조합니다.
  - 강조 대상: project 이름 줄은 `▶ ` 표식과 파란 배경입니다. 좌석을 펼친 project에서는 그 slot의 줄(Leader 줄 또는 `target`의 seat 번호 줄)도 같은 파란 배경입니다. 접힌 project에서는 slot 줄이 없으므로 `▸` 버튼을 같은 배경으로 칠하고 도움말에 `현재 창: Leader` 또는 `현재 창: seat N`을 붙입니다. 좌석을 펼치거나 접는 상태(서버 option)는 강조 때문에 바꾸지 않습니다.
  - 강조하지 않는 경우: 관리 window가 아니거나(`pane_slot`이 None), 그 project가 등록 목록에 없거나, tmux 밖에서 실행한 경우. `target`이 `leader`·`seat-N`이 아니거나 그 seat 번호가 없으면 project만 강조합니다. Leader 줄은 Leader session이 게시된 때만 있으므로(위 동작 시간) 그 전에는 Leader slot의 줄이 없습니다.
  - 읽는 때: pane을 시작할 때, 창이 보이게 되어 SIGUSR1로 가시성을 다시 물을 때(창 이동 직후), 그리고 10초 실행 상태 읽기와 같은 주기입니다. 창을 바꾸면 이동한 window의 pane이 보이게 되는 그 읽기에서 곧바로 강조가 정해집니다. 2초 파일 읽기에는 tmux 호출을 넣지 않습니다. Board pane이 관리 window보다 먼저 만들어지는 경우(`window-created`) 관리 option은 10초 안에 반영됩니다. 읽기 실패와 보이지 않는 window는 이전 강조를 유지하며 읽지 않습니다. 강조가 바뀔 때만 다시 그립니다.
- `path_cr` 또는 `path_decide`가 없는 project는 해당 개수를 `-`로 표시합니다. 읽기 오류도 `0`으로 바꾸지 않습니다.
- 다시 그리기(BOARD-017): 글자·class·tooltip·disabled 값만 바뀌면 이미 mount한 widget에 그 값을 씁니다. widget을 다시 mount하지 않습니다. 행이 생기거나 없어지는 변경(펼치기·접기, Leader·seat·오류 행의 증감)과 project 목록의 변경(추가·삭제·순서·첫 그리기)은 Textual `App.batch_update()` 하나 안에서 적용합니다. 화면에는 변경 전이나 변경 후의 상태만 그려지고, 빈 목록·같은 project가 두 번 있는 목록·밀렸다 돌아오는 행은 그려지지 않습니다. 목록이 화면보다 길어지거나 짧아져 스크롤바가 생기고 없어질 때의 Textual 자체의 추가 layout 한 번은 이 규칙의 범위 밖입니다.
- 화면은 등록 순서를 유지합니다. 긴 project 이름과 CR ID는 tooltip과 가로 스크롤로 전체 값을 볼 수 있게 합니다.
- Tooltip은 pane이 focus를 잃으면(`AppBlur`) 곧바로, 그 밖에는 마지막 mouse motion 5초 뒤에 지웁니다(`SidebarApp.TOOLTIP_IDLE`). Mouse가 다른 pane으로 나가면 tmux는 이 pane에 아무 event도 보내지 않아 Textual이 tooltip을 지울 계기가 없습니다. 그래서 모든 경우에 tooltip이 남아 사용자가 따로 치울 일이 없게 시간으로 닫습니다. 5초는 표시 지연(0.5초) 뒤 가장 긴 tooltip(seat의 CR 제목·호스트·원격 경로)을 읽기에 충분하고, 움직이지 않는 mouse 때문에 오래 남지는 않는 값입니다. Motion이 이어지면 시간을 다시 잽니다. 닫은 tooltip은 mouse를 다시 움직여야 다시 뜹니다.

마우스 클릭은 필수 조작입니다. tmux 설정은 이미 `mouse on`입니다. Sidebar pane 안의 클릭과 휠은 TUI가 처리합니다. tmux 상태줄의 별도 `Board` 영역은 기존 session·cswap 클릭 동작을 유지하면서 sidebar toggle에 사용합니다.

| 클릭 대상 | 동작 |
| --- | --- |
| 상태줄 `Board` | 같은 tmux server의 모든 client에 sidebar 켜기·끄기 |
| Project 이름 | 클릭한 client를 해당 project tmux session의 현재 window로 이동. 대상 session이 없으면 오류 표시 |
| 각 project의 `O/T/I` | 클릭한 client에 해당 CR 목록과 선택한 CR의 전체 Markdown을 읽는 popup 열기 |
| 각 project의 `D` | 클릭한 client에 그 project의 결정 popup 열기 |
| 각 project의 좌석 버튼 | 해당 project의 좌석 목록을 펼치거나 접기 |
| Worker session이 있는 seat의 CR ID | 클릭한 client를 해당 Worker의 tmux window로 이동. 대상 window가 없으면 오류 표시 |
| 빈 seat 또는 시작 대기 seat | 이동하지 않음. Popup이나 오류 알림을 열지 않음 |

SSH seat의 Worker window는 Leader 호스트의 SSH 표시 창입니다. 이 창은 원격 tmux 화면을 표시합니다.
| Sidebar의 휠 | 모든 project가 들어 있는 목록 스크롤 |

위 클릭은 CR과 결정 항목의 상태를 바꾸지 않습니다. 키보드에서도 같은 화면을 열 수 있게 합니다.
`O/T/I`가 `0`, `-`, `!`이면 클릭해도 popup이나 오류 알림을 열지 않습니다. `D`는 표시 상태가 `완료`가 아닌 결정이 없거나 `-`, `!`일 때만 열지 않습니다.

CR popup은 왼쪽 목록에서 선택한 항목의 전체 Markdown 원본을 오른쪽에 표시합니다.
마우스로 CR 행을 클릭하거나 키보드로 행에 초점을 맞춘 뒤 Enter를 눌러 선택합니다.
CR·결정 popup의 너비가 70 column 미만이면 `목록` 버튼으로 목록과 본문을 전환합니다.
70 column 이상이면 목록과 본문을 함께 표시하고 `목록` 버튼을 숨깁니다.
넓은 화면으로 바뀌면 목록 전환 상태를 초기화합니다. 다시 좁아지면 선택 항목의 본문을 표시합니다.
선택 뒤 파일이 이동·삭제되거나 읽기에 실패하면 해당 항목의 오류를 표시합니다.
오류가 나도 popup은 열린 상태를 유지합니다.
원본 경로는 등록한 CR root의 해당 상태에서 열거한 항목으로 제한합니다.

#### Popup 목록 행과 선택 표시 (BOARD-007)

CR popup과 결정 popup의 왼쪽 목록은 같은 규칙을 씁니다(`tui._item_label`).

- 항목마다 한 줄입니다. 형식은 `표식 ID 상태 제목`이고 줄바꿈하지 않습니다. 칸보다 긴 줄은 끝을 `…`로 줄입니다. ID와 상태가 앞에 있으므로 줄어드는 것은 제목뿐입니다. 제목 전체는 오른쪽 본문 머리에서 읽습니다. 너비는 문자 폭(한글 2칸) 기준이며 칸 너비가 바뀌면 다시 줄입니다.
- 목록 칸은 popup 너비의 40%이고 30~46 column입니다. 80 column popup에서 결정 ID와 상태를 모두 보이게 하는 최소 폭입니다.
- 선택한 항목은 표식 `▶`, 파란 배경, 굵은 흰 글자입니다. 선택하지 않은 항목의 표식은 공백이고 어두운 배경입니다. 키보드 초점(Tab)이 선택하지 않은 항목에 있으면 밝은 회청색 배경으로 구별합니다. 선택과 초점은 서로 다른 표시입니다. 선택은 Enter나 클릭으로만 바뀝니다.
- 결정의 상태는 snapshot의 `display_state`를 줄인 말(`결정 대기`→`대기`, `답변 접수`→`접수`, `반영 중`→`반영`)이며 상태마다 색이 다릅니다(대기 노랑, 접수 하늘, 반영 초록). CR 목록은 popup이 상태 하나(`open`·`todo`·`in-progress`)의 목록이고 머리줄이 그 상태를 이미 표시하므로 행마다 반복하지 않습니다. 행에는 구별이 필요한 `review_wait`(아래)만 `검토`로 노랑으로 표시합니다.

`review_wait`의 판정 규칙은 [project-board README](../tools/project-board/README.md#review-wait)가 소유합니다. 제출 행의 문법은 [CR 계약](../skills/project-item/references/cr.md)이 소유합니다. 이 표시는 `R` 표시와 별개입니다.

## 4. 결정 popup

결정 popup은 터미널 너비와 높이의 90%를 사용합니다. 사용자가 다른 상태 정보를 보지 않아도 결정할 수 있게 구성합니다.

```text
┌ 결정 1/2 · D-20261106-07 ───────────────────────────┐
│ 결정 목록      │ 질문 · 긴급도 · 관련 CR             │
│ D-...          │ Background                          │
│ D-...          │ Options [넓은 표는 가로 스크롤]      │
│                │ Recommendation                     │
│                │ Evidence [접기/펼치기]              │
├─────────────────────────────────────────────────────┤
│ 답변: [여러 줄 입력]                     [전송]      │
└─────────────────────────────────────────────────────┘
```

1. 위쪽에 결정 ID, 질문, 긴급도, 막는 일, 관련 ID를 표시합니다.
2. 왼쪽에 표시 상태가 `완료`가 아닌 결정과 결정 대기·답변 접수·반영 중 상태를 표시합니다. 오른쪽에 선택한 결정의 본문을 넓게 표시합니다. 노출 기준은 snapshot의 `display_state != "완료"`입니다. Snapshot과 원본 Decision 파일은 완료 항목도 유지합니다. 선택 항목이 완료되면 남은 첫 항목으로 이동합니다. 남은 항목이 없으면 빈 목록과 본문을 표시하고 답변 입력·전송을 비활성화합니다. 좁은 화면에서는 3절의 `목록` 버튼으로 목록과 본문을 전환합니다.
3. 본문은 파일의 절 순서를 유지합니다. `Background`, `Options`, `Recommendation`, `Evidence`와 project가 추가한 절을 표시합니다. `Disposition`과 `Result`는 popup의 기본 보기에서 제외합니다. `Evidence`는 접을 수 있는 절로 제공합니다.
4. 본문에 제목, 문단, 목록, 인용, 코드 블록, 링크와 Markdown 표를 표시합니다. 넓은 표는 가로로 스크롤합니다. `csv` 코드 블록이나 결정 항목에서 가리키는 같은 project 아래의 로컬 CSV 파일은 별도 표 보기로 엽니다. 외부 URL의 CSV는 자동으로 받지 않습니다.
5. 아래쪽에 답변 입력란과 접수·알림 결과를 둡니다. 답변은 여러 줄을 지원합니다. `open`인 결정만 입력과 전송을 허용합니다. 접수한 답변 원문은 Decision에 보존합니다.
6. 전송 호출자가 `agent_session.api.caller(project)`에서 `operator`가 아니면 접수를 거절합니다. 접수 후 Leader가 없거나 `stopped`인 경우와 알림 실패·결과 불명은 접수 상태와 함께 표시합니다. 사용자는 같은 답변을 다시 입력하지 않습니다.

결정 목록, 접기/펼치기, 본문 스크롤, 답변 입력란, 전송 버튼을 마우스로 조작할 수 있게 합니다. 키보드 조작도 제공합니다.

[`project_board.model`](../tools/project-board/project_board/model.py)은 [`project_item.render.sections()`](../tools/project-item/project_item/render.py)의 Markdown 원문을 `{name, body}`로 제공합니다. `Evidence`를 포함한 전체 본문을 TUI가 읽습니다. 답변 검증·문구·전송 결과 처리는 [`project_board.answer`](../tools/project-board/project_board/answer.py)가 소유합니다. 결정 파일을 `done`으로 옮기는 일은 계속 Leader가 맡습니다.

TUI는 Textual 8.2.8의 [Markdown](https://textual.textualize.io/widgets/markdown/)과 [DataTable](https://textual.textualize.io/widgets/data_table/)을 사용합니다. 버전 원본은 [`requirements.txt`](../tools/project-board/requirements.txt)입니다. macOS의 `~/python/.venv`에는 설치했습니다. WSL과 Workstation에서 실행할 때는 해당 환경의 패키지 가용성을 확인합니다. Workstation에 패키지가 없으면 사용자에게 설치를 요청합니다.

## 5. tmux 표시 범위와 동작

사용자가 선택한 표시 범위는 **모든 tmux client 공통**입니다. Sidebar 내용은 항상 모든 등록 project입니다. 사용자가 어느 client에서 켜거나 끄든 같은 tmux server의 client에 적용합니다. 각 client가 session과 window를 바꿔도 같은 전체 목록을 볼 수 있어야 합니다. tmux pane은 window에 속하므로, client가 현재 보는 window를 추적하는 controller가 필요합니다.

tmux `next-3.9`의 전체 높이 일반 pane을 사용합니다. Controller는 전역 `@project_board_enabled` 옵션을 관리합니다. Sidebar가 켜지면 client가 처음 보는 window마다 왼쪽 25 column을 Board pane에 할당합니다. 사용자가 Board pane의 폭을 조정하면 다음 window에서 Board pane을 만들 때 실제 폭을 적용합니다. 창 크기나 다른 pane의 최소 폭 때문에 Board pane 폭이 제한되어도 저장한 폭은 유지합니다. 충분한 공간이 있는 window로 돌아오면 저장한 폭을 다시 적용합니다. 폭은 tmux pane과 서버 option에 유지합니다. 기존 pane은 오른쪽의 남은 공간에 표시합니다. 같은 window를 보는 client는 Board pane을 공유합니다. 마지막 client가 다른 window로 이동해도 Board pane은 그 window에 남습니다. 돌아온 client는 이미 떠 있는 pane을 봅니다(이전에는 이동마다 pane을 지우고 새 TUI 프로세스를 만들어 수 초가 걸렸습니다). 아직 보지 않은 window에는 만들지 않습니다. 유지하는 pane은 8개까지이고(`tmux_control.MAX_KEPT`) 더 만들 때는 어느 client도 보지 않는 window 중 가장 오래전에 보인 window의 pane을 제거합니다. 8은 Board process 하나의 RSS 약 50 MB(최대 약 400 MB)와 보이지 않는 pane의 CPU 0을 실측해 정했습니다. 근거 수치는 BOARD-002 Result에 있습니다. Board pane은 Board를 끌 때, 그 window의 관리 pane이 끝났을 때, 또는 pane이 스스로 끝났을 때 제거합니다. Controller는 Board를 만들기 전의 pane 배치와 선택 pane을 저장합니다. Board를 끄거나 window에서 제거하면 기존 pane의 배치, 크기, 선택 상태를 복원합니다.

tmux hook은 client 연결·이동·분리와 window 생성·종료를 관찰합니다. Hook은 `sync`를 시작할 일이 있을 때만 시작합니다. 시작 조건은 tmux format(`@project_agent_sync_needed`)이며 "Board가 켜져 있고 이 window의 Board pane이 없거나 저장한 폭이 아님"입니다. 이미 Board pane이 있는 window로 옮긴 hook은 프로세스를 시작하지 않습니다. 조건이 참이면 Controller는 보이는 window와 Board pane을 동기화합니다. 관리된 `agent-session` pane이 종료되면 Board pane도 먼저 제거해 종료 window의 정리를 방해하지 않습니다. 이 구조에는 별도의 서버나 상주 감시 프로세스가 없습니다.

상태줄 `Board`와 prefix `B`는 전역 toggle을 실행합니다. 일반 pane의 클릭은 tmux에 전달합니다. Board pane의 클릭은 tmux binding이 클릭한 client 이름, pane ID, 좌표를 Unix socket으로 TUI에 전달합니다. 따라서 같은 Board pane을 공유하는 client도 자신의 popup을 열거나 자신의 window를 이동합니다. 결정 popup은 90%, CR popup은 80% 크기로 해당 client에 엽니다.

## 6. 구현 단위와 완료 기준

| 순서 | 구현 단위 | 관찰 가능한 완료 기준 |
| --- | --- | --- |
| 1 | 격리 tmux 실험과 표시 범위 확정 | 5절의 이동·토글·다중 client·관리 window 사례를 재현하고 방식 하나를 선택 |
| 2 | Board 읽기·답변 경로 | 모델이 Markdown 원문을 제공함. 답변 검증·전송이 HTTP 없이 동작함 |
| 3 | TUI Sidebar | 모든 project가 한 목록에 표시됨. 3절의 개수, 빈 seat, 단일 `R` 행, 오류와 마우스 스크롤·클릭이 동작함 |
| 4 | 결정 popup | 실제 결정 문서의 Markdown·표·CSV를 읽고 마우스로 목록·본문·답변·전송을 조작함 |
| 5 | tmux 토글과 설치 진입점 | 같은 키 또는 상태줄 `Board` 클릭으로 켜고 끔. Board가 왼쪽 공간을 차지함. 종료 시 Board 소유 pane만 정리하고 기존 pane의 배치, 크기, 포커스를 복원 |
| 6 | HTML server 제거 | `project-board`가 TUI를 시작함. `server.py`, `static/board.html`, HTTP 전용 테스트·옵션을 제거하고 README와 현행 계획을 갱신함 |

`project-board` 테스트 61건과 `project-item` 테스트 83건이 통과했습니다. 실제 tmux 화면에서 두 project의 개수와 seat, 결정 Markdown 표와 CSV 표를 확인했습니다. 두 client의 다른 window에 같은 전체 목록이 표시됐습니다. 마우스 클릭은 해당 client의 CR popup을 열었고, seat 클릭은 해당 client만 Worker window로 이동했습니다. 느린 조회 중 클릭과 중복 조회 방지도 TUI 테스트로 확인했습니다. 실제 사용 중인 tmux server에는 테스트 동작을 적용하지 않았습니다.

tmux popup을 열어 둔 상태에서 외부 명령으로 client의 window를 바꾸면 popup 프로세스는 기존 window에 남습니다. Popup에서 `Esc`나 닫기 버튼으로 종료합니다. 이번 구현은 사용 중인 popup을 창 이동 시 강제로 닫지 않습니다.

관리된 pane이 종료된 뒤 같은 window에서 곧바로 `respawn-pane`되면 Board는 다음 client·window 동기화 때 다시 나타납니다. 즉시 갱신하려면 `project-board sync`를 실행합니다. tmux `next-3.9`에는 `after-respawn-pane` hook이 없습니다.

## 7. 확정한 선택

1. **Sidebar 범위:** 모든 tmux client가 같은 toggle 상태와 전체 project 목록을 봅니다. 같은 window를 보는 client는 화면도 공유합니다.
2. **CSV 범위:** `csv` 코드 블록과 같은 project 안의 로컬 CSV 링크를 표로 봅니다. 외부 URL의 CSV는 자동으로 받지 않습니다.
3. **실행 구조:** HTML server는 제거합니다. Sidebar는 표시 중인 tmux window당 하나의 TUI 프로세스입니다. Popup은 열려 있는 동안만 실행합니다.
