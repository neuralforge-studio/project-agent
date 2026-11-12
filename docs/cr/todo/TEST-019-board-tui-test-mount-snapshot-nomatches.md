# TEST-019: Board TUI test가 화면 mount 전에 snapshot을 적용해 부하에서 NoMatches로 실패

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S3

## Symptom
2026-11-12에 TEST-016 Worker가 merge 뒤 project-board test를 다시 실행했습니다(commit 9fbd339, load 약 100). 이때 `tools/project-board/tests/test_tui.py::test_cr_window_moves_between_every_project_in_the_same_window_and_wraps`가 `NoMatches: '#cr-detail'`로 실패했고, 단독으로 다시 실행하면 통과했습니다(TEST-016 Result).

## Evidence
- 이 test는 `async with app.run_test(...)`에 들어가자마자 `await app.apply_snapshot(...)`을 부릅니다(`test_tui.py:818-819`). `apply_snapshot`은 `_show_cr`를 거쳐 `#cr-detail`을 찾습니다(`tools/project-board/project_board/tui.py:385`, `:427`, `:521`). 화면 구성(compose)의 mount가 끝나기 전에 이 호출이 먼저 실행되면 위 오류가 납니다(TEST-016 Worker의 분석).
- `test_tui.py`에는 `run_test` 바로 다음 줄에서 `apply_snapshot`을 부르는 곳이 29곳 있습니다(Leader가 grep으로 셈). 모두 같은 race에 노출됩니다.
- 제품 경로에서는 snapshot이 `on_mount`가 queue한 `refresh_items`에서 옵니다(`tui.py:246-250`, `:353-359`). 그래서 mount 전에 적용되지 않을 것으로 보이지만, 확인하지 않았습니다.

## Contract
1. Board TUI test는 화면이 준비된 뒤에만 snapshot을 적용합니다. 부하와 무관하게 결과가 같습니다.
2. "화면이 준비됨"을 기다리는 방법은 test helper 한 곳에 두고, 29곳 모두 그것을 씁니다. 고정 sleep이나 숫자 한도를 쓰지 않습니다(TEST-016의 `tools/tests/wait_limit.py`, `tools/test_wait_limits.py`).
3. 제품 경로(창 process가 snapshot을 받는 모든 경로)가 mount 전에 `apply_snapshot`에 닿을 수 있는지 확인합니다. 닿을 수 있으면 제품을 고칩니다.

## Disposition
- 2026-11-12 Leader 판정: 고칩니다. 실제로 관찰한 test 결함이고 release 검증을 깨뜨릴 수 있습니다.
  - 근본 원인: test가 화면 준비를 기다리지 않고 snapshot을 적용합니다. 그리고 그 기다림을 맡는 helper가 없어 29곳이 각자 같은 순서를 반복합니다.
  - 제품 경로도 같은 race에 닿을 수 있는지 Contract 3으로 확인합니다.
  - 다음 release를 설치한 뒤 시작합니다.
- 2026-11-12 Leader: open -> todo.

## Implementation
읽을 문서:
- [Board TUI 계획](../../project-board-tui-plan.md).
- 코드:
  - `tools/project-board/project_board/tui.py`: CR·결정 창의 `on_mount`, `refresh_items`, `apply_snapshot`, window link 요청 처리.
  - `tools/project-board/tests/test_tui.py`와 그 helper(`board_testing.py` 등).
- 절차: [project-team Worker 절](../../../skills/project-team/SKILL.md#worker).

1. 먼저 재현합니다. 부하를 걸거나 mount를 늦춰서 수정 전 실패를 얻고, 원인을 Result에 적습니다.
2. 화면 준비를 기다리는 helper 하나를 만들고(또는 이미 있는 것을 쓰고), 29곳을 모두 그것으로 바꿉니다.
3. 제품 경로를 확인합니다. window link로 받는 요청과 snapshot 적용이 mount 전에 올 수 있는지 봅니다. 올 수 있으면 제품을 고치고 test를 더합니다.

위험 등급: 낮음(주로 test. 제품을 고치면 중간).

## Verification
- README 검증 표:
  - `tools/project-board/**`: `python -m pytest -q tools/project-board/tests`, `python -m pytest -q tools/agent-session/tests/test_api_boundary.py`.
  - 공유 helper(`tools/tests/**`)를 바꾸면 pytest 명령 다섯 개를 모두 실행합니다.
- 고친 test 파일에는 네 번째 명령의 `tools/test_wait_limits.py`도 실행합니다.
- 재현 확인: 수정 전 commit에서는 실패하고 제출 commit에서는 통과하는 것을 Result에 적습니다.
