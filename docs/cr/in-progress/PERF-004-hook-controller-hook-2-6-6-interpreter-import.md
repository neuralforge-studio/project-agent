# PERF-004: 등록 hook과 controller가 시동 번들을 쓰지 않아 hook마다 2~6.6초를 interpreter 시동과 import에 씁니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: PERF-003, SESSION-011, SESSION-013

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
