# Agent Session 동작 명세 v1

공개 CLI는 `agent-session` 하나입니다.
공개 명령은 start·send·stop·restart입니다.
구현 순서와 프로젝트별 이전 범위는 [계획](../project-team-plan.md)이 소유합니다.
현재 실행은 공통 구현과 Haroo 우선 전환입니다.
사용자가 2026-11-03에 승인한 Haroo D1·D2·D4를 적용합니다.

## 1. 명령과 대상

```sh
agent-session start --job leader
agent-session start --job JOB.md
agent-session send --job leader "작업 결과를 보고합니다."
agent-session send --job J-20261103-07 --file FEEDBACK.md
agent-session stop --seat 1
agent-session restart --job leader
```

Start는 --job 하나가 필수입니다.
나머지 대상 지정 명령은 --job과 --seat 중 정확히 하나가 필수입니다.
둘 다 입력하면 같은 대상을 가리켜도 오류입니다.
Leader는 등록 base에서 시작합니다.
Worker는 자동 배정한 seat에서 시작합니다.
JOB의 하위 작업 경로 기본은 seat 자체입니다.
작업 디렉토리·provider·run 값을 사용자가 다시 입력하지 않습니다.

Seat는 등록된 고정 작업 디렉토리이며 JOB이 끝나도 삭제하지 않습니다.
배정 변경은 같은 seat에 연결한 JOB이 바뀌는 것입니다.
같은 JOB의 feedback은 같은 session에 send합니다.
작업 완료 보고만으로 session을 자동 종료하거나 배정을 비우지 않습니다.
Leader가 stop으로 종료·반납한 뒤 새 JOB을 start하면 새 session을 만듭니다.
모든 restart는 기존 실행을 종료하고 새 대화로 교체합니다.
Seat·JOB·Git 기준·branch는 유지하며 이전 대화를 재개하지 않습니다.
이전 대화 기록은 보존합니다.
새 대화는 인계 문서와 현재 JOB으로 이전 작업을 이어받습니다.

Start는 leader 외의 --job 값을 파일 경로로만 해석합니다.
파일을 읽어 문서 내부의 JOB ID를 사용하며 파일명으로 추측하지 않습니다.
다른 명령은 --job 값을 ID로만 해석하며 JOB 파일로 자동 전환하지 않습니다.
특수 값 leader는 대소문자를 구분하며 Worker의 JOB ID로 사용할 수 없습니다.
이름이 leader인 파일은 ./leader로 지정할 수 있습니다.

JOB ID는 현재 state에서 정확히 한 seat를 찾아 지정합니다.
미배정·반납한 ID는 job_not_assigned 오류입니다.
여러 seat에서 같은 ID를 찾으면 상태 오류이며 임의로 고르지 않습니다.
Seat 방식도 선택 시점의 JOB ID와 실행을 확정한 뒤 제어 직전에 다시 대조합니다.
대상 확인과 제어는 해당 자리의 시작·종료·교체와 같은 제어 잠금으로 직렬화합니다.
그 사이 JOB·실행이 바뀌면 target_changed 오류이며 다른 대상으로 다시 해석하지 않습니다.
중지된 실행에 send하지 않습니다.

관리 ID는 base_path_key·project_id·run_id입니다.
Base_path_key는 등록의 경로 key이며 project_id는 project 문자열입니다.
Run_id는 프로그램이 새 실행에 부여하며 사용자 입력으로 받지 않습니다.
JOB ID는 Leader의 JOB 작성 단계에서 부여합니다. 생성 규칙은 8절이 소유합니다.
Provider의 실제 대화 ID와 tmux ID는 외부 도구가 발급한 연결값입니다.

Skill은 JOB·검증·review·commit message 작성 절차를 안내합니다.
개발·검증·commit·push·merge는 Leader와 Worker가 수행합니다.
공통 script는 이 작업을 자동 완료로 판정하지 않습니다.

## 2. 등록과 프로젝트 선택

등록 파일은 `~/.codex/project.json` 또는 `~/.claude/project.json`입니다.
[등록 예제](project-registry.example.json)는 base key와 project·provider·seats를 보여 줍니다.
Project는 유일한 문자열, provider는 claude 또는 codex, seats는 경로 문자열 배열입니다.
Project·경로는 비어 있지 않아야 합니다.
Base key는 절대 경로 또는 ~/로 시작하는 경로입니다.
Seats는 0~10개이며 같은 실제 base·seat 경로를 중복 등록하지 않습니다.
등록 외의 모델·권한·JOB·실행 상태를 이 파일에 추가하지 않습니다.

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
Seat 번호는 배열 순서의 0~9입니다.

프로젝트 선택을 위한 별도 옵션은 두지 않습니다.
내부 호출과 자동 등록은 선택한 base 또는 seat에서 실행합니다.
선택한 등록 파일·socket도 그대로 전달합니다.
현재 실행의 프로젝트가 선택 결과와 다르면 거절합니다.
활성 JOB 중에는 seat 배열을 삭제·재정렬하지 않습니다.
활성 실행 중에는 base·provider를 바꾸지 않습니다.

운영은 사용자 기본 tmux server를 사용합니다.
격리 시험용 `--socket-name NAME`과 `--socket-path PATH`는 상호 배타적입니다.
이 옵션을 사용한 후속 제어도 같은 socket을 지정합니다.

## 3. state.json

위치는 선택한 base의 `agent/state.json`입니다.
[상태 예제](state.example.json)는 Leader와 seat별 배정·통신 정보를 보여 줍니다.
Leader는 필요할 때 state.json과 JOB 문서를 직접 읽어 배정을 확인합니다.
실제 실행과 연결의 유효성은 각 제어 명령이 내부에서 검사합니다.

```json
{
  "leader": {
    "session_id": "11111111-1111-4111-8111-111111111111",
    "endpoint": "unix:///tmp/project-team-example/codex.sock"
  },
  "0": {"job_id": null, "git_hash": null, "session": null},
  "1": {
    "job_id": "J-20261103-07",
    "git_hash": "1111111111111111111111111111111111111111",
    "session": {
      "session_id": "22222222-2222-4222-8222-222222222222",
      "endpoint": "unix:///tmp/project-team-example/codex.sock"
    }
  },
  "2": {"job_id": "J-20261103-08", "git_hash": null, "session": null}
}
```

예제의 값과 주소는 설명용입니다.
Root는 leader와 등록 seat 수만큼의 연속한 숫자 key입니다.
Worker seat가 없으면 `{"leader": null}`입니다.

| 항목 | 의미 |
| --- | --- |
| leader | Leader의 session. 연결 전·반납 완료 후에는 null |
| N.job_id | Leader가 배정한 JOB. 미배정은 null |
| N.git_hash | 최초 pull 직후 hash. 미준비·비Git은 null |
| N.session | Worker의 session. 연결 전·반납 후에는 null |

