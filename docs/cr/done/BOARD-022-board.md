# BOARD-022: Board를 끄고 켜는 데 오래 걸립니다. 단계별 원인을 나눠 줄이고, 남는 시간은 진행 상태로 보입니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S2
- Base: d027205cfbb5208cea3a9174e2cae01128755592 2026-11-11T13:10:56+09:00
- Outcome: fixed

## Symptom
사용자 보고(2026-11-11, 0.8.0 설치 뒤): "board를 겄다가 켜보았어? 끄는데, 켜는데 굉장히 오랜 시간이 걸리긴 하는데... 이게 맞아? 원인을 알려주면 좋겠네. 끄는데, 켜는데 오래걸려야할 이유가 명확하고 해결이 불가능하다면, status? 어떤 상태인지 얼마나 남았는지 등을 표시해주면 좋겠네."

## Evidence
- 켜기·끄기 경로(설치본 0.8.0)에서 확인한 사실:
  - `prefix B`가 `run-shell -b`로 `project_agent_run.sh key … tmux_project_board.sh toggle`을 부릅니다.
  - Python `project-board toggle`이 `tmux_control.toggle_sidebar`를 실행합니다. Board 잠금(`_locked`) 안에서 `@project_board_enabled`를 바꾸고 `_reconcile`을 부릅니다.
  - `_reconcile`은 window마다 tmux 명령을 따로 실행합니다.
    - 끌 때는 유지하던 Board pane(최대 8개, `MAX_KEPT`)마다 `display-message`, `resize-pane`, `_remove`(kill-pane과 `_restore`의 layout 복원)를 합니다.
    - 켤 때는 보이는 window마다 `_create`로 pane을 만들고, 그 pane에서 Board TUI가 시작합니다.
  - 켠 뒤 화면이 그려지기까지는 Board TUI 시동(Textual import와 첫 snapshot, 16×16에서 약 2.8초)이 더해집니다(BOARD-016). 이 부분은 BOARD-018(Rust sidebar)이 줄이고 있습니다.
  - 이 밖에 window 전환 hook이 부르는 sync, 잠금 대기, tmux 명령 하나의 비용(host load가 높을 때)은 재지 않았습니다.
- 이 workstation의 tmux server에는 session 10여 개와 window 수십 개가 있습니다.
- 가설(미확인): 끄기는 Board pane마다 차례로 실행하는 tmux 명령과 layout 복원이, 켜기는 Python 시동, pane 생성, TUI 시동이 대부분입니다.

## Contract
1. 끄기: `prefix B`를 누른 뒤 모든 window에서 Board pane이 사라지기까지의 시간을 줄입니다. 남는 시간에는 근거가 있어야 합니다.
2. 켜기: `prefix B`를 누른 뒤 보이는 window에 Board pane이 생기기까지의 시간을 줄입니다. TUI가 그려지기까지는 BOARD-018의 몫으로 나눠 적습니다.
3. 남는 시간이 사용자가 기다림을 느낄 만큼 길면(약 0.5초 넘게), 누른 client에 진행 상태를 보입니다. 예: 상태 줄이나 `display-message`의 "Board 끄는 중 3/8". 끝나면 사라집니다.
4. 결과(어떤 window에 Board가 있는지, 폭, layout 복원, 떠 있는 Board 창 보존)는 지금과 같습니다.

## Disposition
- 2026-11-11 Leader: 고친다(Leader 판정). 사용자가 보고한 느림이고, 원인 설명과 진행 표시를 요청받았습니다. 줄일 수 있는 비용은 줄이고, 남는 비용은 진행 상태로 보입니다.
- 2026-11-11 Leader: open -> todo. Leader 판정: 사용자 보고 느림
- 2026-11-11 Leader: 제출 c57ec0e를 검토했습니다. 원인 분해, 명령 묶음, 진행 표시, test, A/B(끄기 5.23→1.02초, 켜기 2.05→0.72초, load 87~111)는 인수 가능합니다. 수정 요청은 하나입니다. 제출 뒤 통합된 BOARD-023·BOARD-024(test_tmux_control.py, README, tui.py)를 merge하고, merge commit에서 project-board tests, test_api_boundary, test_distribution_boundary를 다시 실행합니다.
- 2026-11-11 Leader: 제출 7b608e04d225cafd478324df97f345962c79052d를 인수합니다. 재검토 7b608e0(앞 검토 c57ec0e + main be54113 merge, 자동 병합, tmux_control.py는 merge로 바뀌지 않음). merge commit에서 project-board tests + test_api_boundary 208 passed, test_distribution_boundary 9 passed. A/B는 tmux_control.py 입력이 같아 앞 측정을 재사용합니다(끄기 5.23→1.02초, 켜기 2.05→0.72초).
- 2026-11-11 Leader: in-progress -> done, Outcome fixed. 통합 aeb6304 (origin/main)

