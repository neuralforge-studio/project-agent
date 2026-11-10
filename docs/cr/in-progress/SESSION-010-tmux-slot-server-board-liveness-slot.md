# SESSION-010: tmux 조회가 slot·호출마다 같은 server 정보를 다시 읽어 Board liveness와 명령이 slot 수에 비례해 느려집니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: PERF-001, TMUX-003
- Base: 6a2c0f09a9a30b88c9ab4b9794442e5b84674a92 2026-11-10T08:17:51+09:00

## Symptom
agent-session의 tmux 조회가 slot마다, 같은 명령 안에서도 호출마다 같은 server 정보를 다시 읽습니다. 그래서 Board의 liveness 한 번과 Leader의 명령이 slot 수와 조회 횟수에 비례해 느려집니다. 사용자 평가(2026-11-10): "정말 너무 느려서 쓸 수가 없는데", "반복 조회 수정은 측정 결과 기다리지 말고 바로 시작해줘. 너무 느려."

## Evidence
- Leader 측정(2026-11-10, 설치본 0.3.0, 사용자 server, 등록 project 10개·slot 약 46개, host load 45~65):
  - Board `project_board.model.liveness()` 한 번: 3.8~4.6초.
    - tmux subprocess 396번(slot마다 8~9번), 그중 3.86초가 tmux `_run`입니다.
    - `get_current` 46번, `_session_target`(`list-sessions`) 138번이 나옵니다.
    - `server_identity` 46번(`display-message`와 `/proc`의 process birth), `project_pending_releases` 10번에 1.55초가 듭니다.
  - `agent-session review --clear` 한 번: tmux 8번, 그중 `list-sessions`가 3번입니다.
- 원인이 되는 호출 사슬(`tools/agent-session/agent_session/tmux.py`):
  - `get_current`(411행 부근)는 다음을 차례로 부릅니다.
    - `has_session` → `_session_target`(`list-sessions`)
    - `_session_owner`. 이 안에서 다시 `_session_target`(`list-sessions`)과 `show-options`를 부르고, `server_identity`(`display-message`와 `process.birth`)를 부릅니다.
    - `_session_target`(`list-sessions`) → `show-options`(현재 pointer)
    - `read_meta`(1번 이상)
  - liveness는 여기에 `pane_info`를 1번 더 부릅니다.
  - `Manager.pending_releases`(`lifecycle.py` 1034행 부근)는 배정된 seat마다 `get_current`를 처음부터 다시 부릅니다.
  - `clear_current`·`managed_windows`·`set_current`도 같은 사슬을 씁니다.
- Board는 Board pane마다 10초 주기로 모든 project의 liveness를 돕니다(`tools/project-board/project_board/tui.py` 256행, `model.py` `liveness`).
- 비례 추정(측정 아님): 16 project × seat 16(slot 272개)이면 liveness 한 번에 tmux 호출이 약 2,300번입니다. 측정은 PERF-001이 합니다.

