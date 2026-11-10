# TEST-011: launch 기록 test가 파일이 생긴 직후 내용이 쓰이기 전에 읽어 가끔 실패합니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: TEST-009

## Symptom
`tools/agent-session/tests/test_tmux.py::test_launch_records_attempt_before_exec_and_exit_keeps_dead_pane`이 가끔 `assert observed.read_text().strip() == "true"`(`'' == 'true'`)로 실패합니다. 실패하면 release 검증의 agent-session 전체 실행이 깨집니다.

## Evidence
- TEST-009 Result(2026-11-10, seat 1): `-n 8` 전체 실행에서 805 passed, 1 failed였고 실패한 것이 이 test입니다. 이 test만 단독으로 3번 실행하면 1번 같은 오류가 납니다.
- 원인(코드로 확인): test의 `launch.sh`는 `tmux show-options ... > observed.txt`로 실행합니다. shell은 redirection으로 파일을 먼저 만들고, tmux가 끝난 뒤에야 내용을 씁니다. test는 `wait_for(lambda: observed.exists())` 직후 내용을 읽으므로 빈 파일을 읽을 수 있습니다(`test_tmux.py` 241~255행).

## Contract
- test는 관찰하려는 쓰기가 끝난 뒤의 값을 단정합니다. 제품 코드는 바꾸지 않습니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 재현과 원인 근거가 있는 test 결함이고 release 검증을 깨뜨립니다.
- 2026-11-10 Leader: open -> todo. release 검증을 깨는 test 결함

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 관찰 파일이 완성된 뒤에만 보이게 합니다. 예: launch.sh가 임시 파일에 쓴 뒤 `mv`로 바꿉니다. 그러면 `exists()`가 내용까지 보장합니다.
2. agent-session test에서 같은 모양("shell redirection 파일의 `exists()`를 기다린 뒤 내용을 단정")을 찾아 함께 고칩니다. 찾은 곳과 판정을 Result에 적습니다.

의존: 없음.

위험 등급: 낮음.

## Verification
1. 수정 전 재현: 이 test를 반복하거나 동시에 실행해 실패를 보입니다. 동시에 실행할 때는 각 실행의 `TMPDIR`을 다르게 두고 짧은 경로를 씁니다(AF_UNIX 경로 길이).
2. 수정 뒤: 같은 방법으로 실패가 없음을 보입니다.
3. README 검증 표 `tools/agent-session/**` 행: `tools/agent-session/tests` 전체(`-n 8 -rf`).
