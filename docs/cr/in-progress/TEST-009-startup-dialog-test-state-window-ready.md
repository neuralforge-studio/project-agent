# TEST-009: startup dialog test가 state 게시와 window ready 사이를 기다리지 않아 부하에서 실패합니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: SESSION-010
- Base: d66c2615f3aff4f6f161d1491949c2e2ec745777 2026-11-10T10:48:14+09:00

## Symptom
`tools/agent-session/tests/test_lifecycle.py::test_start_held_at_a_startup_dialog_needs_the_user_and_resumes[leader|worker]`가 부하 아래에서 `assert env.tmux.get_current("fixture", slot).get("ready") is True`(327행)로 실패합니다. v0.4.0 후보(SESSION-010·TMUX-003 통합, 802bb93)의 release 검증에서 agent-session 전체(`-n 8`)를 두 번 실행해 두 번 모두 두 parametrize가 실패했습니다(2 failed, 804 passed). 이 실패로 release를 내지 못합니다.

## Evidence
- Leader 진단(2026-11-10, 802bb93의 복제본, host load 45~80). test를 고쳐 state 게시 직후의 window 값과, 그 뒤 `ready`가 될 때까지 걸린 시간을 기록했습니다. 기록 파일은 `/primehome/swain/tmp/claude-1028/-primehome-swain-Utils-project-agent-project-agent-base/9882d26b-f3ea-4f92-80e6-97dea7945eb0/scratchpad/rel040/diag-test009.log`입니다.
  - 단독 실행 1번, 동시 6개 실행 1번에서 실패가 2번 났습니다. 두 번 모두 state가 게시된 순간 window는 `registered=False publishing=True`였고, `ready`는 0.07초 뒤 True가 되었습니다.
  - 통과한 실행에서도 `ready`까지 0.05~0.14초가 걸렸습니다. 끝내 `ready`가 되지 않은 경우는 없습니다.
- 제품 순서: `state.py` `publish_session`은 window의 `publishing` 기록 → state 쓰기(commit) → window `registered`·`ready` 순서입니다(docstring이 계약). state가 게시된 뒤 window가 갱신되기 전의 짧은 구간은 설계상 존재하고, `complete_publication`과 `start`의 `registered and not ready` 분기가 이 구간을 다룹니다.
- test는 state 게시만 기다린 뒤 window의 `ready`를 바로 읽습니다. SESSION-010 전에는 `get_current`가 tmux를 6번 안팎 불러 느렸고, 그동안 hook이 window 갱신을 끝내 경합이 드러나지 않았습니다. SESSION-010으로 읽기가 2번으로 줄어 이 구간에 걸립니다. SESSION-010 Worker도 전체 실행 1번에서 같은 실패를 보았습니다(SESSION-010 Result).

