# BOARD-018: Board sidebar를 Rust(ratatui)로 옮겨 최신 데이터로 1초 안에 엽니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S2
- Base: 65f601db83908a9067a8e8bd5bc03fe25769e7ca 2026-11-11T10:13:43+09:00
- Outcome: fixed

## Symptom
Board sidebar를 여는 데 16×16에서 2.8초, 실제 등록 10개에서 2.2초가 걸립니다(0.7.0, BOARD-016 단계 분해). 사용자는 "rust로 옮겨야하는거 아니야? 왜 느린거야?"라고 물었습니다. BOARD-016 결과를 보고 결정 D-20261111-01에서 C(sidebar를 Rust로)를 골랐습니다.

## Evidence
- BOARD-016 Result(`docs/cr/done/BOARD-016-board-2-4-textual-rust-ratatui.md`):
  - 느린 원인은 NFS 대기입니다. 첫 snapshot은 파일 348개를 차례로 열고, Textual import는 0.7~0.8초 걸립니다. CPU 자체는 작습니다.
  - 시제품 C2(Rust가 파일을 직접 병렬로 읽음)는 16×16에서 최신 데이터로 0.48초 걸렸습니다. 같은 반복에서 지금 Board는 3.9초였습니다. 갱신 1회 CPU는 0.03초로, 지금 0.09초보다 작습니다.
  - 시제품은 project 개수와 내용을 Python과 같게 읽었습니다(차이 0건). 글자는 지금 화면과 같고, 색 차이는 줄 끝 공백 칸의 배경과 비활성 글자색 ±1뿐입니다.
  - 시제품에 없는 것: hover 배경, focus, tooltip, 마우스 클릭, click socket, SIGUSR1 가시성, 현재 창 강조(▶), 긴 이름 가로 스크롤. Rust는 긴 이름을 잘라 냅니다.
  - 다시 써야 하는 Python 규칙의 범위는 Result 4절에 있습니다. 읽기는 약 500줄, liveness·tmux 판정은 약 300줄입니다.
- 시제품 소스: `/primehome/swain/tmp/board016/scripts/board-rs-src/`(main.rs, model.rs, ui.rs, c2.rs, clock.rs), `helper.py`, 측정 보고 `/primehome/swain/tmp/board016/rust-report.md`
- 사내 오프라인 Rust: cargo `/primehome/tools/Inhouse/Rust/latest/bin/cargo`, vendored crate `/primehome/tools/Inhouse/Rust/dependencies/2026-10-29-r3`(ratatui 0.30.2, crossterm 0.29.0). 사용 예는 balvian의 `rust/.cargo/config.toml`입니다. 시제품은 offline release build에 36.8초 걸렸고 binary는 1.5 MB입니다.
- 지금 sidebar 진입점: `tools/project-board/project_board/cli.py`(`sidebar`), `tui.py`(`SidebarApp`, `run_sidebar`), `tmux_control.py`(`_sidebar_command`, `board_visible`, `mark_ready`, `route_click`, `toggle_sidebar`, sync)

## Contract
1. 여는 시간: 16×16에서 sidebar가 최신 데이터로 그려지기까지(ready) 1초 이하입니다. 첫 그림은 liveness를 기다리지 않습니다.
2. 화면은 0.7.1 sidebar와 같습니다.
   - 색, 행 구성, 굵기, 활성 project ▶와 slot 강조, `D:n` 색, 0·`-` 흐림, Leader·seat·error 행이 같습니다.
   - hover 배경과 tooltip 내용이 같습니다.
   - 긴 이름은 잘라 내지 않고 가로 스크롤로 전체를 볼 수 있습니다. 세로 scroll도 같습니다.
   - 갱신은 바뀐 칸만 다시 그립니다. 중간 상태가 보이지 않습니다(BOARD-004·BOARD-017 계약).
3. 동작은 0.7.1과 같습니다.
   - 클릭: project 이름, O·T·I, D, 접기, seat. tmux를 거친 클릭 전달(click socket), keyboard focus와 Enter도 포함합니다.
   - 가시성: 창이 보이지 않으면 읽지 않습니다(SIGUSR1, `mark_ready`).
   - 갱신 주기: snapshot 2초, liveness 10초, 현재 창 10초입니다.
   - popup(CR·결정)은 지금처럼 Python Textual로 엽니다.
