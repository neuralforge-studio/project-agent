# TEST-008: test_self_ended의 live process group test가 seat3 환경에서 항상 control_active로 실패하고 base에서는 통과합니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2

## Symptom
`tools/agent-session/tests/test_self_ended.py::test_a_claude_cli_that_still_has_a_live_process_group_is_not_confirmed`가 실행 환경에 따라 결과가 다릅니다. seat3 Worker 환경에서는 `{'reason': 'control_active'} != {'reason': 'termination_unconfirmed'}`(`test_self_ended.py:225`)로 실패합니다. 같은 commit을 base의 Leader 환경에서 실행하면 통과합니다. release 검증(다섯 명령)이 실행 환경에 따라 다른 결과를 냅니다.

## Evidence
- BOARD-009 Result(2026-11-10, seat3 run 970adc82): merge commit 5cff69c에서 agent-session 전체 790 passed·1 failed. 같은 test를 단독으로 3번 실행해 3번 모두 실패했습니다. `origin/main` bb0e0e2를 `git archive`로 푼 사본에서도 같은 오류가 납니다.
- Leader(2026-11-10, base, bb0e0e2): `python3 -m pytest -q tools/agent-session/tests/test_self_ended.py -k live_process_group` → 1 passed(11.9초).
- TEST-007 Result(seat0, 0530de3 = bb0e0e2의 제품·test와 같음): agent-session 전체 790 passed, 실패 0.
- `control_active`는 `Manager.finish_ended`(`lifecycle.py` 922-927행 부근)가 `stopping`·`control_pending` 또는 살아 있는 `controller_pid`를 볼 때 돌려줍니다. 이 test는 실제 격리 tmux에서 CLI를 죽이므로 server의 `pane-died[agent-session]` hook(별도 interpreter, monkeypatch가 닿지 않음)도 같은 run의 `finish_ended`를 실행합니다. 이 hook과 test의 직접 호출이 경합하는지는 아직 확인하지 않았습니다(가설).
- 환경 비교(2026-11-10): seat3 Worker의 환경 변수는 `/primehome/swain/tmp/claude-1028/-primehome-swain-Utils-project-agent-project-agent-base/9882d26b-f3ea-4f92-80e6-97dea7945eb0/scratchpad/seat3-env.txt`, Leader 것은 같은 디렉터리의 `leader-env.txt`입니다(secret 값은 이름만). 변수 이름의 차이는 Leader에만 있는 `PYTHONNOUSERSITE`와 `TMUX_PLUGIN_MANAGER_PATH`입니다. Leader run은 agent 저장소의 동결 사본으로, seat3 run은 설치본 0.1.0으로 시작했습니다. 두 환경 모두 `AGENT_SESSION_SOCKET`·`TMUX`가 실제 server `/tmp/tmux-1028/default`를 가리킵니다. test가 이 값을 물려받는지도 확인 대상입니다.

## Contract
- README 검증: test는 seat 여럿이 같은 host에서 동시에 검증하는 평소 부하에서 같은 결과를 냅니다. 실행하는 seat·환경 변수·경로에 따라 결과가 달라지지 않습니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 재현 근거가 있는 결함입니다(seat3에서 3/3 실패, base에서 통과). v0.2.0 release 검증의 전제입니다.

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), [동작 명세 3절 스스로 끝난 run의 마무리](../../project-team/spec.md#스스로-끝난-run의-마무리), [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. seat3에서 실패하고 base에서 통과하는 차이를 관찰로 확정합니다. 후보는 다음과 같습니다.
   - 환경 변수(`TMUX`·`TMUX_PANE`·`AGENT_SESSION_*`·`CLAUDE_*`·`PYTHONPATH`·`PATH`의 tmux)
   - 작업 경로
   - hook과 직접 호출의 경합 시간
   어느 쪽이 `control_active`를 만드는지 증거로 확인합니다.
2. 원인이 test의 격리 부족이면 test가 실행 환경을 물려받지 않게 합니다. 원인이 제품의 경합이면 제품을 고칩니다. 예를 들어 hook의 마무리와 다른 마무리가 겹쳐도 결과가 정해져야 합니다. 제품을 고치면 명세를 함께 고칩니다.
3. 같은 원인을 공유하는 다른 test가 있으면 함께 고칩니다.

의존: 없음.

위험 등급: 중간(제품 경합이면 self-ended 마무리 경로).

## Verification
1. 수정 전: seat 환경에서 그 test가 실패하는 재현과 원인 증거.
2. 수정 뒤: 같은 환경에서 반복(최소 5회) 통과.
3. README 검증 표의 `tools/agent-session/**` 행(`tools/agent-session/tests` 전체, `-n 8`). 제품의 `api.py`·state 형식·tmux option 이름을 바꾸면 그 행의 나머지 명령도 실행합니다.
