# BOARD-027: Board sidebar에 project별 cron 작업 수 C:n을 보이고, 누르면 cron 창을 엽니다

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S3
- Base: 6b7b41bad5e0cd15ae157ab3e71f4f2fcb11dee7 2026-11-12T11:40:17+09:00
- Outcome: fixed

## Symptom
SESSION-015로 project마다 사용자 crontab에 project 구역이 생겼습니다(지금은 `check` 작업 하나). Board sidebar에서는 project에 cron 작업이 몇 개 있는지, 다음 실행이 언제인지, 마지막 실행이 성공했는지 볼 수 없습니다. 보려면 `agent-session cron ls --project X`를 직접 실행해야 합니다.

사용자 요청과 결정(D-20261111-04, decided C):
- 답: "3. C, side bar에도 추가해줘. project 밑에 D:? 위에 남은 시간만 보여줘. 가장 큰 단위로 2h | 2d | 3m 이걸 클릭하면 board가 보이는거야. 무슨 말인지 이해가 될까~!?"
- 이어서 표시를 바꿨습니다: "그냥 cron이 몇개 있는지만 보이는게 더 깔끔할까? D:?  C:?" Leader가 동의했습니다. 남은 시간은 tooltip으로 옮깁니다([SESSION-015](../done/SESSION-015-project-cron-crontab-project-session-cron-crontab.md) Symptom에 기록).

