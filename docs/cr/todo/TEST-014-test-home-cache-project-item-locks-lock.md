# TEST-014: test가 실제 HOME의 ~/.cache/project-item/locks에 lock 파일을 남깁니다

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S3

## Symptom
test 실행이 실제 사용자 HOME의 `~/.cache/project-item/locks/`에 lock 파일을 남깁니다. 2026-11-12 02:00 KST 현재 2,906개이고(디렉터리 항목 크기 225 KB, NFS), 하루에 수백 개씩 늘어납니다(11일 748개, 12일 0시~2시 55개). 가장 새 파일(01:59:14~15)은 seat들이 test를 돌리던 시각에 생겼습니다. 실제 등록 project의 root는 20개 안팎이므로 나머지는 test가 만든 임시 root의 잠금입니다.

[README 검증](../../../README.md#검증)의 규칙 "Test가 사용자 계정에 남기는 자원은 test가 끝나면(통과·실패·중단 모두) test 전 수준으로 돌아갑니다"를 어깁니다.

## Evidence
- 잠금 파일 경로는 `tools/project-item/project_item/store.py`의 `lock_path`가 정합니다: `Path.home() / ".cache" / "project-item" / "locks" / <root 경로 sha256 앞 16자>.lock`. 잠금을 놓아도 파일은 지우지 않습니다(지우면 같은 root의 다른 process와 상호 배제가 깨지므로 지우지 않는 것이 맞습니다).
- `tools/project-item/tests/conftest.py`는 HOME을 격리합니다("an isolated HOME (lock files)"). `tools/project-board/tests`에는 HOME을 바꾸는 곳이 없습니다. `tools/agent-session/tests`는 일부 파일만 HOME을 바꿉니다(`test_config.py`, `test_remote_skills.py`, `fixtures/agent_session_fixture.py`의 일부).
- 잠금을 잡는 호출: agent-session의 `jobs.claim`·`unclaim`(start·stop·resume), `remote_bridge`, project-board 결정 창의 답변 접수(`answer_decide`), `render`. 이 경로를 실행하는 test가 임시 root로 실제 HOME에 파일을 만듭니다(어느 test인지는 Worker가 확인합니다).
- 쓰레기 파일 말고도, test가 실제 HOME의 잠금 디렉터리를 쓰면 실제 운영 잠금과 같은 디렉터리를 공유합니다.

## Contract
1. 어떤 test도 실제 HOME의 `~/.cache/project-item/`에 파일을 만들지 않습니다(통과·실패·중단 모두). 다섯 검증 명령 전부와 `cargo test`에 적용합니다.
2. 이 규칙은 test가 지키고, 새 test가 어겨도 드러나게 합니다(예: 공통 conftest가 실제 HOME의 잠금 디렉터리를 test 전후로 비교하거나, test 중에는 실제 HOME에 쓸 수 없게 함). 방법은 Worker가 정하되 각 도구 test의 독립 실행(README "다섯 명령은 서로 독립")을 유지합니다.
3. 제품의 잠금 경로와 동작(실제 운영)은 바뀌지 않습니다.
4. 이미 쌓인 파일은 이 CR을 통합한 뒤 Leader가 정리합니다. 실제 등록 root(등록 파일의 `path_cr`·`path_decide`)의 잠금 파일은 남기고 나머지만 지웁니다.

## Disposition
- 2026-11-12 Leader: 구현한다. Leader 판정: README 검증의 자원 규칙을 어기는 test 결함입니다(Symptom의 파일 수와 시각). 제품 동작은 바꾸지 않습니다.
- 2026-11-12 Leader: open -> todo. Leader 판정: README 자원 규칙을 어기는 test 결함

## Implementation
읽을 문서: [README 검증](../../../README.md#검증)의 자원 규칙, `tools/project-item/project_item/store.py`의 `lock_path`·`root_lock`, `tools/project-item/tests/conftest.py`(격리 HOME의 예), `tools/conftest.py`, 각 도구의 `tests/conftest.py`, `tools/tests/private_root.py`, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 실제 HOME에 lock 파일을 만드는 test를 찾습니다(예: test 전후로 실제 HOME 잠금 디렉터리의 목록을 비교하는 일시 계측). 찾은 test 목록과 경로(어느 호출이 잠금을 잡는지)를 Result에 적습니다.
2. 그 test들이 격리된 HOME(또는 잠금 위치)을 쓰게 합니다. 제품 코드에 test 전용 분기를 넣지 않는 방법을 우선합니다.
3. 새 test가 어겨도 드러나게 하는 장치를 둡니다(Contract 2). 다른 seat가 같은 시각에 옛 코드로 test를 돌려 실제 HOME에 파일을 만들 수 있으므로, 장치는 "이 test process가 만든 파일"만 판정하거나 실제 HOME에 쓰지 못하게 하는 방식이어야 합니다(디렉터리 전체 개수 비교는 다른 seat 때문에 거짓 실패가 납니다).
4. README 검증의 자원 규칙 목록에 이 항목을 더합니다.

의존: 없음. BOARD-018이 `tools/project-board/tests`를 크게 고치고 있으니 제출 전에 `origin/main`을 merge합니다. 위험 등급: 낮음.

## Verification
1. README 검증 표에서 바꾼 경로의 행 명령 전부를 제출 commit에서 실행합니다. `tools/conftest.py`나 여러 도구가 함께 쓰는 test helper를 바꾸면 다섯 명령 모두(`python -m pytest -q -n 8 tools/agent-session/tests`, `python -m pytest -q tools/project-item/tests`, `python -m pytest -q tools/project-board/tests`, 네 번째 명령, `python -m pytest -q -n 8 install/tests`). 도구별 conftest만 바꾸면 그 도구 행의 명령 전부. 문서를 바꾸면 상대 link 검사와 `tools/test_distribution_boundary.py`.
2. 그 실행들에서 이 CR의 test process가 실제 HOME의 `~/.cache/project-item/`에 만든 파일이 0개임을 Result에 적습니다(1번의 계측 방법으로).
