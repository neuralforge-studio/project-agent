# TEST-015: test가 PATH를 통째로 바꾸면 crontab shim이 가려져 실제 사용자 crontab을 씁니다

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S2

## Symptom
2026-11-12 SESSION-016을 검증하는 중에 새 test 하나가 실제 사용자 crontab에 test용 구역 `# >>> project-agent: alpha >>>`을 썼습니다. 그 test는 PATH를 `<디렉터리>:/usr/bin:/bin`으로 통째로 바꿨고, 이 때문에 `crontab` shim이 가려졌습니다. Worker가 결과를 보다가 발견해 손으로 그 구역만 지웠습니다. test run은 이 사실을 알리지 않았습니다.

실제 crontab에는 사용자 작업(3줄)과 운영 중인 `check` 작업이 있습니다. test가 이를 고치면 사용자 작업이나 정체 점검이 깨질 수 있습니다. [README 검증](../../../README.md#검증)의 규칙 "Test가 사용자 계정에 남기는 자원은 test가 끝나면(통과·실패·중단 모두) test 전 수준으로 돌아갑니다"를 어깁니다.

## Evidence
- `tools/agent-session/agent_session/cron.py`는 PATH에서 찾은 `crontab` 명령만 씁니다. 모듈 설명은 "a test replaces it with a shim"입니다. 그래서 PATH를 통째로 바꾼 test는 `/usr/bin/crontab`(실제 사용자 spool)에 닿습니다.
- TEST-014는 HOME을 run마다 격리하지만 crontab은 HOME 밖의 사용자 spool이라 그 격리가 덮지 못합니다. README 검증이 지키는 자원 목록(tmux server, 임시 디렉터리, 실제 HOME)에도 crontab이 없습니다.
- crontab을 쓰는 제품 경로는 `agent-session cron add|rm`과 Leader 시작의 `ensure_check`(start·restart·resume)입니다. 읽는 경로는 설치기 `check`·`uninstall`(INSTALL-008)이고, BOARD-027이 Board에 더할 예정입니다. 이 경로를 실행하는 test 가운데 shim 없이 돌 수 있는 것이 어느 것인지는 Worker가 확인합니다.
- 발견한 test는 SESSION-016 제출에서 shim이 있는 PATH 앞에 붙이도록 고쳤습니다. 같은 실수를 막거나 드러내는 장치는 아직 없습니다.

## Contract
1. 어떤 test도 실제 사용자 crontab을 쓰지 않습니다. 통과·실패·중단 모두에 적용하고, 다섯 검증 명령 전부와 `cargo test`가 대상입니다.
2. 이 규칙은 test가 지키고, 새 test가 어기면 드러납니다. test가 PATH를 통째로 바꿔도 마찬가지입니다. 방법은 Worker가 정하되 각 도구 test의 독립 실행(README "다섯 명령은 서로 독립")을 유지합니다.
3. 제품의 crontab 동작은 바뀌지 않습니다. 제품 코드에 test 전용 분기가 필요하면 그 이유를 적습니다.
4. README 검증의 자원 규칙에 crontab을 더합니다.

## Disposition
- 2026-11-12 Leader 판정: 구현한다. 근거가 있는 결함입니다(SESSION-016 검증 중 실제 crontab에 test 구역이 써졌고, test run은 알리지 못했습니다). TEST-014(실제 HOME의 lock 파일)와 같은 규칙의 빈틈입니다. 공통 test helper를 바꾸면 다섯 명령을 모두 다시 돌려야 해서 host 부하가 큽니다. 그래서 BOARD-018(Rust sidebar)을 통합한 뒤 todo로 옮겨 시작합니다.

## Implementation
읽을 문서: [README 검증](../../../README.md#검증)의 자원 규칙, [TEST-014 CR](../done/TEST-014-test-home-cache-project-item-locks-lock.md)과 `tools/tests/private_root.py`(HOME 격리 방식), `tools/agent-session/agent_session/cron.py`, `tools/agent-session/tests/test_cron.py`·`test_check.py`의 `crontab` shim, `install/tests`의 `fake_crontab`, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 실제 crontab에 닿을 수 있는 test 경로를 찾습니다(cron 명령, Leader 시작의 `ensure_check`, 설치기 `check`·`uninstall`).
2. test run 전체에서 실제 crontab 쓰기를 막거나, 쓰면 그 run이 실패하게 합니다. test가 PATH를 통째로 바꾼 경우도 포함합니다.
3. 막는 장치가 동작함을 test로 보입니다. 일부러 shim을 가린 test가 실제 crontab을 바꾸지 못하거나 실패로 드러나야 합니다. 이 test 자체도 실제 crontab을 바꾸지 않습니다.
4. README 검증의 자원 규칙에 crontab 항목을 더합니다.

위험 등급: 중간(공통 test helper 변경).

## Verification
- README 검증 표에서 바꾼 경로의 행 명령을 모두 제출 commit에서 실행합니다. 공통 helper(`tools/conftest.py`, `install/tests/conftest.py`, `tools/tests/*`)를 바꾸면 다섯 명령 모두와 `(cd tools/project-board/rust && cargo test --offline --locked)`입니다.
- 실행 전후로 `crontab -l`의 내용이 바이트 단위로 같아야 합니다. 그 사이 운영 Leader 시작이 고친 경우는 그 차이를 설명합니다. 이 결과를 Result에 적습니다.
- 문서: 고친 문서의 상대 link 검사, `python -m pytest -q tools/test_distribution_boundary.py`.
