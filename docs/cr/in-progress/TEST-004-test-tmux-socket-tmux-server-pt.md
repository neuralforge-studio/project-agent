# TEST-004: test 실행이 tmux socket·고아 tmux server·pt-* 임시 디렉터리를 사용자 계정에 계속 남깁니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Base: 8ead20ab6917371f1a2415e89ce02422dca96e97 2026-11-09T17:00:26+09:00

## Symptom
운영자 항의(2026-11-09 16:30경 실측, `/primehome/swain/tmp/claude-1028/-primehome-swain-Utils-project-agent-project-agent-base/76a0fdc1-de2f-4592-908d-8a956e743da6/scratchpad/complaint.md`): 사용자가 서버 자원이 점점 줄어든다고 신고했고, 상당 부분이 project-agent test의 정리 누락입니다.
1. `/tmp/tmux-1028/`에 server가 없는 `board-test-*` socket 파일 414개(전부 당일 생성).
2. pytest가 finalizer 전에 죽은 실행의 tmux server(`tmux -L agent-lifecycle-test-5426c9485a … new-session -d -s harness sleep 86400`, pid 2572796, 부모 pid 1, 1시간 53분)와 그 안의 fake provider(pid 2576416)가 남음. project-agent.seat2의 `test_codex_trust_dialog_returns_its_window_and_reuses_the_run` 실행분.
3. `~/tmp/pt-*` 207개(당일 186개, 하나 약 144MB, 14시대에만 91개).

## Evidence
- `tools/project-board/tests/test_tmux_control.py`(예: 68-104행): 각 test가 finally에서 `tmux -L <name> kill-server`만 부르고 socket 파일을 지우지 않음. 같은 저장소의 `tools/agent-session/tests/fixtures/agent_session_fixture.py:43` `stop_test_server()`는 파일까지 지움(한쪽만 고친 상태).
- agent-session fixture의 harness session이 `sleep 86400`이고, 정리는 fixture finalizer에서만 일어남. pytest가 timeout·SIGKILL·Ctrl-C로 죽으면 server와 pane의 fake provider가 24시간 남음.
- `tools/conftest.py` `pytest_sessionfinish`: `exitstatus == 0`일 때만 `pt-*`를 지움. 실패·중단 실행분을 지우는 곳이 없고 개수·기간 상한이 없음.
- 2026-11-09 Leader 정리(요구 D): 응답하는 server가 없는 test socket 420개 삭제(`board-test-*` 414개, Leader가 확인용으로 만든 `pa-hooktest-*`·`pa-t001-*` 포함), 실행 중인 가장 오래된 pytest보다 먼저 만들어진 test server 1개(pid 2572796) 종료와 socket 삭제(fake provider 2576416도 끝남), 그 기준보다 오래된 `pt-*` 202개 삭제(실행 중 pytest가 쓰는 것은 남김).

