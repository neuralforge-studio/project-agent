# Agent Session 동작 명세 v1

공개 CLI는 `agent-session` 하나입니다.
공개 명령은 start·send·stop·restart·review·shutdown·resume·watch입니다.
공통 도구는 프로젝트 코드를 import하거나 실행하지 않습니다.
프로젝트별 차이는 등록(2절)과 프로젝트 문서·CR 본문으로만 표현합니다.

## 1. 명령과 대상

```sh
agent-session start --job leader
agent-session start --job TOOL-012
agent-session start --job TOOL-012 --seat 3
agent-session send --job leader "작업 결과를 보고합니다."
agent-session send --job TOOL-012 --file FEEDBACK.md
agent-session send --project other --job leader "협업 요청입니다."
agent-session stop --seat 1
agent-session restart --job leader
agent-session review --job TOOL-012
agent-session review --clear
agent-session shutdown --all
agent-session shutdown --project agent --timeout 300 --force
agent-session resume --all
agent-session watch --all
```

Start는 --job이 필수입니다. Worker의 --seat N은 선택이며 지정한 자리만 검사합니다.
Leader의 start는 --seat를 받지 않습니다.
Review는 --job과 --clear 중 정확히 하나가 필수입니다(7절 Review).
Shutdown·resume·watch는 --project와 --all 중 정확히 하나가 필수입니다(7절 shutdown·resume, watch).
나머지 대상 지정 명령은 --job과 --seat 중 정확히 하나가 필수입니다.
둘 다 입력하면 같은 대상을 가리켜도 오류입니다.
Leader는 등록 base에서 시작합니다.
Worker는 기본 자동 배정 또는 --seat로 지정한 seat에서 시작합니다.
JOB의 하위 작업 경로 기본은 seat 자체입니다.
작업 디렉토리·provider·run 값을 사용자가 다시 입력하지 않습니다.

Seat는 등록된 고정 작업 디렉토리이며 JOB이 끝나도 삭제하지 않습니다.
배정할 seat 디렉토리가 없으면 start가 만듭니다(4절).
배정 변경은 같은 seat에 연결한 JOB이 바뀌는 것입니다.
같은 JOB의 feedback은 같은 session에 send합니다.
작업 완료 보고만으로 session을 자동 종료하거나 배정을 비우지 않습니다.
Leader가 stop으로 종료·반납한 뒤 새 JOB을 start하면 새 session을 만듭니다.
모든 restart는 기존 실행을 종료하고 새 대화로 교체합니다.
Seat·JOB·Git 기준·branch는 유지하며 이전 대화를 재개하지 않습니다.
이전 대화를 같은 ID로 다시 여는 명령은 resume 하나뿐입니다(7절 shutdown·resume).
이전 대화 기록은 보존합니다.
새 대화는 인계 문서와 현재 JOB으로 이전 작업을 이어받습니다.

JOB은 CR(Change Request) 파일입니다. JOB ID는 CR ID(`<AREA>-<NNN>`)입니다.
모든 명령의 --job 값은 leader 또는 CR ID입니다. 파일 경로는 받지 않습니다.
CR 파일은 등록의 path_cr에서 project-item 형식으로 찾습니다.
특수 값 leader는 대소문자를 구분합니다.

JOB ID는 현재 state에서 정확히 한 seat를 찾아 지정합니다.
미배정·반납한 ID는 job_not_assigned 오류입니다.
여러 seat에서 같은 ID를 찾으면 상태 오류이며 임의로 고르지 않습니다.
Seat 방식도 선택 시점의 JOB ID와 실행을 확정한 뒤 제어 직전에 다시 대조합니다.
대상 확인과 제어는 해당 자리의 시작·종료·교체와 같은 제어 잠금으로 직렬화합니다.
그 사이 JOB·실행이 바뀌면 target_changed 오류이며 다른 대상으로 다시 해석하지 않습니다.
선택과 재대조에서 실행은 선택한 등록 base의 그 자리 실행이어야 합니다.
그 실행에 대화가 있으면 state가 그 자리에 게시한 session과 같아야 합니다.
다르면 owner_mismatch 오류입니다. Provider 호출·pane 입력·state 갱신을 하지 않습니다.
이 대조는 check_binding(5절)과 같은 조건을 사용합니다.
start가 기존 실행을 관찰·이름 변경·launch하기 전에도 같은 조건을 적용합니다. 게시 전 실행은 base와 자리만 대조합니다.
중지된 실행에 send하지 않습니다.

관리 ID는 base_path_key·project_id·run_id입니다.
Base_path_key는 등록의 경로 key이며 project_id는 project 문자열입니다.
Run_id는 프로그램이 새 실행에 부여하며 사용자 입력으로 받지 않습니다.
CR ID는 project-item이 CR을 만들 때 발급합니다. 공통 도구는 ID를 만들지 않습니다.
Provider의 실제 대화 ID와 tmux ID는 외부 도구가 발급한 연결값입니다.

Skill은 JOB·검증·review·commit message 작성 절차를 안내합니다.
개발·검증·commit·push·merge는 Leader와 Worker가 수행합니다.
공통 script는 이 작업을 자동 완료로 판정하지 않습니다.

## 2. 등록과 프로젝트 선택

등록 파일은 `~/.config/project-agent/project.json`, `~/.codex/project.json`, `~/.claude/project.json` 중 하나입니다. 같은 파일을 가리키는 여러 경로는 하나로 봅니다. 서로 다른 파일이 둘 이상이면 `registry_ambiguous`, 하나도 없으면 `registry_not_found`로 거절하며 오류 문구에 세 위치를 적습니다. 위치의 원본은 `docs/project-team/install-contract.md` 6절입니다.
[등록 예제](project-registry.example.json)는 base key와 project·provider·seats·항목 경로·launch를 보여 줍니다.
Project는 유일한 문자열, provider는 claude 또는 codex입니다.
Seats는 로컬 경로 문자열 배열입니다. Codex project는 아래 SSH seat 객체를 함께 등록할 수 있습니다.
Project·경로는 비어 있지 않아야 합니다.
Base key는 절대 경로 또는 ~/로 시작하는 경로입니다.
Seats의 개수에는 상한이 없으며 같은 실제 로컬 base·seat 경로를 중복 등록하지 않습니다.
SSH seat의 중복은 등록한 host와 원격 path 쌍으로 검사합니다.
선택 key `path_cr`·`path_decide`는 project-item skill의 항목 루트입니다.
두 key의 값은 seats와 같이 절대 경로, `~/` 경로, 또는 base 기준 상대 경로입니다.
Key가 없으면 그 종류의 항목을 쓰지 않는 project입니다. 도구는 기본 위치를 만들지 않습니다.
모든 project의 항목 루트는 서로 같거나 조상·자손 관계이면 안 됩니다.
항목 루트는 project 선택에 사용하지 않습니다.

선택 key `launch`는 provider CLI 인자 배열 `args`·`leader_args`·`worker_args`만 받으며 하나 이상 있어야 합니다.
`args`는 모든 session, `leader_args`는 Leader, `worker_args`는 모든 Worker의 인자입니다. Session의 인자는 `args` 뒤에 그 역할의 인자를 붙인 것입니다.
공통 코드가 쓰는 인자(`--remote`, `--cd`, `--session-id`, `--settings`, `--append-system-prompt-file`, `-n`, `--name`, `--resume`, `--continue`)는 세 배열 어디에 있어도 registry_invalid입니다.
환경 변수·seat별 인자 같은 다른 선언은 두지 않습니다. 역할 지침은 CR 본문에서 문서 link로 줍니다.

등록 외의 JOB·실행 상태를 이 파일에 추가하지 않습니다.

공통 옵션은 하위 명령 앞에 지정합니다.

| 옵션 | 필수·기본값 | 처리 |
| --- | --- | --- |
| --config PATH | 선택. 두 표준 등록 경로 탐색 | 지정한 원본만 읽음. 두 경로가 서로 다른 실제 파일이면 명시 필요 |
| --socket-name NAME | 선택. 사용자 기본 tmux server | 격리 server 선택 |
| --socket-path PATH | 선택. 사용자 기본 tmux server | 명시 socket 선택. socket-name과 동시 지정 금지 |

예를 들어 `agent-session --config /path/project.json start --job leader`입니다.
등록 경로를 생략하고 표준 파일이 하나만 있거나 같은 실제 파일이면 그 원본을 사용합니다.
둘 다 없으면 registry_not_found 오류와 exit 2를 반환합니다.

1. 호출 시 현재 디렉토리와 등록 base·seat를 정규화합니다.
2. 현재 디렉토리와 같거나 그 조상인 등록 경로를 찾습니다.
3. 경로 구성 요소가 가장 많은 경로의 프로젝트를 선택합니다.
4. 선택한 provider와 base의 `agent/state.json`을 사용합니다.

문자열 접두사로 비교하지 않습니다.
등록 밖은 project_not_found이며 같은 실제 경로의 중복 등록은 project_ambiguous입니다.
Base·seat의 하위 디렉토리도 지원합니다.
미사용 seat 전체의 존재를 요구하지 않습니다.
실제 사용하는 base와 seat는 존재해야 합니다.
상대 seat 경로는 해당 base를 기준으로 해석합니다.
Seat 번호는 배열 순서의 0부터입니다.

프로젝트 선택을 위한 별도 옵션은 두지 않습니다. 예외는 send의 `--project`이며 수신 project만 지정합니다(6절).
내부 호출과 자동 등록은 선택한 base 또는 seat에서 실행합니다.
선택한 등록 파일·socket도 그대로 전달합니다.
현재 실행의 프로젝트가 선택 결과와 다르면 거절합니다.
활성 JOB 중에는 seat 배열을 삭제·재정렬하지 않습니다.
활성 실행 중에는 base·provider를 바꾸지 않습니다.

운영은 사용자 기본 tmux server를 사용합니다.
격리 시험용 `--socket-name NAME`과 `--socket-path PATH`는 상호 배타적입니다.
이 옵션을 사용한 후속 제어도 같은 socket을 지정합니다.

### Codex SSH Worker seat

기존 로컬 seat 문자열은 그대로 사용합니다. SSH seat는 다음 객체로 등록합니다.

```json
{
  "host": "macbook-worker",
  "path": "/Users/worker/Agent/project.seat0",
  "python": "/opt/homebrew/bin/python3"
}
```

| Key | 계약 |
| --- | --- |
| host | 필수 SSH alias 또는 접속 대상. `[A-Za-z0-9][A-Za-z0-9_.@-]*` 형식 |
| path | 필수 원격 절대 경로. `..`와 제어 문자를 허용하지 않음 |
| python | 선택 원격 Python 실행 파일. 기본값 `python3`. Python 3.11 이상 필요 |

SSH seat는 Codex Worker에만 사용합니다. Leader와 Claude seat는 로컬에서 실행합니다.
원격 경로는 Leader 호스트의 프로젝트 선택 후보에 넣지 않습니다.
서로 다른 호스트의 같은 경로는 서로 다른 seat입니다.
동일 호스트를 여러 SSH alias로 등록한 경우의 동일성은 사용자 등록이 소유합니다.
기본 동작은 미배정 seat를 배열 순서로 검사합니다.
`start --job <CR-ID> --seat N`은 앞의 로컬 seat가 비어 있어도 지정한 SSH seat만 검사합니다.
지정한 seat가 사용 중이거나 안전 검사를 통과하지 못하면 다른 seat로 넘어가지 않습니다.
이미 배정한 CR의 --seat는 현재 배정과 같아야 합니다. 생략한 재시도도 기존 배정을 유지합니다.
활성 실행의 host·path·python은 바꾸지 않습니다. 실행 근거와 등록이 다르면 제어를 거절합니다.

Leader 호스트는 사용자 SSH 설정으로 비대화형 접속이 가능해야 합니다.
원격 호스트는 Python 3.11 이상·Git·tmux·로그인한 Codex CLI와 origin 접근 권한이 필요합니다.
SSH 서버는 Unix socket reverse forwarding을 허용해야 합니다.
공통 도구는 SSH 인증·승인·호스트 신뢰 설정을 변경하지 않습니다.
이미 승인한 provider 실행 인자는 기존 `launch`에서 읽습니다.
SSH 명령은 검증한 host와 인자별 quoting을 사용합니다. 작업 경로·Git 인자는 JSON 표준 입력으로 전달합니다.

원격 seat의 clone·Git 준비·작업 파일·셸·빌드·검증·tmux·provider daemon은 원격 호스트가 소유합니다.
원격 clone은 base의 origin URL을 사용하며 로컬 `--reference` 경로를 전달하지 않습니다.
원격 clone이 실패하면 새 디렉토리를 진단용으로 보존합니다. 기존 원격 파일은 지우지 않습니다.
Git 기준·branch 준비와 반납 판정은 기존 규칙을 적용하며 해당 Git 명령은 원격 호스트에서 실행합니다.

## 3. state.json

위치는 선택한 base의 `agent/state.json`입니다.
[상태 예제](state.example.json)는 Leader와 seat별 배정·통신 정보를 보여 줍니다.
Leader는 필요할 때 state.json과 JOB 문서를 직접 읽어 배정을 확인합니다.
실제 실행과 연결의 유효성은 각 제어 명령이 내부에서 검사합니다.

```json
{
  "leader": {
    "session_id": "11111111-1111-4111-8111-111111111111",
    "endpoint": "unix:///tmp/project-team-example/codex.sock",
    "connected_at": "2026-11-04T09:12:30Z",
    "reviewing": "TOOL-012"
  },
  "0": {"job_id": null, "git_hash": null, "session": null},
  "1": {
    "job_id": "TOOL-012",
    "git_hash": "1111111111111111111111111111111111111111",
    "session": {
      "session_id": "22222222-2222-4222-8222-222222222222",
      "endpoint": "unix:///tmp/project-team-example/codex.sock",
      "connected_at": "2026-11-04T04:20:02Z"
    }
  },
  "2": {"job_id": "TOOL-013", "git_hash": null, "session": null}
}
```

예제의 값과 주소는 설명용입니다.
Root는 leader와 등록 seat 수만큼의 연속한 숫자 key입니다.
Worker seat가 없으면 `{"leader": null}`입니다.
등록 seat 수가 state보다 많으면 없는 seat를 미배정 행으로 읽고 다음 쓰기에서 저장합니다. 등록 seat 수가 state보다 적으면 사라지는 seat가 모두 미배정일 때만 그 행을 빼고 읽습니다. 하나라도 배정·연결이 있으면 `state_invalid`이고 details에 그 seat 번호를 담습니다. Key가 연속 숫자가 아니거나 형식이 깨진 state는 seat 수와 무관하게 거절합니다.

| 항목 | 의미 |
| --- | --- |
| leader | Leader의 session. 연결 전·반납 완료 후에는 null |
| leader.reviewing | Leader가 지금 review 중인 JOB. 없으면 null(7절 Review) |
| N.job_id | Leader가 배정한 JOB. 미배정은 null |
| N.git_hash | 최초 pull 직후 hash. 미준비·비Git은 null |
| N.session | Worker의 session. 연결 전·반납 후에는 null |
| session.connected_at | 그 대화를 처음 게시한 UTC 시각(`YYYY-MM-DDTHH:MM:SSZ`) |

Session의 값은 provider에 따라 다릅니다.

| Provider | 필수 필드 | 사용 |
| --- | --- | --- |
| Claude | session_id·message_to | 실제 대화 UUID와 ListAgents에서 확인한 SendMessage 대상 |
| Codex | session_id·endpoint | 실제 thread ID와 app-server 주소 |

Session의 각 필수 값은 비어 있지 않은 문자열입니다.
`connected_at`과 Leader의 `reviewing`은 선택 key입니다. 이 key가 없는 기존 state도 읽습니다.
Provider 내부 등록은 session을 게시할 때 같은 slot의 기존 session과 session_id를 대조합니다.
같으면 같은 대화의 재게시이므로 `connected_at`·`reviewing`을 보존하고 연결 주소만 갱신합니다.
다르거나 없으면 새 대화이므로 현재 시각을 쓰고 Leader의 `reviewing`을 null로 씁니다.
`connected_at`이 없는 기존 대화의 재게시는 시각을 추정해 채우지 않습니다.
저장한 `reviewing`은 null 또는 현재 어떤 seat의 job_id입니다. 다른 값은 state_invalid입니다.
연결을 대조하는 식별값은 Claude가 session_id, Codex가 session_id·endpoint입니다.
`connected_at`·`reviewing`·Claude의 message_to 변경은 연결 교체로 보지 않습니다.
Provider는 등록에서 읽으므로 state에 중복 저장하지 않습니다.
Claude UUID를 SendMessage.to로 가정하지 않습니다.
Claude 이름·ref는 전송 시 현재 목록과 실제 대화에 대조합니다.
Codex endpoint는 TUI와 전송이 사용하는 같은 서버입니다.

배정 시 JOB ID와 null hash·session을 기록합니다.
Provider 내부 등록은 자기 window의 실제 native binding을 기록하고, 같은 단계에서 state의 session을 게시합니다(5절 Provider 내부 등록).
게시하는 주체는 이 등록 하나입니다. 시작 controller는 state를 쓰지 않고 등록 결과를 기다려 보고만 합니다.
예외는 원격 seat입니다. 등록이 원격 host에서 일어나 Leader 호스트에는 등록 함수가 없으므로, 아래 SSH Worker 절의 controller가 원본 state에 게시합니다.
Git hash는 작업 시작 기준이며 이후 commit·조회로 덮어쓰지 않습니다.
전체 commit hash를 사용하며 40자리와 64자리를 지원합니다.
Commit 날짜·동기화 시각·제출 hash는 JOB 문서에 둡니다.
오류나 작업 중단은 JOB 배정을 자동 삭제하지 않습니다.

상태 저장은 한 내부 함수가 담당합니다.
`agent/state.lock` 아래 최신 파일을 읽고 자기 변경을 합친 뒤 원자적으로 교체합니다.
외부 명령을 기다리는 동안 이 잠금을 유지하지 않습니다.
현재 JOB·실행을 대조하며 늦은 등록·반납이 새 실행을 덮어쓰지 못합니다.
추가 상태 enum·오류·실행 이력은 이 파일에 저장하지 않습니다.
필드·타입·seat 수는 script가 직접 검사합니다.
손상 파일은 빈 상태로 덮어쓰지 않습니다.

