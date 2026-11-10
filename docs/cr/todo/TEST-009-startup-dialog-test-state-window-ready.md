# TEST-009: startup dialog test가 state 게시와 window ready 사이를 기다리지 않아 부하에서 실패합니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: SESSION-010

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
