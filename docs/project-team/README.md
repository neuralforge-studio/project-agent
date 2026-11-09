# Project Team 제품 지도

이 문서는 project-team 제품의 전체 구성을 설명합니다.
각 기능의 계약과 실행 방법은 아래 표의 소유 문서가 설명합니다. 이 문서는 그 내용을 다시 쓰지 않고 연결합니다.
문서 소유 원칙은 정보의 원본과 문서 갱신입니다. 사실마다 원본 문서가 하나이고, 다른 문서는 원본을 가리킵니다.

## 목적과 구성

Project team은 등록한 프로젝트에서 Leader와 Worker 대화를 tmux로 운영합니다. Leader는 CR(변경 요청)을 만들고 판정합니다. Worker는 seat에서 CR을 수행합니다. 사용자는 결정 항목에 답합니다.

| 구성 요소 | 하는 일 | 소유 경로 |
| --- | --- | --- |
| `agent-session` (CLI) | Leader·Worker의 시작·전송·종료·재시작·review·shutdown·resume. 배정 state와 tmux 실행 근거 | `tools/agent-session/` |
| `project-item` (CLI) | CR과 결정 항목의 생성·조회·이동·검사. CR 형식의 실행 코드 | `tools/project-item/` |
| `project-board` (CLI) | 모든 프로젝트의 CR·결정·seat 상황을 보이는 tmux 화면. 결정 답변 전송 | `tools/project-board/` |
| `project-team` skill | Leader·Worker·운영자의 역할별 절차 | `skills/project-team/` |
| `project-item` skill | CR·결정 항목 사용 시점과 상태·전이, 형식 규칙 | `skills/project-item/` |
| 동작 명세 | 등록, state, start·stop·restart·shutdown·resume, CR과 JOB의 연결 | `docs/project-team/spec.md` |
| 설치 계약 | 설치·갱신·되돌리기·제거가 만들고 고치고 건드리지 않는 경로, 실행 중 HOME 쓰기 목록, 인수 test 명세. 설치기는 DIST-001 4단계에서 구현 | `docs/project-team/install-contract.md` |
| tmux 연결 | Board 열기·닫기 binding, status 표시, 결정 대기 알림 | `integrations/tmux/tmux_project_board.sh`, `project_board.conf`, `project_board_home_status.conf`, `tmux_decide_status.py` |
| 원격 seat 실행본 | SSH Worker seat에 보내는 Python helper와 guidance 문서 | `tools/agent-session/agent_session/remote.py`의 `source_archive()` |

## 구성 요소별 문서와 검증 위치

| 구성 요소 | 문서(원본) | test |
| --- | --- | --- |
| `agent-session` | [명세](spec.md), [README](../../tools/agent-session/README.md) | `tools/agent-session/tests/` |
| `project-item` | 형식·상태: [SKILL.md](../../skills/project-item/SKILL.md), [cr.md](../../skills/project-item/references/cr.md), [decide.md](../../skills/project-item/references/decide.md). 명령 사용: [README](../../tools/project-item/README.md)와 `--help` | `tools/project-item/tests/` |
| `project-board` | [README](../../tools/project-board/README.md). 화면 계약: [TUI 계획](../project-board-tui-plan.md) | `tools/project-board/tests/` |
| `project-team` skill | [SKILL.md](../../skills/project-team/SKILL.md) | 위 세 도구의 test와 skill 검사(아래) |
| tmux 연결 | 각 script의 머리말과 `project-board` README | `integrations/tmux/test_tmux_decide_status.py` |

명령과 옵션의 원본은 각 CLI의 `--help`입니다. README와 SKILL.md는 옵션을 다시 쓰지 않습니다.

## 공개 진입점

