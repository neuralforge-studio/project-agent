# BOARD-013: Board TUI pane 하나가 16×16에서 아무 일 없이 1분에 CPU 25~32초(코어의 40~53%)를 씁니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: PERF-001, SESSION-010, BOARD-012

## Symptom
Project Board TUI pane 하나가 아무 조작 없이 떠 있기만 해도 16 project × seat 16 규모에서 1분에 CPU 25~32초를 씁니다. 이는 코어 하나의 40~53%입니다. v0.4.0의 Board liveness 개선(tmux 호출 3번) 뒤에도 남았습니다. 사용자는 Board를 늘 켜 두므로 이 비용이 host load에 계속 더해집니다.

## Evidence
- PERF-001 Result "측정 결과 B"의 steady 16×16입니다(2026-11-10, `tools/tests/perf`, 격리 tmux, Board TUI가 ready를 표시한 뒤 60초, client 1개, status-interval 1초).
  - Board pane 1개: v0.3.0 46.9 CPU초, v0.4.0 32.0 CPU초
  - Board pane 4개(보이는 pane 1개): 95.7 대 25.1 CPU초
  - Board pane의 tmux 호출은 v0.4.0에서 초당 1.3번입니다.
- 4×4는 v0.4.0 5.99 CPU초, 8×8은 9.95 CPU초입니다. 규모에 따라 늘어납니다.
- `tools/project-board/project_board/tui.py`의 주기는 snapshot 2초, liveness 10초, context 10초입니다.
- 원인은 아직 나누지 않았습니다. 후보는 다음과 같습니다.
  - snapshot마다 CR·결정 파일을 stat하거나 parse하는 일
  - Textual 위젯 갱신(변화가 없어도 다시 그림)
  - liveness 처리

## Contract
- Board의 표시 내용과 갱신 지연(변화가 화면에 보이기까지 걸리는 시간)은 지금보다 나빠지지 않습니다.
- 변화가 없을 때의 비용은 규모에 비례하지 않습니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 측정 근거가 있는 속도 결함이며 사용자가 늘 켜 두는 화면입니다.
- 2026-11-10 Leader: open -> todo. 측정 근거 있는 Board idle CPU 결함

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), [project-board README](../../../tools/project-board/README.md), `tools/project-board/project_board/tui.py`(`refresh_snapshot`, `refresh_liveness`, `refresh_context`, `refresh_items`, `refresh_decisions`), 측정 도구 [`tools/tests/perf/perf_bench.py`](../../../tools/tests/perf/perf_bench.py) 머리말(steady), PERF-001 Result "측정 결과 B", [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 원인 분해: 16×16 격리 환경에서 Board TUI를 띄우고 60초 동안 profile합니다(cProfile 또는 `py-spy`가 있으면 그것). CPU를 주기 작업별(snapshot, liveness, context, 위젯 갱신)로 나눕니다. 변화가 없는 주기에 하는 일을 적습니다.
2. 변화가 없을 때의 일을 상수로 줄입니다. 예: 파일 mtime이 같으면 parse를 건너뛰기, 결과가 같으면 위젯을 다시 그리지 않기, 보이지 않는 pane의 갱신 멈추기. 방법은 근거로 정합니다.
3. 표시 내용과 갱신 지연을 유지합니다. 변화(CR 이동, 결정 추가, run 시작·종료)가 지금과 같은 주기 안에 보여야 합니다.

의존: 없음.

위험 등급: 중간. Board 표시 경로입니다.

## Verification
1. 측정 도구 steady로 현재 `origin/main`과 후보를 비교합니다(`--scales 16x16 --groups board_cli --reps 3 --cold-reps 0 --steady-seconds 60` 또는 steady만 재는 가장 작은 옵션). Board pane 1개의 CPU초를 적고 host load를 함께 적습니다. 목표는 16×16에서 1분에 CPU 3초 이하입니다(코어의 5%). 목표에 닿지 못하면 남은 몫을 근거와 함께 적습니다.
2. 변화가 화면에 반영된다는 test를 둡니다. CR 이동, 결정 추가, run 종료가 대상입니다. 변화가 없을 때 parse나 다시 그리기를 하지 않는다는 호출 수 test도 둡니다.
3. README 검증 표에서 바꾼 경로의 행을 모두 실행합니다(`-rf`). 측정과 동시에 돌립니다.
4. 제출 전에 `origin/main`을 merge하고, merge가 입력을 바꾼 명령만 merge commit에서 다시 실행합니다. 측정은 merge 뒤에 다시 하지 않습니다. 4×4, A/A, cold는 하지 않습니다.
