# BOARD-011: 통합 파일 밖의 제품 run-shell(agent-session의 pane-died hook, Board popup)도 실패하면 작업 pane에 결과가 보입니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S3
- Base: 8d070b2be0c5a8a5c396c8c63713d8e044569dc7 2026-11-10T00:57:30+09:00

## Symptom
BOARD-010은 tmux 통합 파일의 `run-shell` 작업을 모두 `project_agent_run.sh`로 감싸 작업 pane에 출력·종료 상태가 보이지 않게 했습니다. 같은 원인의 `run-shell`이 통합 파일 밖의 제품 코드에 두 곳 남아 있습니다. 실패하면 활성 작업 pane에 `'…' returned N`이 view-mode로 보일 수 있습니다.

## Evidence
- BOARD-010 Result(2026-11-10) 범위 밖 관찰: `tools/agent-session/agent_session/tmux.py`의 `install_exit_hook`(`pane-died[agent-session]`)은 shell 쪽에서 `>/dev/null 2>&1`만 하고 종료 상태를 버리지 않음. `tools/project-board/project_board/tmux_control.py`의 Board popup은 `display-popup -E`를 `run-shell -b`로 실행.
- 계약 5.3절의 `run-shell` 규칙 표(BOARD-010)는 새 `run-shell`이 세 방식 중 하나를 고르도록 정함.