Session의 값은 provider에 따라 다릅니다.

| Provider | 필수 필드 | 사용 |
| --- | --- | --- |
| Claude | session_id·message_to | 실제 대화 UUID와 ListAgents에서 확인한 SendMessage 대상 |
| Codex | session_id·endpoint | 실제 thread ID와 app-server 주소 |

Session의 각 값은 비어 있지 않은 문자열입니다.
Provider는 등록에서 읽으므로 state에 중복 저장하지 않습니다.
Claude UUID를 SendMessage.to로 가정하지 않습니다.
Claude 이름·ref는 전송 시 현재 목록과 실제 대화에 대조합니다.
Codex endpoint는 TUI와 전송이 사용하는 같은 서버입니다.

배정 시 JOB ID와 null hash·session을 기록합니다.
Provider 내부 등록은 자기 window의 실제 native binding만 기록합니다.
대상 제어 잠금을 가진 시작 controller가 현재 run과 binding을 대조한 뒤 state의 session을 게시합니다.
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
| 제어와 관찰 | stopping 여부, provider 실행 시도 여부, 등록 완료 여부, hook 관찰값, controller PID·생성 시각 |

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
죽은 server의 값과 복원한 창의 복사된 option은 현재 실행의 근거가 아닙니다.
Tmux 근거가 사라지면 state를 자동 삭제하거나 실행을 자동 채택하지 않습니다.
`agent/runs/<run_id>/`에는 prompt·settings·launch·hook 진단·제어 결과를 둡니다.
이 파일은 실행 산출물이며 배정의 두 번째 원본으로 사용하지 않습니다.

잠금 파일은 삭제로 해제하지 않고 열린 파일의 OS 잠금을 사용합니다.

| 잠금 | 경로·범위 |
| --- | --- |
| 배정 | agent/allocation.lock. 후보 선택과 예약에만 사용 |
| 대상 제어 | agent/control/leader.lock 또는 agent/control/seat-N.lock. 해당 대상의 start/send/stop/restart 직렬화 |
| 프로젝트 main Git | Falcon2 개인 repo의 state/main-git.lock. Base main 통합·CR commit/push 직렬화 |
| 업무 원본 | Falcon2 개인 repo의 state/jobs.lock 또는 Haroo .haroo-ops/lock |
| State 저장 | agent/state.lock. 최신 읽기·검사·원자 교체에만 사용 |

잠금 순서는 배정 → 대상 제어 → 프로젝트 main Git → 업무 원본 → state입니다.
필요 없는 중간 잠금은 생략하며 업무 잠금 안에서 main Git 잠금을 새로 획득하지 않습니다.
Main Git 잠금은 실제 base Git 변경에만 사용하며 feedback·Worker 검증을 기다리는 동안 유지하지 않습니다.
배정 중 사용 중인 대상 제어 잠금은 기다리지 않고 해당 후보를 건너뜁니다.
예약 뒤 배정 잠금은 풀며 대상 제어 잠금은 해당 제어가 끝날 때까지 유지합니다.
State 잠금 안에서 adapter·provider·외부 명령을 호출하지 않습니다.
업무 원본 잠금 안에서 대상 제어 명령을 호출하지 않습니다.
Read-state와 check-binding은 잠금을 획득하지 않는 읽기 전용 API입니다.
원자 교체한 snapshot을 읽고 외부 관찰 뒤 다시 읽어 JOB·run·연결 변경을 거절합니다.
따라서 Haroo verify가 업무 잠금 안에서 check-binding을 호출해도 잠금 순서를 뒤집지 않습니다.
Hook은 대상 제어 잠금을 다시 획득하지 않습니다.
Hook은 canonical state를 쓰지 않고 자기 window의 binding·관찰값만 갱신합니다.
시작 controller는 게시 직전에 현재 run·JOB·window·실제 연결을 다시 대조합니다.
늦은 hook이 옛 window를 갱신해도 새 실행의 state session을 덮어쓸 수 없습니다.

## 4. start

| 옵션 | 필수·기본값 | 처리 |
| --- | --- | --- |
| --job leader 또는 PATH | 필수 | Leader 시작 또는 JOB 파일을 읽고 Worker 자동 배정 |
| --prompt-file FILE | 선택. Leader 기본 역할 지시 | Leader 시작에만 허용. UTF-8 사용자 지시 파일 |
| --timeout SECONDS | 선택. 600초 | Git 준비와 실제 연결 확인을 포함한 전체 대기 제한 |

Worker는 JOB 문서를 지시 원본으로 사용하며 추가 prompt-file을 받지 않습니다.

### Leader

```sh
agent-session start --job leader
agent-session start --job leader --prompt-file REQUEST.md
```

Prompt 파일은 선택입니다.
생략하면 프로젝트 지침과 Leader 역할로 시작하고 사용자 지시를 기다립니다.
현재 Leader가 실행 중이거나 종료를 확인할 수 없으면 새로 시작하지 않습니다.
정상 종료가 확인된 이전 Leader는 명시적인 새 시작을 막지 않습니다.
시작 전 프로젝트의 check-workspace와 prepare-workspace를 base에 적용합니다.
Falcon2 base의 clean·미push 검사와 main 동기화는 이 경로가 소유합니다.
Falcon2는 dirty·미push이면 base 동기화만 건너뛰고 기존 작업을 보존한 채 시작합니다.
경로·repo·실제 소유권 오류와 동기화 생략 사유를 구분합니다.
Base 준비는 Worker의 JOB·branch·Git 기준을 새로 만들지 않습니다.

### Worker

```sh
agent-session start --job JOB.md
```

공식 JOB 전달 문서만 필수입니다.
역할·write/read-only 모드·범위·하위 작업 경로는 JOB에서 읽습니다.
같은 JOB의 기존 배정이 있으면 먼저 아래 재요청 규칙을 적용합니다.

1. 현재 프로젝트·JOB 승인·원본 경로를 확인합니다.
2. 미배정 seat를 번호순으로 확인합니다.
3. Check-workspace를 통과한 seat에 새 run·대기 tmux 창·현재 실행 포인터와 state 예약을 기록합니다.
4. Record-assignment를 호출합니다. 실패 시에도 run 포인터와 예약을 남겨 같은 호출부터 재개합니다.
5. Worker 시작 script가 최초 Git 준비를 수행합니다.
6. 프로젝트 guard와 세션 등록을 포함한 최종 prompt·settings를 만듭니다.
7. 대화형 CLI를 시작하고 자기 window의 native binding을 확인합니다. 시작 controller가 state에 게시하고 record-ready 뒤 시작 완료를 표시합니다.
8. Seat·JOB·연결 결과를 반환합니다.