| 종류 | 진입점 |
| --- | --- |
| CLI | `agent-session`, `project-item`, `project-board`. 각 `bin/` 파일을 `~/.local/bin`에 link합니다. 세 파일은 `tools/python-launcher.sh`로 Python을 고릅니다. 설치본은 `PROJECT_AGENT_PYTHON`·`PROJECT_AGENT_PYTHONPATH`로 interpreter와 package 경로를 넘깁니다([설치 계약 6.1절](install-contract.md#61-python-선택)). |
| Python API | `agent_session.api`: 목록의 원본은 [api.py](../../tools/agent-session/agent_session/api.py)의 `__all__`이고 이름별 계약은 [명세 5절](spec.md#프로젝트-consumer용-python-api)이 기록합니다. `project_item.api`: 목록의 원본은 [api.py](../../tools/project-item/project_item/api.py)의 `__all__`이고 계층은 [project-item README](../../tools/project-item/README.md#layers-and-public-api)가 설명합니다. |
| Hook·controller | `agent_session.internal`의 `register_from_hook`(Claude SessionStart hook), `register_current`(Codex 초기 도구), `mark_process`, `run_controller`([명세 5절](spec.md#provider-내부-등록)) |
| 원격 seat | `python -m agent_session.remote_runtime`, `python -m agent_session.remote_bridge` |
| tmux option | 관리 window의 `@agent_session_*`([명세 3절](spec.md#실행-근거와-잠금)), Board의 `@project_board_*`(`@project_board_enabled`, `_managed`, `_pane`, `_width`, `_restore`, `_expanded`, `_config`, `_click_socket`) |
| 환경 변수 | 설치본 CLI에 `PROJECT_AGENT_PYTHON`, `PROJECT_AGENT_PYTHONPATH`를 줍니다. 관리 대화에 `AGENT_SESSION_BASE`, `AGENT_SESSION_CONFIG`, `AGENT_SESSION_SOCKET`, `AGENT_SESSION_UPLINK`을 줍니다. 관리 Claude CLI에는 `CLAUDE_DISABLE_ADOPT=1`도 줍니다. CLI가 끝날 때 대화가 background session으로 넘어가는 것을 막습니다([명세 3절](spec.md#background로-옮겨진-대화와-등록되지-않은-run의-종료-판정)). |
| 등록·state | 등록 파일 `project.json`과 `<base>/agent/state.json`([명세 2절](spec.md#2-등록과-프로젝트-선택), [3절](spec.md#3-statejson)) |

## 의존 관계

관계를 사용하는 쪽의 코드가 원본입니다. 이 절은 2026-11-09 코드에서 확인한 관계를 요약합니다. 관계를 바꾼 작업은 이 절도 함께 고칩니다.

### 현행

| 사용하는 쪽 | 쓰는 대상 | 위치 |
| --- | --- | --- |
| `project_item.registry` | `agent_session.api` | `registry.py`가 `sys.path`에 `agent-session`을 넣습니다. |
| `agent_session.jobs` | `project_item.api` | `jobs.py`의 `item_api()`가 `sys.path`에 `project-item`을 넣습니다. |
| `agent_session.remote_bridge` | `project_item.api` | `jobs.item_api()`로 가져와 함수 안에서 씁니다. |
| `project_board.model` | `agent_session.api`와 `project_item.api` | `model.py`가 두 도구를 `sys.path`에 넣습니다. |
| `project_board.answer` | `project_item.api` | |
| `project_board.tmux_control` | `agent_session.api` | |
| `integrations/tmux/tmux_decide_status.py` | `project_item.api` | 저장소 상대 경로로 `project-item`을 찾습니다. |

`agent-session`과 `project-item`은 서로를 씁니다(양방향). project-item을 쓰는 쪽은 `project_item.api`만 씁니다([경계 test](../../tools/project-item/tests/test_api_boundary.py)가 확인합니다). 이 표의 project-item 소비자 목록은 그 test의 `CONSUMERS`와 맞춥니다. agent-session을 쓰는 쪽은 `agent_session.api`만 씁니다([경계 test](../../tools/agent-session/tests/test_api_boundary.py)가 `tools`·`integrations/tmux`의 다른 도구 파일을 모두 검사하고, agent-session 안에서 다른 모듈의 밑줄 이름을 import하는 것도 막습니다).

### agent-session 내부 구성

관계를 사용하는 쪽의 코드가 원본입니다(2026-11-09 확인). `lifecycle`과 `suspend`는 서로를 import하지 않고, `launch_artifacts`·`windows`·`handoff`는 둘 중 어느 쪽도 import하지 않습니다. [test](../../tools/agent-session/tests/test_import_cycle.py)가 이 모듈들의 import 문(함수 안 포함)으로 확인합니다. 세 모듈의 함수는 [test](../../tools/agent-session/tests/test_run_modules.py)가 `Manager` 없이 직접 호출합니다. 다른 모듈(`suspend`, `remote_runtime`, `remote_lifecycle`)은 계속 `Manager`의 `_new_window`·`_launch`·`_sweep`·`_retire_name`·`_handoff_path`·`_fresh_handoff` 등으로 이 기능을 부르며, 이 method는 위 모듈 함수에 위임합니다.

| 모듈 | 책임 | 의존 방향 |
| --- | --- | --- |
| `cli` | 입력 해석, 결과 JSON 표현, 조립. `Manager`와 `Fleet`을 만들고 `Fleet`에 `Manager` class를 `manager_factory`로 넘깁니다(`_default_fleet`). start는 `Manager`를 만들기 전에 `lifecycle.check_start_arguments`를 부릅니다. | `lifecycle`, `suspend`를 지연 import합니다. |
| `lifecycle` | 통합 계층 `Manager`: start·send·stop·restart·review. 배정·제어의 순서, 잠금, state 기록, 실패 처리를 맡고 아래 세 모듈을 조립합니다. start 인자 규칙(`--prompt-file`은 Leader, `--seat`는 Worker JOB)의 원본인 모듈 함수 `check_start_arguments`를 소유하고 `Manager.start`가 부릅니다. | `suspend`, `launch_artifacts`, `windows`, `handoff`를 import합니다(`Manager`가 `SuspendMixin`을 상속). |
| `launch_artifacts` | run의 시작 산출물: prompt 문서, provider 입력(`prompt.md`, Claude `settings.json`), `launch.sh`, `controller.sh`, run 디렉터리 경로. 생성되는 command가 `agent_session.internal`의 이름을 부르는 곳이 여기입니다. 상태를 갖지 않고 아무것도 시작하지 않습니다. | `lifecycle`·`suspend`를 import하지 않습니다. project·provider·run context를 인자로 받습니다. |
| `windows` | 한 slot의 run을 담는 tmux window: 이름, 반납된 window의 재사용, 생성·current 지정, 이름 바꾸기, 정리(sweep), 시작 실패한 대기 pane의 정리. 종료 판정은 호출자가 넘긴 `observe`로 합니다. slot 제어 잠금은 호출자가 잡습니다. | `lifecycle`·`suspend`를 import하지 않습니다. `launch_artifacts.run_directory`를 씁니다. |
| `handoff` | slot의 인계 파일: 경로, 이번 run이 쓴 것인지(`launch.sh` 이후 갱신) 판단, restart의 `handoff_required`, 인계 문서 경로 검증. | `lifecycle`·`suspend`를 import하지 않습니다. `launch_artifacts.run_directory`를 씁니다. |
| `suspend` | `SuspendStore`(shutdown 기록), `SuspendMixin`(한 대상의 shutdown·resume 단계), `Fleet`(운영자 명령). | `lifecycle`을 import하지 않습니다. `SuspendMixin`이 기대는 `Manager` 멤버는 그 docstring이 나열합니다. |

### `sys.path` 조작 위치

도구 사이를 잇는 `sys.path` 조작은 도구마다 한 곳입니다. 실행 진입점(`agent_session.py`, hook·controller command, `remote.py` bootstrap)은 자기 도구만 넣습니다.

| 조작하는 쪽 | 넣는 도구 | 위치 |
| --- | --- | --- |
| `project_item.registry` | `agent-session` | `registry.py` module load |
| `agent_session.jobs` | `project-item` | `jobs.item_api()` 안 |
| `project_board.model` | `agent-session`, `project-item` | `model.py` module load |
| `integrations/tmux/tmux_decide_status.py` | `project-item` | `load_project_item()` 안 |

### 예외: 양방향 의존

`agent-session`과 `project-item`의 양방향 의존은 해소하지 않고 남깁니다(2026-11-09 Leader 판정, CR ARCH-005).

- **이유**: 두 방향은 서로 다른 계약을 씁니다. 등록과 호출자 규칙은 agent-session의 계약이고([동작 명세](spec.md) 2절·5절), CR 저장과 형식은 project-item의 계약입니다. 해소하려면 등록 해석을 별도 패키지로 빼야 합니다. 그러면 `agent_session.config`가 옮겨지고 원격 zip 배치와 hook의 import 경로가 바뀝니다. 이는 아래 실행 경로 계약을 바꾸는 일이라, 얻는 것보다 위험이 큽니다.
- **적용 범위**: `project_item.registry`가 `agent_session.api`를 module load 때 import하는 것과, `agent_session.jobs.item_api()`가 `project_item.api`를 함수 안에서 import하는 것입니다. 각 방향은 상대의 공개 모듈만 씁니다. agent-session은 project-item을 지연 import하므로 import 시점 순환이 없습니다.
- **영향받는 소비자**: `project_item.registry`와 이를 쓰는 project-item 전체, `agent_session.jobs`·`agent_session.remote_bridge`(`jobs.item_api()` 경유), project-board와 tmux script(위 표의 두 도구를 모두 가져옵니다), 원격 zip의 `agent-session/`·`project-item/` 배치.
- **검증의 한계**: [순환 방지 test](../../tools/agent-session/tests/test_import_cycle.py)는 `agent_session.api`·`project_item.api`·`project_board.model`·`agent_session.internal`을 새 interpreter에서 첫 import로 확인하고, agent-session이 project-item을 import 시점에 싣지 않는지도 봅니다. 이 네 순서만 보며, 다른 `sys.path` 구성이나 동적 import(`importlib`)가 만드는 순환은 보지 못합니다.

### 목표

CR ARCH-001이 합의한 목표는 모두 위 현행에 옮겼습니다(2026-11-09). 내용은 공개 인터페이스(ARCH-003 `project_item.api`, ARCH-004 `agent_session.api`), `sys.path` 조작 위치와 양방향 의존의 예외 기록(ARCH-005), agent-session 내부 구성(ARCH-006·ARCH-007)입니다. `project-board`는 다른 도구가 import하지 않으므로 CLI(`project-board`)와 tmux 연결이 공개 진입점입니다. 새 목표가 생기면 이 절에 적고, 적용한 뒤 현행으로 옮깁니다.

## 실행 경로 계약

떠 있는 Leader·Worker·hook·controller가 merge 뒤에도 동작하려면 다음 경로와 이름이 그대로여야 합니다. 이 목록이 원본입니다.

1. 세 `bin/` 경로(`tools/<도구>/bin/<도구>`)와 `tools/agent-session/agent_session.py`.
2. 도구 디렉터리 이름(`agent-session`, `project-item`, `project-board`).
3. `agent_session.internal`의 `register_from_hook`, `register_current`, `mark_process`, `run_controller`. Hook command, Codex 등록 command, `launch.sh`, `controller.sh`가 `tools/agent-session`의 절대 경로로 호출합니다.
4. `python -m agent_session.remote_runtime`과 `python -m agent_session.remote_bridge`.
5. 원격 zip의 배치. `agent-session/`, `project-item/`, `guidance/<저장소 상대 경로>`입니다. 어떤 guidance 문서를 싣는지는 `remote.py`의 `GUIDANCE_FILES`가 정하고, test가 skill 문서의 link와 맞는지 확인합니다.
6. tmux script는 저장소 상대 경로로 도구를 부릅니다(`tmux_project_board.sh`는 `../../tools/project-board/bin/project-board`, `tmux_decide_status.py`는 `tools/project-item`).

## 검증

검증 명령의 원본은 [저장소 README](../../README.md#검증)입니다.

- 형식 규칙(상태·전이·header·절·Outcome)과 코드의 일치는 `tools/project-item/tests/test_doc_contract.py`가 확인합니다.
- 원격 guidance 목록과 skill link의 일치는 `tools/agent-session/tests/test_remote.py`가 확인합니다.