4. 데이터 규칙: 모든 project에서 Python 구현과 같은 결과를 냅니다. 대상은 CR 개수, 결정 단계, seat(상태·경과·제목·host·path), Leader 경과, 오류 행, liveness입니다.
   - 같은 규칙이 Python과 Rust 두 곳에 생깁니다. 같은 fixture에서 두 구현의 결과를 비교하는 일치 test가 이 중복을 지킵니다.
   - 이 예외의 이유와 범위는 [제품 지도](../../project-team/README.md)에 적습니다.
5. Python `SidebarApp`과 그 test는 지웁니다. sidebar 구현은 하나만 둡니다.
6. 설치: 설치기가 release의 Rust source를 vendored crate로 offline build합니다.
   - build가 실패하면 `current`를 바꾸지 않습니다. 떠 있는 release가 그대로 남으므로 Board가 깨진 release로 넘어가는 경우가 없습니다.
   - 설치 계약, README 검증 표, release 절차에 cargo test와 build를 넣습니다.
7. 열린 뒤 idle CPU는 0.7.1보다 늘지 않습니다(BOARD-013).

## Disposition
- 2026-11-11 Leader: 구현한다. 사용자 결정 D-20261111-01, Outcome decided C.
  - 사용자 원문(대화): "B로 진행하고 0.7.1 업그레이드해"
  - 선택지에 B가 없어 되물었고, 사용자가 "C. sidebar를 Rust로"를 골랐습니다. Board 답변도 "C"입니다.
- 2026-11-11 Leader: 결정한 방향 안에서 Leader가 정한 것(Leader 판정)입니다. 사용자는 CR을 open으로 되돌려 바꿀 수 있습니다.
  - Python `SidebarApp`을 지웁니다. 같은 화면을 두 언어로 유지하지 않으려는 것입니다.
  - 설치할 때 build합니다. 실패하면 release를 바꾸지 않습니다. 저장소에 binary를 넣지 않고, 어느 경로로도 Board가 깨진 release로 넘어가지 않게 하려는 것입니다.
  - 두 언어에 생기는 읽기 규칙은 일치 test로 지킵니다.
