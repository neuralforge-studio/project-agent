# TEST-013: release 검증의 agent-session test 3개가 높은 host 부하에서 대기 한도를 넘겨 실패합니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S3

## Symptom
0.9.0 release 검증(2026-11-11, release commit 532faea의 clone)에서 `python -m pytest -q -n 8 tools/agent-session/tests`가 3 failed, 869 passed(44분)였습니다. 다른 줄기(project-item, project-board, 네 번째 명령, install/tests)도 같은 시간에 돌았고, host load는 92~143이었습니다.

## Evidence
- 실패한 test:
  - `test_suspend.py::test_a_failed_resume_leaves_the_record_and_start_can_take_over`: `{'leader': 'provider_exited', 'seat-0': 'timeout'}`
  - `test_watch.py::test_a_stalled_worker_with_a_background_shell_names_it_in_the_message`: `SessionError: The command's total wait limit expired.`(`lifecycle.py:65`)
  - `test_suspend.py::test_resume_lost_reopens_the_slots_that_have_no_record_in_the_same_conversations`
- 같은 clone에서 세 test만 다시 실행하면 load 143에서 3 passed(307초)입니다.
- 이전 release 검증(0.7.1, 0.8.0, 0.8.1)에서는 agent-session test가 모두 통과했습니다(846개, load 70~130).
- README: "Agent-session test는 seat 여럿이 같은 host에서 동시에 검증하는 평소 부하에서 같은 결과를 냅니다. 한도(`AGENT_SESSION_TEST_TIMEOUT`, 기본 120초)는 host가 이보다 심하게 느릴 때만 늘립니다."
- test의 fake provider(`tests/fixtures/agent_session_fake_provider.py`)는 `UserPromptSubmit` hook(TEAM-002)을 실행하지 않습니다. 그래서 TEAM-002가 원인은 아닙니다.
- 가설(미확인): 이 세 test는 run 둘(Leader, seat)을 띄우고 기다리는 시간이 길어서, release 검증처럼 두 줄기에 각각 `-n 8`이 겹치는 부하에서 한도를 넘깁니다.

## Contract
- release 검증의 다섯 명령은 이 workstation의 평소 release 조건(두 줄기 병렬, load 150 안팎)에서 같은 결과를 냅니다. 부하 때문에 실패하지 않습니다.
- test가 기다리는 결과(무엇을 판정하는지)는 바뀌지 않습니다. 한도를 늘리는 것만으로 고치면 근거(측정)를 적습니다.

## Disposition
- 2026-11-11 Leader: 고친다(Leader 판정). release 검증을 막는 test 결함입니다. 0.9.0은 실패한 세 test를 다시 실행해 통과한 근거로 release했습니다.
- 2026-11-11 Leader: open -> todo. Leader 판정: release 검증을 막는 test 결함
- 2026-11-11 Leader: 범위를 넓힙니다. 같은 0.9.0 검증에서 install/tests 4개도 설치 명령의 300초 한도를 넘겨 실패했습니다. 대상은 `test_tmux.py::test_t20_user_bindings_are_kept_and_reported_as_skipped`와 `test_tmux_version.py::test_check_passes_when_the_first_tmux_is_the_minimum_or_newer`의 3.8, next-3.9, 4.0입니다. 전체 1시간 45분이 걸렸고 load는 90~140이었습니다. 다시 실행하면 5 passed였습니다(load 40~100). 그때 seat 1 Worker가 띄운 install test 두 개가 부모 없이 2시간 넘게 돌고 있었습니다. 이 4개도 같은 기준(부하 아래 반복)으로 고칩니다. 0.9.0은 실패한 test를 다시 실행해 모두 통과한 근거로 release했습니다.

## Implementation
읽을 문서: `tools/agent-session/tests/test_suspend.py`, `test_watch.py`, `tests/conftest.py`의 `AGENT_SESSION_TEST_TIMEOUT`, `agent_session/lifecycle.py`의 wait limit, README 검증, [release 절차](../../project-team/release.md), [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 세 test가 한도를 넘기는 단계를 부하 아래에서 재현해 기록합니다. 예: 다른 줄기와 함께 `-n 8`로 실행. 원인을 Result에 적습니다.
2. 고칩니다. 예: test가 기다리는 대상을 상태 기반으로 바꾸기, 불필요한 대기 줄이기, 한도를 test 규모에 맞추기.
3. 반복 실행(부하 아래 5회)에서 실패가 없음을 보입니다.

의존: 없음.

위험 등급: 낮음. test만 바꿉니다. 제품 코드를 바꾸면 그 행의 명령도 실행합니다.

## Verification
1. `python -m pytest -q -n 8 tools/agent-session/tests`(다른 줄기와 병렬, 부하 아래)
2. 세 test의 부하 아래 반복 결과를 Result에 적습니다.
