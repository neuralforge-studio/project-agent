# PERF-004: 등록 hook과 controller가 시동 번들을 쓰지 않아 hook마다 2~6.6초를 interpreter 시동과 import에 씁니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: PERF-003, SESSION-011, SESSION-013
- Base: 16fce569de54eec284550d1a6bb1a4b243f834b7 2026-11-10T19:54:37+09:00

## Symptom
등록 hook과 controller는 PERF-003의 시동 번들을 쓰지 않습니다. hook process 하나가 interpreter 시동과 import에만 4×4에서 2초, 16×16(load 78)에서 6.6초를 씁니다. 같은 hook 명령이 SessionStart뿐 아니라 Stop·StopFailure·SessionEnd에도 실행됩니다. 그래서 모든 대화가 turn이 끝날 때마다 이 비용을 치릅니다.

## Evidence
- SESSION-011 Result의 수정 전 단계 측정(가짜 `claude`, sitecustomize 추적): hook의 interpreter+import는 4×4 load 42에서 1.96초, load 64에서 2.19초, 16×16 load 78에서 6.6초였습니다.
- PERF-003 Result: 번들을 쓴 CLI는 v0.4.0보다 warm wall 비가 0.18~0.27이고 CPU 비가 0.49~0.62입니다. PERF-003은 hook·controller 명령(`python -c "...from agent_session.internal import ..."`)이 생성 script 내용이라 범위에서 뺐습니다.
- hook 명령(`providers/claude.py` `registration_hooks`)은 `-S` 없이 시작합니다. `mark_process`와 controller 명령(`launch_artifacts.py`)도 같은 모양입니다.

