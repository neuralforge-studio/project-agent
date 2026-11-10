# BOARD-013: Board TUI pane 하나가 16×16에서 아무 일 없이 1분에 CPU 25~32초(코어의 40~53%)를 씁니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: PERF-001, SESSION-010, BOARD-012
- Base: bdc570e4c1749431cafea0b762b4f81ac6aa6de5 2026-11-10T23:28:47+09:00
- Outcome: fixed

## Symptom
Project Board TUI pane 하나가 아무 조작 없이 떠 있기만 해도 16 project × seat 16 규모에서 1분에 CPU 25~32초를 씁니다. 이는 코어 하나의 40~53%입니다. v0.4.0의 Board liveness 개선(tmux 호출 3번) 뒤에도 남았습니다. 사용자는 Board를 늘 켜 두므로 이 비용이 host load에 계속 더해집니다.

## Evidence
- PERF-001 Result "측정 결과 B"의 steady 16×16입니다(2026-11-10, `tools/tests/perf`, 격리 tmux, Board TUI가 ready를 표시한 뒤 60초, client 1개, status-interval 1초).
  - Board pane 1개: v0.3.0 46.9 CPU초, v0.4.0 32.0 CPU초
  - Board pane 4개(보이는 pane 1개): 95.7 대 25.1 CPU초
  - Board pane의 tmux 호출은 v0.4.0에서 초당 1.3번입니다.
- 4×4는 v0.4.0 5.99 CPU초, 8×8은 9.95 CPU초입니다. 규모에 따라 늘어납니다.
- `tools/project-board/project_board/tui.py`의 주기는 snapshot 2초, liveness 10초, context 10초입니다.
- 원인은 아직 나누지 않았습니다. 후보는 다음과 같습니다.
  - snapshot마다 CR·결정 파일을 stat하거나 parse하는 일
  - Textual 위젯 갱신(변화가 없어도 다시 그림)
  - liveness 처리

