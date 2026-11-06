# Project Board 계획

등록된 모든 project의 팀 상황을 한 화면에 보여 주는 local HTML server입니다.
화면 시안은 [project-board-mockup.html](project-board-mockup.html)입니다. 시안의 값은 예시 데이터입니다.

## 1. 목표

- 등록된 모든 project의 Leader·Worker·seat·CR·결정 대기를 한 화면에 보여 줍니다.
- 사용자가 처리할 결정 대기 항목을 바로 찾게 합니다.
- 결정 항목의 답변을 board에서 해당 project Leader에게 보냅니다.

## 2. 범위

포함합니다.

- 읽기: project 등록, `state.json`, CR·결정 항목 파일
- 쓰기: 결정 답변을 Leader에게 전송하는 것 하나

포함하지 않습니다.

- CR·결정 항목 파일의 이동과 편집. 항목을 옮기는 주체는 Leader입니다([project-item](../codex/skills/project-item/SKILL.md)).
- `state.json`의 쓰기. `agent-session`만 씁니다.
- Done CR의 목록과 개수. 시간이 지나면 계속 늘어나고, 지금 할 일과 관계가 없습니다.

## 3. 데이터 원본

Board는 원본을 복사하지 않습니다. 요청마다 아래 파일을 읽습니다.

| 원본 | 위치 | 얻는 정보 |
| --- | --- | --- |
| Project 등록 | `~/.codex/project.json`, `~/.claude/project.json` | project 목록, provider, seat 수, `path_cr`·`path_decide` |
| 배정·연결 | `<base>/agent/state.json` | seat별 JOB, session, `connected_at`, `leader.reviewing` |
| CR 상태 | `path_cr`의 `open/`·`todo/`·`in-progress/` 파일 이름 | 화이트보드 숫자, CR 목록 |
| CR 본문 | `in-progress/`의 CR 파일 | 제목, `- Base:` header, `## Result`, `## Disposition` |
| 결정 대기 | `path_decide`의 `open/` 파일 | 결정 대기 숫자, 질문 본문(Evidence·Disposition·Result를 뺀 비어 있지 않은 절을 파일 순서대로, project가 더한 절 포함) |

