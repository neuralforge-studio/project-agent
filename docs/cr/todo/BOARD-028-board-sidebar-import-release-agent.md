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
결정 D-20261112-01(decided C)로 정한 계약입니다. agent가 쓴 요청 원문은 아래 "요청 원문"에 그대로 둡니다.

1. **자동 전환**: sidebar는 자기 release와 설치본 `current`의 release가 다르면, 같은 pane에서 새 release의 sidebar binary로 자기를 바꿔 실행합니다. pane과 그 크기·위치는 그대로이고 화면 배치가 바뀌지 않습니다. 접힘 상태처럼 tmux option에 있는 상태도 그대로 이어집니다. click socket, SIGUSR1, `mark_ready` 규약은 새 process에서도 같습니다.
2. **전환하지 못할 때**: 새 binary가 없거나, 실행할 수 없거나, 실행에 실패하면 옛 코드로 계속 그립니다. 그리고 "재시작 필요", 이유, 다시 켜는 방법(prefix `B` 두 번 등)을 보입니다. release가 같으면 아무것도 보이지 않습니다.
3. **release를 판단하는 원본은 하나**: 비교는 설치본의 release 식별 하나로 합니다(release 디렉터리, 그 안의 `VERSION`과 commit). 이 원본이 무엇인지 설치 계약에 적습니다.
   - binary의 `--version`은 지금 release(0.11.0)가 아니라 crate 버전(0.1.0)을 냅니다. release와 다른 버전 값이 따로 있으면 정리합니다.
   - `current` 밖에서 실행한 sidebar(개발 checkout)는 전환하지 않습니다.
4. **감지 비용**: 지금의 주기 읽기에 process를 더하지 않습니다. 첫 그림의 시간도 늘지 않습니다.
5. **떠 있는 Board 창**: CR·결정·cron 창(Python, BOARD-025 재사용)도 오래 떠 있으므로 같은 원인을 가집니다. release가 다른 창은 클릭 때 재사용하지 않고 새 release로 다시 시작합니다. 전환한 sidebar가 여는 창과 popup은 새 release의 `project-board`로 열립니다.
6. 설치기의 안내("Runs that are up keep the release they started with. Reopen Project Board to use the new release."), TUI 계획, 설치 계약의 관련 문장을 새 동작에 맞게 고칩니다. run이 시작한 release를 고정하는 정책은 바꾸지 않습니다. sidebar와 창은 run이 아니라는 점을 명세에 적습니다.

### 요청 원문
- 요청: sidebar가 자기 코드의 release와 현재 설치본 `current`의 release가 다르면 "재시작 필요"를 보입니다. 다시 켜는 방법(prefix `B` 두 번 등)도 함께 보입니다. 같으면 아무것도 보이지 않습니다.
- 자동 재시작은 요청하지 않습니다. 화면 배치가 바뀌므로 다시 켜는 것은 사람이 합니다.
- release를 비교하는 원본은 설치본의 release 식별(VERSION·release 디렉터리) 하나를 씁니다. run마다 release를 고정하는 정책과 이 표시가 어떤 관계인지(sidebar는 run이 아님)는 담당 project가 정합니다.
- 형식·문구·version은 담당 project가 정합니다.

## Disposition
- 2026-11-12 Leader: 설계 선택(표시만, 같은 pane 자동 전환, 둘 다)이 요청한 project의 계약을 바꾸므로 결정 항목 D-20261112-01로 사용자에게 묻습니다. BOARD-027·TMUX-004가 Rust sidebar를 고치는 중이라 그 뒤에 시작합니다.
- 2026-11-12 Leader: 결정 D-20261112-01 decided C. 사용자 답변 원문: "C". 선택지 C는 "자동으로 전환하고, 전환할 수 없을 때(새 binary가 없거나 실행 실패)만 '재시작 필요'와 이유를 보입니다"입니다.
  - 요청서가 자동 재시작을 꺼린 이유(화면 배치 변경)는 같은 pane 안의 전환에는 해당하지 않습니다.
  - 근거는 사용자 지시 "판단의 주요관점은 ** Root cause & SSOT **"입니다. 원인(upgrade 뒤에도 옛 코드가 돎)을 없애는 쪽을 택했습니다. Contract를 이 결정대로 고쳤습니다.
  - BOARD-027·TMUX-004가 Rust sidebar와 창을 고치고 있습니다. 둘 중 먼저 끝나는 seat에서 시작하고, 시작 시점의 `origin/main`을 기준으로 합니다.
- 2026-11-12 Leader: open -> todo.

## Implementation
읽을 문서:
- [Board TUI 계획](../../project-board-tui-plan.md)(sidebar 실행, 5절 창 재사용).
- [설치 계약](../../project-team/install-contract.md)(release 디렉터리, `current`, 2.1절 Rust build).
- [동작 명세](../../project-team/spec.md)(run의 release 고정).
- [제품 지도](../../project-team/README.md)의 중복 예외.
- 코드: `tools/project-board/project_board/tmux_control.py`(`sidebar_binary`, `_reuse`), `tools/project-board/rust/src/`(`app.rs`, `window.rs`), `install/project_agent_install/`.
- 절차: [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. release 식별의 원본을 정하고, sidebar(Rust)와 창(Python)이 같은 방법으로 읽게 합니다. Rust와 Python이 같은 규칙을 가지면 중복 예외 표와 일치 test로 지킵니다.
2. sidebar: 주기 읽기 안에서 `current`가 가리키는 release를 확인하고, 다르면 새 binary로 같은 pane에서 바꿔 실행합니다. 실패하면 알림 줄에 "재시작 필요"를 보입니다.
3. 창: 재사용 전에 창의 release를 확인하고, 다르면 새로 시작합니다.
4. binary `--version`과 release 버전을 정리합니다.
5. 문서(Contract 6).
6. Test(관측 동작):
   - 격리 HOME과 두 release를 만들고, `current`를 바꾼 뒤 sidebar가 같은 pane에서 새 binary로 바뀌는지(pane id·크기 그대로, 새 binary의 release) 확인합니다.
   - 새 binary가 없거나 실행할 수 없을 때 알림이 나오는지 확인합니다.
   - release가 다른 창은 재사용하지 않는지 확인합니다.
   - 같은 release에서는 아무 일도 없는지 확인합니다.

위험 등급: 중간(실행 중인 sidebar의 교체, 설치기 안내).

## Verification
- README 검증 표에서 바꾼 경로의 행 명령을 모두 제출 commit에서 실행합니다.
  - `tools/project-board/rust/**`: `(cd tools/project-board/rust && cargo test --offline --locked)`, `python -m pytest -q tools/project-board/tests`, 네 번째 명령.
  - `tools/project-board/**`: `python -m pytest -q tools/project-board/tests`, `python -m pytest -q tools/agent-session/tests/test_api_boundary.py`.
  - `install/**`를 바꾸면 `python -m pytest -q -n 8 install/tests`도 실행합니다.
  - 문서: 고친 문서의 상대 link 검사, `python -m pytest -q tools/test_distribution_boundary.py`. `docs/project-team/spec.md`를 바꾸면 `python -m pytest -q tools/agent-session/tests/test_remote.py`도 실행합니다.
- 화면: 격리 server에서 전환 전과 후의 sidebar를 `tmux capture-pane -p -e`로 `/primehome/swain/tmp/board028/`에 저장하고 Result에 적습니다. 실패 알림 화면도 함께 저장합니다.