사용 가능한 seat가 없으면 후보별 이유와 함께 오류를 반환합니다.
JOB 모드·범위·작업 경로·필수 연결 코드·guard 입력은 배정과 Git 변경 전에 검사합니다.
후보 확인과 배정은 자리별 제어와 짧은 state 잠금으로 경합을 막습니다.
JOB 하위 경로가 seat 밖이나 다른 등록 프로젝트로 나가면 거절합니다.
시작 실패는 JOB 배정과 이미 기록한 Git 기준을 유지합니다.

같은 JOB이 이미 배정돼 있으면 다른 seat를 배정하지 않습니다.
현재 실행 중이며 session 등록과 시작 완료를 확인했으면 현재 배정을 성공으로 반환합니다.
CLI 프로세스가 존재한다는 이유만으로 시작 성공을 반환하지 않습니다.
초기 등록이 아직 진행 중이면 남은 timeout 안에서 확인합니다.
Record-assignment가 실패한 예약이면 같은 run의 callback부터 다시 실행합니다.
이 호출은 기존 기준과 prepared 값을 초기화하지 않으며 성공 전 Git·provider 단계를 진행하지 않습니다.
Provider 실행 전 Git 준비가 실패한 사실을 현재 run의 실행 기록으로 확인하면 그 준비부터 재개합니다.
이 경우 Worker가 아직 작업하지 않았으므로 별도 Worker handoff를 요구하지 않습니다.
현재 JOB·기준·실패 기록을 사용하며 이미 기록한 기준과 branch 재시도 규칙을 따릅니다.
Provider 실행 여부가 불명확하면 미시작으로 추측하지 않고 오류를 반환합니다.
실제 종료가 확인됐으면 같은 seat에서 JOB을 인계한 새 대화로 시작할 수 있습니다.
Git 기준과 branch는 유지합니다.
이 경로도 restart와 같은 prepare-restart 검사와 인계 prompt 생성을 사용합니다.
같은 JOB 인계에는 새 후보용 clean 검사를 적용하거나 최초 pull을 반복하지 않습니다.
Worker의 기록한 미commit·미push 작업은 그대로 보존합니다.
Start는 중지된 배정의 새 대화 시작이며 살아 있는 실행을 종료하지 않습니다.
Restart는 현재 실행의 종료와 새 대화 시작을 한 제어로 수행합니다.
종료 여부가 불명확하면 멈춥니다.
완료·반납한 JOB ID를 새 JOB으로 재사용하지 않습니다.

### 최초 Git 준비

이 절차는 Worker 시작 script의 내부 처리입니다.
사용자가 별도 준비 명령을 실행하지 않습니다.

| JOB·저장소 | 최초 처리 | 반복 호출 |
| --- | --- | --- |
| write·Git | 아래 번호 절차 적용 | 기록한 기준과 JOB branch 확인. 다시 pull하지 않음 |
| read-only·Git | 기본은 현재 hash·commit 시각 기록. 승인한 Haroo는 최신 main 준비 뒤 기록. Branch 생성 없음 | 같은 기준 반환. 다시 동기화하지 않음 |
| 비Git | JOB에 Git 미해당 기록. State hash는 null | 같은 결과 반환. Git 명령 없음 |

다음 번호 절차와 branch 재시도 규칙은 write·Git JOB에만 적용합니다.
승인한 Haroo read-only는 같은 동기화·기준 기록을 사용하되 JOB branch를 생성하지 않습니다.

1. JOB·seat 소유권과 미보존 tracked·untracked 변경을 확인합니다.
2. 프로젝트 준비 함수의 before_sync를 호출합니다.
3. Main으로 전환하고 origin/main을 fast-forward로 갱신합니다.
4. After_sync로 공통·역할·JOB 추가 submodule과 기존 초기화 submodule을 현재 gitlink에 맞춥니다.
5. 전체 HEAD hash와 같은 commit의 committer 시각을 읽습니다.
6. 프로젝트 JOB writer로 hash·commit 시각·동기화 시각을 기록합니다.
7. 같은 hash를 state에 기록하고 JOB branch를 생성합니다.
8. 같은 기준을 writer에 다시 전달하여 프로젝트의 branch 준비 완료도 확인합니다.

공통 Git 명령은 `-c submodule.recurse=false`로 하위 저장소를 자동 갱신하지 않습니다.
Main 갱신은 `switch --no-overwrite-ignore main`, `fetch origin main`,
`merge --ff-only --no-overwrite-ignore origin/main` 순서입니다.
이는 origin/main의 fast-forward pull과 같은 갱신이며 ignored 파일 덮어쓰기도 거절합니다.
Ignored 파일 때문에 실패해도 파일을 삭제하거나 강제로 덮어쓰지 않습니다.
기준은 `rev-parse HEAD`와 `show -s --format=%cI HEAD`에서 읽습니다.
두 번 기록하는 기준의 hash·시각은 같아야 합니다.

기본 branch는 `job/<JOB-ID>`이며 프로젝트 규약은 연결 코드가 정합니다.
단계 실패 시 다음 단계를 실행하지 않습니다.
이미 JOB 기준이 있으면 pull을 반복하지 않습니다.
State hash가 null이면 기존 JOB 기준부터 기록합니다.
Branch가 없고 HEAD가 시작 hash이면 branch 생성부터 재개합니다.
현재 JOB branch에 시작 hash가 ancestor이면 기존 준비를 사용합니다.
다른 부분 완료 상태와 기준 불일치는 오류입니다.

Read-only의 JOB 기준은 있지만 state hash가 null이면 같은 hash를 복원합니다.
승인한 Haroo D2 정책은 read-only의 최초 준비도 최신 main을 동기화합니다.
Adapter의 before_sync는 이 경우 {"sync_main": true}를 반환합니다.
공통 Git helper가 같은 ignored 파일 보호로 동기화하고 hash·시각을 기록합니다.
JOB branch는 만들지 않으며 같은 JOB의 재시도에서 기준을 변경하지 않습니다.
어떤 모드든 JOB과 state의 기존 기준이 다르면 덮어쓰지 않고 오류를 반환합니다.
초기 Git 준비는 provider 시작 전이므로 배정한 run·seat·JOB 소유권을 대조합니다.
Submodule 준비·branch·제출·상위 gitlink는 프로젝트 연결 코드와 업무 도구가 담당합니다.
재요청에서 기존 기준이 있으면 프로젝트 준비도 기준과 대조하며 새 main 기준으로 바꾸지 않습니다.
Git 준비 중에는 해당 자리의 종료·교체도 직렬화합니다.

## 5. 내부 세션 등록과 실행 확인

### 프로젝트 consumer용 Python API

외부 운영 명령은 네 개로 유지합니다.
기존 프로젝트의 검증·JOB writer·CR 코드는 설치한 `agent_session.api`를 사용합니다.

