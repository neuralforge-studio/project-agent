# BOARD-002: Board 전체 동작이 매우 느립니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Base: 7e35d2411a827df482e386643624eb7663330833 2026-11-09T19:53:55+09:00

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
- 2026-11-09 Leader: 제출 dcca9e9 검토. 원인 확정(project마다 registry 재로드 72%, 변경 없는 파일 2회 읽기, 창 이동마다 TUI 재기동, hook마다 Python 기동)과 수정·측정(재방문 20~28초→0.1~0.2초, snapshot 4~7초→0.3초, CR popup 9→3초), RUST-001 근거 기록을 확인했습니다. 계약 변경(본 window의 Board pane 유지)은 원칙을 받아들이되 지금 형태로는 인수하지 않습니다: 본 window마다 Textual process가 상주하며 2초마다 읽으므로 이 server의 window 33개(2026-11-09 확인)면 상주 process가 그만큼 늘어 사용자가 지적한 서버 자원 문제를 다시 만듭니다. 수정 요청: (1) 보이지 않는 pane은 갱신(polling)을 멈추고 보이면 바로 갱신, (2) 유지하는 pane 수에 상한(최근 본 순서), 값과 근거(Board process 하나의 RSS·CPU 실측)를 계약과 TUI 계획에 적음, (3) `origin/main` merge(CHANGELOG·spec·agent-session api.py·test_model.py 충돌), CHANGELOG 변경은 빼고(Leader가 씀), (4) BOARD-003·004 판정 근거로 빠른 창 이동 때의 hook process 수와 깜빡임 원인(pane 재생성인지)을 수정 전·후로 적음.

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

## Result

- 제출 commit: dcca9e930ff37c1d4718730a80115bf92eef49dd

### 1. 측정 조건

- 격리 tmux server(`tmux -S <새 socket>`, 사용자 server 미사용)에 `integrations/tmux/project-agent.conf`를 읽고 pty client 1개(100x30)를 붙여 쟀습니다. 등록 파일은 이 계정의 실제 등록(10개 project, 결정 190여 개, CR 130여 개)입니다. 읽기만 했습니다.
- 수정 전은 base `7e35d24`의 `git archive`본, 수정 후는 `dcca9e9`입니다. 둘을 같은 시간대에 번갈아 3라운드 돌렸습니다. 이 host의 load average는 측정 중 120~280이었습니다(수정 전 기준값을 처음 잰 때 120~180, 번갈아 잰 최종 측정은 245~280). 절대값이 크고 라운드마다 흔들리므로 **같은 라운드 안의 수정 전·후 비교**가 근거입니다.
- 횟수: 라운드당 8회씩 3라운드(창 첫 방문은 라운드당 2회라 6회, 재방문은 18회). popup은 6회씩 2번 번갈아(12회). 단계별 표(2절)는 각 항목 10회 중앙값이며, Textual import 시간만 `python -X importtime` 1회 값을 함께 적었습니다. click 처리(`click` 명령→popup 시작 사이)는 직접 재지 않았습니다. 아래 단계 표의 launcher·import 값에서 추정하며, 실측은 못 했습니다.

### 2. 수정 전 단계별 측정 (load 120~210, 중앙값/최대)

