# BOARD-010: 통합 파일의 다른 run-shell(toggle 키, 창 이동 hook)도 실패하면 사용자 작업 pane에 오류를 띄웁니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Base: 3581f1fc9fad89cb02768dfab072e6de4597d52a 2026-11-10T00:34:22+09:00

## Symptom
tmux `run-shell`은 실행한 명령의 출력과 0이 아닌 종료 상태를 그때의 활성 pane에 view-mode로 보입니다. BOARD-006은 Board click 경로만 고쳤습니다. 통합 파일의 다른 `run-shell`(prefix Board 키 toggle, status line toggle, 창 이동·client 이벤트 hook의 `sync`·visibility script)도 실패하면 사용자의 작업 pane에 오류가 덮입니다. hook은 창을 옮길 때마다 돌기 때문에 실패가 반복되면 작업 pane을 계속 가립니다.

## Evidence
- BOARD-006 Result(2026-11-10, `docs/cr/done/BOARD-006-sidebar-click-pane.md`) "범위 밖 관찰": prefix `B`·status line의 `Board` toggle 등 다른 `run-shell` binding도 실패하면 같은 방식으로 활성 pane에 출력될 수 있음.
- `integrations/tmux/project-agent-main.conf`의 hook과 `project_agent_bind.sh`의 binding이 `run-shell -b`로 helper를 부름.

## Contract
- Board 통합은 사용자의 작업 pane에 출력·입력을 남기지 않아야 합니다(BOARD-006 Contract와 같은 원칙). 사용자가 직접 누른 동작(toggle)이 실패하면 사용자가 알 수 있어야 하지만, 작업 pane을 가리지 않는 방식이어야 합니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). BOARD-006과 같은 원인의 결함이며 근거가 있으므로 위임 범위입니다.

## Implementation
읽을 문서: [설치 계약](../../project-team/install-contract.md) 3.1·5.3절, `integrations/tmux/project-agent.conf`·`project-agent-main.conf`·`project_agent_bind.sh`, BOARD-006 Result, [README 검증 표](../../../README.md#검증).

1. 통합 파일과 helper가 `run-shell`로 부르는 명령을 모두 나열하고, 사람이 누른 것(toggle)과 자동 이벤트(hook)로 나눕니다.
2. 자동 이벤트: 출력과 종료 상태를 활성 pane에 보이지 않습니다. 실패는 사용자가 나중에 볼 수 있는 한 곳(예: Board의 오류 표시 또는 정해진 log 파일)에 남깁니다. 위치를 계약 5.3절에 적습니다.
3. 사람이 누른 것: 실패하면 작업 pane을 덮지 않는 방식(예: `display-message`)으로 짧게 알립니다.
4. 규칙을 계약 3.1절 또는 5.3절에 한 번 적고, 새 `run-shell`을 더할 때 따르게 합니다(test로 확인: 모든 `run-shell`이 규칙대로인지).

의존: 선행 BOARD-006(done).

위험 등급: 낮음.

## Verification
README 검증 표의 `integrations/tmux/**` 행.
1. 재현(수정 전): 실패하는 가짜 helper로 toggle과 hook을 실행하면 활성 pane이 view-mode가 됨.
2. 수정 뒤: hook 실패는 활성 pane에 아무것도 남기지 않고 정해진 곳에 기록됨, toggle 실패는 `display-message`로만 알림.
3. 통합 파일의 모든 `run-shell`이 규칙을 따르는지 검사하는 test.
