# TEST-013: release 검증의 agent-session test 3개가 높은 host 부하에서 대기 한도를 넘겨 실패합니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S3
- Base: 82fe650528592b9262d08ce94e540fcf5224eb46 2026-11-11T19:46:19+09:00
- Outcome: fixed

## Symptom
0.9.0 release 검증(2026-11-11, release commit 532faea의 clone)에서 `python -m pytest -q -n 8 tools/agent-session/tests`가 3 failed, 869 passed(44분)였습니다. 다른 줄기(project-item, project-board, 네 번째 명령, install/tests)도 같은 시간에 돌았고, host load는 92~143이었습니다.

## Evidence
- 실패한 test:
  - `test_suspend.py::test_a_failed_resume_leaves_the_record_and_start_can_take_over`: `{'leader': 'provider_exited', 'seat-0': 'timeout'}`
  - `test_watch.py::test_a_stalled_worker_with_a_background_shell_names_it_in_the_message`: `SessionError: The command's total wait limit expired.`(`lifecycle.py:65`)
  - `test_suspend.py::test_resume_lost_reopens_the_slots_that_have_no_record_in_the_same_conversations`
- 같은 clone에서 세 test만 다시 실행하면 load 143에서 3 passed(307초)입니다.
- 이전 release 검증(0.7.1, 0.8.0, 0.8.1)에서는 agent-session test가 모두 통과했습니다(846개, load 70~130).
- README: "Agent-session test는 seat 여럿이 같은 host에서 동시에 검증하는 평소 부하에서 같은 결과를 냅니다. 한도(`AGENT_SESSION_TEST_TIMEOUT`, 기본 120초)는 host가 이보다 심하게 느릴 때만 늘립니다."
- test의 fake provider(`tests/fixtures/agent_session_fake_provider.py`)는 `UserPromptSubmit` hook(TEAM-002)을 실행하지 않습니다. 그래서 TEAM-002가 원인은 아닙니다.
- 가설(미확인): 이 세 test는 run 둘(Leader, seat)을 띄우고 기다리는 시간이 길어서, release 검증처럼 두 줄기에 각각 `-n 8`이 겹치는 부하에서 한도를 넘깁니다.

## Contract
- release 검증의 다섯 명령은 이 workstation의 평소 release 조건(두 줄기 병렬, load 150 안팎)에서 같은 결과를 냅니다. 부하 때문에 실패하지 않습니다.
- test가 기다리는 결과(무엇을 판정하는지)는 바뀌지 않습니다. 한도를 늘리는 것만으로 고치면 근거(측정)를 적습니다.

## Disposition
- 2026-11-11 Leader: 고친다(Leader 판정). release 검증을 막는 test 결함입니다. 0.9.0은 실패한 세 test를 다시 실행해 통과한 근거로 release했습니다.
- 2026-11-11 Leader: open -> todo. Leader 판정: release 검증을 막는 test 결함
- 2026-11-11 Leader: 범위를 넓힙니다. 같은 0.9.0 검증에서 install/tests 4개도 설치 명령의 300초 한도를 넘겨 실패했습니다. 대상은 `test_tmux.py::test_t20_user_bindings_are_kept_and_reported_as_skipped`와 `test_tmux_version.py::test_check_passes_when_the_first_tmux_is_the_minimum_or_newer`의 3.8, next-3.9, 4.0입니다. 전체 1시간 45분이 걸렸고 load는 90~140이었습니다. 다시 실행하면 5 passed였습니다(load 40~100). 그때 seat 1 Worker가 띄운 install test 두 개가 부모 없이 2시간 넘게 돌고 있었습니다. 이 4개도 같은 기준(부하 아래 반복)으로 고칩니다. 0.9.0은 실패한 test를 다시 실행해 모두 통과한 근거로 release했습니다.
- 2026-11-11 Leader: 제출 957124086b3c94755abc16443c4ef79318e99bf2를 인수합니다. 검토 9571240(29afe08 + main 5fe6458 merge, merge는 CR 이동만). 원인 측정(start p50 24.6초·최대 80초, 두 slot resume 최대 43초인데 resume 한도 20초 고정), fixture 한도 120→240초와 git·MCP·lifecycle 한도의 fixture 한도 사용, installer 한도 300→900초, README 갱신을 읽었습니다. 판정 내용은 그대로이고 한도는 측정 최대의 3배입니다. agent-session 872 passed, install 283 passed, 세 test 부하 아래 5회 통과, Leader가 test_distribution_boundary 9 passed 확인. 제품 코드 쪽 남은 실패 후보(remote_bridge 5초 대기, resume order)는 다시 실패하면 별도 CR로 다룹니다.
- 2026-11-11 Leader: in-progress -> done, Outcome fixed. 통합 58efb42 (origin/main)