- 2026-11-11 Leader: open -> todo. 사용자 결정 D-20261111-01 decided C
- 2026-11-11 Leader: 범위를 더합니다. 사용자 지시: "rust로 이미 수정하기로 결정된 상태라서, 원인 파악한 것을 rust 쪽에 반영할게 있다면 반영해서 rust용 side bar를 만들도록 하자." 더하는 것은 넷입니다. (1) 기준 화면은 0.8.1(BOARD-023 이름 줄 포함)입니다. (2) BOARD-022 결론에 따라 주기 읽기와 클릭 처리마다 tmux process는 하나이고, 호출 수를 test로 셉니다. (3) BOARD-022·025 결론에 따라 클릭이 Python 시동을 기다리지 않게 합니다. tmux 명령 하나로 끝나는 전환은 Rust가 직접 하고, 하위 명령은 시동 번들 경로로 부르고, CR·결정 창이 떠 있으면 BOARD-025의 규약 socket에 직접 알립니다. (4) prefix B 켜기·끄기와 sync는 Python에 남깁니다.
- 2026-11-11 Leader: 제출 2a79768을 검토했습니다. Rust crate, Python SidebarApp 제거, 일치·binary·전환 test, 설치기 build(실패 시 current 불변, T34~T40), README 검증 표의 Rust 행, 제품 지도 예외, A/B(7.99→1.40초, load 54~58), idle CPU, 화면 차이를 확인했습니다. 수정 요청은 하나입니다. BOARD-025(75285ec)를 merge해서 떠 있는 창에 규약 socket으로 직접 알리는 경로를 activate에 붙이고, merge commit에서 바뀐 경로 행 명령을 다시 실행합니다.
- 2026-11-11 Leader: 설치 영향(설치 때 사내 Rust build, Python sidebar 제거)을 사용자에게 물었습니다. 결정 D-20261111-03 decided A. 사용자 원문: ""이렇게 바뀌어도 괜찮으시면, 수정 제출을 확인한 뒤 바로 release하고 설치하겠습니다." : OK". 수정 제출을 인수하면 release하고 설치합니다.
- 2026-11-11 Leader: 화면 요구 두 가지를 더합니다(사용자 요청). (1) "Side bar에서 highlight 되는 leader에 화살표 표시 추가되는거 제거.": 현재 창 project 이름 줄의 `▶ `를 없애고 강조 색만 둡니다. (2) "D:0 일때, 채도 빠지는거 어디는 적용되고 어디는 적용안되고, 무엇이 맞는거? 나는 채도가 빠지는게 맞다고 생각함.": `D:0`과 `-`는 항상 흐린 색으로 그리고, 클릭 동작(보이는 결정이 있으면 열림)은 그대로 둡니다.
- 2026-11-11 Leader: 위 (2) D:0 흐리게는 취소합니다. 사용자 원문: "오호!! 몰랐네. 오케이 유지해줘 현재 상태." D:0 색은 지금 규칙을 유지합니다. (1) ▶ 제거는 그대로입니다.
- 2026-11-12 Leader 검토(수정 제출 a7b972753cef40d7226a5b5d73990b260dd6f36c): 인수. 첫 제출(2a79768) 검토 근거는 바뀌지 않은 범위에 재사용하고, 그 뒤 바뀐 부분을 확인했습니다.
  - BOARD-025 창 알림 client(`rust/src/window.rs`): Python `tmux_control._reuse`와 판정이 같습니다(같은 종류의 창만, `ok`면 title만 바꿈, `busy`면 알림, 그 밖은 `project-board`로 시작). 시작 중인 창은 Rust가 기다리지 않고 Python 경로에 넘기며, Python 경로는 Board 잠금 안에서 기다립니다. 제품 지도의 중복 예외 표에 이 client가 들어 있습니다.
  - 남은 빈틈: Rust 창 알림 test는 Python client와 비교하지 않고 가짜 창을 상대로 TUI 계획 5절대로 하는지 봅니다. 그래서 Python 규칙이 바뀌어도 Rust test가 실패하지 않습니다(읽기 규칙의 `test_rust_equivalence.py`, 전환의 `test_rust_switch.py`와 다름). 같은 client를 cron 창으로 넓히는 BOARD-027에 일치 test를 넣습니다.
  - 현재 창 이름 줄의 `▶ ` 제거(golden 6개), `D:0` 변경 되돌림, 설치 시험 T36~T42 이동(INSTALL-008의 T34·T35와 겹침 해소), T42 timeout 1800초를 확인했습니다.
  - 재실행(a7b9727, merge 포함): `install/tests` 313 passed 2 skipped, project-board+api_boundary+remote 389 passed, 네 번째 명령 141 passed, `cargo test` 72 passed. vi3 실패의 원인(merge 때 import 누락은 고침, 나머지는 load 100~200의 timeout)과 그 뒤 통과 근거가 Result에 있습니다.
  - 지금 `origin/main`(SESSION-016 통합분)과는 설치 계약 8절 표에서만 충돌합니다(main의 T35 행, 이 CR의 T36~T42 행). Leader가 통합 merge에서 두 쪽을 모두 살려 풉니다. 통합한 tree는 release 검증(clone에서 다섯 명령과 `cargo test`)이 확인합니다.
- 2026-11-12 Leader: 제출 a7b972753cef40d7226a5b5d73990b260dd6f36c를 인수합니다.
- 2026-11-12 Leader: in-progress -> done, Outcome fixed. 통합 2bcd290 (origin/main)

## Implementation
읽을 문서:
- BOARD-016 Result 전체, `/primehome/swain/tmp/board016/rust-report.md`
- [project-board README](../../../tools/project-board/README.md), [Board TUI 계획](../../project-board-tui-plan.md)
- [동작 명세](../../project-team/spec.md) 5절(liveness의 원본), [설치 계약](../../project-team/install-contract.md), [release 절차](../../project-team/release.md), [제품 지도](../../project-team/README.md), README 검증 표
- [project-team Worker 절](../../../skills/project-team/SKILL.md)

1. Crate: `tools/project-board/rust/`에 둡니다(`Cargo.toml`, `Cargo.lock`, `src/`, vendored source를 쓰는 `.cargo/config.toml`).
   - binary 이름은 `project-board-sidebar`입니다. 설치 위치는 `<release>/tools/project-board/bin/` 아래입니다.
   - 시제품 소스에서 시작합니다. vendored 디렉터리 경로는 환경 변수로 바꿀 수 있게 하고, 기본값은 사내 경로로 합니다.
