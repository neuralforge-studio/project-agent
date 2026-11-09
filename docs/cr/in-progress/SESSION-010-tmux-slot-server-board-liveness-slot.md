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