| 단계 | 중앙값 | 최대 | 비고 |
| --- | --- | --- | --- |
| bash: launcher 선택 | 0.05초 | 0.07초 | |
| Python 기동(import 없음) | 0.13~0.22초 | | |
| `project-board --help` 전체(bash→launcher→Python→cli import) | 0.62초 | 0.79초 | |
| `import project_board.model`(agent_session, project_item) | 0.28~0.32초 | 0.83초 | 첫 실행이 느림 |
| `import project_board.tui`(Textual) | 3.1초 | | load 210에서는 8.1초(최대 10.7초) |
| registry 읽기(`load_registry`) | 0.024초 | 0.032초 | **snapshot 한 번에 11번 호출**(아래) |
| `model.snapshot`(10개 project 전체) | 2.16초 | 3.71초 | load 210에서는 4.4~8.1초 |
| `model.liveness`(전체) | 0.39초 | 0.49초 | project마다 registry 재로드 |
| 그 중 결정 읽기가 큰 project 하나(결정 48개) | 0.99초 | | |
| 화면 그리기(`_render_projects`, 10 project) | 0.36초 | 0.38초 | 내용이 바뀐 때만 |
| `sync`(바뀐 것 없음, 프로세스 전체) | 0.73초 | 0.88초 | |
| toggle OFF / ON 명령 | 0.71 / 0.82초 | 1.31 / 1.00초 | |
| 창 이동 → Board pane 생김 / 첫 project 행 | 0.98 / 4.87초 | 1.24 / 5.64초 | n=10 |
| 창 이동 한 번에 시작되는 hook process | 1개(1.9~3.3초) | | `session-window-changed` |
| popup 첫 항목: CR popup / 결정 popup | 8.7 / 25.5초 | 16.2 / 32.4초 | n=10, 전체 project snapshot 때문 |

### 3. 원인 (확정)

1. **project마다 등록 파일을 다시 읽음**(`tools/agent-session/agent_session/api.py:68` `read_state`, `liveness`→`config.py:237 current_project`→`:207 resolve_project`→`:150 load_registry`): snapshot과 liveness가 project마다 `api.read_state(project.base, …)`를 불러 등록 파일 전체를 다시 파싱하고 `Path.resolve()`·`_overlap`(O(n²))을 돕니다. 한 번의 snapshot에 `load_registry` 11번. cProfile에서 snapshot 시간의 약 72%(2.88초/4.02초, 3회 합).
2. **바뀌지 않은 파일도 매번 두 번 읽음**(`model.py` 수정 전 `decide_items`·`cr_items`): `parse(path)`와 `sections(path)`가 각각 `read_text`. NFS에서 파일 open·close가 파일당 약 1ms+(load 시 수 ms~수십 ms). 2초마다 모든 pane이 이를 반복했고 snapshot이 갱신 주기(2초)보다 길었습니다(수정 전 중앙값 4.4~8.1초).
3. **창 이동마다 Board pane을 지우고 새 TUI process를 만듦**(`tmux_control.py` `_reconcile`의 `show = enabled and window in visible`): 이동 한 번이 Python+Textual import(3~8초)+첫 snapshot을 다시 치릅니다. 4.9초(load 낮을 때)~28초(load 250).
4. **hook마다 bash→launcher→Python process**(`project-agent-main.conf` 6개 hook): 바뀐 것이 없어도 0.7초(load 낮을 때)~4.6초 동안 CPU를 씁니다. 같은 이벤트에 여러 hook이 겹치면 `control.lock` 때문에 줄을 섭니다.
5. popup이 자기 project 하나만 보면서 모든 project를 읽음(`tui.py` 수정 전 `model.snapshot` 호출).

기각한 가설: 화면 그리기(0.36초, 내용이 바뀐 때만)는 병목이 아닙니다. hook 중복 실행은 창 이동당 1개로 확인(`session-window-changed`만)해서 "겹친 sync" 가설은 기각합니다.

### 4. 고친 것 (`dcca9e9`)

- `project_board/model.py`: CR·결정 파일을 크기·수정 시각·inode가 바뀐 것만 다시 파싱(`_cached`), 한 번에 한 번만 읽음(`project_item.api.text_sections` 추가). `snapshot(project_id=…)`로 popup은 자기 project만 읽음. 읽기 오류는 캐시하지 않음.
- `agent_session/api.py`: `project_state(project)`·`project_liveness(project, socket)` 추가(기존 `read_state`·`liveness`는 이를 부름, 동작 불변). Board는 등록 파일을 한 번만 읽음. `config.require_base`로 `base_unavailable` 판정을 한 곳에 둠. 명세 5절 표에 두 이름 추가.
- `tmux_control.py`: 마지막 client가 떠나도 Board pane 유지. 끌 때·관리 pane 종료·pane 종료 때만 제거.
- `project-agent-main.conf`: 6개 hook이 `@project_agent_sync_needed`(Board on이고 그 window의 Board pane이 없거나 저장한 폭이 아님)일 때만 `sync` 실행. 조건은 tmux format 하나.
- 문서: `docs/project-board-tui-plan.md`(2절 갱신·실행 단위, 5절), `install-contract.md` 5.3절(Board pane·hook·option), `tools/project-board/README.md`, `docs/project-team/spec.md` 5절. CHANGELOG에 BOARD-002.
- 숫자 한도·sleep으로 가린 것은 없습니다.