2. 읽기: 시제품 C2(병렬 읽기)를 Contract 4의 범위로 완성합니다. liveness는 spec 5절의 판정을 그대로 옮깁니다.
3. 화면과 동작: Contract 2·3을 구현합니다.
   - `tmux_control`이 sidebar pane에서 Rust binary를 실행하게 바꿉니다.
   - 클릭 동작(popup 열기, seat 전환, 접기·펼치기)은 지금 Python 함수를 `project-board` 하위 명령으로 부릅니다. 필요하면 하위 명령을 추가합니다.
   - click socket, SIGUSR1, `mark_ready`의 규약은 지금과 같습니다.
4. Python sidebar 제거: `SidebarApp`, `run_sidebar`, `cli.py sidebar`, 그 test를 지웁니다. popup과 `model.py`의 popup용 읽기는 남깁니다.
5. 일치 test: `tools/project-board/tests`에서 `board_testing.Board` fixture로 Rust binary의 읽기 결과(JSON 출력 모드 등)를 Python `model.snapshot`·`liveness`와 비교합니다.
   - 대상 경우는 지금 Python test가 다루는 경우와 같습니다: 결정 단계, seat 상태 전부, 원격 seat, 오류, path가 없는 project.
6. 설치: 설치기가 `cargo build --release --offline --locked`로 build합니다(target dir은 임시 디렉터리).
   - build에 성공한 뒤에만 `current`를 바꿉니다. 실패하면 이유를 출력하고 끝냅니다.
   - `check`는 binary가 있고 실행되는지 확인합니다.
   - 설치 계약 2·7·8절, README 검증 표(`tools/project-board/**` 행과 새 Rust 행), release 절차의 검증 명령에 cargo test를 넣습니다.
7. 제품 지도에 중복 예외(이유, 범위, 일치 test 위치)를 적습니다.
8. 독립된 부분(설치기 build, sidebar 구현)은 sub-agent로 나눠도 됩니다. process를 멈출 때는 자기가 띄운 PID로만 멈춥니다.

의존: 없음. 0.7.1(BOARD-017)이 기준입니다.

위험 등급: 높음. sidebar 구현, 설치기, release 절차를 함께 바꿉니다.

## Verification
1. README 검증 표에서 바꾼 경로의 행 명령 전부를 실행합니다. 이 CR은 `tools/project-board/**`, `install/**`, `integrations/tmux/**`(바꾸면), 문서를 바꿉니다. 새 Rust 행의 cargo test도 포함합니다.
2. 여는 시간 A/B: 16×16 sidebar ready(최신 데이터)를 0.7.1과 이 CR로 번갈아 3회 잽니다. wall과 CPU를 95% 구간과 함께 적습니다. test는 측정과 동시에 돌립니다.
3. idle CPU: 16×16에서 열린 뒤 1분 CPU를 3회 잽니다. 0.7.1보다 늘지 않아야 합니다.
4. 화면: 실제 등록과 16×16에서 0.7.1과 이 CR의 `tmux capture-pane -p -e`를 `/primehome/swain/tmp/board018/`에 저장하고 차이 목록을 적습니다. hover·tooltip·가로 스크롤 화면도 포함합니다.
5. 설치: 격리 HOME에서 install, upgrade(build 성공), upgrade(build 실패: `current`가 그대로)를 install test로 확인합니다.

## Result
- 제출 commit: 2a79768e5a424abe1d0b20b9a301b3c87c98e4b9

`origin/cr/BOARD-018`에 push했습니다. 마지막 `origin/main` merge는 BOARD-026·BOARD-022·release 0.8.1까지입니다(2a79768).

### 한 일
- **Rust sidebar**(`tools/project-board/rust/`, binary `project-board-sidebar`):
  - `src/data/`: 등록·state·CR·결정 파일과 run liveness 읽기. 첫 읽기는 32 thread로 병렬, 이후는 `stat` 서명으로 바뀐 것만 읽습니다. 분담해서 만든 것을 합쳤습니다.
  - `src/ui.rs`: 화면. 0.7.1 Textual sidebar와 칸 단위로 같게 그립니다(색, hover 배경, focus, 스크롤바, tooltip, 가로·세로 스크롤).
  - `src/app.rs`: 이벤트 루프. 2초 파일 읽기, 10초 liveness·현재 창 읽기, click socket, SIGUSR1·`mark_ready`, 키·마우스, 한 번 그리기(바뀐 칸만).
  - `src/tmuxio.rs`: 접힘·가시성·현재 창의 tmux 읽기(tmux process 하나씩). `src/switch.rs`, `src/data/jump.rs`: project·seat 전환을 sidebar가 직접 tmux로 합니다.
