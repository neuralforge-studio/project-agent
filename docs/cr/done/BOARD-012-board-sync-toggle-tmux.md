# BOARD-012: Board sync·toggle이 창마다 tmux를 여러 번 불러 창 수에 비례해 느려집니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: SESSION-010, PERF-001
- Base: cc73ad69370bdd19ef5ef54426a4c9cb3d4b935b 2026-11-10T13:34:52+09:00
- Outcome: fixed

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
- 2026-11-10 Leader: 제출 7d774be81073f16a8a89fa89c496e7b67405ad41를 인수합니다. Leader review: _snapshot은 tmux 한 번(display-message, list-clients, list-panes -a)으로 전역 Board option, 보이는 창, 모든 pane과 창·pane option을 읽습니다. _reconcile·_evict의 판정 함수 규칙은 그대로이고 입력만 바뀌었습니다. format의 option 상속(pane, window, session, global)은 기존 tmux 통합의 @project_agent_sync_needed가 쓰는 조회와 같고, 이 option들은 창·pane에만 써서 값이 같습니다. test_the_snapshot_reads_what_the_per_window_options_hold가 이를 고정합니다. 측정 도구로 v0.4.0과 비교한 16×16 호출 수는 sync 1124 -> 7, toggle on 1123 -> 16, off 853 -> 17이고 창 수와 무관합니다. warm 시간은 sync 39.4초 -> 2.0초입니다. 창 4개와 52개 server의 호출 수 test는 수정 전에 실패합니다. README 표 tools/project-board/** 행 163 passed. 제출 이후 main은 움직이지 않았습니다.
- 2026-11-10 Leader: in-progress -> done, Outcome fixed. 통합 4018f0c(Merge cr/BOARD-012, 제출 7d774be). origin/main 반영 확인. CHANGELOG Unreleased에 더했습니다.

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

## Result

- 제출 commit: 7d774be81073f16a8a89fa89c496e7b67405ad41

변경: `tools/project-board/project_board/tmux_control.py`에 `_snapshot`을 두었습니다. tmux 한 번이 전역 Board option, client가 보는 창, 모든 pane과 그 창·pane option을 읽습니다(`display-message ; list-clients ; list-panes -a -F`). `_reconcile`과 `_evict`가 이 snapshot을 판정합니다. 판정 규칙(`_board_pane`, `_managed_pane_dead`, 보이는 창, eviction 순서)은 같고 입력만 바뀌었습니다. `_evict`는 pane 생성·삭제 뒤 상태를 보려고 snapshot을 한 번 더 읽습니다. 쓰기 경로(`_create`, `_remove`, `_restore`, resize)는 그대로이고 Board pane이 있는 창(최대 `MAX_KEPT` 안팎)에만 비례합니다.

가정(Contract 영향 없음): format은 option을 pane → window → session → global 순으로 읽고 `show-options -w`는 창만 읽습니다(tmux 3.8에서 확인). Board와 agent-session은 이 option을 창·pane에만 쓰므로 값이 같습니다. 상위에 같은 이름을 따로 설정하면 달라집니다. 이 가정은 `_Snapshot` docstring에 적었습니다.

검증:
1. 측정(`tools/tests/perf/perf_bench.py`, BASE = `git archive cc73ad6`(v0.4.0 + CR 문서), CANDIDATE = 제출 commit과 같은 내용, `--groups board_cli --reps 3`, host load 47~57). 규모마다 tmux 실행 수(counting pass)입니다.

   | 연산 | 4×4 | 8×8 | 16×16 |
   | --- | --- | --- | --- |
   | `sync`(변화 없음) | 98 → 8 | 315 → 8 | 1124 → 7 |
   | `sync`(Board off) | 70 → 4 | 226 → 4 | 826 → 4 |
   | `toggle` on | 106 → 16 | 314 → 16 | 1123 → 16 |
   | `toggle` off | 88 → 15 | 244 → 17 | 853 → 17 |

   warm 중앙값(초, BASE → 후보): 16×16 `sync` 39.4 → 2.0, `toggle` on 33.6 → 2.4, `toggle` off 23.1 → 2.3. 8×8 `sync` 10.7 → 1.8. 4×4 `sync` 4.5 → 1.0. 후보의 호출 수는 8×8과 16×16에서 같습니다. `board_sidebar_ready`·`board_popup_ready`는 Board TUI 시작 시간이라 tmux 호출 0이고 이 변경과 무관합니다(host 부하에 따른 잡음). `click`은 변경하지 않았고 측정 대상에서 제외했습니다(`board_cli` 단위에 없음). 결과 원본: 이 seat의 scratchpad `out/summary.md`.
2. 새 test `test_sync_and_toggle_start_the_same_tmux_processes_for_any_number_of_windows`(창 4개와 52개 server에서 `toggle` on·`sync`·`toggle` off의 tmux 실행 수가 같음). 수정 전 코드(`git show cc73ad6`의 `tmux_control.py`)에서 실패합니다: 4개 창 `sync` 21 대 52개 창 213 등. 수정 뒤 통과합니다. `test_the_snapshot_reads_what_the_per_window_options_hold`는 snapshot이 `show-options`와 같은 값을 읽음을 확인합니다(죽은 관리 pane, 공백이 든 config 포함).
3. `python -m pytest -q -rf tools/project-board/tests`: 제출 commit에서 163 passed. `integrations/tmux/**`·`install/**`는 바꾸지 않아 실행하지 않았습니다.
4. `origin/main`은 base(cc73ad6) 이후 움직이지 않아 merge가 없습니다.

근거 재사용: 위 3번은 제출 commit에서 실행했습니다. 측정(1번)은 docstring 한 줄을 고치기 전의 작업 트리로 실행했고, 이후 코드 변경은 docstring뿐입니다.
