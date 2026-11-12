# TEST-016: test가 성공을 기다리는 한도를 숫자로 직접 줘서 부하에서 release 검증이 실패합니다

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S2

## Symptom
2026-11-12 0.11.1 release 검증(clone, release commit 136a489)에서 agent-session test 1건이 실패해 release가 멈췄습니다.
- `test_lifecycle.py::test_claude_restart_replaces_a_leader_whose_cli_is_gone_whatever_its_last_stop_report_listed[fixture-cron-leader]`: `SessionError: The command's total wait limit expired.`(`_wait_ready`의 `remaining`). 결과는 1 failed, 933 passed였고 host load는 80~90이었습니다.
- 이 test는 SESSION-017이 더했습니다. 성공을 기대하는 restart(새 run 시작 포함)에 `env.manager(timeout=20)`을 줍니다.

## Evidence
- 기다림 한도의 원본은 `tools/agent-session/tests/fixtures/agent_session_fixture.py`의 `command_timeout()`입니다(`DEFAULT_TIMEOUT` 240초, `AGENT_SESSION_TEST_TIMEOUT`이 덮어씀). TEST-003·TEST-013이 측정한 근거가 주석에 있습니다. 부하에서 `start` 하나가 최대 80.3초였습니다. `env.manager()`는 인자가 없으면 이 값을 씁니다.
- 숫자를 직접 준 곳: `env.manager(timeout=N)` 17곳(`test_caller.py` 180초 4곳, `test_lifecycle.py` 2·3·5·20·30초), test 안의 `time.monotonic() + N` 기다림 10곳(예: `end_cli_on_its_own`의 10초).
  - 일부는 한도 자체를 확인하는 test입니다(`test_fixture_timeout.py`, 일부러 짧은 한도로 `timeout`을 기대하는 test).
  - 나머지는 성공을 기대하면서 원본보다 짧은 한도를 줘서, 부하에 따라 실패합니다. 20초를 준 4곳 중 2곳은 SESSION-009, 2곳은 SESSION-017에서 생겼습니다.
- [README 검증](../../../README.md#검증): "Agent-session test는 seat 여럿이 같은 host에서 동시에 검증하는 평소 부하에서 같은 결과를 냅니다. 한도(`AGENT_SESSION_TEST_TIMEOUT`, 기본 240초)는 host가 이보다 심하게 느릴 때만 늘립니다." 숫자를 직접 준 test는 이 한도를 따르지 않으므로, `AGENT_SESSION_TEST_TIMEOUT`을 늘려도 고쳐지지 않습니다.

## Contract
1. 성공을 기대하는 기다림은 모두 기다림 한도의 원본 하나(`command_timeout()` 또는 그 원본에서 나온 값)를 따릅니다. test가 숫자를 따로 갖지 않습니다.
2. 일부러 짧은 한도를 주는 test(한도에 걸리는 동작을 확인)는 그 이유를 test에 적고, 원본과 무관하게 짧아도 결과가 부하에 흔들리지 않게 합니다(예: 끝나지 않는 동작에만 짧은 한도를 줌).
3. 새 test가 숫자 한도로 성공을 기다리면 드러나게 합니다. 방법은 Worker가 정합니다.
4. agent-session 밖의 test(project-board, project-item, install, integrations)에 같은 모양이 있으면 같은 원칙으로 다룹니다. 각 도구 test의 독립 실행은 유지합니다.

## Disposition
- 2026-11-12 Leader 판정: 구현한다. 재현 근거가 있는 결함이고 release 검증을 막았습니다(0.11.1 검증 중단).
  - 판단 기준은 사용자 지시 "판단의 주요관점은 ** Root cause & SSOT **"입니다. 실패한 한 test만 늘리지 않습니다. 기다림 한도의 원본(TEST-013의 `command_timeout()`)을 따르지 않는 모든 곳을 같은 원칙으로 고칩니다.
  - 0.11.1 단독 release는 접었습니다. 다음 release는 이 CR을 통합한 뒤 검증합니다. seat가 비면 BOARD-028보다 먼저 시작합니다.
- 2026-11-12 Leader: open -> todo.

## Implementation
읽을 문서:
- [README 검증](../../../README.md#검증)의 agent-session 한도 문장.
- `tools/agent-session/tests/fixtures/agent_session_fixture.py`의 `command_timeout()`과 주석(TEST-003·TEST-013 측정).
- [TEST-013 CR](../done/TEST-013-release-agent-session-test-3-host.md), [SESSION-017 CR](../done/SESSION-017-leader-run-self-restart-cli-finish-lock-timeout-agent.md)(실패한 test를 더함).
- 절차: [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 다섯 검증 명령의 test에서 숫자로 준 기다림 한도를 모두 찾아 목록을 Result에 적습니다. 각각을 "성공을 기다림"과 "한도에 걸림을 확인"으로 나눕니다.
2. 성공을 기다리는 곳은 원본을 따르게 합니다. 한도를 확인하는 곳은 이유를 적고, 부하에 흔들리지 않는 모양으로 둡니다.
3. 새 test가 숫자 한도로 성공을 기다리면 드러나는 장치를 둡니다.
4. 부하에서 확인합니다. 실패했던 test를 다른 `-n 8` suite와 동시에 여러 번 돌려 통과하는지 봅니다.

위험 등급: 낮음~중간(test만 바뀜. 공통 helper를 바꾸면 다섯 명령에 영향).

## Verification
- README 검증 표에서 바꾼 경로의 행 명령을 모두 제출 commit에서 실행합니다. `tools/agent-session/tests`만 바꾸면 `python -m pytest -q -n 8 tools/agent-session/tests`입니다. 다른 도구의 test나 공통 helper(`tools/conftest.py`, `tools/tests/*`, fixture)를 바꾸면 그 행의 명령, 공통 helper면 다섯 명령 모두와 `cargo test`입니다.
- 부하 확인 결과(동시 실행한 suite, host load, 반복 횟수, 결과)를 Result에 적습니다.