- **BOARD-023 모양**: 이름 줄 `{▶ }{project} {time}`, `Leader` 줄 없음, Leader window는 이름 줄 강조(Leader 메시지로 범위가 늘었습니다).
- **Python**: `SidebarApp`·`run_sidebar`·`cli.py sidebar`와 그 test를 지웠습니다. `tmux_control`은 binary를 실행합니다(`sidebar_binary`). `project-board`에 `open-decision`·`open-cr`·`toggle-fold`·`liveness`를 더했고, 이 하위 명령과 `sync|click|toggle`은 시동 번들(`python -S`)로 시작합니다(`bin/project-board`).
- **설치기**: release를 만들 때 vendored crate로 `cargo build --release --offline --locked`를 하고, 성공한 뒤에만 `current`를 바꿉니다. 실패하면 이유를 출력하고(종료 코드 4) release 디렉터리·`current`가 그대로입니다. `check`는 binary 실행을 확인합니다. 설치 계약 2.1절과 T34~T40.
- **문서**: 제품 지도에 중복 예외(이유, 범위 표, 일치 test 위치), TUI 계획·README·spec·설치 계약·release 절차·README 검증 표.
- **perf 도구**(`tools/tests/perf`): `Executable.sidebar_argv`(새 binary와 옛 `project-board sidebar` 둘 다 잽니다), probe가 지운 함수를 건너뜁니다.

### 검증(README 검증 표의 행 전부, 마지막 commit 기준)
| 명령 | 결과 |
| --- | --- |
| `tools/project-board/tests` + `tools/agent-session/tests/test_api_boundary.py` | 295 passed (일치 test 86, binary test 15, 전환 일치 test 34 포함). 이 전 실행에서 `test_decision_window_moves_only_between_projects_with_decisions_and_keeps_drafts`가 host load 100 이상에서 한 번 실패했고, 단독 실행과 다음 전체 실행은 통과했습니다 |
| `cargo test --offline --locked`(`tools/project-board/rust`) | 68 passed (golden 화면 25개, 데이터 규칙, ui, tmux option) |
| 네 번째 명령(`integrations/tmux` 외) | 132 passed |
| `install/tests` | 파일별로 병렬 실행: 298 passed, 2 skipped. 새 `test_rust_build.py` 18개(T40 진짜 cargo 포함)와 `tools/test_release_files.py`·`test_distribution_boundary.py` 포함. 마지막 merge는 VERSION과 문서만 바꿨습니다 |
| `tools/agent-session/tests/test_remote.py`(spec.md 변경) | 61 passed |
| `python -m pytest -q tools/tests/perf` | 8 passed (25분). probe 수정 뒤 전체를 다시 돌렸고 이후 perf 파일은 바꾸지 않았습니다 |
| 문서 상대 link | 깨진 link 0 |

마지막 `origin/main` merge(BOARD-022·026, 0.8.1)가 바꾼 것은 tmux_control·tui·test·문서이고 `project-board` test 전체를 그 commit에서 다시 돌렸습니다. 설치기·tmux 통합 test의 입력은 바뀌지 않았습니다(VERSION 값만).

### 여는 시간 A/B (16×16 `bench_env`, `perf_bench`, 번갈아 3회, host load 54~58)
기준 BASE = `origin/main` 트리(0.8.0 + BOARD-023·024. 0.8.1 tag 전이라 그 시점 `origin/main`), 후보 CAND = 이 CR의 binary.
| | BASE (Textual) | CAND (Rust) | 비율 |
| --- | --- | --- | --- |
| sidebar ready(최신 데이터) wall 중앙값 [95% 구간] | 7.99 s [7.04–20.59] | **1.40 s [1.33–1.54]** | 0.18 [0.06–0.22] |

- **1초 이하 계약은 이 load에서 닿지 못했습니다.** BOARD-016의 시제품은 load 30에서 0.48초였고, 이 측정의 host load는 50~60입니다(같은 날 load 90~200에서는 2~8초로 흔들렸습니다). 첫 읽기를 8→32 thread로 늘려 4~8초→2~3.4초(load 90 이상)로 줄였습니다. 더 줄일 수 있는 부분(첫 읽기 NFS 지연)은 host가 조용할 때 다시 재야 합니다. 후보는 같은 load에서 기준의 약 1/6입니다.
- popup ready는 이 CR이 바꾸지 않았고 두 쪽이 같습니다(`same`).
- 측정 중 test를 동시에 돌렸습니다(설치기·project-board test).