### 5. 수정 후 측정 (같은 조건, 같은 라운드의 수정 전과 비교)

| 사용자가 느끼는 동작 | 수정 전 (라운드1/2/3 중앙값) | 수정 후 (라운드1/2/3 중앙값) | 최대(수정 전→후) |
| --- | --- | --- | --- |
| 창 **재방문** 뒤 sidebar 보임 | 27.8 / 22.5 / 20.4초 | 0.19 / 0.06 / 0.10초 | 31.6→0.33초 |
| 창 **첫 방문** 뒤 sidebar 보임 | 29.8 / 27.8 / 17.5초 (n=2씩) | 25.1 / 13.0 / 7.8초 (n=2씩) | 30.9→26.9초 |
| sidebar 켠 뒤 첫 project 행 | 24.5 / 22.8 / 17.5초 | 17.6 / 14.7 / 8.5초 | 33.2→27.7초 |
| toggle ON 명령(pane 생성까지) | 3.7 / 3.5 / 2.5초 | 3.1 / 2.8 / 1.5초 | |
| CR popup 첫 항목(6회씩 2번) | 8.95 / 9.70초 | 3.31 / 2.53초 | 20.99→4.08초 |
| 결정 popup 첫 항목(6회씩 2번) | 6.55 / 4.18초 | 5.85 / 3.34초 | 7.11→6.60초 |
| 전체 snapshot 한 번(load 210) | 4.4~7.1초 | 0.31~0.35초 | 13.0→0.46초 |
| 창 이동 한 번의 hook process | 1개 | 재방문은 **0개**(6회 중 4회, 첫 방문 2회만 1개) | |

읽는 법: 사용자가 가장 자주 하는 동작(이미 본 창으로 돌아가기)은 수 초~수십 초에서 0.1~0.2초가 됐습니다. snapshot은 매 2초 반복 비용이라 약 15~20배 줄었습니다. CR popup 첫 항목도 3~4배 빨라졌습니다. 반면 **처음 보는 창의 첫 표시, sidebar 켜기, 결정 popup**은 10~55% 줄어드는 데 그쳤습니다(라운드마다 편차가 큽니다). 이 구간은 새 Python+Textual process의 기동과 첫 읽기가 대부분입니다.

### 6. RUST-001 근거 (언어를 바꾸지 않고는 못 줄이는 비용)

- 새 process마다 Python 기동 0.13~0.22초 + `project_board.tui`(Textual) import **약 3.1초(load 210에서 8.1초, 최대 10.7초)**. 같은 코드를 `-X importtime`으로 보면 `textual.app` 누적 2.4초, `textual` 패키지 0.88초입니다. 이 비용은 (a) 처음 보는 window마다 Board pane 하나, (b) popup을 열 때마다 한 번씩 반드시 치릅니다. CR popup은 이 값 때문에 수정 후에도 `first byte`가 2.3~3.1초입니다.
- 첫 snapshot(cache가 비어 있을 때)은 파일 수에 비례합니다. 수정 후에도 새 process는 한 번 전체를 읽습니다. load 210에서 전체 project 6~8초(수정 후 번갈아 측정에서 첫 호출 3.1~7.4초). 파일당 1회 읽기로 줄였지만 NFS 지연은 남습니다.
- `sync`·`toggle`·`click` 명령은 매번 bash→launcher→Python 기동(0.62초, load 높으면 2~4초)+agent_session import. 재방문 hook은 process를 시작하지 않지만 첫 방문 hook과 toggle, click은 이 비용을 냅니다.

### 7. 가정과 Leader 확인 사항