## Implementation
읽을 문서: `tools/project-board/project_board/tmux_control.py`(`toggle_sidebar`, `_reconcile`, `_create`, `_remove`, `_restore`, `_evict`, `_locked`), `integrations/tmux/`(`project_agent_bind.sh`, `project_agent_run.sh`, `tmux_project_board.sh`, `project-agent-main.conf`의 hook), `tools/bundle_boot.py`, [Board TUI 계획](../../project-board-tui-plan.md), BOARD-016 Result(단계 분해 방법), [설치 계약](../../project-team/install-contract.md) 5.3절, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 단계 분해: 다음 단계마다 wall 시간을 잽니다. 반복 3회이고 host load를 함께 적습니다.
   - 단계: key → run-shell 시작, shell 진입점, Python 시동, 잠금 대기, `_snapshot`, window별 tmux 명령(개수와 합계), layout 복원, pane 생성, hook이 부르는 sync, TUI 첫 그림
   - 환경 두 가지: test tmux server(`tools/tests/tmux_test_server.py`의 claim·release)와, 이 workstation과 비슷한 규모(session 10개, window 40개, client 1~2개, Board 유지 8개)
   - 사용자의 실제 tmux server에서는 켜고 끄지 않습니다.
2. 원인을 Result에 적습니다. 줄일 수 있는 것을 고칩니다. 예: tmux 명령을 묶기, 한 번에 보내기, 불필요한 조회 없애기, 잠금 경합 없애기, hook이 부르는 중복 sync 없애기.
3. 남는 시간이 Contract 3에 해당하면 진행 상태를 보입니다. 사용자의 status 설정은 바꾸지 않는 방법(예: `display-message -c <client>`)을 고릅니다.
4. Test: 진행 상태 표시, 결과 동일성(Contract 4), 줄인 명령 수(예: tmux 호출 수를 세는 test)를 둡니다.

의존: 없음. BOARD-018이 `tmux_control.py`의 sidebar 실행 명령을 바꾸고 있으니 제출 전에 `origin/main`을 merge합니다.

위험 등급: 중간. 모든 window의 Board pane 생성과 제거에 닿습니다.

## Verification
1. README 검증 표에서 바꾼 경로의 행 명령 전부를 실행합니다. `tools/project-board/**` 행이고, `integrations/tmux/**`를 바꾸면 그 행도 실행합니다.
2. 끄기와 켜기(pane 생성까지)의 A/B를 0.8.0과 이 CR로 번갈아 3회 잽니다. 위의 workstation 규모 환경이고, wall과 95% 구간을 적습니다. test는 측정과 동시에 돌립니다.

## Result
- 제출 commit: c57ec0e5707b8e306ae0bba2b7c64b05ec374e65

### 원인 (측정, 확인된 사실)
측정 환경은 test tmux server(`-f /dev/null`) 하나입니다. session 10개, window 40개, client 2개이고 Board 6~8개를 유지한 상태입니다. Board TUI는 `sleep` stand-in입니다. host load는 87~111(52명 사용 중인 workstation)이었고, 모든 수치는 이 부하에서 잰 값입니다. 측정 script는 scratchpad의 `bench.py`로 repo에는 넣지 않았습니다. 0.8.0(`d027205`)과 이 CR을 번갈아 3회 실행했습니다.

단계별 시간입니다(반복 평균, 호출 수/초).

| 단계 | 끄기 0.8.0 | 끄기 이 CR | 켜기 0.8.0 | 켜기 이 CR |
| --- | --- | --- | --- | --- |
| 잠금 디렉터리(pid) | 1 / 0.08 | 1 / 0.08 | 1 / 0.08 | 1 / 0.08 |
| 죽은 server 디렉터리 정리(`ps`) | 2 / 0.17 | 1 / 0.12 | 6 / 0.44 | 1 / 0.09 |
| 상태 읽기(`_snapshot`, 켜짐 조회) | 3 / 0.23 | 1 / 0.09 | 3 / 0.21 | 1 / 0.10 |
| 옵션 쓰기 | 2 / 0.14 | 1 / 0.09 | 2 / 0.13 | 1 / 0.08 |
| Board pane별 폭 조회 | 6 / 0.51 | 0 | - | - |
| Board pane 제거와 layout 복원 | 48 / 4.08 | 6 / 0.63 | - | - |
| Board pane 생성(layout·focus 조회, split, 옵션) | - | - | 16 / 0.99 | 4 / 0.36 |
| 중복 eviction 조회 | - | - | 2 / 0.18 | 0 |