## Contract
- 관측 동작은 바꾸지 않습니다. 다음이 그대로여야 합니다.
  - [동작 명세 5절 Python API](../../project-team/spec.md#프로젝트-consumer용-python-api)의 반환값과 오류 code
  - CLI JSON
  - tmux option 이름·값
  - state 형식
  - owner·server identity 검사의 판정(`tmux_owner_mismatch`, restore 감지, `target_changed`, `execution_evidence_missing`)
- Board의 liveness 한 번(등록한 모든 project)이 띄우는 tmux process 수는 project·slot 수와 무관한 상수입니다.
- 한 명령 안에서 같은 tmux 사실을 다시 읽지 않습니다. 예외는 둘입니다. 그 사이 명령 자신이 그 사실을 바꿨을 때, 그리고 변화를 관찰하는 것이 목적인 읽기일 때입니다. 자기가 쓴 직후의 읽기는 새 값을 봅니다.

## Disposition
- 2026-11-10 Leader: 고친다. 재현 측정이 있는 결함이고, 사용자 지시가 있습니다(2026-11-10 대화 원문: "반복 조회 수정은 측정 결과 기다리지 말고 바로 시작해줘. 너무 느려."). PERF-001(측정)과 동시에 진행합니다. 기준선 측정은 PERF-001의 Base가 맡고, 이 CR은 자기 수정 전후만 잽니다.
- 2026-11-10 Leader: open -> todo. 사용자 지시로 즉시 수정
- 2026-11-10 Leader: 제출 0fdedf276f411528c11c1a9cdcba4c9e273ba087를 인수합니다. Leader review: ServerView가 tmux process 하나(window option 읽기까지 둘)로 server identity, session·owner·pointer, window, pane을 읽고, 판정은 기존과 같은 대조 함수를 지납니다. write_meta는 같은 sequence에서 쓰고 다시 읽어 자기 쓰기 뒤의 읽기가 새 값을 봅니다. 쓰기 경로에는 값 cache가 없고 매 관찰이 server identity를 새로 읽습니다. 사전 읽기를 identity·provider_launch_attempted 갱신으로 좁힌 것도 검사 대상 key가 같아 판정이 같습니다. Leader 독립 확인: 사용자 실제 server(32 slot)에서 v0.3.0과 제출본의 project_board.model.liveness를 읽기 전용으로 실행해 liveness·release hold 결과가 같았습니다(tmux 464번 -> 3번, 5.35초 -> 0.39초). 지적: merge(0fdedf2)로 들어온 TMUX-003의 integrations/tmux·install-contract.md는 tools/project-board/tests/test_tmux_control.py와 tools/test_distribution_boundary.py의 입력인데 다시 실행하지 않았습니다. Leader가 통합 commit 8d6365c(제품 tree는 제출과 같음)에서 두 test를 실행했고 30 passed입니다. 바꾼 문서 두 개의 상대 link도 확인했습니다.

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), [동작 명세 5절 Python API](../../project-team/spec.md#프로젝트-consumer용-python-api), [실행 경로 계약](../../project-team/README.md#실행-경로-계약), [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 수정 전 기준을 잽니다.
   - 격리 tmux server(README 검증의 test server 규칙)에 project 여럿 × seat 여럿의 살아 있는 run을 만듭니다. `tools/agent-session/tests/fixtures`의 fake provider를 씁니다.
   - 다음 연산마다 tmux process 수를 셉니다.
     - `project_board.model.liveness()`(모든 project)
     - `api.project_liveness`
     - `api.project_pending_releases`
     - CLI `review`·`review --clear`·`send`·`start`·`stop`
2. 읽기 전용 경로는 한 번의 tmux 실행으로 읽은 server view를 함께 씁니다.
   - 대상: `project_liveness`, `project_pending_releases`, 그리고 그 안의 `get_current`·`read_meta`·`pane_info`.
   - 한 tmux 실행에서 `;`로 이은 명령으로 다음을 읽습니다.
     - session 목록과 owner option
     - session option(현재 pointer)
     - 관리 window의 option
     - `list-panes -a`의 pane 사실
     - server identity
   - Board의 `model.liveness`가 모든 project에 그 view 하나를 쓰도록 합니다.
   - 판정 규칙(owner·server identity·pointer와 window identity 대조)은 지금 코드와 같은 함수를 지납니다. 같은 사실의 원본을 둘로 만들지 않습니다.
   - 새 공개 함수가 필요하면 다음 세 곳을 함께 고칩니다.
     - `api.__all__`
     - [동작 명세 5절](../../project-team/spec.md#프로젝트-consumer용-python-api) 표
     - `tools/agent-session/tests/test_api_boundary.py`
3. 쓰기 경로(CLI 명령)는 한 명령 안에서 같은 사실을 반복해 읽지 않게 합니다.
   - 대상: session handle, owner marker, server identity.
   - `kill-session`·`new-session`·`set-option` 등 명령 자신이 바꾼 뒤의 읽기는 새로 읽습니다.
   - 중간에 server가 바뀌면 지금과 같은 오류로 끝나야 합니다. 바뀐 server를 알아채지 못하는 cache는 만들지 않습니다.
4. 호출 수 test를 추가합니다.
   - tmux 실행을 세는 test를 둡니다. 다음 둘이 고정 상수 이하임을 보입니다.
     - project 2개와 6개, seat 2개와 6개에서 Board liveness 한 번의 tmux 실행 수
     - 대표 CLI 명령의 tmux 실행 수
   - 이 test는 수정 전 commit에서 실패해야 합니다.
   - 기존 test의 기대값(반환값·오류 code)은 바꾸지 않습니다. 바꿔야 한다면 그 이유를 Result에 적고 Leader에게 먼저 보고합니다.

의존: 없음. PERF-001과 파일이 겹치지 않습니다(PERF-001은 read-only). TMUX-003과도 겹치지 않습니다.

위험 등급: 높음. 모든 명령이 지나는 owner·identity 검사 경로입니다.

## Verification
1. 수정 전후 표를 Result에 적습니다. 1단계의 연산마다 tmux process 수와 벽시계 시간(3회 중앙값, host load 함께)을 넣습니다. 16 project × seat 16(slot 272개)의 Board liveness 한 번도 포함합니다.
2. 4단계의 호출 수 test가 수정 전에 실패하고 수정 뒤에 통과하는 것을 보입니다.
3. README 검증 표에서 바꾼 경로의 행을 모두 실행합니다.
   - `tools/agent-session/**`: `tools/agent-session/tests` 전체(`-n 8`).
   - `agent_session/api.py`나 tmux option·state 형식을 바꾸면 그 행에 따라 다음 셋도 실행합니다.
     - `tools/project-item/tests`
     - `tools/project-board/tests`
     - `install/tests`(`-n 8`)
   - `tools/project-board/**`를 바꾸면 `tools/project-board/tests`.
4. 제출 전에 `origin/main`이 움직여 위 명령의 입력을 바꿨으면 merge하고 merge commit에서 다시 실행합니다.

## Result

- 제출 commit: 0fdedf276f411528c11c1a9cdcba4c9e273ba087

`cr/SESSION-010`에 push했습니다. 구현 commit은 2bd14b3이고 0fdedf2는 `origin/main`(b5488b3)을 merge한 commit입니다.

### 변경
- `tmux.py`: `ServerView`를 추가했습니다. tmux process 하나가 server identity, session 목록(handle·owner marker·요청한 slot의 current pointer), window, pane을 읽습니다. 현재 run의 window option은 한 번 더 읽습니다(긴 batch는 `source-file -`로 stdin 입력. tmux가 16KB 넘는 command line을 거절하기 때문입니다).
  - `get_current`는 `ServerView.current`입니다. owner·identity·pointer 대조 함수는 그대로이고 호출 순서도 같아서 오류 code가 같습니다.
  - `has_session`·`_session_owner`·`set_current`·`clear_current`·`managed_windows`·`find_by_session`·`create_window`·`reuse_window`·`close_window`는 session handle·owner·identity를 한 번의 관찰로 얻습니다.
  - `read_meta`는 option 이름을 요청과 같은 sequence에서 나열하며 확인합니다(이름은 프로세스 안에서 학습해 `_META_KEYS`에 둡니다. 나열에 없는 이름이 보이면 다시 읽으므로 빠뜨리지 않습니다). `write_meta`는 같은 sequence에서 결과를 읽어 오고, identity·`provider_launch_attempted`를 바꾸는 갱신만 사전 읽기를 합니다.
- `api.py`: 공개 `server_view(projects, socket=None)`를 추가했습니다. `project_liveness`·`project_pending_releases`는 `view=None`을 받고, `caller`의 slot 순회도 한 번의 읽기를 씁니다. `Manager.pending_releases(view=None)`.
- `project-board/model.py`: `liveness`가 view 하나를 모든 project에 씁니다.
- 문서: [동작 명세 5절](../../project-team/spec.md#프로젝트-consumer용-python-api) 표(`server_view` 추가, `view` 인자), `docs/project-board-tui-plan.md`. `test_api_boundary`는 `__all__`과 표를 대조하며 통과했습니다.
- 결정: Implementation은 "한 번의 tmux 실행"이라고 썼지만 window option은 pointer가 가리키는 window를 알아야 읽을 수 있어서 둘입니다(Contract의 "project·slot 수와 무관한 상수"는 만족). 프로세스의 첫 읽기에서 option 이름을 학습하는 경우(seed에 없는 `job`·`provider` 등)에는 한 번 더 듭니다.
- 쓰기 경로에는 pointer·window option 값을 저장하는 cache를 만들지 않았습니다. 매 관찰이 server identity를 같은 tmux process 안에서 새로 읽으므로 바뀐 server를 알아채지 못하는 경우가 없습니다. 같은 명령 안의 `get_current` 반복(예: review의 Leader 3회)은 pointer·window option의 변화를 보려는 읽기라 남겼습니다.

### 기존 test 변경 (기대값은 그대로)
- `test_remote_api.py`의 `Display` 대역에 `server_view`를 추가했습니다(`get_current`·`pane_info`를 감쌈).
- `test_model.py`: monkeypatch한 `project_liveness`·`project_pending_releases`의 signature에 `view=None`을 추가했고, `model.liveness`가 사용자 default tmux server를 읽지 않도록 autouse fixture로 `AGENT_SESSION_SOCKET`을 없는 socket으로 지정했습니다. 반환값·오류 code 기대값은 바꾸지 않았습니다.

### 수정 전후 (tmux process 수 / 벽시계 중앙값 3회, 합성 fleet: 격리 tmux server, project N × seat N, 살아 있는 pane. host load는 측정 시점 30~42, 수정 전 첫 측정은 75~127)
| 연산 | 수정 전 (6a2c0f0) | 수정 후 |
| --- | --- | --- |
| Board `model.liveness` 6×6 (42 slot) | 666 / 12.1 s | 2 / 0.23 s |
| Board `model.liveness` 16×16 (272 slot) | 4496 / 91.4 s (load 75~127에서는 107 s) | 2 / 0.86 s |
| `api.project_liveness` 한 project, seat 2 / 6 / 16 | 27 / 63 / 153 (1.8 s at 16) | 2 / 2 / 2 (0.09 s) |
| `api.project_pending_releases` 한 project, seat 2 / 6 / 16 | 16 / 48 / 128 (1.7 s at 16) | 2 / 2 / 2 (0.09 s) |

CLI(fixture project 하나·seat 2, fake provider, load 82~87, 3회):
| 명령 | 수정 전 | 수정 후 |
| --- | --- | --- |
| `review` | 24 / 0.29 s | 6 / 0.09 s |
| `review --clear` | 8 / 0.11 s | 2 / 0.06 s |
| `send` | 43 / 0.63 s | 13 / 0.18 s |
| `stop` | 69 / 1.5 s | 24 / 0.88 s |
| `start` leader | 154~163 / 2.9 s | 62~68 / 1.5 s |
| `start` worker | 178~205 / 4.3 s | 57~61 / 2.8 s |
(`start`의 tmux 수는 provider 등록을 기다리는 loop 횟수를 따라 달라집니다. 시간은 host load의 영향이 큽니다.)

### 검증
- 호출 수 test: `agent-session/tests/test_tmux_calls.py`(project 2·6, seat 2·6의 view 읽기 ≤ 2, 한 project 읽기 ≤ 2, review ≤ 8·review --clear ≤ 3·send ≤ 16·stop ≤ 30, option 이름 학습 1회, 사라진 window), `project-board/tests/test_tmux_calls.py`(Board refresh ≤ 2). helper는 `agent-session/tests/fleet.py`.
- 수정 전 실패 확인: 6a2c0f0 트리를 `git archive`로 풀어 새 test를 얹고 실행했습니다. 호출 수 test가 27·63(한 project), 666(Board 6×6), review 24·--clear 8·send 43·stop 69로 실패했습니다. 수정 뒤에는 통과합니다.
- view와 live 읽기 동치: `test_a_server_view_judges_each_slot_as_a_live_read_does`가 window 소실·run 불일치·JSON 아님·window handle이 아닌 문자열·다른 server의 owner·없는 project에서 view와 `get_current`의 결과(오류 code 포함)가 같음을 봅니다.
- README 검증 표 실행(구현 commit 2bd14b3 기준): `tools/agent-session/tests -n 8` 806 passed, `tools/project-item/tests` 125 passed, `tools/project-board/tests` 161 passed, `install/tests -n 8` 267 passed 2 skipped, `tools/test_distribution_boundary.py` 9 passed.
- merge 뒤(0fdedf2): merge가 가져온 TMUX-003의 `integrations/tmux/**`·`install-contract.md`는 `install/tests`의 입력이어서 그것만 다시 실행했습니다. 267 passed 2 skipped. agent-session·project-item·project-board의 입력은 바뀌지 않아 재사용합니다.
- 한 번의 전체 실행에서 `test_start_held_at_a_startup_dialog_needs_the_user_and_resumes[leader]`가 host load로 실패했고 단독 재실행에서 통과했습니다. 다음 전체 실행에서는 통과했습니다.
