# BOARD-027: Board sidebar에 project별 cron 작업 수 C:n을 보이고, 누르면 cron 창을 엽니다

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S3

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

## Disposition
- 2026-11-12 Leader: 구현한다. 사용자 결정 D-20261111-04 decided C와 사용자 후속 요청("그냥 cron이 몇개 있는지만 보이는게 더 깔끔할까? D:?  C:?", 원문은 Symptom)입니다. 남은 시간의 반올림, `C:0`·`C:!` 색, cron 창의 틀(CR 창 재사용)은 승인한 요청 안의 세부라서 Leader가 정했습니다. BOARD-018(Rust sidebar)을 통합한 뒤 todo로 옮겨 시작합니다.

## Implementation
읽을 문서: [Board TUI 계획](../../project-board-tui-plan.md) 2·3·5절, [동작 명세 7절 cron](../../project-team/spec.md#cron), `tools/agent-session/agent_session/cron.py`, `tools/agent-session/tests/fixtures/cron_next_run.json`, `tools/project-board/rust/`(BOARD-018 통합본)와 BOARD-018 CR Result, BOARD-022·BOARD-025 CR(process 수, 떠 있는 창 알림), `tools/project-board/README.md`, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. `agent_session.api`에 project의 cron 목록을 읽는 공개 함수를 더합니다(`cron.listing` 재사용, `ls`와 같은 값). API 경계 test에 반영합니다.
2. Rust sidebar: `crontab -l` 한 번으로 모든 project 구역을 읽고(10초 주기, 가시성 규칙 동일), 작업 수와 가장 가까운 다음 실행을 계산합니다. `D:n C:n` 표시, 색, tooltip, 클릭(`C:n` ≥ 1이면 cron 창 열기, BOARD-025 규약으로 떠 있는 창에 알리기)을 더합니다.
3. Rust 일치 test: `cron_next_run.json`의 `next_run`·`invalid` 전부, 구역 해석(정상·없음·빈 crontab·깨진 구역·다른 project 구역·구역 밖 사용자 줄)이 Python `cron.split`·`listing`과 같은지. 남은 시간 문자열의 경계(30초, 59분, 60분, 61분, 23시간 59분, 24시간, 47시간)를 손으로 쓴 기대값으로 확인합니다.
4. Python cron 창(`project-board` 하위 명령): CR 창 틀 재사용, 작업 목록과 본문, `◀ project ▶`, 작업 없음, 마지막 실행 없음. Textual test로 확인합니다.
5. process 수 test: `test_sidebar_binary.py`의 shim 방식으로 `crontab` 호출이 10초 주기에 하나이고 2초 주기에는 없으며, 보이지 않는 동안 0인지 셉니다.
6. 문서: TUI 계획 2절(데이터 원본 표에 cron 행), 3절(화면 예시, 색, tooltip, 클릭 표), 5절(cron 창 알림), project-board README, 필요하면 명세 7절의 Board 읽기 문장.

의존: BOARD-018(Rust sidebar) 통합 뒤 시작합니다. 시작 시점의 `origin/main` 기준입니다.

위험 등급: 중간(Rust·Python 두 언어의 같은 규칙, 새 창).

## Verification
1. README 검증 표에서 바꾼 경로의 행 명령 전부를 제출 commit에서 실행합니다(BOARD-018 통합 뒤의 표 기준):
   - `tools/project-board/rust/**`: `(cd tools/project-board/rust && cargo test --offline --locked)`, `python -m pytest -q tools/project-board/tests`, 네 번째 명령(`integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py`). `Cargo.toml`·`Cargo.lock`·`.cargo/config.toml`을 바꾸면 `python -m pytest -q -n 8 install/tests`도.
   - `tools/project-board/**`: `python -m pytest -q tools/project-board/tests`, `python -m pytest -q tools/agent-session/tests/test_api_boundary.py`.
   - `tools/agent-session/**`(`agent_session/api.py`): `python -m pytest -q -n 8 tools/agent-session/tests`, `python -m pytest -q tools/project-item/tests`, `python -m pytest -q tools/project-board/tests`, `python -m pytest -q -n 8 install/tests`.
   - 문서: 고친 문서의 상대 link 검사, `tools/test_distribution_boundary.py`. `docs/project-team/spec.md`를 바꾸면 `python -m pytest -q tools/agent-session/tests/test_remote.py`도.
2. 화면: 실제 등록에서 `D:n C:n` 줄, `C:1` tooltip, `C:0`(cron 없는 project), cron 창(작업 있음·없음, 좁은 폭)을 `tmux capture-pane -p -e`로 `/primehome/swain/tmp/board027/`에 저장하고 Result에 목록을 적습니다.
3. 여는 시간: 16×16 `bench_env`에서 sidebar ready를 기준(BOARD-018 통합본)과 번갈아 3회 잽니다(`tools/tests/perf`의 기존 도구, test와 병렬). 늘지 않아야 합니다. 측정 도구가 바뀌어도 진행 중인 측정을 다시 시작하지 않습니다.