## Contract
- Board·agent-session이 사용자 tmux server에 남기는 `run-shell` 작업은 사용자의 작업 pane에 출력·종료 상태를 남기지 않습니다(계약 5.3절 규칙).

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). BOARD-006·010과 같은 원인의 결함이며 근거가 있으므로 위임 범위입니다. 이 CR로 이 결함 종류를 제품 전체에서 닫습니다.
- 2026-11-10 Leader: 제출 e9ec0bc211837a6f65bfa42e35210065e21ec209를 인수합니다. Leader review: 제품의 run-shell 작성 지점 세 곳(pane-died[agent-session] hook, stop·restart controller(본문에 없던 지점, 같은 결함 종류라 범위 안), Board popup)이 모두 quiet_shell을 거치는 것을 확인했습니다. controller에서 exec를 뺀 것은 결과 파일 계약을 바꾸지 않고, agent_session에 controller의 process 계보를 가정하는 코드가 없음도 확인했습니다. 규칙의 구현이 project_agent_run.sh(통합 파일)와 quiet_shell(도구) 둘인 것은 원격 bundle과 원격 host의 hook이 script를 가질 수 없기 때문이며, 규칙의 원본은 계약 5.3절 한 곳이고 option 이름은 test가 두 구현을 맞춥니다(인정). pane-died hook의 view-mode는 재현되지 않았다는 정직한 기록과 실패 기록 개선을 인정합니다. ast로 tools/**·integrations/**의 모든 run-shell을 검사하는 test, controller·popup 형태의 수정 전 재현, README 표의 네 행(agent-session 787+기존 실패 1(TEST-007), project-board 154, 네 번째 명령 103, install 261+2 skipped) 확인.

## Implementation
1. 두 곳을 계약 5.3절 규칙에 맞춥니다: agent-session의 `pane-died[agent-session]`(자동 이벤트 → `hook` 방식), Board popup(사람이 연 것 → 실패를 작업 pane을 덮지 않고 알림). 통합 파일의 `project_agent_run.sh`를 쓸 수 없는 경로(원격 bundle, 통합 파일이 없는 tree)면 같은 규칙을 그 도구 안에서 지킵니다.
2. 제품 코드 전체(`tools/**`, `integrations/**`)에서 `run-shell`을 만드는 곳을 찾아 모두 규칙을 따르는지 검사하는 test를 둡니다(BOARD-010의 통합 파일 검사를 제품 코드로 넓힘).

의존: 선행 BOARD-010(done).

위험 등급: 낮음.

## Verification
README 검증 표의 `tools/agent-session/**`(전체)·`tools/project-board/**`·`integrations/tmux/**` 행.
1. 수정 전: 실패하는 가짜 명령으로 두 경로를 실행하면 활성 pane이 view-mode.
2. 수정 뒤: 활성 pane에 아무것도 남지 않고 규칙대로 기록·알림.
3. 제품 코드의 모든 `run-shell`을 검사하는 test 통과.

## Result

- 제출 commit: e9ec0bc211837a6f65bfa42e35210065e21ec209

Base(8d070b2) 위의 한 commit입니다. `origin/main`이 진행하지 않아 merge는 없습니다. `origin/cr/BOARD-011`에 push했습니다.

1. `run-shell` 작성 지점 목록(제품 코드 `tools/**`·`integrations/**`, test 제외)
   - 통합 파일: BOARD-010에서 끝남(검사 test가 계속 확인).
   - `agent_session/tmux.py`: `install_exit_hook`(`pane-died[agent-session]`), `run_controller`(stop·restart 예약). 조사 중 발견한 것으로 CR 본문에 없던 세 번째 지점입니다. 같은 결함 종류이고 Leader 판정의 "이 결함 종류를 제품 전체에서 닫습니다" 범위로 보아 함께 고쳤습니다.
   - `project_board/tmux_control.py`: `_popup`(Board popup).
2. 고침: `agent_session.tmux.quiet_shell`(job 출력 폐기, 종료 코드 0, 실패는 `@project_agent_last_error`에 `<날짜> <시각> <이름> failed (exit N)` 한 줄, 사람이 연 작업은 그 client에 5초 `display-message`)과 `Tmux.run_quiet`. 세 지점이 이를 씁니다. 통합 파일의 `project_agent_run.sh`를 쓰지 않은 이유: 원격 bundle(zip은 `*.py`만 실음)과 원격 host의 tmux hook이 그 script를 갖지 못합니다. 규칙의 원본은 계약 5.3절이고 option 이름은 test가 두 구현을 맞춥니다. `controller.sh`·원격 zip 배치·hook의 인자 순서·CLI·JSON은 불변입니다.
   - hook: 옛 `exec env … >/dev/null 2>&1`(종료 상태를 버리지 않음) → `quiet_shell` 안에서 실행(`exec` 제거). 이름 붙은 hook의 tmux 따옴표 제약(`'` 금지, 두 번 parse)에 맞춰 `$?` 대신 `set -- $?`·`$*`를 씁니다.
   - controller: `cd <base> && exec bash controller.sh` → `quiet_shell` 안의 `cd <base> && bash controller.sh`. 결과 파일 계약은 그대로입니다.
   - Board popup: 실패하면 기록하고, 연 client에만 알림. 작업 pane을 덮지 않습니다.
3. 문서: 설치 계약 5.3절의 `run-shell`·hook·option 행과 규칙 문단(도구 부분과 test 이름 추가), 동작 명세 3절의 hook 문장.

검증(격리 tmux 3.8, `PATH`에 사내 tmux):
1. 수정 전(재현): 실패하는 job을 bare `run-shell -b`로 실행하면 활성 pane이 view-mode(`test_the_check_sees_what_a_bare_run_shell_does_to_the_work_pane`, `test_a_failing_popup_never_covers_the_work_pane_and_the_client_is_told[True]`)입니다. 이는 controller와 Board popup 형태이며 둘 다 재현했습니다. **`pane-died` hook은 재현하지 못했습니다.** 옛 hook text(`exec … returned 7`)를 client를 붙인 server에서 실행해도 작업 pane은 view-mode가 되지 않았습니다(hook은 client 없는 queue item이라 출력할 곳이 없음). 이 hook의 실제 이득은 실패 기록과 규칙 일치입니다(고치기 전에는 실패가 흔적 없이 사라짐).
2. 수정 뒤: 활성 pane의 `pane_mode`가 비고 `capture-pane -M`이 비며, option에 `… fake-job failed (exit 3)`·`… board-popup failed (exit 3)`·`… finish-ended failed (exit 7)`(interpreter가 실패하는 실제 hook)이 기록됩니다. 성공한 job은 기록하지 않고, popup 실패는 client 알림 호출(stub tmux로 확인)과 함께 갑니다.
3. 제품 전체 검사: `integrations/tmux/test_project_agent_conf.py::test_every_run_shell_the_product_makes_leaves_nothing_in_the_work_pane`(ast로 `tools/**`·`integrations/**`의 모든 `run-shell` 작성 지점이 `quiet_shell`을 쓰는지)와 `…::test_the_error_record_of_the_tools_is_the_option_the_integration_writes`. `_popup`을 bare `run-shell`로 되돌리면 이 검사가 `tmux_control.py:553: _popup() writes a run-shell without quiet_shell`로 실패함을 확인했습니다.

README 검증 표 실행(제출 commit 기준 작업 트리):
- `python -m pytest -q -n 8 tools/agent-session/tests`: 787 passed, **1 failed** — `test_control_queue.py::test_external_control_cannot_overtake_a_pending_self_request`(`AttributeError: 'Tmux' object has no attribute 'require_version'`, 그 test의 가짜 `Tmux`에 `require_version`이 없음). 이 변경과 무관합니다. Base(8d070b2)의 `git archive`에서도 같은 test가 같게 실패함을 확인했습니다(`1 failed, 3 passed`). 별도 CR 후보입니다.
- `python -m pytest -q tools/project-board/tests`: 154 passed.
- `python -m pytest -q integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py`: 103 passed.
- `python -m pytest -q -n 8 install/tests`: 261 passed, 2 skipped.
- 근거 재사용: `origin/main` merge가 없어 재실행 판정 없음.