- 끄기는 Board 하나당 tmux 명령 약 10개(폭 조회, kill-pane, 옵션 해제 2개, layout 읽기 3개, select-layout, select-pane 등)를 각각 새 tmux process로 실행했습니다. 비용의 90%가 여기입니다.
- 켜기는 pane 하나당 split-window 전에 layout·focus를 읽고 옵션 4개를 따로 쓰며, 만들 때마다 runtime 디렉터리 검사(`ps`)를 다시 했습니다. 마지막에 eviction이 상태를 한 번 더 읽었습니다.
- 둘 다 tmux 호출 하나가 host load 100에서 70~100ms입니다. 호출 수가 곧 시간입니다.
- 사용자 계정의 tmux conf hook이 부르는 `sync`는 같은 잠금을 기다립니다. 처음 측정에서 test server가 `~/.tmux.conf`를 읽어 hook이 잠금을 1~5초 쥐었고 이것이 가짜 지연으로 섞였습니다. `-f /dev/null`로 분리했습니다. 실제 서버에서 이 대기가 얼마나 되는지는 재지 않았습니다(사용자의 실제 server에서는 켜고 끄지 않기로 했습니다).
- key → `run-shell` → shell → Python 시동: 설치본 0.8.0(시동 번들)에서 `project-board toggle`이 첫 tmux 실패까지 걸리는 시간이 0.45~0.55초(load 72, 3회)입니다. 이 시간은 이 CR에서 줄이지 않았습니다. `tmux_control`이 `model`(project_item 포함)을 import하는 부분이 크지만, `model`이 `agent_session`의 `sys.path`를 잡아 주는 구조라 import를 늦추려면 경로 설정의 소유를 옮겨야 합니다. 별도 CR로 남깁니다.
- TUI 첫 그림(약 2.8초)은 BOARD-018의 몫이라 재지 않았고 줄이지 않았습니다.

### 고친 것 (`tools/project-board/project_board/tmux_control.py`)
- `_snapshot`이 pane 폭, window 폭, window layout, 활성 pane, 저장한 layout(`@project_board_restore`), client 이름까지 한 번에 읽습니다. `_reconcile`, `_remove`, `_create`가 같은 값을 다시 묻지 않습니다. Board를 제거할 때 쓰던 layout은 제거 전 window의 `window_layout`에서 floating pane만 취하므로 결과가 같습니다.
- 제거: kill-pane, 옵션 해제, select-layout, select-pane을 tmux 한 process(`;` 연결)로 실행합니다. 옵션 해제를 restore 앞에 두어 restore가 실패해도 이전처럼 옵션이 남지 않습니다. 마지막 pane이 window를 닫는 경우의 처리는 그대로입니다.
- 생성: 옵션 쓰기와 `@project_board_seen`을 한 process로 묶고 layout·focus는 이미 읽은 값을 씁니다. `_locked`가 runtime 디렉터리를 넘겨 pane마다 pid 조회와 `ps`를 반복하지 않습니다.
- `toggle_sidebar`는 잠금 안에서 상태를 한 번 읽고 바꾼 옵션을 한 process로 쓴 뒤 같은 snapshot으로 reconcile합니다(켜짐 조회와 두 번째 snapshot 제거).
- eviction은 유지한 Board가 `MAX_KEPT`를 넘을 때만 상태를 다시 읽습니다. 최종 폭 옵션 쓰기는 값이 바뀌었거나 `resize-pane`을 실행했을 때만 합니다(`after-resize-pane` hook이 전역 폭을 바꾸는 유일한 경로입니다).
- `reap_runtime_directories`가 살아 있는 pid의 `ps`를 디렉터리마다가 아니라 한 번에 부릅니다. 판정 규칙은 `_is_tmux_server_of`가 그대로 소유합니다.
- 진행 상태: 시작부터 0.5초(`PROGRESS_AFTER`)가 지나면 붙어 있는 모든 client에 `display-message -c`로 `Board 끄는 중 3/8` / `켜는 중 1/2`를 보이고(3초), 마지막 단계에 `… 완료`(1초)를 보입니다. 그 단계의 tmux process 안에 포함해 process를 늘리지 않습니다. 사용자의 status 설정은 바꾸지 않습니다. 확인한 것: `display-message -c`가 사라진 client를 가리켜도 오류 없이 뒤 명령이 실행됩니다(tmux 3.8).
- 가정: 키 binding이 client를 넘기지 않으므로(`project-agent-main.conf`/`project_agent_bind.sh`는 수정하지 않았습니다) 붙어 있는 모든 client에 보입니다. 설치된 binding을 다시 만들지 않고 바로 동작합니다. 누른 client만 대상으로 하려면 binding에 `#{client_name}`을 넘기고 toggle에서 그 client를 검증해야 하며, 이는 생성되는 script 내용의 변경이라 이 CR에서 하지 않았습니다.
- 결과(어느 window에 Board가 있는지, 폭, layout 복원, 떠 있는 CR·결정 창 보존)는 같습니다. 기존 test 전부가 그대로 통과합니다.