- **계약 변경**: "마지막 client가 떠나면 Board pane을 정리한다"를 "Board를 끄거나 그 window의 관리 pane이 끝날 때까지 유지한다"로 바꿨습니다(plan 5절, 설치 계약 5.3절). 보지 않은 window에는 만들지 않습니다. 되돌리려면 `_reconcile`의 `usable`/`show` 분리만 되돌리면 됩니다. 사용자 결정이 필요한 정책 변경이면 알려 주십시오.
- 유지된 pane도 2초마다 snapshot을 읽습니다(바뀐 것만 파싱하므로 비용은 stat+목록 읽기 수준). 안 보이는 window의 polling을 멈추는 것은 하지 않았습니다.
- 캐시는 process 안에서만 삼니다. popup이나 새 pane의 첫 읽기는 여전히 전체를 읽습니다. process 간 공유는 만들지 않았습니다(범위 밖, 위 RUST-001 근거 참고).
- BOARD-003·004(같은 원인일 수 있는 항목)는 이 CR의 원인과 수정 후 값을 보고 판정하십시오. 제 판단으로는 창 이동 뒤 갱신 지연은 이 CR로 해소됐고, 첫 방문과 popup 기동의 남은 비용만 별개입니다.

### 8. 검증 (제출 commit `dcca9e9`)

README 검증 표의 `tools/project-board/**`, `integrations/tmux/**`, `tools/project-item/api.py`·`read.py`, `tools/agent-session/api.py`, `docs/**` 행.

| 명령 | 결과 |
| --- | --- |
| `python -m pytest -q tools/project-board/tests` | 123 passed |
| `python -m pytest -q tools/project-item/tests` | 120 passed(`api.py`·`read.py`를 고친 뒤 실행) |
| `python -m pytest -q integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py` | 마지막 실행에서 `integrations/tmux` 36 passed. 처음에는 hook 조건 변경으로 `test_installed_link_is_kept…` 1건 실패했고 테스트가 Board를 켜도록 고쳐 통과. 나머지 파일(`tools/test_*.py`)은 첫 실행에서 83건 중 위 1건 외 통과. |
| `python -m pytest -q -n 8 tools/agent-session/tests` | 729 passed, 1 failed(`test_lifecycle.py::test_registration_publishes_when_the_controller_ends_before_it[sigint]`, load 230에서 60초 한도 초과). 같은 테스트를 단독 재실행해 4 passed. load에 의한 시간 초과로 판단하며 이 변경과 무관한 경로입니다. |
| `python -m pytest -q -n 8 install/tests` | 253 passed, 2 skipped |

근거 재사용·재실행 판정: 결과를 바꾸는 `api.py`·`model.py`·`tmux_control.py`·`conf` 변경 뒤에 각 명령을 실행했습니다. 그 뒤 바꾼 것은 테스트 파일과 CHANGELOG뿐입니다. 새 테스트: `test_model.py`(변경분만 읽음, 이동한 파일, registry 1회 읽기, popup 단일 project), `test_internal.py`(`project_state`·`project_liveness`), `test_tmux_control.py`(떠난 window의 pane 유지), `test_project_agent_conf.py`(hook 조건 4가지 상태). 다른 `tools/test_*.py`와 `install/tests`는 마지막 코드 변경 뒤 재실행하지 않았습니다. CHANGELOG와 테스트 파일만 바뀌었기 때문입니다.

### 수정 제출 (Leader 검토 반영)

- 제출 commit: b9294bd56143bda3bda7d2061ed52575626f729b

Leader 요청 4개를 반영했습니다. 수정 전 값은 base `7e35d24`, 수정 후 값은 이 commit입니다(같은 격리 tmux server·같은 registry, load average 60~350).

#### 요청 3: `origin/main` merge

