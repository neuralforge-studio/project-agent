# BOARD-016: Board를 여는 데 2~4초가 걸립니다. 단계를 나누고 Textual 최적화 시제품과 Rust ratatui 시제품을 비교합니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S2
- Related: BOARD-013, BOARD-014, PERF-001, PERF-003
- Mode: read-only
- Base: 60c89db899f102d8ca7d67b3fff033bd9ee907e2 2026-11-11T01:28:20+09:00
- Outcome: merged BOARD-018

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
- 2026-11-11 Leader: in-progress -> done, Outcome merged BOARD-018. Result 검토: 단계 분해(두 환경, sidebar·popup), 시제품 A·C1·C2 비교, C2 재작성 범위, 화면 capture(/primehome/swain/tmp/board016/)를 확인했습니다. 사용자 결정 D-20261111-01 decided C에 따라 구현은 BOARD-018이 맡습니다.

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

## Result
Read-only CR이라 제출 commit이 없습니다. 제품 코드·저장소·다른 project는 바꾸지 않았습니다. 시제품·측정 도구·원자료는 scratchpad `/primehome/swain/tmp/claude-1028/-primehome-swain-Utils-project-agent-project-agent-seat0/8611dbd2-10a7-465b-a3c5-534ee0ec8a55/scratchpad/b016/`(`SP`)에 있고, 사용자가 볼 자료는 `/primehome/swain/tmp/board016/`에 복사했습니다(정리 때 지우지 않음). README 검증 명령은 실행하지 않았습니다(제품 코드 변경 없음).

### 읽는 법
- host load가 14~47로 높고 흔들렸습니다. 같은 표의 변형은 한 반복 안에서 번갈아(A B C A B C…) 실행해 같은 load를 받게 했습니다. 절대 wall은 load에 따라 달라지고, CPU는 덜 움직입니다. 표마다 load 중앙값을 적었습니다.
- 시계는 `CLOCK_BOOTTIME`, ready는 `capture-pane -p`에 project 이름(popup은 본문)이 보이는 때입니다. 반복은 7~9회, 값은 중앙값(`[최소–최대]`)입니다. 4×4·8×8은 재지 않았습니다. 파일 속성 cache는 warm 상태이고 60초 idle 뒤 cold는 재지 않았습니다.
- sidebar는 25×50, popup은 120×40 pane, 실제 등록(10개)은 읽기 전용으로 읽었습니다(liveness는 실제 tmux server를 읽기만 하고 pane은 측정용 server에서만 만듭니다). 측정용 server는 `tmux_test_server.claim`을 썼습니다. 16×16은 `bench_env`입니다.
- 창을 attach하지 않은 측정이라 probe는 `board_visible`을 True로 고정했습니다(숨김 pane 판정 때문에 liveness가 건너뛰어지는 것을 막기 위함). 키 바인딩·`project-board toggle` 경로(split·layout)는 따로 재지 않았고 "tmux 단계"는 `new-window`→bash 진입점까지입니다.

### 1. 단계 분해 (현재 Board 0.7.0 코드, 5회 이상 → 7회)
파일: `/primehome/swain/tmp/board016/stage-breakdown-current.txt`. 값은 wall 중앙값(초), CPU는 그 구간의 프로세스 CPU 중앙값입니다.