### 실행 근거와 잠금

State는 배정과 연결의 원본이며 실행 process 정보의 원본은 아닙니다.
관리 window의 `@agent_session_*` tmux option에 다음 실행 근거를 둡니다.

| 실행 근거 | 저장할 값 |
| --- | --- |
| 소유 범위 | 정규화한 base, target(leader 또는 seat 번호), JOB ID, run_id |
| Tmux 실행 | 실제 socket 경로, server PID·시작 시각, session/window/pane ID |
| Process 실행 | CLI PID·생성 시각·process group, 추적한 background PID·생성 시각 |
| Provider 연결 | 실제 session_id, Claude message_to 또는 Codex endpoint |
| 제어와 관찰 | stopping 여부, 반납 대기(`release_pending`), provider 실행 시도 여부, 등록 완료 여부, 게시 의도(`publishing`), hook 관찰값, controller PID·생성 시각, background로 옮겨짐(`moved_to_background`), 받은·보낸 메시지의 시각(`last_received`·`last_sent`), watch가 보낸 점검의 기록(`watch`) |

JOB 값은 CR을 가리키는 값(8절)만 둡니다. CR 본문은 option에 복제하지 않고 CR 파일에서 읽습니다.

한 번의 갱신에 포함된 option은 tmux 명령 한 번으로 씁니다.
읽기는 한 번의 명령으로 option 목록과 값을 함께 읽습니다.
따라서 읽는 쪽은 한 갱신의 일부만 쓰인 상태를 보지 않습니다.

현재 pointer의 window가 없으면 `execution_evidence_missing` 오류입니다.
공통 코드는 해당 seat의 배정과 pointer를 지우지 않습니다.
자동 배정은 그 seat의 이유를 기록하고 다음 seat를 검사합니다.
호출자 탐색과 내부 등록은 다른 slot의 이 오류를 건너뜁니다.
지정한 대상의 근거가 없으면 그 대상의 제어는 실패합니다.

Launch script는 현재 run_id·작업 경로와 선택한 등록 파일·socket을 명시적으로 받습니다.
CLI 생성 직전과 실제 등록 직후에 위 근거를 갱신합니다.
Provider 실행 시도 값은 준비 전 false로 기록하고 CLI 생성 직전 true로 바꿉니다.
이 값은 같은 run에서 되돌리지 않으며 누락을 false로 취급하지 않습니다.
관리 tmux session의 대상별 option에 현재 run·window·pane을 가리키는 값을 둡니다.
Leader는 leader, Worker는 seat-N을 option의 고정 target으로 사용합니다.
새 실행 예약 때 대상 제어 잠금 아래 이 현재 실행 포인터를 교체합니다.
등록 callback은 자신의 값과 이 포인터·server 생성 정보·실제 process를 모두 대조합니다.
옛 window에 남은 자기 run 값만으로 새 실행의 state를 갱신하지 못합니다.
관리 window는 target마다 다시 씁니다. 새 run은 같은 target의 종료한 window를 이어받을 수 있고(아래 종료한 window 정리), 그때 window의 관리 정보는 새 run의 값만 담습니다.
이어받으면 이전 run의 값이 하나도 남지 않습니다. 이전 run에만 있던 option은 지우지 않고 처음 만든 window와 같게 읽히는 값(null·false·빈 값)으로 씁니다.
같은 window를 가리키는 이전 run의 기록이 대상 제어 잠금 밖에서 쓰는 경로는 갱신에 자기 run_id를 함께 넣습니다. 내부 등록·hook 관찰·process 기록, controller의 PID·pending 기록, background 기록, stopping 복원이 그 경로입니다. run_id가 window의 현재 값과 다르면 `target_changed`로 거절하므로 이전 run의 늦은 쓰기가 새 run의 값을 덮지 못합니다.
Window의 run_id 등 identity option을 바꾸는 쓰기는 window를 새 run에 넘기는 처리 하나뿐입니다.
죽은 server의 값과 복원한 창의 복사된 option은 현재 실행의 근거가 아닙니다.
Tmux 근거가 사라지면 state를 자동 삭제하거나 실행을 자동 채택하지 않습니다.
Tmux server를 다시 시작하면 예약 seat의 현재 실행 포인터와 실행 근거가 함께 사라집니다.
그 seat의 start·stop·restart는 execution_unknown입니다. 운영자가 7절의 수동 복구를 수행합니다.
예외는 shutdown이 남긴 종료 기록이 있는 slot입니다. 서버를 내리기 전에 `agent-session shutdown`을 실행했으면 이 근거가 사라져도 resume이나 start가 이어 갑니다(7절 shutdown·resume).
shutdown 없이 서버가 내려갔어도 운영자가 `resume --lost`로 재부팅을 확인한 slot은 같은 기록을 만들어 이어 갑니다(7절 resume --lost).
`agent/suspend.json`은 shutdown이 종료를 확인한 slot의 기록입니다. slot(`leader` 또는 `seat-N`)마다 job_id·종료한 run_id·session_id·종료 시각(UTC)·forced를 담습니다. `resume --lost`가 만든 기록은 판정 근거인 `lost`를 더 담습니다.
이 파일은 배정과 연결의 원본이 아닙니다. resume과 start가 state와 대조하는 데만 사용합니다.
저장은 `agent/suspend.lock` 아래 원자적 교체로 합니다. 손상한 파일은 `suspend_invalid`이며 덮어쓰지 않습니다.
`agent/runs/<run_id>/`에는 prompt·settings·launch·hook 진단·제어 결과를 둡니다.
이 파일은 실행 산출물이며 배정의 두 번째 원본으로 사용하지 않습니다.
`agent/diagnostics/`에는 예상하지 못한 예외의 traceback을 둡니다.
이 파일도 배정의 원본이 아닙니다.

SSH Worker의 배정·Base·review·반납과 CR의 원본은 Leader 호스트에만 둡니다.
Leader 호스트의 관리 window는 SSH 표시 창이며 `remote_seat`와 `remote_native`로 원격 실행을 연결합니다.
원격 native 근거는 run·JOB·thread·원격 tmux socket과 server·window·pane·process 생성 정보를 대조합니다.
Leader 호스트의 SSH PID나 동명 로컬 경로로 원격 생존·Git 상태를 대신 판정하지 않습니다.

원격 `~/.cache/agent-session/runtime/<source-hash>/`는 전송한 Python helper cache입니다.
런타임이 설치한 project-team·project-item skill link는 다음 bundle에서도 현재 지침을 가리키도록 갱신합니다.
기존 사용자 설치와 다른 대상의 link는 덮어쓰지 않습니다.
원격 `~/.cache/agent-session/runs/<run_id>/`는 실행 capsule입니다.
Capsule의 등록 파일·state·CR snapshot은 native 등록과 관찰을 위한 실행 cache입니다.
이 cache는 새 배정을 만들거나 원본 CR의 상태·Base·review를 결정하지 않습니다.
원격 native 등록을 확인한 Leader 호스트의 controller가 현재 run·JOB과 대조한 뒤 원본 state에 session을 게시합니다. 이 controller는 확인하는 동안 대상 제어 잠금을 유지합니다.
capsule에서는 로컬 run과 같이 등록 함수가 native binding을 실행 cache에 게시합니다. 원격 controller의 생존과 SSH 응답에 달려 있지 않습니다.
시작 dialog에서 대기한 뒤 native 등록이 늦게 끝나도 같은 run의 등록 함수가 cache 게시를 마칩니다.
이 비동기 cache 게시만으로 Leader 호스트의 배정이나 시작 성공을 확정하지 않습니다.
같은 run의 SSH 재연결은 원격 실행을 새로 만들지 않습니다.
Provider 준비 실패를 고친 뒤 같은 start로 재시도할 수 있습니다.
이전 controller 종료와 provider 실행 전임을 확인한 경우만 같은 run에서 controller를 다시 시작합니다.
기존 waiting window가 있으면 같은 실행을 재사용합니다. 이미 실행을 시도했거나 근거가 불명확하면 다시 launch하지 않습니다.
재시도는 기존 배정·Base·Git branch를 유지합니다.

원격 Worker는 capsule의 CR snapshot에서 Result를 작성하고 기존 `agent-session send --job leader`로 보고합니다.
SSH 표시 연결의 private reverse Unix socket은 run별 credential과 현재 thread를 대조합니다.
Leader 호스트의 bridge는 CR 항목 루트 잠금 아래 Result만 원본에 반영합니다.
원본의 Disposition과 다른 절에서 Leader가 추가한 내용은 보존합니다.
Worker가 snapshot의 다른 절을 바꾸면 `remote_result_invalid`입니다.
원본 Result가 마지막 반영값과도 Worker의 새 결과와도 다르면 `remote_result_conflict`(exit 4)이며 덮어쓰지 않습니다.
Result 반영과 메시지 수락은 별도 결과입니다. 전송 확인 실패를 자동 재전송하지 않습니다.

잠금 파일은 삭제로 해제하지 않고 열린 파일의 OS 잠금을 사용합니다.

| 잠금 | 경로·범위 |
| --- | --- |
| 배정 | agent/allocation.lock. 후보 선택과 예약에만 사용 |
| 대상 제어 | agent/control/leader.lock 또는 agent/control/seat-N.lock. 해당 대상의 start/send/stop/restart 직렬화 |
| CR 항목 루트 | `~/.cache/project-item/locks/<루트 경로 hash>.lock`. CR 조회·in-progress 이동·Base 기록 |
| State 저장 | agent/state.lock. 최신 읽기·검사·원자 교체에만 사용 |

잠금 순서는 배정 → 대상 제어 → CR 항목 루트 → state입니다.
CR 항목 루트 잠금은 재진입하지 않습니다. 잠금을 가진 호출이 같은 잠금을 다시 잡는 함수를 부르지 않습니다.
배정 중 사용 중인 대상 제어 잠금은 기다리지 않고 해당 후보를 건너뜁니다.
예약 뒤 배정 잠금은 풀며 대상 제어 잠금은 해당 제어가 끝날 때까지 유지합니다.
단, 로컬 run의 시작 controller는 등록을 기다리는 동안 대상 제어 잠금을 놓습니다. 등록 함수가 같은 잠금을 잡고 게시하기 때문입니다. 기다림이 끝나면 다시 잡고 정리를 이어갑니다.
State 잠금 안에서 provider·외부 명령을 호출하지 않습니다.
Read-state와 check-binding은 잠금을 획득하지 않는 읽기 전용 API입니다.
원자 교체한 snapshot을 읽고 외부 관찰 뒤 다시 읽어 JOB·run·연결 변경을 거절합니다.
내부 등록은 binding을 확인한 뒤 대상 제어 잠금을 잡고 게시합니다(deadline과 쓰기 순서는 5절). 잠금 안에서 현재 run·JOB·window·pane을 다시 대조합니다.
다르면 `target_changed`이고 state와 window에 아무것도 쓰지 않습니다.
Turn 관찰 hook(Stop·StopFailure·SessionEnd)은 canonical state를 쓰지 않고 자기 window의 관찰값만 갱신합니다.
늦은 hook이 옛 window를 갱신해도 새 실행의 state session을 덮어쓸 수 없습니다.

### 종료한 window 정리

관리 window는 CLI가 끝난 뒤에도 남습니다(remain-on-exit). 종료 확인과 반납 보류의 근거이기 때문입니다.
새 run을 만들 때는 먼저 이 window를 이어받을 수 있는지 봅니다(아래 "종료한 window 재사용"). 이어받지 못할 때만 새 window를 만듭니다.
공통 코드는 다음 시점에 같은 target의 종료한 window를 정리합니다.

1. 반납 성공: stop은 state를 반납한 뒤 대상 제어 잠금 안에서 현재 실행 포인터가 이 run을 가리키는지 대조하고 포인터를 지웁니다. 그 뒤 정리합니다.
2. 새 실행: start·restart는 새 run의 시작 완료 뒤 정리합니다.
3. 반납 보류(`released: false`): 현재 실행 포인터와 그 window를 유지합니다.

정리는 현재 실행 포인터의 run을 제외한 같은 base·target의 관리 window 가운데 다음을 모두 만족하는 것만 닫습니다.

- 관리 정보의 base·target·run_id·window_id·pane_id와 server PID·시작 시각·생성 정보가 일치합니다. 관리 정보가 없거나 복원한 window는 채택하지 않습니다.
- Window의 pane이 관리 pane 하나뿐이고 그 pane이 종료했습니다. 사용자가 pane을 추가한 window는 보존합니다.
- 그 run의 실제 종료를 stop과 같은 기준으로 확인했습니다. 확인하지 못하면 보존합니다.
- control_pending이 false이고 살아 있는 controller가 없습니다. 자기 controller의 예외는 7절 자기 종료·자기 재시작에 따릅니다.

정리는 그 target의 대상 제어 잠금 안에서 현재 실행 포인터를 읽고 후보 검사와 닫기를 마칩니다.
자기 controller의 마지막 정리는 이 잠금을 기다리지 않고 시도합니다. 잠금이 사용 중이면 닫지 않고, 잠금을 가진 명령의 정리가 대신합니다.
한 번의 정리는 시작 뒤 30초가 지나면 다음 window를 검사하지 않고 `cleanup_budget` 이유로 남깁니다.
이미 시작한 provider 종료 조회는 명령의 timeout을 따릅니다.
정리 실패와 보존은 명령의 종료·반납 판정을 바꾸지 않습니다.
반납 뒤 포인터 삭제에 실패하면 반납은 유지하고 그 window와 오류 이유를 `kept`에 보고합니다.
직접 실행한 명령은 결과의 `cleanup`에 닫은 window(`closed`)와 남긴 window·이유(`kept`)를 보고합니다.
남긴 window는 같은 target의 다음 정리가 다시 검사합니다.
`agent/runs/<run_id>/`의 실행 산출물은 정리하지 않습니다.

### 종료한 window 재사용

새 run(start·restart·resume·Worker 배정)은 새 window를 만들기 전에 같은 project·target의 종료한 window를 이어받을 수 있는지 대상 제어 잠금 안에서 봅니다.
대상 window는 현재 실행 포인터가 있으면 그 window 하나입니다. 포인터가 없으면(반납 뒤) 같은 target의 관리 window 가운데 가장 최근 run의 것 하나입니다. 최근 판단은 `agent/runs/<run_id>/launch.sh`의 시각입니다.
이어받으려면 위 정리 조건에서 "pane이 관리 pane 하나뿐" 조건만 뺀 나머지를 모두 만족해야 합니다.

- 관리 정보의 base·target·run_id·window_id·pane_id와 server PID·시작 시각·생성 정보가 일치합니다. 복원한 window는 채택하지 않습니다.
- 관리 pane이 그 window에 있고 종료했습니다.
- 그 run의 실제 종료를 stop과 같은 기준으로 확인했습니다. control_pending이 false이고 살아 있는 controller가 없습니다.
- 사용자가 추가한 pane이 있는지는 보지 않습니다. 사용자 pane이 없는 window도 같은 방식으로 이어받습니다.

자기 restart는 예외입니다. 분리 controller가 `restart`를 수행하는 중이면, 끝낸 그 run의 control_pending과 그 controller(기록한 PID·생성 시각이 지금 process와 같음)는 이어받는 조건을 막지 않습니다. 다른 controller나 다른 pending은 막습니다.

이어받는 절차는 tmux 하나의 처리입니다.

1. 위 조건의 identity·server 대조를 다시 합니다. 조건이 맞지 않으면 window를 바꾸지 않고 거절하며, 호출한 쪽은 새 window를 만듭니다.
2. 죽은 관리 pane을 대기 process(`sleep 86400`, seat root)로 `respawn-pane` 합니다. `-k`를 쓰지 않으므로 pane이 다시 살아 있으면 tmux가 거절합니다. 관리 pane에는 키를 입력하지 않습니다.
3. 한 번의 tmux 명령 sequence로 window의 관리 정보를 새 run의 값으로 바꾸고, 현재 실행 포인터를 새 run으로 바꾸고, window 이름을 새 run의 이름으로 바꿉니다(`-exited-`가 사라집니다).
4. 그 뒤는 새 window와 같습니다. `launch`가 대기 process를 CLI로 바꾸고 등록을 기다린 뒤 정리합니다.

2와 3 사이에 실패하면 대기 process를 종료해 window를 이전 run의 종료 근거로 되돌립니다. 3의 sequence는 한 번에 적용되므로 window는 이전 run의 종료 근거이거나 새 run의 실행 전 대기 pane입니다. 둘 다 다음 start·stop이 처리하는 상태입니다.
이어받지 못하면 지금처럼 새 window를 만들고 옛 window는 정리가 판단합니다. 종료 확인·반납 보류·수동 복구의 근거를 지우지 않기 위해서입니다.

반납(stop) 뒤 사용자 pane이 있는 window는 정리가 닫지 않으므로 다음 start까지 `-exited-` 이름으로 남습니다. 다음 start가 그 window를 이어받고 이름을 되돌립니다. 사용자 pane이 없는 window는 지금처럼 정리가 닫습니다.
Tmux server를 다시 띄운 뒤의 resume·start는 이전 window가 없으므로 새 window를 만듭니다.

### Background로 옮겨진 대화와 등록되지 않은 run의 종료 판정

Claude 2.1.319는 `/background`(`/bg`)나 빈 입력란의 `←`로 대화를 background session으로 옮깁니다. CLI가 background 작업이나 session cron을 가진 채 끝날 때도 대화를 넘깁니다(exit handoff). 옮긴 대화는 새 session ID로 이어지고 `claude daemon`의 process가 맡으며, 관리 pane의 CLI는 그 대화를 보여 주는 화면으로 남습니다. 이 run은 옛 ID로 등록돼 있으므로 hook의 새 ID는 거절되고 ListAgents에도 pane이 없습니다.