## Contract
- 운영자 요청(원문 파일): 원인 수정은 호출자 주의가 아니라 test 쪽 불변식으로 합니다. A. 모든 test tmux server를 하나의 helper로 종료하고 socket 파일까지 지움(project-board·agent-session·internal test가 같은 helper, SSOT). B. pytest가 비정상 종료해도 고아가 남지 않음(`sleep 86400` harness를 그대로 두지 않음). C. `pt-*`에 보존 기간 또는 개수 상한. Result에 socket 파일·고아 server·`pt-*` 개수가 test 실행 전후에 늘지 않는다는 실측을 포함.
- 사용자 계정의 자원은 test가 끝나면(정상·실패·중단 모두) test 전 수준으로 돌아가야 합니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 운영 결함이며 재현 근거가 있으므로 위임 범위입니다(운영자 요청도 Leader 판정으로 진행하라고 함). 요구 D(지금 남은 누수 정리)는 Leader가 위 Evidence 마지막 항목대로 했습니다. TEST-003(b3681f2)이 같은 fixture를 고친 뒤이므로 그 위에서 시작합니다.
- 2026-11-09 Leader: 범위 추가(같은 원인). INSTALL-001(ecc5bce)로 들어온 설치기 test도 `~/tmp/pi-*`(`install/tests/conftest.py`의 session fixture `pi-src-*`, `harness.Home()`)를 만들고 fixture finalizer에서만 지웁니다. pytest가 비정상 종료하면 `pt-*`와 같이 남습니다(2026-11-09 18시 기준 25개, 대부분 실행 중인 INSTALL-004 test). Implementation 3의 보존 규칙과 Verification 2의 전후 실측에 `install/tests`(README의 설치기 test 명령)와 `pi-*`를 포함합니다. 설치기 test가 띄우는 private tmux server도 1의 helper를 씁니다.
- 2026-11-09 Leader: 제출 5b3274994efb11de5025af6bb9fc340572b146f4를 인수합니다. Leader review: 요구 A(tmux test server의 helper 하나, kill-server 직접 호출은 helper 안에만), B(owner pid watchdog: SIGKILL·SIGTERM 1초, SIGINT 8초 안에 server·pane·socket 소멸, 다른 owner 불간섭), C(pt-* 소유 pid와 끝난 run 최근 5개, 표시 없는 옛 것은 24시간), install/tests의 pi-*를 pt-* 아래로 옮김을 확인했습니다. 수정 전 재현 표와, suite마다 전용 TMUX_TMPDIR·TMPDIR로 격리한 전후 실측(다섯 명령 모두 실행 후 socket·server·pt-*·Board 디렉터리 0)을 근거로 인수합니다. 다섯 명령 실행은 README 표(공유 test helper 변경)대로입니다. 제품 결함(Board의 /tmp/project-board-<uid>-<pid> 미정리)은 별도 CR로 엽니다.