| 단계 | 16×16 sidebar (load 25) | 실제 sidebar (load 18) | 16×16 popup (load 14) | 실제 popup (load 19) |
| --- | --- | --- | --- | --- |
| 1 tmux new-window → bash 진입 | 0.03 | 0.02 | 0.03 | 0.02 |
| 2 bash 진입점(launcher, python 선택) | 0.04 | 0.04 | 0.04 | 0.03 |
| 3 interpreter 시동(첫 줄까지) | 0.08 (CPU 0.08) | 0.07 | 0.07 | 0.05 |
| 4 Textual core import | **0.56** (CPU 0.36) | **0.53** (0.36) | 0.41 (0.28) | 0.43 (0.28) |
| 5a agent_session+project_item import | 0.05 | 0.05 | 0.04 | 0.04 |
| 5b project_board.tui 나머지 import(Markdown·TextArea·DataTable·answer) | 0.25 (0.12) | 0.20 (0.11) | 0.16 | 0.15 |
| 6 App 시동(cli→mount) | 0.08 | 0.05 | 0.07 | 0.07 |
| 8 첫 snapshot | **1.19** (CPU 0.72) [0.84–2.35] | **0.89** (0.51) [0.69–1.06] | 0.14 (0.12) | 0.08 |
| 9 첫 liveness(snapshot과 병렬, 첫 그리기를 막지 않음) | 1.74 (CPU 1.12) | 0.34 (0.26) | – | – |
| 10 첫 render(widget mount) | 0.22 | 0.14 | 0.08 | 0.01 |
| 11 render 끝 → 첫 paint | 0.13 | 0.09 | 0.04 | 0.01 |
| **첫 그림(명령부터)** | **2.78 [2.49–5.07]**, CPU 1.72 | **2.00 [1.80–3.18]**, CPU 1.38 | **1.06 [1.03–1.29]**, CPU 0.75 | **0.91 [0.84–1.05]**, CPU 0.60 |
| ready(capture-pane) | 2.79 | 2.00 | 1.07 | 0.97 |

원인(확인된 사실):
- sidebar 첫 snapshot은 CPU가 아니라 **NFS 파일 open·close 지연**이 큽니다. 첫 호출은 파일 348개를 순차로 읽습니다(cProfile: `open` 0.30초+`close` 0.25초, 결정 항목 245개 parse·CR 4,146개 rglob). 둘째 호출은 wall 0.06초·CPU 0.04초입니다.
- 첫 그림은 liveness를 기다리지 않습니다. liveness는 snapshot과 병렬이고 첫 그림 뒤에 끝납니다(16×16에서 liveness가 GIL을 경쟁해 snapshot을 늦춤).
- 고정 비용(bash+interpreter+Textual import+App 시동) ≈ 0.7~0.9초가 popup 여는 시간의 대부분입니다.

### 2. 시제품 A (Textual 유지, 화면 동일) — 단계별 효과
시제품 소스·diff: `$SP/protoA/*`, `/primehome/swain/tmp/board016/prototype-A.diff`(제품 대비 `tui.py` +67/−11, `model.py` +28/−10), 재현 `scripts/mkA.py`. 비교표 `prototype-A-comparison.txt`(9회, load 15~23).

| 변형 | 내용 | 변경 크기(추정=시제품 diff 줄) |
| --- | --- | --- |
| A1 | sidebar가 popup 전용 import(Markdown·TextArea·DataTable·answer)를 하지 않음 | `tui.py` 25줄 |
| A2 | 첫 snapshot에서 project와 파일을 thread로 병렬 읽기(첫 호출에만) | `model.py` 27줄 |
| A3 | 첫 liveness를 첫 paint 뒤로 | `tui.py` 5줄 |
| A4 | listing을 `os.walk` 한 번으로(rglob 대체) | `model.py` 11줄 |
| A5 | 직전 slim snapshot을 cache 파일(`~/.cache/project-board/`)에 써 두고 첫 paint를 그것으로(옛 데이터), 진짜 snapshot이 오면 교체 | `tui.py` 44줄 |
| A6 | A5가 있으면 진짜 첫 snapshot 읽기를 첫 paint 뒤로 | `tui.py` 4줄 |
| A7 | 시동 번들(`bundle_boot.py`, 이미 toggle/sync/click이 쓰는 방식)에 Textual·rich 등 sidebar가 import하는 436개 모듈(7.4 MB)을 넣고 `python -S`로 시동 | 설치기 `bundle.py` ~30줄, launcher ~10줄, 테스트·계약 문서(미시제품화, 추정) |

ready(중앙값, 초) / 프로세스 CPU:
| | 현재 | A1+2+3+4 | +A5 | +A6 | **+A7(번들)** |
| --- | --- | --- | --- | --- | --- |
| 16×16 sidebar(load ≈21) | 2.80 / 1.64 | 1.93 / 1.73 | 1.23 / 0.87 | 1.14 / 0.82 | **0.83 [0.72–1.28] / 0.69** |
| 실제 sidebar(load ≈16) | 2.22 / 1.33 | 1.82 / 1.70 | 1.04 / 0.75 | 1.12 / 0.73 | **0.72 [0.63–0.74] / 0.61** |
| 16×16 popup(load 18~22, 7회) | 1.23 / 0.83 | A1 1.33, A1+4 1.32 | – | – | **0.81 [0.69–1.35] / 0.69** |
| 실제 popup(load 19, 7회) | 1.11 / 0.71 | A1 1.10, A1+4 1.06 | – | – | **0.63 [0.51–0.61] / 0.48** |

