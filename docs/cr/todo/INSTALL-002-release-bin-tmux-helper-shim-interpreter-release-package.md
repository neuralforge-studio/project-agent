# INSTALL-002: release의 진입점(bin·tmux helper·결정 표시)이 shim 없이 설치 interpreter와 release package 경로로 실행되게 합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2

## Symptom
설치본에서 tmux가 부르는 helper는 `~/.local/bin`의 shim을 거치지 않습니다. `integrations/tmux/tmux_project_board.sh`는 release 안의 `tools/project-board/bin/project-board`를 직접 실행하고, `@project_agent_decide_status`는 `tmux_decide_status.py`(`#!/usr/bin/env python3`)를 직접 실행합니다. shim이 정하는 `PROJECT_AGENT_PYTHON`·`PROJECT_AGENT_PYTHONPATH`가 없으므로 개발 checkout 규칙(`python3` 등)으로 interpreter를 고릅니다. 새 직원 환경에서는 그 interpreter가 Python 3.10 미만이거나 `textual`이 없을 수 있어 Board와 결정 표시가 동작하지 않습니다.

## Evidence
- `integrations/tmux/tmux_project_board.sh:6`: `exec "$SCRIPT_DIR/../../tools/project-board/bin/project-board" "$@"`
- `integrations/tmux/project-agent.conf`: `@project_agent_decide_status`가 `#(…/tmux_decide_status.py)`를 부름
- `integrations/tmux/tmux_decide_status.py:1`: `#!/usr/bin/env python3`
- 설치 계약 6.1절: 환경 변수가 없으면 개발 checkout 규칙(macOS `python3`, WSL venv, 그 밖은 사내 Python, venv, `python3` 순서)
- TMUX-001 review(2026-11-09, `docs/cr/done/TMUX-001-*.md` Disposition)에서 넘긴 일입니다.

## Contract
- 설치 계약 6.1절: 설치본은 설치 때 고른 interpreter와 release 안의 package만 씁니다. 다른 interpreter로 되돌아가지 않습니다.
- 사용자 결정(agent D-20261109-08 C, -09 C): 다른 설정에 영향이 없어야 합니다. 전역 Python과 사용자 site에 기대지 않습니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 승인한 계획 agent DIST-001 4단계의 하위 결함입니다(TMUX-001 review에서 발견). 계약 6.1절이 정한 동작을 tmux helper 경로에도 지키게 하는 일이므로 위임 범위입니다. INSTALL-001에서 떼어 내 병렬로 진행합니다(사용자 지시 2026-11-09 "병렬로 진행 가능 한 것은 병렬로 진행해").

## Implementation
읽을 문서: [설치 계약](../../project-team/install-contract.md) 6.1절·3.1절·5.3절, [README의 검증](../../../README.md#검증), INSTALL-001의 Implementation 2단계(interface).

1. `tools/python-launcher.sh`가 `PROJECT_AGENT_PYTHON`·`PROJECT_AGENT_PYTHONPATH` 환경 변수가 없을 때, 자기와 같은 디렉터리의 `python.env`를 읽어 두 값을 정합니다. 형식은 INSTALL-001과 맞춘 것입니다: 한 줄에 `NAME=값` 하나, 이름은 두 변수만, 값은 따옴표 없이 줄 끝까지. 파일을 shell로 `source`하지 않고 이 두 이름만 읽습니다. 환경 변수가 있으면 환경 변수가 이깁니다. 파일이 없으면(개발 checkout) 지금 규칙 그대로입니다.
2. `python.env`의 interpreter가 없거나 실행할 수 없으면 6.1절의 기존 오류(`python_unavailable`, 종료 코드 5)와 같게 끝납니다. 다른 interpreter로 되돌아가지 않습니다.
3. 결정 대기 표시: `@project_agent_decide_status`가 `tmux_decide_status.py`를 launcher와 같은 interpreter 규칙으로 실행하게 합니다. 예: `integrations/tmux/`에 launcher를 `source`하는 작은 sh wrapper를 두고 option이 그것을 부릅니다. 표시 결과(출력 형식)는 바꾸지 않습니다.
4. `tmux_project_board.sh`는 release의 `bin/project-board`를 부르므로 1단계로 해결됩니다. 이를 test로 확인합니다.
5. 계약 6.1절에 `python.env`의 위치·형식·우선순위를 적습니다. 5.3절의 `@project_agent_decide_status` 행을 새 호출 방식에 맞춥니다.
6. `.gitignore`가 없으므로, 개발 checkout에 `tools/python.env`가 실수로 commit되지 않게 하는 방법(예: root `.gitignore`에 한 줄)을 둡니다.

범위 밖: `python.env`를 쓰는 설치기(INSTALL-001), 외부 package(INSTALL-003은 D-20261109-01로 waived. release에 package를 넣지 않으므로 `PROJECT_AGENT_PYTHONPATH`는 빈 값입니다).

의존: 선행 없음(REPO-001·TMUX-001 done). 병렬 INSTALL-001. 후행 RELEASE-002.

위험 등급: 중간. 세 CLI 모두의 interpreter 선택 경로를 바꿉니다. 이 workstation의 실제 CLI는 agent 저장소의 동결 사본이므로 지금 운영에는 영향이 없습니다.

## Verification
1. 재현(수정 전 실패): 가짜 release 배치(임시 디렉터리에 `tools/`·`integrations/` 복사)에서 shim 환경 변수 없이, `PATH`의 `python3`를 Python 3.10 미만을 흉내 내는 가짜로 둡니다. 이때 `tools/project-board/bin/project-board --help`와 결정 표시 실행이 설치 interpreter를 쓰지 않음을 기록합니다.
2. 수정 뒤 자동 test(`tools/test_python_launcher.py` 또는 새 test):
   - `python.env`만 있을 때 세 진입점이 그 interpreter와 package 경로로 실행됩니다(`PYTHONPATH`·`PYTHONNOUSERSITE` 확인은 기존 test 방식).
   - 환경 변수가 있으면 파일보다 우선합니다.
   - 파일의 interpreter가 없으면 종료 코드 5와 기존 오류 형식입니다.
   - 파일에 다른 이름이나 shell 문법(예: `$(…)`)이 있어도 실행되지 않습니다.
   - 파일이 없으면 기존 개발 checkout test가 그대로 통과합니다.
   - 격리 tmux server에서 가짜 release의 `project-agent.conf`를 읽고 `#{E:@project_agent_decide_status}`를 펼치면, 결정 표시 script가 `python.env`의 interpreter로 실행됩니다.
3. 영향 회귀: README의 네 명령이 통과합니다(알려진 timing test 2개는 단독 실행 통과 확인).
