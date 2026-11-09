# INSTALL-002: release의 진입점(bin·tmux helper·결정 표시)이 shim 없이 설치 interpreter와 release package 경로로 실행되게 합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Base: 9458aba01535c1a12ee034ce725048aca5448c10 2026-11-09T14:40:54+09:00

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

## Result
- 제출 commit: 5c41f2d9bc416f73ed747e9f847789753619fa71

변경(Base 9458aba 위 1 commit, `origin/cr/INSTALL-002`에 push):
- `tools/python-launcher.sh`: 환경 변수에 값이 없는 `PROJECT_AGENT_PYTHON`·`PROJECT_AGENT_PYTHONPATH`를 같은 디렉터리의 `python.env`에서 읽습니다. 두 이름의 줄만 `case`로 읽고 `source`하지 않습니다. 환경 변수(빈 값은 없는 것으로 봄)가 파일보다 우선하며 변수마다 따로 판단합니다. 파일이 없으면 기존 개발 checkout 규칙 그대로입니다. interpreter가 없으면 기존 `python_unavailable`·종료 코드 5입니다.
- `integrations/tmux/tmux_decide_status.sh`(신규): launcher로 interpreter를 골라 `PYTHONNOUSERSITE=1`로 `tmux_decide_status.py`를 실행합니다. 실패하면 stderr 한 줄과 종료 코드 5입니다. `project-agent.conf`의 `@project_agent_decide_status`가 이 wrapper를 부릅니다. 표시 형식은 그대로입니다.
- `tmux_project_board.sh`는 코드를 바꾸지 않았습니다. release의 `bin/project-board`가 launcher를 쓰므로 1단계로 해결되며 test로 확인했습니다.
- 계약 6.1절(`python.env`의 위치·형식·우선순위·오류), 5.3절의 결정 표시 설명과 5.1절의 cache 행, 9절 표를 고쳤습니다. `docs/project-team/README.md`의 진입점·tmux 연결 행도 맞췄습니다.
- root `.gitignore`(신규)에 `tools/python.env` 한 줄을 두었습니다.

검증:
1. 재현(수정 전): 가짜 release(`tools/`·`integrations/` 복사, `tools/python.env`가 설치 interpreter를 지정, PATH의 `python3`는 가짜)에서 shim 환경 변수 없이 실행했습니다. `project-board --help`는 workstation 사내 Python으로 실제 실행됐고, `tmux_decide_status.py`는 PATH의 가짜 `python3`로 실행됐습니다. 둘 다 `python.env`의 interpreter를 쓰지 않았습니다. 수정 뒤 같은 배치에서 `project-board`·`project-item`·`agent-session`·결정 표시가 모두 설치 interpreter로 실행되고, 환경 변수가 파일보다 우선하며, 없는 interpreter는 종료 코드 5였습니다.
2. 자동 test(`tools/test_python_launcher.py` 27개, `integrations/tmux/test_project_agent_conf.py`):
   - `python.env`만 있을 때 세 CLI와 `tmux_project_board.sh`·`tmux_decide_status.sh`가 그 interpreter·package 경로로 실행되고 `PYTHONNOUSERSITE=1`입니다(`agent-session`은 기존대로 설정하지 않음). 공백이 있는 interpreter 경로도 통과합니다.
   - 환경 변수가 파일보다 우선합니다. 파일의 interpreter가 없으면 다섯 진입점 모두 종료 코드 5와 기존 오류 형식입니다.
   - 다른 이름·`$(…)`·백틱 줄은 실행되지 않고, 값의 `$(…)`도 글자 그대로입니다. 파일에 다른 이름만 있으면 그 값을 interpreter로 쓰지 않습니다.
   - 파일이 없을 때는 기존 `test_development_checkout_runs_without_installer_values`가 그대로 통과합니다.
   - 격리 tmux server에서 가짜 release의 `project-agent.conf`를 읽고 `#{E:@project_agent_decide_status}`를 펼치면 `python.env`의 interpreter가 `tmux_decide_status.py`를 실행합니다. conf를 옛 호출(`.py` 직접)로 되돌리면 이 test가 실패함을 확인했고 복원했습니다.
3. 영향 회귀(README의 네 명령, 제출 commit):
   - `integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py`: 68 passed.
   - `tools/project-item/tests`: 120 passed.
   - `tools/agent-session/tests`: `-n 4`로 704 passed. 첫 실행(`-n 8`)은 695 passed·9 failed였는데, 부하 때문인 timing 실패입니다. `test_suspend.py`·`test_lifecycle.py`를 `-n 2`로 다시 돌리면 1개(`test_the_most_recent_runs_window_is_the_one_a_slot_takes`)만 실패했고, 그 test는 단독 실행에서 변경본과 base 모두 통과했습니다. 마지막으로 `-n 4` 전체 실행이 모두 통과했습니다.
   - `tools/project-board/tests`: 113 passed·1 failed(`test_tui.py::test_popup_renders_markdown_and_csv_and_closes_editor_after_acceptance`). 이 CR의 변경과 무관한 기존 실패입니다. base(`git archive 9458aba`)에서도 단독 실행으로 같은 test가 실패합니다. 알려진 timing test 2개와는 다른 test입니다.
4. 근거 재사용·재실행: 변경은 launcher·tmux helper와 문서뿐이므로 `agent-session`·`project-item`·`project-board`의 Python 코드는 바뀌지 않았습니다. 위 회귀는 그 범위의 영향 확인입니다. merge는 없었습니다(`origin/main`이 진행하지 않음).

알려 둘 점:
- 계약 6.1절에 "변수마다 따로 판단"을 적었습니다(CR 문구의 "환경 변수가 있으면 환경 변수가 이긴다"의 해석). 예: 환경에 `PROJECT_AGENT_PYTHON`만 있고 `PROJECT_AGENT_PYTHONPATH`가 없으면 후자는 파일에서 읽습니다.
- 같은 이름이 여러 번 나오면 마지막 줄이 이긴다는 규칙을 계약에 적었습니다(CR이 정하지 않은 부분입니다. INSTALL-001이 이 형식으로 쓰므로 중복은 없을 것입니다).
- `__pycache__`가 untracked로 보입니다. `.gitignore`에는 CR이 요구한 한 줄만 두었습니다.