## Implementation
읽을 문서: [README의 검증](../../../README.md#검증), `tools/conftest.py`, `tools/agent-session/tests/fixtures/agent_session_fixture.py`, `tools/project-board/tests/test_tmux_control.py`, `tools/agent-session/tests/test_internal.py`.

1. test tmux server의 수명 helper 하나(요구 A): server를 만들고 끝내는 함수를 한 곳에 둡니다. 끝낼 때 `kill-server` 뒤 socket 파일을 지웁니다. project-board·agent-session(fixture와 `test_internal.py`의 `agent-internal-test-*` 포함)·integrations/tmux·install test가 모두 이 helper를 씁니다. 두 도구가 함께 쓸 수 있는 위치(예: `tools/` 아래 test 전용 module)를 고르고, 도구 사이 import 경계 test(`test_api_boundary.py`)와 배포 경계(test는 release에 넣지 않음)를 지킵니다. 다른 곳에서 직접 `kill-server`를 부르는 test 정리 코드는 없앱니다.
2. server 수명을 그것을 만든 test process에 묶습니다(요구 B). helper가 server를 만들 때 소유 process(pytest worker)의 pid를 받아, 그 process가 사라지면 server가 스스로 끝나고 socket 파일을 지우게 합니다. 예: `sleep 86400` harness 대신 `while kill -0 <owner>; do sleep 1; done; tmux -S <socket> kill-server; rm -f <socket>`를 harness session으로 둡니다. pane 안의 fake provider는 server가 끝날 때 함께 끝나는지 확인하고, 아니면 같은 방식으로 묶습니다. finalizer는 그대로 두되 정리의 유일한 수단이 아니게 합니다.
3. `pt-*` 보존 상한(요구 C): `tools/conftest.py`가 run을 시작할 때 이전 run의 `pt-*`를 정리합니다. 지울 수 있는 것은 소유 run이 끝난 것(디렉터리에 소유 pid를 남기고 그 pid가 없음)뿐입니다. 실패 run의 디렉터리는 디버깅용으로 최근 N개(예: 5) 또는 일정 기간(예: 24시간)만 남기고, 값과 이유를 module docstring과 README 검증 절에 적습니다. 통과한 run은 지금처럼 끝날 때 지웁니다.
4. 같은 방식으로 남는 다른 자원이 있는지 찾습니다(예: `/tmp/project-board-<uid>-*` 디렉터리, test가 만드는 다른 임시 위치). 찾으면 같은 helper 또는 같은 수명 규칙으로 정리하고 목록을 Result에 적습니다.

의존: 선행 TEST-003(done). 다른 진행 중 CR과 병렬. SESSION-001·INSTALL-001이 test 파일을 고치고 있으므로, 제출 전에 `origin/main`을 merge합니다.

위험 등급: 중간. test 기반만 바꾸고 제품 코드는 바꾸지 않습니다. 단, 2단계의 watchdog이 실행 중인 다른 seat의 server를 건드리지 않음을 확인해야 합니다.

## Verification
1. 재현(수정 전): Base에서 project-board suite 한 번 실행 전후의 `board-test-*` socket 파일 수가 늘어남. agent-session test 하나를 실행 중에 pytest를 SIGKILL하면 그 server와 fake provider가 남음. 실패하는 test 하나로 run을 끝내면 `pt-*`가 남고 다음 run에서도 지워지지 않음.
2. 수정 뒤, 같은 절차에서:
   - 네 suite(README 명령)를 각각 한 번 실행한 전후로 `/tmp/tmux-1028`의 test socket 파일 수, test tmux server 수, `~/tmp/pt-*` 수가 늘지 않음(운영자 요청의 세 수치). 실측값을 Result에 표로 적음.
   - pytest를 SIGKILL한 뒤 몇 초 안에 그 run의 server·fake provider·socket 파일이 없어짐(SIGTERM·Ctrl-C도).
   - 실패 run을 상한보다 많이 만든 뒤 다음 run 시작 시 상한만 남음. 실행 중인 다른 run(다른 seat)의 `pt-*`·server는 지워지지 않음.
3. 영향 회귀: README의 네 명령이 통과합니다(agent-session은 TEST-003 이후 기본 한도).

## Result

- 제출 commit: 5b3274994efb11de5025af6bb9fc340572b146f4

`cr/TEST-004`를 `origin`에 push했습니다. 제품 코드는 바꾸지 않았습니다(test 기반과 README 검증 절만). `origin/main`(8e314f4)을 merge했고 충돌은 README뿐이었습니다.

### 구현

1. **요구 A, helper 하나**: `tools/tests/tmux_test_server.py`. `claim(prefix)`가 이름을 주고, `release(name)`가 `kill-server`, pane의 process 종료, `/tmp/tmux-<uid>`의 socket 파일 삭제, Board가 server마다 만드는 `/tmp/project-board-<uid>-<server pid>` 삭제를 한 번에 합니다. `-S` 경로로 server를 다루는 installer test는 `watch_path`·`release_path`를 씁니다. project-board·agent-session(fixture, `test_internal`, `test_tmux`, `test_suspend`, `test_lifecycle`)·integrations/tmux·install/tests가 모두 이것을 씁니다. 저장소에 `kill-server` 직접 호출은 helper 안에만 남았습니다. `stop_test_server`와 `kill_server`의 직접 호출은 없앴습니다. 위치가 `tools/tests/`라서 release에 들어가지 않고(`PRODUCT_PATHS` 밖), install-contract 5절의 `grep -v /tests/` 규약에 맞고, `test_api_boundary`(agent_session import 없음)도 통과합니다.
2. **요구 B, 수명 묶기**: `claim`이 owner(pytest worker) pid를 보는 watchdog을 별도 session(`start_new_session`)으로 띄웁니다. owner가 사라지면 `tmux -S <그 server의 socket> kill-server`, socket 삭제, Board runtime 디렉터리 삭제를 합니다. 이유: server를 test가 만들 때도, 제품이 첫 명령에서 만들 때(`test_tmux.py`)도 같은 방식으로 덮을 수 있고, `sleep 86400` harness session을 바꿀 필요가 없기 때문입니다. watchdog은 자기 socket만 지정하므로 다른 seat·사용자의 server를 건드리지 않습니다. `release`가 watchdog을 먼저 끝냅니다. pane의 fake provider는 server가 끝날 때 tmux의 hangup으로 같이 끝납니다(아래 실측). finalizer는 그대로 두었고 정리의 유일한 수단이 아닙니다. `atexit`도 남은 것을 `release`합니다.
3. **요구 C, `pt-*` 상한**: `tools/tests/private_root.py`. 각 `pt-*`에 소유 pid(`owner`)를 쓰고, pytest의 basetemp는 그 안쪽 `t`입니다(pytest가 basetemp를 비우기 때문). run을 시작할 때 `prune()`이 소유 pid가 살아 있는 것은 지우지 않고, 소유 run이 끝난 것은 최근 5개만 남깁니다. 소유자 표시가 없는 옛 디렉터리는 24시간 넘게 손대지 않았을 때만 지웁니다(진행 중 run의 것을 잘못 지우지 않기 위함). 통과한 run은 끝날 때 지웁니다. 값과 이유는 module docstring, `tools/conftest.py` docstring, README 검증 절에 적었습니다.
4. **같은 방식으로 남던 다른 자원**(목록):
   - `/tmp/project-board-<uid>-<server pid>`: 제품(`tmux_control._private_dir`)이 server마다 만들고 지우지 않습니다. helper의 `release`와 watchdog이 지웁니다. 이름이 바뀌면 알도록 `test_ending_a_test_server_removes_the_runtime_directory_the_board_made_for_it`가 제품 함수와 helper를 대조합니다. 제품이 지우지 않는 것은 제품 결함이므로 이 CR에서 고치지 않았고, 아래 후속으로 남깁니다.
   - `/tmp/project-board-ui-*.sock`(test_tui 3곳)과 `/tmp/board-click-*`: test 실패에도 지워지게 finalizer로 바꿨습니다(`board_testing.click_socket`).
   - `install/tests`의 `pi-*`, `pi-t*`, `pi-src-*`(`tempfile.mkdtemp`): `install/tests/conftest.py`가 `private_root.configure(config, temp=True)`로 run의 `pt-*/m` 안에 만들게 했습니다(xdist worker도 환경 변수로 같은 root). 비정상 종료 때 남아도 `pt-*`의 상한 규칙으로 정리됩니다. `-S` server는 helper가 맡습니다.
   - 남은 것: 없음(아래 격리 실측 기준). test가 `--basetemp`를 직접 받은 run은 기존대로 사용자가 지정한 경로입니다.

### 검증

**수정 전(Base 8ead20a), 같은 절차**
| 절차 | 결과 |
| --- | --- |
| project-board suite 1회(전후 비교) | `board-test-*` socket 9개 증가, `/tmp/project-board-1028-*` 6개 증가 |
| agent-session fixture test를 SIGKILL(`git archive` 사본) | 6초 뒤에도 tmux server와 socket 파일이 남음(운영자가 본 고아 server와 같음) |
| 실패하는 test로 run 3회 → 통과하는 run 1회 | `pt-*` 3개가 남고 통과 run 뒤에도 그대로(상한 없음) |

**수정 후, 네 suite와 install/tests 각 1회.** host의 다른 seat 실행과 섞이지 않게 실행마다 `TMUX_TMPDIR`와 `TMPDIR`을 전용 디렉터리로 두고, 그 디렉터리와 그 안의 tmux server만 셉니다(server는 `/proc/<pid>/environ`으로 귀속, Board runtime 디렉터리는 실행 중 본 server pid로 귀속). 실행 전은 모두 0입니다.

| suite(README 명령) | 결과 | 실행 후 socket 파일 | 실행 후 test tmux server | 실행 후 `pt-*` | 실행 후 그 외 임시 디렉터리 | 남은 Board runtime 디렉터리 |
| --- | --- | --- | --- | --- | --- | --- |
| `tools/agent-session/tests` (`-n 8`) | 730 passed, 976 s | 0 | 0 | 0 | 0 | 0 |
| `tools/project-item/tests` | 120 passed | 0 | 0 | 0 | 0 | 0 |
| `tools/project-board/tests` | 115 passed | 0 | 0 | 0 | 0 | 0 (server 6개를 거쳤음) |
| 네 번째 명령(`integrations/tmux` 외 + `tools/test_tmux_test_server.py`) | 79 passed | 0 | 0 | 0 | 0 | 0 |
| `install/tests` (`-n 8`), merge 뒤 한 번 더 | 239 passed, 2 skipped, 472 s | 0 | 0 | 0 | 0 | 0 |

(agent-session 줄의 Board runtime 디렉터리는 sampler가 본 pid 중 하나가 오늘 09:44에 다른 server가 만든 디렉터리와 겹친 것 1건이 처음 집계에 있었습니다. 만든 시각과 pid 재사용으로 제 실행 것이 아님을 확인했습니다.)

**중단 실험(수정 후, 실제 `session_env` fixture로 `start`한 pane의 fake provider 포함)**
| 신호 | 결과 |
| --- | --- |
| SIGKILL | 1초 안에 server process·pane process 2개·socket 파일이 없어짐 |
| SIGTERM | 1초 안에 같음 |
| SIGINT(Ctrl-C와 같은 핸들러) | 8초 안에 같음(fixture finalizer가 먼저 정리) |
| 자동 test `tools/test_tmux_test_server.py` | SIGKILL·SIGTERM·SIGINT 각 owner에 server·pane process·socket 소멸, 정상 `release` 소멸, 다른 owner의 server는 건드리지 않음 |

**`pt-*` 상한(실제 pytest, 전용 TMPDIR)**: 실패 run을 7회 반복한 뒤 `pt-*`는 5개 + 진행 중이던 다른 run의 것 1개였고, 진행 중 run의 디렉터리는 끝까지 남았습니다. 이어 통과 run을 하자 5개가 남았습니다(진행 중이던 run은 그 사이 통과해 스스로 지움). 자동 test(`tools/test_private_root.py`)는 최근 N개 유지·소유자 생존 보호·소유자 없는 디렉터리의 나이 기준·symlink/파일 무시를 검사합니다.

**근거 재사용·재실행 판정**
- 다섯 명령은 helper와 `tools/conftest.py`를 바꾸므로 README 표대로 모두 한 번 실행했습니다(위 표, 마지막 코드 변경 d1e60b1 이후 본 실행). 그 뒤 merge(5b32749)가 가져온 것은 installer 제품 코드·`install/tests`의 새 test(`test_adopt.py`, `test_prune.py`)·문서입니다. 그래서 영향받는 `install/tests`만 merge 상태에서 다시 실행했고(239 passed), 나머지 네 suite의 근거는 재사용했습니다. merge가 바꾸지 않은 파일입니다.
- 첫 측정에서 `test_lifecycle.py::test_registration_publishes_when_the_controller_ends_before_it[sigint]`와 제 `[SIGINT]` test가 실패했습니다. 원인은 제가 `nohup … &`로 background에 띄워 자식이 SIGINT 무시 상태를 상속한 것이었습니다(pytest를 SIGINT 핸들러를 복원한 wrapper로 실행하면 통과, 전경 실행에서도 통과). 제품·test 결함이 아니고, 제 helper test의 owner는 SIGINT 핸들러를 복원하도록 고쳤습니다.
- 한 번의 측정 주기에 두 seat의 옛 코드가 같은 host에서 `board-test-*`·`pi-*`를 만들어 전역 수치가 섞였습니다. 그래서 위의 격리 방식으로 다시 측정했습니다. 격리 전 전역 수치는 근거로 쓰지 않았습니다.
- 일회성 정리: `private_root.prune()`이 처음 실행되며 소유자 표시 없이 24시간이 지난 옛 `~/tmp/pt-*`를 지웠습니다(요구 C의 규칙대로).

### 남은 일(범위 밖)
- 제품 `tmux_control._private_dir`가 server마다 `/tmp/project-board-<uid>-<pid>`를 만들고 지우지 않습니다. 사용자 실제 환경에서도 server가 끝나도 남는 제품 결함입니다. 제품 코드는 바꾸지 않는다는 이 CR의 범위 밖이라 helper가 test에서만 지웁니다. 별도 CR이 필요하면 Leader가 판정해 주십시오.
- 현재 떠 있는 다른 seat의 옛 코드 run이 만든 `pi-*`·`board-test-*`는 그 seat가 이 branch를 merge하기 전까지 계속 생깁니다(`pt-*`로 옮겨지지 않은 옛 모양).
