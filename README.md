# project-agent

project-agent는 등록한 프로젝트에서 Leader와 Worker 대화를 tmux로 운영하는 도구 묶음입니다. Leader는 CR(변경 요청)을 만들고 판정하며, Worker는 seat에서 CR을 수행하고, 사용자는 결정 항목에 답합니다. 다른 직원에게 배포하는 독립 저장소입니다. 구성 요소와 계약의 사실은 [제품 지도](docs/project-team/README.md)가 원본이며, 이 문서는 그 내용을 복사하지 않고 위치만 안내합니다.

## 디렉터리 지도

| 디렉터리 | 내용 | 소유 문서 |
| --- | --- | --- |
| `tools/agent-session/` | Leader·Worker의 시작·전송·종료·재시작·review·shutdown·resume | [README](tools/agent-session/README.md), [동작 명세](docs/project-team/spec.md) |
| `tools/project-item/` | CR과 결정 항목의 생성·조회·이동·검사 | [README](tools/project-item/README.md) |
| `tools/project-board/` | 모든 프로젝트의 상황을 보이는 tmux 화면 | [README](tools/project-board/README.md) |
| `tools/` 바로 아래 | 세 CLI가 공유하는 `python-launcher.sh`와 저장소 수준 test(`conftest.py`, `test_*.py`) | [설치 계약 6.1절](docs/project-team/install-contract.md#61-python-선택) |
| `skills/project-team/`, `skills/project-item/` | Leader·Worker·운영자 절차와 CR·결정 항목 형식 | [SKILL.md](skills/project-team/SKILL.md), [SKILL.md](skills/project-item/SKILL.md) |
| `integrations/tmux/` | Board binding, status 표시, 결정 대기 알림. 설치본은 `project-agent.conf`를 읽습니다 | 각 script의 머리말, [project-board README](tools/project-board/README.md) |
| `docs/project-team/` | 제품 지도, 동작 명세, 설치 계약, 예제 JSON | [제품 지도](docs/project-team/README.md) |
| `docs/project-board-*` | Project Board 계획과 화면 시안 | [TUI 계획](docs/project-board-tui-plan.md) |
| `docs/cr/` | 이 저장소의 CR | [CR 계약](skills/project-item/references/cr.md) |

## 검증

저장소 루트에서 실행합니다. `python`은 Python 3.10 이상이고 `pytest`가 있는 interpreter입니다. `project-board` test는 [requirements.txt](tools/project-board/requirements.txt)의 package가 필요합니다. `pytest-xdist`가 없으면 `-n 8`을 뺍니다.

```sh
python -m pytest -q -n 8 tools/agent-session/tests
python -m pytest -q tools/project-item/tests
python -m pytest -q tools/project-board/tests
python -m pytest -q integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py
```

- 네 명령은 서로 독립이며 pytest 설정 파일 없이 각 디렉터리의 `conftest.py`로 동작합니다.
- Agent-session test는 load가 높으면 `AGENT_SESSION_TEST_TIMEOUT`(초)을 지정합니다. 자세한 사용법은 [agent-session README](tools/agent-session/README.md#프로젝트-api와-검사)가 설명합니다.
- CLI smoke: `tools/<도구>/bin/<도구> --help`.

## 관련 문서

- [제품 지도](docs/project-team/README.md): 구성 요소, 공개 진입점, 의존 관계, 실행 경로 계약
- [동작 명세](docs/project-team/spec.md): 등록, state, start·stop·restart·shutdown·resume
- [설치 계약](docs/project-team/install-contract.md): 설치·갱신·되돌리기·제거의 경계
- [AGENTS.md](AGENTS.md): 이 저장소에서 작업하는 agent의 규칙