## Contract
- test는 제품 계약이 보장하는 것만 단정합니다. 계약은 "state commit 뒤 window가 registered·ready가 된다"이지, "state를 읽은 순간 window가 ready다"가 아닙니다.
- 제품 코드와 게시 순서는 바꾸지 않습니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 재현과 원인 근거가 있는 test 결함이고, v0.4.0 release 검증을 막습니다(사용자 승인: 2026-11-10 "지금 0.4.0 설치").
- 2026-11-10 Leader: open -> todo. release를 막는 test 결함
- 2026-11-10 Leader: 제출 f0f4cb774d1795eadfbb58a76cd13b107e834109를 인수합니다. Leader review: state 게시와 window ready를 함께 기다리도록 바꿨습니다. 이것이 publish_session의 계약(state commit 뒤 window 갱신)과 맞는 단정입니다. 수정 전 18실행 중 8 실패가 수정 뒤 24실행 0 실패가 되었습니다. 같은 모양의 다른 test가 없다는 판정 근거도 인정합니다. README 표 tools/agent-session/** 행 전체 실행 결과는 805 passed, 1 failed입니다. 실패한 test_tmux.py의 launch 기록 test는 이 변경과 무관한 다른 경합입니다(파일이 생긴 뒤 내용이 쓰이기 전에 읽음). TEST-011로 엽니다. 제출 이후 main의 변경(d417943: tools/tests/perf, README)은 agent-session test의 입력이 아니어서 다시 실행하지 않습니다.

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), [동작 명세](../../project-team/spec.md)의 게시 순서(`state.py` `publish_session` docstring), [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 이 test가 state 게시 직후 window `ready`를 바로 단정하지 않게 합니다. state 게시와 window `ready`를 함께 기다립니다(같은 파일의 `wait_until`).
2. 같은 파일과 agent-session test 전체에서 "state를 읽은 뒤 window의 registered·ready를 기다리지 않고 바로 단정하는" 같은 모양의 test를 찾아 함께 고칩니다. 찾은 곳과 판정을 Result에 적습니다.
3. 제품 코드는 바꾸지 않습니다.

의존: 없음.

위험 등급: 낮음.

## Verification
1. 수정 전 재현: 이 test를 동시에 여러 개(예: 6개) 실행해 실패가 나는 것을 보입니다. 이때 TEST-010의 prune 경합과 구분되도록 각 실행의 `TMPDIR`을 다르게 둡니다.
2. 수정 뒤: 같은 방법으로 반복(최소 3회 × 6개)해 실패가 없음을 보입니다.
3. README 검증 표 `tools/agent-session/**` 행: `tools/agent-session/tests` 전체(`-n 8`). 실패한 test 이름이 보이도록 `-rf`를 붙입니다.

## Result
- 제출 commit: f0f4cb774d1795eadfbb58a76cd13b107e834109

### 변경
- `tools/agent-session/tests/test_lifecycle.py` `test_start_held_at_a_startup_dialog_needs_the_user_and_resumes`: state 게시만 기다린 뒤 window `ready`를 바로 단정하던 두 행을, state 게시와 window `ready`를 함께 `wait_until`로 기다리는 한 행으로 바꿨습니다. 제품 코드는 바꾸지 않았습니다(test 파일 2 insertions, 2 deletions).

### 같은 모양 test 탐색 (Implementation 2)
agent-session test 전체에서 `ready`·`registered`를 단정하거나 기다리는 곳을 모두 보았습니다. 같은 모양(state를 읽은 뒤 window registered·ready를 기다리지 않고 단정)은 위 test 한 곳뿐입니다.
- `test_lifecycle.py` 358행(codex trust dialog): `registered`를 `wait_until`로 기다립니다. `_finished`가 registered·ready를 한 번의 `write_meta`로 쓰므로 충분합니다. 고치지 않습니다.
- `test_lifecycle.py` `published_leader`(446·467행): state와 window의 `ready`·`registered`를 함께 `wait_until`에서 평가합니다. 고치지 않습니다.
- `test_lifecycle.py` 233·335·580·684·792 등 `result["ready"]`: `start()`·`resume()`의 반환값이며 두 API가 window ready를 기다린 뒤 돌려줍니다. 고치지 않습니다.
- `test_lifecycle.py` 1127행: `start()` 반환 뒤 이미 ready인 worker를 읽습니다. 고치지 않습니다.
- `test_internal.py` 131·145행: `internal._register`·`register_from_hook`를 같은 thread에서 동기 호출한 뒤 읽습니다. 고치지 않습니다.
- `test_suspend.py` 442·561행: `fleet.resume()`이 `relaunch`→`_launch`로 ready를 기다린 뒤 돌려준 다음에 읽습니다. 고치지 않습니다.
- `test_remote*.py`·`test_tmux.py`·`test_background.py`: fake meta나 `write_meta`를 직접 쓴 값을 읽는 test이며 비동기 게시와 무관합니다.

### 검증
- 수정 전 재현: 이 test(두 parametrize)를 6개 동시에, 각 실행마다 `TMPDIR`을 달리해 3회(18개 실행) 돌렸습니다. 8개 실행이 실패했고(leader 3·worker 5) 실패 지점은 모두 `assert env.tmux.get_current(...).get("ready") is True`(`ready`가 False)입니다. host load 약 35~70.
- 수정 뒤: 같은 방법으로 4회 × 6개(24개 실행, 최소 요구 3회) 모두 `2 passed`, 실패 0.
- `TMPDIR=<짧은 경로> python -m pytest -q -n 8 -rf tools/agent-session/tests` → 805 passed, 1 failed (526초, load 약 35~50).
  - 실패 1: `test_tmux.py::test_launch_records_attempt_before_exec_and_exit_keeps_dead_pane`. 이 CR과 무관한 기존 경합입니다. test의 launch.sh가 `tmux show-options ... > observed.txt`로 파일을 먼저 만든 뒤 값을 쓰는데, test는 `wait_for(observed.exists())` 직후 내용을 읽어 `'' == 'true'`로 실패합니다(255행). 이 test만 단독으로 3번 돌렸을 때 1번 같은 오류가 났습니다. 변경한 파일과 무관하고 다른 모양의 경합이라 이 CR에서 고치지 않았습니다. `exists()` 대신 파일 내용이 비어 있지 않을 때까지 기다리게 하는 한 줄 수정이 후보입니다. 별도 CR 여부는 Leader가 판정해 주십시오.
  - 처음 실행은 `TMPDIR`을 긴 scratchpad 경로로 두어 `test_websocket.py` 9개가 `AF_UNIX path too long`으로 실패했습니다. 환경 탓이며 짧은 `TMPDIR`로 다시 실행해 통과했습니다(위 결과).
- 근거 재사용: `origin/main` merge는 하지 않았습니다(base d66c261 그대로).