## Contract
- `agent_session.internal`의 entry 이름과 인자, hook의 판정과 결과는 바꾸지 않습니다(AGENTS.md 호환 규칙).
- 떠 있는 run은 자기 release에 고정되어 있습니다. 바뀐 명령은 새 run에만 적용됩니다.
- 번들이 없거나 맞지 않으면(개발 checkout, 다른 interpreter) 지금처럼 일반 import로 동작합니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 측정 근거가 있는 속도 결함이며 PERF-003의 범위 밖으로 남긴 경로입니다.
- 2026-11-10 Leader: open -> todo. hook·controller 시동 번들, 측정 근거 있는 속도 결함
- 2026-11-10 Leader: 제출 14b0c8fb139b878d7ba2f1bceed51da0a73afea6를 인수합니다. 검토 14b0c8f(구현 fdacd6f + main 1b0ea72 merge). 세 생성 명령의 -S 추가(-c 프로그램·entry·인자 순서 그대로), agent_session/__init__.py의 번들 연결(이미 reader가 있으면 건너뜀, bundle_boot.py·번들이 없으면 일반 import), bundle_boot.py의 표지, 문서 두 곳을 읽었습니다. 고친 문서의 상대 link는 Leader가 확인했습니다(0 broken). README 표 행: tools/agent-session/** 832 passed + test_remote 1건 부하 timeout(단독 통과), bundle_boot.py 행의 네 번째 명령 130·install/tests 280 passed(merge commit). 16x16 start wall 0.68·CPU 0.77 improved, hook 시동+import 0.70→0.21초. Result가 적은 pkill -f 사고는 Leader가 사용자에게 알립니다.

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), [실행 경로 계약](../../project-team/README.md#실행-경로-계약), [동작 명세](../../project-team/spec.md)의 등록(5절), 측정 도구 [`tools/tests/perf/perf_bench.py`](../../../tools/tests/perf/perf_bench.py) 머리말(가짜 `claude`의 `hooks.log`), [project-team Worker 절](../../../skills/project-team/SKILL.md), PERF-003 Result와 [`tools/bundle_boot.py`](../../../tools/bundle_boot.py), [설치 계약 6.1절](../../project-team/install-contract.md#61-python-선택).

1. 설치본에서 등록 hook(`providers/claude.py` `registration_hooks`), `mark_process`, controller(`launch_artifacts.py`)의 process가 시동 번들에서 import하게 합니다. 표준 library만 쓰는 경로이므로 `-S`도 씁니다. 방법은 Worker가 정합니다. 예: 생성 명령의 `-c` 앞에 reader를 넣는 방법, `agent_session/__init__.py`가 맨 앞에서 번들을 거는 방법이 있습니다. 생성 명령은 가능한 한 적게 바꿉니다.
2. 번들이 없거나 맞지 않을 때의 fallback은 PERF-003과 같습니다.
3. 바꾼 명령의 모양과 이유를 설치 계약 6.1절과 동작 명세의 해당 문장에 적습니다.

의존: 없음. SESSION-013과 `providers/claude.py`의 `registration_hooks`가 겹칠 수 있습니다(SESSION-013은 timeout 값을 바꿉니다).

위험 등급: 높음. 모든 run의 등록과 turn 끝 hook 경로입니다.

## Verification
1. 측정 도구로 v0.4.0 대신 현재 `origin/main`(번들 있음, hook은 번들 없음)과 후보를 비교합니다. `--scales 16x16 --groups lifecycle --reps 3 --cold-reps 0` 한 번만 잽니다. `start` wall·CPU와 `hooks.log`의 hook 시간(SessionStart, Stop)을 적고 host load를 함께 적습니다.
2. 번들이 있는 설치본에서 hook·controller process의 모듈이 번들에서 오는지 보이는 test와, 번들이 없을 때 일반 import로 동작하는 test를 둡니다.
3. README 검증 표에서 바꾼 경로의 행을 모두 실행합니다(`-rf`). 측정을 기다리지 말고 측정과 동시에 돌립니다.
4. 제출 전에 `origin/main`을 merge합니다. merge가 입력을 바꾼 명령만 merge commit에서 다시 실행합니다. 측정은 merge 뒤에 다시 하지 않습니다.
5. 측정 도구가 바뀌어도 진행 중인 측정을 다시 시작하지 않습니다. 사용자가 빠른 반영을 요구했습니다. 위 범위 밖의 측정(4×4, A/A, cold)은 하지 않습니다.

## Result
- 제출 commit: 14b0c8fb139b878d7ba2f1bceed51da0a73afea6

branch `cr/PERF-004`(origin에 push). 구현 commit `fdacd6f`에 `origin/main`(`1b0ea72` release 0.5.0)을 merge한 commit입니다.

### 변경
- 등록 hook(`providers/claude.py` `registration_hooks`), `launch.sh`의 `mark_process`, `controller.sh`의 controller 명령에 `-S`를 더했습니다. 세 명령은 표준 library만 씁니다. `-c` 프로그램, entry 이름, 인자 순서는 그대로입니다.
- 번들은 [`agent_session/__init__.py`](../../../tools/agent-session/agent_session/__init__.py)가 연결합니다. 패키지를 처음 import할 때 `tools/bundle_boot.py`를 읽어 `_project_agent_bundle(tools)`를 부릅니다. 생성 명령에 reader를 넣지 않았으므로 명령은 `-S` 한 단어만 바뀝니다.
    - 이미 reader가 있으면(세 CLI의 진입점) 다시 설치하지 않습니다. `bundle_boot.py`의 finder에 `project_agent_bundle = True` 표지를 더했고 `__init__`이 `sys.meta_path`에서 찾습니다.
    - `bundle_boot.py`가 없으면(원격 runtime의 복사본) 일반 import입니다. 번들이 없거나 맞지 않으면(개발 checkout, 다른 interpreter, `-O`) reader가 아무것도 하지 않아 일반 import입니다.
- 문서: 설치 계약 6.1절에 "생성 명령의 시동(PERF-004)" 항목, 동작 명세 5절(등록)에 한 문장. 떠 있는 run은 자기 release의 명령을 그대로 씁니다(이 변경은 새 run에만 적용).
- 범위 밖으로 둔 것: 첫 prompt의 `register_current` 명령(`_registration_command`)과 tmux `pane-died` hook(`python -m agent_session.internal finish-ended`)은 CR의 범위(hook, `mark_process`, controller)에 없어 바꾸지 않았습니다.
- 바뀐 파일: `tools/agent-session/agent_session/{__init__,launch_artifacts,providers/claude}.py`, `tools/bundle_boot.py`, test(`tools/agent-session/tests/{test_run_modules,test_providers}.py`, `install/tests/test_bundle.py`), 위 두 문서.

### 측정 (host srv04, 16x16, `--groups lifecycle --reps 3 --cold-reps 0`, BASE=origin/main `16fce56` 설치본 대 후보 `fdacd6f` 설치본, 격리 tmux)
host load는 측정 중 81~96(BASE)·66~84(후보)였습니다. 도구가 환경을 끝에 지워서 `hooks.log`는 남지 않았습니다. hook 시간은 아래 별도 측정으로 대신합니다.

| 명령 | BASE wall s | 후보 wall s | wall 비 | BASE cpu s | 후보 cpu s | cpu 비 |
| --- | --- | --- | --- | --- | --- | --- |
| agent_start_worker (n=6) | 38.5 [31.8-42.7] | 26.4 [14.7-31.4] | 0.68 [0.38-0.87] improved | 3.552 | 2.736 | 0.77 [0.66-0.83] improved |
| agent_restart_worker (n=3) | 89.0 | 70.7 | 0.79 [0.33-1.47] same | 4.347 | 3.523 | 0.81 [0.60-0.96] improved |
| agent_stop_worker (n=3) | 46.2 | 30.8 | 0.67 [0.44-1.58] same | 1.286 | 1.172 | 0.91 same |
| agent_finish_ended (n=3) | 18.4 | 9.6 | 0.52 [0.24-1.72] same | - | - | - |

`start`는 wall과 CPU 모두 개선입니다. wall 구간이 넓고 나머지 행이 `same`인 것은 load 차이와 n=3 때문입니다. 호출 수 비교는 하지 못했습니다. BASE의 counting pass가 `start`에서 rc 4로 끝나(load 125 이상, 59초) summary의 `-`로 남았습니다. 후보는 tmux 148, 그 밖의 process 18입니다.

hook 한 process의 interpreter 시동과 import(`python [-S] -c "...from agent_session.internal import register_from_hook"`, 두 release를 번갈아 9회, warm, load 43→86):

| | wall 중앙값 [min-max] | cpu 중앙값 |
| --- | --- | --- |
| BASE (`-S` 없음, 번들 없음) | 0.701초 [0.565-1.295] | 0.190초 |
| 후보 | 0.212초 [0.141-0.278] | 0.110초 |

wall 비 0.30, cpu 비 0.58입니다. 이 값은 hook 판정과 tmux 읽기를 뺀 시동·import만이며 `hooks.log`의 hook 전체 시간(SessionStart, Stop)이 아닙니다. 측정 스크립트는 저장소에 넣지 않았습니다.

### 검증 (모두 `-rf`, 구현 commit에서 실행하고 merge 뒤 입력이 바뀐 두 명령은 merge commit `14b0c8f`에서 다시 실행)
- 새 test `install/tests/test_bundle.py` 4건(설치본에서 `-S -c`로 `agent_session.internal`을 import하면 `agent_session`은 파일에서, `internal`·`state`·`json`은 번들에서 오고 reader는 하나. 세 CLI의 진입점 뒤에도 reader는 하나. 번들이 없는 복사본과 `bundle_boot.py`가 없는 복사본은 모두 `SourceFileLoader`로 동작). 단독 13 passed.
- 생성 명령의 모양 test 갱신: `test_run_modules.py`(launch.sh marker, controller), `test_providers.py`(hook 명령)에 `-S`.
- `tools/agent-session/tests` (`-n 8`, 구현 commit): 832 passed, 1 failed. 실패는 `test_remote.py::test_dead_report_bridge_reuses_its_token_and_replaces_its_stale_socket`이고 "The Worker report bridge did not start"(5초 deadline)입니다. 그때 host load가 100 이상이었고, 같은 test를 단독으로 다시 실행하니 통과했습니다(1 passed, 12초). 부하로 인한 시간 초과로 판정했습니다.
- 네 번째 명령(`integrations/tmux`, launcher, 배포 경계, private root, release files, tmux test server): 구현 commit 130 passed, merge commit 130 passed(`VERSION`이 바뀌었으므로 재실행).
- `install/tests` (`-n 8`): 구현 commit 280 passed, 2 skipped. merge commit 280 passed, 2 skipped.
- merge(`1b0ea72`)는 `VERSION`, `CHANGELOG.md`와 CR 파일 이동만 바꿨습니다. 그래서 `VERSION`이 입력인 네 번째 명령과 `install/tests`만 다시 실행했고, `tools/agent-session/tests`는 구현 commit의 결과를 재사용합니다. 측정은 merge 뒤에 다시 하지 않았습니다.
- 알림: 작업 중 `pkill -f`로 제 background pytest를 멈추려다 같은 사용자의 다른 shell이 끝났습니다(skill이 경고한 함정). 다른 seat의 test run이 같은 pattern에 걸렸는지는 확인하지 못했습니다.
