# BOARD-016: Board를 여는 데 2~4초가 걸립니다. 단계를 나누고 Textual 최적화 시제품과 Rust ratatui 시제품을 비교합니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S2
- Related: BOARD-013, BOARD-014, PERF-001, PERF-003
- Mode: read-only
- Base: 60c89db899f102d8ca7d67b3fff033bd9ee907e2 2026-11-11T01:28:20+09:00

## Symptom
Project Board를 열 때 이 workstation(project 10개)에서 2~3초가 걸립니다. 16×16에서는 sidebar가 약 4초, popup이 약 2초입니다. 열린 뒤의 갱신은 빠릅니다(2초마다 CPU 0.04초). 사용자는 느리다고 느끼고 Rust로 옮겨야 하는지 물었습니다. 화면 모양은 지금 수준이 유지되어야 합니다.

## Evidence
- Leader 측정(2026-11-11 01:17, 설치본 0.7.0, 실제 등록 10개, host load 24~39):
  - `import project_board.tui`: wall 0.97~1.85초, CPU 0.6초. 대부분 Textual입니다.
  - 첫 `model.snapshot()`: wall 0.86~1.09초
  - 두 번째 snapshot: wall 0.06초, CPU 0.04초
  - `model.liveness()`: wall 0.24초, CPU 0.05초
- BOARD-014 Result(16×16, 5회): popup ready 중앙값 1.87~2.23초, sidebar ready 3.66~4.14초.
- PERF-001 측정 결과 D(16×16): `import_project_board` CPU 0.57~0.61초, `board_snapshot_first` wall 0.88초, `board_liveness` wall 1.25초.
- 사용자 원문(2026-11-11): "rust로 옮겨야하는거 아니야? 왜 느린거야?" 이어서 "curses도 textual처럼 여러 표라던가 highlight 등이 제대로 지원이 돼? 지금 visual 적으로 어느정도는 만족하는데 visual 적으로 downgrade 된다면 curses는 사용하지 않겠어. 측정 시제품 비교부터 진행해봐."
- 사내 오프라인 Rust 의존성 `/primehome/tools/Inhouse/Rust/dependencies/2026-10-29-r3`에 `ratatui-0.30.2`와 `crossterm-0.29.0`이 있습니다. cargo는 `/primehome/tools/Inhouse/Rust/latest/bin/cargo`입니다. 사용 예는 balvian의 `rust/.cargo/config.toml`(vendored source, offline)입니다.

## Contract
- 이 CR은 측정과 시제품 비교만 합니다. 제품 코드와 저장소는 바꾸지 않고, 시제품은 scratchpad에 둡니다.
- 결과는 사용자가 방향을 고를 수 있는 숫자와 화면 비교입니다. 방향은 A(Textual 유지와 최적화)와 C(Rust Board)입니다.
- 화면 모양이 지금보다 떨어지는 방법은 후보가 아닙니다. 사용자 원문에 따라 curses는 후보에서 뺍니다.

## Disposition
- 2026-11-11 Leader: 조사한다(Leader 판정, read-only). 사용자가 "측정 시제품 비교부터 진행해봐"라고 지시했습니다. Rust로 옮길지는 결과를 보고 사용자가 결정합니다.
- 2026-11-11 Leader: open -> todo. 사용자 지시: 측정 시제품 비교부터

## Implementation
읽을 문서: [project-board README](../../../tools/project-board/README.md), [Board TUI 계획](../../project-board-tui-plan.md), `tools/project-board/project_board/{__main__,tui,model,tmux_control}.py`, `tools/project-board/bin/project-board`, 측정 도구 [`tools/tests/perf/perf_bench.py`](../../../tools/tests/perf/perf_bench.py) 머리말과 `bench_env.py`·`bench_ops.py`(`pane_ready`), BOARD-014 Result, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 여는 시간 분해: sidebar와 popup 각각에 대해 단계별 wall·CPU를 잽니다.
   - 단계: tmux key·pane 생성, bash 진입점, interpreter 시동, Textual import, `project_board` 나머지 import, 첫 snapshot, 첫 liveness, 첫 그리기(ready)
   - 환경 두 가지: 실제 등록(이 workstation, 읽기만 함)과 16×16 격리 환경(`bench_env`)
   - 반복 5회 이상, host load를 함께 적습니다.
2. 시제품 A(Textual 유지): 화면 모양을 바꾸지 않고 여는 시간을 줄이는 방법을 시제품으로 만들어 잽니다. 예:
   - 첫 그리기를 liveness보다 먼저 하기
   - import 지연
   - 첫 snapshot의 읽기 범위 줄이기(보이는 것 먼저)
   - popup이 떠 있는 sidebar process를 재사용하기
   달성 가능한 여는 시간과 그 방법의 크기(바뀌는 파일·줄 수 추정)를 적습니다.
3. 시제품 C(Rust ratatui): 지금 sidebar의 한 화면(project 목록, 펼친 project의 seat·CR 행, 색과 강조)을 같은 모양으로 그리는 최소 binary를 vendored crate로 offline build합니다. 데이터를 얻는 방법 두 가지를 잽니다.
   - C1: Python이 만든 snapshot JSON을 받음. 예: 기존 model을 부르는 작은 Python helper. 첫 화면까지와 갱신마다의 wall·CPU를 잽니다.
   - C2: Rust가 파일을 직접 읽음. 등록 파일, state.json, CR·결정 디렉터리 listing과 header 해석이 대상입니다. 읽기 시간만 재고, 제품으로 만들 때 Rust로 다시 써야 하는 Python 규칙의 범위(모듈·함수·줄 수)를 적습니다. 결정 답변 쓰기, toggle, liveness 판정이 포함됩니다.
4. 화면 비교: 지금 Board, 시제품 A, 시제품 C의 같은 화면을 `tmux capture-pane -p -e`(ANSI 색 포함)로 저장합니다. 사용자가 `cat`으로 볼 수 있는 경로를 Result에 적습니다. 위치는 seat 밖 `/primehome/swain/tmp/board016/`이며 정리 때 지우지 않습니다. 색·표·강조·테두리에서 Textual과 다른 점을 적습니다.
5. 저장소 파일과 다른 project의 파일은 바꾸지 않습니다. 측정용 tmux server는 `tools/tests/tmux_test_server.py`의 claim·release를 씁니다.

의존: 없음.

위험 등급: 낮음. 조사입니다.

## Verification
1. Result에 다음을 적습니다.
   - 단계 분해표(두 환경, sidebar·popup, 중앙값과 범위, load)
   - 시제품 비교표(지금, A, C1, C2의 여는 시간과 갱신 CPU)
   - C2의 다시 써야 하는 규칙 범위
   - 화면 capture 경로와 차이 목록
   - 16×16에서 여는 시간 1초 이하에 어느 방법이 닿는지
2. 제품 코드를 바꾸지 않으므로 README 검증 명령은 실행하지 않습니다.
3. 사용자가 빠른 결과를 원합니다. 반복은 5회로 하고 4×4와 8×8은 재지 않습니다.
