# TEST-016: test가 성공을 기다리는 한도를 숫자로 직접 줘서 부하에서 release 검증이 실패합니다

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S2
- Base: f73658f7306315c99ee4b248bb3bd8416574546c 2026-11-12T16:31:00+09:00
- Outcome: fixed

## Symptom
2026-11-12 0.11.1 release 검증(clone, release commit 136a489)에서 agent-session test 1건이 실패해 release가 멈췄습니다.
- `test_lifecycle.py::test_claude_restart_replaces_a_leader_whose_cli_is_gone_whatever_its_last_stop_report_listed[fixture-cron-leader]`: `SessionError: The command's total wait limit expired.`(`_wait_ready`의 `remaining`). 결과는 1 failed, 933 passed였고 host load는 80~90이었습니다.
- 이 test는 SESSION-017이 더했습니다. 성공을 기대하는 restart(새 run 시작 포함)에 `env.manager(timeout=20)`을 줍니다.

## Evidence
- 기다림 한도의 원본은 `tools/agent-session/tests/fixtures/agent_session_fixture.py`의 `command_timeout()`입니다(`DEFAULT_TIMEOUT` 240초, `AGENT_SESSION_TEST_TIMEOUT`이 덮어씀). TEST-003·TEST-013이 측정한 근거가 주석에 있습니다. 부하에서 `start` 하나가 최대 80.3초였습니다. `env.manager()`는 인자가 없으면 이 값을 씁니다.
- 숫자를 직접 준 곳: `env.manager(timeout=N)` 17곳(`test_caller.py` 180초 4곳, `test_lifecycle.py` 2·3·5·20·30초), test 안의 `time.monotonic() + N` 기다림 10곳(예: `end_cli_on_its_own`의 10초).
  - 일부는 한도 자체를 확인하는 test입니다(`test_fixture_timeout.py`, 일부러 짧은 한도로 `timeout`을 기대하는 test).
  - 나머지는 성공을 기대하면서 원본보다 짧은 한도를 줘서, 부하에 따라 실패합니다. 20초를 준 4곳 중 2곳은 SESSION-009, 2곳은 SESSION-017에서 생겼습니다.
