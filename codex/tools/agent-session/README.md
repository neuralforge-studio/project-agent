# Agent Session

`agent-session`은 등록 프로젝트의 Leader·Worker를 tmux에서 운영합니다.
공개 명령은 start·send·stop·restart·review·shutdown·resume입니다.
상세 동작은 [명세](../../../docs/project-team/spec.md)가 소유합니다.
이 문서는 설치와 실행 진입점을 안내하며 실제 인수 완료를 뜻하지 않습니다.

## 설치 전제

신뢰한 유지보수 원본 하나를 선택합니다.
각 머신의 home에서 다음 symlink를 같은 원본에 연결합니다.

| 런타임 경로 | 연결 대상 |
| --- | --- |
| `~/.local/lib/agent-session` | `<원본>/codex/tools/agent-session` |
| `~/.local/bin/agent-session` | `<원본>/codex/tools/agent-session/bin/agent-session` |
| `~/.codex/skills/project-team` | `<원본>/codex/skills/project-team` |
| `~/.claude/skills/project-team` | `<원본>/codex/skills/project-team` |

기존 항목은 실제 연결 대상을 대조하며 다른 원본으로 덮어쓰지 않습니다.
`~/.local/bin`을 PATH에 포함합니다.
Launcher와 프로젝트 API는 같은 원본을 사용하며 상속한 PYTHONPATH에 의존하지 않습니다.

| 환경 | 사용할 Python |
| --- | --- |
| WSL | `~/python/.venv/bin/python` |
| Workstation | `/primehome/tools/Inhouse/Python3/latest/bin/python3`. Venv 사용 안 함 |
| macOS | 해당 환경에서 확인한 `python3` |

Tmux·Git·provider CLI를 준비합니다.
Base 디렉토리를 정확한 실제 경로에 미리 준비합니다.
Codex의 start는 새 Leader 실행 전에 등록 Base의 정확한 실제 경로를 자동으로 신뢰 설정에 기록합니다.
기존의 명시적 `untrusted`는 보존합니다.
신뢰 설정을 기록하지 못해 Codex CLI가 신뢰 화면에 멈추면 창 정보와 `dialog=workspace_trust`를 포함한 `needs_user_action`(exit 3)을 반환합니다.
Claude Base의 신뢰 설정은 미리 준비합니다.
배정할 seat 디렉토리가 없으면 start가 base의 origin을 clone합니다. 접속 인증은 사용자의 Git·SSH 설정을 따릅니다.
공통 도구는 프로젝트 코드를 import하거나 실행하지 않습니다. CR 파일과 등록 선언만 읽습니다.
CR 형식과 in-progress 이동은 같은 저장소의 `codex/tools/project-item`을 사용합니다.
Tmux 제어 권한은 host 명령 실행 권한입니다.
V1은 기존에 승인한 비sandbox 실행만 지원합니다.

