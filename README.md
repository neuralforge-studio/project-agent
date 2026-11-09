# project-agent

project-agent는 등록한 프로젝트에서 Leader와 Worker 대화를 tmux로 운영하는 도구 묶음입니다. Leader는 CR(변경 요청)을 만들고 판정하며, Worker는 seat에서 CR을 수행하고, 사용자는 결정 항목에 답합니다. 다른 직원에게 배포하는 독립 저장소입니다. 구성 요소와 계약의 사실은 [제품 지도](docs/project-team/README.md)가 원본이며, 이 문서는 그 내용을 복사하지 않고 위치만 안내합니다.

## 디렉터리 지도

| 디렉터리 | 내용 | 소유 문서 |
| --- | --- | --- |
| `tools/agent-session/` | Leader·Worker의 시작·전송·종료·재시작·review·shutdown·resume | [README](tools/agent-session/README.md), [동작 명세](docs/project-team/spec.md) |
| `tools/project-item/` | CR과 결정 항목의 생성·조회·이동·검사 | [README](tools/project-item/README.md) |
| `tools/project-board/` | 모든 프로젝트의 상황을 보이는 tmux 화면 | [README](tools/project-board/README.md) |
| `tools/` 바로 아래 | 세 CLI가 공유하는 `python-launcher.sh`와 저장소 수준 test(`conftest.py`, `test_*.py`)와 세 도구의 test가 함께 쓰는 test 전용 module(`tests/`, release에 넣지 않음) | [설치 계약 6.1절](docs/project-team/install-contract.md#61-python-선택) |
| `install/` | 설치기(`install`·`upgrade`·`rollback`·`uninstall`·`check`, `--dry-run`)와 격리 HOME 인수 test | [설치 계약](docs/project-team/install-contract.md) |
| `skills/project-team/`, `skills/project-item/` | Leader·Worker·운영자 절차와 CR·결정 항목 형식 | [SKILL.md](skills/project-team/SKILL.md), [SKILL.md](skills/project-item/SKILL.md) |
| `integrations/tmux/` | Board binding, status 표시, 결정 대기 알림. 설치본은 `project-agent.conf`를 읽습니다 | 각 script의 머리말, [project-board README](tools/project-board/README.md) |
| `docs/project-team/` | 제품 지도, 동작 명세, 설치 계약, 예제 JSON | [제품 지도](docs/project-team/README.md) |
| `docs/project-board-*` | Project Board 계획과 화면 시안 | [TUI 계획](docs/project-board-tui-plan.md) |
| `VERSION`, `CHANGELOG.md`, `tools/formats.json` | 버전 값, 변경 기록, 형식 버전 선언 | [버전 규칙](docs/project-team/release.md) |
| `docs/cr/` | 이 저장소의 CR | [CR 계약](skills/project-item/references/cr.md) |

## 검증

저장소 루트에서 실행합니다. `python`은 Python 3.10 이상이고 `pytest`가 있는 interpreter입니다. `project-board` test는 [requirements.txt](tools/project-board/requirements.txt)의 package가 필요합니다. `pytest-xdist`가 없으면 `-n 8`을 뺍니다.

```sh
python -m pytest -q -n 8 tools/agent-session/tests
python -m pytest -q tools/project-item/tests
python -m pytest -q tools/project-board/tests
python -m pytest -q integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py
python -m pytest -q -n 8 install/tests
```

- 다섯 명령은 서로 독립이며 pytest 설정 파일 없이 각 디렉터리의 `conftest.py`로 동작합니다.
- 다섯 명령을 모두 실행하는 것은 release를 낼 때 한 번입니다([버전 규칙 5절](docs/project-team/release.md#5-변경-기록과-release-절차)). 평소 변경은 아래 표에서 바꾼 경로에 해당하는 명령만 실행합니다(focused check와 직접 영향 회귀). 표의 의존은 [제품 지도의 의존 관계](docs/project-team/README.md#의존-관계)를 따릅니다. `origin/main`을 merge한 뒤에는 merge가 고른 명령의 입력을 바꿨을 때만 다시 실행합니다.

| 바꾼 경로 | 실행할 명령 |
| --- | --- |
| `install/**` | `install/tests` |
| `integrations/tmux/**` | 네 번째 명령, `tools/project-board/tests/test_tmux_control.py`, `install/tests` |
| `tools/python-launcher.sh`, `tools/formats.json`, `VERSION` | 네 번째 명령, `install/tests` |
| `tools/project-board/**` | `tools/project-board/tests` |
| `tools/project-item/**` | `tools/project-item/tests`. `project_item/api.py` 또는 CR·결정 형식(`cr.py`, `decide.py`, `kinds.py`)을 바꾸면 agent-session·project-board test와 네 번째 명령도 |
| `tools/agent-session/**` | `tools/agent-session/tests`. `agent_session/api.py`, state 형식(`state.py`), tmux option 이름을 바꾸면 project-item·project-board test와 `install/tests`도 |
| `tools/conftest.py`, 여러 도구가 함께 쓰는 test helper | 다섯 명령 모두 |
| `skills/**`, `docs/**`, `README.md`, `AGENTS.md` | 고친 문서의 상대 link 검사, `tools/test_distribution_boundary.py`. `skills/project-item`의 형식 문서를 바꾸면 `tools/project-item/tests/test_doc_contract.py`, 원격 guidance 문서(`skills/**`, `docs/project-team/spec.md`)를 바꾸면 `tools/agent-session/tests/test_remote.py`도 |
- Agent-session test는 seat 여럿이 같은 host에서 동시에 검증하는 평소 부하에서 같은 결과를 냅니다. 한도(`AGENT_SESSION_TEST_TIMEOUT`, 기본 120초)는 host가 이보다 심하게 느릴 때만 늘립니다. 자세한 사용법은 [agent-session README](tools/agent-session/README.md#프로젝트-api와-검사)가 설명합니다.
- 설치기 test(`install/tests`)는 격리 HOME에서만 설치기를 실행합니다. 개발 중 설치기를 실제 HOME에 실행하지 않습니다. `tmux`와 `git`이 필요하고 계약 8절의 T1~T32을 구현합니다.
- Test가 사용자 계정에 남기는 자원은 test가 끝나면(통과·실패·중단 모두) test 전 수준으로 돌아갑니다.
  - tmux server: 모든 test server는 [`tools/tests/tmux_test_server.py`](tools/tests/tmux_test_server.py)의 `claim`으로 이름을 받고 `release`로 끝냅니다. `release`는 server와 pane의 process, `/tmp/tmux-<uid>`의 socket 파일, Board가 server마다 만드는 `/tmp/project-board-<uid>-<server pid>`를 지웁니다. `claim`은 소유 pytest process가 사라지면(SIGKILL·SIGTERM 포함) 같은 정리를 하는 watchdog을 함께 띄웁니다. Test에서 `kill-server`를 직접 부르지 않습니다.
  - 임시 디렉터리: `tools/conftest.py`가 만드는 `TMPDIR/pt-*`는 통과한 run이 끝날 때 지웁니다. 실패·중단한 run의 것은 조사용으로 남고, 다음 run이 시작할 때 소유 run이 끝난 것 중 최근 5개만 남기고 지웁니다. 진행 중인 run의 것은 지우지 않습니다. 소유자 표시가 없는 옛 디렉터리는 24시간 넘게 손대지 않았을 때만 지웁니다. 규칙과 이유는 [`tools/tests/private_root.py`](tools/tests/private_root.py)가 소유합니다.
- CLI smoke: `tools/<도구>/bin/<도구> --help`.

## 관련 문서

- [제품 지도](docs/project-team/README.md): 구성 요소, 공개 진입점, 의존 관계, 실행 경로 계약
- [동작 명세](docs/project-team/spec.md): 등록, state, start·stop·restart·shutdown·resume
- [설치 안내](docs/install.md): 직원용. 전제, 한 줄 설치, 설치가 만드는 경로, 갱신·제거, tmux 연결
- [설치 계약](docs/project-team/install-contract.md): 설치·갱신·되돌리기·제거의 경계
- [버전 규칙](docs/project-team/release.md): 버전 값, 형식 버전과 호환 범위, git tag 이름, 변경 기록 작성
- [변경 기록](CHANGELOG.md): 버전별 CR ID 목록과 형식 변경 여부
- [AGENTS.md](AGENTS.md): 이 저장소에서 작업하는 agent의 규칙