- 등록 파일은 `agent_session.config.load_registry`로 읽습니다. 두 표준 경로 가운데 어느 파일을 쓰는지는 [spec 2절](project-team/spec.md#2-등록과-프로젝트-선택)의 선택 규칙을 따릅니다.
- 등록에 `path_cr` 또는 `path_decide`가 없는 project는 그 종류를 쓰지 않습니다. 화이트보드에 해당 숫자를 표시하지 않습니다.
- `state.json`은 `agent_session.api.read_state`로 읽습니다. `agent-session`과 같은 형식 검사를 재사용합니다.
- `state.json`은 lock 없이 읽습니다. `agent-session`이 임시 파일에 쓴 뒤 `os.replace`로 교체하므로 반쯤 쓰인 파일을 읽지 않습니다.

## 4. 화면

### 4.1 구성

- 위에서 내려다본 사무실 평면도입니다. 자리는 직사각형, 사람은 원입니다.
- Project 하나가 방 하나입니다. 방은 2열로 놓입니다. 순서는 등록 순서이고 왼쪽→오른쪽, 위→아래로 읽습니다. 화면 너비가 1180px보다 좁으면 1열로 쌓입니다.
- 방 안의 배치는 왼쪽부터 화이트보드, Leader, Leader 책상, seat 순서입니다. Leader는 seat 쪽을 바라봅니다.
- 방 머리에는 project 이름, base 경로, provider를 씁니다. Leader 상태와 seat 수는 평면도가 보여 주므로 머리에 쓰지 않습니다.

### 4.2 요소

| 요소 | 모양 | 내용 |
| --- | --- | --- |
| Seat 책상 | 72×44 직사각형. 위쪽 막대는 모니터입니다. | CR ID, session 시간 |
| Leader 책상 | 48×64 세로 직사각형. 오른쪽 막대는 모니터입니다. | session 시간(단위별로 세로 배치) |
| Worker | 지름 24px 원 | 상태별 모양은 4.3절 |
| Leader | 지름 28px 동심원 | 상태별 위치는 4.3절 |
| 화이트보드 | Leader 뒤 벽의 버튼 2개 | 결정 대기 수, CR `open`·`todo`·진행 수 |
| 선택 영역 | 책상과 Worker를 감싸는 76×92 사각형 | 배정된 seat만 누를 수 있습니다. |

Session 시간은 `connected_at`부터 지금까지의 경과 시간입니다.

- 형식은 `1d 4h 12m`입니다. 크기는 9.5px, 색은 회색입니다.
- 앞쪽의 0인 단위는 생략합니다. 분 단위는 항상 씁니다. 예: `3h 5m`, `48m`.
- Session이 없는 자리에는 시간을 쓰지 않습니다.
- `connected_at`이 없는 기존 session은 시간 대신 `?`를 씁니다. 현재 시각으로 추정하지 않습니다.
- Restart하면 session이 새로 만들어지므로 시간도 0부터 다시 셉니다.

### 4.3 상태 판정

| 화면 상태 | 판정 | 표현 |
| --- | --- | --- |
| 빈 seat | `job_id`가 `null` | 흐린 책상만 있음 |
| 연결 전 | `job_id` 있음, `session`이 `null` | 책상에 CR ID, 점선 원 |
| 작업 중 | `session` 있음, review 대기 아님 | 채운 파란 원, 모니터 점 3개 |
| Review 대기 | `session` 있음, review 대기 규칙(7절 1번)을 만족함 | 속 빈 파란 원, 움직임 없음 |
| Review 중 | `leader.reviewing`이 이 seat의 `job_id` | Review 대기 표현에 더해, Leader가 Worker 바로 옆에 섬 |
| 멈춤 | `session` 있음, 실행 확인(7절 2번) 결과가 `stopped` 또는 `unknown` | 회색 원, 움직임 없음, label에 `멈춤` 또는 `확인 불가` |
| Leader 작업 중 | `leader` 있음, `reviewing`이 `null` | 자기 자리에 동심원 |
| Leader 멈춤 | `leader` 있음, 실행 확인 결과가 `stopped` 또는 `unknown` | 회색 동심원, 움직임 없음 |
| Leader 부재 | `leader`가 `null` | 자기 자리에 점선 원, 시간 없음 |

- 판정 순서는 멈춤, Review 중, Review 대기, 작업 중입니다. 앞의 조건이 맞으면 뒤의 조건은 보지 않습니다.
- Leader는 실제로 review 중인 seat에만 섭니다. Review 대기 seat가 여러 개여도 Leader는 한 곳에만 있습니다.
- Leader가 seat로 가 있는 동안 자기 자리에는 점선 원이 남고, 그 아래에 `leader → seatN`이라고 씁니다.
- Session이 종료되면 Worker 원은 바로 사라집니다.
- 실행 확인 결과가 아직 없으면 파일만으로 판정합니다.

### 4.4 색

| 색 | 값 | 용도 |
| --- | --- | --- |
| 파랑 | `#2563EB` | 작업 중인 Worker, 모니터 점 |
| 주황 | `#B4410E`, 배경 `#FFF3EB` | 결정 대기에만 사용합니다. |
| 검정 | `#1D2330` | Leader |
| 옅은 파랑 | `#EAF1FE`, 테두리 `#A9C2F5` | 선택 영역 |

### 4.5 움직임

- 작업 중인 Worker는 위아래로 2px 움직입니다. 모니터의 점 3개가 차례로 깜빡입니다.
- 작업 중인 Leader는 좌우로 2px 움직입니다. Review 중에도 같습니다.
- 상태가 바뀔 때 이동·등장·퇴장 animation은 없습니다. 원은 새 위치에 바로 나타나고 바로 사라집니다.
- 펼침 영역은 열고 닫을 때 높이가 부드럽게 바뀝니다.
- 움직임은 OS의 움직임 줄이기 설정(`prefers-reduced-motion`)과 관계없이 항상 보입니다. 움직임이 작업 상태를 나타내기 때문입니다. 처음에는 이 설정을 따라 모든 움직임을 껐습니다. 그러다 Windows의 애니메이션 효과가 꺼진 환경에서 board 전체가 멈춰 보였고, 2026-11-05 사용자 결정으로 바꿨습니다.

### 4.6 상호작용

1. 화이트보드의 결정 버튼을 누르면 그 project 아래에 결정 대기 목록이 펼쳐집니다. 아래 project들은 밀려납니다.
2. 화이트보드의 CR 버튼을 누르면 `open`·`todo`·`in-progress` CR 목록이 펼쳐집니다.
3. 선택 영역을 누르면 그 seat의 CR이 펼쳐집니다. 상태, session 시간, branch(`cr/<ID>`), Base, Result, 본문 요약을 보여 줍니다.
4. 같은 버튼을 다시 누르거나 닫기를 누르면 펼침이 닫힙니다.
5. 결정 항목에 답변을 쓰고 전송 버튼을 누르면 6.2절에 따라 Leader에게 보냅니다.

## 5. `state.json` 보완

현재 `state.json`에는 session 시작 시각과 Leader의 review 대상이 없습니다. 필드 두 개를 추가합니다.

```json
{
  "leader": {
    "session_id": "…", "endpoint": "…",
    "connected_at": "2026-11-04T09:12:30Z",
    "reviewing": "TOOL-013"
  },
  "1": {
    "job_id": "TOOL-013", "git_hash": "…",
    "session": { "session_id": "…", "endpoint": "…", "connected_at": "2026-11-04T04:20:02Z" }
  }
}
```

| 필드 | 위치 | 값 | 쓰는 시점 |
| --- | --- | --- | --- |
| `connected_at` | 모든 session 객체 | UTC ISO 8601 시각 | `agent-session`이 연결을 확정하고 session을 `state.json`에 기록할 때 |
| `reviewing` | `leader` 객체 | CR ID 또는 `null` | Leader가 review를 시작할 때 |

`reviewing`은 `leader` 객체에만 둡니다. 따라서 Leader가 동시에 두 곳을 review하는 상태는 만들 수 없습니다.

### 5.1 `reviewing` 설정과 해제

1. 설정: Leader가 `agent-session review --job <CR-ID>`를 실행합니다. 그 JOB이 seat에 배정되어 있고 session이 있어야 합니다. 다른 JOB을 review 중이면 새 JOB으로 바뀝니다.
2. 명시 해제: Leader가 `agent-session review --clear`를 실행합니다.
3. 자동 해제: 다음 명령은 `reviewing`이 그 JOB을 가리킬 때만 같은 상태 저장 단계에서 지웁니다.
    - Leader가 review 중인 JOB에 feedback을 보냄(`send --job <CR-ID>`)
    - Review 중인 JOB을 종료함(`stop --job <CR-ID>`)
    - Leader가 restart하거나 종료됨. `leader` 객체가 바뀌거나 `null`이 됩니다.

### 5.2 바꿔야 하는 곳

`state.json`의 형식 검사는 key 집합이 정확히 일치해야 통과합니다. 필드를 추가하려면 다음을 함께 바꿉니다.

| 대상 | 변경 |
| --- | --- |
| [동작 명세](project-team/spec.md) 3절, [상태 예제](project-team/state.example.json) | 두 필드의 의미와 쓰는 시점 |
| `codex/tools/agent-session/agent_session/state.py` | 새 필드 검사. 저장된 `reviewing`은 현재 배정된 JOB 또는 `null`입니다. Seat session이 있어야 한다는 조건은 설정할 때만 검사합니다. |
| `codex/tools/agent-session/agent_session/lifecycle.py` | `connected_at` 기록, `review` 명령, send·stop의 자동 해제 |
| [project-team skill](../codex/skills/project-team/SKILL.md) Leader 5단계 | Review를 시작할 때 `agent-session review --job`을 실행합니다. |
| `codex/tools/agent-session/tests/` | 설정, 교체, 명시 해제, 자동 해제, 잘못된 대상 거절의 회귀 test |

## 6. Server 동작

### 6.1 읽기

- Server는 상태를 저장하지 않습니다.
- 브라우저는 2초마다 server에 현재 상태를 요청합니다. Server는 요청을 받을 때마다 3절의 파일을 새로 읽어 응답합니다.
- 브라우저는 10초마다 실행 확인(7절 2번)을 따로 요청합니다. 실행 확인은 tmux와 process를 조회하므로 파일 읽기보다 느립니다.
- `agent-session`은 server에 알리지 않습니다. Board에 필요한 변화의 대부분(`## Result` 작성, `project-item move`, 새 결정 항목)은 `agent-session`을 거치지 않기 때문입니다.
- Server가 꺼져 있어도 복구할 것이 없습니다. 켜지면 그때의 파일을 읽어 현재 상태를 보여 줍니다. 경과 시간은 `connected_at`에서 계산하므로 꺼져 있던 시간도 정확합니다.
- 한 project의 파일을 읽지 못하면 그 방에만 오류를 표시합니다. 다른 project는 계속 보여 줍니다.

### 6.2 결정 답변 전송

1. Server가 `agent-session send --job leader`를 실행해 답변을 보냅니다. 전송 방식은 다시 구현하지 않습니다.
2. 메시지 본문의 첫 줄은 `결정 답변: <결정 ID>`입니다. 그 아래에 project와 사용자가 입력한 답변 원문을 넣습니다.
3. Server는 결정 항목 파일을 옮기거나 고치지 않습니다. Leader가 답을 받아 [결정 항목 절차](../codex/skills/project-item/references/decide.md)에 따라 done으로 옮깁니다.
4. `leader`가 `null`이거나 실행 확인 결과가 `stopped`이면 전송 버튼을 비활성화합니다(7절 4번).
5. 전송에 실패하면 오류를 보여 주고, 입력한 답변을 그대로 둡니다. `agent-session`이 끝나지 않았거나 결과를 돌려주지 않았으면 `send_unconfirmed`로 구분하고, Leader에서 받았는지 확인한 뒤 다시 보내라고 씁니다. 자동으로 다시 보내지 않습니다.
6. 2초마다 화면을 다시 그려도 입력 중인 답변은 지우지 않습니다. 전송이 성공하면 보낸 답변만 지웁니다. 응답을 기다리는 동안 고친 내용은 보내지 않은 초안으로 남깁니다.

Server는 사용자가 자기 terminal에서 실행합니다. 관리 밖 agent session(예: 사용자의 Claude Code) 안에서 실행하면 `agent-session`이 전송을 거절합니다(`caller_unbound`). 등록된 Leader·Worker 안에서 실행하면 동료 메시지로 전달되며, 동료 메시지는 결정 승인이 아닙니다. 어느 경우든 agent가 사용자 답변을 대신 보내지 못합니다.

### 6.3 보안

> **경고:** 전송 대상 agent는 `--dangerously-bypass-approvals-and-sandbox`로 실행될 수 있습니다. Server를 외부에 열면 다른 사람이 agent에게 지시를 넣을 수 있습니다.

- Server는 `127.0.0.1`에만 bind합니다.
- 다른 web site가 사용자의 browser를 통해 전송 요청을 보내지 못하게 합니다.
    - Server는 시작할 때 임의의 token을 만들고 board page에만 넣습니다. 전송 요청은 `X-Board-Token` header에 이 token이 있어야 합니다.
    - 전송 요청의 본문은 JSON이어야 합니다. `Host`는 `127.0.0.1:<port>` 또는 `localhost:<port>`여야 합니다. `Origin`이 있으면 같은 주소여야 합니다.
- 같은 머신의 다른 process는 막지 않습니다. 그 process는 `agent-session`을 직접 실행할 수도 있습니다.

## 7. 결정 사항

처음의 미결 사항 5개와 구현 중 발견한 1개를 아래와 같이 정했습니다.

### 7.1 Review 대기 판정

Worker가 제출했고 Leader가 아직 그 제출에 답하지 않았으면 review 대기입니다. 제출과 응답은 CR 파일로 판정합니다.

- Write CR의 Worker는 제출할 때마다 `## Result`에 들여쓰지 않은 제출 행 `- 제출 commit: <40자리 hash>`를 씁니다. 제출 hash는 마지막 제출 행의 hash입니다. Result의 다른 hash(검증 명령, 비교 기준, Base)와 들여쓴 행, code fence(들여쓴 fence 포함) 안의 행은 제출로 보지 않습니다.
- `## Disposition`에 제출 hash가 없으면 review 대기입니다. 앞 7자리 이상만 적어도 인용으로 봅니다.
- Leader는 review 결과(인수 또는 수정 요청)를 Disposition에 쓸 때 검토한 제출 hash를 함께 적습니다. Worker가 새 hash를 제출하면 다시 review 대기가 됩니다.
- Read-only CR(`- Mode: read-only`)은 commit이 없습니다. `## Result`에 내용이 있으면 review 대기입니다.
- CR 파일이 `in-progress/`에 없으면 review 대기가 아닙니다.

처음 제안(Result와 Disposition 항목의 날짜 비교)은 쓰지 않습니다. 두 절의 항목에는 날짜만 있어서 같은 날의 제출과 응답의 순서를 알 수 없습니다.

알려진 한계: Read-only CR에 Leader가 수정을 요청하면, Leader가 CR을 옮길 때까지 review 대기로 보입니다.

이 규칙에 맞춰 [CR 계약](../codex/skills/project-item/references/cr.md)의 "JOB으로 쓸 때"와 [project-team skill](../codex/skills/project-team/SKILL.md)에 두 기록 규칙(Result의 제출 행, Disposition의 hash 인용)을 추가합니다. 처음 안(Result의 마지막 40자리 hash)은 검증 기록에 다른 hash가 뒤따르면 잘못 고르므로 쓰지 않습니다(Codex 검토 B1).

### 7.2 멈춘 session 표시

`agent_session.api.liveness()`를 추가합니다. Session이 있는 slot마다 판정한 `session_id`와 다음 셋 중 하나를 돌려줍니다.

| 값 | 판정 |
| --- | --- |
| `alive` | 현재 실행 pointer의 session이 `state.json`의 session과 같고, pane과 CLI process가 살아 있음 |
| `stopped` | 위 실행의 pane이 종료되었거나 CLI process가 없음 |
| `unknown` | 현재 실행 pointer가 없거나, 다른 session을 가리키거나, 조회가 실패함 |

- Provider는 호출하지 않습니다. 기존 `check_binding`은 provider를 호출합니다. Claude provider는 확인마다 `claude mcp serve` process를 띄우므로 주기적 조회에 쓰지 않습니다.
- `active_turn`은 쓰지 않습니다. Provider 호출이 필요하기 때문입니다.
- CLI process 판정은 `check_binding`과 같은 helper를 씁니다.
- 파일 조회(2초)와 실행 확인(10초)은 따로 갱신됩니다. 화면은 실행 확인 결과의 `session_id`가 현재 `state.json`의 session과 다르면 그 결과를 버립니다. 새 Leader에 옛 Leader의 멈춤 표시가 남지 않습니다.
- 실행 확인은 화면 표시용입니다. Stop·반납의 종료 확인을 대신하지 않습니다.

### 7.3 Project가 많을 때의 배치

- 할 일이 없는 project는 머리 한 줄로 접습니다. 할 일이 없다는 것은 다음을 모두 만족하는 경우입니다: Leader 없음, 배정된 seat 없음, 결정 대기 0, CR `open`·`todo`·`in-progress` 0.
- 접힌 방의 머리를 누르면 평면도가 펼쳐집니다.
- Project 순서는 등록 순서입니다. 상태에 따라 순서를 바꾸지 않습니다. 위치가 바뀌지 않아야 찾기 쉽습니다.
- 평면도의 너비는 seat 4개 기준으로 고정합니다(520px). Seat 수에 따라 방의 너비가 변하지 않으며 평면도에는 가로 scroll이 없습니다.
- Seat는 한 줄에 4개씩 놓습니다. 1~4개는 1줄, 5~8개는 2줄, 9~12개는 3줄이고 줄이 늘면 평면도의 높이만 늘어납니다.
- 책상은 등록된 seat 수만큼만 그립니다. 4개보다 적으면 남는 자리는 비워 두고 빈 책상을 그리지 않습니다.

### 7.4 Leader 부재 시 결정 화면

- 답변 입력란은 계속 쓸 수 있습니다.
- 전송 버튼은 비활성이고 `Leader 없음`이라고 씁니다. 버튼 옆에 `Leader가 연결되면 보낼 수 있습니다.`라고 씁니다.
- Leader의 실행 확인 결과가 `stopped`이면 같은 방식으로 `Leader 멈춤`이라고 씁니다.

### 7.5 구현 방식

| 항목 | 결정 |
| --- | --- |
| 언어 | Python 표준 library(`http.server`). 외부 package를 쓰지 않습니다. |
| 위치 | `codex/tools/project-board/`. 다른 공통 도구와 같은 구조(`bin/`, package, `tests/`)입니다. |
| 재사용 | 등록·`state.json`·실행 확인은 `agent_session.api`, CR·결정 항목 파일 해석은 `project_item`을 씁니다. |
| 실행 | `project-board [--port PORT] [--config PATH]` |
| Port | 기본 8765 |
| 화면 | Page 하나와 JSON API. 화면 코드는 시안의 구조와 CSS를 그대로 씁니다. |

### 7.6 Board 답변의 승인 효력 (구현 중 발견)

[결정 항목 절차](../codex/skills/project-item/references/decide.md)는 사용자가 담당 session에 직접 입력한 답만 승인으로 인정합니다. 그런데 `agent-session send`는 모든 발신자의 메시지 앞에 "동료 메시지입니다. 사용자 승인으로 사용하지 마십시오."를 붙입니다. 그대로 두면 Leader는 board 답변으로 결정 항목을 옮길 수 없습니다.

정한 내용:

- `agent-session`은 operator 발신(관리 session과 식별된 agent가 아닌 발신 process)의 첫 줄을 `로컬 operator 입력입니다.`로 바꿉니다. Leader·Worker 발신은 지금처럼 동료 메시지로 표시합니다. Operator는 사람 인증이 아니라 process 분류입니다. 같은 머신의 process를 신뢰한다는 전제입니다.
- 결정 항목 절차의 승인에 "operator 발신으로 받은 `결정 답변: <ID>` 메시지"를 추가합니다.
- Codex·Claude Code agent는 operator로 판정되지 않습니다. `agent-session`은 `CODEX_THREAD_ID`·`CLAUDE_CODE_SESSION_ID`·관리 tmux pane으로 agent를 가려냅니다. 관리 밖 agent의 전송은 `caller_unbound`로 거절합니다. 등록된 Leader·Worker의 전송은 동료 메시지입니다.
- Token·`Host`·`Origin` 검사(6.3)는 browser를 통한 요청 위조를 막는 경계입니다. 사람 인증이 아닙니다.
- 남는 위험: 이 환경 변수를 일부러 지운 process는 operator로 판정됩니다. 그런 process는 `tmux send-keys`로 Leader 화면에 직접 입력할 수도 있으므로 이 변경으로 새로 생기는 위험은 아닙니다.

## 8. 진행 순서

1. 5절의 `agent-session` 변경 계획을 Codex에게 review받습니다. (완료)
2. `agent-session` 변경을 구현하고 회귀 test로 검증합니다. (완료)
3. 7절의 미결 사항을 정합니다. (완료)
4. Board server를 구현하고, 시안과 실제 화면을 대조해 인수합니다. (구현: [`codex/tools/project-board`](../codex/tools/project-board/README.md), 실행: `project-board`)
