# TEST-010: 동시에 시작한 pytest가 test 임시 디렉터리 정리(prune)의 경합으로 INTERNALERROR가 납니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S3
- Base: d66c2615f3aff4f6f161d1491949c2e2ec745777 2026-11-10T10:48:14+09:00
- Outcome: fixed

## Symptom
pytest 여러 개가 거의 동시에 시작하면 그중 하나가 `tools/conftest.py`의 `private_root.configure` → `prune()`에서 `FileNotFoundError`(INTERNALERROR)로 끝나고 test를 하나도 실행하지 않습니다. seat 여럿이 같은 host에서 동시에 검증하는 평소 상황(README 검증)에서 일어납니다.

## Evidence
- Leader 재현(2026-11-10, 802bb93 복제본): `python3 -m pytest -q tools/agent-session/tests/test_lifecycle.py -k startup_dialog`을 동시에 6개 실행했고, 그중 1개가 아래 오류로 끝났습니다.
  ```
  INTERNALERROR>   File ".../tools/conftest.py", line 2
  INTERNALERROR>     private_root.configure(config)
  INTERNALERROR>   File ".../tools/tests/private_root.py", ... prune()
  INTERNALERROR>     info = directory.lstat()
  INTERNALERROR> FileNotFoundError: [Errno 2] No such file or directory: '/primehome/swain/tmp/pt-jwskhvzd'
  ```
- `prune()`은 `TMPDIR/pt-*`를 나열한 뒤 항목마다 `lstat`합니다. 그 사이에 다른 pytest의 `prune()`이 같은 디렉터리를 지우면 `lstat`이 실패합니다.

## Contract
- 동시에 시작한 pytest들은 서로의 정리 때문에 실패하지 않습니다. 이미 사라진 항목은 정리된 것으로 봅니다.
- 정리 규칙(최근 5개 보존, 진행 중인 run 보존, 소유자 표시 없는 옛 디렉터리 24시간)은 바꾸지 않습니다(README 검증, `private_root.py`가 소유).

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 재현이 있는 test 기반 결함이며, seat 여럿이 동시에 검증하는 평소 운영에서 검증 실행을 통째로 실패시킵니다.
- 2026-11-10 Leader: open -> todo. 동시 검증을 깨는 test 기반 결함
- 2026-11-10 Leader: 제출 c0bbac67abf6f1412ecc8795e07dd65b29b40e27를 인수합니다. Leader review: prune()이 다른 pytest가 이미 지운 항목(lstat의 FileNotFoundError)을 정리 완료로 보고 건너뜁니다. 정리 규칙은 그대로입니다. _owner와 rmtree(ignore_errors)가 이미 같은 경합을 견딘다는 판정과, tmux_test_server 정리 경로에 같은 모양이 없다는 판정을 확인했습니다. 수정 전 실패하는 test가 있습니다. 검증은 1d754e8에서 다섯 명령, merge commit c0bbac6에서 agent-session 806 passed입니다. 이 제출 뒤 main에 들어온 v0.4.0 release commit(VERSION)과 TEST-011(test_tmux.py)의 입력 변경은 PERF-002가 main을 merge한 commit에서 다섯 명령을 다시 실행해 함께 확인합니다.
- 2026-11-10 Leader: in-progress -> done, Outcome fixed. 통합 bb89816(Merge cr/TEST-010, 제출 c0bbac6). origin/main 반영 확인. CHANGELOG Unreleased에 더했습니다.

## Implementation
읽을 문서: [README 검증](../../../README.md#검증)(test 자원 규칙), [`tools/tests/private_root.py`](../../../tools/tests/private_root.py), [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. `prune()`과 그 안의 파일 조회·삭제가 다른 process가 이미 지운 항목(`FileNotFoundError`)을 정리 완료로 보게 합니다. 대상은 `lstat`, 소유자 표시 읽기, 삭제 등입니다. 다른 OSError는 지금 처리 방식을 유지합니다.
2. 같은 모양의 경합이 `private_root.py`와 `tools/tests/tmux_test_server.py`의 정리 경로에 더 있는지 확인하고 함께 고칩니다.
3. 동시에 여러 번 `prune()`하는 test를 추가합니다. 예: 두 process 또는 thread가 같은 후보 목록을 동시에 정리합니다. 이 test는 수정 전에 실패해야 합니다.

의존: 없음.

위험 등급: 낮음.

## Verification
1. 수정 전 실패와 수정 뒤 통과(3단계의 test).
2. README 검증 표 `tools/conftest.py, 여러 도구가 함께 쓰는 test helper` 행: 다섯 명령 모두. 실패 이름이 보이도록 `-rf`를 붙입니다.

## Result
- 제출 commit: c0bbac67abf6f1412ecc8795e07dd65b29b40e27
- 수정: `tools/tests/private_root.py`의 `prune()`이 `lstat`의 `FileNotFoundError`(다른 pytest의 prune이 목록 뒤에 지운 항목)를 정리 완료로 보고 건너뜁니다. 정리 규칙(5개 보존·진행 중 보존·24시간)은 그대로입니다.
- 다른 정리 경로: `_owner`(OSError 처리)와 `rmtree(ignore_errors=True)`는 이미 같은 경합을 견딥니다. `tmux_test_server.py`의 `release_path`는 `ProcessLookupError`를 처리하고 shell 정리는 오류를 무시해 같은 모양의 경합이 없어 바꾸지 않았습니다.
- test: `tools/test_private_root.py`에 `test_prune_counts_a_root_that_another_run_already_removed_as_removed`(listing·lstat 두 시점)를 추가했습니다. 다른 run의 prune이 같은 목록을 먼저 지우는 상황을 재현하며, 수정 전 `listing`이 `FileNotFoundError`로 실패했고 수정 뒤 통과합니다.
- 검증(수정 commit 1d754e8에서 README 다섯 명령, `-rf`): `agent-session/tests` -n 8 806 passed, `project-item/tests` 125 passed, `project-board/tests` 161 passed, 네 번째 명령 114 passed, `install/tests` -n 8 267 passed·2 skipped.
- 근거 재사용: 그 뒤 `origin/main`(TEST-009·PERF-001 등)을 merge했습니다. merge는 `private_root.py`·`conftest.py`를 바꾸지 않아 다섯 명령은 다시 실행하지 않고, merge한 상태에서 `test_private_root.py`·`test_tmux_test_server.py`·startup_dialog 포함 focused 14 passed를 확인했습니다.
- 참고: 동시 6개 재현은 작업 중 별도 부하로 4개가 test 단언(`ready`)에서 실패했으나 INTERNALERROR는 없었습니다. 이는 TEST-009(merge에 포함)가 다루는 결함입니다.
- merge 뒤 재검증(Leader 요청): merge commit c0bbac6에서 `python -m pytest -q -n 8 -rf tools/agent-session/tests` 806 passed(TEST-009가 바꾼 `test_lifecycle.py` 포함). 코드 변경이 없어 제출 hash는 그대로입니다. 다른 네 명령은 merge가 입력을 바꾸지 않아 위 결과를 재사용합니다.
