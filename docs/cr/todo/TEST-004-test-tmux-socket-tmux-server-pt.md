# TEST-004: test 실행이 tmux socket·고아 tmux server·pt-* 임시 디렉터리를 사용자 계정에 계속 남깁니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2

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
