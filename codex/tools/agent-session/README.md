# Agent Session

`agent-session`은 등록 프로젝트의 Leader·Worker를 tmux에서 운영합니다.
공개 명령은 start·send·stop·restart입니다.
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
Base는 신뢰한 정확한 실제 경로에 미리 준비합니다.
배정할 seat 디렉토리가 없으면 start가 base의 origin을 clone합니다. 접속 인증은 사용자의 Git·SSH 설정을 따릅니다.
공통 도구는 프로젝트 코드를 import하거나 실행하지 않습니다. CR 파일과 등록 선언만 읽습니다.
CR 형식과 in-progress 이동은 같은 저장소의 `codex/tools/project-item`을 사용합니다.
Tmux 제어 권한은 host 명령 실행 권한입니다.
V1은 기존에 승인한 비sandbox 실행만 지원합니다.

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
| start | `agent-session start --job leader` 또는 `agent-session start --job TOOL-012` |
| send | `agent-session send --job leader "제출 commit과 CR ID"`. 다른 project의 Leader에게는 `agent-session send --project <project> --job leader "..."` |
| stop | `agent-session stop --job TOOL-012` |
| restart | `agent-session restart --job TOOL-012` |
| review | `agent-session review --job TOOL-012` 또는 `agent-session review --clear` |

Start는 todo의 CR을 in-progress로 옮기고 Worker seat를 자동 배정합니다.
Claude seat를 새로 clone하면 그 seat의 workspace trust를 기록합니다.
시작이 trust·login·권한 dialog에서 멈추면 `needs_user_action`(exit 3)과 `dialog`를 반환합니다. 사용자가 그 창에서 답한 뒤 같은 start를 다시 실행합니다.
다른 명령은 CR ID 대신 `--seat N`으로 현재 배정 대상을 지정할 수 있습니다.
옵션은 `agent-session --help`와 해당 하위 명령의 `--help`에서 확인합니다.
Restart 전에 해당 session이 `<base>/agent/handoff/<slot>.md`를 씁니다.
Restart는 이전 대화를 보존하고 그 인계 파일로 새 대화에 작업을 넘깁니다.
Seat·CR·Git 기준·branch는 유지합니다.
Worker 반납은 CR이 in-progress를 떠나고 seat의 결과가 origin에 게시된 뒤에만 합니다.
반납과 새 실행 뒤에는 종료가 확인된 옛 tmux window를 닫습니다. 반납 보류·pending·종료 미확인 window는 남깁니다.
Review는 Leader가 지금 review 중인 JOB을 state에 표시합니다. Feedback 전송·stop·Leader 교체 때 자동으로 지워집니다.
제어 예약이나 메시지 수락을 실제 종료·반납·작업 완료로 해석하지 않습니다.

모델·effort·기존에 승인한 권한 인자는 등록의 `launch`로 전달합니다.
`args`는 모든 session, `leader_args`·`worker_args`는 해당 역할에만 `args` 뒤에 붙습니다.
Binary를 직접 실행하므로 shell function·alias가 붙이던 인자는 적용되지 않습니다.
기존 비sandbox 승인 인자도 등록에 명시하며 공통 도구가 새 bypass 기본값을 추가하지 않습니다.
Codex TUI는 공용 daemon에 연결할 때도 `--cd <배정한 실제 cwd>`를 명시합니다.
Launcher의 cd만으로 remote daemon의 작업 경로를 추측하지 않습니다.

## 프로젝트 API와 검사

프로젝트 consumer는 `~/.local/lib/agent-session`을 import 경로로 사용합니다.
`agent_session.api`는 다음 읽기 전용 함수를 제공합니다.

| 함수 | 결과 |
| --- | --- |
| `read_state(cwd, config_path=None)` | 선택한 프로젝트의 현재 state snapshot |
| `check_binding(cwd, target, expected_session_id=None, config_path=None, socket=None)` | 현재 JOB·run·실제 session의 대조 결과와 ready·alive·종료 확인 |
| `liveness(cwd=None, config_path=None, socket=None)` | Session이 있는 slot마다 판정한 `session_id`와 `alive`·`stopped`·`unknown`. Provider를 호출하지 않음 |

Target은 `leader` 또는 현재 배정된 CR ID입니다.
두 함수는 업무·배정을 변경하지 않으며 제어 잠금을 획득하지 않습니다.
실행 관찰 실패를 빈 배정이나 종료 완료로 바꾸지 않습니다.

환경 표의 Python을 PY로 지정한 뒤 원본 repo에서 focused 검사를 실행합니다.

```sh
"$PY" -m pytest -q codex/tools/agent-session/tests
```

Machine load가 높으면 `AGENT_SESSION_TEST_TIMEOUT`(초, 기본 15)으로 fixture의 명령당 대기 한도를
늘립니다. `codex/tools/conftest.py`는 `--basetemp`가 없을 때 실행마다 `TMPDIR` 아래 전용 임시
디렉터리를 쓰고, 통과하면 지웁니다. 실패하면 조사를 위해 남깁니다.

이 검사는 실제 provider 연결과 실제 project의 인수 결과를 대신하지 않습니다.
