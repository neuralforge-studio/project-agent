# BOARD-008: sidebar에 Leader·Worker session이 동작한 시간(??d ??h ??m)을 보입니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3
- Base: f3182143ab5b3c436d1c2f975c28fe784e4eadb9 2026-11-10T00:03:56+09:00
- Outcome: fixed

## Symptom
사용자 요청: "Leader/Worker의 Session 동작 중인 시간에 대한 표시가 필요한 ??d ??h ??m"
출처: 사용자 개선 요청 2026-11-09(대화, 11개 항목 중 6번).

## Evidence
- state의 session마다 `connected_at`(처음 게시한 UTC 시각)이 있습니다([명세 3절](../../project-team/spec.md#3-statejson)).

## Contract
- 표시 형식은 사용자가 정한 `??d ??h ??m`입니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 사용자가 표시 형식까지 정한 기능 요청이므로 위임 범위입니다. BOARD-002 뒤에 시작합니다. 사용자 지시(2026-11-09 대화): "위와 같이 11개의 개선 요청 사항이 있어."
- 2026-11-10 Leader: 선행 BOARD-002가 61e881e로 통합되었습니다(BOARD-003·004 병합). 그 구조를 따르십시오: Board pane은 본 window에 남고(최대 8개, 최근 본 순서), 보이지 않는 pane은 갱신하지 않으며(`project_board_visibility.sh`의 SIGUSR1), 파일은 바뀐 것만 다시 읽습니다(TUI 계획 2·5절). Board CR 다섯 개가 같은 `tui.py`·`tmux_control.py`를 고칠 수 있으므로 제출 전에 `origin/main`을 merge하십시오.
- 2026-11-10 Leader: 제출 7457bc4d0bda162e5a27a18d2f7a4b989e25e0a1를 인수합니다. Leader review: TUI 계획 3절의 규칙(분 단위 내림, 0인 앞자리 생략, session·connected_at 없으면 표시 안 함), Worker 행의 시간과 펼친 project 첫 줄의 Leader 줄, 분이 바뀔 때만 다시 그림을 확인했습니다. 경계 test와 export_screenshot 렌더 확인, project-board 146 passed. merge는 docs/cr만이라 근거 재사용.
- 2026-11-10 Leader: in-progress -> done, Outcome fixed. 통합 8315909(Merge cr/BOARD-008, 제출 7457bc4). origin/main 반영 확인. CHANGELOG Unreleased에 더했습니다.

## Implementation
읽을 문서: [project-board README](../../../tools/project-board/README.md), [TUI 계획](../../project-board-tui-plan.md), [설치 계약 5.3·5.4절](../../project-team/install-contract.md), [README 검증 표](../../../README.md#검증).

1. sidebar의 Leader와 각 Worker seat 줄에 그 session이 게시된 뒤 지난 시간을 `??d ??h ??m`으로 보입니다. 기준은 state의 `connected_at`입니다. 0인 앞자리 단위는 생략합니다(예: `3h 05m`, `12m`, `2d 01h 00m`). session이 없으면 표시하지 않습니다.
2. 갱신 주기는 sidebar의 기존 갱신과 같게 하고, 분이 바뀔 때만 다시 그려 깜빡임을 만들지 않습니다.
3. `connected_at`이 없는 이전 state(명세 3절)는 표시하지 않습니다.
4. 표시 규칙을 [TUI 계획](../../project-board-tui-plan.md)에 먼저 적습니다.

의존: 선행 BOARD-002.

## Verification
1. 경계 test: 0분, 59분, 1시간, 23시간 59분, 1일, 여러 날, `connected_at` 없음.
2. 화면 capture에서 Leader·Worker 줄에 시간이 보임.
3. README 검증 표의 `tools/project-board/**` 행.

## Result
- 제출 commit: 7457bc4d0bda162e5a27a18d2f7a4b989e25e0a1

구현 commit은 `f291588`이고, 그 위에 `origin/main`(문서 `docs/cr`만 바뀜)을 merge한 것이 제출 commit입니다. 코드는 merge로 바뀌지 않았습니다.

변경:
- [TUI 계획](../../project-board-tui-plan.md) 3절에 표시 규칙을 먼저 적었습니다(분 단위 내림, 0인 앞자리 생략, session·`connected_at` 없으면 표시 안 함).
- `tui.py`: `format_elapsed`(`0m`, `12m`, `3h 05m`, `2d 01h 00m`)를 두고 Worker seat 행 끝에 붙입니다. model의 `elapsed`(`connected_at` 기준, snapshot마다 계산)를 그대로 씁니다.
- Leader는 sidebar에 줄이 없었으므로, 펼친 project의 첫 줄에 `Leader <시간>`을 더했습니다. Leader session이 없거나 `connected_at`이 없으면 줄을 두지 않습니다. 좌석을 접으면 Leader 줄도 접힙니다. 클릭 동작은 없습니다.
- 갱신 주기는 기존 snapshot(2초)이고, 화면 signature에 표시 문자열을 넣어 분이 바뀔 때만 다시 그립니다.

검증:
- `python -m pytest -q tools/project-board/tests -n 8` → 146 passed (f291588에서 실행).
- 경계: 0초·59초→`0m`, 60초→`1m`, 59분, 1시간, 23시간 59분, 1일, 2일 1시간, 12일, 음수, `None`(`test_elapsed_time_drops_zero_leading_units`); 시간 없는 seat 행; `connected_at` 없는 Leader·Worker와 session 없는 seat(`test_sidebar_shows_no_time_for_old_state_...`).
- 화면 capture: `test_sidebar_shows_leader_and_worker_time_...`가 `export_screenshot` 렌더에서 `Leader 1d 01h 30m`과 `CPU-012 2h 30m`을 확인하고, 같은 분 안의 재수신은 widget을 다시 만들지 않으며 다음 분에 둘 다 바뀌는 것을 확인합니다.
- 기존 두 test(`R 0 CPU-012`, `0 AG-001`)는 이제 시간이 붙으므로 snapshot `now`를 고정해 기대값을 갱신했습니다.
- Merge 뒤 재실행: 하지 않음. merge로 들어온 변경은 `docs/cr` 파일뿐이라 검증 입력이 달라지지 않았습니다.