읽을 점(사실):
- **지배 효과는 A7(번들)입니다.** Textual+project_board import wall을 별도로 재면 0.69~0.79초 → 0.32~0.38초입니다(`bundle-import-time.txt`, load 8~26 모두). NFS의 모듈별 open 지연이 줄어든 것이고, CPU 시간은 같습니다.
- A1은 sidebar import만 −0.2초(`tui rest` 0.25→0.01)이고 popup은 Markdown·TextArea를 어차피 읽어서 이득이 없습니다(A1 popup 1.1~1.3 ≈ 현재).
- A2(병렬 읽기)는 첫 snapshot을 1.1→0.7초로 줄이는 데 그칩니다: 남은 0.4~0.5초는 Python CPU(GIL)라서 thread로 줄지 않습니다(Rust 병렬 C2는 같은 읽기를 0.24초에 끝냄). A2·A3 단독은 CPU가 오히려 늘어(1.3→1.7) 첫 호출에서만 pool을 쓰게 해 갱신 CPU는 그대로입니다(아래).
- A6는 A5 위에서 뚜렷한 이득이 없습니다(16×16 1.23→1.14, 실제 1.04→1.12: 잡음 범위).
- **A5의 첫 그림은 옛 데이터입니다.** 새 데이터가 화면에 오르는 시각(= snapshot 끝 + render): 현재 2.53(16×16)/2.18(실제), A1~4 1.87/1.77, A5~7 1.66/1.52(A7). 즉 A5는 "보이는 시간"만 앞당기고 최신 값은 1.5~1.7초에 옵니다(옛 값이 1초 안팎 보임).
- 갱신(열린 뒤) CPU: `model.snapshot` 둘째 호출 현재 0.043(16×16)/0.047(실제) → A 0.044~0.048 / 0.052; A5의 slim 변환 +0.001~0.003초 → **갱신 CPU는 그대로**입니다.
- 화면: 현재와 A(A1~A6, A7) sidebar의 `capture-pane -p -e`가 숫자(경과 분)를 마스킹하면 **ANSI까지 완전히 같습니다**(실제 등록·16×16). popup(실제 falcon2, 16×16 p00)은 A7이 현재와 text·ANSI 모두 바이트 동일입니다.
- A7의 위험: 번들은 설치한 Python·Textual 버전에 묶여 Textual을 올리면 다시 만들어야 하고(현재 번들 헤더는 `sys.version`만 확인) 설치 계약(6.1)·release digest·테스트를 건드립니다. 이번에는 미시제품화(시동 경로만 실험).
- 1초 이하: **16×16에서 A5+A7은 ready 0.83초(최대 1.28), A7 단독 popup 0.81초**로 닿습니다(load 20 안팎). 다만 sidebar는 옛 데이터 기준이고 새 데이터는 1.66초입니다. A7 없이 A1~A6만으로는 1.1~1.2초가 한계입니다. 번들·cache 없는 A1~4는 1.9초입니다. popup 한 번을 "이미 떠 있는 process 재사용"하면 시동(위 1~6단계 ≈ 0.7~0.8초)을 빼고 snapshot+render ≈ 0.2~0.3초지만 미시제품화입니다(tmux popup 경로와 fd 전달이 필요, 추정 150~250줄).

### 3. 시제품 C (Rust ratatui) — fork 측정, 상세 `/primehome/swain/tmp/board016/rust-report.md`
- 빌드: vendored ratatui 0.30.2·crossterm 0.29 offline release 36.8초, binary 1.5 MB, 시제품 Rust 794줄+helper.py 68줄(`scripts/board-rs-src`, `helper.py`).
- 이 측정은 load 30~47에서 했습니다(위 A·현재 표와 load가 달라 절대값을 직접 견줄 수 없음; 아래 "현재"는 같은 반복에서 번갈아 잰 값).