## Implementation
읽을 문서: `tools/agent-session/tests/test_suspend.py`, `test_watch.py`, `tests/conftest.py`의 `AGENT_SESSION_TEST_TIMEOUT`, `agent_session/lifecycle.py`의 wait limit, README 검증, [release 절차](../../project-team/release.md), [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 세 test가 한도를 넘기는 단계를 부하 아래에서 재현해 기록합니다. 예: 다른 줄기와 함께 `-n 8`로 실행. 원인을 Result에 적습니다.
2. 고칩니다. 예: test가 기다리는 대상을 상태 기반으로 바꾸기, 불필요한 대기 줄이기, 한도를 test 규모에 맞추기.
3. 반복 실행(부하 아래 5회)에서 실패가 없음을 보입니다.

의존: 없음.

위험 등급: 낮음. test만 바꿉니다. 제품 코드를 바꾸면 그 행의 명령도 실행합니다.

## Verification
1. `python -m pytest -q -n 8 tools/agent-session/tests`(다른 줄기와 병렬, 부하 아래)
2. 세 test의 부하 아래 반복 결과를 Result에 적습니다.

## Result
- 제출 commit: 957124086b3c94755abc16443c4ef79318e99bf2

변경은 test와 README뿐이고 제품 코드는 바꾸지 않았습니다. 시험 내용(무엇을 판정하는지)은 그대로입니다. 한도만 부하 측정에 맞췄습니다. `29afe08`이 변경이고, 제출 commit은 그 위에 `origin/main`(`5fe6458`, CR 파일 이동 두 개만 다름)을 merge한 것입니다. merge가 바꾼 검증 입력이 없어서 아래 검증을 `29afe08`의 clone에서 한 근거를 그대로 씁니다.

### 원인(측정)
실패한 세 test는 모두 fixture의 `start` 둘(Leader, Worker)과 `resume`을 연달아 실행합니다. 같은 test를 `-n 8` agent-session과 `-n 8` install을 동시에 돌린 부하(load 50~100)에서 명령별로 쟀습니다(386개 `start`).

| 명령 | p50 | p99 | 최대 |
| --- | --- | --- | --- |
| `start` | 24.6초 | 61.0초 | 80.3초 |
| 두 slot `resume`(한 한도를 나눠 씀) | | | 43초 |

- `start`의 시간은 대부분 provider 등록 대기(12~17초)와 두 번째 `start`의 seat 배정·git 준비(assignment 6~9초, git 8~12초)입니다. fixture 한도 기본 120초는 최대의 1.5배뿐이어서 0.9.0 gate(load 92~143)처럼 부하가 더 높으면 넘습니다.
- `test_a_failed_resume_leaves_the_record_and_start_can_take_over`(`{'leader': 'provider_exited', 'seat-0': 'timeout'}`)는 원인이 따로 있었습니다. 이 test와 `test_a_failed_lost_resume_keeps_its_evidence_and_start_takes_over`는 `resume`의 한도를 20초로 고정했는데, `resume`은 slot을 차례로 relaunch하며 한 한도를 나눠 씁니다. 두 slot의 resume이 12~23초(load 50~80), 최대 43초라서 둘째 slot(seat-0)이 시간 초과였습니다.
- 가설 가운데 "run 둘을 띄우고 기다리는 시간이 길다"는 확인했습니다. TEAM-002의 `UserPromptSubmit` hook은 원인이 아닙니다(fake provider가 실행하지 않음).

### 변경
- `tests/fixtures/agent_session_fixture.py`: `DEFAULT_TIMEOUT` 120초 → 240초(측정 최대 80초의 3배). 주석에 측정을 적었습니다. fixture의 `git()` 한도 15초도 `command_timeout()`으로 바꿨습니다(clone이 15초를 넘겨 `TimeoutExpired`).
- `tests/test_suspend.py`: `resume`의 20초 고정 두 곳을 fixture 한도로 바꿨습니다.
- `tests/test_lifecycle.py`: 등록 실패를 기다리는 `start`의 한도 60·120초 네 곳을 fixture 한도로 바꿨습니다. `tests/test_providers.py`: MCP client 3초 → 30초(같은 파일의 다른 test와 같은 값).
- `tests/test_fixture_timeout.py`: 기본값 단언을 240초로, 환경 변수 test의 값은 360초로 바꿨습니다.
- `install/tests/harness.py`: 설치 명령 한도 300초를 `INSTALLER_TIMEOUT = 900`으로 올렸습니다. load 55~60에서 `install` 97초, `check` 23초이고(한 test가 설치와 check를 함께 해서 115~155초) 0.9.0 gate에서 300초를 넘겼습니다. 900초는 그 300초의 3배입니다.
- `README.md`, `tools/agent-session/README.md`: 기본 한도(240초)와 측정 근거를 갱신했습니다.

### 변경 전 기준선(같은 부하, `82fe650`의 clone)
- `-n 8 tools/agent-session/tests`: 7 failed, 865 passed(48분). CR의 세 test는 이 실행에서 통과했습니다(load가 gate보다 낮았음). 실패는 `test_start_reports_a_failed_registration_before_its_timeout`(60초 한도), `test_mcp_process_scrubs_parent_markers_and_uses_current_schema`(MCP 3초), `test_a_replaced_leader_run_cannot_cross_projects`(fixture git 15초), `test_resume_reopens_the_same_conversations_leader_first`(2개), `test_dead_report_bridge_reuses_its_token_and_replaces_its_stale_socket`, `test_explicit_remote_seat_is_chosen_while_an_earlier_local_seat_is_free`입니다. 마지막은 제 측정 plugin의 오류(`_progress`가 None)였고 test 결함이 아닙니다.
- `-n 8 install/tests`: 2 failed, 281 passed(1시간 25분). 둘 다 300초 `TimeoutExpired`(`test_hardening.py`의 두 test)였습니다.

### 검증(`29afe08`의 `git clone --no-hardlinks`, 세 줄기 동시)
1. `python -m pytest -q -n 8 tools/agent-session/tests`: **872 passed**(35분 26초). 같은 시간에 install 전체와 아래 반복이 함께 돌았습니다. load는 32~143(1분 평균, 실행 중 관측)이었습니다.
2. 세 test의 반복(`-n 3`, 위 두 줄기와 동시, 5회): **5회 모두 3 passed**(130~160초). 회마다 시작 시 load 32, 57, 90, 70, 78입니다. 가장 긴 test는 81초(`test_a_failed_resume...`)였고 한도 240초의 1/3입니다.
3. `python -m pytest -q -n 8 install/tests`: **283 passed, 2 skipped**(1시간 1분 40초). 기준선 실패 2개 포함.

### 남은 문제와 가정
- load 150 안팎의 gate 조건은 이 실행에서 만나지 못했습니다(최대 관측 143, 대부분 50~100). 한도를 측정 최대의 3배로 잡았으므로 그 부하의 2배까지는 같은 결과를 기대하지만, 확인한 것은 아닙니다.
- 기준선에서 실패했지만 이 commit이 직접 고치지 않은 test가 있습니다. `test_dead_report_bridge_reuses_its_token_and_replaces_its_stale_socket`는 제품 코드(`remote_bridge.py:76`)의 5초 대기에서 실패했습니다. `test_resume_reopens_the_same_conversations_leader_first`(2개)는 resume 결과의 `order == []`로 실패했는데 원인은 확인하지 못했습니다(shutdown 쪽 한도로 의심하지만 재현하지 못했습니다). 이 세 test는 검증 실행에서 통과했습니다. 다시 실패하면 별도 CR로 다룰 만합니다.
- 두 seat의 install test가 부모 없이 돌고 있다는 Leader 기록(Disposition)은 이번 작업에서 확인하지 못했습니다. 이 Worker가 띄운 process는 전부 끝났습니다.
