# BOARD-010: 통합 파일의 다른 run-shell(toggle 키, 창 이동 hook)도 실패하면 사용자 작업 pane에 오류를 띄웁니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Base: 3581f1fc9fad89cb02768dfab072e6de4597d52a 2026-11-10T00:34:22+09:00

## Symptom
tmux `run-shell`은 실행한 명령의 출력과 0이 아닌 종료 상태를 그때의 활성 pane에 view-mode로 보입니다. BOARD-006은 Board click 경로만 고쳤습니다. 통합 파일의 다른 `run-shell`(prefix Board 키 toggle, status line toggle, 창 이동·client 이벤트 hook의 `sync`·visibility script)도 실패하면 사용자의 작업 pane에 오류가 덮입니다. hook은 창을 옮길 때마다 돌기 때문에 실패가 반복되면 작업 pane을 계속 가립니다.

## Evidence
- BOARD-006 Result(2026-11-10, `docs/cr/done/BOARD-006-sidebar-click-pane.md`) "범위 밖 관찰": prefix `B`·status line의 `Board` toggle 등 다른 `run-shell` binding도 실패하면 같은 방식으로 활성 pane에 출력될 수 있음.
- `integrations/tmux/project-agent-main.conf`의 hook과 `project_agent_bind.sh`의 binding이 `run-shell -b`로 helper를 부름.

## Contract
- Board 통합은 사용자의 작업 pane에 출력·입력을 남기지 않아야 합니다(BOARD-006 Contract와 같은 원칙). 사용자가 직접 누른 동작(toggle)이 실패하면 사용자가 알 수 있어야 하지만, 작업 pane을 가리지 않는 방식이어야 합니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). BOARD-006과 같은 원인의 결함이며 근거가 있으므로 위임 범위입니다.
- 2026-11-10 Leader: 제출 72af2aae47868d76b67fd667b2107e08a90d441b를 인수합니다. Leader review: run-shell shell 작업 14개 목록(사람이 누른 것·자동 hook, -C 제외 근거), project_agent_run.sh(hook은 출력 없이 @project_agent_last_error 한 줄, key는 display-message, drop은 click), 계약 5.3절 규칙 표 한 곳, 모든 run-shell이 규칙을 따르는지 통합 파일 text와 server 양쪽에서 검사하는 test를 확인했습니다. 수정 전 실패 재현, 네 번째 명령 101·test_tmux_control 17·install 261 passed. 범위 밖 관찰(agent-session의 pane-died hook, Board popup의 run-shell)은 BOARD-011로 엽니다.