| | 현재 Textual | C1(Python helper 상주+slim JSON) | C1+cache | C2 병렬 읽기 | C2 순차 |
| --- | --- | --- | --- | --- | --- |
| 실제 sidebar 데이터가 그려짐(load 35) | 3.43 [2.58–5.95] | 1.58 [1.03–4.27] | 첫 화면 0.06(옛), 새 1.63 | **0.32 [0.22–0.71]** | 0.74 |
| 16×16 (load 31) | 3.91 [2.96–7.88] | 2.14 [1.23–3.15] | 첫 화면 0.08(옛), 새 1.59 | **0.48 [0.23–1.32]** | 1.28 |
| 열린 뒤 2초 갱신 1회분 CPU, 실제/16×16 | 0.087 / 0.096 | 0.066 / 0.087 | – | **0.029 / 0.032** | – |

- C1: 첫 snapshot(Python, NFS 읽기) 1.1~1.3초가 그대로 남고 Textual import·widget만 사라집니다. 전체 snapshot JSON 756 KB를 slim 6.9 KB로 줄여 받습니다.
- C2(읽기만, 새 process 첫 읽기): 실제 Python `model.snapshot` 1.30초 vs Rust 병렬 8 thread 0.24초, 순차 0.58초. 16×16은 1.37 vs 0.27/0.82. 개수는 Python과 **차이 0건**(실제 10개·16×16). 느린 원인은 CPU가 아니라 NFS 지연이라 병렬 읽기만 wall을 줄입니다.
- liveness 판정은 C2에서 구현하지 않았습니다(판정이 쓰는 tmux 읽기 2개만 0.02~0.04초 측정; 판정 자체의 비용은 미측정).
- Rust binary는 bash launcher 없이 직접 실행해서 제품이 되면 launcher 0.03~0.04초가 더해질 수 있습니다.

### 4. C2로 옮길 때 다시 써야 하는 Python 규칙(함수 줄 수, base 60c89db)
- 읽기: `agent_session/config.py`(registry 약 158줄, 시제품은 base·seat 수·path 부분만), `state.py`(읽기·검증 약 100), `api.project_state`·`pane_slot`(11), `project_item/cr.py`·`decide.py`·`read.py`·`store.py`(parse_text·files·submitted_hash·decision_stage·text_sections·cr_states 약 160), `project_board/model.py` 305줄 → 시제품 Rust 324줄이 sidebar용을 대신함(popup용 `result_markdown`·`contract_markdown`·`sections`는 미구현).
- liveness·tmux 판정(spec 5절 소유, 시제품 미구현): `api.project_liveness`·`server_view`·`project_pending_releases` 61, `tmux.py` ServerView·`_observe`·`pane_slot` ≥190, `process.py` 23, `model.liveness` 22 → **≈ 300줄**.
- 쓰기·연동(결정 답변 쓰기, toggle, 클릭): `answer.py` 98(+`api.caller` 34, operator 판정), `project_item.store.answer_decide`·`render` ≈ 100+, `tmux_control.py` 750(`_reconcile` 67·`route_click` 38·`toggle_sidebar` 17·`switch_*`·`open_popup` 등), `tui.py` sidebar 부분 ≈ 500 → ≈ 1,000줄 이상. Python에 두고 Rust가 `project-board toggle|sync|click`·`agent-session send`·`project-item`을 subprocess로 부르는 하이브리드가 가장 작은 변경입니다.
- 읽기+liveness만 옮기면 Python ≈ 800줄 상당, 전부 옮기면 ≈ 1,900줄 이상과 `tools/tests`의 대응 검증을 다시 써야 합니다.
- popup: vendored 534개 crate에 `pulldown-cmark`·`comrak`·`tui-markdown`·`tui-textarea`·`edtui`·`syntect`가 **없습니다**(목록으로 확인). Markdown(제목·목록·인용·코드·표·링크)·fenced CSV 표(DataTable)·답변 TextArea(한글 입력)는 직접 써야 하고, 대응하는 Python이 약 500줄입니다(Rust 쪽 작업량은 추정). popup을 만들지는 않았습니다.