| 함수 | 입력·결과 |
| --- | --- |
| read_state(cwd, config_path=None) | 현재 디렉토리로 프로젝트를 선택하고 state 원본 snapshot을 반환. 파일 생성·갱신 없음 |
| check_binding(cwd, target, expected_session_id=None, config_path=None, socket=None) | Target은 leader 또는 현재 JOB ID. 현재 배정·실제 실행·선택적 예상 session_id를 대조하여 seat·작업 경로·run_id·session과 종료 관찰 결과 반환 |

두 함수는 읽기 전용입니다.
호출자는 선택한 등록 파일과 socket을 전달할 수 있습니다.
전달하지 않은 등록 경로는 CLI와 같은 표준 경로 규칙을 적용합니다.
상태 손상·미등록·현재 소유자 불일치·관찰 불가를 구분해 공통 오류로 반환합니다.
오류를 빈 배정이나 종료 완료로 변환하지 않습니다.
Provider 시작 전 기준 기록은 이 live 대조를 요구하지 않습니다.
그 시점의 JOB·seat 예약 검사는 공통 start가 수행합니다.

### Provider 내부 등록

실제 provider 대화를 확인하고 자기 window에 native binding을 기록하는 처리는 필요합니다.
이 내부 등록은 canonical state의 session 게시와 구분합니다.
Claude SessionStart hook과 Codex 초기 도구 등록 코드가 호출합니다.
선택한 등록·작업 위치·현재 run을 전달하며 사용자에게 ID 입력을 요구하지 않습니다.
사용자가 호출하는 등록·이벤트 명령은 두지 않습니다.
Turn 관찰은 아래 provider 종료 확인에만 사용합니다.
이를 JOB 상태나 별도 state enum으로 저장하지 않습니다.

Claude는 시작 때 지정한 UUID와 실제 hook의 session·cwd·source를 대조합니다.
Codex는 실제 도구 문맥의 CODEX_THREAD_ID와 endpoint를 확인합니다.
내부 등록은 현재 run과 자기 window를 대조하고 그 window의 binding만 기록합니다.
시작 controller는 대상 제어 잠금 아래 현재 포인터와 binding을 검증해 canonical state에 게시합니다.
Record-ready가 끝나기 전에는 Worker의 일반 작업을 시작하지 않습니다.
새 CLI 실행 전에 부모의 중첩 실행 표시·세션 ID·메시지 IPC 환경을 제거합니다.
Claude의 CLAUDECODE·CLAUDE_CODE_SESSION_ID·CLAUDE_CODE_MESSAGING_*와 부모 CODEX_THREAD_ID가 대상입니다.
자격증명과 유효 사용자 설정은 일괄 제거하지 않습니다.
공통 코드가 모델·추론 강도·권한 우회를 고정하지 않습니다.
로그인·trust·권한 dialog로 시작이 멈추면 needs_user_action 오류를 반환합니다.
이 오류는 exit 3이며 배정과 생성한 창을 보존합니다.
기존에 승인한 프로젝트 설정을 사용하며 새 승인을 대신하는 키 입력을 보내지 않습니다.

### Claude 실행·전송·관찰

대화형 `claude --session-id <새 UUID> --settings <최종 파일>`로 시작합니다.
최초 prompt는 위치 인자이며 대화 재개 옵션을 사용하지 않습니다.
프로젝트의 provider_name이 있으면 현재 CLI의 이름 옵션 `-n`에 전달합니다.
최종 --settings에는 프로젝트 guard와 공통 SessionStart·Stop·StopFailure·SessionEnd hook을 합칩니다.
이 파일의 writer는 prepare-session 하나입니다.
공통 코드는 hook 조각을 제공하며 같은 파일을 다시 쓰지 않습니다.
`crossSessionInbound: "accept"`도 이 --settings 파일에 넣습니다.
사용자 설정 파일을 수정하거나 project/local settings의 accept에 의존하지 않습니다.
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
Canonical state는 시작 controller가 게시하며 등록 함수는 그 준비 결과를 기다립니다.
업무 record-ready writer는 provider process 밖의 시작 controller가 호출합니다.

Tmux 제어 권한은 host에서 명령을 실행하는 권한과 같습니다.
이 권한으로 run-shell·new-window를 실행할 수 있으므로 filesystem sandbox의 격리를 보장하지 못합니다.
Leader·Worker 모두 현재 설계에서 tmux 제어가 필요합니다.
V1은 기존에 승인한 비sandbox 실행만 지원합니다.
Sandbox가 적용된 profile은 시작 전에 unsupported_sandbox로 거절합니다.
지원 판정은 실제 적용할 argv와 profile·config를 합친 설정을 기준으로 합니다.
Binary를 직접 실행하므로 shell function·alias가 붙이던 인자는 상속하지 않습니다.
기존에 승인한 비sandbox 실행 인자는 adapter의 provider_args에 명시합니다.
공통 tool이 권한 우회 옵션을 추가하거나 사용자 설정을 자동 변경하지 않습니다.
현재 파일 쓰기 권한이나 tmux 접근이 없으면 needs_user_action입니다.
프로젝트 mode read-only는 업무 수정 금지이며 OS sandbox나 승인 prompt 정책과 구분합니다.

Codex에는 --settings가 없습니다.
Prepare-session의 Codex 결과는 settings_file=null과 검증한 argv 배열입니다.
설정은 `-c key=value`, 모델은 --model, profile은 --profile을 사용합니다.
0.166.0의 --profile NAME은 `$CODEX_HOME/NAME.config.toml`의 profile v2입니다.
기존 `[profiles.NAME]`를 이 파일과 같은 입력으로 가정하지 않습니다.
설치 때 실제 지원 형식을 확인하고 기존 값의 명시 override 또는 검토한 v2 파일로 옮깁니다.
공통 start가 사용자 config를 자동 변환하거나 존재하지 않는 profile을 생성하지 않습니다.
Effort는 `-c model_reasoning_effort="..."`로 전달합니다.
권한 입력은 --sandbox와 --ask-for-approval 또는 기존에 승인한 provider 인자입니다.
기존 Haroo exec_options의 모델·effort·권한을 이 대화형 인자로 변환합니다.
Exec 전용 JSON 출력·파일 입출력·resume 옵션은 전달하지 않습니다.
Codex env는 launcher뿐 아니라 `-c shell_environment_policy.set.KEY="value"`로 전달합니다.
제거 대상은 현재 filters 형식의 exclude 규칙으로 추가합니다.
예: `-c 'shell_environment_policy.filters."SOCSIM_USE_BALVIAN"="exclude"'`입니다.
Unset-env의 정확한 각 이름을 필터 key로 옮기며 wildcard를 사용하지 않습니다.
기존 profile·inherit·기본 제외·include allowlist를 임의로 넓히지 않습니다.
같은 설정 계층에 legacy exclude 배열과 filters를 혼합하지 않습니다.
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
CLI 전에 관리 창에 remain-on-exit를 설정합니다.
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