Codex SSH Worker를 사용할 때는 원격 호스트에도 Python 3.11 이상·Git·tmux·로그인한 Codex CLI를 준비합니다.
Leader 호스트에서 등록한 SSH alias로 비대화형 접속과 원격 origin 접근이 가능해야 합니다.
SSH 서버는 Unix socket reverse forwarding을 허용해야 합니다.
원격 실행에 필요한 Python helper는 start가 전송합니다. 원격 project clone은 seat 준비가 수행합니다.
등록 형식과 원본·cache 경계는 [SSH Worker 계약](../../../docs/project-team/spec.md#codex-ssh-worker-seat)을 따릅니다.

## 등록과 실행

등록 원본은 `~/.codex/project.json` 또는 `~/.claude/project.json` 하나입니다.
두 경로를 사용하면 같은 파일로 연결합니다.
서로 다른 파일이면 `--config PATH`로 사용할 원본을 명시합니다.
형식은 [등록 예제](../../../docs/project-team/project-registry.example.json)를 따릅니다.
등록한 base 또는 seat 안에서 명령을 실행하면 현재 경로로 프로젝트를 선택합니다.
배정·대화 연결은 프로젝트별 `<base>/agent/state.json`에 저장합니다.
JOB은 등록의 `path_cr`에 있는 CR 파일입니다. Provider 실행 인자는 등록의 `launch`로 줍니다.

| 명령 | 예 |
| --- | --- |
| start | `agent-session start --job leader`, `agent-session start --job TOOL-012`, 지정 시 `agent-session start --job TOOL-012 --seat 3` |
| send | `agent-session send --job leader "제출 commit과 CR ID"`. 다른 project의 Leader에게는 `agent-session send --project <project> --job leader "..."` |
| stop | `agent-session stop --job TOOL-012` |
| restart | `agent-session restart --job TOOL-012` |
| review | `agent-session review --job TOOL-012` 또는 `agent-session review --clear` |
| shutdown | `agent-session shutdown --all` 또는 `--project NAME`. 서버를 내리기 전에 운영자가 실행합니다. `--timeout SECONDS`, `--force` |
| resume | `agent-session resume --all` 또는 `--project NAME`. 서버가 뜬 뒤 운영자가 실행합니다. shutdown 없이 서버가 내려갔으면 `--lost` |

Start는 todo의 CR을 in-progress로 옮기고 Worker seat를 자동 배정합니다.
`--seat N`을 지정하면 해당 Worker seat만 검사합니다. 지정한 seat가 비어 있지 않거나 안전 검사를 통과하지 못하면 배정을 거절합니다.
이미 배정한 CR의 재시도는 같은 seat만 지정할 수 있습니다. Leader에는 `--seat`를 사용할 수 없습니다.
Claude·Codex seat를 새로 clone하면 그 seat의 workspace trust를 기록합니다.
시작이 trust·login·권한 dialog에서 멈추면 `needs_user_action`(exit 3)과 `dialog`를 반환합니다. 사용자가 그 창에서 답한 뒤 같은 start를 다시 실행합니다.
다른 명령은 CR ID 대신 `--seat N`으로 현재 배정 대상을 지정할 수 있습니다.
옵션은 `agent-session --help`와 해당 하위 명령의 `--help`에서 확인합니다.
Restart 전에 해당 session이 `<base>/agent/handoff/<slot>.md`를 씁니다.
Restart는 이전 대화를 보존하고 그 인계 파일로 새 대화에 작업을 넘깁니다.
Seat·CR·Git 기준·branch는 유지합니다.
Worker 반납은 CR이 in-progress를 떠나고 seat의 결과가 origin에 게시된 뒤에만 합니다.
반납과 새 실행 뒤에는 종료가 확인된 옛 tmux window를 닫습니다. 반납 보류·pending·종료 미확인 window는 남깁니다.
새 실행은 같은 대상의 종료가 확인된 window를 먼저 이어받아(사용자가 붙인 pane은 그대로 남습니다) `-exited-` window가 갈라져 남지 않게 합니다. 이어받을 수 없을 때만 새 window를 만듭니다.
Review는 Leader가 지금 review 중인 JOB을 state에 표시합니다. Feedback 전송·stop·Leader 교체 때 자동으로 지워집니다.
제어 예약이나 메시지 수락을 실제 종료·반납·작업 완료로 해석하지 않습니다.

Shutdown과 resume은 Claude project만 처리하는 운영자 명령입니다. 현재 디렉토리가 아니라 등록 이름으로 project를 고릅니다.
Shutdown은 모든 대상이 쉬기를 한 마감 아래 기다린 뒤 종료하고 `<base>/agent/suspend.json`에 기록합니다. 반납하지 않습니다.
`--force`가 없으면 마감까지 쉬지 않은 대상을 종료하지 않고 보고합니다(exit 4). 기다리는 동안 tmux client에 마감 시각을 알리고 마감 전에 bell을 남깁니다.
Resume은 같은 대화 ID로 Leader, Worker 순서로 다시 열고 재개 메시지를 한 번 보냅니다. 실패한 Worker는 `start --job <CR>`로 새 대화를 시작합니다.
`resume --lost`는 shutdown 없이 서버가 내려간(정전·crash) 뒤 종료 기록이 없는 slot도 대상으로 삼습니다. 부팅 시각·대화 기록 갱신 시각·process·실행 포인터로 재부팅이 끝냈음을 확인한 slot만 같은 대화로 재개하고, 확인하지 못한 slot은 이유와 함께 `rejected`로 보고하며 배정을 바꾸지 않습니다([명세](../../../docs/project-team/spec.md#resume---lost)).

모델·effort·기존에 승인한 권한 인자는 등록의 `launch`로 전달합니다.
`args`는 모든 session, `leader_args`·`worker_args`는 해당 역할에만 `args` 뒤에 붙습니다.
Binary를 직접 실행하므로 shell function·alias가 붙이던 인자는 적용되지 않습니다.
기존 비sandbox 승인 인자도 등록에 명시하며 공통 도구가 새 bypass 기본값을 추가하지 않습니다.
Codex TUI는 공용 daemon에 연결할 때도 `--cd <배정한 실제 cwd>`를 명시합니다.
Launcher의 cd만으로 remote daemon의 작업 경로를 추측하지 않습니다.

원격 Worker의 작업 파일·셸·검증과 Codex daemon은 등록한 호스트에서 실행됩니다.
Board는 seat의 호스트를 표시하고 Leader 호스트의 SSH 표시 창으로 전환합니다.
SSH 표시 창이 끊겨도 원격 실행을 종료로 판정하지 않습니다.
연결을 복구한 뒤 같은 `start --job <CR-ID>`를 실행하면 같은 배정의 실행을 대조하고 표시 창을 다시 연결합니다.
Provider 실행 전 준비 실패는 원인을 고친 뒤 같은 start로 재시도합니다. 이전 controller 종료와 실행 전 근거를 확인할 수 있어야 합니다.
관찰할 수 없으면 `remote_unknown`(exit 4)과 기존 배정을 보존합니다.
원격 Worker가 `send --job leader`를 실행하면 CR snapshot의 Result만 원본에 돌려보냅니다.
원본 Result와 충돌하면 `remote_result_conflict`로 거절합니다. 원격 파일과 원본을 보존한 뒤 내용을 조정합니다.

## 모듈 구성

`lifecycle.Manager`는 배정과 제어의 순서·잠금·state 기록·실패 처리를 맡는 통합 계층입니다. run의 시작 산출물은 `launch_artifacts`, tmux window의 수명은 `windows`, 인계 파일은 `handoff`가 소유합니다. 모듈별 책임과 의존 방향은 [제품 지도](../../../docs/project-team/README.md#agent-session-내부-구성)가 원본입니다. 생성하는 command가 부르는 `agent_session.internal`의 이름은 [실행 경로 계약](../../../docs/project-team/README.md#실행-경로-계약)이 정합니다.

## 프로젝트 API와 검사

프로젝트 consumer는 `~/.local/lib/agent-session`을 import 경로로 사용합니다.
다른 도구는 `agent_session.api`만 import합니다. 공개 이름의 목록은 `api.py`의 `__all__`이고 이름별 입력·결과는 [명세 5절](../../../docs/project-team/spec.md#프로젝트-consumer용-python-api)이 기록합니다.
조회 함수는 업무·배정을 변경하지 않으며 제어 잠금을 획득하지 않습니다.
실행 관찰 실패를 빈 배정이나 종료 완료로 바꾸지 않습니다.

환경 표의 Python을 PY로 지정한 뒤 원본 repo에서 focused 검사를 실행합니다.

```sh
"$PY" -m pytest -q -n 8 codex/tools/agent-session/tests
```

테스트는 서로 독립이므로 `-n 8`로 병렬 실행합니다. 직렬 실행은 `-n 0`입니다. Fixture는 git 저장소를
pytest 프로세스(xdist worker)마다 한 번 만들고, 테스트마다 그 복사본을 씁니다.
Machine load가 높으면 `AGENT_SESSION_TEST_TIMEOUT`(초, 기본 15)으로 fixture의 명령당 대기 한도를
늘립니다. `codex/tools/conftest.py`는 `--basetemp`가 없을 때 실행마다 `TMPDIR` 아래 전용 임시
디렉터리를 쓰고, 통과하면 지웁니다. 실패하면 조사를 위해 남깁니다.
macOS의 Unix socket 경로 제한에 걸리면 `--basetemp=/tmp/as-test`처럼 짧은 임시 경로를 지정합니다.

이 검사는 실제 provider 연결과 실제 project의 인수 결과를 대신하지 않습니다.