## Implementation
읽을 문서: [설치 계약](../../project-team/install-contract.md) 3.1·5.3절, `integrations/tmux/project-agent.conf`·`project-agent-main.conf`·`project_agent_bind.sh`, BOARD-006 Result, [README 검증 표](../../../README.md#검증).

1. 통합 파일과 helper가 `run-shell`로 부르는 명령을 모두 나열하고, 사람이 누른 것(toggle)과 자동 이벤트(hook)로 나눕니다.
2. 자동 이벤트: 출력과 종료 상태를 활성 pane에 보이지 않습니다. 실패는 사용자가 나중에 볼 수 있는 한 곳(예: Board의 오류 표시 또는 정해진 log 파일)에 남깁니다. 위치를 계약 5.3절에 적습니다.
3. 사람이 누른 것: 실패하면 작업 pane을 덮지 않는 방식(예: `display-message`)으로 짧게 알립니다.
4. 규칙을 계약 3.1절 또는 5.3절에 한 번 적고, 새 `run-shell`을 더할 때 따르게 합니다(test로 확인: 모든 `run-shell`이 규칙대로인지).

의존: 선행 BOARD-006(done).

위험 등급: 낮음.

## Verification
README 검증 표의 `integrations/tmux/**` 행.
1. 재현(수정 전): 실패하는 가짜 helper로 toggle과 hook을 실행하면 활성 pane이 view-mode가 됨.
2. 수정 뒤: hook 실패는 활성 pane에 아무것도 남기지 않고 정해진 곳에 기록됨, toggle 실패는 `display-message`로만 알림.
3. 통합 파일의 모든 `run-shell`이 규칙을 따르는지 검사하는 test.

## Result

- 제출 commit: 72af2aae47868d76b67fd667b2107e08a90d441b

수정 commit 46a8aac에 `origin/main`(fec7391)을 merge한 것이 제출입니다. `origin/cr/BOARD-010`에 push했습니다.

1. `run-shell` 목록(통합 파일 `integrations/tmux/`, `-C` 제외 shell 작업 14개)
   - 사람이 누른 것: prefix Board 키 toggle(`project_agent_bind.sh`), 통합 파일을 읽을 때의 `project_agent_bind.sh` 실행(`project-agent-main.conf`). 정상 실패인 Board pane click은 BOARD-006에서 이미 조용함.
   - 자동 이벤트: hook 6개(`client-attached`·`client-detached`·`client-session-changed`·`session-window-changed`·`window-created`·`window-closed`)의 `project_board_visibility.sh`와 `sync` 각 1개(12개).
   - `run-shell -C`(`after-resize-pane`, `pane-died`의 tmux 명령 4개)는 shell 작업이 아니라 pane에 안 보임: 격리 server에서 실패하는 `-C`(없는 pane `kill-pane`)가 `pane_mode` 빈 값, 버퍼 빈 값임을 확인함. 규칙 대상에서 제외.
   - status line의 `Board` toggle: 통합 파일에 없음(사용자 tmux 설정이 소유, 계약 5.3절). 계약에 같은 방식으로 감쌀 수 있다고 적음.
2. 고침: 새 `integrations/tmux/project_agent_run.sh <hook|key|drop> <socket> <명령…>`. 출력 없이 종료 코드 0. `hook`은 실패를 server option `@project_agent_last_error`에 한 줄(날짜 시각 명령 failed (exit N): 출력 첫 줄)로 남김(다음 실패가 덮어쓰므로 파일·증가 없음, 5.1절의 HOME 쓰기 목록 불변). `key`는 같은 기록과 붙은 모든 client에 `display-message` 5초. `drop`은 click용(BOARD-006의 `>/dev/null 2>&1; true`를 대체, 동작 동일). 통합 파일의 hook·binding·`project_agent_bind.sh` 실행을 모두 이 script로 감쌈. CLI·JSON·socket 계약 불변.
3. 규칙은 계약 5.3절 `run-shell` 규칙 표 한 곳(방식 3개, 새 `run-shell`은 이 중 하나를 고름)과 binding·hook·option 행에 적음. `docs/project-team/README.md`의 파일 목록·6항에 새 script 반영.
4. test(`integrations/tmux/test_project_agent_conf.py`): `test_every_run_shell_job_goes_through_the_run_script`(통합 파일 text와 읽힌 server의 binding·hook 모두), `test_a_failing_hook_job_leaves_nothing_in_the_active_pane_and_is_recorded`, `test_a_failing_board_key_tells_the_user_without_covering_a_pane`, run script 단위 3개(출력 없음·종료 0, 잘못된 호출 거절, drop은 기록 없음·hook은 첫 줄 기록). BOARD-006 click test의 pty 부분은 공용 helper(`attached`)로 옮김(동작 동일).

검증:
1. 재현(수정 전): Base 3581f1f의 파일에 새 test를 적용(scratch 사본) → hook test와 key test가 `assert 'view-mode' == ''`로 실패(실패하는 가짜 Board로 `window-created`의 sync와 prefix `B` toggle 실행, pty client attach), 규칙 test도 `project-agent-main.conf:11` 위반으로 실패. 수정 뒤 모두 통과: 활성 pane `pane_mode` 빈 값·mode buffer 빈 값, hook은 `@project_agent_last_error`가 `… tmux_project_board.sh failed (exit 1): Board cannot reach its session`, toggle은 client 화면에 `project-agent: tmux_project_board.sh failed (exit 1): Board cannot…`(80열에서 잘림, 전체는 option에 있음).
2. README 검증 표 `integrations/tmux/**` 행(수정 commit 46a8aac): 네 번째 명령(`integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py`) 101 passed, `tools/project-board/tests/test_tmux_control.py` 17 passed, `install/tests` 261 passed·2 skipped. `git diff --check` 깨끗함.
3. `origin/main` merge 뒤 근거 재사용 판정: merge가 가져온 변경(`git diff 3581f1f origin/main`, 21개 파일)에 `integrations/`·`install/`·`tools/project-board/`·`tools/tests/`·`tools/python-launcher.sh`가 없어 위 검증의 입력이 바뀌지 않음. 따라서 재실행하지 않고 46a8aac의 결과를 재사용함.
- CHANGELOG는 건드리지 않음(Leader가 close 때 더함).
- 범위 밖 관찰(미수정): `tools/agent-session/agent_session/tmux.py`의 `pane-died[agent-session]` hook(`install_exit_hook`)은 shell 쪽에서 `>/dev/null 2>&1`만 하고 종료 상태는 버리지 않으므로, `finish-ended`가 0이 아닌 상태로 끝나면 BOARD-006에서 확인한 것과 같은 방식으로 활성 pane에 `returned N`이 보일 수 있음(실패하는 경우를 재현하지는 않음). `tools/project-board/project_board/tmux_control.py`의 Board popup(`display-popup -E`를 `run-shell -b`로)도 같은 경로. 둘 다 통합 파일 밖이고 agent-session·project-board의 검증 행이 달라 이 CR에서 고치지 않았음.