- [README 검증](../../../README.md#검증): "Agent-session test는 seat 여럿이 같은 host에서 동시에 검증하는 평소 부하에서 같은 결과를 냅니다. 한도(`AGENT_SESSION_TEST_TIMEOUT`, 기본 240초)는 host가 이보다 심하게 느릴 때만 늘립니다." 숫자를 직접 준 test는 이 한도를 따르지 않으므로, `AGENT_SESSION_TEST_TIMEOUT`을 늘려도 고쳐지지 않습니다.
- 같은 날 TEAM-003 검증(`-n 8` agent-session, 전체 49분)에서도 5건이 load로 실패했고, 직렬 재실행에서 통과했습니다. SESSION-017 restart test 2건(`timeout=20`), `test_git_ops.py::test_timed_out_git_releases_its_lock_and_reports_the_interruption`(git `timeout=2`), `test_tmux.py::test_exit_refuses_tmux_mode_and_preserves_partial_input[False-copy-mode]`(client `wait(timeout=10)`), `test_remote.py::test_dead_report_bridge_reuses_its_token_and_replaces_its_stale_socket`(원인 미확인)입니다. 일부러 짧은 한도를 주는 test도 부하에 흔들리지 않아야 합니다(Contract 2).

## Contract
1. 성공을 기대하는 기다림은 모두 기다림 한도의 원본 하나(`command_timeout()` 또는 그 원본에서 나온 값)를 따릅니다. test가 숫자를 따로 갖지 않습니다.
2. 일부러 짧은 한도를 주는 test(한도에 걸리는 동작을 확인)는 그 이유를 test에 적고, 원본과 무관하게 짧아도 결과가 부하에 흔들리지 않게 합니다(예: 끝나지 않는 동작에만 짧은 한도를 줌).
3. 새 test가 숫자 한도로 성공을 기다리면 드러나게 합니다. 방법은 Worker가 정합니다.
4. agent-session 밖의 test(project-board, project-item, install, integrations)에 같은 모양이 있으면 같은 원칙으로 다룹니다. 각 도구 test의 독립 실행은 유지합니다.

## Disposition
- 2026-11-12 Leader 판정: 구현한다. 재현 근거가 있는 결함이고 release 검증을 막았습니다(0.11.1 검증 중단).
  - 판단 기준은 사용자 지시 "판단의 주요관점은 ** Root cause & SSOT **"입니다. 실패한 한 test만 늘리지 않습니다. 기다림 한도의 원본(TEST-013의 `command_timeout()`)을 따르지 않는 모든 곳을 같은 원칙으로 고칩니다.
  - 0.11.1 단독 release는 접었습니다. 다음 release는 이 CR을 통합한 뒤 검증합니다. seat가 비면 BOARD-028보다 먼저 시작합니다.
- 2026-11-12 Leader: open -> todo.
- 2026-11-12 Leader 검토(제출 67487e4504c9): 수정 요청 1건입니다. 지금 `origin/main`(BOARD-028 포함)과 합친 tree에서 `tools/test_wait_limits.py`가 2 failed입니다.
  - 걸린 곳: `test_sidebar_release.py`의 `timeout=10` 6곳, `test_tmux_control.py:1477`의 `time.monotonic() + 20`.
  - 요청: merge하고 이 7곳을 같은 원칙으로 고칩니다. 나머지(원본, 변환, 이유 표기, 가드, `expire_when_ready`, 검증)는 인수할 수 있습니다.
  - `test_tui` 마운트 race는 별도 CR로 열고, `install/tests/test_tmux.py`의 `no server running` 관찰은 TEST-017로 넘깁니다.
- 2026-11-13 Leader: 제출 717cbba5a080c95f1bdc232b12fa5bdfec21f6d8를 인수합니다. 7곳 수정 확인(성공 기다림만 command_timeout()으로, 부정 단언 없음). Leader가 origin/main과 합친 tree에서 test_wait_limits·distribution boundary 127 passed
- 2026-11-13 Leader: in-progress -> done, Outcome fixed. 통합 2c8216a (origin/main)

## Implementation
읽을 문서:
- [README 검증](../../../README.md#검증)의 agent-session 한도 문장.
- `tools/agent-session/tests/fixtures/agent_session_fixture.py`의 `command_timeout()`과 주석(TEST-003·TEST-013 측정).
- [TEST-013 CR](../done/TEST-013-release-agent-session-test-3-host.md), [SESSION-017 CR](../done/SESSION-017-leader-run-self-restart-cli-finish-lock-timeout-agent.md)(실패한 test를 더함).
- 절차: [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 다섯 검증 명령의 test에서 숫자로 준 기다림 한도를 모두 찾아 목록을 Result에 적습니다. 각각을 "성공을 기다림"과 "한도에 걸림을 확인"으로 나눕니다.
2. 성공을 기다리는 곳은 원본을 따르게 합니다. 한도를 확인하는 곳은 이유를 적고, 부하에 흔들리지 않는 모양으로 둡니다.
3. 새 test가 숫자 한도로 성공을 기다리면 드러나는 장치를 둡니다.
4. 부하에서 확인합니다. 실패했던 test를 다른 `-n 8` suite와 동시에 여러 번 돌려 통과하는지 봅니다.

위험 등급: 낮음~중간(test만 바뀜. 공통 helper를 바꾸면 다섯 명령에 영향).

## Verification
- README 검증 표에서 바꾼 경로의 행 명령을 모두 제출 commit에서 실행합니다. `tools/agent-session/tests`만 바꾸면 `python -m pytest -q -n 8 tools/agent-session/tests`입니다. 다른 도구의 test나 공통 helper(`tools/conftest.py`, `tools/tests/*`, fixture)를 바꾸면 그 행의 명령, 공통 helper면 다섯 명령 모두와 `cargo test`입니다.
- 부하 확인 결과(동시 실행한 suite, host load, 반복 횟수, 결과)를 Result에 적습니다.

## Result
- 제출 commit: 717cbba5a080c95f1bdc232b12fa5bdfec21f6d8

`origin/cr/TEST-016`에 push했습니다. Base f73658f 뒤 `origin/main`(TEST-015·TMUX-004·SESSION-018, db563b9)을 merge했습니다(충돌은 README 두 곳, 양쪽 내용 유지). 코드는 test와 test helper만 바뀌었고 제품 코드는 그대로입니다.

### 원인과 변경
- 원인: `command_timeout()`(240초)을 따르지 않고 test가 숫자(20·30초, `deadline = now + 10` 등)를 직접 줘서 `AGENT_SESSION_TEST_TIMEOUT`을 늘려도 고쳐지지 않았습니다. 다섯 명령 전체에 같은 모양이 남아 있었습니다.
- 원본: `tools/tests/wait_limit.py`(새 파일)의 `command_timeout()`입니다. 값(240)·측정 근거 주석·env는 fixture에서 옮겼습니다. `agent_session_fixture`가 다시 내보내 기존 import는 그대로이고, 모든 도구의 test가 같은 모듈을 `tools/tests`(공유 helper 위치)에서 가져와 각 도구 test의 독립 실행은 유지됩니다.
- 성공을 기다리는 곳(가드를 처음 돌렸을 때 195곳 중 아래 한도 확인·값 비교를 뺀 나머지)은 숫자를 지우고 `command_timeout()`을 씁니다.
  - `env.manager(timeout=N)`·`fleet(env, timeout=N)` 인자, `time.monotonic() + N`, `subprocess.run/wait/communicate/join/settimeout`의 숫자, helper 기본값(`wait_until(limit=15)`, `finished(limit=30)`, `_wait`·`wait_text`·`wait_gone`·`wait_for`의 `timeout=10.0`/`seconds=`), 자식 script 안의 `Manager(timeout=300/60)`(인자로 전달), `range(50/100)` polling 반복.
  - `INSTALLER_TIMEOUT`(900)은 `4 * command_timeout()`, cargo build(1800)는 `2 * INSTALLER_TIMEOUT`으로 원본에서 파생합니다.
- 한도에 걸림을 확인하는 곳(`# short limit: <이유>`로 같은 줄에 이유를 적음): 모두 "끝나지 않는 동작에만 짧은 한도"입니다.
  - `test_lifecycle` 5곳(stop이 끝나지 않는 busy·background·view-mode 대상), `test_suspend` 11곳(busy 대상이 쉬지 않아 한도에서 force/보고), `test_state` 2곳(lock을 끝까지 쥠), `test_providers`(응답 없는 MCP).
- 값을 그대로 넘겨 비교하는 숫자(`# not a wait: <이유>`): `test_provider_codex` 2곳(원격 호출이 받을 값), `test_fixture_timeout`, `test_lifecycle` 파일 mtime, `test_project_agent_conf`의 cache 만료 시각, `test_git_ops`의 오류 보고 값 2곳.
- 부하에 흔들리던 모양을 고친 곳:
  - `test_git_ops` git timeout test 2건: 한도가 고정 시각에 끝나 hook·trap이 뜨기 전에 만료될 수 있었습니다. `expire_when_ready`가 자식이 준비된 뒤에만 한도를 만료시킵니다(`timeout=2`는 오류가 보고하는 값으로만 남음, fake git의 `sleep 3`은 끝나지 않는 loop로).
  - 리더가 알려 준 `test_tmux_control::test_moving_or_resizing_the_board_window_never_changes_the_saved_sidebar_width`: helper subprocess 한도(5초)는 위 변환에 포함됩니다. 드래그 뒤 고정 `sleep(0.5)`는 변화가 반영될 때까지 `eventually()`로 기다린 뒤 단언하는 모양으로 바꿨습니다. 같은 파일의 나머지 고정 sleep 5곳과 `test_sidebar_binary`의 것은 "일어나지 않음"을 보는 부정 단언이라 부하로 실패할 수 없어 그대로 뒀습니다.
- 장치(Contract 3): `tools/test_wait_limits.py`(네 번째 명령)가 다섯 명령의 test 파일을 AST로 읽어 `timeout=`·`limit=`·`seconds=` 숫자 인자, 시계에 더한 숫자, `.wait/.join/.communicate/.settimeout`의 숫자, 시계를 읽는 polling 함수의 숫자 기본값을 이유 없이 두면 실패합니다. merge로 들어온 새 test(TEST-015·TMUX-004·SESSION-018)의 숫자 7곳을 이 장치가 바로 잡아 고쳤습니다. 제품 형태를 흉내 낸 fake의 기본값(`verify_binding(..., timeout=30)`)은 시계를 읽지 않으므로 대상이 아닙니다.
- 문서: README 검증(마지막 bullet, 네 번째 명령에 `tools/test_wait_limits.py` 추가), `tools/agent-session/README.md`.

### 숫자 한도 목록(1단계)
변경 전 숫자 한도가 있던 곳은 `tools/test_wait_limits.py`가 규칙으로 보여 줍니다(이유 없는 숫자는 실패). 위의 "이유를 적고 남긴 곳"이 한도 확인이고, 나머지는 모두 성공을 기다리는 곳이라 원본으로 바꿨습니다. 파일별 변경은 `git diff f73658f 6b19a00 --stat`(merge 전 test 변경 48개 파일)으로 봅니다.

### 검증
제출 commit 67487e4(또는 merge 직후 9fbd339에서 실행한 것을 근거로 재사용)에서 실행했고 host load는 50~190이었습니다.

| 명령 | 결과 |
| --- | --- |
| `python -m pytest -q -n 8 tools/agent-session/tests` | 969 passed (merge 뒤 9fbd339, 40분49초). merge 전 6b19a00에서도 937 passed (39분13초, load 109~190, 아래 다른 suite와 동시) |
| `python -m pytest -q tools/project-item/tests` | 147 passed (6b19a00). merge가 이 도구 입력을 바꾸지 않아 재사용 |
| `python -m pytest -q tools/project-board/tests` | 460 passed (6b19a00, `-n 4`, 1시간16분). merge 뒤 `test_tmux_record.py`·`test_tmux_control.py`·`test_tui.py`를 9fbd339에서 다시: 163 passed, 1 failed(아래), `test_tmux_control.py` 전체는 67487e4에서 159 passed(가드 포함) |
| 네 번째 명령(`tools/test_real_crontab.py`, `tools/test_wait_limits.py` 포함) | 272 passed (9fbd339) |
| `python -m pytest -q -n 8 install/tests` | 318 passed, 2 skipped (9fbd339, 1시간21분). merge 전 6b19a00 316 passed, 2 skipped |
| `cargo test --offline --locked` | 83 passed (6b19a00). merge가 Rust를 바꾸지 않아 재사용 |

- 실패 1건: `test_tui.py::test_cr_window_moves_between_every_project_in_the_same_window_and_wraps`가 9fbd339 재실행(load 약 100)에서 `NoMatches: '#cr-detail'`로 실패했고, 단독 재실행은 통과했습니다. `run_test` 직후 마운트 전에 `apply_snapshot`을 부르는 race(`tui.py` `_show_cr`)로 기다림 한도와 무관하고, 이 CR은 그 test를 바꾸지 않았습니다. 같은 모양이 `test_tui.py`에 29곳 있습니다. 이 CR에서는 고치지 않았고 Leader가 별도 CR로 판정해 주십시오.
- 부하 확인(실패했던 test를 다른 suite와 동시에 반복): 위 suite들이 같은 host에서 도는 동안 실행했습니다.
  - SESSION-017 restart test 2건(`claude_restart_replaces_a_leader_whose_cli_is_gone…[fixture-cron-leader/background-leader]`)과 `claude_stop_ends…` 3건, git timeout 2건(`timed_out_git…`, `ignores_sigterm…`): 5회 모두 6 passed (load 104~153).
  - `test_tmux.py::test_exit_refuses_tmux_mode_and_preserves_partial_input[False-copy-mode]` 외 포함 5건, `test_remote.py::test_dead_report_bridge_reuses_its_token_and_replaces_its_stale_socket`: 5회 모두 5 passed (load 107~164).
  - 리더가 알려 준 `test_moving_or_resizing_…[window/behind]`: 3회 모두 2 passed (load 51~76).
- 중간 관찰(미확인): 변환 도중 한 fork가 install batch를 `-n 8`로 다른 큰 suite와 돌렸을 때 `install/tests/test_tmux.py` 5건이 `tmux: no server running`으로 실패했습니다(`TimeoutExpired` 아님, 단독은 통과). 제출 commit의 전체 install 실행(6b19a00·9fbd339)에서는 재현되지 않았고 원인은 확인하지 못했습니다.
- 근거 재사용·재실행 판정: merge가 입력을 바꾼 test 파일과 merge가 넣은 새 test(숫자 7곳)는 9fbd339에서 다시 실행했고, 입력이 같은 project-item·cargo는 6b19a00의 결과를 재사용했습니다. 67487e4는 `test_tmux_control.py` 한 파일만 바꿔 그 파일 전체와 가드 test만 다시 실행했습니다.

### 수정 제출(Leader 검토 요청 1건)
- 요청: 제출 뒤 `origin/main`에 들어온 BOARD-028(`f0d0726`)의 새 test에 숫자 한도 7곳이 있어 가드가 실패합니다.
- 조치: `origin/main`을 `cr/TEST-016`에 merge(충돌 없음)하고 7곳을 같은 원칙으로 고쳤습니다(717cbba). `test_sidebar_release.py`의 `timeout=10` 6곳(`_wait`·`wait_text`·`wait_gone`의 인자를 지움, 이 helper는 이미 `command_timeout()`을 씀), `test_tmux_control.py:1477`의 `time.monotonic() + 20`. 가드 scan은 0건입니다.
- 재실행(merge가 입력을 바꾼 것만, 717cbba, load 50~120대):
  - project-board `test_sidebar_release.py`·`test_rust_release.py`·`test_tmux_control.py`·`test_rust_window_notify.py`·`test_sidebar_binary.py`: 161 passed (`-n 4`, 1시간10분).
  - 네 번째 명령 전체(`test_wait_limits.py`와 release 파일 검사 포함): 274 passed.
  - install `test_install.py`·`test_rust_build.py`(BOARD-028과 TEST-016이 겹친 두 파일): 115 passed, 1 skipped.
- 재사용: agent-session 969(9fbd339)·project-item 147·cargo 83은 이번 merge가 그 입력(agent-session test·project-item·Rust 소스 중 TEST-016이 바꾼 것)을 바꾸지 않아 이전 근거를 씁니다. Rust 소스(BOARD-028)는 이 CR이 바꾸지 않았고 `cargo test`는 이 CR의 변경 범위 밖이라 다시 실행하지 않았습니다.
