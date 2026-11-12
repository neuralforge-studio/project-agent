# TEST-017: test 실행을 process tree째 끝내면 installer test의 tmux server가 하루 동안 남습니다

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S3

## Symptom
2026-11-12 15:28 KST, Leader가 0.11.1 release 검증을 멈췄습니다. clone에서 돌던 `python -m pytest -q -n 8 install/tests`의 shell을 Claude `TaskStop`으로 끝냈습니다. 10분 뒤에도 installer test harness의 tmux server 4개가 남아 있었습니다(`tmux -S <TMPDIR>/pt-_c_1stg1/m/pi-*/s -f /dev/null new-session -d -s harness sleep 86400`, 하나는 Python 자식 포함). `sleep 86400`이라 그대로 두면 하루 동안 남습니다.

[README 검증](../../../README.md#검증)의 규칙을 어깁니다: "모든 test server는 … `claim`은 소유 pytest process가 사라지면(SIGKILL·SIGTERM 포함) 같은 정리를 하는 watchdog을 함께 띄웁니다".

## Evidence
- 남은 server들에 대응하는 watchdog process(`sh -c 'while kill -0 OWNER …; done; CLEANUP' sh <socket>`)는 하나도 없었습니다. installer harness는 `tools/tests/tmux_test_server.watch_path`로 watchdog을 띄웁니다(`install/tests/harness.py:309`, `start_new_session=True`).
- socket 파일은 이미 지워져 있었습니다(`pi-*` 디렉터리는 15:30~15:31에 바뀜). 그래서 정리 함수 `release_path`(`tmux -S <socket> kill-server`)로는 server에 닿지 못했고, Leader가 server PID 4개를 `kill`로 멈췄습니다.
- 가설(확인하지 않음): `TaskStop`이 process tree 전체(새 session으로 띄운 watchdog 포함)를 끝내서 watchdog이 정리 전에 죽었습니다. 같은 일은 process tree를 통째로 끝내는 다른 경로(CI, 터미널 종료)에서도 생길 수 있습니다. socket 파일을 누가 지웠는지는 확인하지 않았습니다.
- 지금 정리 책임은 server 밖의 별도 process(watchdog)에 있습니다. 그 process가 함께 죽으면 아무도 정리하지 않습니다.

## Contract
1. test가 띄운 tmux server는 소유 test process가 어떻게 끝나든(정상, 실패, SIGTERM, SIGKILL, process tree 전체 종료) 그 뒤 정해진 시간 안에 사라집니다. socket 파일과 Board가 server마다 만드는 디렉터리도 사라집니다.
2. 정리가 별도 process 하나의 생존에 기대지 않게 합니다. 예를 들어 server 안의 session 명령이 소유 process를 지켜보다 끝나면 server도 끝나게 할 수 있습니다. 방법은 Worker가 정합니다.
3. 다섯 검증 명령의 모든 test server(`claim`·`watch`·`watch_path`)에 적용합니다. README의 규칙 문장을 실제 보장에 맞게 고칩니다.
4. 각 도구 test의 독립 실행(README "다섯 명령은 서로 독립")은 유지합니다.

## Disposition
- 2026-11-12 Leader 판정: 구현한다. Leader가 직접 겪은 재현이 있는 결함입니다(server 4개를 PID로 정리함). README 검증의 자원 규칙이 약속한 보장을 실제로는 못 합니다.
  - 판단 기준은 사용자 지시 "판단의 주요관점은 ** Root cause & SSOT **"입니다. 원인은 정리 책임이 server 밖의 별도 process 하나에 있다는 것입니다. 그 구조를 고칩니다.
  - seat가 비면 TEST-016(release를 막음), BOARD-028 다음에 시작합니다.
- 2026-11-12 Leader: open -> todo.

## Implementation
읽을 문서:
- [README 검증](../../../README.md#검증)의 자원 규칙.
- 코드: `tools/tests/tmux_test_server.py`(`claim`·`watch`·`watch_path`·`release`·`CLEANUP`·`WATCHDOG`), `install/tests/harness.py`, 각 도구의 conftest와 fixture가 test server를 띄우는 곳.
- 절차: [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 재현: test process를 process tree째 끝내는 경우(watchdog 포함 SIGKILL)와 SIGTERM, 정상 종료에서 server·socket·Board 디렉터리가 남는지 확인합니다. socket 파일을 지우는 주체도 확인합니다.
2. 정리가 별도 process 하나의 생존에 기대지 않도록 바꿉니다.
3. Test(관측 동작): 위 경우마다 정해진 시간 안에 server, socket, Board 디렉터리가 사라지는지 확인합니다. 이 test 자체도 남기지 않습니다.
4. README의 규칙 문장을 실제 보장에 맞게 고칩니다.

위험 등급: 중간(모든 도구 test가 쓰는 공통 helper).

## Verification
- 공통 helper(`tools/tests/*`)를 바꾸므로 README 검증 표의 "여러 도구가 함께 쓰는 test helper" 행인 다섯 명령 모두와 `(cd tools/project-board/rust && cargo test --offline --locked)`를 제출 commit에서 실행합니다.
- 문서: 고친 문서의 상대 link 검사, `python -m pytest -q tools/test_distribution_boundary.py`.
- 실행 전후로 이 계정의 test tmux server(`/tmp/tmux-<uid>/` 아래와 `TMPDIR/pt-*` 아래 socket)가 늘지 않았는지 Result에 적습니다.
