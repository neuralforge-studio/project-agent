# TEST-012: launcher test가 사용자 cache의 상태줄 view를 읽어 0.4.0 설치 host에서 실패합니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: TMUX-003, PERF-002

## Symptom
v0.4.0을 설치하고 상태줄에 결정 표시를 넣은 workstation에서는 README 검증의 네 번째 명령이 `tools/test_python_launcher.py`의 `tmux_decide_status.sh` 케이스 4건으로 실패합니다. 실행 시점에 사용자 상태줄이 갱신한 `~/.cache/tmux-decide-status.view`가 유효하면 실패합니다. release 검증이 실행하는 host와 시각에 따라 결과가 달라집니다.

## Evidence
- PERF-002 Result(2026-11-10, seat 3, merge commit 944ab5b):
  - 네 번째 명령의 첫 실행이 125건 중 4 failed였습니다.
  - `XDG_CACHE_HOME`을 빈 디렉터리로 격리하면 125 passed입니다.
  - `origin/main` 4de08e8에서도 같은 4건이 실패합니다.
  - v0.4.0 설치 전에 돌린 release 검증(ce52466, 11:17)에서는 유효한 view가 없어 통과했습니다.
- 원인(코드로 확인): TMUX-003이 `tmux_decide_status.sh` 맨 앞에 view 파일 읽기를 추가했습니다(`${XDG_CACHE_HOME:-$HOME/.cache}/tmux-decide-status.view`). view가 유효하면 interpreter를 실행하지 않습니다. 그런데 `test_python_launcher.py`의 `run()`은 `PROJECT_AGENT_*`·`PYTHONPATH`만 빼고 `HOME`·`XDG_CACHE_HOME`을 그대로 넘깁니다. 그래서 test가 사용자의 실제 cache를 읽고, 가짜 python이 실행되지 않아 `ARGV1=`·exit 5·`LD=` 기대가 어긋납니다.

## Contract
- test는 사용자 계정의 cache·설정을 읽지도 쓰지도 않습니다(README 검증의 test 자원 규칙). 사용자 상태줄이 동작하는 host에서도 결과가 같습니다.
- 제품 코드는 바꾸지 않습니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 재현과 원인 근거가 있는 test 결함입니다. v0.4.0을 설치한 host에서 release 검증이 깨집니다.
- 2026-11-10 Leader: open -> todo. 0.4.0 설치 host에서 release 검증을 깨는 test 결함

## Implementation
읽을 문서: [README 검증](../../../README.md#검증)(test 자원 규칙), [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. `tools/test_python_launcher.py`의 실행 helper가 `HOME`·`XDG_CACHE_HOME`을 test 임시 디렉터리로 둡니다.
2. 같은 구멍을 찾아 함께 고칩니다. 대상은 `tmux_decide_status.sh`·`.py`, 또는 사용자 cache·설정(`~/.cache`, `~/.config`, `~/.claude*`, `~/.codex`)을 읽는 진입점을 실행하는 test입니다. 범위는 `integrations/tmux`, `tools/`, `install/tests`이며, 찾은 곳과 판정을 Result에 적습니다.
3. 회귀 test를 둡니다. 유효한 view 파일이 있는 HOME에서 실행해도 결과가 같아야 합니다.

의존: 없음.

위험 등급: 낮음.

## Verification
1. 수정 전 재현: 유효한 view 파일을 둔 cache(사용자 cache를 쓰지 않고 test가 만든 것)로 실패 4건을 보입니다.
2. README 검증 표에서 바꾼 경로의 행을 실행합니다(`-rf`). `tools/test_python_launcher.py`는 `tools/python-launcher.sh` 행의 명령(네 번째 명령, `install/tests`)으로 실행합니다. `integrations/tmux/**`를 바꾸면 그 행도 실행합니다.
