# BOARD-025: CR·결정 창이 열리고 내용이 보이기까지 느립니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S2

## Symptom
사용자 보고(2026-11-11, 0.8.0): "decision cr 내용 load하는 것도 엄청 느리네."

## Evidence
- `tools/project-board/bin/project-board`는 `sync`·`click`·`toggle`만 시동 번들(`python -S`, bundle)로 실행합니다. CR 창(`cr`)과 결정 창(`popup`)은 `python -m project_board`로 실행해서 site 단계와 Textual import를 NFS에서 읽습니다. BOARD-016 측정에서 popup을 여는 데 16×16에서 1.2초가 걸렸고, Textual을 번들에 넣은 시제품(A7)은 0.81초였습니다.
- BOARD-020: 창이 떠 있을 때 sidebar에서 다른 항목을 누르면 `respawn-pane -k`로 창 process를 새로 시작합니다. 누를 때마다 Python과 Textual 시동을 다시 합니다. BOARD-020 Worker는 test server에서 CR 창이 시작하는 데 약 10초 걸렸다고 적었습니다(host 부하).
- BOARD-021:
  - CR 창은 `popup_snapshot(project_id, done=True)`로 연 project의 CR과 done 목록을 읽습니다.
  - 결정 창은 다른 project의 결정 여부를 background에서 전체 snapshot으로 읽습니다. 실제 등록 10개에서 cold 약 5초 걸리고, 그동안 ◀▶가 꺼져 있습니다.
- 본문은 Textual `Markdown` widget으로 그립니다. 긴 CR(표와 Result가 긴 것)을 그리는 비용은 재지 않았습니다.
- host load는 최근 87~111이었습니다(BOARD-022).

## Contract
1. 창이 이미 떠 있을 때 sidebar에서 다른 CR·결정을 누르거나 창 안에서 항목·project를 바꾸면, 새 내용이 0.5초 안에 보입니다. 측정 조건은 실제 등록과 같은 규모이고, host load를 함께 적습니다.
2. 창을 처음 열 때 목록과 첫 본문이 보이기까지의 시간을 줄입니다. 남는 시간에는 근거가 있어야 하고, 기다리는 동안 무엇을 읽는 중인지 창에 보입니다.
3. 화면 모양과 동작은 0.8.0 이후 통합된 것과 같습니다. 대상은 BOARD-020(떠 있는 창, 위치·크기 유지), BOARD-021(네 묶음, ◀▶), BOARD-024(Ctrl+J)입니다.

## Disposition
- 2026-11-11 Leader: 고친다(Leader 판정). 사용자가 보고한 느림입니다. 먼저 단계를 나눠 원인을 확인하고, 줄일 수 있는 비용을 줄입니다.
- 2026-11-11 Leader 판정(방향): 창이 이미 떠 있으면 process를 새로 띄우지 않고 떠 있는 창에 내용을 바꾸라고 알립니다(Contract 1). 처음 여는 비용은 시동 번들처럼 이미 있는 방식을 먼저 씁니다. 측정 결과가 다른 원인을 가리키면 Result에 근거를 적고 그에 맞게 고칩니다.
- 2026-11-11 Leader: open -> todo. Leader 판정: 사용자 보고 느림

## Implementation
읽을 문서:
- `tools/project-board/bin/project-board`, `tools/python-launcher.sh`, `tools/bundle_boot.py`, `install/project_agent_install/`의 번들 생성
- `tools/project-board/project_board/tmux_control.py`(`_popup`, `_window_command`, `open_popup`, `open_cr_popup`)
- `tui.py`(`CRPopupApp`, `PopupApp`, `run_cr_popup`, `run_popup`), `model.py`(`popup_snapshot`, `snapshot`, `done_items`, `read_cr_markdown`)
- BOARD-016 Result 2절(A7 번들, popup process 재사용 추정), BOARD-020·021 Result
- [설치 계약](../../project-team/install-contract.md), [Board TUI 계획](../../project-board-tui-plan.md), [project-team Worker 절](../../../skills/project-team/SKILL.md)

1. 단계 분해: 실제 등록(읽기만 함)과 test tmux server(`tools/tests/tmux_test_server.py`의 claim·release)에서 다음을 잽니다. 반복 3회이고 load를 함께 적습니다.
   - 경우: 처음 열기(CR, 결정), 창이 떠 있을 때 sidebar에서 다른 항목, 창 안 항목 바꾸기, ◀▶
   - 단계: 클릭에서 pane 생성, Python과 Textual 시동, 목록 읽기, 첫 그림, 본문 읽기, Markdown 그림
2. 원인을 Result에 적고 고칩니다. 후보:
   - 떠 있는 창 process에 새 내용을 알리는 경로(click socket과 같은 방식). `respawn-pane`은 창이 죽었을 때만 씁니다.
   - `cr`·`popup`의 시동 번들. 설치 계약과 release 검증에 미치는 영향을 적습니다.
   - 본문 읽기와 그리기 줄이기
   - 결정 창 ◀▶용 전체 snapshot 비용 줄이기
3. 기다리는 동안 창에 "읽는 중" 상태를 보입니다(Contract 2).
4. Test: Contract 1의 경로(떠 있는 창 재사용, 창이 죽었을 때 새로 띄우기)와 Contract 3의 동작 유지를 확인합니다.

의존: 없음.
- BOARD-022가 `tmux_control.py`를 고치고 있고 곧 통합됩니다. BOARD-018이 sidebar를 Rust로 옮기는 중입니다(popup은 Python으로 남음).
- 제출 전에 `origin/main`을 merge합니다.

위험 등급: 중간.

## Verification
1. README 검증 표에서 바꾼 경로의 행 명령 전부를 실행합니다. `tools/project-board/**`, `install/**`(번들을 바꾸면), `tools/python-launcher.sh`·`tools/bundle_boot.py`(바꾸면) 행입니다.
2. A/B: 0.8.0과 이 CR로 Contract 1의 대표 경우(창이 떠 있을 때 다른 항목)와 처음 열기(CR 창)를 번갈아 3회 잽니다. wall과 95% 구간을 적습니다. test는 측정과 동시에 돌립니다.
