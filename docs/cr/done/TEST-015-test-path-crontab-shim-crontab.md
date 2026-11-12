# TEST-015: test가 PATH를 통째로 바꾸면 crontab shim이 가려져 실제 사용자 crontab을 씁니다

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S2
- Base: fe4cbf2efd4e2f9e2ae9e8741d33ad198c47e802 2026-11-12T12:43:09+09:00
- Outcome: fixed

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
- 2026-11-12 Leader: BOARD-018을 통합하고 0.11.0을 release했습니다. 시작합니다. TMUX-004가 같은 때 crontab `check` 줄과 설치기의 crontab 해석을 고치므로, 먼저 통합된 쪽을 `origin/main`에서 merge해 맞춥니다.
- 2026-11-12 Leader: open -> todo.
- 2026-11-12 Leader 검토(제출 fd3edaf8af6d62e847a3860e8288f4ce0da79376): 인수.
  - 원인(PATH의 shim이 유일한 보호)을 고칩니다. run의 pytest process에 `PR_SET_NO_NEW_PRIVS`를 걸면 set-uid root인 실제 `crontab`이 권한을 얻지 못합니다. 그래서 PATH를 어떻게 바꾼 test도, 그 자식과 손자도 실제 crontab을 읽거나 쓰지 못합니다. shim은 영향이 없습니다.
  - 사후 비교 대신 막는 방식을 고른 이유(쓴 뒤에야 알고, 운영 Leader의 정당한 변경과 섞임)가 맞습니다. 제품 코드와 test 전용 분기는 없습니다. 세 conftest(각 명령의 독립 실행)가 같은 함수 `real_crontab.block()`을 부르고, README 자원 규칙에 crontab 항목과 한계(비 Linux는 경고, Rust test는 읽기만)를 적었습니다.
  - 검증(fd3edaf): agent-session 936, project-board 460, 네 번째 명령 149(`test_real_crontab.py` 포함), `install/tests` 316 passed·2 skipped, `cargo test` 83 passed. project-item 141은 9262b59 결과를 재사용합니다(merge가 바꾸지 않음). 실행 전후 실제 crontab은 다른 project 운영 Leader가 더한 `fc2_npu`·`ipweaver` 구역만 다르고 test 구역은 없습니다.
- 2026-11-12 Leader: 제출 fd3edaf8af6d62e847a3860e8288f4ce0da79376를 인수합니다.
- 2026-11-12 Leader: in-progress -> done, Outcome fixed. 통합 b504b41 (origin/main)

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

## Result
- 제출 commit: fd3edaf8af6d62e847a3860e8288f4ce0da79376

### 변경
- `tools/tests/real_crontab.py`(신규): Linux에서 run의 pytest process에 `PR_SET_NO_NEW_PRIVS`를 겁니다. 이 flag는 xdist worker와 test가 띄우는 모든 자식 process에 상속되고 풀 수 없으며, exec 때 set-uid bit를 무시합니다. `/usr/bin/crontab`은 set-uid root(spool은 root 전용)라서 PATH를 어떻게 바꾼 test도 실제 crontab을 읽기·쓰기 모두 `Permission denied`로 얻지 못합니다. shim은 일반 script라 영향이 없습니다. Linux가 아니면 `RuntimeWarning`을 냅니다(막을 수 없음).
- `tools/conftest.py`, `install/tests/conftest.py`, `integrations/tmux/conftest.py`(신규; 단독 실행 때 필요하고 release에서 제외되는 `conftest*`): `pytest_configure`에서 `block()`을 호출합니다. Rust sidebar는 `crontab -l`로 읽기만 하고 쓰는 코드가 없습니다(merge한 BOARD-027의 `rust/src/data/crontab.rs`).
- `tools/test_real_crontab.py`(신규, 5개): run이 NoNewPrivs 상태, `PATH=/usr/bin:/bin`·`<디렉터리>:/usr/bin:/bin`로 바꾼 test의 `crontab -l`이 `Permission denied`, 손자 process도 막힘, shim은 차단 아래에서 동작, 비 Linux는 경고 후 False. 읽기만 하므로 차단이 깨져도 실제 crontab은 바뀌지 않습니다(읽기와 쓰기의 필요 권한이 같음).
- README 검증: 네 번째 명령에 `tools/test_real_crontab.py`를 더하고 자원 규칙에 "실제 crontab" 항목을 추가했습니다.
- 제품 코드 변경 없음(계약 3). test 전용 분기 없음.

### 방식 판단
- 사후 비교(run 전후 `crontab -l`)는 쓴 뒤에야 알고, 중단된 run과 운영 Leader의 정당한 변경이 섞입니다. 그래서 막는 방식을 골랐습니다. 한계: 차단은 `Permission denied`로 드러나는데, Leader 시작의 `ensure_check`는 crontab 오류로 시작을 멈추지 않도록 설계돼 있어 그 경로의 test는 crontab 내용 단언에서 실패합니다. 비 Linux는 막지 못하고 경고만 냅니다.
- 이 test run 도중 `sudo`·`su`처럼 권한을 얻는 명령은 쓸 수 없습니다. 기존 test에 그런 것은 없었고 아래 전체 run이 통과했습니다.

### 검증
작업 commit 9262b59에서 다섯 명령과 cargo를 실행한 뒤 `origin/main`(BOARD-027 등)이 진행해 merge했고(c3a3584, 충돌 없음), README 한 문장을 고쳐 제출 commit fd3edaf가 됐습니다. 아래는 모두 fd3edaf에서 실행한 결과입니다. `tools/project-item/**`는 merge가 바꾸지 않아 다시 실행하지 않고 9262b59의 결과(141 passed)를 재사용합니다.

| 명령 | 결과 |
| --- | --- |
| `python -m pytest -q -n 8 tools/agent-session/tests` | 936 passed |
| `python -m pytest -q tools/project-item/tests` | 141 passed (9262b59 결과 재사용) |
| `python -m pytest -q tools/project-board/tests` | 460 passed |
| 네 번째 명령(`test_real_crontab.py` 포함) | 149 passed |
| `python -m pytest -q -n 8 install/tests` | 316 passed, 2 skipped |
| `(cd tools/project-board/rust && cargo test --offline --locked)` | 83 passed |
- 문서: README의 상대 link 검사(깨진 link 0). `tools/test_distribution_boundary.py`는 네 번째 명령에 포함돼 통과했습니다.
- merge로 BOARD-027의 Rust sidebar가 `crontab -l`을 읽습니다(`rust/src/data/crontab.rs`, 읽기만). cargo test는 pytest 밖이라 차단 대상이 아니며 README에 그렇게 적었습니다. Board의 Python·Rust test는 모두 이 차단 아래에서 통과했습니다.
- crontab 전후 비교: 실행 전 `crontab -l`(1396바이트)은 `project-agent`·`agent` 구역과 사용자 작업입니다. 모든 run을 마친 뒤에는 그 내용 뒤에 `fc2_npu`·`ipweaver` 구역(각 `check` 줄 3줄, 빈 줄 포함 10줄)만 더해졌고 기존 줄은 바이트 단위로 같습니다. 더해진 구역은 다른 project의 운영 Leader 시작(`ensure_check`, 실제 0.11.0 release 경로)이 쓴 것입니다. test가 만드는 구역(`alpha` 등)은 없습니다.
- 첫 실행에서 세 명령이 내 실행 script의 인자 분리 실수로 실행되지 않아 같은 commit에서 다시 실행했습니다. 위 표는 실행된 결과만 담았습니다.
