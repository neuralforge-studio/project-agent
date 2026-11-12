# BOARD-028: Board sidebar가 자기가 import한 release와 현재 설치본이 다르면 재시작이 필요하다고 표시합니다(agent 요청)

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S3
- Requester: agent, /primehome/swain/Utils/agent/agent.base, 2026-11-12

## Symptom
Board sidebar process는 시작할 때 import한 코드를 계속 씁니다. 설치본(`~/.local/lib/project-agent/current`)이 새 release로 바뀌어도 이미 떠 있는 sidebar는 옛 코드로 판정하고 표시합니다. 지금은 사람이 기억해서 Board를 끄고 다시 켭니다(agent Leader 메모리 `restart-board-after-tool-merge`). 옛 Board가 옛 검사로 잘못된 상태를 보인 적이 있습니다.

## Evidence
- 2026-11-06: 오래 떠 있던 옛 Board가 옛 검사로 `registry_invalid`를 표시했습니다(agent SESSION-013 통합 뒤).
- 2026-11-09: 새 Board 코드가 들어온 뒤에도 11-07에 띄운 옛 Board가 계속 돌았습니다.
- 2026-11-12 기준 `current`는 `releases/0.10.0-e0eb77d100fd`입니다. 실행 중 run은 0.7.0·0.10.0 등 서로 다른 release를 고정해 씁니다. agent TEAM-005 Result 3절 R14가 이 항목을 도구 쪽 후보로 골랐습니다(`/primehome/swain/Utils/agent/agent.base/docs/cr/open/TEAM-005-project-team-project-item-hook-mod.md`).

## Contract
- 요청: sidebar가 자기 코드의 release와 현재 설치본 `current`의 release가 다르면 "재시작 필요"를 보입니다. 다시 켜는 방법(prefix `B` 두 번 등)도 함께 보입니다. 같으면 아무것도 보이지 않습니다.
- 자동 재시작은 요청하지 않습니다. 화면 배치가 바뀌므로 다시 켜는 것은 사람이 합니다.
- release를 비교하는 원본은 설치본의 release 식별(VERSION·release 디렉터리) 하나를 씁니다. run마다 release를 고정하는 정책과 이 표시가 어떤 관계인지(sidebar는 run이 아님)는 담당 project가 정합니다.
- 형식·문구·version은 담당 project가 정합니다.

## Disposition
- 2026-11-12 Leader: 설계 선택(표시만, 같은 pane 자동 전환, 둘 다)이 요청한 project의 계약을 바꾸므로 결정 항목 D-20261112-01로 사용자에게 묻습니다. BOARD-027·TMUX-004가 Rust sidebar를 고치는 중이라 그 뒤에 시작합니다.