### 5. 화면 비교 (`cat`으로 볼 수 있음, 모두 `capture-pane -p -e`)
디렉터리 `/primehome/swain/tmp/board016/`
- 현재 Board: `cur-real-sidebar.{txt,ansi}`(25×52, project-agent·falcon2 펼침), `cur-b16-sidebar.*`(p00·p01 펼침), `cur-real-popup.*`(120×40, falcon2), `cur-b16-popup.*`
- 시제품 A: `a123456-real-sidebar.*`, `a123456-b16-sidebar.*`, `a7-real-sidebar.*`, `a7-b16-sidebar.*`, `a7-real-popup.*`, `a7-b16-popup.*`
- 시제품 C: `c1-real-sidebar.*`, `c2-real-sidebar.*`, `c1-b16-sidebar.*`, `c1-real-sidebar-active-falcon2.*`(활성 project 강조)
- 예: `cat /primehome/swain/tmp/board016/cur-real-sidebar.ansi`

차이 목록:
- A vs 현재: sidebar·popup 모두 **차이 없음**(sidebar는 경과 분 숫자만 캡처 시각 차이, 숫자를 가리면 ANSI 동일).
- C vs 현재(sidebar만 구현, 25×52, 같은 펼침):
  - 실제 등록: plain text 완전 동일. 색·굵기·배경 cell 차이는 줄 끝 공백 cell의 배경(눈에 안 띔)과 비활성 글자색 파랑 채널 ±1뿐입니다.
  - 16×16: 본문 동일, 스크롤바 thumb 끝의 8분의 1 블록 높이가 다름(`▅`↔`▇`, thumb 길이 ¼행 차이).
  - 같음: 배경 #111c28, 굵은 이름 #e6f0ff, `D:n` 노랑/빨강/흐림, `O T I` 칸·0 흐림, `▸▾`, Leader·seat 줄 색, 활성 project #2f6db3 강조, 한글 폭.
  - 시제품에 없는 것: hover 배경, focus(Tab/Enter), tooltip, 마우스 클릭(project·CR popup·결정 popup·seat 전환·접기), click socket 수신, SIGUSR1 가시성, `active_context`(▶ 표시), popup 두 종류, 긴 이름 가로 스크롤(Rust는 잘라 냄). 표·테두리는 sidebar에 없고 Markdown 표·DataTable은 popup에 있어 C는 미비교입니다.

### 6. 사용자가 방향을 고를 때 참고
| | A (Textual 유지) | C (Rust) |
| --- | --- | --- |
| 16×16 sidebar 여는 시간(같은 조건) | 현재 2.8 → A1~4 1.9 → +cache 1.2 → +번들 **0.83**(옛 데이터 첫 화면, 최신 1.66) | C2 병렬 **0.48**(최신 데이터), C1 2.1 |
| 16×16 popup | 현재 1.2 → 번들 **0.81** | 미시제품(Markdown·입력 자체 구현 필요) |
| 화면 | 동일(검증함) | sidebar 거의 동일, 상호작용·popup 미구현 |
| 변경 크기 | 제품 코드 약 100줄(A1·2·3·4·5)+번들(설치기·launcher 약 40줄과 계약·테스트) | sidebar 읽기+liveness 재작성 ≈ 800줄 상당 +(하이브리드로 쓰기는 Python 유지)+popup은 Textual 유지 또는 ≈ 500줄 재작성 |
| 남는 비용 | 첫 snapshot Python CPU 0.4~0.5초(최신 데이터 ≈ 1.5초대) | Python 3.x 병행 유지, launcher, 이중 규칙(SSOT) |
- 확인한 사실: 최신 데이터를 1초 안에 보이려면 C2 병렬이 필요하고(0.3~0.5초), 옛 데이터라도 보이게 하는 것이 허용되면 Textual 유지(A5+A7)로도 16×16에서 1초 안팎입니다. 가설: A의 첫 snapshot도 Python 안에서 더 줄일 여지(숨겨진 완료 결정의 section parse 생략 등)는 시험하지 않았습니다.
- 사용 도구: `scripts/measure.py`(단계 분해·교차 측정), `analyze.py`·`summ.py`, `capture.py`, `mkA.py`·`mkvariant.py`·`mkbundle.py`·`bundle_time.py`·`steady.py`, Rust 쪽은 `rust-report.md` 8절. 원자료는 `SP/out/*.jsonl`(`b16-*`·`real-*`: 교차 비교, `cur-*`: 단계 분해, `run1/`: load 34~36 첫 교차 batch).