- **감지**: 옛 transcript가 `{"type":"continued-in","continuedInSessionId":<새 ID>}`로 끝나면 옮겨진 것입니다. 마지막 record만 봅니다. 옮긴 뒤 같은 대화를 다시 열면 record가 이어 붙으므로 옮겨진 것이 아닙니다.
  - transcript 위치의 원본은 `providers/claude.py`의 `transcript_files`입니다(`resume --lost`의 대화 기록 확인과 같은 규칙: `<Claude 설정 dir>/projects/<경로 slug>/<session_id>.jsonl`). 여기서는 cwd를 쓰지 않고 `projects/*/<옛 ID>.jsonl`을 찾습니다. 설정 dir은 호출한 process의 `CLAUDE_CONFIG_DIR`, 없으면 `~/.claude`입니다. CLI에만 다른 config 디렉토리를 줬다면 찾지 못하고, 그때는 감지하지 못한 채 이전 오류가 그대로 나옵니다.
  - hook 경로: 다른 session ID의 hook이 오면, 그 ID가 옛 transcript의 `continued-in`이 가리키는 ID일 때 window option `moved_to_background`(`old_session_id`·`new_session_id`·`host_pid`·`host_birth`·`detected_at`)를 기록하고 `conversation_backgrounded`로 실패합니다. 아니면 `owner_mismatch`입니다.
  - 명령 경로: 기록이 없어도 transcript가 `continued-in`으로 끝나고 provider 조회(ListAgents)가 관리 pane을 보여 주지 않으면 같은 판정을 하고 기록합니다. pane이 조회되면 옮겨진 것이 아닙니다.
- **host**: background 대화를 맡은 process입니다. `claude agents --json --cwd <run의 cwd>`에서 새 ID의 행 `pid`를 찾아 PID와 생성 시각을 기록합니다. 조회가 실패하거나 행이 없으면 PID는 unknown(null)입니다.
- **종료 판정**: 옮겨진 run은 다음 둘이 모두 확인될 때만 종료입니다.
  - 대화 종료: provider 조회에 새 ID가 없고, 기록한 host PID(생성 시각 포함)의 process가 없습니다. 조회가 실패했거나 host PID가 unknown이면 확인하지 못한 것입니다.
  - CLI 종료: pane이 dead이고 `cli_pid`·`cli_birth`가 일치하는 process가 없습니다. 이 판정은 process group을 보지 않습니다. CLI가 띄운 `claude daemon`이 같은 group에 남을 수 있기 때문입니다. host는 위 대화 종료가 따로 봅니다.
  - 하나라도 살아 있으면 `running`, 살아 있는 것은 없지만 확인하지 못한 것이 있으면 `unknown`입니다.
- **명령의 처리**:
  - 종료로 판정한 run은 일반 종료 run과 같습니다. `start`·`restart`가 새 대화로 진행하고, `stop`이 반납합니다. Leader는 state의 leader를 새 대화로 바꾸고 Worker는 같은 seat·CR·branch를 유지합니다.
  - 종료가 아니면 `send`·`review`는 `conversation_backgrounded`(exit 4)로 거절하고 아무것도 바꾸지 않습니다. `start`·`restart`·`stop`도 `running`이면 같은 오류이고 `unknown`이면 `execution_unknown`(exit 4)입니다. 둘 다 details에 `run_id`·`window_id`·`pane_id`·`old_session_id`·`new_session_id`·`host_pid`(unknown이면 null)와 `conversation`·`cli`·`state`의 판정을 담습니다.
  - 옮겨진 대화를 멈추는 일은 운영자가 합니다(7절 수동 복구). 도구는 확인만 하고 host에 신호를 보내지 않습니다.
- **방지**: 관리 Claude CLI의 실행 환경에 `CLAUDE_DISABLE_ADOPT=1`을 넣어 exit handoff를 끕니다. 새로 시작하는 run에만 적용됩니다. 이미 떠 있는 run은 환경을 바꿀 수 없으므로 이 변경 뒤에도 옮겨질 수 있습니다. `/background`와 `←`는 이 환경 변수로 막지 못합니다. Claude의 `env` 설정이 이 값을 다르게 정하면 `env_policy_conflict`입니다.
- **등록되지 않은 run**: 실행을 시도했으나(`provider_launch_attempted`가 false가 아님) 등록하지 못한 run도 같은 CLI 종료 근거(pane dead, `cli_pid`·`cli_birth` 일치 process 없음)가 확인되면 종료로 판정합니다. 같은 slot의 `start`가 새 대화로 진행합니다. `cli_pid`·`cli_birth` 기록이 없으면 확인하지 못한 것이므로 지금처럼 보존합니다. CLI가 살아 있으면 `registration_failed`를 그대로 보고합니다. 이 판정은 start와 window 정리·재사용에 쓰이며, stop은 등록되지 않은 run에 대해 지금처럼 `session_unbound`입니다.

## 4. start

| 옵션 | 필수·기본값 | 처리 |
| --- | --- | --- |
| --job leader 또는 CR_ID | 필수 | Leader 시작 또는 todo CR의 Worker 자동 배정 |
| --prompt-file FILE | 선택. Leader 기본 역할 지시 | Leader 시작에만 허용. UTF-8 사용자 지시 파일 |
| --timeout SECONDS | 선택. 600초 | Seat 생성·Git 준비와 실제 연결 확인을 포함한 전체 대기 제한 |

Worker는 CR 본문을 지시 원본으로 사용하며 추가 prompt-file을 받지 않습니다.

`--prompt-file`을 Worker JOB에 주거나 `--seat`를 Leader에 주면 `invalid_arguments`·exit 2이며 어떤 효과도 생기기 전에 거절합니다. 이 검사는 `lifecycle.check_start_arguments` 한 곳이 소유합니다. `Manager.start`와 CLI(`Manager`를 만들기 전)가 부르므로, 등록 밖 cwd에서도 CLI와 Python 호출이 같은 오류를 받습니다.

### Leader

```sh
agent-session start --job leader
agent-session start --job leader --prompt-file REQUEST.md
```

Prompt 파일은 선택입니다.
생략하면 프로젝트 지침과 Leader 역할로 시작합니다. Leader는 `project-item ls`로 결정 대기와 CR을 확인하고 사용자 지시를 기다립니다.
현재 Leader가 실행 중이거나 종료를 확인할 수 없으면 새로 시작하지 않습니다.
등록 전 시작 dialog에서 기다리는 Leader(5절 Provider 내부 등록)는 예외입니다. 사용자가 dialog에 답하면 등록이 게시까지 마칩니다. 다시 실행한 start는 새로 시작하지 않습니다. 답하기 전이면 그 실행의 등록을 기다립니다. 답한 뒤에는 실행 중인 Leader가 있으므로 `leader_exists`입니다.
등록 전 hook이 실패해 `registration_failed`로 끝난 Leader도 같은 경로입니다. CLI가 살아 있으면 다시 실행한 start는 같은 오류를 바로 반환합니다. 새로 시작하지 않습니다. CLI가 끝난 것이 확인되면 새 대화로 시작합니다(3절 "Background로 옮겨진 대화와 등록되지 않은 run의 종료 판정").
Background로 옮겨진 대화의 Leader는 그 대화와 CLI가 모두 끝난 것이 확인될 때만 새로 시작합니다. 아니면 start는 `conversation_backgrounded` 또는 `execution_unknown`입니다.
정상 종료가 확인된 이전 Leader는 명시적인 새 시작을 막지 않습니다.
새 Leader는 이전 Leader의 종료한 window를 이어받을 수 있습니다. 사용자가 그 window에 붙인 pane은 새 Leader 옆에 그대로 남습니다(3절 종료한 window 재사용).
Leader 시작은 base의 Git 상태를 바꾸지 않습니다.

### Worker

```sh
agent-session start --job TOOL-012
```

새 배정은 todo/의 CR만 받습니다. Todo에 있다는 사실이 승인입니다.
Leader는 사용자 합의를 CR의 Disposition에 기록한 뒤 todo로 옮깁니다.
배정이 없는데 CR이 in-progress에 있거나, CR이 다른 상태이면 cr_not_assignable입니다.
같은 CR의 기존 배정이 있으면 아래 재요청 규칙을 적용합니다.
기존 배정의 CR은 in-progress에 있거나 보류로 todo에 있어야 합니다. 그 밖이면 assignment_mismatch입니다.

1. CR과 mode·cwd를 확인합니다.
2. 미배정 seat를 번호순으로 확인합니다. Seat 디렉토리가 없으면 만듭니다.
3. 공통 workspace 검사를 통과한 seat에서 CR을 todo→in-progress로 옮깁니다.
4. 새 run·대기 tmux 창(같은 seat의 종료한 window를 이어받을 수 있으면 그 window, 3절)·현재 실행 포인터와 state 예약을 기록합니다. 예약이 실패하면 이번 시작이 만든 대기 pane을 종료 확인하고 CR을 todo로 되돌립니다.
5. Git 준비를 수행합니다.
6. 공통 prompt와 등록의 `launch` Worker 인자로 실행 입력을 만듭니다(8절).
7. 대화형 CLI를 시작하고 자기 window의 native binding을 확인합니다. 등록이 state에 게시한 것을 확인한 뒤 시작 완료를 표시합니다.
8. Seat·CR·연결 결과를 반환합니다.

사용 가능한 seat가 없으면 후보별 이유와 함께 오류를 반환합니다.
CR mode·작업 경로는 배정과 Git 변경 전에 검사합니다.
후보 확인과 배정은 자리별 제어와 짧은 state 잠금으로 경합을 막습니다.
CR의 Cwd가 seat 밖으로 나가면 배정 전에 거절합니다. Cwd 디렉토리의 존재는 Git 준비 뒤 provider 시작 전에 확인합니다. 대기 pane은 seat root에서 시작합니다.
시작 실패는 CR 배정과 이미 기록한 Git 기준을 유지합니다.

로컬 seat 생성: base가 Git 저장소이면 `git clone --no-recurse-submodules --reference <base> --dissociate <base origin URL> <seat>`을 실행합니다(생성 시에는 submodule을 받지 않고, start의 Git 준비가 초기화합니다). 아니면 seat_unavailable입니다. 접속 인증은 사용자의 Git·SSH 설정을 그대로 따르며 공통 도구가 설정을 더하지 않습니다.
Claude provider는 이렇게 만든 seat의 workspace trust를 기록합니다(5절 Claude 실행·전송·관찰).

공통 workspace 검사:

- Git work tree이며 origin URL이 base와 같습니다.
- 추적·비추적 변경이 없습니다.
- 현재 HEAD가 origin의 어떤 ref(`refs/remotes/origin/`)에 포함됩니다. 다른 remote는 세지 않습니다.
- Local `cr/<ID>`가 있으면 `origin/cr/<ID>`와 같습니다.

같은 CR이 이미 배정돼 있으면 다른 seat를 배정하지 않습니다.
현재 실행 중이며 session 등록과 시작 완료를 확인했으면 현재 배정을 성공으로 반환합니다.
SSH Worker의 표시 연결이 끝났으면 같은 원격 run을 대조한 뒤 표시 창과 보고 연결만 다시 엽니다.
CLI 프로세스가 존재한다는 이유만으로 시작 성공을 반환하지 않습니다.
초기 등록이 아직 진행 중이면 남은 timeout 안에서 확인합니다.
Provider 실행 전 실패한 예약이면 같은 run에서 Git 준비부터 재개합니다.
이 경우 Worker가 아직 작업하지 않았으므로 별도 handoff를 요구하지 않습니다.
Provider 실행 여부가 불명확하면 미시작으로 추측하지 않고 오류를 반환합니다.
실제 종료가 확인됐으면 같은 seat에서 CR을 이어받는 새 대화로 시작할 수 있습니다.
보류로 todo에 있는 CR은 새 run을 만들기 직전에 in-progress로 옮깁니다.
보류한 CR의 기존 실행이 살아 있거나 시작 중이면 assignment_mismatch입니다. 이때 CR을 옮기지 않습니다.
Provider 실행 전 실패한 예약은 CR이 보류 중이어도 같은 run에서 Git 준비부터 재개합니다.
Git 기준과 branch는 유지합니다.
기존 run 시작 뒤 갱신한 `agent/handoff/<slot>.md`가 있으면 최초 prompt에 넣습니다.
같은 CR 인계에는 새 후보용 clean 검사를 적용하거나 main 동기화를 반복하지 않습니다.
Worker의 미commit·미push 작업은 그대로 보존합니다.
Start는 중지된 배정의 새 대화 시작이며 살아 있는 실행을 종료하지 않습니다.
Restart는 현재 실행의 종료와 새 대화 시작을 한 제어로 수행합니다.
종료 여부가 불명확하면 멈춥니다.

### Git 준비

이 절차는 Worker 시작의 내부 처리입니다.
사용자가 별도 준비 명령을 실행하지 않습니다.
CR의 `- Base: <commit> <ISO 시각>` header가 준비 이력입니다. 이 header는 agent-session만 씁니다.

| 경우 | 판별 | 처리 |
| --- | --- | --- |
| 최초 준비 | CR에 Base가 없음 | Clean 확인, 최신 main, Base를 state와 CR에 기록, write이면 Base에서 `cr/<ID>` 생성 |
| 준비 실패 재시도 | 같은 배정, CR에 Base 있음 | Main을 다시 맞추지 않음. Base commit 확인. Write는 `cr/<ID>`가 있으면 전환 후 Base 조상 확인, 없으면 HEAD가 Base이고 clean일 때 생성. Read-only는 HEAD가 Base |
| 작업 뒤 restart | 같은 배정, run 교체 | Git 준비를 다시 하지 않음. Base·branch·작업 파일 유지 |
| 보류 뒤 재배정 | 새 배정, CR에 Base 있음 | Write는 `origin/cr/<ID>`를 fetch해 이어받음. 원격 branch가 없으면 Base에서 생성. Base 유지. Read-only는 최초 준비와 같이 최신 main으로 맞추고 Base를 새 값으로 바꿈 |

- Read-only에서 write로 재배정할 때 과거 CR branch tip이 기록된 Base의 조상이면, 해당 branch를 `merge --ff-only --no-overwrite-ignore <Base>`로 올립니다. Base와 원격 branch는 바꾸지 않습니다. 실제 divergence와 사용자 파일 충돌은 거절합니다.
- 다른 seat에 Base commit이 없으면 origin에서 fetch한 뒤 그 commit을 확인합니다. Main을 전환하거나 최신 main으로 Base를 바꾸지 않습니다.
- Fast-forward 뒤 state 기록이 실패한 재시도는 로컬 tip이 Base이고 원격 tip이 Base의 조상일 때만 그 불일치를 허용합니다. 새 배정 전 seat 검사의 local/remote 일치 조건은 유지합니다.
- State hash가 있는데 CR Base가 없으면 state 값으로 CR Base를 복원합니다.
- Read-only 재배정이 새 Base를 state에만 쓰고 CR 쓰기에 실패했으면, seat HEAD가 그 state 값일 때 CR Base를 state 값으로 고칩니다. Main을 다시 맞추지 않습니다.
- CR Base와 state hash가 다르면 baseline_mismatch이며 덮어쓰지 않습니다.
- 새 기준으로 다시 시작하려면 Leader가 CR의 Base를 지우고 Disposition에 이유를 적습니다.

공통 Git 명령은 `-c submodule.recurse=false`로 하위 저장소를 자동 갱신하지 않습니다.
Git 준비와 seat 검사(배정·반납)의 Git 명령은 모두 timeout 600초를 씁니다. Seat 생성 clone만 3600초입니다.
Timeout이 나면 git에 먼저 SIGTERM을 보내 최대 10초 기다립니다. git은 SIGTERM을 받으면 자기 `index.lock`을 지웁니다. 그래도 살아 있을 때만 SIGKILL을 보냅니다.
중단한 명령의 작업 tree는 반쯤 바뀐 채 남을 수 있습니다. 도구는 lock이나 변경을 지우지 않습니다.
Timeout은 `git_failed`(exit 5)로 보고하며 message에 중단 사실과 반쯤 적용됐을 수 있다는 점을 적습니다. details는 `operation`, `timeout_seconds`, `interrupted`(`SIGTERM` 또는 `SIGKILL`), `index_lock`(경로 또는 null), `index_lock_left`입니다. 경로는 `git rev-parse --git-path index.lock`으로 확인합니다.
Seat에 `index.lock`이 있으면 배정 검사·반납 검사의 reason에 "seat has <경로> left by an interrupted Git command"를 더하고, Git 준비는 같은 문장으로 `workspace_dirty`를 반환합니다. 운영자 정리는 7절 "중단된 Git 단계의 정리"를 따릅니다.
Start의 Git 준비(첫 준비·재시도·재배정·read-only)는 마지막에 한 번 `git submodule update --init --recursive`(timeout 600초)를 실행해 seat의 모든 submodule을 초기화하고 현재 HEAD의 gitlink에 맞춥니다. 실패하면 git_failed로 start가 멈추고 기록한 Git 기준과 배정은 유지합니다. 반납 검사는 바꾸지 않으며, Worker가 건드리지 않은 submodule은 깨끗하므로 반납됩니다. Submodule의 원격 접속·인증·protocol 허용은 사용자 Git 설정을 따릅니다.
Main 갱신은 `switch --no-overwrite-ignore main`, `fetch origin main`,
`merge --ff-only --no-overwrite-ignore origin/main` 순서입니다.
이는 origin/main의 fast-forward pull과 같은 갱신이며 ignored 파일 덮어쓰기도 거절합니다.
Ignored 파일 때문에 실패해도 파일을 삭제하거나 강제로 덮어쓰지 않습니다.
기준은 `rev-parse HEAD`와 `show -s --format=%cI HEAD`에서 읽습니다.
Branch 이름은 `cr/<CR-ID>`입니다.
단계 실패 시 다음 단계를 실행하지 않습니다.
Git 준비 중에는 해당 자리의 종료·교체도 직렬화합니다.

## 5. 내부 세션 등록과 실행 확인

### 프로젝트 consumer용 Python API

