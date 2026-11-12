# project-agent

project-agent는 등록한 프로젝트에서 Leader와 Worker 대화를 tmux로 운영하는 도구 묶음입니다. Leader는 CR(변경 요청)을 만들고 판정하며, Worker는 seat에서 CR을 수행하고, 사용자는 결정 항목에 답합니다. 다른 직원에게 배포하는 독립 저장소입니다. 구성 요소와 계약의 사실은 [제품 지도](docs/project-team/README.md)가 원본이며, 이 문서는 그 내용을 복사하지 않고 위치만 안내합니다.

## 디렉터리 지도

| 디렉터리 | 내용 | 소유 문서 |
| --- | --- | --- |
| `tools/agent-session/` | Leader·Worker의 시작·전송·종료·재시작·review·shutdown·resume | [README](tools/agent-session/README.md), [동작 명세](docs/project-team/spec.md) |
| `tools/project-item/` | CR과 결정 항목의 생성·조회·이동·검사 | [README](tools/project-item/README.md) |
| `tools/project-board/` | 모든 프로젝트의 상황을 보이는 tmux 화면 | [README](tools/project-board/README.md) |
| `tools/` 바로 아래 | 세 CLI가 공유하는 `python-launcher.sh`, 시동 번들을 읽는 `bundle_boot.py`와 저장소 수준 test(`conftest.py`, `test_*.py`)와 세 도구의 test가 함께 쓰는 test 전용 module(`tests/`, release에 넣지 않음) | [설치 계약 6.1절](docs/project-team/install-contract.md#61-python-선택) |
| `tools/tests/perf/` | 두 실행본(기준·후보)을 같은 격리 환경에서 번갈아 실행해 명령·Board·상태줄의 시간과 process 수를 비교하는 개발 도구(release에 넣지 않음). 사용법은 `perf_bench.py` 머리말 | [perf_bench.py](tools/tests/perf/perf_bench.py) |
| `install/` | 설치기(`install`·`upgrade`·`rollback`·`uninstall`·`check`, `--dry-run`)와 격리 HOME 인수 test | [설치 계약](docs/project-team/install-contract.md) |
| `skills/project-team/`, `skills/project-item/` | Leader·Worker·운영자 절차와 CR·결정 항목 형식 | [SKILL.md](skills/project-team/SKILL.md), [SKILL.md](skills/project-item/SKILL.md) |
| `integrations/tmux/` | Board binding, status 표시, 결정 대기 알림. 설치본은 `project-agent.conf`를 읽습니다 | 각 script의 머리말, [project-board README](tools/project-board/README.md) |
| `docs/project-team/` | 제품 지도, 동작 명세, 설치 계약, 예제 JSON | [제품 지도](docs/project-team/README.md) |
| `docs/project-board-*` | Project Board 계획과 화면 시안 | [TUI 계획](docs/project-board-tui-plan.md) |
| `VERSION`, `CHANGELOG.md`, `tools/formats.json` | 버전 값, 변경 기록, 형식 버전 선언 | [버전 규칙](docs/project-team/release.md) |
| `docs/cr/` | 이 저장소의 CR | [CR 계약](skills/project-item/references/cr.md) |

## 검증

저장소 루트에서 실행합니다. `python`은 Python 3.10 이상이고 `pytest`가 있는 interpreter입니다. `project-board` test는 [requirements.txt](tools/project-board/requirements.txt)의 package가 필요합니다. `pytest-xdist`가 없으면 `-n 8`을 뺍니다. Rust test는 cargo와 vendored crate가 필요합니다. 찾는 규칙은 [설치 계약 2.1절](docs/project-team/install-contract.md#21-rust-sidebar의-build)이 소유합니다(`PROJECT_AGENT_CARGO`, `PROJECT_AGENT_RUST_VENDOR`).

```sh
python -m pytest -q -n 8 tools/agent-session/tests
python -m pytest -q tools/project-item/tests
python -m pytest -q tools/project-board/tests
python -m pytest -q integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py tools/test_real_crontab.py
python -m pytest -q -n 8 install/tests
(cd tools/project-board/rust && cargo test --offline --locked)
```

- 여섯 명령은 서로 독립입니다. pytest 명령은 설정 파일 없이 각 디렉터리의 `conftest.py`로 동작합니다.
- `tools/project-board/tests`의 `test_rust_equivalence.py`와 `test_sidebar_binary.py`는 Rust binary로 돕니다. binary가 없거나 소스보다 오래됐으면 `cargo build --release --offline --locked`로 만듭니다(`tests/rust_binary.py`). `PROJECT_BOARD_SIDEBAR_BIN`이 있으면 그 binary를 그대로 씁니다.
- 여섯 명령을 모두 실행하는 것은 release를 낼 때 한 번입니다([버전 규칙 5절](docs/project-team/release.md#5-변경-기록과-release-절차)). 평소 변경은 아래 표에서 바꾼 경로에 해당하는 명령만 실행합니다(focused check와 직접 영향 회귀). 표의 의존은 [제품 지도의 의존 관계](docs/project-team/README.md#의존-관계)를 따릅니다. `origin/main`을 merge한 뒤에는 merge가 고른 명령의 입력을 바꿨을 때만 다시 실행합니다.

| 바꾼 경로 | 실행할 명령 |
| --- | --- |
| `install/**` | `install/tests` |
| `integrations/tmux/**` | 네 번째 명령, `tools/project-board/tests/test_tmux_control.py`, `install/tests` |
| `tools/python-launcher.sh`, `tools/bundle_boot.py`, `tools/formats.json`, `VERSION` | 네 번째 명령, `install/tests` |
| `tools/project-board/**` | `tools/project-board/tests`, `tools/agent-session/tests/test_api_boundary.py` |
| `tools/project-board/rust/**` | `cargo test --offline --locked`(`tools/project-board/rust`에서), `tools/project-board/tests`(일치 test와 binary test는 바뀐 binary로 돕니다), 네 번째 명령(release 파일 검사). `Cargo.toml`·`Cargo.lock`·`.cargo/config.toml`을 바꾸면 `install/tests`도 |
| `tools/project-item/**` | `tools/project-item/tests`, `tools/agent-session/tests/test_api_boundary.py`. `project_item/api.py` 또는 CR·결정 형식(`cr.py`, `decide.py`, `kinds.py`)을 바꾸면 agent-session·project-board test와 네 번째 명령도 |
| `tools/agent-session/**` | `tools/agent-session/tests`. `agent_session/api.py`, state 형식(`state.py`), tmux option 이름을 바꾸면 project-item·project-board test와 `install/tests`도 |
| `tools/tests/perf/**` | `python -m pytest -q tools/tests/perf`. 개발 도구의 test라 release 검증(위 여섯 명령)에 넣지 않습니다. 작은 규모에서 두 실행본을 한 번 번갈아 실행하므로 host 부하에 따라 수 분에서 수십 분이 걸립니다 |
| `tools/conftest.py`, 여러 도구가 함께 쓰는 test helper | pytest 명령 다섯 개 모두 |
| `skills/**`, `docs/**`, `README.md`, `AGENTS.md` | 고친 문서의 상대 link 검사, `tools/test_distribution_boundary.py`. `skills/project-item`의 형식 문서를 바꾸면 `tools/project-item/tests/test_doc_contract.py`, 원격 guidance 문서(`skills/**`, `docs/project-team/spec.md`)를 바꾸면 `tools/agent-session/tests/test_remote.py`도 |
- Agent-session test는 seat 여럿이 같은 host에서 동시에 검증하는 평소 부하에서 같은 결과를 냅니다. 한도(`AGENT_SESSION_TEST_TIMEOUT`, 기본 240초)는 host가 이보다 심하게 느릴 때만 늘립니다. 자세한 사용법은 [agent-session README](tools/agent-session/README.md#프로젝트-api와-검사)가 설명합니다.
- 설치기 test(`install/tests`)는 격리 HOME에서만 설치기를 실행합니다. 개발 중 설치기를 실제 HOME에 실행하지 않습니다. `tmux`와 `git`이 필요하고 계약 8절의 T1~T42를 구현합니다.
- Test가 사용자 계정에 남기는 자원은 test가 끝나면(통과·실패·중단 모두) test 전 수준으로 돌아갑니다.
  - tmux server: 모든 test server는 [`tools/tests/tmux_test_server.py`](tools/tests/tmux_test_server.py)의 `claim`으로 이름을 받고 `release`로 끝냅니다. `release`는 server와 pane의 process, `/tmp/tmux-<uid>`의 socket 파일, Board가 server마다 만드는 `/tmp/project-board-<uid>-<server pid>`를 지웁니다. `claim`은 소유 pytest process가 사라지면(SIGKILL·SIGTERM 포함) 같은 정리를 하는 watchdog을 함께 띄웁니다. Test에서 `kill-server`를 직접 부르지 않습니다.
  - 임시 디렉터리: `tools/conftest.py`가 만드는 `TMPDIR/pt-*`는 통과한 run이 끝날 때 지웁니다. 실패·중단한 run의 것은 조사용으로 남고, 다음 run이 시작할 때 소유 run이 끝난 것 중 최근 5개만 남기고 지웁니다. 진행 중인 run의 것은 지우지 않습니다. 소유자 표시가 없는 옛 디렉터리는 24시간 넘게 손대지 않았을 때만 지웁니다. 규칙과 이유는 [`tools/tests/private_root.py`](tools/tests/private_root.py)가 소유합니다.
  - 실제 HOME: `tools/conftest.py`와 `install/tests/conftest.py`가 run마다 HOME을 `<basetemp>-home`(보통 `TMPDIR/pt-*` 안)으로 바꿔 run과 자식 process(xdist worker 포함)의 `~`를 거기로 보냅니다. Test는 실제 HOME의 `~/.cache/project-item/locks` 같은 곳에 파일을 만들지 않고, 실제 운영 잠금과 디렉터리를 공유하지 않습니다. 통과한 run은 그 HOME을 지웁니다. 이 격리는 [`tools/test_private_root.py`](tools/test_private_root.py)가 검사합니다. HOME이 따로 필요한 test는 `monkeypatch.setenv`로 바꿉니다. HOME에서 위치를 정하는 읽기 전용 도구 위치(`PYTHONUSERBASE`: `pip install --user`한 pytest·xdist·textual, `RUSTUP_HOME`: rustup proxy의 toolchain)는 HOME을 바꾸기 전 값으로 고정합니다(이미 값이 있으면 그대로 둡니다). `CARGO_HOME`은 고정하지 않아 cargo cache는 run의 HOME에 생깁니다.
  - 실제 crontab: 사용자 crontab(`crontab -l`)은 HOME 밖의 사용자 spool이라 HOME 격리가 덮지 못합니다. 제품은 PATH에서 찾은 `crontab`만 쓰고 test는 그 자리에 shim([`tools/tests/fake_crontab.py`](tools/tests/fake_crontab.py))을 둡니다. 그러나 test가 PATH를 `<디렉터리>:/usr/bin:/bin`처럼 통째로 바꾸면 shim이 가려져 `/usr/bin/crontab`이 실제 spool에 닿습니다. 그래서 `tools/conftest.py`·`install/tests/conftest.py`·`integrations/tmux/conftest.py`가 Linux에서 run의 pytest process에 `PR_SET_NO_NEW_PRIVS`를 걸어([`tools/tests/real_crontab.py`](tools/tests/real_crontab.py)) 실제 `crontab`을 읽기·쓰기 모두 `Permission denied`로 막습니다. 이 flag는 xdist worker와 test가 띄우는 모든 자식 process에 상속되고 풀 수 없으며, shim(일반 script)에는 영향이 없습니다. PATH를 어떻게 바꾼 test도 실제 crontab을 바꾸지 못하고 제품의 `crontab_unreadable` 오류가 납니다(Leader 시작의 `ensure_check`는 이 오류로 시작을 멈추지 않으므로 그 test는 crontab 내용을 확인하는 단언에서 실패합니다). Linux가 아니면 막을 수 없어 경고를 냅니다. 이 경우 run 전후의 `crontab -l`을 직접 비교합니다. 이 차단은 [`tools/test_real_crontab.py`](tools/test_real_crontab.py)가 검사하며, 읽기만 합니다. `cargo test`(Rust sidebar)는 pytest process가 아니라 이 차단 밖입니다. Rust sidebar는 `crontab -l`로 읽기만 하고 쓰는 코드가 없습니다. Rust test가 crontab을 쓰게 되면 이 규칙의 대상입니다.
- CLI smoke: `tools/<도구>/bin/<도구> --help`.

## 관련 문서

- [제품 지도](docs/project-team/README.md): 구성 요소, 공개 진입점, 의존 관계, 실행 경로 계약
- [동작 명세](docs/project-team/spec.md): 등록, state, start·stop·restart·shutdown·resume
- [설치 안내](docs/install.md): 직원용. 전제, 한 줄 설치, 설치가 만드는 경로, 갱신·제거, tmux 연결
- [설치 계약](docs/project-team/install-contract.md): 설치·갱신·되돌리기·제거의 경계
- [버전 규칙](docs/project-team/release.md): 버전 값, 형식 버전과 호환 범위, git tag 이름, 변경 기록 작성
- [변경 기록](CHANGELOG.md): 버전별 CR ID 목록과 형식 변경 여부
- [AGENTS.md](AGENTS.md): 이 저장소에서 작업하는 agent의 규칙