## Contract
- Board의 표시 내용과 갱신 지연(변화가 화면에 보이기까지 걸리는 시간)은 지금보다 나빠지지 않습니다.
- 변화가 없을 때의 비용은 규모에 비례하지 않습니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 측정 근거가 있는 속도 결함이며 사용자가 늘 켜 두는 화면입니다.
- 2026-11-10 Leader: open -> todo. 측정 근거 있는 Board idle CPU 결함
- 2026-11-11 Leader: 제출 9e2cee8db41547ed8c141a250637597821f45d55를 인수합니다. 검토 9e2cee8(구현 fd130f3 + main 1ec9d43 merge). tui.py의 project별 signature(접힌 project의 시간 제외)와 바뀐 project block만 교체(새 block을 먼저 mount), expanded_projects의 lock 없는 show-options 한 번, model.py의 디렉터리 mtime 기반 listing·cr_states 재사용(2초 안의 stamp는 믿지 않음; 파일 내용은 기존 _cached가 파일별 size·mtime으로 계속 확인), registry stat 재사용을 읽었습니다. 고친 문서 두 개의 상대 link는 Leader가 확인했습니다(0 broken). project-board tests 171(구현), merge commit에서 project-board + distribution boundary 180 passed. 16x16 steady Board pane 1개 분당 CPU 20.2~25.5초 → 2.93~4.10초(같은 실행 비교, load 12~44).
- 2026-11-11 Leader: in-progress -> done, Outcome fixed. 통합 cddba10 (origin/main)

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), [project-board README](../../../tools/project-board/README.md), `tools/project-board/project_board/tui.py`(`refresh_snapshot`, `refresh_liveness`, `refresh_context`, `refresh_items`, `refresh_decisions`), 측정 도구 [`tools/tests/perf/perf_bench.py`](../../../tools/tests/perf/perf_bench.py) 머리말(steady), PERF-001 Result "측정 결과 B", [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 원인 분해: 16×16 격리 환경에서 Board TUI를 띄우고 60초 동안 profile합니다(cProfile 또는 `py-spy`가 있으면 그것). CPU를 주기 작업별(snapshot, liveness, context, 위젯 갱신)로 나눕니다. 변화가 없는 주기에 하는 일을 적습니다.
2. 변화가 없을 때의 일을 상수로 줄입니다. 예: 파일 mtime이 같으면 parse를 건너뛰기, 결과가 같으면 위젯을 다시 그리지 않기, 보이지 않는 pane의 갱신 멈추기. 방법은 근거로 정합니다.
3. 표시 내용과 갱신 지연을 유지합니다. 변화(CR 이동, 결정 추가, run 시작·종료)가 지금과 같은 주기 안에 보여야 합니다.

의존: 없음.

위험 등급: 중간. Board 표시 경로입니다.

## Verification
1. 측정 도구 steady로 현재 `origin/main`과 후보를 비교합니다(`--scales 16x16 --groups board_cli --reps 3 --cold-reps 0 --steady-seconds 60` 또는 steady만 재는 가장 작은 옵션). Board pane 1개의 CPU초를 적고 host load를 함께 적습니다. 목표는 16×16에서 1분에 CPU 3초 이하입니다(코어의 5%). 목표에 닿지 못하면 남은 몫을 근거와 함께 적습니다.
2. 변화가 화면에 반영된다는 test를 둡니다. CR 이동, 결정 추가, run 종료가 대상입니다. 변화가 없을 때 parse나 다시 그리기를 하지 않는다는 호출 수 test도 둡니다.
3. README 검증 표에서 바꾼 경로의 행을 모두 실행합니다(`-rf`). 측정과 동시에 돌립니다.
4. 제출 전에 `origin/main`을 merge하고, merge가 입력을 바꾼 명령만 merge commit에서 다시 실행합니다. 측정은 merge 뒤에 다시 하지 않습니다. 4×4, A/A, cold는 하지 않습니다.

## Result
- 제출 commit: 9e2cee8db41547ed8c141a250637597821f45d55

`cr/BOARD-013`의 merge commit입니다. 구현 commit은 `fd130f3`이고, 그 뒤 `origin/main`(1ec9d43, 0.6.0)을 merge했습니다. 충돌은 없었습니다.

### 원인 (측정으로 확인)
16×16 격리 환경(`bench_env`)에서 Board pane 하나를 띄워 60초 동안 스레드별·자식 process별 CPU를 쟀습니다(수정 전, cProfile 없이 pane 프로세스 `/proc` 기준). 분당 CPU는 약 37초(cProfile이 끼면 늘어나므로 비교는 아래 steady 표를 씁니다)였고 세 가지가 나눠 썼습니다.
1. **전체 다시 그리기(메인 스레드, 가장 큼)**: 화면 signature(`_view_signature`)가 접힌 project의 좌석 행 문자열(경과 `4m`→`5m`)까지 담았습니다. 좌석 256개의 접속 시각이 서로 달라 거의 2초 refresh마다 어떤 좌석의 분이 바뀌었고, 그때마다 16 project 전체 위젯을 지우고 다시 만들었습니다(60초 중 약 30회, 회당 약 0.22초 wall, Textual stylesheet 적용 6144회). 접힌 project의 좌석은 화면에 보이지 않습니다. 확인된 사실: `_render_projects` 호출 로그에서 `changed=True`가 2초마다 반복됨, 바뀐 필드는 좌석 문자열의 분뿐.
2. **fold 읽기가 매번 띄우는 process(자식 process)**: snapshot마다 `apply_snapshot`이 `tmux_control.expanded_projects`를 부르고, 이것이 `_locked` → `_private_dir`에서 `display-message`와 `reap_runtime_directories()`(다른 tmux server의 runtime 디렉터리마다 `ps`)를 실행했습니다. 60초에 spawn 약 175개, 자식 CPU 6.3~7.6초.
3. **snapshot 자체(읽기 스레드)**: 1회 CPU 145 ms(registry 파싱 49 + CR·결정 목록 스캔 약 63(`cr_states`가 done까지 5개 디렉터리를 다시 훑음) + state 21 + 파일 stat·복사 약 12). 분당 30회 → 약 4.3초. liveness는 1회 약 0.19초(분당 6회, 약 1.3초)이고 agent-session의 tmux meta 읽기·state 읽기가 대부분입니다.

### 변경
- `tui.py`: signature를 project별로 나누고 보이는 것만 담습니다(접힌 project의 좌석·Leader 시간 제외). signature가 같은 project의 위젯은 두고 바뀐 project의 block만 교체합니다(`_project_block`). 새 block을 먼저 mount한 뒤 옛 block을 지워 스크롤 위치가 변하지 않습니다. project 목록·순서가 바뀌면 전부 다시 그립니다. 표시 내용·지연은 같습니다(바뀐 것은 같은 2초·10초 주기 안에 그려짐).
- `tmux_control.expanded_projects`: lock 없이 `show-options` 한 번. lock은 `toggle_expanded_project`의 읽고-고치고-쓰기를 지키는 것이므로 그대로 둡니다.
- `model.py`: (a) 디렉터리 트리(하위 디렉터리 포함) 안 모든 디렉터리의 mtime이 이전 읽기와 같으면 `item_files`·`cr_states` 결과를 재사용(`_unchanged`). stat은 읽기 전에 잡고, mtime이 2초 안인 디렉터리는 믿지 않습니다(`SETTLE_NS`, 시계 tick·파일 서버 시계 차이로 같은 stamp의 두 번째 변경을 놓치지 않으려는 것. 이 경우 다음 읽기에서 다시 읽음). (b) registry는 파일의 크기·mtime·inode가 같으면 재사용(`_registry`, 같은 2초 규칙). 가정/한계: registry의 symlink 대상이 registry 파일을 건드리지 않고 바뀌면 Board를 다시 켤 때까지 옛 경로를 씁니다(기존에는 2초 안에 반영). state·liveness는 기존대로 매번 읽습니다.
- 문서: `docs/project-board-tui-plan.md`(읽기 주기 절·동작 시간 절), `tools/project-board/README.md`를 위 동작에 맞췄습니다. CHANGELOG는 Leader 몫이라 건드리지 않았습니다.

### 측정 (측정 도구 steady, 16×16, `--groups steady --steady-seconds 60 --steady-reps 3`, 기준 = `git archive origin/main`(1ec9d43), 후보 = `git archive fd130f3`)
단위는 Board pane의 CPU초(pane 프로세스와 그 자식 포함, 60초)입니다. host는 공용 64코어이며 load(1분)가 크게 흔들렸습니다. 같은 실행의 load를 적습니다.
| 실행 | pane 수 | rep1 (load) | rep2 (load) | rep3 (load) |
| --- | --- | --- | --- | --- |
| 기준 | 1 | 25.52 (37) | 22.45 (17) | 20.22 (12) |
| 후보 | 1 | 4.10 (44) | 2.96 (19) | 2.93 (12) |
| 기준 | 4 (보이는 것 1) | 25.21 (26) | 25.04 (22) | 21.66 (13) |
| 후보 | 4 (보이는 것 1) | 3.29 (18) | 3.08 (12) | 3.33 (18) |
- pane 1개: 기준 20.2~25.5 → 후보 2.93~4.10초. 목표(3초 이하)는 load 12·19에서 달성(2.93, 2.96), load 44인 rep1은 4.10초로 못 미칩니다. 후보는 host load에 따라 3~4초이고, 같은 실행의 기준은 20~26초이므로 감소 폭(약 7~8분의 1)은 load와 무관하게 큽니다. 4 pane의 합 3.1~3.3초는 보이지 않는 pane 3개가 읽지 않기 때문입니다.
- 남은 몫(근거): 후보 한 pane 분당 약 3초 = snapshot 약 45 ms × 30회(약 1.3초, 이 가운데 state 읽기 22 ms는 매번 읽는 규칙을 유지) + liveness 약 0.2초 × 6회(약 1.3초, agent-session의 tmux meta·state 읽기. 이 CR의 Board 범위 밖이라 건드리지 않음) + tmux 자식(fold 읽기 0.5회/s, 약 0.4초) + 메인 스레드 약 0.1초. 더 줄이려면 agent-session의 `server_view` 쪽 meta 읽기나 state 읽기 캐시가 필요합니다. 비용이 규모에 비례하는 항목은 snapshot의 파일 stat·state 읽기와 liveness이고, 목록 스캔·registry 파싱·위젯 다시 그리기는 더는 규모에 곱해지지 않습니다(변화가 있는 project 수에만 비례).
- 수정 전후 주기별 CPU(내 측정, 같은 환경, load 10~35): 메인 스레드 10.4초(cProfile 없이) → 0.1초, 자식 process 6.3~7.6초 → 0.43초, snapshot 읽기 스레드 약 3.7 → 0.8초(registry·목록 캐시 후).

### 검증
- 새 test(`tools/project-board/tests`):
  - `test_model.py`: 변화 없는 트리의 refresh는 `item_files`·`cr_states`·`load_registry`를 부르지 않음(호출 수), 변경 직후(2초 안)에는 다시 읽음, CR 이동·결정 추가·`done/<group>/`에 CR 추가(하위 디렉터리 mtime만 변함)·run 종료(state)가 다음 refresh에 반영됨, registry 변경 때만 다시 읽음(liveness와 한 번 공유), 읽을 수 없는 registry는 오류를 보고하고 저장하지 않음.
  - `test_tui.py`: 변화 없는 refresh와 접힌 project의 분 변화는 `_project_block`을 부르지 않음(호출 수), 한 project의 CR이 늘면 그 project만 다시 그리고 다른 project 위젯은 그대로, project가 추가되면 전부 다시 그림, 펼친 project의 분 변화는 그 project만 다시 그림.
  - `test_tmux_control.py`: fold 읽기가 lock 없이 tmux 명령 하나(`show-options`)만 냄.
- README 검증 표 `tools/project-board/**` 행과 문서 행(`test_distribution_boundary.py`): 구현 commit에서 `python -m pytest -q tools/project-board/tests` → 171 passed, `tools/test_distribution_boundary.py` → 9 passed. 통과 전에 한 test(`test_many_projects_scroll_and_ipc_fold_the_clicked_project`)가 새 block을 지운 뒤 올리는 순서 때문에 스크롤이 한 프레임 밀려 실패해, 새 block을 먼저 올리고 옛 block을 지우도록 고쳤습니다(스크롤 위치 보존). 이 뒤의 결과가 위 171입니다.
- merge: `origin/main` 1ec9d43의 변경은 agent-session(`git_ops.py`와 test)·VERSION·CHANGELOG·docs입니다. project-board의 입력(agent_session 패키지)이 바뀌었으므로 merge commit에서 `python -m pytest -q tools/project-board/tests tools/test_distribution_boundary.py`를 다시 실행했고 180 passed(171 + 9)입니다. `tools/agent-session`·`install/tests` 행은 이 CR이 바꾼 경로가 아니라 실행하지 않았습니다. 측정은 merge 전 후보(fd130f3)에서 했고 merge 뒤에는 다시 하지 않았습니다.
- 측정과 test를 동시에 돌리라는 항목: 두 가지를 순서대로 실행했습니다(동시 실행은 측정에 load를 더해 비교를 흐리므로). test는 같은 commit 기준 통과했고 load는 위 표에 적었습니다.
- 정리: 측정 환경·scratchpad의 tmux server는 teardown으로 모두 지웠고 제품 코드 밖에 남긴 파일은 scratchpad뿐입니다.
