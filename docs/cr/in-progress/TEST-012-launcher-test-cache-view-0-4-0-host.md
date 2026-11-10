# TEST-012: launcher test가 사용자 cache의 상태줄 view를 읽어 0.4.0 설치 host에서 실패합니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: TMUX-003, PERF-002
- Base: 341901e4fb17de913d7fa3bff394d291b3c24bc0 2026-11-10T12:03:55+09:00

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
- 2026-11-10 Leader: 제출 22da49d06e56ec4afe12a9e2c95f5cf5bced024b를 인수합니다. Leader review: launcher test와 tmux 통합 test가 자식 process에 빈 HOME·XDG_CACHE_HOME을 주고 XDG_CONFIG/DATA/STATE_HOME을 뺍니다. 그래서 사용자 상태줄의 view가 결과를 바꾸지 않습니다. 회귀 test는 두 위치에 유효한 view를 두고, 격리하지 않으면 view가 출력되는 것을 먼저 확인합니다. 같은 구멍을 test_project_agent_conf.py에서 하나 더 찾아 고쳤고, 나머지 범위는 이미 격리되어 있다는 판정을 확인했습니다. 검증은 README 표 integrations/tmux 행(네 번째 명령 127 passed, test_tmux_control.py 21 passed, install/tests 267 passed·2 skipped)입니다. 제출 이후 main은 움직이지 않았습니다.

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

## Result
- 제출 commit: 22da49d06e56ec4afe12a9e2c95f5cf5bced024b

변경(test만, 제품 코드 변경 없음):
- `tools/test_python_launcher.py`: autouse fixture `empty_user_dirs`가 test마다 빈 `HOME`·`XDG_CACHE_HOME`을 만들고, 자식 process 환경(`child_env()`와 직접 `subprocess.run` 3곳)에 넣습니다. `XDG_CONFIG_HOME`·`XDG_DATA_HOME`·`XDG_STATE_HOME`은 자식 환경에서 뺍니다. 회귀 test `test_valid_view_of_the_users_status_line_does_not_change_the_result`는 `$XDG_CACHE_HOME`과 `~/.cache`의 두 위치에 유효한 view를 두고, 격리 없이 실행하면 view가 출력됨을 먼저 확인한 뒤 `run()`이 가짜 interpreter를 실행함을 확인합니다.
- `integrations/tmux/test_project_agent_conf.py`: 같은 구멍을 찾아 함께 고쳤습니다. `test_decide_status_entry_expands_to_the_decision_script`는 tmux server가 `#()`로 `tmux_decide_status.sh`를 실행하므로 사용자의 유효한 view가 있으면 interpreter가 실행되지 않아 실패합니다. autouse fixture와 `Server.run()`의 환경으로 빈 `HOME`·`XDG_CACHE_HOME`을 주고, 그 test를 `user_view` False·True로 parametrize해 유효한 view를 둔 경우를 회귀로 둡니다.

같은 구멍 점검(범위 `integrations/tmux`, `tools/`, `install/tests`):
- `integrations/tmux/test_tmux_decide_status.py`: 이미 fixture `status`가 `HOME`·`XDG_CACHE_HOME`을 tmp로 둡니다. 변경 없음.
- `integrations/tmux/test_project_agent_conf.py`: 위 한 건이 같은 구멍이었고 수정했습니다. 나머지 test는 `tmux_decide_status.sh`를 실행하지 않습니다.
- `tools/agent-session/tests`·`tools/project-item/tests`·`tools/project-board/tests`: `HOME`을 tmp로 격리했거나(`project-item/tests/conftest.py`, `test_cli.py`, `test_remote_skills.py`) 설정 경로를 tmp로 직접 넘깁니다(`test_config.py`). `tmux_decide_status`를 실행하는 곳이 없습니다. 변경 없음.
- `install/tests`: harness가 격리 HOME을 만들고 `XDG_*`·`CLAUDE*`·`CODEX*`를 환경에서 뺍니다. 변경 없음.

검증:
1. 수정 전 재현: `XDG_CACHE_HOME`을 test가 만든 유효한 view 하나(`<만료 epoch>\nVIEWBODY`)의 디렉터리로 두고 `python -m pytest -q tools/test_python_launcher.py` → 4 failed, 42 passed(`tmux_decide_status.sh` 케이스 4건). `python -m pytest -q integrations/tmux`도 같은 cache로 1 failed(`test_decide_status_entry_expands_to_the_decision_script`), 55 passed.
2. 수정 후 같은 명령: `tools/test_python_launcher.py` 47 passed. 수정 전 코드에서 회귀 test만 되돌리면(`USER_DIRS` 주입 제거) 회귀 test를 포함해 5건이 실패함을 확인했습니다. `integrations/tmux`의 회귀 test도 주입을 제거하면 실패함을 확인했습니다. 이 host는 사용자의 view(`~/.cache/tmux-decide-status.view`)가 있어 주입 제거 시 `no-user-view` 케이스도 실패했습니다.
3. README 검증 표 실행(제출 commit에서):
   - 네 번째 명령 `python -m pytest -q integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py -rf`: 127 passed.
   - `python -m pytest -q tools/project-board/tests/test_tmux_control.py -rf`: 21 passed.
   - `python -m pytest -q -n 8 install/tests -rf`: 267 passed, 2 skipped.
4. 근거 재사용·재실행 판정: 제출 commit 뒤에 코드 변경이 없고 `origin/main`은 base(341901e)에서 진행하지 않아(merge 없음) 위 실행을 그대로 근거로 씁니다.