### Test (`tools/project-board/tests/test_tmux_control.py`에 추가)
- `test_turning_the_board_off_starts_one_tmux_process_per_board_pane`: Board 1개와 4개일 때 끄기의 tmux process 수 차이가 3(pane당 1)이고, 모든 window의 pane 구성과 옵션이 복원됩니다.
- `test_turning_the_board_on_makes_each_pane_with_two_tmux_processes`: 켜기의 process 수가 window 수와 무관하고 6 이하입니다.
- `test_a_slow_toggle_tells_the_clients_how_far_it_is_and_a_quick_one_says_nothing`: 임계값이 크면 화면에 아무것도 없고, 0이면 pty client 화면에 `Board 끄는 중 1/3`과 `3/3 완료`가 나타납니다. 진행 표시가 tmux process를 늘리지 않고 status 옵션이 바뀌지 않습니다.
- 기존 snapshot test에 새 필드(폭·layout·활성 pane·restore)가 개별 조회 값과 같은지 검사를 더했습니다. 기존 reap test에 `ps`가 한 번만 실행된다는 검사를 더했습니다.

### 검증
- README 표의 `tools/project-board/**` 행: `python -m pytest -q tools/project-board/tests tools/agent-session/tests/test_api_boundary.py` → 206 passed(측정과 동시에 실행, 403초). `integrations/tmux/**`는 바꾸지 않았습니다. 문서 변경(`tools/project-board/README.md`)에는 `tools/test_distribution_boundary.py` 9 passed.
- 근거 재사용: `origin/main`(a9f446a, CR 문서 이동만) merge는 검증 입력을 바꾸지 않아 test를 다시 돌리지 않았습니다. 마지막 commit은 README 문장만 바꿨습니다.
- A/B (Verification 2): 0.8.0(`d027205`)과 이 CR을 번갈아 3회, test 동시 실행 중이 아니라 별도 시간대(load 87~111)에서 쟀습니다. 표의 구간은 t 분포(n=3, t=4.303)의 95% 구간입니다. 표본이 3개라 구간이 넓습니다.

| 동작(process 안, 초) | 0.8.0 | 이 CR | 같은 회차 비 (이 CR/0.8.0) |
| --- | --- | --- | --- |
| 끄기 (Board 6개 제거) | 5.23 [3.98, 6.48], tmux 62회 | 1.02 [0.33, 1.72], 10회 | 0.18, 0.16, 0.24 |
| 켜기 (pane 2개 생성) | 2.05 [1.38, 2.73], tmux 30회 | 0.72 [0.32, 1.12], 8회 | 0.38, 0.29, 0.39 |

  - 이 값은 `toggle_sidebar` 호출을 process 안에서 잰 것입니다. CLI를 통한 end-to-end(개발 tree라 시동 번들이 없음)는 test 동시 실행으로 load 77~90에서 끄기 8.62 → 5.17, 켜기 7.23 → 5.86이었습니다. 이 차이에는 번들 없는 Python 시동이 섞여 약 4초를 차지하며, 설치본의 시동은 위에서 쓴 0.5초 안팎입니다. 이 구간은 줄이지 않았습니다.
  - 남는 시간: 끄기는 Board 하나당 tmux process 1개(load 100에서 약 0.1초)입니다. 여기에 시동 약 0.5초가 더해집니다. 0.5초를 넘으면 진행 상태가 보입니다.

### 수정 제출 (origin/main merge)
- 제출 commit: 7b608e04d225cafd478324df97f345962c79052d
- Leader 요청대로 `origin/main`(be54113, BOARD-023·024 통합)을 `cr/BOARD-022`에 merge했습니다. 충돌은 없었습니다(`test_tmux_control.py`, README는 자동 병합).
- merge commit에서 `python -m pytest -q tools/project-board/tests tools/agent-session/tests/test_api_boundary.py` → 208 passed(422초), `tools/test_distribution_boundary.py` → 9 passed. 측정(A/B)은 merge가 `tmux_control.py`를 바꾸지 않아 다시 하지 않았습니다.