- 충돌 4개(`CHANGELOG.md`, `spec.md`, `agent_session/api.py`, `test_model.py`)를 해결했습니다. `CHANGELOG.md`는 origin/main과 같게 두었습니다(`git diff origin/main -- CHANGELOG.md` 비어 있음, BOARD-002 항목 제거).
- **merge가 만든 새 회귀**: SESSION-004·005의 `model.project_view`가 project마다 `api.pending_releases(...)`를 불러(`Manager`가 등록 파일을 다시 읽고 `tmux get_current`가 seat마다 tmux process 8개) snapshot 한 번이 0.3초에서 4.2초(load 242)로 돌아갔습니다. cProfile: ipweaver 하나가 tmux 호출 32번, 1.5초. 고침: `api.project_pending_releases(project)`(등록 파일을 다시 읽지 않음)를 추가하고, 이 읽기를 2초 파일 갱신에서 10초 실행 상태 갱신(`model.liveness`)으로 옮겼습니다. `snapshot`은 그 결과를 씁니다. 반납 대기가 끝난 것은 다음 10초 갱신까지 최대 10초 늦게 사라집니다. 고친 뒤 snapshot 중앙값 0.26초(최대 0.44초). 명세 5절 표, TUI 계획 2절, README에 적었습니다.

#### 요청 1: 보이지 않는 pane은 갱신하지 않음

- 방식: tmux hook(6개)이 Board가 켜져 있으면 `integrations/tmux/project_board_visibility.sh`(plain sh, Python 없음)를 실행합니다. 이 스크립트가 `list-clients`로 보이는 window를 구하고, Board pane(`@project_board_managed`)마다 `@project_board_visible`을 기록해 상태가 바뀐 pane에만 SIGUSR1을 보냅니다. TUI는 신호를 받으면 tmux에 한 번 물어(`tmux_control.board_visible`) 2초·10초 읽기를 멈추거나, 보이게 되면 각각 곧바로 한 번 읽습니다. 2초마다 tmux client를 띄우지 않습니다.
- 안전장치: SIGUSR1의 기본 동작은 종료이므로 TUI가 handler를 설치한 뒤에만 `@project_board_ready=1`을 쓰고(`mark_ready`), 스크립트는 ready인 pane에만 신호를 보냅니다. ready를 쓴 직후 보임 상태를 한 번 읽어 그 사이의 변화를 놓치지 않습니다. 시작 때 handler를 달기 전 신호로 pane이 죽는 경로는 없습니다.
- 실측(격리 server, window 2개, 같은 부하): 보이는 Board pane은 30초 동안 CPU 5초, 보이지 않는 pane은 **0초**. 창을 되돌리면 옵션이 `visible=1`로 돌아옵니다. 스크립트 한 번 0.059초(중앙값, 15회, window 7개), 같은 부하의 `sync` 1.6초(최대 4.3초).
- SIGSTOP으로 멈추는 안은 쓰지 않았습니다. `control.lock`을 잡은 채 멈추면 `sync`·`toggle`이 그 window가 다시 보일 때까지 막힐 수 있기 때문입니다.

#### 요청 2: 유지하는 pane 상한 8개

- 실측(격리 server, 실제 sidebar): Board process 하나의 RSS **49.8 MB**, thread 6개. 보일 때 CPU는 40초에 6초(load 약 250에서 15%), 보이지 않을 때는 0입니다.
- 근거: 보이지 않는 pane은 읽지 않으므로 비용은 메모리입니다. **N=8이면 약 400 MB 이하**입니다. 이 server에 window가 33개 있어도 Board process는 8개를 넘지 않습니다. 한 작업에서 오가는 window(project의 Leader와 Worker, 몇 개의 shell)가 8개 안에 들어옵니다. 값은 `tmux_control.MAX_KEPT`, 근거는 TUI 계획 5절과 설치 계약 5.3절에 적었습니다.
- 동작: 새 pane을 만들 때 유지 pane이 8개를 넘으면, 어느 client도 보지 않는 window 중 `@project_board_seen`(보인 시각, 위 스크립트가 기록, 새 pane은 만든 시각)이 가장 오래된 window의 pane을 제거하고 layout을 복원합니다. 지금 보이는 window의 pane은 제거하지 않습니다.

#### 요청 4: BOARD-003·004 판정 근거