외부 운영 명령은 네 개로 유지합니다.
다른 도구(project-item·project-board)는 설치한 `agent_session.api` 모듈 하나만 import합니다.
공개 이름의 원본은 [api.py](../../tools/agent-session/agent_session/api.py)의 `__all__`이고, 이 표가 그 계약을 기록합니다.
[경계 test](../../tools/agent-session/tests/test_api_boundary.py)가 다른 도구의 import와 이 표의 이름을 대조합니다.

| 이름 | 입력·결과 |
| --- | --- |
| read_state(cwd=None, config_path=None) | 현재 디렉토리로 프로젝트를 선택하고 state 원본 snapshot을 반환. 파일 생성·갱신 없음 |
| check_binding(cwd, target, expected_session_id=None, config_path=None, socket=None) | Target은 leader 또는 현재 JOB ID. 현재 배정·실제 실행·선택적 예상 session_id를 대조하여 seat·작업 경로·run_id·session과 종료 관찰 결과 반환 |
| liveness(cwd=None, config_path=None, socket=None) | Session이 있는 slot(`leader`, seat 번호)마다 판정한 `session_id`와 `state`(`alive`·`stopped`·`unknown`) 반환. tmux 실행 근거와 CLI process만 조회하고 provider를 호출하지 않음 |
| caller(project, tmux=None, store=None) | 이 명령을 실행하는 쪽을 `(slot, session_id)`로 반환. slot은 `leader`·`seat-N`·`operator`(관리 실행 밖 CLI, session_id는 None)·`unmanaged-agent`(이 project의 구성원이 아닌 agent). 환경의 대화 ID를 state의 binding과 대조하고, 없으면 관리 실행의 tmux pane으로 판정. project 도구의 유일한 caller 규칙 |
| require_live(project, slot, identity, tmux=None) | Leader·Worker caller의 slot이 아직 그 대화의 살아 있는 관리 CLI를 가졌는지 확인. 아니면 `caller_not_running` 오류. 반환값 없음 |
| load_registry(config_path=None) | 등록 파일의 모든 project 튜플을 반환([2절](#2-등록과-프로젝트-선택)) |
| resolve_project(cwd=None, config_path=None) | 현재 디렉토리를 포함하는 가장 깊은 등록 base·seat의 project를 반환. 없거나 모호하면 `SessionError` |
| RemoteSeat | 원격 Worker seat의 등록 항목 형식. `Project.seats`의 원소가 이 형식이면 원격 seat |
| SessionError | 공통 오류. `code`·`message`·`exit_code`·`details` |
| pending_releases(cwd=None, config_path=None, socket=None) | 반납 대기인 seat를 `{JOB ID: {seat, since, reasons}}`로 반환. tmux 실행 근거만 읽고, 읽을 수 없는 run은 나열하지 않음 |
| finish_release(cwd, job_id, config_path=None, socket=None) | JOB의 반납 대기를 마침. CR이 in-progress를 떠난 뒤에 호출. 대기가 없으면 None, 있으면 `{job_id, seat, released, reasons}`. 반납 조건은 stop과 같고 맞지 않으면 배정을 보존하고 이유를 반환 |
| Tmux | tmux control 클래스. 소비자는 socket 경로를 주어 만들고 option 조회·pane 조작에 씀 |
| PANE_ID_OPTION | 관리 window의 pane을 가리키는 tmux window option 이름(`@agent_session_pane_id`). 정의는 `agent_session/tmux.py`. tmux 설정 파일은 import할 수 없어 같은 문자열을 주석과 함께 씀 |

`PANE_ID_OPTION`·`RemoteSeat`·`SessionError`·`Tmux`는 이름과 형식을 제공하는 값이고, 나머지는 함수입니다.
agent-session 내부 모듈은 서로의 밑줄 이름을 import하지 않습니다. 함께 쓰는 helper는 소유 모듈의 공개 이름입니다.

`read_state`·`check_binding`·`liveness`·`pending_releases`·`caller`·`require_live`는 읽기 전용이고, `finish_release`는 반납 대기를 마치는 쓰기 호출입니다(project-item이 CR을 옮긴 직후 부름).
호출자는 선택한 등록 파일과 socket을 전달할 수 있습니다.
전달하지 않은 등록 경로는 CLI와 같은 표준 경로 규칙을 적용합니다.
상태 손상·미등록·현재 소유자 불일치·관찰 불가를 구분해 공통 오류로 반환합니다.
오류를 빈 배정이나 종료 완료로 변환하지 않습니다.
Liveness의 `alive`는 현재 실행 pointer의 session이 state의 session과 같고 pane과 CLI process가 살아 있다는 뜻입니다.
`stopped`는 그 실행의 pane이나 CLI process가 끝났다는 뜻입니다.
`unknown`은 현재 실행 pointer가 없거나 다른 session을 가리키거나 조회가 실패했다는 뜻입니다.
Liveness는 조회 실패를 오류로 올리지 않고 `unknown`으로 돌려줍니다. 주기적으로 상태를 보여 주는 consumer용입니다.
호출자는 결과의 `session_id`가 현재 session과 다르면 그 판정을 버립니다.
Liveness는 화면 표시용이며 stop·반납의 native 종료 확인을 대신하지 않습니다.
Provider 시작 전 기준 기록은 이 live 대조를 요구하지 않습니다.
그 시점의 JOB·seat 예약 검사는 공통 start가 수행합니다.

### Provider 내부 등록

실제 provider 대화를 확인하고 자기 window에 native binding을 기록하는 처리는 필요합니다.
내부 등록은 binding 기록과 canonical state의 session 게시를 한 단계로 합니다. 등록됐지만 게시되지 않은 run은 없습니다.
Claude SessionStart hook과 Codex 초기 도구 등록 코드가 호출합니다.
선택한 등록·작업 위치·현재 run을 전달하며 사용자에게 ID 입력을 요구하지 않습니다.
사용자가 호출하는 등록·이벤트 명령은 두지 않습니다.
Turn 관찰은 아래 provider 종료 확인에만 사용합니다.
이를 JOB 상태나 별도 state enum으로 저장하지 않습니다.

Claude는 시작 때 지정한 UUID와 실제 hook의 session·cwd·source를 대조합니다.
일반 start·restart의 run은 SessionStart의 source가 `startup`일 때만 등록합니다. resume의 run은 `resume`일 때만 등록합니다.
run이 resume인지는 그 window의 `resume` option이 정합니다. hook의 matcher도 같은 값을 씁니다.
Codex는 실제 도구 문맥의 CODEX_THREAD_ID와 endpoint를 확인합니다.
내부 등록은 현재 run과 자기 window를 대조하고 그 window의 binding만 기록합니다.
등록은 하나의 deadline 안에서 일합니다. deadline은 hook(Codex는 도구 호출)이 시작한 시각에서 25초 뒤입니다. hook 제한 30초보다 짧습니다. binding 확인(최대 20초)은 deadline 6초 전에 끝나야 하고, 대상 제어 잠금과 state 잠금은 남은 시간을 나눠 씁니다. deadline이 지나면 등록 실패입니다.
게시는 대상 제어 잠금을 잡고 다음 순서로 합니다.

1. 현재 포인터·JOB·window·pane과 binding을 다시 대조합니다. 다르면 `target_changed`이고 아무것도 쓰지 않습니다.
2. window에 게시 의도(`publishing`: 게시할 session)를 씁니다.
3. state에 그 slot의 session을 씁니다(같은 slot의 기존 session과 비교해 `connected_at`·`reviewing`을 보존하는 규칙은 3절). 이 쓰기가 게시의 commit 지점입니다.
4. window에 `session_id`·`registered`·`ready`를 한 번에 쓰고 `publishing`·`start_error`를 지웁니다.

3 전에 실패하면 아무것도 게시되지 않고 `start_error`를 남깁니다. 4가 실패하면 같은 잠금 안에서 state의 그 slot을 쓰기 전 값으로 되돌린 뒤 `start_error`를 남깁니다. 되돌린 뒤에야 "실패한 등록은 게시된 것이 없음"입니다. `registered`·`ready`는 거짓으로 남습니다.
등록 process가 3과 4 사이에 끝나면(SIGKILL 등) 되돌릴 기회가 없습니다. 그때 state는 `publishing`과 같은 session을 이미 가리키고 window만 미완입니다. 기다리는 시작 controller와 다시 실행한 start는 대상 제어 잠금 안에서 "현재 run이고, state가 이 run의 `publishing` session을 가리키며 window가 ready가 아님"을 확인하면 4만 마칩니다. 새 게시 결정이 아니라 이미 commit된 게시의 마무리입니다. 이 조건 밖에서는 controller가 state를 쓰지 않습니다.
로컬 run이 `registered`이고 `ready`가 아닌 상태는 이 절차가 만들지 않습니다. 이전 release가 남긴 상태입니다. 시작 controller는 이를 기다리지 않고 곧바로 `registration_incomplete`(exit 4)로 끝나며 그 run을 stop 또는 restart하라고 안내합니다. controller가 대신 게시하지 않습니다(binding을 다시 검증할 수 없기 때문입니다).
시작 controller는 대상 제어 잠금을 놓고 기다린 뒤 잠금을 다시 잡아 옛 window 정리를 이어갑니다. 다시 잡지 못해도(시간 부족) 게시된 사실은 그대로 보고하고 정리는 다음 start가 합니다. 잠금을 다시 잡은 뒤(못 잡았으면 그냥) 현재 포인터를 다시 읽어, 그 run이 다른 run으로 바뀌었으면 `target_changed`, 멈추는 중이면 `target_stopping`으로 보고합니다. 옛 snapshot으로 성공을 보고하지 않습니다.
시작 controller의 게시 뒤 일은 옛 window 정리뿐입니다. controller가 먼저 끝나면 다음 start의 정리가 대신합니다.
Record-ready가 끝나기 전에는 Worker의 일반 작업을 시작하지 않습니다.
새 CLI 실행 전에 부모의 중첩 실행 표시·세션 ID·메시지 IPC 환경을 제거합니다.
Claude의 CLAUDECODE·CLAUDE_CODE_SESSION_ID·CLAUDE_CODE_MESSAGING_*와 부모 CODEX_THREAD_ID가 대상입니다.
자격증명과 유효 사용자 설정은 일괄 제거하지 않습니다.
공통 코드가 모델·추론 강도·권한 우회를 고정하지 않습니다.
로그인·trust·권한 dialog로 시작이 멈추면 needs_user_action 오류를 반환합니다.
이 오류는 exit 3이며 배정과 생성한 창을 보존합니다. 결과의 `dialog`는 provider가 판정한 dialog 종류입니다.
시작 controller는 등록 전까지 잠금 없이 기다리며 1초마다 관리 pane의 보이는 화면을 읽어 provider의 dialog 문구와 대조합니다.
이 화면 읽기는 dialog 탐지에만 사용합니다. 등록 뒤에는 읽지 않습니다.
시작 controller는 이 오류로 끝납니다. 사용자가 그 창에서 dialog에 답하면 등록이 게시까지 마치므로 start를 다시 실행하지 않아도 됩니다. 답한 뒤 다시 실행한 Worker start는 새로 시작하지 않고 이미 게시된 결과를 그대로 돌려줍니다(`connected_at` 불변). Leader start는 4절대로 `leader_exists`입니다.
기존에 승인한 프로젝트 설정을 사용하며 새 승인을 대신하는 키 입력을 보내지 않습니다.

내부 등록의 provider binding 확인은 ListAgents에 이 pane의 행이 하나도 없을 때만 다시 조회합니다.
여러 Leader를 동시에 시작하면 목록이 잠시 늦을 수 있기 때문입니다. 간격은 1초이고 전체 20초 안에서만 반복하며, 등록의 deadline이 더 이르면 그때 끝납니다.
행이 둘 이상이거나, 이름·UUID가 다르거나, tmux 위치를 알 수 없으면 일시적 누락이 아니므로 바로 실패합니다.
send와 observe의 조회는 다시 시도하지 않습니다.
등록이 실패하면 오류 code와 message를 그 run의 window option `start_error`(`{code, message}`)에 남깁니다.
이미 다른 run이 target을 이어받았으면(`target_changed`) 남기지 않습니다. 이어받은 window에는 쓰지 않습니다.
시작 controller는 등록 전까지 이 option을 읽습니다. 기록이 있으면 기다림을 멈추고 `registration_failed`(exit 4)를 반환합니다.
오류 details에는 run 정보와 `hook_error`(hook의 원래 `{code, message}`)가 들어갑니다. 배정과 생성한 window는 보존합니다.
`registered`가 `start_error`보다 앞섭니다. 이미 보고한 실패 뒤에 이 run이 등록에 성공하면 성공한 등록이 `start_error`를 지웁니다. 그 등록은 게시까지 마친 것입니다.
Hook은 SessionStart마다 한 번 실행하므로 실패한 run이 스스로 다시 등록하지는 않습니다.

### Claude 실행·전송·관찰

대화형 `claude --session-id <새 UUID> --settings <최종 파일>`로 시작합니다.
최초 prompt는 위치 인자이며 대화 재개 옵션을 사용하지 않습니다.
예외는 resume의 run입니다. 이 run은 `claude --resume <기록한 session_id> --settings <최종 파일>`로 같은 대화를 엽니다(7절 shutdown·resume).
resume의 run은 `--fork-session`과 위치 인자 prompt를 쓰지 않습니다. 재개 메시지는 등록이 끝난 뒤 send로 보냅니다.
프로젝트의 provider_name이 있으면 현재 CLI의 이름 옵션 `-n`에 전달합니다.
CLI의 환경에 `CLAUDE_DISABLE_ADOPT=1`을 넣어 CLI가 끝날 때 대화가 background session으로 넘어가지 않게 합니다(3절 "Background로 옮겨진 대화와 등록되지 않은 run의 종료 판정").
SessionStart·Stop·StopFailure·SessionEnd hook의 session_id가 기대값과 다르면 `owner_mismatch`이지만, 옛 transcript가 그 ID로의 이동을 보여 주면 이동을 기록하고 `conversation_backgrounded`입니다.
최종 --settings에는 프로젝트 guard와 공통 SessionStart·Stop·StopFailure·SessionEnd hook을 합칩니다.
이 파일의 writer는 prepare-session 하나입니다.
공통 코드는 hook 조각을 제공하며 같은 파일을 다시 쓰지 않습니다.
`crossSessionInbound: "accept"`도 이 --settings 파일에 넣습니다.
사용자 설정 파일을 수정하거나 project/local settings의 accept에 의존하지 않습니다.

Claude는 workspace trust를 cwd부터 git 저장소 루트까지만 찾습니다. Trust한 상위 디렉토리는 새 clone을 덮지 않습니다.
등록에 seat 경로를 적은 것이 그 seat의 승인입니다. 공통 start가 seat를 새로 clone하면 Claude provider가 그 경로의 trust를 기록합니다.
기록 위치는 Claude 전역 설정(`~/.claude.json`, CLAUDE_CONFIG_DIR가 있으면 그 아래 `.claude.json`)의 `projects[<seat 실제 경로>].hasTrustDialogAccepted`입니다.
Claude의 설정 잠금(`.claude.json.lock` 디렉토리)을 잡고 파일을 다시 읽은 뒤 그 항목만 true로 씁니다. 다른 key와 파일 권한은 보존합니다.
설정 파일이 없거나 잠금을 5초 안에 얻지 못하거나 읽기·쓰기가 실패하면 기록하지 않고 시작을 계속합니다. 그 시작은 위의 dialog 탐지로 needs_user_action을 반환합니다.
Base와 이미 있던 seat에는 기록하지 않습니다.
Managed 정책이나 기존 refuse/deny가 이를 막으면 오류로 알리며 우회하지 않습니다.
수신 정책의 적용 범위는 [Claude 공식 문서](https://code.claude.com/docs/en/cross-session-messaging#control-inbound-messages)를 따릅니다.

외부 script 전송은 요청마다 `claude mcp serve`를 시작합니다.
MCP initialize → tools/list → ListAgents → SendMessage → host 종료 순서입니다.
현재 도구의 inputSchema를 사용하며 직접 메시지 socket protocol을 구현하지 않습니다.
ListAgents의 이름·ref는 UUID에서 계산하지 않습니다.
SessionStart의 실제 UUID·cwd와 관리 pane·PID를 먼저 결합합니다.
이 실행의 -n 이름과 ListAgents 행의 tmux session/window/pane을 대조합니다.
Claude 2.1.317의 구조화 rows에는 name·ref·type·status만 있습니다.
Tmux 근거는 사람용 listing 문자열의 `tmux <session>:<window_id>.<pane_id>` 부분입니다.
예: `tmux agent-8:@12.%24`입니다. UUID·실제 관리 pane을 함께 대조합니다.
이 버전의 listing fixture로 파싱을 회귀 검증합니다.
CLI 변경으로 형식을 해석하지 못하면 연결 미확인 오류입니다.
Tmux 표시가 없거나 여러 행이 대응하면 연결 미확인 오류입니다.
확인한 행의 정확한 `이름 [ref]`를 message_to에 기록하고 매 전송 전에 재확인합니다.
예: UUID add69150-b337-440d-9968-a8cb3d9ec866의 ref는 6d267e일 수 있습니다.
두 값의 접두사 일치를 요구하거나 이름만 같은 다른 대화를 채택하지 않습니다.

On-demand host의 임시 회신 주소는 team 주소로 저장하지 않습니다.
Envelope는 sender의 project·leader/JOB·run과 회신할 `send --job leader` 또는 JOB ID를 포함합니다.
수신자는 이 논리 대상과 현재 state로 회신합니다.
SendMessage 성공을 읽음이나 사용자 승인으로 기록하지 않습니다.
반환은 accepted·held·rejected·unknown을 구분하며 held는 무인 전달 성공이 아닙니다.

Stop·StopFailure hook은 해당 UUID/run의 turn 종료와 background 관찰을 기록합니다.
SessionEnd는 정상 CLI 종료 관찰을 추가합니다.
관찰값에는 판정에 쓰는 field만 남깁니다. 응답 본문 같은 대화 내용은 저장하지 않습니다.
관찰 원본은 위 window option과 runs의 hook 진단이며 JOB 업무 상태를 변경하지 않습니다.
Stop hook 부재·누락된 background 필드를 빈 목록으로 가정하지 않습니다.
사용자 interrupt에는 Stop hook이 없을 수 있으므로 실제 종료·process 검사도 사용합니다.
Hook 자체를 종료 완료 판정으로 사용하지 않습니다.
Hook 의미는 [Claude 공식 reference](https://code.claude.com/docs/en/hooks#stop)를 따릅니다.

### Codex 실행·전송·관찰

사용자 공용 app-server daemon을 사용합니다.
`codex app-server daemon version`의 socketPath를 읽고 실제 경로로 정규화합니다.
`/tmp/codex-daemon-<uid>/<hash>`를 임의 조립하지 않습니다.
Daemon이 없으면 현재 CLI의 daemon start로 시작하고 readiness를 확인합니다.
공통 tool은 공용 daemon의 stop/restart를 수행하지 않습니다.
대화형 TUI는 `codex --remote unix://<socketPath> --cd <확정한 cwd> ... <최초 prompt>`로 시작합니다.
Tmux cwd만으로 원격 daemon의 thread cwd가 정해진다고 가정하지 않습니다.
일반 start와 restart 모두 이전 thread의 resume 옵션을 사용하지 않습니다.
State endpoint와 전송·조회 endpoint는 이 TUI가 사용하는 같은 서버입니다.

초기 prompt의 첫 작업은 실제 도구 문맥에서 내부 등록 함수를 호출하는 것입니다.
Run·config·socket은 prompt의 명시 인자로 전달하고 CODEX_THREAD_ID는 실제 도구 환경에서 읽습니다.
공유 daemon이 launcher의 임시 환경을 상속한다고 가정하지 않습니다.
Thread 조회로 실제 ID·cwd를 확인하고 현재 run·관리 process와 대조합니다.
이 등록이 끝나기 전에는 JOB 일반 작업을 시작하지 않습니다.
Codex hooks는 현재 stable이며 SessionStart 입력에는 실제 session_id·cwd·source가 있습니다.
그러나 이 입력만으로 pane PID와 run을 결합할 수 없습니다.
따라서 v1은 이를 보조 관찰로만 사용하며 초기 도구 등록을 대체하지 않습니다.
고정 hook의 trust·실행 문맥 전달·늦은 callback 거절을 실제로 검증한 뒤에만 대체할 수 있습니다.
Hook trust 우회는 공통 기본값으로 추가하지 않습니다.

내부 등록은 설치 때 확정한 Python과 library를 사용합니다.
최초 prompt는 다음 Python -c 호출을 실제 절대 경로·값으로 생성합니다.

```sh
PYTHON -c 'import sys; sys.path.insert(0, sys.argv[1]); from agent_session.internal import register_current; register_current(run_id=sys.argv[2], config_path=sys.argv[3], socket_path=sys.argv[4], endpoint=sys.argv[5])' LIB RUN CONFIG TMUX_SOCKET ENDPOINT
```

PYTHON·LIB는 launcher가 확정한 실행 파일·설치 package 경로입니다.
Run·config·tmux socket·endpoint는 호출을 생성한 start가 확정한 값입니다.
실제 대화 ID는 함수가 도구 환경의 CODEX_THREAD_ID에서 읽으며 인자로 받지 않습니다.
별도 사용자 명령이나 설치 callback script를 만들지 않습니다.
모든 인자는 argv 단위로 안전하게 인용합니다.
함수는 현재 run을 검증하고 자기 window의 native binding만 기록합니다.
Canonical state는 등록 함수가 게시합니다. 시작 controller는 그 결과(`ready` 또는 `start_error`)를 기다려 보고만 합니다.
등록 함수는 게시가 끝난 뒤에만 반환합니다. 원격 seat만 Leader 호스트의 controller가 게시합니다(3절).

Tmux 제어 권한은 host에서 명령을 실행하는 권한과 같습니다.
이 권한으로 run-shell·new-window를 실행할 수 있으므로 filesystem sandbox의 격리를 보장하지 못합니다.
Leader·Worker 모두 현재 설계에서 tmux 제어가 필요합니다.
V1은 기존에 승인한 비sandbox 실행만 지원합니다.
Sandbox가 적용된 profile은 시작 전에 unsupported_sandbox로 거절합니다.
지원 판정은 실제 적용할 argv와 profile·config를 합친 설정을 기준으로 합니다.
Binary를 직접 실행하므로 shell function·alias가 붙이던 인자는 상속하지 않습니다.
기존에 승인한 비sandbox 실행 인자는 등록의 `launch`에 명시합니다.
공통 tool이 권한 우회 옵션을 추가하지 않습니다. 새로 clone한 Claude·Codex Worker seat와 새 Codex Leader 실행의 등록 Base에 대한 trust 기록은 사용자 설정 변경의 예외입니다.
현재 파일 쓰기 권한이나 tmux 접근이 없으면 needs_user_action입니다.
프로젝트 mode read-only는 업무 수정 금지이며 OS sandbox나 승인 prompt 정책과 구분합니다.

Codex에는 --settings가 없습니다.
공통 start가 등록 project의 새 Codex Worker seat를 clone하거나 새 Codex Leader 실행을 준비하면 Codex provider가 해당 seat 또는 등록 Base의 정확한 실제 경로에 `projects.<path>.trust_level = "trusted"`를 사용자 `config.toml`에 기록합니다. 등록 밖 경로와 이미 있던 Worker seat에는 기록하지 않습니다. 기존의 명시적 `untrusted`는 덮어쓰지 않습니다. 다른 설정 값과 주석을 보존하며 같은 경로에 중복 기록하지 않습니다. 기록하지 못하면 CLI의 `Folder access` 화면을 `workspace_trust`로 감지해 창을 포함한 `needs_user_action`을 반환합니다.
이미 CLI가 열린 실행의 start 재시도는 그 실행과 신뢰 화면을 보존합니다. 설정을 다시 기록하거나 CLI를 다시 띄우지 않습니다. 사용자가 기존 창에서 답한 뒤 같은 start로 등록을 기다립니다. 새 실행의 신뢰 설정 준비로 이미 열린 화면을 자동 승인하지 않습니다.
Codex 실행 입력은 settings_file=null과 검증한 argv 배열입니다.
설정은 `-c key=value`, 모델은 --model, profile은 --profile을 사용합니다.
0.166.0의 --profile NAME은 `$CODEX_HOME/NAME.config.toml`의 profile v2입니다.
기존 `[profiles.NAME]`를 이 파일과 같은 입력으로 가정하지 않습니다.
Profile의 sandbox·환경 정책은 user 설정 위, 활성 project 설정 아래에 적용합니다.
명시한 CLI override는 그 위에 적용합니다. 비활성 project와 선택하지 않은 profile 값은 적용하지 않습니다.
Profile 검증에 필요한 활성 설정 계층을 확인할 수 없으면 시작을 거절합니다.
Profile을 지정하지 않으면 native 유효 설정으로 검증합니다.
설치 때 실제 지원 형식을 확인하고 기존 값의 명시 override 또는 검토한 v2 파일로 옮깁니다.
공통 start가 사용자 config를 자동 변환하거나 존재하지 않는 profile을 생성하지 않습니다.
Effort는 `-c model_reasoning_effort="..."`로 전달합니다.
권한 입력은 --sandbox와 --ask-for-approval 또는 기존에 승인한 provider 인자입니다.
Exec 전용 JSON 출력·파일 입출력·resume 옵션은 전달하지 않습니다.
Codex env는 launcher뿐 아니라 `-c shell_environment_policy.set.KEY="value"`로 전달합니다.
제거 대상은 현재 filters 형식의 exclude 규칙으로 추가합니다.
예: `-c 'shell_environment_policy.filters."EXAMPLE_FLAG"="exclude"'`입니다.
Unset-env의 정확한 각 이름을 필터 key로 옮기며 wildcard를 사용하지 않습니다.
기존 profile·inherit·기본 제외·include allowlist를 임의로 넓히지 않습니다.
같은 설정 계층에 legacy exclude 배열과 filters를 혼합하지 않습니다.
상위 계층이 legacy 배열과 filters 중 다른 형식을 지정하면 이전 형식의 규칙은 대체합니다.
Filters끼리는 대소문자를 구분하지 않는 key로 병합하며 같은 key의 상위 값이 우선합니다.
Unset-env 필터를 추가할 때 기존 legacy 배열의 제약을 잃게 되면 env_policy_conflict로 거절합니다.
기존 set이 제거 대상을 다시 주입하거나 allowlist가 필수 값을 막으면 env_policy_conflict입니다.
빈 문자열을 unset으로 대신하지 않습니다.
실제 tool 환경 수신은 별도 인수하며 설정 파싱 성공만으로 통과시키지 않습니다.
적용 순서는 [공식 환경 정책](https://learn.chatgpt.com/docs/config-file/config-advanced#shell-environment-policy)을 따릅니다.

제어 연결은 같은 Unix socket 위 WebSocket JSON-RPC를 사용합니다.
HTTP Upgrade와 masked client frame을 사용하는 실제 WebSocket 연결입니다.
`codex app-server proxy --sock PATH`는 raw byte bridge이며 동일한 WebSocket framing이 필요합니다.
Proxy stdin에 JSON 한 줄만 쓰는 stdio JSON-RPC 방식으로 연결하지 않습니다.
전송은 `codex queue --remote unix://PATH --thread ID --message TEXT`를 사용합니다.
Queue의 --resume은 사용하지 않습니다.
아래 API는 설치한 0.166.0의 생성 protocol에서 확인한 계약입니다.
실행 시 같은 기능을 지원하는지 확인하며 미지원 조회를 빈 결과로 바꾸지 않습니다.

| 확인 | API·판정 |
| --- | --- |
| 실제 thread | thread/read. 실제 ID·cwd·runtime status 대조 |
| Turn | thread/turns/list. sortDirection=desc로 모든 page 확인. terminal은 completed/interrupted/failed |
| 중단 요청 | turn/interrupt. 응답 뒤 위 terminal 상태를 별도로 확인 |
| 수신 대기 | thread/queue/list. 모든 page 확인. 취소는 thread/queue/delete로 해당 submission만 삭제 |
| Background | thread/backgroundTerminals/list. 모든 page 확인. 추적 process와 프로젝트 registry도 대조 |

NotLoaded thread는 background API를 제공하지 않습니다.
Loaded 상태에서 목록이 비었고 turn·pending도 terminal인 마지막 관찰만 tmux 근거로 저장합니다.
이 근거는 실제 session_id·run_id·최신 native turn ID를 포함합니다.
NotLoaded 관찰은 세 값이 현재 값과 같을 때만 이 근거를 사용합니다.
근거가 없거나 새 turn이 있으면 background와 종료는 unknown입니다.
공통 send는 전송 시도 전에 이전 empty 근거를 무효화합니다.
관찰 중 unload의 -32600 오류는 thread/read가 notLoaded를 확인할 때만 이 규칙으로 처리합니다.

Experimental background 조회에는 해당 capability를 협상합니다.
지원 불가·관찰 실패는 종료 미확인 오류입니다.
Unsubscribe와 archive는 thread 종료 판정으로 사용하지 않습니다.
Endpoint와 hook·API 기준은 [공식 app-server 문서](https://learn.chatgpt.com/docs/app-server)와
[공식 hooks 문서](https://learn.chatgpt.com/docs/hooks#sessionstart)를 따릅니다.

통신 주소는 state에서 읽습니다.
Tmux의 base·run·seat·JOB·provider 대화·PID 생성 정보로 실제 실행을 대조합니다.
이름·pane 숫자·복사된 option만으로 복원 창을 채택하지 않습니다.
CLI 전에 관리 창에 remain-on-exit를 설정합니다. 종료한 창은 3절 종료한 window 정리로만 닫거나 다음 run이 이어받습니다(3절 종료한 window 재사용).
다른 창과 사용자 전역 tmux 설정은 변경하지 않습니다.
Tmux session 이름은 등록의 project를 사용합니다.
Leader window는 `<project>-leader`, Worker window는 `<project>-<role>-<seat>-<JOB-ID>`로 표시합니다.
이 이름은 표시용이며 실제 실행 대조에는 run과 provider 연결값을 사용합니다.

현재 agent는 실제 provider 대화 또는 관리 pane에서 자동으로 확인합니다.
Claude는 실제 도구 환경의 CLAUDE_CODE_SESSION_ID도 등록한 UUID와 대조합니다.
신뢰할 실행 문맥이 없으면 agent의 관리 요청을 다른 역할로 추정하지 않습니다.
JOB 배정·다른 Worker 제어는 Leader가 담당합니다.
Worker는 자기 작업과 Leader 보고를 담당합니다.
Run 값은 내부 실행 확인에 사용하며 권한 자격증명으로 취급하지 않습니다.
발신자의 역할은 수신 project가 아니라 발신자 자신의 project(현재 디렉토리로 선택한 project)의 state와 실제 실행으로 판정합니다.

## 6. send

```sh
agent-session send --job leader "완료 보고입니다."
agent-session send --seat 1 --file FEEDBACK.md
agent-session send --project other --job leader "협업 요청입니다."
```

### Send 옵션

| 입력 | 필수·기본값 | 처리 |
| --- | --- | --- |
| --job leader 또는 JOB_ID | seat와 택일 | State의 Leader 또는 해당 JOB의 Worker에게 전송 |
| --seat N | job과 택일 | 현재 그 seat에 배정된 Worker에게 전송 |
| --project PROJECT | 선택. 현재 디렉토리의 project | 수신 project의 등록 이름. 다른 project를 지정하면 `--job leader`만 허용(아래 Project 간 Leader 협업) |
| MESSAGE | file과 택일 | 위치 인자의 메시지 본문 |
| --file FILE | 본문과 택일 | UTF-8 메시지 파일 읽기 |
| --timeout SECONDS | 선택. 30초 | 대상 확인과 transport 수락 확인의 전체 대기 제한 |

비어 있는 본문·파일은 입력 오류입니다.
본문은 UTF-8 기준 32768 byte 이하입니다.
공통 envelope를 합친 실제 전송문은 UTF-8 49152 byte 이하로 제한합니다.
두 provider와 MESSAGE·--file에 같은 한도를 적용합니다.
Native provider가 더 작은 한도를 알리면 전송 전에 그 한도를 적용합니다.
크기 초과는 message_too_large·exit 2이며 자르기·분할·파일 경로 대체를 하지 않습니다.
Worker가 Leader에게 보고할 때는 `send --job leader`를 사용합니다.
Leader가 보낸 send가 accepted되고 그 JOB이 `leader.reviewing`이면 reviewing을 null로 만듭니다(7절 Review 표시).
Send가 accepted되면 받는 쪽 window의 `last_received`(`{from, at}`: 보낸 slot 또는 `operator`, UTC 시각)를 쓰고, 보낸 쪽이 관리 session이면 그 window의 `last_sent`(`{to, at}`: 받는 `leader` 또는 JOB ID)를 씁니다. 이 기록은 7절 watch가 읽습니다. 메시지는 이미 전달됐으므로 기록이 실패해도 send는 실패하지 않습니다.

### Project 간 Leader 협업

서로 다른 project의 Leader는 `send --project <수신 project> --job leader`로 협업 메시지를 보내고 같은 방법으로 회신합니다.
`--project`는 같은 등록 파일의 project 이름이며 생략하면 현재 디렉토리로 고른 project가 수신자입니다.
자기 project 이름을 지정하면 생략한 것과 같습니다.
수신 project는 등록되어 있어야 하며 아니면 project_not_found·exit 2입니다.
다른 project에는 `--job leader`만 허용하고 JOB ID·`--seat`는 invalid_input·exit 2입니다.
발신자는 자기 project(현재 디렉토리)의 현재 Leader여야 합니다. 자기 project의 state Leader session과 대조하고 그 실행이 살아 있어야 합니다.
Worker와 operator는 role_denied, 이전 run의 Leader·다른 project의 session·등록되지 않은 session은 caller_unbound입니다. 발신 marker를 지우거나 임의 session_id를 입력해 통과할 수 없습니다.
수신 대상은 수신 project의 base·state session·현재 실행으로 같은 조건으로 대조합니다.
전송 허용은 send에 한정합니다. 다른 project의 start·stop·restart·review·배정 권한을 주지 않으며 이 명령들에는 `--project`가 없습니다.
Envelope는 발신 project·역할·run과 `ToProject`를 포함하고 회신 방법으로 `agent-session send --project <발신 project> --job leader`를 적습니다.
수신 Leader는 자기 project 디렉토리에서 이 명령으로 회신합니다.
협업 메시지는 동료 메시지이며 사용자 승인·읽음·작업 완료가 아닙니다.

같은 JOB의 문서나 feedback을 다시 보내도 JOB ID·Git 기준·branch를 초기화하지 않습니다.
Send의 파일 입력은 메시지 전달이며 새 JOB 배정을 자동으로 수행하지 않습니다.
다른 JOB 문서를 보내는 것만으로 현재 JOB을 바꾸지 않습니다.
새 JOB 배정은 start 절차를 사용합니다.
발신 실행·현재 JOB과 state의 대상 session을 실제 연결과 대조합니다.
Session이 없거나 중지한 실행이면 보내지 않습니다.
수신 주소를 새로 확인해야 하면 같은 대화인지 검증하고 공통 저장 함수를 사용합니다.
Leader·Worker의 발신은 동료 메시지임을 표시하며 사용자 승인으로 해석하지 않습니다.
Operator 발신은 첫 줄에 로컬 operator 입력임을 표시합니다. Operator는 관리 session도 식별된 agent도 아닌 발신 process의 분류이며 사람 인증이 아닙니다.
결정 항목의 답으로 받은 operator 발신의 승인 효력은 [결정 항목 절차](../../skills/project-item/references/decide.md)가 정합니다.
Accepted·held는 읽음·동의·JOB 완료가 아닙니다.
전달 여부가 불명확하면 자동 재전송하지 않습니다.
일반 메시지에 tmux 키 입력과 화면 scraping을 사용하지 않습니다.

## 7. stop·restart·shutdown·resume

### Stop 옵션

| 옵션 | 필수·기본값 | 처리 |
| --- | --- | --- |
| --job leader 또는 CR_ID | seat와 택일 | 해당 Leader 또는 배정 Worker 종료 |
| --seat N | job과 택일 | 현재 해당 seat의 Worker 종료 |
| --timeout SECONDS | 선택. 600초 | 정상 종료와 반납 조건 확인의 전체 대기 제한 |

### Restart 옵션

| 옵션 | 필수·기본값 | 처리 |
| --- | --- | --- |
| --job leader 또는 CR_ID | seat와 택일 | 기존 실행을 종료하고 새 대화로 교체 |
| --seat N | job과 택일 | 기존 실행을 종료하고 해당 seat에서 같은 JOB의 새 대화로 교체 |
| --timeout SECONDS | 선택. 600초 | 인계 검사·기존 종료·새 대화 등록의 전체 대기 제한 |

```sh
agent-session stop --seat 1
agent-session stop --job leader
agent-session restart --job TOOL-012
agent-session restart --job leader
```

Stop은 공통 경로의 새 입력을 막고 정상 종료를 요청합니다.
제어 잠금은 종료 요청 중의 공통 send를 직렬화합니다.
등록 검증이나 provider 종료 요청이 실패하면 stopping을 새로 기록하지 않습니다.
모든 accepted 메시지의 처리 완료를 보장하는 명령은 아닙니다.
Codex의 pending 입력은 개별 취소하고 active turn은 완료 또는 interrupt의 terminal을 확인합니다.
Claude는 turn hook·SessionEnd·실제 process 종료로 더 이상 작업하지 않음을 확인합니다.
Claude에서 개별 메시지의 처리 여부를 조회할 수 없으면 그 결과는 unknown으로 남깁니다.
CLI 종료로 폐기된 입력을 처리 완료로 보고하거나 자동 재전송하지 않습니다.
공통 코드는 provider가 해당 CLI의 idle 또는 turn terminal을 확인한 뒤 종료 요청을 한 번 보냅니다.
종료 요청 방식은 provider가 정합니다.
Claude는 실행 근거의 cli_pid가 기록한 cli_birth와 같은 process일 때만 그 PID 하나에 SIGTERM을 보냅니다.
Birth가 다르거나 확인할 수 없으면 Claude는 신호를 보내지 않고 오류를 반환합니다.
Claude는 process group에 신호를 보내지 않습니다.
Claude 관리 pane에는 어떤 키도 입력하지 않습니다. 사용자가 같은 입력란에 입력하는 중일 수 있습니다.
Codex는 SIGTERM 종료 동작을 확인하기 전까지 관리 pane에 /exit와 Enter를 전달합니다.
이 키 입력은 Codex 종료 요청에만 사용하며 JOB 메시지·dialog 승인에 사용하지 않습니다.
Codex는 각 키 전송 전에 `pane_in_mode`·`pane_mode`를 확인합니다.
Copy-mode·view-mode가 열려 있으면 `pane_input_blocked`(exit 4)와 해당 `pane_mode`를 반환합니다.
모드 관찰이 불완전하면 `tmux_unknown`입니다. 공통 도구는 모드를 닫거나 키를 추가로 보내지 않습니다.
종료 전달 오류의 `exit_delivery.stage`는 `literal`(`/exit` 전송 단계) 또는 `enter`입니다.
`exit_delivery.literal_confirmed`는 tmux가 literal 전송 명령의 성공을 반환했는지입니다. TUI 수신 확인은 아닙니다.
Literal 전송 뒤 모드가 열리면 Enter를 보내지 않고 부분 전송 근거를 보존합니다.
현재 turn을 확인하지 못하면 종료 요청을 반복하지 않고 timeout 오류를 반환합니다.
실제 종료는 PID·process group·pane·provider 관찰로 확인합니다. Hook만으로 종료 완료를 판정하지 않습니다.
SSH Worker는 이 근거를 원격 호스트에서 관찰합니다. 로컬 SSH 표시 창의 종료는 Worker 종료 근거가 아닙니다.
SSH 장애·불완전한 응답은 `remote_unknown`(exit 4)입니다. Liveness는 `unknown`이며 배정·현재 run·session을 보존합니다.
원격 실행 근거가 바뀌거나 사라졌으면 임의 실행을 채택하거나 반납하지 않습니다.
실제 종료를 확인한 뒤 결과를 반환합니다.
Stop·restart가 실제 종료를 확인하기 전에 실패할 수 있습니다. Timeout도 이 실패에 포함합니다.
이때 공통 코드는 같은 cli_birth의 CLI가 살아 있음을 확인한 경우에만 stopping을 false로 되돌립니다.
결과는 원래 오류 code와 exit를 유지하고 details의 `stopping_restored`에 복원 여부를 적습니다.
생존을 확인하지 못하면 stopping을 유지하고 details의 `stopping_kept`에 이유를 적습니다. 이 unknown은 자동 처리하지 않습니다.
종료 대기 중에 실패한 오류의 details에는 `exit_wait`도 적습니다. 마지막으로 성공한 관찰에서 종료를 막은 조건입니다. 대화 내용은 넣지 않습니다.

| 필드 | 뜻 |
| --- | --- |
| `exit_requested` | 종료 요청 함수가 성공을 반환했는지. false이면 idle 대기 중이거나 종료 전달이 실패·미확인입니다. Codex 부분 전송은 `exit_delivery`로 구분합니다. |
| `observed` | 성공한 관찰이 있었는지. false이면 아래 필드가 없습니다. |
| `provider_status` | provider가 보고한 상태. Claude는 background shell이 도는 동안 `idle`이 아니라 `shell`로 보고합니다. |
| `idle` | provider 기준 idle 여부 |
| `background` | provider가 보고한 남은 background 목록. 항목은 `id`·`type`과 120자로 줄인 `command`입니다. 보고가 없으면 null입니다. |
| `cli_alive`·`pane_dead`·`group_alive`·`tracked_alive` | CLI, pane, process group, 추적한 background PID의 생존 |

Claude Worker에 background 작업이 남으면 idle이 되지 않아 종료 요청을 보내지 않고 시간 초과가 납니다. 이때 `exit_requested`가 false이고 `background`가 그 작업을 보여 줍니다.
이 상태에서 Worker가 그 작업을 멈추면 같은 stop이 끝납니다. stop은 background 작업에 신호를 보내지 않습니다.

Worker는 아래 반납 검사를 추가로 확인합니다.

- CR이 in-progress에 없습니다. Leader가 done·todo·open·deferred로 먼저 옮깁니다.
- Seat에 추적·비추적 변경이 없습니다.
- CR이 done이고 Outcome이 fixed이면 seat HEAD가 origin/main에 포함됩니다.
- 그 밖이면 seat HEAD가 origin의 어떤 ref에 포함됩니다. 보류한 작업 branch가 게시돼 있어야 합니다.

반납 조건도 맞으면 job_id·git_hash·session을 null로 만듭니다.
같은 저장에서 `leader.reviewing`이 이 JOB이면 null로 만듭니다.
그 뒤 현재 실행 포인터를 지우고 종료한 window를 정리합니다(3절).
조건이 안 맞으면 종료만 수행하고 JOB·hash·대화 기록을 보존합니다.
이때 `leader.reviewing`이 이 JOB이면 null로 만들고 현재 실행 포인터와 window는 유지합니다.
이 경우 `stopped: true, released: false`와 이유를 반환합니다.
CR이 in-progress라서 반납하지 못했으면 종료한 run의 window에 반납 대기를 기록합니다(`release_pending`: 처음 기록한 UTC 시각 `since`와 `reasons`). state의 배정은 그대로 둡니다. 실행 근거이므로 state에 쓰지 않고, 같은 window를 다음 run이 이어받으면 다른 run 값처럼 null로 돌아갑니다.
Leader가 그 CR을 `project-item move`로 in-progress에서 옮기면(done·todo·open·deferred) 같은 명령이 이 반납을 마칩니다. 반납 조건은 위 검사를 그대로 씁니다. 조건이 안 맞으면 반납하지 않고 이유를 출력하며, 반납 대기는 유지합니다. 이미 CR을 옮긴 뒤의 stop은 이 기록 없이 위처럼 반납합니다.
`project-item ls`와 Board sidebar는 반납 대기인 seat를 표시합니다.
보류로 todo에 둔 CR의 배정이 남으면 같은 CR의 start가 같은 seat에서 새 대화로 이어받습니다(4절).
종료 성공·반납 보류는 exit 0입니다. 실제 종료 미확인은 exit 4입니다.
보존한 session은 종료한 대화의 이력이며 송신 가능을 뜻하지 않습니다.
Provider 대화 값과 주소는 종료 pane에서도 유지하며 재시작 때 다시 대조합니다.
종료 확인 전에 자리를 반납하지 않습니다.

Provider 실행 시도가 명시적으로 false인 예약도 stop할 수 있습니다.
이 경우 공통 코드는 현재 소유한 대기 pane의 PID·생성 정보·process group을 대조합니다.
공통 코드는 그 PID에 정상 SIGTERM을 요청하고 실제 종료를 확인합니다.
Native provider 관찰은 수행하지 않습니다. Provider를 시작한 적이 없기 때문입니다.
반납 검사는 그대로 적용합니다. CR이 in-progress에 있으면 첫 stop은 released=false입니다.
Leader가 실제 종료 후 CR을 todo로 옮기면 그 move가 반납을 마칩니다.
이 경로의 API binding은 session=null·ready=false·alive=false입니다.
Termination-confirmed는 대기 pane·PID·그룹이 모두 종료했을 때만 true입니다.
실행 시도가 true 또는 누락인 미등록 실행에는 이 경로를 적용하지 않습니다.

Leader는 실제 종료가 확인되면 반납합니다. 반납이 완료되면 state.leader를 null로 만듭니다.
진행 중인 Worker 배정은 보존합니다.
Leader가 없는 동안 보고 전송은 수신 대상 없음으로 반환합니다.

Restart는 다음 순서로 새 대화로 교체합니다.

1. 대상 run의 시작 뒤 갱신한 `agent/handoff/<slot>.md`가 있는지 기존 실행을 종료하기 전에 확인합니다. 없으면 handoff_required입니다. 자기 restart는 요청에 담긴 기존 run으로 같은 검사를 합니다.
2. 기존 실행의 실제 종료를 확인합니다. JOB·seat를 반납하지 않습니다.
3. 같은 seat·JOB·Git 기준·branch를 유지하고 새 run을 발급합니다. 종료한 window를 이어받을 수 있으면 그 window와 pane 자리를 새 run이 씁니다(3절 종료한 window 재사용).
4. 최신 프로젝트 지침으로 prompt·settings·환경을 다시 생성합니다.
5. 인계 파일과 현재 CR 파일 경로를 최초 prompt에 넣고 새 대화를 시작합니다.
6. 새 run의 등록이 window의 실제 binding을 검증해 state에 게시한 것을 확인한 뒤 시작 완료를 표시합니다.
7. 같은 target의 종료한 window를 정리합니다(3절). 이어받은 window는 현재 실행이므로 닫지 않습니다.

이전 provider session_id와 새 session_id는 달라야 합니다. 이 원칙의 예외는 resume 하나입니다(아래 shutdown·resume).
종료 전에는 새 대화를 시작하지 않습니다.
새 등록 전에는 이전 연결을 송신 가능한 새 연결로 취급하지 않습니다.
시작 실패 시 JOB·Git 기준과 이전 대화 이력을 보존하며 오류를 반환합니다.
Provider의 이전 대화 기록을 삭제하거나 새 대화의 transcript로 합치지 않습니다.
인계 문서에는 이전 session_id와 실제 기록을 찾을 근거도 보존합니다.
인계 파일에는 진행 결과·미완료 항목·제출 hash·다음 행동을 씁니다. 해당 session이 restart 전에 씁니다.
Worker는 인계 파일에 적은 현재 HEAD·branch·미commit 파일·미push를 그대로 보존합니다.
Worker의 보존한 미완료 작업만으로 restart나 같은 JOB의 재start를 거절하지 않습니다.
Leader restart는 기존 Worker 배정을 바꾸지 않습니다.

### shutdown·resume

Workstation을 내리기 전에 운영자가 shutdown을 실행합니다. 서버가 다시 뜨면 resume을 실행합니다.
서버를 내리기 전에 stop으로 Worker를 하나씩 반납하지 않습니다. 실행 근거가 tmux에 있으므로 shutdown 없이 server가 내려가면 배정을 다시 제어할 수 없습니다(3절 실행 근거와 잠금).
두 명령은 운영자 명령입니다. 관리 session(Leader·Worker)이 호출하면 role_denied이고, 등록 밖의 agent가 호출하면 caller_unbound입니다. 등록된 모든 project에 대해 이 판정을 먼저 하며, 판정 전에는 아무것도 바꾸지 않습니다.
두 명령은 현재 디렉토리로 project를 고르지 않습니다. `--project NAME`은 등록 이름, `--all`은 등록 파일의 모든 project입니다. 등록에 없는 이름은 project_not_found·exit 2입니다.
Provider가 Claude인 project만 처리합니다. Codex project는 건드리지 않고 결과의 `skipped`에 `provider_not_supported`로 보고합니다. Codex의 thread 재개를 검증하지 못했기 때문입니다.

| 옵션 | 필수·기본값 | 처리 |
| --- | --- | --- |
| --project NAME | --all과 택일 | 그 project만 |
| --all | --project와 택일 | 등록 파일의 모든 project |
| --timeout SECONDS | 선택. 600초 | shutdown은 모든 대상이 함께 쓰는 마감까지의 대기, resume은 전체 대기 제한 |
| --force | shutdown만. 선택 | 마감까지 쉬지 않는 대상을 강제 종료 |
| --lost | resume만. 선택 | shutdown 없이 서버가 내려간 뒤 기록이 없는 slot도 대상으로 삼음(아래 resume --lost) |

#### shutdown

1. 대상은 state에 session이 있는 Leader와 Worker입니다. 반납을 보류해 이미 종료한 Worker도 포함합니다. 그 Worker는 기존 종료 근거로 확인합니다. 대화가 등록되지 않은 seat는 건드리지 않고 `skipped`로 보고합니다.
2. 모든 대상은 한 마감(`--timeout`) 아래 동시에 진행합니다. 한 대상의 대기가 다른 대상을 늦추지 않습니다. 한 project 안에서는 Worker가 모두 끝난 뒤(기록했든 남겼든) Leader를 멈춥니다.
3. 각 대상은 stop의 종료 경로를 씁니다. 새 입력을 막고, CLI의 idle을 확인한 뒤 종료 요청을 한 번 보내고, 실제 종료를 확인합니다. 관찰 간격은 1초입니다.
4. shutdown은 반납하지 않습니다. state의 job_id·git_hash·session과 CR의 위치와 seat의 파일을 바꾸지 않습니다. `leader.reviewing`도 유지합니다.
5. 실제 종료를 확인한 대상만 `agent/suspend.json`에 기록합니다. 그 window의 이름은 종료한 window의 이름(`-exited-<run>`)으로 바꿉니다.
6. 마감까지 쉬지 않은 대상은 `--force`에 따라 갈립니다.
   - `--force`가 없으면 종료하지 않고 기록하지 않습니다. stop의 실패 경로처럼 stopping을 되돌려 계속 일하게 합니다. 결과의 `busy`와 `rerun`(강제 종료하려면 다시 실행할 명령)을 보고합니다.
   - `--force`가 있으면 마감에 같은 CLI에만 SIGTERM을 보냅니다. 기록한 cli_pid의 birth가 같을 때만 보냅니다. process group에는 신호를 보내지 않습니다. 종료를 확인하면 forced=true로 기록합니다. birth가 다르거나 확인하지 못하면 신호를 보내지 않고 `unknown`으로 보고합니다.
   - 종료 요청을 보낸 뒤에는 마감이 지나도 최대 30초 더 실제 종료를 기다립니다.
7. 종료를 확인하지 못한 대상(unknown, control_pending 등)은 기록하지 않고 보고합니다. 자동으로 정리하지 않습니다.
8. 결과는 project별 `recorded`·`busy`·`unknown`·`skipped`입니다. 남은 대상(`busy`·`unknown`)이 없으면 exit 0입니다. 있으면 `shutdown_incomplete`이고 exit 4이며 같은 결과를 details에 담습니다.
9. shutdown은 다시 실행해도 안전합니다. 이미 종료한 대상은 같은 run으로 다시 기록합니다.

#### 알람

운영자가 마감 시각을 알 수 있도록 tmux에 접속한 모든 client에 알립니다.

| 시점 | 알림 |
| --- | --- |
| 대기 시작 | `display-message -d 10000`. `--force`가 있으면 "agent shutdown: 대상 N, 강제 종료 시각 HH:MM:SS". 없으면 대기 마감 시각과 강제 종료하지 않는다는 사실 |
| 마감 60초 전(`--timeout`이 60초를 넘을 때) | 쉬지 않은 대상과 다음 행동. `--force`가 없으면 강제 종료 명령 |
| 마감 | 같은 형식. `--force`가 있으면 "강제 종료합니다" |

- 60초 전과 마감에는 아직 쉬지 않은 대상의 window에 bell을 남깁니다. status line이 그 window와 session을 bell 표시로 보입니다.
- Bell은 그 pane의 tty에 BEL(0x07) 한 byte를 쓰는 것입니다. 이것은 터미널로 나가는 출력이며 pane의 프로그램이 받는 입력이 아닙니다. 사용자가 같은 입력란에 입력하는 중이어도 입력에 섞이지 않습니다. 따라서 "Claude 관리 pane에는 어떤 키도 입력하지 않습니다" 원칙과 충돌하지 않습니다.
- 알람이 실패하거나 접속한 client가 없어도 shutdown의 판정은 바뀌지 않습니다. 결과의 `alarms`에 시점별 client 수·bell 수·오류를 적습니다.
- 새 결정 항목을 알리는 알람은 이 명세의 범위가 아닙니다. tmux status script가 맡습니다.

#### resume

1. project마다 종료 기록과 state를 대조합니다. 같은 job_id·session_id여야 하고, Worker의 CR은 in-progress여야 합니다. 다르면 그 대상은 `target_changed`로 남기고 다음 대상으로 넘어갑니다.
2. project마다 Leader를 먼저, 그다음 Worker를 시작합니다. project들은 동시에 진행합니다. 시작 때마다 새 run을 만들고 최신 project 지침으로 prompt·settings를 다시 만듭니다. shutdown 뒤에도 tmux server가 유지돼 있으면 종료한 window를 이어받고(3절 종료한 window 재사용), server가 다시 떴으면 이전 window가 없으므로 새 window를 만듭니다.
3. Claude는 `--session-id` 대신 `--resume <기록한 session_id>`로 같은 대화를 엽니다. 이 예외로 resume은 이전 session_id를 다시 쓰며 새 session_id를 만들지 않습니다.
4. 등록은 이 run의 SessionStart `source == "resume"`만 받고, session_id가 기대값과 같아야 합니다.
5. 같은 session_id를 다시 게시하는 것이므로 3절 규칙대로 `connected_at`과 `reviewing`을 보존합니다.
6. 시작이 끝난 대상을 종료 기록에서 지웁니다. 실패한 대상은 기록을 남기고 이유와 `agent-session start --job <CR>`(새 대화) 안내를 보고합니다.
7. 모든 시작이 끝난 뒤 send 경로로 재개 메시지를 한 번 보냅니다. Worker가 먼저, Leader가 마지막입니다.
   - 서버를 내려 CLI가 끊겼고 background 작업과 monitor는 끝났으니 상태를 확인하고 이어 가라고 알립니다.
   - forced였으면 실행 중이던 명령이 강제 종료되어 결과가 없다는 사실을 넣습니다.
   - Leader의 메시지에는 재개한 Worker와 재개하지 못한 대상을 적습니다.
   - 메시지 전달 실패는 해당 대상의 `message`에 보고하며 재전송하지 않습니다.
8. tmux server가 다시 뜬 경우와 종료한 window가 남은 경우 결과가 같습니다. tmux-resurrect가 복원한 window의 option은 채택하지 않습니다(3절).
   - 서버가 뜬 뒤에는 tmux-resurrect 복원보다 resume을 먼저 실행합니다.
   - 복원이 먼저면 project 이름의 session이 owner 표시 없이 생깁니다. 그러면 resume이 `tmux_owner_mismatch`("The named tmux session is not managed by agent-session.")로 멈춥니다.
   - 이때 운영자는 그 project 이름의 복원된 session을 닫고 resume을 다시 실행합니다. 복원된 session의 pane은 재부팅 전 process가 아니라 새 shell입니다.
   - 복원된 session을 채택하는 코드는 없습니다.
9. 모두 재개했으면 exit 0입니다. 하나라도 실패하면 `resume_incomplete`이고 exit 4이며 같은 결과를 details에 담습니다.

#### resume --lost

정전·crash·강제 재부팅으로 shutdown 없이 서버가 내려가면 종료 기록과 tmux의 실행 근거가 모두 없습니다. `resume --lost`는 이 slot을 재부팅이 끝냈다고 확인할 수 있을 때만 shutdown의 `forced: true` 기록과 같게 취급합니다. 재부팅을 종료 근거로 쓰는 경우만 다룹니다. 재부팅 없이 tmux만 죽은 경우는 아래 수동 복구입니다.

1. 대상은 `--lost`가 없을 때와 같은 호출자·project 선택 규칙을 따릅니다(관리 session이 호출하면 role_denied). 그 위에 state에 session이 있고 종료 기록이 없는 Leader·Worker slot을 판정합니다. 종료 기록이 있는 slot은 판정 없이 위 1~9항을 따릅니다. 대화가 등록되지 않은 seat는 `skipped`(`no_conversation`)로 보고합니다.
2. slot마다 다음을 모두 확인합니다. 확인하지 못한 항목은 충족하지 못한 것으로 봅니다. 한 항목이 실패해도 나머지 근거를 모아 보고합니다.

   | 확인 | 충족 조건 | 거절 사유(`reasons[].code`) |
   | --- | --- | --- |
   | 실행 포인터 | 그 slot의 현재 실행 포인터가 없습니다. 포인터가 있으면 창이 없어도 충족하지 않습니다 | `execution_present` |
   | 부팅 시각 | 시스템 부팅 시각을 얻었습니다 | `process_unknown` |
   | 대화 기록 | `<Claude 설정 dir>/projects/<경로 slug>/<session_id>.jsonl`이 있습니다. 경로는 Leader는 base, Worker는 seat와 CR의 Cwd입니다. SSH seat는 판정하지 않습니다 | `transcript_missing`, `remote_seat`, `target_changed`(Worker의 CR이 in-progress가 아님) |
   | 갱신 시각 | 대화 기록의 마지막 갱신이 부팅 시각보다 앞섭니다 | `updated_after_boot` |
   | process | 그 session_id가 명령행에 있는 process가 없습니다. 목록을 완전히 읽지 못하면 충족하지 않습니다 | `cli_alive`, `process_unknown` |
   | 마지막 run | 그 session_id를 쓴 run(`agent/runs/<run_id>/launch.sh`)이 있습니다 | `run_unknown` |

3. 모두 충족한 slot은 `forced: true` 기록에 판정 근거 `lost`(`checked_at`·`boot_time`·`transcript`·`transcript_updated`·`processes`·`execution_pointer`)를 더해 `agent/suspend.json`에 씁니다. 그 slot은 위 1~9항의 resume 경로로 같은 대화 ID로 재개합니다. 같은 근거가 결과의 `resumed[].lost`에 남습니다. 재개 메시지는 shutdown이 아니라 서버가 shutdown 없이 내려갔고 실행 중이던 명령이 끊겼다고 알립니다.
4. 하나라도 충족하지 못한 slot은 기록을 쓰지 않고 배정을 바꾸지 않습니다. 결과의 `rejected`에 slot·job_id·session_id와 `error`(`lost_not_confirmed`, `details.reasons`·`details.evidence`)를 보고하며, 다른 slot의 판정과 재개는 계속합니다. 거절한 slot이 있으면 `resume_incomplete`·exit 4입니다. 정상 실행 중인 slot도 포인터가 있으므로 이때 거절됩니다.
5. 재개하지 못한 slot의 기록은 남으므로 Worker는 `start --job <CR>`로 같은 seat에서 새 대화를 시작할 수 있습니다(아래).
6. 부팅 시각은 Linux에서 `/proc/stat`의 `btime`, macOS에서 `sysctl kern.boottime`입니다. 둘 다 부팅 때의 벽시계 시각이라 부팅 뒤 시계를 조정하면 같은 양만큼 어긋납니다. 다른 platform은 얻지 못한 것으로 봅니다. 대화 기록 경로는 영숫자가 아닌 문자를 `-`로 바꾼 이름이며 200자 이상의 경로는 찾지 못합니다. process는 Linux의 `/proc/*/cmdline`, macOS의 `ps`로 찾으므로 `hidepid` 같은 설정으로 일부가 보이지 않으면 놓칠 수 있습니다.

#### 새 대화로 시작

- 종료 기록이 있고 state의 job_id·session_id가 그 기록과 같은 Worker seat는 현재 실행 포인터가 없어도 `start --job <CR>`로 시작할 수 있습니다. 같은 seat에서 새 대화로 시작하며 Git 준비를 다시 하지 않습니다. 시작하면 그 기록을 지웁니다.
- 기록이 없거나 state와 다르면 지금처럼 execution_unknown입니다. 재부팅으로 내려간 slot은 `resume --lost`가 먼저 기록을 만듭니다.
- `start --job leader`는 실행 포인터가 없으면 새 Leader로 시작합니다. 시작하면 시작 전에 있던 Leader의 기록을 지웁니다. 시작을 기다리는 사이 새 run에 대해 shutdown이 남긴 기록은 지우지 않습니다(run_id가 다릅니다).
- 시작하지 못한 resume의 run이 CLI 종료로 등록 전에 끝났으면 그 포인터를 지워 위 경로가 열리게 합니다.

### 종료 근거가 부족한 실행의 수동 복구

실행을 시도한 미등록 CLI는 자동으로 빈 자리로 바꾸지 않습니다.
Stop은 session_unbound를 반환하고 배정·Git 기준·기존 runtime 근거를 보존합니다.
단 그 CLI의 종료(pane dead, 기록한 `cli_pid`·`cli_birth`의 process 없음)가 확인되면 start가 같은 slot에서 새 대화로 진행합니다(3절). 이 수동 복구는 그 근거를 확인하지 못한 경우에 적용합니다.
등록한 CLI도 직접 /exit·crash·외부 종료 뒤 unload되면 마지막 background 근거가 없을 수 있습니다.
이 경우의 종료 판정도 unknown이며 같은 수동 확인 절차를 적용합니다.
이 경우 v1은 자동 복구를 지원하지 않습니다. 재부팅으로 서버가 내려간 경우는 `resume --lost`(7절)가 처리합니다.
종료한 window 정리(3절)는 control_pending이 남았거나 종료를 확인하지 못한 window를 닫지 않습니다. 이 절의 수동 확인 근거는 보존됩니다.
담당 Agent는 오류와 run 경로를 보고합니다. 운영자가 다음 절차를 수행합니다.

1. 해당 대상의 제어 잠금을 확보하고 state·CR 파일·run 파일을 보존하십시오.
2. 기록한 window·pane·server·PID 생성 정보를 실제 대상과 대조하십시오.
3. 실제 provider UUID를 시작 prompt의 run과 대조하십시오. 표시 이름이나 UUID 접두사로 선택하지 마십시오.
4. 해당 대화의 active turn·pending·background가 없고 pane·원래 PID·그룹이 종료했는지 확인하십시오.
5. 실제 대화의 cwd와 provider 설정도 확인하십시오. 확인하지 못한 사실은 unknown으로 남기십시오.
6. 등록 callback만 누락했고 모든 연결 근거가 일치하면 운영자가 기존 tmux binding과 state의 session을 복구하십시오. 그 뒤 정상 stop·프로젝트 취소·stop 순서로 처리하십시오.
7. 최초 Leader가 잘못된 cwd로 시작한 경우에는 그 대화를 채택하지 마십시오. 작업 부재와 종료 근거를 run의 startup-failure.json에 기록하십시오. State의 Leader가 null인 것을 확인한 뒤 그 실패 run의 current pointer만 해제하십시오. 원인을 수정하고 start하십시오.
8. 등록 binding이 일치하고 background 근거만 없으면 4·5번의 실제 확인을 완료하십시오. 운영자는 해당 run window에 last_background_clear를 기록하십시오. 값은 실제 session_id·run_id·thread/turns/list의 desc 첫 native turn ID입니다. 기록한 뒤 stop 또는 start를 다시 실행하십시오. 확인하지 못한 background를 빈 목록으로 기록하지 마십시오.
9. 분리 controller가 죽어 control_pending만 남으면 해당 controller의 PID·생성 정보를 대조하십시오. 운영자는 죽음을 확인한 뒤 control-result.json에 완료한 실패를 기록하고 그 run window의 control_pending만 false로 바꾸십시오. 그 뒤 정상 명령을 다시 실행하십시오. PID 기록이 없고 실행 여부도 확인하지 못하면 pending을 보존하십시오.
10. Tmux 근거를 잃은 예약 seat(3절)는 다음 순서로 처리하십시오. State에 기록한 provider 대화에 active turn과 pending이 없는지 확인하십시오. 그 대화의 background와 seat 작업 process가 남지 않았는지 확인하십시오. 종료 근거가 하나라도 unknown이면 예약을 유지하고 여기서 중단하십시오. 필요한 추가 확인을 완료한 경우에만 다음 반납을 수행하십시오. Seat의 보존할 변경을 `cr/<ID>`에 commit하고 push하십시오. 배정 잠금, 대상 제어 잠금, state 잠금 순서로 잠그십시오. State의 JOB·session과 현재 포인터의 부재를 다시 대조하십시오. 그 seat 행의 job_id·git_hash·session 세 필드를 모두 null로 바꾸십시오. `leader.reviewing`이 이 JOB이면 같은 저장에서 null로 바꾸십시오. CR이 todo이면 다음 start가 게시한 branch를 이어받습니다.

위 절차는 명시적 운영자의 수동 정비입니다. 일반 Agent의 state 직접 편집을 허용하지 않습니다.
Worker의 연결·종료·보존 근거가 부족하면 JOB과 seat를 그대로 보존합니다.
운영자는 그 이유를 확인하기 전까지 배정을 삭제하거나 같은 seat를 재사용하지 않습니다.

운영자가 검증한 실제 socket·window·native 값으로 다음 형식을 사용합니다.
예제의 대문자 값과 UUID는 실제 값으로 교체합니다.

```sh
tmux -S TMUX_SOCKET set-option -w -t @WINDOW @agent_session_last_background_clear '{"session_id":"ACTUAL_UUID","run_id":"ACTUAL_RUN","latest_turn_id":"ACTUAL_TURN_UUID"}'
tmux -S TMUX_SOCKET set-option -w -t @WINDOW @agent_session_control_pending false
```

두 번째 명령 전에 control-result.json에 완료한 실패를 기록합니다.
파일 값은 `{"ok":false,"data":{"completed":true},"error":{"code":"controller_failed","message":"Verified controller exit.","details":{}}}` 형식입니다.
첫 번째 명령은 최신 turn이 없는 대화에 한해 latest_turn_id=null을 사용합니다.

Codex의 종료 확인 오류 뒤 입력란에 원래 /exit가 남으면 전체 stop을 반복하지 않습니다.
운영자는 같은 run·pane·idle과 원래 입력을 확인한 뒤 Enter 한 번으로 그 요청만 마칩니다.
그 뒤 기존 제어 결과와 실제 종료를 확인합니다.
입력이나 실제 실행을 확인하지 못하면 추가 키를 보내지 않습니다.
`pane_input_blocked`이면 운영자가 같은 pane의 모드 화면과 실제 TUI 입력을 따로 확인합니다.
`display-message -p -t PANE '#{pane_in_mode} #{pane_mode}'`로 모드를 확인하고,
지원하는 tmux에서는 `capture-pane -p -M -t PANE`로 모드 화면을 확인합니다.
운영자가 확인한 모드를 닫은 뒤 `pane_in_mode=0`과 실제 입력을 다시 대조합니다.
부분 전송이 없고 입력이 비었을 때만 정식 stop을 새로 요청합니다.
부분 전송이나 수신 여부가 unknown이면 위의 원래 /exit 확인 절차를 적용합니다.

### Background로 옮겨진 대화의 복구

`conversation_backgrounded`는 관리 대화가 background session으로 옮겨져 새 session ID로 이어지고 있다는 뜻입니다(3절). 같은 slot에서 새 대화로 시작하는 지원 경로는 다음 순서입니다.

1. 고유 오류를 확인하십시오. details의 `old_session_id`·`new_session_id`·`host_pid`와 판정(`conversation`·`cli`·`state`)을 봅니다. 같은 오류가 hook에서 나면 그 pane에 Stop hook 오류로 보입니다.
2. 인계 파일을 확인하십시오. restart는 `agent/handoff/<slot>.md`가 필요합니다. 옮겨진 대화에서 작업 중이면 그 대화에 인계 내용을 쓰게 하거나, 직접 작성하십시오. Worker의 미commit·미push 작업은 seat에 그대로 있습니다.
3. 옮겨진 대화와 CLI를 끝내십시오. 새 ID의 대화를 `claude agents`로 찾아 멈춥니다(예: `claude agents --json --cwd <작업 경로>`의 `pid`를 확인한 뒤 그 대화를 종료). 그 다음 관리 pane의 CLI를 끝냅니다. 도구는 이 일을 하지 않습니다.
4. `agent-session start --job <leader 또는 CR>`을 다시 실행하십시오(restart도 같습니다). 종료가 확인되면 새 대화로 진행합니다. 여전히 `conversation_backgrounded`이면 어느 쪽이 살아 있는지 details의 판정으로 확인하십시오. `execution_unknown`이면 host PID나 CLI 기록을 확인하지 못한 것입니다. 그 경우 배정을 바꾸지 않고 위 "종료 근거가 부족한 실행의 수동 복구"의 확인을 먼저 마치십시오.

옮겨진 대화가 이미 끝났어도 host PID를 기록하지 못했다면 종료를 확인하지 못해 `execution_unknown`입니다. 이때 운영자가 대화와 process의 종료를 실제로 확인한 뒤 7절의 수동 복구 절차를 따르십시오.

### 중단된 Git 단계의 정리

Git 명령이 timeout이나 외부 종료로 끊기면 seat에 `index.lock`과 반쯤 적용된 작업 tree가 남을 수 있습니다(4절 "Git 준비").
도구는 이를 지우지 않고 보고합니다. 운영자가 다음 순서로 정리합니다.

1. 그 seat를 쓰는 git process가 없음을 확인하십시오(`ps`로 해당 seat 경로의 git과 그 hook·하위 process).
2. Reason이나 `git_failed` details의 `index_lock` 경로를 확인하고 그 파일을 지우십시오.
3. Start의 Git 단계는 깨끗한 tree에서 시작합니다. `git status`의 변경이 중단된 단계(예: origin/main으로의 fast-forward)의 것뿐인지 확인한 뒤 되돌리십시오. 작업 내용이 섞여 있으면 먼저 보존하십시오.
4. 같은 `start --job <CR>`를 다시 실행하십시오.

Process가 남았거나 변경의 출처를 확인하지 못하면 lock과 tree를 그대로 두십시오.

### 자기 종료·자기 재시작

호출자가 대상의 실제 provider session이면 분리한 controller를 사용합니다.
Controller는 provider process group과 실행 중 tool의 자식 수명에서 분리합니다.
이미 실행 중인 tmux server가 고정한 내부 controller 호출을 실행하게 합니다.
Provider sandbox 안의 자식을 setsid로 분리한 것만으로 sandbox 밖 controller라고 판정하지 않습니다.
호출자는 제어가 예약되면 `accepted:true, completed:false, result_file:PATH`를 받고 끝냅니다.
이 반환은 종료·반납·교체 완료가 아닙니다.
Controller는 호출 반환 후 같은 대상 제어 잠금으로 실제 제어를 수행합니다.
최종 결과는 `agent/runs/<기존 run_id>/control-result.json`에 원자적으로 기록합니다.
일반 CLI와 같은 ok/data/error에 completed=true와 종료·반납·새 연결 결과를 담습니다.
실패와 timeout도 같은 파일에 기록하며 이전 결과를 성공으로 덮어쓰지 않습니다.
자기 호출은 결과 파일을 기다리지 않습니다.
후임 Leader나 다른 호출자가 이 파일과 현재 state를 대조합니다.
이 파일은 명령 결과 산출물이며 state.json의 대체 원본이 아닙니다.
Controller PID·생성 시각을 기록하여 provider의 미종료 업무 process로 오판하지 않습니다.
자기 restart의 controller는 끝낸 run의 window를 새 run에 넘길 수 있습니다(3절 종료한 window 재사용). 그러면 controller의 control_pending=false 기록은 window의 run_id가 달라 건너뛰고 결과 파일은 지금처럼 completed로 남습니다. 마지막 정리에는 닫을 window가 없습니다.
Controller는 결과를 기록하고 control_pending을 false로 바꾼 뒤 마지막으로 종료한 window를 정리합니다(3절).
마지막 window를 닫아 tmux server가 끝나도 결과는 이미 저장되어 있습니다.
Controller가 살아 있어도 다음을 모두 만족하면 자기 run의 window를 닫을 수 있습니다.
결과 파일이 completed=true이고, 그 window의 control_pending이 false이고, 정리하는 process가 그 window에 기록된 controller PID·생성 시각과 같습니다.
다른 controller, 결과가 없거나 미완료인 controller, pending이 남은 window는 보존합니다.
다른 대상 제어는 기본적으로 최종 결과까지 기다리고 반환합니다.

Claude 종료는 pane dead·CLI·추적한 자식과 background 종료를 확인합니다.
Codex는 공유 engine의 active turn·pending 입력·background도 확인합니다.
분리된 자식을 process group 검사만으로 종료 처리하지 않습니다.
근거가 부족하면 오류이며 종료 완료로 표시하지 않습니다.
시간 초과 뒤 강제 종료로 자동 전환하지 않습니다. 이 원칙의 예외는 운영자가 `shutdown --force`를 준 실행뿐입니다(위 shutdown).
PID 관찰의 Linux·macOS 차이는 provider module이 처리합니다.
실제 종료 확인은 판정 시점의 관찰입니다.
외부 주체가 옛 Codex thread로 새 입력을 보내도 seat를 자동 재점유하지 않습니다.
그 활동은 소유자 없는 활동으로 오류·진단에 표시합니다.

### Review 표시

```sh
agent-session review --job TOOL-012
agent-session review --clear
```

Leader는 Worker의 제출을 실제로 review하기 시작할 때 `review --job`으로 `leader.reviewing`을 씁니다.
관찰 도구는 이 값으로 Leader가 지금 review 중인 seat를 표시합니다.

| 입력 | 필수·기본값 | 처리 |
| --- | --- | --- |
| --job JOB_ID | clear와 택일 | 현재 seat에 배정되고 session이 있는 JOB으로 설정. 다른 JOB이면 교체 |
| --clear | job과 택일 | null로 해제. 이미 null이어도 성공 |
| --timeout SECONDS | 선택. 30초 | 전체 대기 제한 |

호출자는 Leader 또는 operator입니다. Worker는 role_denied, 비관리 agent는 caller_unbound입니다.
Leader가 없으면 session_unbound입니다.
같은 state 저장 안에서 Leader session_id·대상 배정·Worker session 존재를 다시 대조합니다.
그 사이 Leader가 바뀌면 target_changed입니다.
Seat session이 있어야 한다는 조건은 설정할 때만 검사합니다.

다음 경우 `reviewing`이 그 JOB을 가리킬 때만 null로 만듭니다.

| 시점 | 처리 |
| --- | --- |
| Leader가 그 JOB에 send하고 accepted | 발신 Leader가 현재 state의 Leader일 때만 해제 |
| 그 JOB의 Worker stop | 반납이면 반납 저장에서, 반납 보류면 별도 저장에서 해제 |
| Leader restart·stop | 새 Leader 게시 또는 반납으로 해제 |

Worker restart는 `reviewing`을 바꾸지 않습니다.

### watch

```sh
agent-session watch --all
agent-session watch --project NAME --minutes 30
```

CR이 in-progress인데 쉬고 있는 Worker를 깨우고 Leader에게 알립니다. 운영자가 주기적으로 실행하는 명령입니다. 관리 session(Leader·Worker)이 호출하면 role_denied이고 등록 밖의 agent가 호출하면 caller_unbound입니다(shutdown·resume과 같은 판정, 아무것도 바꾸기 전에 합니다). 한 번 실행하면 각 project의 Worker seat를 한 번씩 보고 끝납니다. 반복은 명령이 하지 않습니다.

| 옵션 | 필수·기본값 | 처리 |
| --- | --- | --- |
| --project NAME | --all과 택일 | 그 project만 |
| --all | --project와 택일 | 등록 파일의 모든 project |
| --minutes N | 선택. 30 | Worker가 쉬어도 되는 시간. 이 시간이 지나야 움직입니다 |
| --timeout SECONDS | 선택. 120 | 한 project의 전체 대기 제한 |

**실행 방식: cron을 고릅니다.** 운영자의 crontab에 한 줄을 둡니다(tmux socket이 기본 위치가 아니면 `--socket-name`·`--socket-path`를 앞에 붙입니다).

```
*/10 * * * * $HOME/.local/bin/agent-session watch --all
```

Board의 갱신 loop는 고르지 않습니다. Board는 사람이 열어 보는 화면이라 닫히면 감지가 멈추고, 여러 곳에서 열리면 같은 판정이 겹칩니다. 또 화면 도구가 Worker에게 메시지를 보내는 부수효과를 갖게 됩니다. cron은 Board와 무관하게 돌고 한 줄이면 설치됩니다. 실행 간격(10분)은 `--minutes`보다 짧아야 합니다. 쉬기 시작한 뒤 `--minutes`에 최대 간격만큼을 더한 때 움직입니다.

**쉬고 있음**: 다음이 모두 맞는 Worker입니다.

1. 배정한 CR이 in-progress이고 로컬 seat의 현재 run이 살아 있습니다. 원격 seat는 이 판정이 대상이 아니라 `skipped`(`remote_seat`)입니다.
2. turn이 끝났습니다. provider 관찰의 idle이거나, Claude가 background shell만 도는 상태로 보고합니다(`shell`).
3. 아무 입력도 없이 `--minutes`가 지났습니다. 시작점은 마지막 turn 종료(그 대화의 `Stop`·`StopFailure` hook 시각), 마지막으로 받은 메시지(`last_received`), watch가 마지막으로 turn 안에서 본 시각 가운데 가장 늦은 때입니다. 셋 다 없으면(Stop hook이 없는 Codex) watch가 그 run을 처음 본 시각입니다. 사용자 interrupt에는 Stop hook이 없을 수 있어 세 번째 값이 있습니다.
4. Leader의 회신을 기다리지 않습니다. Worker의 마지막 `send`가 Leader에게 간 것이고 그 뒤 받은 메시지가 없으면, 또는 Leader가 그 JOB을 `reviewing`으로 표시했으면 제출·보고 뒤 피드백 대기이므로 쉬고 있음이 아닙니다(`awaiting_leader`).
5. 자식 process가 CPU를 쓰며 일하지 않습니다. CLI의 자식 process(시작 직후 120초 안에 뜨는 MCP server 같은 helper 제외)의 CPU 시간(이미 끝난 자식의 시간 포함)이 직전 점검 뒤 한 core의 2% 이상 늘었으면 긴 test·build가 진행 중이므로 건드리지 않습니다(`working`). 자식이 있는데 직전 점검 기록이 없으면 비교할 수 없어 그 점검은 건너뜁니다(`observing`). 자식이 없거나 CPU를 쓰지 않으면 이 조건을 만족합니다.

turn이 진행 중이면 아무것도 하지 않습니다(`busy`). foreground 명령은 tool 시간 제한을 넘으면 background로 넘어가고 Worker는 turn을 끝냅니다. 그래서 `pgrep -f`를 담은 끝나지 않는 대기도 위의 쉬고 있음으로 모입니다.

**하는 일**: 메시지 전송과 기록뿐입니다. process에 신호를 보내지 않고 state·CR·Git 작업을 바꾸지 않습니다. 쉬고 있는 Worker에는 다음을 보냅니다.

- Worker에게 점검 메시지를 `send`로 한 번 보냅니다. Worker가 스스로 확인하고 판단하도록 CR 진행 상황을 확인해 이어서 하라고 쓰고, 근거를 담습니다: CR ID, 마지막 turn 종료·마지막 입력·마지막 보고(Leader에게 한 send) 시각, background 작업의 종류·명령, 자식 process의 pid·실행 시간·CPU 누적과 직전 점검 뒤 CPU 사용·명령(160자까지).
- Leader에게 같은 근거를 담아 알립니다.
- 발신자는 operator입니다. 메시지 첫 줄에 로컬 operator 입력임이 적히고 본문은 `[agent-session watch]`로 시작합니다. 사용자 승인이 아닙니다.

**반복 방지**: window option `watch`(`first_seen_at`·`busy_seen_at`·`children`·`children_at`·`resting.nudged_at`·`resting.notified_at`)에 보낸 기록을 둡니다. 같은 쉬는 상태가 이어지면 Worker에게는 다시 보내지 않습니다. Leader에게는 마지막 알림 뒤 `--minutes`가 지날 때마다 다시 알립니다. Worker가 점검 뒤 Leader에게 보고하거나 Leader에게서 메시지를 받으면 다음 쉼은 새 상태이므로 Worker에게 다시 보냅니다. 전달이 accepted가 아니면 기록하지 않아 다음 점검이 다시 시도합니다(Leader가 없거나 Worker가 준비 중인 경우 등). 기록은 run의 window에 있으므로 새 run은 처음부터 봅니다. 같은 project의 watch는 `agent/watch.lock`으로 동시에 하나만 돕니다(둘째는 `control_busy`를 그 project의 `error`로 보고하고 아무것도 보내지 않습니다).

결과는 `{threshold_minutes, projects: [{project, targets: [{slot, job_id, status, reason, actions}], error?}]}`입니다. status는 `skipped`·`busy`·`idle`·`awaiting_leader`·`observing`·`working`·`resting`·`error`입니다. 한 seat의 오류는 다른 seat를 막지 않고 그 target의 `error`로 보고합니다. 점검 대상이 없어도 exit 0입니다. 자식 process의 CPU 시간은 Linux에서만 읽습니다. 다른 OS에서는 자식 process를 읽지 못한 것으로 보고 메시지에 그렇게 적으며 CPU 조건은 자식이 없는 것으로 취급합니다.

## 8. CR과 실행 입력

공통 도구는 프로젝트 코드를 import하거나 실행하지 않습니다.
프로젝트별 차이는 등록(2절), 프로젝트 `AGENTS.md`, CR 본문으로 표현합니다.

### CR이 JOB을 겸합니다

CR 형식·상태·전이는 project-item skill과 `skills/project-item/references/cr.md`가 소유합니다.
공통 도구는 같은 저장소의 `tools/project-item`으로 CR을 조회·이동합니다.

| JOB 값 | CR 원본 |
| --- | --- |
| ID | CR ID |
| 작업 | 제목과 CR 파일 경로. 최초 prompt는 CR 파일을 읽으라고 지시합니다 |
| mode | `- Mode: write \| read-only`. 없으면 write |
| 작업 디렉토리 | `- Cwd: <seat 기준 상대 경로>`. 없으면 seat root |
| branch | Write이면 `cr/<ID>`. Read-only이면 없음 |
| 시작 기준 | `- Base: <commit> <ISO 시각>`과 state의 git_hash |

CR을 고치는 주체(Leader·Worker)와 하는 일은 [cr.md의 JOB으로 쓸 때](../../skills/project-item/references/cr.md#job으로-쓸-때)가 소유합니다.
agent-session은 start에서 todo→in-progress 이동과 `- Base:` 기록을 합니다.

역할 지침·읽을 문서는 CR 본문에 link와 문장으로 적습니다. Submodule 초기화는 start의 Git 준비가 합니다. 공통 형식은 이를 해석하지 않습니다.
`project-item move`의 허용 전이와 호출자 권한(`agent_session_only`·`role_denied`·`review_missing`)은 [project-item skill의 상태와 전이](../../skills/project-item/SKILL.md#상태와-전이)가 소유합니다.
이 명세는 호출자 판정만 소유합니다. `project-item`은 이 명세의 호출자 규칙(`agent_session.api.caller`)을 그대로 씁니다.

### 실행 입력

Start와 restart는 다음 실행 입력을 만듭니다.

| 항목 | 계약 |
| --- | --- |
| prompt_file | `agent/runs/<run_id>/prompt.md`. 공통 prompt, 인계 파일, CR 파일 경로와 그 파일을 읽으라는 지시를 포함 |
| settings_file | Claude만. 공통 코드가 `agent/runs/<run_id>/settings.json`을 씁니다: `crossSessionInbound: accept`와 등록 hook. Codex는 null |
| provider_name | Claude만. Tmux window 이름 |
| env | 공통 `AGENT_SESSION_*` |
| unset_env | 없음 |
| provider_args | `launch.args` 뒤에 역할의 `leader_args` 또는 `worker_args`. Provider가 실제 지원 인자인지 검사 |

공통 코드의 내부 등록·endpoint·새 대화 지정 인자는 `launch`의 인자가 덮어쓸 수 없습니다.
Provider-args는 모델·effort·기존 승인 권한·profile 같은 실제 지원 인자만 전달합니다.
공통 코드는 새 모델·effort·권한 우회 기본값을 정하지 않습니다.
Codex exec 전용 인자와 기존 thread 재개 인자는 거절합니다.
필수 env가 공유 engine의 실제 도구 문맥에 전달됐는지 provider별 인수에서 확인합니다.

### 인계 파일과 window 이름

- 인계 파일은 `<base>/agent/handoff/<slot>.md`입니다. Slot은 leader 또는 seat-N입니다.
- Restart는 대상 run 시작 뒤 갱신한 인계 파일을 요구합니다.
- Leader의 결정 대기는 `path_decide`, 다음 작업은 CR todo·in-progress가 소유합니다. 인계 파일은 목표와 맥락을 씁니다.
- Tmux window 이름은 Leader가 `<project>-leader`, Worker가 `<project>-seat<N>-<CR-ID>`입니다. 종료한 window는 `-exited-<run 앞 8자리>`가 붙은 이름으로 남고, 다음 run이 이어받으면 그 run의 이름으로 돌아옵니다.

## 9. 출력과 인수

Stdout은 `{"ok": true, "data": {...}, "error": null}` 형태의 JSON 하나입니다.
실패는 ok=false와 error의 code·message·details로 반환합니다.
Details는 남은 JOB·실행과 부수 효과 발생 여부를 포함합니다.
진단 로그는 stderr로 보냅니다.
예상하지 못한 예외는 `internal_error`입니다.
출력에는 예외 내용을 넣지 않습니다.
Details의 `diagnostic`에 `agent/diagnostics/`의 traceback 파일 경로를 줍니다.
프로젝트를 선택하기 전에 실패했거나 파일을 쓰지 못하면 `diagnostic`이 없습니다.
타입·누락·경로·배정·실행 오류는 상태 enum 대신 명령 오류로 반환합니다.

| Exit | 의미 |
| --- | --- |
| 0 | 명령의 정의된 결과 확인 |
| 2 | 입력·등록 오류 |
| 3 | 현재 배정·실행·Git 조건 충돌 |
| 4 | 시간 초과·전송 또는 종료 확인 불가 |
| 5 | 파일·외부 명령 실패 |

선택 timeout은 양의 정수 초 단위이며 각 명령 표의 전체 대기 제한입니다.
시작·종료·재시작은 NFS의 Git·guard 확인 시간을 포함해 기본 600초입니다.
전송은 작업 완료를 기다리지 않으므로 기본 30초를 유지합니다.
시간 초과 뒤 다음 단계를 새로 시작하지 않습니다.
이미 수행한 변경과 남은 실행은 결과에 표시하며 강제 종료·자동 재전송·자동 반납을 하지 않습니다.
입력 오류는 부수 효과 전에 반환합니다.
시작·중지 실패를 숨기려고 배정·파일을 삭제하지 않습니다.

| 검사 | 합격 기준 |
| --- | --- |
| V1 등록 | 현재 디렉토리로 정확한 등록 선택, 하위 경로·중복·등록 밖 처리 |
| V2 상태 | 자동 배정·CR 이동 경합 방지, CR/seat 대상 변경 거절, 늦은 요청이 새 실행을 변경하지 않음 |
| V3 실행 | 두 provider의 시작·전송·종료·재시작 확인. 내부 등록 실패와 연결 소실을 성공으로 처리하지 않음 |
| V4 Git | Seat 생성, 최초 준비·재시도·restart·보류 뒤 재배정의 기준 유지, read-only 규약 |
| V5 통합 | CR todo→배정(in-progress)→작업→제출→review 반복→merge→done→반납 |
| V6 중단·재개 | shutdown의 기록·마감·`--force`·알람, resume의 같은 대화 재개·재개 메시지, `resume --lost`의 판정·거절·근거 기록, 기록이 있는 slot의 새 대화 시작 |

Review 뒤 제출 hash가 바뀌면 새 hash를 다시 검토합니다.
V3의 restart는 새 UUID와 이전 실행 종료를 모두 확인합니다.
Self-control의 accepted 반환은 V3 완료가 아니며 최종 결과 파일과 실제 실행을 확인합니다.
Ignored·사용자 파일을 일괄 삭제하지 않습니다.
문서·예제 검사를 실제 프로그램 인수 PASS로 확대하지 않습니다.
