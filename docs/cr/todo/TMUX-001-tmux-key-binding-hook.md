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
- 2026-11-09 Leader: 고친다(Leader 판정). REPO-001이 1e06cac로 통합되어 판정 입력이 갖춰졌습니다. 이 CR은 agent의 승인한 계획 DIST-001 5단계입니다. 목표 동작은 설치 계약 3.1절과 5.3절이 이미 정했습니다. 사용자 binding을 덮어쓰는 현재 동작은 그 계약의 위반입니다. 따라서 위임 범위(승인한 작업의 하위 작업, 근거가 있는 결함 수정)입니다. 2026-11-09 격리 tmux 3.8 server에서 확인: `set-hook -g 'client-attached[board]' …`는 숫자 index가 아닌 이름 `[board]`로 저장되고, `[0]`·`[7]`과 따로 남습니다. 그러므로 이름만 제품 전용으로 바꾸면 사용자 hook과 겹치지 않습니다. REPO-001 review에서 넘긴 문서 정정 두 가지를 이 CR에 넣습니다.

## Implementation
읽을 문서: [설치 계약](../../project-team/install-contract.md) 2절(`tmux.conf` 행), 3절, 3.1절, 5.3절, 8절 T20·T21. [project-board README](../../../tools/project-board/README.md). 이 CR의 Contract가 범위의 원본입니다.

1. 통합 파일 이름을 계약의 이름으로 바꿉니다: `integrations/tmux/project_board.conf` → `integrations/tmux/project-agent.conf`(`git mv`). 설치 계약 2절이 `current/integrations/tmux/project-agent.conf`를 읽습니다.
2. helper 경로를 개인 경로(`~/.tmux/scripts/…`)에서 통합 파일 자신의 디렉터리 기준으로 바꿉니다. 같은 파일이 개발 checkout과 `~/.local/lib/project-agent/current/integrations/tmux/`에서 모두 동작해야 합니다. 예를 들어 읽힐 때 `#{d:current_file}`를 server option에 `-F`로 고정하고 binding·hook이 그 option을 씁니다. 설치본에서는 `current` link를 풀지 않은 경로를 써서 upgrade 뒤 다음 호출부터 새 release를 씁니다.
3. 3.1절 규칙 1·2를 구현합니다.
   - Board 키는 `@project_agent_board_key`가 있으면 그 값, 없으면 `B`입니다.
   - prefix의 Board 키와 root `MouseDown1Pane`은 binding이 없거나 tmux 기본값(`MouseDown1Pane`: `select-pane -t = \; send-keys -M`)일 때만 binding합니다. 판정은 읽을 때 `tmux list-keys`로 합니다. tmux 설정 문법만으로 판정할 수 없으면 helper script 하나를 둡니다.
   - 제품이 이미 넣은 binding은 사용자 binding으로 보지 않습니다. 같은 파일을 다시 읽어도 결과가 같아야 합니다.
   - 건너뛴 키를 server option 하나(이름은 구현이 정하고 계약 3.1절에 적습니다)에 남깁니다. INSTALL-001의 `check`가 이 option으로 "binding 건너뜀"을 알립니다.
4. hook 배열 이름 `[board]`를 제품 전용 이름(예: `[project-agent]`)으로 바꿉니다. 다시 읽으면 같은 이름의 항목만 바뀌고 사용자 hook은 그대로입니다.
5. 결정 대기 표시: 사용자 status 배치는 제품이 넣지 않습니다(계약 5.3절). 대신 사용자가 경로를 몰라도 status에 넣을 수 있는 진입점 하나를 통합 파일이 제공합니다. 예: `tmux_decide_status.py`를 부르는 `#()` 조각을 담은 server option. 그 이름과 사용자가 쓸 한 줄을 계약 5.3절에 적습니다. RELEASE-001의 안내문이 이를 link합니다.
6. 통합 파일이 넣는 binding·hook·server option의 목록을 계약 한 곳(5.3절 표)에 둡니다. INSTALL-001의 `uninstall` 되돌림 명령(3.1절 규칙 4)이 이 목록을 씁니다.
7. 문서를 고칩니다.
   - 계약 5.3절: 통합 파일 행의 이름·hook 이름·개수를 실제와 맞춥니다(지금 문장은 "9개"이지만 이름은 8개입니다).
   - 계약 5.3절 끝 문장: `project_board_home_status.conf`는 각 사용자의 tmux 설정 파일이며 제품에 넣지 않습니다. "TMUX-001이 정합니다"를 이 사실로 바꿉니다.
   - [제품 지도](../../project-team/README.md)의 "tmux 연결" 행: 이 저장소에 없는 `project_board_home_status.conf`를 목록에서 뺍니다. 실행 경로 계약 6항을 새 이름에 맞춥니다.
   - `tools/project-board/README.md`의 `~/.tmux/scripts` 안내를 새 진입 방식으로 바꿉니다.
