# BOARD-002: Board 전체 동작이 매우 느립니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2

## Symptom
사용자 보고: "전체적으로 굉장히 큰 문제는 엄청 느림." sidebar 표시, 창 이동 뒤 갱신, popup 열기가 느립니다.
출처: 사용자 개선 요청 2026-11-09(대화, 11개 항목 중 5번).

## Evidence
- tmux hook(`client-attached`, `session-window-changed`, `window-created` 등 8개, `integrations/tmux/project-agent-main.conf`)이 일어날 때마다 `run-shell -b … tmux_project_board.sh sync`로 bash → launcher → Python process를 새로 띄웁니다.
- TEST-003 측정(2026-11-09): 이 host에서 Python import 하나가 0.66~3.85초로 흔들립니다(NFS, CPU 경쟁).
- 측정값은 아직 없습니다. 어느 단계가 시간을 쓰는지는 미확인입니다.

## Contract
- Board는 사용자의 tmux 조작에 바로 반응해야 합니다([TUI 계획](../../project-board-tui-plan.md)). RUST-001(Rust 전환)의 범위는 이 측정을 근거로 정합니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정, 측정으로 원인 확정 뒤 수정). 사용자가 "굉장히 큰 문제"라고 한 동작 결함이고 위임 범위입니다. 같은 원인일 수 있는 BOARD-003·004는 이 CR의 원인 확정 뒤 판정합니다(같으면 병합). 사용자 지시(2026-11-09 대화): "위와 같이 11개의 개선 요청 사항이 있어."

## Implementation
읽을 문서: [project-board README](../../../tools/project-board/README.md), [TUI 계획](../../project-board-tui-plan.md), [설치 계약 5.3·5.4절](../../project-team/install-contract.md), [README 검증 표](../../../README.md#검증).

1. 측정: sidebar 첫 표시, 창 이동 뒤 sidebar 갱신, hook 하나의 `sync`, popup 열기, click 처리 각각의 걸린 시간을 단계별(bash·launcher·Python 기동·import·registry·state·CR 목록 읽기·tmux 명령·화면 그리기)로 잽니다. 이 host의 평소 부하에서 각 10회 이상, 분포(중앙값·최대)를 Result에 표로 적습니다.
2. 원인 확정: 시간을 가장 많이 쓰는 단계와 그 이유를 근거(`path:line`, 측정값)로 적습니다. 예를 들어 hook마다 Python을 새로 띄우는 구조, 갱신마다 모든 project의 파일을 다시 읽는 구조, 중복 실행되는 sync 같은 가설을 측정으로 확인하거나 기각합니다.
3. 고침: 확정한 원인을 Python 구현 안에서 구조적으로 고칩니다. 예: 오래 사는 process 하나가 tmux 이벤트를 받아 처리하고 hook은 알림만 보냄, 바뀐 것만 다시 읽음, 겹친 sync를 하나로 합침. 숫자 한도나 sleep으로 가리지 않습니다. 고친 구조는 [TUI 계획](../../project-board-tui-plan.md)과 설치 계약 5.3절(server에 남기는 것)에 먼저 적습니다.
4. 언어를 바꾸지 않고는 줄일 수 없는 비용(예: Python 기동 자체)이 남으면 그 값을 RUST-001의 근거로 Result에 따로 적습니다.

의존: 선행 없음. 후행 BOARD-003·004 판정, 다른 Board CR(같은 파일).

위험 등급: 중간. 사용자 tmux에서 늘 도는 경로입니다.

## Verification
1. 수정 전 측정 표(1단계)와 원인 근거.
2. 수정 뒤 같은 조건의 측정 표. 사용자가 느끼는 동작(sidebar 첫 표시, 창 이동 뒤 갱신, popup 열기)의 중앙값과 최대값이 얼마나 줄었는지 적습니다.
3. README 검증 표의 `tools/project-board/**` 행, 바꾼 경로에 `integrations/tmux/**`가 있으면 그 행.