## 6. send

```sh
agent-session send --job leader "완료 보고입니다."
agent-session send --seat 1 --file FEEDBACK.md
```

### Send 옵션

| 입력 | 필수·기본값 | 처리 |
| --- | --- | --- |
| --job leader 또는 JOB_ID | seat와 택일 | State의 Leader 또는 해당 JOB의 Worker에게 전송 |
| --seat N | job과 택일 | 현재 그 seat에 배정된 Worker에게 전송 |
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

같은 JOB의 문서나 feedback을 다시 보내도 JOB ID·Git 기준·branch를 초기화하지 않습니다.
Send의 파일 입력은 메시지 전달이며 새 JOB 배정을 자동으로 수행하지 않습니다.
다른 JOB 문서를 보내는 것만으로 현재 JOB을 바꾸지 않습니다.
새 JOB 배정은 start 절차를 사용합니다.
발신 실행·현재 JOB과 state의 대상 session을 실제 연결과 대조합니다.
Session이 없거나 중지한 실행이면 보내지 않습니다.
수신 주소를 새로 확인해야 하면 같은 대화인지 검증하고 공통 저장 함수를 사용합니다.
동료 메시지임을 표시하며 사용자 승인으로 해석하지 않습니다.
Accepted·held는 읽음·동의·JOB 완료가 아닙니다.
전달 여부가 불명확하면 자동 재전송하지 않습니다.
일반 메시지에 tmux 키 입력과 화면 scraping을 사용하지 않습니다.

## 7. stop·restart

### Stop 옵션

| 옵션 | 필수·기본값 | 처리 |
| --- | --- | --- |
| --job leader 또는 JOB_ID | seat와 택일 | 해당 Leader 또는 배정 Worker 종료 |
| --seat N | job과 택일 | 현재 해당 seat의 Worker 종료 |
| --timeout SECONDS | 선택. 600초 | 정상 종료와 반납 조건 확인의 전체 대기 제한 |

### Restart 옵션

| 옵션 | 필수·기본값 | 처리 |
| --- | --- | --- |
| --job leader 또는 JOB_ID | seat와 택일 | 기존 실행을 종료하고 새 대화로 교체 |
| --seat N | job과 택일 | 기존 실행을 종료하고 해당 seat에서 같은 JOB의 새 대화로 교체 |
| --timeout SECONDS | 선택. 600초 | 인계 검사·기존 종료·새 대화 등록의 전체 대기 제한 |