## Evidence
- crontab 구역의 형식과 다음 실행 규칙은 [동작 명세 7절 cron](../../project-team/spec.md#cron)이 소유합니다. 이 형식이 Board와의 계약이고, 명세는 "Board는 이 명령을 부르거나, `crontab -l`을 직접 읽어 위 형식을 해석하고 위 규칙으로 다음 실행을 계산할 수 있습니다"라고 적습니다.
- 다음 실행 규칙의 원본은 `tools/agent-session/agent_session/cron.py`의 `Schedule.next_run`이고, 다른 언어의 일치 사례는 `tools/agent-session/tests/fixtures/cron_next_run.json`(손으로 쓴 `next_run` 16건, `invalid` 15건)입니다.
- `cron.listing(project, crontab, summary=...)`이 `ls`·`--summary` 값(`{count, next_run}`, 작업마다 `{id, schedule, description, command, next_run, last_run}`)을 만듭니다. 마지막 실행 결과는 `<base>/agent/cron/<id>.json`입니다. `agent_session.api`에는 아직 cron 읽기가 없습니다. Board는 `agent_session.api`로만 agent-session을 읽습니다(`tools/agent-session/tests/test_api_boundary.py`).
- `agent-session cron ls`를 project마다 부르면 2초·10초 주기마다 Python process가 project 수만큼 생깁니다. BOARD-022는 주기 읽기와 클릭마다 생기는 process 수를 줄이고 test로 셉니다.
- BOARD-018(Rust sidebar)이 sidebar를 Rust로 옮깁니다. 이 CR은 그 통합 뒤의 Rust sidebar와 Python 창(CR·결정 창)을 고칩니다. BOARD-025는 떠 있는 CR·결정 창에 규약 socket으로 새 내용을 알립니다([Board TUI 계획 5절](../../project-board-tui-plan.md#열려-있는-창에-새-내용-알리기-board-025)).
- 지금 `D` 색 규칙(열린 결정이 있으면 빨강, `D:0`·`-`·`!`은 노랑)은 사용자가 유지하기로 했습니다(BOARD-018 Disposition: "오호!! 몰랐네. 오케이 유지해줘 현재 상태."). 이 CR은 `D` 색을 바꾸지 않습니다.

## Contract
1. **표시**: sidebar의 project마다 `D:n` 줄을 `D:n C:n`으로 그립니다. `C`는 그 project 구역의 작업 수입니다. 구역이 없거나 crontab이 비어 있으면(`no crontab for`) `C:0`입니다.
   - `C:n`(n ≥ 1)은 누를 수 있는 보통 색, `C:0`은 흐린 색(빈 seat의 `-`와 같은 회색)이고 눌러도 아무것도 열지 않습니다.
   - crontab을 읽지 못하거나(`crontab` 명령 없음 포함) 그 project의 구역이 깨졌으면(명세 7절의 `cron_invalid` 조건) `C:!`이고 `D:!`와 같은 색입니다. 다른 project의 표시는 영향받지 않습니다(구역이 깨진 경우).
2. **Tooltip**: `C:n`(n ≥ 1) 위에 mouse를 올리면 `cron N개, 다음 실행 3m 뒤`처럼 가장 가까운 다음 실행까지 남은 시간을 단위 하나로 보입니다.
   - 남은 시간 = 가장 가까운 `next_run`(local 분) − 지금. 분 단위로 올린 뒤 1440분 이상이면 `Nd`, 60분 이상이면 `Nh`, 그 밖은 `Nm`이고 각 단위에서 내립니다(예: 61분 → `1h`, 47시간 → `1d`, 30초 → `1m`).
   - 다음 실행이 없으면(8년 안에 일치 없음) `다음 실행 없음`입니다. `C:0`과 `C:!`의 tooltip은 각각 `cron 작업 없음`, 읽기 실패 이유입니다.
   - 다음 실행은 명세의 규칙(`Schedule.next_run`)과 같은 결과를 냅니다.
3. **cron 창**: `C:n`(n ≥ 1)을 누르면 클릭한 client에 그 project의 cron 창이 뜹니다. 읽기 전용입니다(작업 추가·삭제는 `agent-session cron add|rm`).
   - 작업마다 ID, 설명, 일정(cron 식), 다음 실행(local 시각과 남은 시간), 마지막 실행(시각, 성공·실패, `result`)을 보입니다. 마지막 실행이 없으면 `아직 없음`입니다. 명령 전체는 본문(선택한 작업)에서 볼 수 있습니다.
   - 창의 틀은 CR 창을 따릅니다: 맨 위 `◀ project ▶`(등록된 모든 project를 돌고, 작업이 없는 project는 `작업 없음` 한 줄), 닫기 키, 좁은 폭의 목록·본문 전환. 이미 떠 있는 cron 창이 있으면 BOARD-025 규약대로 그 창에 알려 내용을 바꿉니다.
   - 창은 열 때와 project를 옮길 때 읽습니다.
4. **읽기 비용**: sidebar는 모든 project의 cron을 `crontab -l` process 하나로 읽습니다. project마다 process를 만들지 않고, 2초 파일 읽기에 process를 더하지 않습니다(10초 실행 상태 읽기와 같은 주기·같은 가시성 규칙). sidebar가 처음 보이기까지의 시간이 늘지 않습니다(첫 그림이 crontab 읽기를 기다리지 않아도 됩니다).
5. **원본 하나**: 구역 형식과 다음 실행 규칙은 `agent_session/cron.py`가 소유합니다. Rust의 읽기는 그 규칙을 따르고 일치 test가 지킵니다(fixture를 복사하지 않고 그 파일을 읽습니다). Python cron 창은 `agent_session.api`에 더하는 공개 함수로 읽고 `agent_session.cron`을 직접 import하지 않습니다.
   - Rust의 cron 읽기는 [제품 지도](../../project-team/README.md)의 "예외: Rust sidebar와 Python이 같은 규칙을 읽습니다" 표에 행으로 더합니다(Python 원본, Rust 구현, 일치 test 위치).
6. **창 알림 client의 일치**: Rust `rust/src/window.rs`와 Python `project_board.tmux_control._reuse`는 같은 규약(TUI 계획 5절)의 두 client입니다. 같은 시나리오에서 두 client가 같은 결과를 내는지 비교하는 일치 test를 둡니다. 시나리오는 같은 종류의 창, 다른 종류, 시작 중, `ok`·`busy`·`invalid`·`closing`·JSON 아님, 죽은 창이고, cron 창 종류도 포함합니다. 이 test는 Python 쪽이 바뀌면 실패해야 합니다(`test_rust_switch.py`처럼 Python 결과를 기준으로 삼음).
   - 근거: BOARD-018 검토(2026-11-12)에서 Rust 창 알림 test가 Python과 비교하지 않고 가짜 창만 상대한다는 빈틈을 찾았습니다. 읽기 규칙(`test_rust_equivalence.py`)과 전환(`test_rust_switch.py`)은 Python과 비교합니다.

## Disposition
- 2026-11-12 Leader: 구현한다. 사용자 결정 D-20261111-04 decided C와 사용자 후속 요청("그냥 cron이 몇개 있는지만 보이는게 더 깔끔할까? D:?  C:?", 원문은 Symptom)입니다. 남은 시간의 반올림, `C:0`·`C:!` 색, cron 창의 틀(CR 창 재사용)은 승인한 요청 안의 세부라서 Leader가 정했습니다. BOARD-018(Rust sidebar)을 통합한 뒤 todo로 옮겨 시작합니다.
- 2026-11-12 Leader: BOARD-018을 통합했습니다(2bcd290). Contract 5에 중복 예외 표의 행을 더하고, Contract 6(창 알림 client 일치 test)을 더했습니다. 근거는 BOARD-018 검토에서 찾은 빈틈과 사용자 지시 "판단의 주요관점은 ** Root cause & SSOT **"입니다. Rust와 Python 두 곳에 있는 규칙은 Python이 바뀌면 test가 Rust 쪽 수정을 요구해야 합니다.
- 2026-11-12 Leader: open -> todo.
- 2026-11-12 Leader 검토(제출 452744a17cb31e10acf5db1efcff13b0862e8034): 인수.
  - 계약 1~4: `D:n C:n`, `C:0`·`C:!`·`C:-`(첫 읽기 전, Worker가 정한 세부), tooltip, cron 창(목록·본문·좁은 폭·작업 없음), `crontab -l` 10초 주기 하나(2초 읽기와 보이지 않을 때는 0)를 화면 capture와 process 수 test로 확인했습니다.
  - 계약 5: Rust `cron.rs`가 `cron_next_run.json`을 직접 읽고, `test_rust_cron.py`가 crontab 30종 × 시각 5개를 Python `cron.listing`과 비교합니다. Python 창은 새 공개 함수 `agent_session.api.cron_listing`으로 읽습니다. 제품 지도 중복 예외 표에 cron 행이 있습니다.
  - 계약 6: `test_rust_window_notify.py`가 같은 server·같은 창 process에서 Python `_reuse`를 기준으로 Rust `window::tell`을 63건 비교합니다. 이 test가 Python client의 결함 둘(객체가 아닌 응답에서 `AttributeError`, `ok`의 참 값을 성공으로 봄)을 찾아 고쳤습니다.
  - 검증: README 표의 해당 행을 모두 실행했습니다. project-board 1건 실패는 새 test의 기다림 조건 결함이고, 그 조건만 고쳐 그 파일의 cron test를 다시 돌렸습니다. merge(SESSION-017) 뒤의 재실행 범위 판정도 맞습니다. 여는 시간은 늘지 않았습니다(`same`).
  - 통합은 0.11.1(SESSION-017) tag 뒤에 합니다. 0.11.1의 검증 tree에 이 변경이 섞이지 않게 하기 위해서입니다.
- 2026-11-12 Leader: 제출 452744a17cb31e10acf5db1efcff13b0862e8034를 인수합니다.
- 2026-11-12 Leader: in-progress -> done, Outcome fixed. 통합 bc2605c (origin/main)

## Implementation
읽을 문서: [Board TUI 계획](../../project-board-tui-plan.md) 2·3·5절, [동작 명세 7절 cron](../../project-team/spec.md#cron), `tools/agent-session/agent_session/cron.py`, `tools/agent-session/tests/fixtures/cron_next_run.json`, `tools/project-board/rust/`(BOARD-018 통합본)와 BOARD-018 CR Result, BOARD-022·BOARD-025 CR(process 수, 떠 있는 창 알림), `tools/project-board/README.md`, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. `agent_session.api`에 project의 cron 목록을 읽는 공개 함수를 더합니다(`cron.listing` 재사용, `ls`와 같은 값). API 경계 test에 반영합니다.
2. Rust sidebar: `crontab -l` 한 번으로 모든 project 구역을 읽고(10초 주기, 가시성 규칙 동일), 작업 수와 가장 가까운 다음 실행을 계산합니다. `D:n C:n` 표시, 색, tooltip, 클릭(`C:n` ≥ 1이면 cron 창 열기, BOARD-025 규약으로 떠 있는 창에 알리기)을 더합니다.
3. Rust 일치 test: `cron_next_run.json`의 `next_run`·`invalid` 전부, 구역 해석(정상·없음·빈 crontab·깨진 구역·다른 project 구역·구역 밖 사용자 줄)이 Python `cron.split`·`listing`과 같은지. 남은 시간 문자열의 경계(30초, 59분, 60분, 61분, 23시간 59분, 24시간, 47시간)를 손으로 쓴 기대값으로 확인합니다.
4. Python cron 창(`project-board` 하위 명령): CR 창 틀 재사용, 작업 목록과 본문, `◀ project ▶`, 작업 없음, 마지막 실행 없음. Textual test로 확인합니다.
5. process 수 test: `test_sidebar_binary.py`의 shim 방식으로 `crontab` 호출이 10초 주기에 하나이고 2초 주기에는 없으며, 보이지 않는 동안 0인지 셉니다.
6. 문서: TUI 계획 2절(데이터 원본 표에 cron 행), 3절(화면 예시, 색, tooltip, 클릭 표), 5절(cron 창 알림), project-board README, 제품 지도의 중복 예외 표(cron 읽기 행, 창 알림 행의 검증 문장), 필요하면 명세 7절의 Board 읽기 문장.
7. 창 알림 일치 test(Contract 6): 같은 fixture tmux server와 같은 창 process에서 Python `_reuse`와 Rust `window::tell`의 결과(알림 여부, 시작 여부, 오류 알림, title)를 비교합니다.

의존: BOARD-018(Rust sidebar)은 통합됐습니다(2bcd290). 시작 시점의 `origin/main` 기준입니다. TMUX-004(쓸 tmux를 정하는 원본)가 이 CR보다 먼저 통합되면 `origin/main`을 merge해서 Rust의 tmux 호출이 그 규칙을 따르게 합니다.

위험 등급: 중간(Rust·Python 두 언어의 같은 규칙, 새 창).

## Verification
1. README 검증 표에서 바꾼 경로의 행 명령 전부를 제출 commit에서 실행합니다(BOARD-018 통합 뒤의 표 기준):
   - `tools/project-board/rust/**`: `(cd tools/project-board/rust && cargo test --offline --locked)`, `python -m pytest -q tools/project-board/tests`, 네 번째 명령(`integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py`). `Cargo.toml`·`Cargo.lock`·`.cargo/config.toml`을 바꾸면 `python -m pytest -q -n 8 install/tests`도.
   - `tools/project-board/**`: `python -m pytest -q tools/project-board/tests`, `python -m pytest -q tools/agent-session/tests/test_api_boundary.py`.
   - `tools/agent-session/**`(`agent_session/api.py`): `python -m pytest -q -n 8 tools/agent-session/tests`, `python -m pytest -q tools/project-item/tests`, `python -m pytest -q tools/project-board/tests`, `python -m pytest -q -n 8 install/tests`.
   - 문서: 고친 문서의 상대 link 검사, `tools/test_distribution_boundary.py`. `docs/project-team/spec.md`를 바꾸면 `python -m pytest -q tools/agent-session/tests/test_remote.py`도.
2. 화면: 실제 등록에서 `D:n C:n` 줄, `C:1` tooltip, `C:0`(cron 없는 project), cron 창(작업 있음·없음, 좁은 폭)을 `tmux capture-pane -p -e`로 `/primehome/swain/tmp/board027/`에 저장하고 Result에 목록을 적습니다.
3. 여는 시간: 16×16 `bench_env`에서 sidebar ready를 기준(BOARD-018 통합본)과 번갈아 3회 잽니다(`tools/tests/perf`의 기존 도구, test와 병렬). 늘지 않아야 합니다. 측정 도구가 바뀌어도 진행 중인 측정을 다시 시작하지 않습니다.

## Result

- 제출 commit: 452744a17cb31e10acf5db1efcff13b0862e8034

`origin/cr/BOARD-027`에 push했습니다. 시작 base 위에 `origin/main`(SESSION-017 통합, 6d2421e)을 merge했고 충돌은 없었습니다.

### 변경
- **Rust sidebar**: `D:n C:n`을 한 줄에 그립니다(`ui.rs`). `C:n`(n ≥ 1)은 보통 색이고 누를 수 있습니다. `C:0`은 빈 seat와 같은 회색이고 눌러도 열지 않습니다. `C:!`는 `D:!`와 같은 색이며(crontab을 읽지 못함 = 모든 project, 구역이 깨짐 = 그 project만) 열지 않습니다. 첫 crontab 읽기 전에는 `C:-`(회색, tooltip `cron을 읽는 중입니다`)입니다. 이 값은 계약에 없던 세부라서 정했습니다. tooltip은 `cron N개, 다음 실행 3m 뒤`·`다음 실행 없음`·`cron 작업 없음`·읽기 실패 이유이고 보여 줄 때의 지금으로 다시 계산합니다(저장한 것은 일정 문자열뿐). 클릭은 `open-cron`이거나 떠 있는 cron 창에 알림입니다(`window.rs`, 요청 `{"kind":"cron","project":P}`).
- **읽기(계약 4)**: `crontab -l` 하나로 모든 project를 10초 주기로 읽습니다(`app.rs`의 `cron_loop`, 자기 thread, 가시성 규칙은 실행 상태 읽기와 같음). 2초 파일 읽기에는 process를 더하지 않고 첫 그림은 기다리지 않습니다.
- **원본 하나(계약 5)**: `rust/src/cron.rs`(Schedule·next_run·구역 해석·남은 시간), `rust/src/data/crontab.rs`(`crontab -l`). 제품 지도의 중복 예외 표에 행을 더했습니다. Python 창은 `agent_session.api.cron_listing`(새 공개 함수, `__all__`·명세 5절 표·API 경계 test)으로 읽고 `agent_session.cron`을 import하지 않습니다.
- **Python cron 창**: `project-board cron`·`open-cron`, `tui.CronPopupApp`(`_ListWindow`는 CR 창이 갖던 틀을 둘이 나눠 쓰도록 꺼낸 것이라 `CRPopupApp`의 동작은 같고 CR test가 그대로 통과), `window_link.KINDS`에 `cron`, `model.cron_view`·`remaining_text`.
- **창 알림 일치(계약 6)**: `test_rust_window_notify.py`가 같은 tmux server·같은 fake 창 process에서 Python `_reuse`(앞의 `_window_pane` 포함)와 Rust `window::tell`(새 숨은 하위 명령 `tell`)을 21개 시나리오 × 요청 종류 `cr`·`decision`·`cron`으로 비교합니다(63건 중 느린 한 시나리오는 cron만). 비교 대상은 창이 받은 요청, 결과(done·busy+메시지·fallback), 마지막 title입니다. 기대값은 Python 쪽이며 Python이 바뀌면 실패합니다.
  - **이 test가 Python client의 결함 둘을 찾았고 고쳤습니다**: (1) 응답이 JSON 객체가 아니면(`[]`·`null`·문자열) `_reuse`가 `AttributeError`로 죽었습니다. `window_link.send`가 이제 `OSError`로 바꿔 창을 다시 시작합니다. (2) `ok`가 `true`가 아닌 참 값(`1`)을 성공으로 봤습니다. 규약은 `{"ok": true}`이고 Rust는 그렇게 읽으므로 `is True`로 맞췄습니다.
  - 시작 중인 창(link 없음)은 Python이 기다리고 Rust는 `project-board`에 맡기는 의도된 차이라서, 끝내 뜨지 않는 창(둘 다 fallback)으로 비교합니다.

### 검증(제출 commit의 입력 기준)
| 명령 | 결과 |
| --- | --- |
| `(cd tools/project-board/rust && cargo test --offline --locked)` | 83 passed (단위 test 7건 추가: 계약 3의 `cron_next_run.json` `next_run` 16건·`invalid` 15건을 그 파일에서 직접 읽음, 구역 해석, 남은 시간 경계 18건은 `tests/fixtures/cron_remaining.json`에서 읽음, `C` 상태·색·tooltip, 클릭 좌표. golden 23개를 다시 그렸고 바뀐 줄이 `D` 줄뿐임을 확인했으며 `basic_cron`·`basic_hover_cron` 2개를 더함) |
| `python -m pytest -q tools/project-board/tests` | 459 passed, 1 failed. 실패는 부하 때문에 읽는 중 문구를 기다림 조건으로 삼은 새 test의 결함이라 조건을 고쳤고, 그 파일의 cron test 14건을 6회 다시 돌려 통과했습니다. 전체를 다시 돌리지는 않았습니다. 포함: `test_rust_cron.py` 31건(crontab 30종 × now 5개를 Python `cron.listing`과 Rust `dump cron`에 같은 입력으로 비교: 정상·없음·빈 crontab·깨진 구역 11종·다른 project 구역·구역 밖 사용자 줄), `test_rust_window_notify.py`, `test_sidebar_binary.py`(crontab shim으로 실제 crontab을 읽지 않음. `C:n` 표시·`C:!`·tooltip·클릭·떠 있는 창 알림, process 수: `crontab -l`은 20초 동안 3~4회(10초 주기 + 첫 읽기)이고 2초 읽기마다는 없음, 보이지 않는 동안 0) |
| `python -m pytest -q -n 8 tools/agent-session/tests` | 932 passed (merge 전). merge 뒤에는 `test_api_boundary.py`·`test_cron.py` 68건만 다시 돌렸습니다(SESSION-017이 바꾼 `lifecycle.py`·`providers/claude.py`는 이 변경의 입력과 겹치지 않음) |
| `python -m pytest -q tools/project-item/tests` | 141 passed |
| 네 번째 명령(`integrations/tmux` … `tools/test_tmux_test_server.py`) | 144 passed (merge 전). merge 뒤 `test_release_files.py`·`test_distribution_boundary.py` 11 passed |
| `python -m pytest -q -n 8 install/tests` | 316 passed, 2 skipped(`api.py`를 바꿔 실행) |
| `python -m pytest -q tools/agent-session/tests/test_remote.py` | 61 passed(`spec.md`를 바꿔 실행) |
| 문서 상대 link 검사(바꾼 md 5개) | 깨진 link 0 |

`Cargo.toml`·`Cargo.lock`·`.cargo/config.toml`은 바꾸지 않았습니다.

### 화면 (`/primehome/swain/tmp/board027/`)
`tmux capture-pane -p -e`로 저장했습니다. 등록은 실제 등록(10개 project)이고 격리 tmux server에서 돌렸습니다. 실제 crontab에는 `agent`의 작업이 없어서 `crontab`만 shim(`shim/crontab.txt`: 실제 crontab에 `agent`의 작업 2개를 더한 것)으로 바꿨습니다. 마지막 실행은 실제 `<base>/agent/cron/check.json`입니다.
- `sidebar-C-lines.txt`: `D:2   C:2`, 실제 crontab 그대로인 project는 `C:1`·`C:0`
- `sidebar-C1-tooltip.txt`: `cron 2개, 다음 실행 7m 뒤`
- `sidebar-C0-tooltip.txt`: `cron 작업 없음`
- `cron-window-jobs.txt`(100×30), `cron-window-no-jobs.txt`(`cron 0개`·`작업 없음`), `cron-window-narrow-detail.txt`·`cron-window-narrow-list.txt`(60×24의 본문과 `목록` 전환)
- `real-crontab.txt`: 비교용 실제 crontab

### 여는 시간 (16×16 `bench_env`, `tools/tests/perf`, 번갈아 3회, test와 병렬이라 host load 80~180)
`board_sidebar_ready` warm 중앙값(초, BASE → 이 변경): **3.36 [2.36–4.37] → 2.10 [1.51–3.98]**, 비 `0.62 [0.35–1.68]`, 판정 `same`(늘지 않음). 회별 값은 BASE 2.36·3.36·4.37, 이 변경 1.51·3.98·2.10. tmux 호출 수 0 → 0. 결과 원본은 scratchpad의 `perf/out/summary.md`입니다.

### 알려 드릴 점
- `D` 버튼이 줄 전체 폭이 아니라 `O/T/I`처럼 글자 폭이 됐습니다(`C`와 한 줄이라서). TUI 계획 3절의 Textual 0.7.1과 다른 점 목록에 적었습니다.
- 테스트용으로 숨은 하위 명령 `project-board-sidebar tell`(창 알림 일치)와 `dump cron`(구역 해석 일치)을 더했습니다.
- TMUX-004는 아직 통합되지 않아 Rust의 tmux 호출을 그 규칙에 맞추는 일은 하지 않았습니다(통합 뒤 `origin/main` merge로 처리).
- 문서: TUI 계획 2·3·5절, project-board README, 제품 지도(CLI 목록, 중복 예외 표의 cron 행과 검증 문장), 명세 5절 `cron_listing` 행과 7절 Board 읽기 문장, CHANGELOG(Unreleased).