격리 server, window 4개, 이미 모두 한 번씩 본 상태에서 0.3초 간격으로 24번 전환(`m_rapid.py`: 전환 때마다 sidebar를 20ms 간격으로 sampling, `list-panes`로 pane 생성·제거 집계, hook 래퍼로 process 시작 집계).

| 항목 | 수정 전 | 수정 후 |
| --- | --- | --- |
| 시작된 hook process | `sync`(bash+launcher+Python) **24개**(전환 1회당 1개, 서로 `control.lock`을 기다림) | `sync` **0개**, visibility sh 24개(0.06초) |
| Board pane 생성 / 제거 | **11 / 11** | **0 / 0** |
| sidebar sample(보이는 window) | 137개 중 133개(**97%**)가 project 행 없음(그 window에 Board pane이 없음 131, 있어도 행 없음 2) | 130개와 71개(2회) 중 **0개** |
| 전환 뒤 0.3초 안에 행이 이미 보인 전환 | 1/24 | **24/24** |

판정 근거:
- **BOARD-004(깜빡임)**: 원인은 pane 재생성입니다. 수정 전에는 창을 옮길 때마다 Board pane이 지워지고 새로 만들어져(11번) 보이는 window의 97%가 빈 화면이었습니다. 수정 후에는 pane이 그대로 있어 생성·제거 0, 빈 화면 0입니다. 같은 원인으로 해소됩니다.
- **BOARD-003(빠른 창 이동 때 지연·loading 중복)**: 수정 전 24번 전환이 Python `sync` 24개를 만들었고(각 0.7초~4.6초, 서로 기다림) 그 사이 pane이 반복해서 만들어지고 지워졌습니다(loading 화면이 반복된 원인). 수정 후에는 Python process가 0개이고, 전환 24번 모두 0.3초 안에 행이 보입니다. 수정 전 단독 `sync`가 1.6초(load 337)였던 것과 달리 스크립트는 0.06초입니다. 같은 원인으로 해소됩니다. 남는 것은 **처음 보는 window**의 첫 표시(새 TUI process 기동)뿐이며, 이는 위 6절의 RUST-001 근거와 같은 비용입니다.

#### 검증 (제출 commit `b9294bd`)

README 검증 표의 `tools/project-board/**`, `integrations/tmux/**`, `tools/agent-session/**`(`api.py`·`lifecycle.py`), `tools/project-item/**` 행. merge로 입력이 바뀐 test와 `api.py` 변경이 요구하는 `install/tests`를 실행했습니다.

| 명령 | 결과 |
| --- | --- |
| `python -m pytest -q tools/project-board/tests` | 130 passed(처음에 `test_cli` 1건 실패: 새 인자 `mark_ready`, `visibility_reader`를 test의 가짜 `sidebar()`가 받지 못함. test를 고쳐 `test_cli` 3 passed. 나머지 129건은 그 실행에서 통과) |
| `python -m pytest -q integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py` | 93 passed |
| `python -m pytest -q tools/project-item/tests` | 125 passed |
| `python -m pytest -q -n 8 tools/agent-session/tests` | 753 passed(`[sigint]` test도 통과, TEST-005 merge 뒤 재발 없음) |
| `python -m pytest -q -n 8 install/tests` | 260 passed, 2 skipped |

새 test: `test_tui.py`(보이지 않는 sidebar는 읽지 않고 보이면 곧바로 한 번 읽음, SIGUSR1 경로와 handler 정리), `test_tmux_control.py`(pane 상한과 가장 오래 안 본 window 제거, `mark_ready`·`board_visible`), `test_project_agent_conf.py`(visibility 스크립트가 바뀐 ready pane에만 신호를 보내는지, hook이 스크립트를 실행하는지), `test_model.py`(반납 대기는 10초 갱신에서만 읽음). `test_cli.py`는 고친 호출 인자를 확인합니다.

근거 재사용·재실행 판정: 마지막 코드 변경(`test_cli.py` 수정) 전에 전체 명령을 한 번 실행했고, 그 뒤 바뀐 것은 `test_cli.py`뿐이라 그 파일만 다시 실행했습니다. CHANGELOG는 Leader 통합에서 씁니다.
