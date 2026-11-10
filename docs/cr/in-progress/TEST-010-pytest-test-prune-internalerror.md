# TEST-010: 동시에 시작한 pytest가 test 임시 디렉터리 정리(prune)의 경합으로 INTERNALERROR가 납니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S3
- Base: d66c2615f3aff4f6f161d1491949c2e2ec745777 2026-11-10T10:48:14+09:00

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
