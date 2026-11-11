# BOARD-022: Board를 끄고 켜는 데 오래 걸립니다. 단계별 원인을 나눠 줄이고, 남는 시간은 진행 상태로 보입니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S2

## Symptom
사용자 보고(2026-11-11, 0.8.0 설치 뒤): "board를 겄다가 켜보았어? 끄는데, 켜는데 굉장히 오랜 시간이 걸리긴 하는데... 이게 맞아? 원인을 알려주면 좋겠네. 끄는데, 켜는데 오래걸려야할 이유가 명확하고 해결이 불가능하다면, status? 어떤 상태인지 얼마나 남았는지 등을 표시해주면 좋겠네."

## Evidence
- 켜기·끄기 경로(설치본 0.8.0)에서 확인한 사실:
  - `prefix B`가 `run-shell -b`로 `project_agent_run.sh key … tmux_project_board.sh toggle`을 부릅니다.
  - Python `project-board toggle`이 `tmux_control.toggle_sidebar`를 실행합니다. Board 잠금(`_locked`) 안에서 `@project_board_enabled`를 바꾸고 `_reconcile`을 부릅니다.
  - `_reconcile`은 window마다 tmux 명령을 따로 실행합니다.
    - 끌 때는 유지하던 Board pane(최대 8개, `MAX_KEPT`)마다 `display-message`, `resize-pane`, `_remove`(kill-pane과 `_restore`의 layout 복원)를 합니다.
    - 켤 때는 보이는 window마다 `_create`로 pane을 만들고, 그 pane에서 Board TUI가 시작합니다.
  - 켠 뒤 화면이 그려지기까지는 Board TUI 시동(Textual import와 첫 snapshot, 16×16에서 약 2.8초)이 더해집니다(BOARD-016). 이 부분은 BOARD-018(Rust sidebar)이 줄이고 있습니다.
  - 이 밖에 window 전환 hook이 부르는 sync, 잠금 대기, tmux 명령 하나의 비용(host load가 높을 때)은 재지 않았습니다.
- 이 workstation의 tmux server에는 session 10여 개와 window 수십 개가 있습니다.
- 가설(미확인): 끄기는 Board pane마다 차례로 실행하는 tmux 명령과 layout 복원이, 켜기는 Python 시동, pane 생성, TUI 시동이 대부분입니다.

## Contract
1. 끄기: `prefix B`를 누른 뒤 모든 window에서 Board pane이 사라지기까지의 시간을 줄입니다. 남는 시간에는 근거가 있어야 합니다.
2. 켜기: `prefix B`를 누른 뒤 보이는 window에 Board pane이 생기기까지의 시간을 줄입니다. TUI가 그려지기까지는 BOARD-018의 몫으로 나눠 적습니다.
3. 남는 시간이 사용자가 기다림을 느낄 만큼 길면(약 0.5초 넘게), 누른 client에 진행 상태를 보입니다. 예: 상태 줄이나 `display-message`의 "Board 끄는 중 3/8". 끝나면 사라집니다.
4. 결과(어떤 window에 Board가 있는지, 폭, layout 복원, 떠 있는 Board 창 보존)는 지금과 같습니다.

## Disposition
- 2026-11-11 Leader: 고친다(Leader 판정). 사용자가 보고한 느림이고, 원인 설명과 진행 표시를 요청받았습니다. 줄일 수 있는 비용은 줄이고, 남는 비용은 진행 상태로 보입니다.
- 2026-11-11 Leader: open -> todo. Leader 판정: 사용자 보고 느림

## Implementation
읽을 문서: `tools/project-board/project_board/tmux_control.py`(`toggle_sidebar`, `_reconcile`, `_create`, `_remove`, `_restore`, `_evict`, `_locked`), `integrations/tmux/`(`project_agent_bind.sh`, `project_agent_run.sh`, `tmux_project_board.sh`, `project-agent-main.conf`의 hook), `tools/bundle_boot.py`, [Board TUI 계획](../../project-board-tui-plan.md), BOARD-016 Result(단계 분해 방법), [설치 계약](../../project-team/install-contract.md) 5.3절, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 단계 분해: 다음 단계마다 wall 시간을 잽니다. 반복 3회이고 host load를 함께 적습니다.
   - 단계: key → run-shell 시작, shell 진입점, Python 시동, 잠금 대기, `_snapshot`, window별 tmux 명령(개수와 합계), layout 복원, pane 생성, hook이 부르는 sync, TUI 첫 그림
   - 환경 두 가지: test tmux server(`tools/tests/tmux_test_server.py`의 claim·release)와, 이 workstation과 비슷한 규모(session 10개, window 40개, client 1~2개, Board 유지 8개)
   - 사용자의 실제 tmux server에서는 켜고 끄지 않습니다.
2. 원인을 Result에 적습니다. 줄일 수 있는 것을 고칩니다. 예: tmux 명령을 묶기, 한 번에 보내기, 불필요한 조회 없애기, 잠금 경합 없애기, hook이 부르는 중복 sync 없애기.
3. 남는 시간이 Contract 3에 해당하면 진행 상태를 보입니다. 사용자의 status 설정은 바꾸지 않는 방법(예: `display-message -c <client>`)을 고릅니다.
4. Test: 진행 상태 표시, 결과 동일성(Contract 4), 줄인 명령 수(예: tmux 호출 수를 세는 test)를 둡니다.

의존: 없음. BOARD-018이 `tmux_control.py`의 sidebar 실행 명령을 바꾸고 있으니 제출 전에 `origin/main`을 merge합니다.

위험 등급: 중간. 모든 window의 Board pane 생성과 제거에 닿습니다.

## Verification
1. README 검증 표에서 바꾼 경로의 행 명령 전부를 실행합니다. `tools/project-board/**` 행이고, `integrations/tmux/**`를 바꾸면 그 행도 실행합니다.
2. 끄기와 켜기(pane 생성까지)의 A/B를 0.8.0과 이 CR로 번갈아 3회 잽니다. 위의 workstation 규모 환경이고, wall과 95% 구간을 적습니다. test는 측정과 동시에 돌립니다.
