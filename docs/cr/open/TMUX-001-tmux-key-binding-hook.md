# TMUX-001: tmux 통합 파일을 설치본 기준으로 만들고, 사용자 key binding과 hook을 덮어쓰지 않게 합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Requester: agent, /primehome/swain/Utils/agent/agent.base, 2026-11-09

## Symptom
Board의 tmux 연결은 agent 저장소의 개인 tmux 설정 경로를 전제로 합니다(`~/.tmux/scripts/tmux_project_board.sh`, 저장소 상대 경로로 project-item 찾기). 사용자가 이미 지정한 `prefix B`와 root `MouseDown1Pane` binding을 말없이 덮어쓰고, hook 배열 이름도 일반 이름(`[board]`)이라 사용자 hook과 겹칠 수 있습니다. 설치본만 있는 환경에서는 동작하지 않거나 다른 설정에 영향을 줍니다.

## Evidence
- `tmux/scripts/project_board.conf:3-32`: binding과 `[board]` hook
- `tmux/scripts/tmux_project_board.sh:6`: 저장소 상대 경로로 `project-board`를 실행
- `tmux/scripts/tmux_decide_status.py:46`: 저장소 상대 경로로 project-item을 찾음
- 설치 계약 3절(include 블록, 대상 파일 규칙), 3.1절(binding 규칙: 비어 있거나 tmux 기본값일 때만, `@project_agent_board_key`, `check`의 "binding 건너뜀", 제거 때의 되돌림 명령), 5.3절(tmux server에 남기는 것), 8절 T20·T21
- tmux 3.8의 기본값: `prefix B` binding 없음, `MouseDown1Pane`은 `select-pane -t = \; send-keys -M`(agent DIST-002 Result)
- agent DIST-001: hook 배열 이름을 제품 전용 이름으로 바꾸기로 했습니다.

## Contract
- 사용자 결정(agent D-20261109-08 C, -09 C): 설치가 고치는 기존 파일은 tmux 설정의 include 블록 한 줄뿐입니다. 사용자 key binding과 hook을 덮어쓰지 않습니다.
- 통합 파일과 helper는 `~/.local/lib/project-agent/current` 아래 설치본 경로로 동작하고, 개발 checkout에서도 test할 수 있어야 합니다.
- 사용자 status layout(`project_board_home_status.conf` 같은 것)은 제품이 아니라 각자의 설정이 소유합니다.

## Disposition
- 2026-11-09 Leader: 판정 보류(open 유지). REPO-001이 저장소 배치를 바꾸는 중이므로, 그 통합 뒤의 경로로 Implementation·Verification을 써서 판정합니다. 판정에 필요한 입력은 REPO-001이 통합한 배치입니다. 순서는 사용자가 2026-11-09 대화에서 지시했습니다. 사용자 원문: "제안 진행 순서대로 진행".