### idle CPU (16×16, 열린 뒤 60초, 3회, 값은 Board pane 합계 CPU초)
| | BASE | CAND |
| --- | --- | --- |
| pane 1개 | 5.33 / 4.20 / 5.15 | 1.44 / 1.27 / 1.31 |
| pane 4개 | 8.27 / 7.62 / 4.50 | 1.39 / 1.41 / 1.27 |
0.7.1보다 늘지 않았고 약 1/3~1/5입니다. RSS는 Rust 12.7 MB, Textual 42.7 MB(실제 등록 10개). 갱신 1회 CPU는 0.013~0.015초(Python 0.09).

### 화면 capture (`/primehome/swain/tmp/board018/`)
`{base,cand}-{real,b16}-{plain,hover-tooltip,hover-name,focus,scroll-right}.{txt,ansi}`. `base`는 위 BASE 트리의 Textual sidebar, `cand`는 Rust입니다. `cat 파일.ansi`로 색까지 봅니다. 실제 등록(10개)과 16×16(합성), 25×50.
- 일반·focus·가로 스크롤 화면은 글자가 같습니다(차이는 분 단위 시간 숫자뿐). ANSI도 같습니다. 16×16에서는 비활성 글자색 한 채널이 1 다르고(Textual의 반올림), 스크롤 막대 칸의 보이지 않는 글자색이 다릅니다.
- tooltip 화면: 내용은 같고 상자 모양이 다릅니다. Rust는 pane 폭 안에서 줄을 바꾸고(Textual은 40칸 상자를 만든 뒤 pane 밖을 잘라 냅니다), pointer 아래에 가운데 맞춰 놓습니다. Textual은 pointer가 다른 위젯으로 옮긴 뒤에도 잠시 이전 tooltip을 남기고, Rust는 바로 지웁니다(`hover-name` 화면의 차이).
- 위 차이와 그 밖의 의도한 차이(오류 알림 줄, `ctrl+p` 없음)는 TUI 계획 3절에 적었습니다. 칸 단위 비교는 `rust/tests/golden`의 화면 25개를 0.7.1 Textual로 그려 Rust test가 지킵니다. BOARD-023 모양으로 바뀐 화면은 바뀐 행 말고는 Textual 화면과 같음을 확인하고 다시 그렸습니다.

### 설치
`install/tests`의 T34~T40(격리 HOME): install, upgrade(build 성공), upgrade(build 실패: `current`·설치 기록·기존 release 그대로, 새 release 디렉터리 없음), dry-run은 build하지 않음, cargo·vendored 디렉터리 없음, check가 binary를 확인, 진짜 cargo로 한 번 build(38~50초).

### 범위 추가(Leader 메시지)에 대한 결과
- **tmux 호출 수(BOARD-022)**: 접힘 2초 읽기는 process 하나, liveness 10초 읽기는 둘(서버, run의 option. 명세 5절), 현재 창 하나, 가시성 확인은 명령을 `;`로 묶어 하나(`mark_ready`도 하나)입니다. `test_sidebar_binary.py`가 `tmux` shim으로 20초 동안 호출을 세어 상한을 지킵니다. 전환은 project 2개, seat 3개 process입니다(`test_rust_switch.py`가 Python보다 적음을 단언).
- **클릭 비용(BOARD-022·025)**: project·seat 전환은 Rust가 직접 tmux를 부르고 Python과 같은 결과인지 일치 test가 지킵니다(34개: 정상·원격 seat·오류·client 처리·순서). CR·결정 창 열기와 접기·펴기는 `project-board`를 부르되 시동 번들(`python -S`) 경로입니다(`--config`가 앞에 와도 분기합니다).
- **BOARD-025(떠 있는 창에 socket으로 알리는 경로)는 아직 통합되지 않아 반영하지 못했습니다.** 통합되면 창이 있을 때 sidebar가 그 socket에 직접 보내고 없을 때만 Python 하위 명령을 부르게 `src/app.rs`의 `activate`를 바꾸면 됩니다.
- 이미 계약에 있는 것은 지켰습니다: 첫 그림은 liveness를 기다리지 않음, 바뀐 칸만 그림, `@project_board_managed`는 Python이 붙임, click socket은 떠 있는 CR·결정 창이 열려 있어도 받음(pane 자체가 받습니다).

