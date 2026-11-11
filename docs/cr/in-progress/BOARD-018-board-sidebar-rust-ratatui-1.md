# BOARD-018: Board sidebar를 Rust(ratatui)로 옮겨 최신 데이터로 1초 안에 엽니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S2

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
