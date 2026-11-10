# TEST-011: launch 기록 test가 파일이 생긴 직후 내용이 쓰이기 전에 읽어 가끔 실패합니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: TEST-009
- Base: 645e322aa2dd8b1116b70292dcbf42f458eeb27b 2026-11-10T11:14:00+09:00

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
- 2026-11-10 Leader: 제출 24ec304b5ff7b674468d6cf85a48c895ffef35a1를 인수합니다. Leader review: launch.sh가 관찰 파일을 임시 이름으로 쓴 뒤 mv하므로 exists()가 내용 완성을 뜻합니다. 수정 전에는 16개 동시 실행 중 7개가 실패했고, 수정 뒤에는 32개 실행에서 실패가 0입니다. agent-session 전체 806 passed입니다. 같은 모양이 다른 곳에 없다는 판정도 확인했습니다. 이 제출 뒤 main의 변경(v0.4.0 release commit, TEST-010의 private_root.py)은 PERF-002가 main을 merge한 commit에서 다섯 명령을 다시 실행해 함께 확인합니다.

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

## Result
- 제출 commit: 24ec304b5ff7b674468d6cf85a48c895ffef35a1

변경: `test_launch_records_attempt_before_exec_and_exit_keeps_dead_pane`(`tools/agent-session/tests/test_tmux.py`)의 `launch.sh`가 `tmux show-options`를 `attempt.txt.pending`에 쓴 뒤 `mv`로 `attempt.txt`로 바꿉니다. `observed.exists()`가 내용 완성을 보장합니다. 제품 코드는 바꾸지 않았습니다.

검증:
1. 수정 전 재현: 이 test를 16개 동시에 실행(각 실행에 다른 짧은 `TMPDIR`)했을 때 7개가 `assert '' == 'true'`로 실패했습니다.
2. 수정 뒤: 같은 방법으로 16개씩 2회(32개 실행) 모두 통과했습니다.
3. `python -m pytest -q -n 8 -rf tools/agent-session/tests`: 806 passed, 0 failed (821초).

같은 모양 점검(`agent-session/tests`의 `exists()` 대기와 shell redirection 쓰기):
- `test_tmux.py` `observation.exists`(paste_sensitive_tui 2곳): fixture가 임시 파일에 쓴 뒤 `replace`하므로 안전합니다. 수정 없음.
- `test_tmux.py` `result_path`(controller test): `exists() and bool(read_text())`로 내용을 확인하고 한 번의 write이므로 안전합니다. 수정 없음.
- `test_git_ops.py` `seen`, `test_self_ended.py` `mark`: 존재만 단정하고 내용을 읽지 않습니다. 수정 없음.
- 그 밖의 `>` redirection 쓰기는 `test_tmux.py` stub의 `>>` log 한 곳이며, 프로세스 종료 뒤에 읽습니다. 수정 없음.
- 결론: 같은 결함 모양은 이 test 한 곳뿐입니다.