```sh
agent-session stop --seat 1
agent-session stop --job leader
agent-session restart --job J-20261103-07
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
해당 CLI의 idle 또는 turn terminal을 확인한 뒤 관리 pane에 /exit와 Enter를 전달합니다.
키 입력은 이 종료 요청에만 사용하며 JOB 메시지·dialog 승인에 사용하지 않습니다.
현재 turn을 확인하지 못하면 임의 키를 반복하지 않고 timeout 오류를 반환합니다.
실제 종료를 확인한 뒤 결과를 반환합니다.
Worker는 JOB 완료 또는 명시 취소와 정리를 추가 확인합니다.
완료한 Git 수정 JOB은 실제 제출 hash의 review와 원격 반영도 확인합니다.
반납 조건도 맞으면 job_id·git_hash·session을 null로 만듭니다.
조건이 안 맞으면 종료만 수행하고 JOB·hash·대화 기록을 보존합니다.
이 경우 `stopped: true, released: false`와 이유를 반환합니다.
종료 성공·반납 보류는 exit 0입니다. 실제 종료 미확인은 exit 4입니다.
보존한 session은 종료한 대화의 이력이며 송신 가능을 뜻하지 않습니다.
Provider 대화 값과 주소는 종료 pane에서도 유지하며 재시작 때 다시 대조합니다.
종료 확인 전에 자리를 반납하지 않습니다.

Provider 실행 시도가 명시적으로 false인 예약도 stop할 수 있습니다.
이 경우 공통 코드는 현재 소유한 대기 pane의 PID·생성 정보·process group을 대조합니다.
공통 코드는 그 PID에 정상 SIGTERM을 요청하고 실제 종료를 확인합니다.
Native provider 관찰은 수행하지 않습니다. Provider를 시작한 적이 없기 때문입니다.
Check-release와 record-release의 업무 보존 조건은 그대로 적용합니다.
Haroo에서 취소 전이면 첫 stop은 released=false입니다.
Leader는 실제 종료 후 JOB을 취소하고 stop을 다시 호출해 반납합니다.
이 경로의 API binding은 session=null·ready=false·alive=false입니다.
Termination-confirmed는 대기 pane·PID·그룹이 모두 종료했을 때만 true입니다.
실행 시도가 true 또는 누락인 미등록 실행에는 이 경로를 적용하지 않습니다.

Leader도 프로젝트의 인계·업무 보존 조건을 check_release로 확인합니다.
Leader 반납이 완료되면 state.leader를 null로 만듭니다.
실제 종료만 완료하고 인계 조건이 부족하면 연결 이력을 보존하고 released=false로 반환합니다.
진행 중인 Worker 배정은 보존합니다.
Leader가 없는 동안 보고 전송은 수신 대상 없음으로 반환합니다.

Restart는 다음 순서로 새 대화로 교체합니다.

1. Prepare-restart로 인계 자료·보존할 작업·미push·background 조건을 확인합니다.
2. 기존 실행의 실제 종료를 확인합니다. JOB·seat를 반납하지 않습니다.
3. 같은 seat·JOB·Git 기준·branch를 유지하고 새 run을 발급합니다.
4. 최신 프로젝트 지침으로 prompt·settings·환경을 다시 생성합니다.
5. 인계 자료와 현재 JOB 원본을 최초 prompt에 넣고 새 대화를 시작합니다.
6. 시작 controller가 새 window의 실제 binding을 검증해 state에 게시합니다. Record-ready 뒤 시작 완료를 표시합니다.

이전 provider session_id와 새 session_id는 달라야 합니다.
종료 전에는 새 대화를 시작하지 않습니다.
새 등록 전에는 이전 연결을 송신 가능한 새 연결로 취급하지 않습니다.
시작 실패 시 JOB·Git 기준과 이전 대화 이력을 보존하며 오류를 반환합니다.
Provider의 이전 대화 기록을 삭제하거나 새 대화의 transcript로 합치지 않습니다.
인계 문서에는 이전 session_id와 실제 기록을 찾을 근거도 보존합니다.
인계 자료는 JOB 원본·진행 결과·미완료 항목·제출 hash·다음 행동을 포함합니다.
Falcon2의 30분 handoff 검사와 rules stamp 재생성은 프로젝트 연결 코드가 소유합니다.
이 30분·clean·미push 0 검사는 Falcon2 Leader에만 적용합니다.
Worker는 인계 자료에 적은 현재 HEAD·branch·미commit 파일·미push를 그대로 보존합니다.
Worker의 보존한 미완료 작업만으로 restart나 같은 JOB의 재start를 거절하지 않습니다.
Haroo Leader도 승인한 D1의 단일 restart를 사용하며 기존 동시 교대 경로는 제거합니다.
Leader restart는 기존 Worker 배정을 바꾸지 않습니다.
Restart에 파일 경로를 지정하거나 start에 JOB ID를 지정하는 자동 해석은 하지 않습니다.

### 종료 근거가 부족한 실행의 수동 복구

실행을 시도한 미등록 CLI는 자동으로 빈 자리로 바꾸지 않습니다.
Stop은 session_unbound를 반환하고 배정·Git 기준·기존 runtime 근거를 보존합니다.
등록한 CLI도 직접 /exit·crash·외부 종료 뒤 unload되면 마지막 background 근거가 없을 수 있습니다.
이 경우의 종료 판정도 unknown이며 같은 수동 확인 절차를 적용합니다.
이 경우 v1은 자동 복구를 지원하지 않습니다.
담당 Agent는 오류와 run 경로를 보고합니다. 운영자가 다음 절차를 수행합니다.

1. 해당 대상의 제어 잠금을 확보하고 state·프로젝트 업무 원본·run 파일을 보존하십시오.
2. 기록한 window·pane·server·PID 생성 정보를 실제 대상과 대조하십시오.
3. 실제 provider UUID를 시작 prompt의 run과 대조하십시오. 표시 이름이나 UUID 접두사로 선택하지 마십시오.
4. 해당 대화의 active turn·pending·background가 없고 pane·원래 PID·그룹이 종료했는지 확인하십시오.
5. 실제 대화의 cwd와 provider 설정도 확인하십시오. 확인하지 못한 사실은 unknown으로 남기십시오.
6. 등록 callback만 누락했고 모든 연결 근거가 일치하면 운영자가 기존 tmux binding과 state의 session을 복구하십시오. 그 뒤 정상 stop·프로젝트 취소·stop 순서로 처리하십시오.
7. 최초 Leader가 잘못된 cwd로 시작한 경우에는 그 대화를 채택하지 마십시오. 작업 부재와 종료 근거를 run의 startup-failure.json에 기록하십시오. State의 Leader가 null인 것을 확인한 뒤 그 실패 run의 current pointer만 해제하십시오. 원인을 수정하고 start하십시오.
8. 등록 binding이 일치하고 background 근거만 없으면 4·5번의 실제 확인을 완료하십시오. 운영자는 해당 run window에 last_background_clear를 기록하십시오. 값은 실제 session_id·run_id·thread/turns/list의 desc 첫 native turn ID입니다. 기록한 뒤 stop 또는 start를 다시 실행하십시오. 확인하지 못한 background를 빈 목록으로 기록하지 마십시오.
9. 분리 controller가 죽어 control_pending만 남으면 해당 controller의 PID·생성 정보를 대조하십시오. 운영자는 죽음을 확인한 뒤 control-result.json에 완료한 실패를 기록하고 그 run window의 control_pending만 false로 바꾸십시오. 그 뒤 정상 명령을 다시 실행하십시오. PID 기록이 없고 실행 여부도 확인하지 못하면 pending을 보존하십시오.

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

종료 확인 오류 뒤 입력란에 원래 /exit가 남으면 전체 stop을 반복하지 않습니다.
운영자는 같은 run·pane·idle과 원래 입력을 확인한 뒤 Enter 한 번으로 그 요청만 마칩니다.
그 뒤 기존 제어 결과와 실제 종료를 확인합니다.
입력이나 실제 실행을 확인하지 못하면 추가 키를 보내지 않습니다.

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
다른 대상 제어는 기본적으로 최종 결과까지 기다리고 반환합니다.

Claude 종료는 pane dead·CLI·추적한 자식과 background 종료를 확인합니다.
Codex는 공유 engine의 active turn·pending 입력·background도 확인합니다.
분리된 자식을 process group 검사만으로 종료 처리하지 않습니다.
근거가 부족하면 오류이며 종료 완료로 표시하지 않습니다.
시간 초과 뒤 강제 종료로 자동 전환하지 않습니다.
PID 관찰의 Linux·macOS 차이는 provider module이 처리합니다.
실제 종료 확인은 판정 시점의 관찰입니다.
외부 주체가 옛 Codex thread로 새 입력을 보내도 seat를 자동 재점유하지 않습니다.
그 활동은 소유자 없는 활동으로 오류·진단에 표시합니다.

## 8. 프로젝트 연결과 JOB

Base의 `agent/adapter.py`는 프로젝트 정책을 호출하는 설치 진입 파일입니다.
유지보수 원본이 별도 개인 repo에 있으면 그 파일을 설치 link로 연결할 수 있습니다.
별도 CLI나 사용자 등록 파일을 만들지 않습니다.

함수의 context는 프로그램이 확정한 base·seat_root·cwd·target·job·run_id·config_path·socket입니다.
Leader의 seat_root는 base이고 job은 null입니다.
이 값은 사용자용 입력이나 추가 JSON 원본이 아닙니다.

| 함수 | 입력·결과와 호출 시점 |
| --- | --- |
| job_file(job_id) | 공식 전달 문서의 절대 경로 반환 |
| read_job(path) | 공식 입력을 검증하고 업무 원본에서 아래 JOB 필드 반환 |
| check_workspace(context) | 배정 전 후보의 repo·origin·retained/protected ref·branch·background 검사. 읽기 전용. allowed/reasons 반환 |
| prepare_workspace(context, phase) | before_sync에 clone hook·설정 준비. after_sync에 공통·역할·추가·기존 초기화 submodule 준비 |
| record_assignment(context) | 새 state 예약 뒤 업무 원본에 JOB→seat 배정 기록. 실패해도 state 예약을 숨기지 않음 |
| prepare_session(context, hooks, prompt) | 최신 프로젝트 guard·인계 자료·내부 등록을 합친 실행 입력 반환 |
| record_baseline(context, baseline) | 지정된 업무 writer로 시작 hash·시각·branch 기록. Branch 생성 전후 동일 기준 전달 |
| prepare_restart(context) | 종료 전 handoff·미push·background 검사. 확인한 인계 자료 경로 반환 |
| record_ready(context, session) | 시작 controller가 현재 binding을 canonical state에 게시한 뒤 업무 이력·Leader ready 기록. 성공 뒤 controller가 시작 완료 값을 설정 |
| check_release(context) | 실제 종료 뒤 완료·명시 취소·review·원격 반영·정리 검사. allowed/reasons와 보존 근거 반환 |
| record_release(context, evidence) | 위 근거로 retained ref·취소 commit·반납 이력을 저장. 성공 후 공통 state 배정을 비움 |

모든 함수는 같은 내부 package 경계에서 호출하며 별도 CLI를 만들지 않습니다.
해당 프로젝트에 필요 없는 업무 callback은 빈 처리로 구현합니다.
Record-assignment와 record-release는 새 배정·실제 반납 때만 호출합니다.
Restart는 두 함수를 호출하지 않습니다.
Record-assignment에 실패한 같은 예약의 start는 이 callback부터 재개합니다.
업무 배정 완료를 확인하기 전 다음 준비를 진행하지 않습니다.
Haroo task.seat는 업무 snapshot이며 현재 배정의 원본은 공통 state입니다.
현재 작업의 두 값이 다르면 assignment_mismatch이며 자동 덮어쓰지 않습니다.
반납 뒤의 task.seat는 과거 이력으로만 읽습니다.
Window의 native binding·controller의 canonical state 게시·업무 ready를 구분합니다.
Record-ready가 실패하면 실제 연결은 보존하지만 시작 완료·업무 ready는 false입니다.
Check-binding은 이 차이를 반환하며 일반 send·재요청 start를 성공으로 처리하지 않습니다.
Record-ready의 현재 연결 확인은 이미 기록한 session과 현재 run 포인터를 사용합니다.
같은 start의 재요청은 해당 실행이 실제로 연결돼 있으면 같은 run·session에서 record-ready만 재시도합니다.
이 재시도는 새 대화를 만들거나 최초 Git 준비를 다시 수행하지 않습니다.
성공한 뒤에만 시작 완료를 설정하며 연결 소실은 성공으로 처리하지 않습니다.
업무 writer는 같은 JOB·run의 재호출에 같은 결과를 내며 이전 완료 사실을 덮어쓰지 않습니다.
Record-release 실패 시 공통 배정은 보존합니다.
Retry는 보존 근거를 대조하여 업무 기록 완료부터 재개합니다.
새 lease나 별도의 활성 session 원본을 프로젝트 상태에 발급하지 않습니다.

Mode는 write 또는 read-only이며 cwd는 seat 기준 상대 경로입니다.
기본 cwd는 `.`이며 scope·checks·submodules는 문자열 배열입니다.
Submodules 기본값은 빈 배열이며 추가 경로는 seat 내부의 실제 submodule만 허용합니다.
Prepare-workspace는 공통 pull을 다시 수행하지 않습니다.
Read-only의 공통 기본은 준비 확인만 수행하며 ref를 바꾸지 않습니다.
승인한 Haroo는 before_sync의 sync_main=true로 최초 준비 때 공통 Git helper에 동기화를 요청합니다.
기존 기준이 있으면 이 요청도 다시 pull하거나 branch를 생성하지 않습니다.
Leader base의 프로젝트 준비는 Worker mode와 분리합니다.
업무 역할과 settings의 Leader/Worker 구분을 혼동하지 않습니다.
팀 settings와 OWNERS 경로 기준은 하위 cwd가 아니라 seat clone root입니다.
선택적 provider_name은 프로젝트의 기존 대화 이름이며 tmux 창 표시 이름과 구분합니다.
Approved는 기존 사용자 지시와 프로젝트 정책으로 판정한 boolean입니다.
Baseline은 미준비면 null이며 준비 후 base_hash·base_commit_time·synced_at·branch를 포함합니다.
Read-only·비Git의 branch는 null입니다.
내부 등록 hook은 같은 설치 package의 함수를 호출합니다.
별도 callback script나 사용자가 호출할 등록 CLI를 추가하지 않습니다.
Check-release는 완료 또는 명시 취소가 기록됐고 정리도 확인했을 때만 allowed를 true로 반환합니다.
완료한 Git 수정 JOB은 실제 제출 hash의 review와 필요한 원격 반영도 통과해야 합니다.
위 JOB 인수 조건은 Worker에 적용합니다.
Job=null인 Leader에는 프로젝트의 handoff·checkpoint·업무 보존 조건을 적용합니다.

Prepare-session의 결과는 다음과 같습니다.

| 항목 | 계약 |
| --- | --- |
| prompt_file | UTF-8 최초 prompt 절대 경로. Restart 때 현재 JOB·인계를 포함해 재생성 |
| system_prompt_file | 선택. Claude의 --append-system-prompt-file 원본. 최초 사용자 prompt와 구분 |
| settings_file | Claude 최종 --settings 경로. Codex는 null |
| provider_name | 선택적 native 대화 이름. Tmux 창 이름과 구분 |
| env | 프로젝트가 설정할 환경변수 이름→문자열 |
| unset_env | 제거할 실제 환경변수 이름 배열. Shell wildcard 문자열을 실행하지 않음 |
| provider_args | 현재 provider CLI에서 검증한 argv 문자열 배열. Shell 문자열로 합치지 않음 |

Falcon2 env는 FC2_SESSION·FC2_SCRATCH와 해당 역할의 socsim PATH를 보존합니다.
CLAUDE_CODE_TMPDIR는 launcher와 최종 --settings의 env에 같은 값을 기록합니다.
Falcon2 unset-env는 SOCSIM_USE_BALVIAN·SOCSIM_RUNTIME_FLAVOR 두 이름으로 한정합니다.
다른 SOCSIM 설정과 사용자 TMPDIR는 변경하지 않습니다.
공통 코드의 내부 등록·endpoint·새 대화 지정 인자를 adapter가 덮어쓸 수 없습니다.
Provider-args는 모델·effort·기존 승인 권한·profile 같은 실제 지원 인자만 전달합니다.
공통 코드는 새 모델·effort·권한 우회 기본값을 정하지 않습니다.
Codex exec 전용 인자와 기존 thread 재개 인자는 거절합니다.
필수 env가 공유 engine의 실제 도구 문맥에 전달됐는지 provider별 인수에서 확인합니다.
Launcher env만 맞다는 이유로 이 검사를 통과시키지 않습니다.

### JOB ID 생성 규칙

이전 명세의 Leader 부여·재사용 금지 규칙을 다음 형식으로 구체화합니다.

| 항목 | 규칙 |
| --- | --- |
| 형식 | J-YYYYMMDD-NN. 예: J-20261103-07 |
| 날짜 | JOB 생성 시 Leader 실행 머신의 로컬 날짜. 생성 시각은 시간대와 함께 JOB 원본에 기록 |
| 순번 | 같은 프로젝트·같은 날짜의 기존 ID 중 최대값 + 1. 첫 값은 01 |
| 자리 수 | 최소 두 자리. 01~99 다음은 100이며 일일 99개로 제한하지 않음 |
| 유일 범위 | 선택한 프로젝트 안에서 유일. 다른 프로젝트는 같은 ID 사용 가능 |
| 보존 | 완료·취소 JOB도 원본을 보존하며 ID를 재사용하지 않음 |

Leader가 JOB을 작성할 때 지정된 프로젝트 JOB writer가 ID를 부여합니다.
Writer는 프로젝트 잠금 아래 보존한 JOB 원본을 조회하고 ID를 정한 뒤 원본을 배타적으로 생성합니다.
원본 조회는 파일명만이 아니라 기록된 JOB ID를 기준으로 합니다.
동시에 생성해도 같은 ID를 확정하지 못하도록 잠금과 중복 검사를 함께 사용합니다.
별도 카운터 필드를 state에 추가하지 않습니다.
Start는 이미 원본에 기록한 ID를 읽습니다.
ID가 없으면 입력 오류이며 임의 ID를 부여하지 않습니다.
새 규칙은 전환 후 만드는 JOB에 적용하며 과거 JOB ID를 일괄 변경하지 않습니다.
기존 미완료 JOB의 ID는 프로젝트 연결 코드가 유지할 수 있습니다.

JOB 업무 원본과 전달 문서는 프로젝트별로 구분합니다.

| 프로젝트 | 업무 원본 | start에 전달할 문서 |
| --- | --- | --- |
| Falcon2 | 개인 운영 repo의 state/jobs Markdown | 같은 공식 JOB 파일 |
| Haroo | 기존 .haroo-ops/state.json의 tasks | Task 원본에서 생성한 .haroo-ops/jobs/<JOB-ID>.md |

Haroo의 공통 job_id는 task_id와 같은 값입니다.
Read-job은 생성 문서를 별도 업무 원본으로 쓰지 않고 현재 task와 대조합니다.
업무 변경·기준 기록은 지정한 원본 writer를 사용하며 전달 문서도 다시 생성합니다.
파일 입력은 job-file 함수가 반환한 공식 문서와 같아야 합니다.
JOB을 seat마다 복사하거나 정리 때 삭제하지 않습니다.
Commit 양식은 summary·reason·Job·Validation을 포함하고 프로젝트 규약을 우선합니다.
실제 검증 결과를 만들어 넣지 않습니다.

### JOB 전달 형식

[JOB 예제](job.example.md)는 공통 assets/job.md의 목표 형식입니다.
별도 JSON Schema나 YAML parser를 요구하지 않습니다.
Markdown의 첫 json code block을 입력 metadata로 사용합니다.
필수 key는 job_id·role·mode·cwd·task·scope·checks·branch·approved·baseline입니다.
Created-at·submission·review·integration도 아래 기록 key로 포함합니다.
선택 key submodules의 기본은 빈 배열입니다.
Job-id·role·task는 비어 있지 않은 문자열입니다.
Branch는 write·Git이면 프로젝트의 JOB branch 이름이며 그 외는 null입니다.
날짜는 timezone을 포함한 ISO 8601 문자열입니다.
공통 코드는 approved=true와 비어 있지 않은 승인 근거 절만 검사합니다.
공통 코드가 자연어의 실제 승인 여부를 판정하지 않습니다.
Leader가 사용자 승인과 범위를 확인하고 프로젝트 writer가 그 근거를 기록합니다.
Adapter는 프로젝트의 구조화한 승인 원본이 있으면 그 값도 대조합니다.
기존 자연어 JOB을 mode·cwd로 추측하지 않습니다.
기존 미완료 문서는 프로젝트 writer가 근거를 확인해 명시 metadata를 채운 뒤 사용합니다.
Falcon2 metadata의 cwd·scope·checks가 해당 JOB 입력의 유일한 원본입니다.
본문의 쓰기 범위·gate 표시는 이 값에서 생성하며 별도 수동 원본으로 편집하지 않습니다.
Fc2conf는 역할의 기본 cwd·허용 경로·submodule 기본값을 소유합니다.
JOB writer는 이 기본값으로 유효한 cwd를 정하며 명시한 JOB 값은 역할 허용 범위 안에서만 사용합니다.
역할 정책은 허용 범위이며 확정한 JOB 값과 같은 종류의 원본이 아닙니다.
Falcon2 template는 이 metadata와 기존 승인 근거·설명 본문을 포함합니다.
Haroo 전달 문서는 이 형식으로 생성하지만 task 원본보다 우선하지 않습니다.

| 기록 key | 값·writer |
| --- | --- |
| created_at | 생성 시각. Timezone 포함 ISO 8601. JOB 생성 writer가 기록 |
| submission | 미제출은 null. 제출 후 head·branch·remote_ref·published_at·checks·waiver. Worker 결과를 프로젝트 writer가 기록 |
| review | 미검토는 null. Head·reviewer·verdict(accepted/feedback)·at·evidence. Leader review writer가 기록 |
| integration | 미통합은 null. Head·target_ref·published_at·checks·waiver. Leader가 실제 main 반영과 gate를 기록 |

Checks의 각 결과는 command·head·result·evidence를 포함합니다.
Waiver는 없으면 null이며 있으면 승인된 rule과 근거 경로를 기록합니다.
반납 판정은 실제 branch·원격 ref와 이 기록의 hash를 대조합니다.
Falcon2는 같은 공식 JOB metadata에 이 기록을 저장합니다.
Haroo는 기존 task 결과·review·인수 필드가 원본이며 adapter가 위 기록으로 변환합니다.
Read-only는 submission·integration 없이 현재 기준의 결과와 Leader 인수로 반납할 수 있습니다.
이를 쓰기 JOB의 branch 게시나 merge 완료로 위조하지 않습니다.

## 9. 출력과 인수

Stdout은 `{"ok": true, "data": {...}, "error": null}` 형태의 JSON 하나입니다.
실패는 ok=false와 error의 code·message·details로 반환합니다.
Details는 남은 JOB·실행과 부수 효과 발생 여부를 포함합니다.
진단 로그는 stderr로 보냅니다.
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
| V2 상태 | 자동 배정·JOB ID 생성 경합 방지, JOB/seat 대상 변경 거절, 늦은 요청이 새 실행을 변경하지 않음 |
| V3 실행 | 두 provider의 시작·전송·종료·재시작 확인. 내부 등록 실패와 연결 소실을 성공으로 처리하지 않음 |
| V4 Git | 최초 준비와 중단 재시도에서 기준 유지. Read-only·비Git·submodule 규약 보존 |
| V5 통합 | 배정→작업→제출→review 반복→merge→정리→종료 뒤 반납. 기존 guard·CR·직접 consumer 보장 유지 |

Review 뒤 제출 hash가 바뀌면 새 hash를 다시 검토합니다.
V3의 restart는 새 UUID와 이전 실행 종료를 모두 확인합니다.
Self-control의 accepted 반환은 V3 완료가 아니며 최종 결과 파일과 실제 실행을 확인합니다.
Ignored·사용자 파일을 일괄 삭제하지 않습니다.
문서·예제 검사를 실제 프로그램 인수 PASS로 확대하지 않습니다.
