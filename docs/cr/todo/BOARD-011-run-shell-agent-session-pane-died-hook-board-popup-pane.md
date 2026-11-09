# BOARD-011: 통합 파일 밖의 제품 run-shell(agent-session의 pane-died hook, Board popup)도 실패하면 작업 pane에 결과가 보입니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S3

## Symptom
BOARD-010은 tmux 통합 파일의 `run-shell` 작업을 모두 `project_agent_run.sh`로 감싸 작업 pane에 출력·종료 상태가 보이지 않게 했습니다. 같은 원인의 `run-shell`이 통합 파일 밖의 제품 코드에 두 곳 남아 있습니다. 실패하면 활성 작업 pane에 `'…' returned N`이 view-mode로 보일 수 있습니다.

## Evidence
- BOARD-010 Result(2026-11-10) 범위 밖 관찰: `tools/agent-session/agent_session/tmux.py`의 `install_exit_hook`(`pane-died[agent-session]`)은 shell 쪽에서 `>/dev/null 2>&1`만 하고 종료 상태를 버리지 않음. `tools/project-board/project_board/tmux_control.py`의 Board popup은 `display-popup -E`를 `run-shell -b`로 실행.
- 계약 5.3절의 `run-shell` 규칙 표(BOARD-010)는 새 `run-shell`이 세 방식 중 하나를 고르도록 정함.

## Contract
- Board·agent-session이 사용자 tmux server에 남기는 `run-shell` 작업은 사용자의 작업 pane에 출력·종료 상태를 남기지 않습니다(계약 5.3절 규칙).

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). BOARD-006·010과 같은 원인의 결함이며 근거가 있으므로 위임 범위입니다. 이 CR로 이 결함 종류를 제품 전체에서 닫습니다.

## Implementation
1. 두 곳을 계약 5.3절 규칙에 맞춥니다: agent-session의 `pane-died[agent-session]`(자동 이벤트 → `hook` 방식), Board popup(사람이 연 것 → 실패를 작업 pane을 덮지 않고 알림). 통합 파일의 `project_agent_run.sh`를 쓸 수 없는 경로(원격 bundle, 통합 파일이 없는 tree)면 같은 규칙을 그 도구 안에서 지킵니다.
2. 제품 코드 전체(`tools/**`, `integrations/**`)에서 `run-shell`을 만드는 곳을 찾아 모두 규칙을 따르는지 검사하는 test를 둡니다(BOARD-010의 통합 파일 검사를 제품 코드로 넓힘).

의존: 선행 BOARD-010(done).

위험 등급: 낮음.

## Verification
README 검증 표의 `tools/agent-session/**`(전체)·`tools/project-board/**`·`integrations/tmux/**` 행.
1. 수정 전: 실패하는 가짜 명령으로 두 경로를 실행하면 활성 pane이 view-mode.
2. 수정 뒤: 활성 pane에 아무것도 남지 않고 규칙대로 기록·알림.
3. 제품 코드의 모든 `run-shell`을 검사하는 test 통과.