### 알려진 한계와 가정
- Rust와 Python이 같은 읽기 규칙을 가집니다(제품 지도에 예외 기록). 알려진 미세 차이: `connected_at` 초가 60·61이면 Python은 snapshot 전체가 죽고 Rust는 값을 냅니다. liveness 오류인 project는 Python `{"error":…}`, Rust `{}`입니다. SSH seat의 실행 판정은 `project-board liveness`(Python)에 맡깁니다.
- 첫 snapshot이 오기 전의 pane은 비어 있습니다(Textual은 같은 순간에도 빈 목록).
- 창이 보이지 않는 동안 읽지 않는 규칙은 hook의 SIGUSR1에 달려 있습니다. test는 hook이 하는 것처럼 SIGUSR1을 보냅니다.
- sidebar의 seat 전환은 Python과 같게 `PROJECT_BOARD_SOCKET`(없으면 기본 server)을 씁니다.
- Release 때 해야 할 일: `CHANGELOG.md`의 Unreleased는 Leader가 채웁니다. 형식 버전은 바뀌지 않았습니다. 공개 진입점(`project-board sidebar` 제거)이 바뀌므로 MAJOR가 0인 동안 MINOR로 올리는 변경입니다.

### 수정 제출 (Leader feedback 반영: BOARD-025 연동, 화면 요구, 번호 이동, 재검증)
- 제출 commit: a7b972753cef40d7226a5b5d73990b260dd6f36c

`origin/cr/BOARD-018`에 push했습니다. 마지막 `origin/main`은 ITEM-001·INSTALL-008·TEST-014(`a48d1fe`)까지 merge했습니다. 위 첫 제출(2a79768) 뒤에 한 일입니다.

#### 바꾼 것
- **BOARD-025 연동**(`rust/src/window.rs`, `app.rs`): CR·결정 클릭에서 같은 종류의 창이 떠 있으면 TUI 계획 5절의 순서대로 그 창의 socket에 요청 한 줄(JSON)을 보냅니다. 응답이 ok이면 창 title만 바꾸고 아무것도 시작하지 않습니다. `busy`면 창을 바꾸지 않고 sidebar 아래에 알립니다. 창이 없거나, 종류가 다르거나, `link`가 비어 있거나(시작 중), socket에 연결할 수 없거나, 응답이 JSON 한 줄이 아니거나, `invalid`·`closing`이면 지금처럼 `project-board`(시동 번들)로 창을 엽니다. 클릭 경로의 tmux process는 읽기 하나와 title 설정 하나입니다.
  - test: `window.rs` 단위 test 4개(창 pane 찾기, 응답 판정, 한 줄 요청·응답, socket이 없거나 socket이 아님)와 `test_sidebar_binary.py`의 창 test 9개(같은 종류에 알림, 결정 요청의 `decision: null`, busy, 다른 종류·시작 중·invalid·closing·JSON 아님은 helper로 시작, 죽은 창·창 없음). 가짜 창 process가 raw socket으로 규약대로 응답합니다(BOARD-025의 `test_window_protocol.py`와 같은 기준).
- **화면 요구**: 현재 창의 project 이름 앞 `▶ `를 없앴습니다(강조 색은 그대로, golden 6개를 다시 그렸고 이름 줄 글자 말고는 같음을 확인했습니다). `D:0`을 항상 흐리게 하는 변경은 Leader 정정(사용자: 현재 상태 유지)으로 되돌려 이 제출에는 없습니다(규칙은 이전과 같음).
- **merge가 부른 수정**: BOARD-025 merge에서 내가 `tui.py`의 `import os`를 빠뜨려 창 test 8개가 실패했고, 고쳤습니다. merge 때 지운 Textual sidebar의 `expanded_projects` 등을 쓰는 test는 지우고 BOARD-025·BOARD-022·BOARD-026의 새 test는 살렸습니다.
- **install 시험 번호**: main의 INSTALL-008이 T34·T35(crontab)를 먼저 썼으므로 이 CR의 설치 시험을 T36~T42로 옮겼습니다(설치 계약 8.2절 표·2.1절·8.1절, `release.md`, README의 "T1~T42", `test_rust_build.py`의 함수 이름·머리말).
- **test 시간 여유**: T42(진짜 cargo build)의 설치기 timeout을 1800초로 늘렸습니다(host load 60 이상에서 build가 5~8분 걸려 300초 timeout에 걸렸습니다. 조용한 host에서는 40초). 첫 읽기는 8→32 thread로 올렸습니다(load 90 이상에서 4~8초→2~3.4초).
- sidebar 호출의 tmux process는 `test_sidebar_binary.py`가 shim으로 세는 상한을 지킵니다(위 첫 제출과 같음). `bin/project-board`는 `open-decision`·`open-cr`·`toggle-fold`·`liveness`를 시동 번들로 시작하고, BOARD-025의 `cr|popup` 번들 시작도 살렸습니다.