8. `tools/test_distribution_boundary.py`의 `PRODUCT_PATHS`에 `integrations/tmux`를 더합니다. 통합 파일도 이제 배포되는 제품입니다.

범위 밖: 설치기와 사용자 tmux 설정의 include 블록(INSTALL-001). 설치본에서 release의 `bin/` 진입점이 shim 없이 설치 interpreter와 release package 경로로 실행되는 방식(계약 6.1절, INSTALL-001). tmux helper는 release 안의 상대 경로로 `tools/project-board/bin/project-board`를 부르므로, 그 실행 환경은 INSTALL-001이 맞춥니다. 이 workstation의 전환(agent DIST-001 6단계).

의존: 선행 REPO-001(done). 후행 INSTALL-001(통합 파일 이름, binding·hook 목록, 건너뜀 option, 결정 표시 진입점을 씁니다), RELEASE-001(안내문).

위험 등급: 중간. 통합 파일을 읽는 사용자의 tmux 조작에 영향을 줍니다. 이 workstation은 6단계 전까지 agent 저장소의 통합 파일을 읽으므로 지금 운영에는 영향이 없습니다. revert로 되돌릴 수 있습니다. 독립 검토는 두지 않습니다.

## Verification
모든 tmux 검사는 격리 server(`tmux -L <임시 이름> -f /dev/null`)에서 하고 끝나면 그 server를 끕니다. 사용자의 기본 server에는 binding·hook을 넣지 않습니다.

1. 재현(수정 전 실패): Base의 `integrations/tmux/project_board.conf`로, 사용자 설정이 `prefix B`와 root `MouseDown1Pane`을 다른 명령으로 미리 binding한 server에서 파일을 읽으면 두 binding이 제품 명령으로 바뀝니다. 이 test가 Base에서 실패하고 수정 뒤 통과함을 기록합니다.
2. 수정 뒤 자동 test(새 test, `integrations/tmux/` 또는 `tools/project-board/tests/`):
   - 사용자 binding이 없으면 prefix `B`와 root `MouseDown1Pane`이 제품 binding입니다. 건너뜀 option은 비어 있습니다.
   - 사용자 binding이 있으면 두 키 모두 사용자 값 그대로이고, 건너뜀 option이 두 키를 담습니다.
   - `MouseDown1Pane`이 tmux 기본값이면 제품 binding으로 바뀝니다.
   - 읽기 전에 `@project_agent_board_key`를 `X`로 정하면 `prefix X`가 Board toggle이고 `prefix B`는 binding되지 않습니다.
   - 같은 파일을 두 번 읽은 뒤의 `list-keys`·`show-hooks -g`·건너뜀 option이 한 번 읽은 뒤와 같습니다.
   - 사용자가 같은 hook 이벤트에 다른 이름 또는 숫자 index로 넣은 hook은 읽은 뒤에도 그대로입니다. `[board]` 이름의 hook은 남지 않습니다.
   - 통합 파일을 다른 디렉터리(설치본 배치를 흉내 낸 `…/current/integrations/tmux/`의 symlink 경로)에서 읽어도 binding 명령이 그 디렉터리의 helper를 가리킵니다.
   - 5단계의 결정 표시 진입점을 status 형식으로 펼치면 `tmux_decide_status.py`가 실행됩니다.
3. 영향 회귀: `python -m pytest -q tools/project-board/tests`와 README의 네 번째 명령(`integrations/tmux`, `tools/test_*.py`)이 통과합니다. project-board의 알려진 timing test(`test_popup_renders_markdown_and_csv_and_closes_editor_after_acceptance`)가 실패하면 단독 실행으로 통과를 확인합니다.
4. 남은 개인 경로: `git grep -n "\.tmux/scripts" -- integrations tools skills docs/project-team`의 결과가 없거나, 남긴 줄마다 이유를 Result에 적습니다.
5. 고친 문서의 Markdown 상대 link가 실제 파일을 가리킵니다.
