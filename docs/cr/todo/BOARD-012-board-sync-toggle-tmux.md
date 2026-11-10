# BOARD-012: Board sync·toggle이 창마다 tmux를 여러 번 불러 창 수에 비례해 느려집니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: SESSION-010, PERF-001

## Symptom
Board의 `sync`(창 전환·session 전환·client 연결 hook에서 실행)와 `toggle`은 tmux server의 창마다 tmux를 여러 번 부릅니다. 그래서 project·seat가 늘면 창 전환 한 번의 비용도 창 수에 비례해 늘어납니다. SESSION-010이 liveness의 같은 결함을 고친 뒤 남은 반복 조회입니다. 사용자 지시(2026-11-10): "반복 조회 수정은 측정 결과 기다리지 말고 바로 시작해줘. 너무 느려."

## Evidence
- PERF-001 중간 측정(2026-11-10, `tools/tests/perf`, counting pass, v0.3.0 → v0.4.0):

  | 연산 | 4×4 | 8×8 |
  | --- | --- | --- |
  | `sync` tmux 호출 | 100 → 105 | 579 → 306 |
  | `toggle_on` tmux 호출 | — | 338 → 321 |

  같은 측정에서 liveness는 규모와 무관하게 3번입니다.
- 원인(코드로 확인, `tools/project-board/project_board/tmux_control.py`):
  - `_reconcile`(417행)은 `list-windows -a`로 받은 창마다 tmux를 부릅니다.
    - `_panes`: `list-panes -t <창>`
    - `_board_pane`: `show-options -w`, 그리고 Board pane이면 `show-options -p`
    - `_managed_pane_dead`: `show-options -w`
  - `_evict`(387행)는 `list-windows -a`를 다시 부르고, 창마다 `show-options -w`를 1~2번 부릅니다.
  - 16 project × seat 16(창 약 290개)이면 `sync` 한 번에 1,000번이 넘을 것으로 봅니다(비례 추정).
- `sync`는 `@project_agent_sync_needed` 조건이 참일 때만 실행됩니다(integrations/tmux/project-agent-main.conf). Board를 켠 상태에서 Board pane이 없는 창으로 옮길 때마다 참입니다.

## Contract
- Board의 관측 동작은 그대로입니다. 어느 창에 pane을 만들고 지우는지, 너비 규칙, 보관 수(`MAX_KEPT`)와 eviction 순서, tmux option 이름과 값, CLI JSON이 모두 같아야 합니다.
- `sync`·`toggle` 한 번의 읽기 tmux 실행 수는 창·project·seat 수와 무관한 상수입니다. 쓰기(pane 생성·삭제·option 설정)는 실제로 바꾸는 창 수에만 비례합니다.

## Disposition
- 2026-11-10 Leader: 고친다. 재현 측정이 있는 결함이고, 사용자 지시가 있습니다(2026-11-10: "반복 조회 수정은 측정 결과 기다리지 말고 바로 시작해줘. 너무 느려.").
- 2026-11-10 Leader: open -> todo. 사용자 지시: 반복 조회 수정 즉시

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), [project-board README](../../../tools/project-board/README.md), [tmux 통합](../../../integrations/tmux/project-agent-main.conf), SESSION-010의 `ServerView`(`tools/agent-session/agent_session/tmux.py`, [동작 명세 5절](../../project-team/spec.md#프로젝트-consumer용-python-api)), 측정 도구 `tools/tests/perf/perf_bench.py` 머리말, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 수정 전 기준: 측정 도구의 counting pass로 v0.4.0의 `sync`·`toggle_on`·`toggle_off`·`click` tmux 호출 수를 잽니다. 규모는 4×4, 8×8, 16×16입니다.
2. 읽기를 묶습니다. `_reconcile`·`_evict`가 쓰는 창·pane·option 정보를 tmux 실행 하나(또는 상수 개)로 읽습니다. 예를 들어 `list-panes -a -F`에 `#{pane_id}`·`#{window_id}`·`#{pane_dead}`·`#{pane_width}`와 창·pane option을 format으로 넣는 방법이 있습니다. format의 option 조회는 상위(session·global)로 내려가 상속하므로, 지금 `show-options -w`·`-p`와 같은 값을 읽는지 test로 확인합니다.
3. 판정 규칙(Board pane 확인, 관리 pane이 죽었는지, 보이는 창, eviction 순서)은 지금 함수의 규칙 그대로 한 곳에 둡니다. 읽기 방식만 바꿉니다.
4. 호출 수 test를 둡니다. 창 수가 다른 두 server에서 `sync`·`toggle`의 읽기 tmux 실행 수가 같은 상수 이하임을 보입니다. 이 test는 수정 전에 실패해야 합니다.

의존: 없음.

위험 등급: 중간. Board pane 생성·삭제 경로입니다.

## Verification
1. 측정 도구로 v0.4.0과 후보를 비교합니다(counting pass와 warm). 대상은 1단계의 연산과 세 규모입니다.
2. 4단계 test의 수정 전 실패와 수정 뒤 통과를 보입니다.
3. README 검증 표 `tools/project-board/**` 행을 실행합니다(`-rf`). `integrations/tmux/**`를 바꾸면 그 행도 실행합니다.
4. 제출 전에 `origin/main`이 움직여 위 명령의 입력을 바꿨으면 merge하고 merge commit에서 다시 실행합니다.