#### 재실행 결과 (a7b9727, merge 포함, 모두 `run_in_background`)
| 명령 | 결과 |
| --- | --- |
| `install/tests` 전체 (T42 진짜 cargo 포함) | 313 passed, 2 skipped (3시간 29분) |
| `tools/project-board/tests` + `tools/agent-session/tests/test_api_boundary.py` + `test_remote.py` | 389 passed |
| 네 번째 명령(`integrations/tmux` 외) | 141 passed |
| `cargo test --offline --locked` | 72 passed |

#### vi3 실행의 실패와 그 뒤 통과 근거
merge(BOARD-025) 직후 같은 commit 계열을 처음 돌렸을 때 실패가 있었고, 원인과 뒤의 근거는 다음과 같습니다.
- **`tools/project-board/tests` 11건**: 8건은 merge 때 `test_tui.py`의 `click_socket` import, 2건은 같은 merge의 `tui.py`·`test_tui.py` `import os` 누락(내 실수, 코드·test 수정). 나머지 2건(`test_folding...`, `test_every_periodic_read...`)은 test가 host load 100 이상에서 한 번에 10초 안에 끝나지 않은 것과, 내 test harness가 SIGUSR1을 더 보내 tmux 호출 수가 상한을 하나 넘은 것이었습니다(상한과 timeout을 고침). 고친 뒤 위 389 passed입니다.
- **`install/tests`의 `test_principles`(unknown-op, TimeoutExpired)·`test_prune`(T29, T31)**: host load 100~200에서 `git status`가 60초, install이 300초 timeout에 걸린 것이었습니다(출력에 `TimeoutExpired`·`git_unavailable: timed out after 60 seconds`). load 55~85에서 그 test를 단독으로 다시 돌렸을 때 통과했고, 마지막 전체 실행(313 passed)에서도 통과합니다. `test_rust_build`의 T35(rollback)도 같은 이유였고 마지막 실행에서 통과합니다.
- 그 밖에 `test_tui.py`의 결정 창 test 하나가 load 100 이상에서 한 번 실패했고 단독 실행과 이후 전체 실행은 통과했습니다.

#### 근거 재사용·재실행 판정
- 설치기·`tools/project-board`·Rust·문서가 바뀌었으므로 README 검증 표에서 해당 행(`install/**`, `tools/project-board/**`, `tools/project-board/rust/**`, `skills|docs|README`)의 명령을 merge commit에서 모두 다시 실행했습니다. 에이전트 도구(`tools/agent-session/tests` 전체)는 이 CR이 바꾸지 않고 main의 SESSION-015·ITEM-001·TEST-014가 검증했으므로 `test_api_boundary.py`·`test_remote.py`만 다시 돌렸습니다. TEST-014(test run마다 자기 HOME)의 영향은 위 install·project-board·Rust test가 그 상태에서 통과함으로 확인했습니다.
- `tools/tests/perf`는 첫 제출 뒤 바뀌지 않아 이전 결과(8 passed)를 재사용합니다. A/B 여는 시간·idle CPU도 첫 제출의 값을 재사용합니다(이후 바뀐 것은 클릭 경로와 문서·test이고 읽기·그리기 경로는 같습니다).
- 긴 실행을 `nohup`으로 띄워 완료 알림을 못 받아 06시간 멈춘 일이 있었습니다. 이후 모든 긴 실행은 `run_in_background`로 띄웠고, 끝나지 않던 대기 shell(PID 3826158, 3890499)은 PID로 멈췄습니다.
