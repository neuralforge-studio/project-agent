# BOARD-028: Board sidebar가 자기가 import한 release와 현재 설치본이 다르면 재시작이 필요하다고 표시합니다(agent 요청)

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S3
- Requester: agent, /primehome/swain/Utils/agent/agent.base, 2026-11-12
- Base: a78e888123c42988f11a3f76de0655f0e8f7a10d 2026-11-12T18:17:47+09:00
- Outcome: fixed

## Symptom
Board sidebar process는 시작할 때 import한 코드를 계속 씁니다. 설치본(`~/.local/lib/project-agent/current`)이 새 release로 바뀌어도 이미 떠 있는 sidebar는 옛 코드로 판정하고 표시합니다. 지금은 사람이 기억해서 Board를 끄고 다시 켭니다(agent Leader 메모리 `restart-board-after-tool-merge`). 옛 Board가 옛 검사로 잘못된 상태를 보인 적이 있습니다.

## Evidence
- 2026-11-06: 오래 떠 있던 옛 Board가 옛 검사로 `registry_invalid`를 표시했습니다(agent SESSION-013 통합 뒤).
- 2026-11-09: 새 Board 코드가 들어온 뒤에도 11-07에 띄운 옛 Board가 계속 돌았습니다.
- 2026-11-12 기준 `current`는 `releases/0.10.0-e0eb77d100fd`입니다. 실행 중 run은 0.7.0·0.10.0 등 서로 다른 release를 고정해 씁니다. agent TEAM-005 Result 3절 R14가 이 항목을 도구 쪽 후보로 골랐습니다(`/primehome/swain/Utils/agent/agent.base/docs/cr/open/TEAM-005-project-team-project-item-hook-mod.md`).

## Contract
결정 D-20261112-01(decided C)로 정한 계약입니다. agent가 쓴 요청 원문은 아래 "요청 원문"에 그대로 둡니다.

1. **자동 전환**: sidebar는 자기 release와 설치본 `current`의 release가 다르면, 같은 pane에서 새 release의 sidebar binary로 자기를 바꿔 실행합니다. pane과 그 크기·위치는 그대로이고 화면 배치가 바뀌지 않습니다. 접힘 상태처럼 tmux option에 있는 상태도 그대로 이어집니다. click socket, SIGUSR1, `mark_ready` 규약은 새 process에서도 같습니다.
2. **전환하지 못할 때**: 새 binary가 없거나, 실행할 수 없거나, 실행에 실패하면 옛 코드로 계속 그립니다. 그리고 "재시작 필요", 이유, 다시 켜는 방법(prefix `B` 두 번 등)을 보입니다. release가 같으면 아무것도 보이지 않습니다.
3. **release를 판단하는 원본은 하나**: 비교는 설치본의 release 식별 하나로 합니다(release 디렉터리, 그 안의 `VERSION`과 commit). 이 원본이 무엇인지 설치 계약에 적습니다.
   - binary의 `--version`은 지금 release(0.11.0)가 아니라 crate 버전(0.1.0)을 냅니다. release와 다른 버전 값이 따로 있으면 정리합니다.
   - `current` 밖에서 실행한 sidebar(개발 checkout)는 전환하지 않습니다.
4. **감지 비용**: 지금의 주기 읽기에 process를 더하지 않습니다. 첫 그림의 시간도 늘지 않습니다.
5. **떠 있는 Board 창**: CR·결정·cron 창(Python, BOARD-025 재사용)도 오래 떠 있으므로 같은 원인을 가집니다. release가 다른 창은 클릭 때 재사용하지 않고 새 release로 다시 시작합니다. 전환한 sidebar가 여는 창과 popup은 새 release의 `project-board`로 열립니다.
6. 설치기의 안내("Runs that are up keep the release they started with. Reopen Project Board to use the new release."), TUI 계획, 설치 계약의 관련 문장을 새 동작에 맞게 고칩니다. run이 시작한 release를 고정하는 정책은 바꾸지 않습니다. sidebar와 창은 run이 아니라는 점을 명세에 적습니다.

### 요청 원문
- 요청: sidebar가 자기 코드의 release와 현재 설치본 `current`의 release가 다르면 "재시작 필요"를 보입니다. 다시 켜는 방법(prefix `B` 두 번 등)도 함께 보입니다. 같으면 아무것도 보이지 않습니다.
- 자동 재시작은 요청하지 않습니다. 화면 배치가 바뀌므로 다시 켜는 것은 사람이 합니다.
- release를 비교하는 원본은 설치본의 release 식별(VERSION·release 디렉터리) 하나를 씁니다. run마다 release를 고정하는 정책과 이 표시가 어떤 관계인지(sidebar는 run이 아님)는 담당 project가 정합니다.
- 형식·문구·version은 담당 project가 정합니다.

## Disposition
- 2026-11-12 Leader: 설계 선택(표시만, 같은 pane 자동 전환, 둘 다)이 요청한 project의 계약을 바꾸므로 결정 항목 D-20261112-01로 사용자에게 묻습니다. BOARD-027·TMUX-004가 Rust sidebar를 고치는 중이라 그 뒤에 시작합니다.
- 2026-11-12 Leader: 결정 D-20261112-01 decided C. 사용자 답변 원문: "C". 선택지 C는 "자동으로 전환하고, 전환할 수 없을 때(새 binary가 없거나 실행 실패)만 '재시작 필요'와 이유를 보입니다"입니다.
  - 요청서가 자동 재시작을 꺼린 이유(화면 배치 변경)는 같은 pane 안의 전환에는 해당하지 않습니다.
  - 근거는 사용자 지시 "판단의 주요관점은 ** Root cause & SSOT **"입니다. 원인(upgrade 뒤에도 옛 코드가 돎)을 없애는 쪽을 택했습니다. Contract를 이 결정대로 고쳤습니다.
  - BOARD-027·TMUX-004가 Rust sidebar와 창을 고치고 있습니다. 둘 중 먼저 끝나는 seat에서 시작하고, 시작 시점의 `origin/main`을 기준으로 합니다.
- 2026-11-12 Leader: open -> todo.
- 2026-11-12 Leader 검토(제출 827b1c30a4a6): 수정 요청 2건입니다.
  - (1) 실행 권한이 있고 `execv`도 성공하지만 바로 끝나는 binary로 바꾸면 pane이 끝납니다(Contract 2). 바꾸기 전에 새 binary를 한 번 실행해 확인합니다(`<binary> release`).
  - (2) thread가 도는 중에 `set_var`로 환경을 바꿉니다. 환경을 바꾸지 않고 envp를 만들어 `execve`로 넘깁니다.
  - 창 재시작 중의 전송 끊김과 전환 순간의 클릭 거절은 받아들입니다. merge 뒤 `test_tmux_control` 부하 timeout은 TEST-016 Contract 4로 넘깁니다.
- 2026-11-12 Leader: 제출 8c00220ea408e200a90fd2ec7f96649487604fc1를 인수합니다. 수정 2건 확인: 전환 전 probe(바로 끝남·다른 release·무응답·실행 불가는 알림과 옛 코드 유지), execve로 환경 불변. cargo 97, project-board 539, 네 번째 명령 재사용(입력 불변), distribution boundary 9 passed(Leader 재실행)
- 2026-11-12 Leader: in-progress -> done, Outcome fixed. 통합 83f3e55 (origin/main)

## Implementation
읽을 문서:
- [Board TUI 계획](../../project-board-tui-plan.md)(sidebar 실행, 5절 창 재사용).
- [설치 계약](../../project-team/install-contract.md)(release 디렉터리, `current`, 2.1절 Rust build).
- [동작 명세](../../project-team/spec.md)(run의 release 고정).
- [제품 지도](../../project-team/README.md)의 중복 예외.
- 코드: `tools/project-board/project_board/tmux_control.py`(`sidebar_binary`, `_reuse`), `tools/project-board/rust/src/`(`app.rs`, `window.rs`), `install/project_agent_install/`.
- 절차: [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. release 식별의 원본을 정하고, sidebar(Rust)와 창(Python)이 같은 방법으로 읽게 합니다. Rust와 Python이 같은 규칙을 가지면 중복 예외 표와 일치 test로 지킵니다.
2. sidebar: 주기 읽기 안에서 `current`가 가리키는 release를 확인하고, 다르면 새 binary로 같은 pane에서 바꿔 실행합니다. 실패하면 알림 줄에 "재시작 필요"를 보입니다.
3. 창: 재사용 전에 창의 release를 확인하고, 다르면 새로 시작합니다.
4. binary `--version`과 release 버전을 정리합니다.
5. 문서(Contract 6).
6. Test(관측 동작):
   - 격리 HOME과 두 release를 만들고, `current`를 바꾼 뒤 sidebar가 같은 pane에서 새 binary로 바뀌는지(pane id·크기 그대로, 새 binary의 release) 확인합니다.
   - 새 binary가 없거나 실행할 수 없을 때 알림이 나오는지 확인합니다.
   - release가 다른 창은 재사용하지 않는지 확인합니다.
   - 같은 release에서는 아무 일도 없는지 확인합니다.

위험 등급: 중간(실행 중인 sidebar의 교체, 설치기 안내).

## Verification
- README 검증 표에서 바꾼 경로의 행 명령을 모두 제출 commit에서 실행합니다.
  - `tools/project-board/rust/**`: `(cd tools/project-board/rust && cargo test --offline --locked)`, `python -m pytest -q tools/project-board/tests`, 네 번째 명령.
  - `tools/project-board/**`: `python -m pytest -q tools/project-board/tests`, `python -m pytest -q tools/agent-session/tests/test_api_boundary.py`.
  - `install/**`를 바꾸면 `python -m pytest -q -n 8 install/tests`도 실행합니다.
  - 문서: 고친 문서의 상대 link 검사, `python -m pytest -q tools/test_distribution_boundary.py`. `docs/project-team/spec.md`를 바꾸면 `python -m pytest -q tools/agent-session/tests/test_remote.py`도 실행합니다.
- 화면: 격리 server에서 전환 전과 후의 sidebar를 `tmux capture-pane -p -e`로 `/primehome/swain/tmp/board028/`에 저장하고 Result에 적습니다. 실패 알림 화면도 함께 저장합니다.

## Result
- 제출 commit: 827b1c30a4a6843f2421010eaa588a9a02569ad6
  (`cr/BOARD-028`, origin에 push함. 구현 commit `d9d40ddd7eb9ba476b300c4634ec865a1e6445a4` 위에 `origin/main`(`ee57615`)을 충돌 없이 merge함)

### 구현 요약
1. **release 식별의 원본**: release 디렉터리 이름 `<version>-<hash>` 하나입니다(설치 계약 2.2절 신설). 설치본의 release는 `current`가 가리키는 디렉터리 이름, process의 release는 자기 코드가 놓인 `<lib>/releases/<이름>/tools/project-board/`(그리고 `<lib>/current`가 symlink)입니다. 그 밖(개발 checkout)은 release가 없고 전환하지 않습니다. Rust는 `rust/src/release.rs`, Python은 `project_board/release.py`가 같은 규칙을 읽고 제품 지도 예외 표에 올렸으며 `test_rust_release.py`가 같은 배치 6가지로 비교합니다.
2. **sidebar 자동 전환**: 2초 파일 읽기 안에서 snapshot을 보낸 뒤 `current`를 읽습니다(path 읽기만, process 추가 없음, 첫 그림 지연 없음). 다르고 새 binary를 실행할 수 있으면 같은 process를 `execv`로 바꿉니다(pid·pane·크기·위치·환경·인자 그대로). 바꾸기 전 터미널 상태를 돌려놓고 SIGUSR1을 무시하며(handler는 `exec`를 지나지 못하고 기본 동작은 process 종료), click socket 파일은 `PROJECT_BOARD_SUCCESSOR=1`일 때만 새 process가 이어받습니다. `execv`를 쓴 이유: std의 `Command::exec`(`execvp`)는 실행 파일이 아닌 파일을 `/bin/sh`로 실행해 sidebar가 사라집니다.
3. **전환하지 못할 때**(binary 없음·실행 권한 없음·`exec` 실패·`current` 읽기 실패·`releases/` 밖): 옛 코드로 계속 그리고 맨 위에 `재시작 필요: <이유>. Board를 껐다 켜세요(prefix B 두 번).`를 보입니다. 등록 오류(옛 검사가 만든 `registry_invalid` 같은 것)와 함께 보이도록 `ui::layout`이 오류와 알림을 둘 다 그립니다. `current`가 다시 자기 release가 되면 사라집니다. release가 같으면 아무것도 보이지 않습니다.
4. **창(Python)**: 창을 시작한 release를 pane option `@project_board_window_release`에 적고(시작 script와 `respawn` 전 두 곳), 클릭하는 쪽(Python `_reuse`, Rust `window::tell`)은 자기 release와 다른 창(option이 없는 옛 창 포함)을 알리지 않고 같은 pane에서 다시 시작합니다. 전환한 sidebar가 여는 창·popup은 자기 binary와 같은 release의 `project-board`로 열립니다.
5. **`--version`**: `project-board-sidebar <release 이름>`(release 밖은 `(not in an installed release)`). crate의 `Cargo.toml`에서 `version`을 없애(`Cargo.lock`은 `0.0.0`) release와 다른 버전 값이 없습니다. 설치 계약 `check`·T36·T42 문구를 맞췄습니다.
6. **문서**: 설치 계약(1·2.2·7.1 4항·5.3·`check`·T36/T42), TUI 계획("Sidebar의 release" 절, 2절 읽기 주기, 5절 option 표와 client 순서), 제품 지도 예외 표, `docs/install.md`, 설치기 안내(`commands.py`의 `BOARD_NOTE`, upgrade·rollback). run이 시작한 release를 고정하는 정책은 바꾸지 않았고, sidebar와 창은 run이 아니라는 점을 설치 계약 2.2절 5항과 7.1절 4항에 적었습니다. `spec.md`는 바꾸지 않았습니다(release 고정 정책의 서술이 설치 계약 7.1절에 있어 그곳에 적음).

### 검증 (모두 위 제출 commit의 tree 기준. 아래 "근거 재사용"을 참조)
- `(cd tools/project-board/rust && cargo test --offline --locked)`: 94 passed (`release.rs` 단위 test 5건, `ui.rs` 알림 test 1건 포함).
- `python -m pytest -q -n 8 tools/project-board/tests`: merge 전 구현 commit에서 536 passed. merge 뒤 제출 commit에서 535 passed, 1 failed — `test_tmux_control.py::test_moving_or_resizing_the_board_window_never_changes_the_saved_sidebar_width[window]`가 `subprocess.TimeoutExpired`로 실패했습니다(host load average 120 이상). 그 test만 다시 실행해 2 passed입니다(부하로 인한 timeout. 내 변경과 무관한 경로라는 확인은 아니고, 재실행 통과로 판정함).
  - 새 test: `test_sidebar_release.py`(전환: pid·pane·크기·위치·접힘·ready·click socket·SIGUSR1 유지, 같은 release 무변화, release 밖 무변화, 전환 불가 5가지와 되돌림, 등록 오류와 알림 동시 표시, 주기 읽기의 tmux·crontab process 수 불변, 자기 release가 시작한 창은 알리고 다른 release 창은 다시 시작), `test_rust_release.py`, `test_rust_window_notify.py`(Python·Rust가 같은 결과인 "another release" 시나리오), `test_sidebar_binary.py`("other release" 창), `test_tmux_control.py`(Python `_reuse` 다른 release 창 재시작과 raw client의 규약).
- `python -m pytest -q tools/agent-session/tests/test_api_boundary.py`: 4 passed.
- 네 번째 명령(`integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py`): `integrations/tmux`가 전부 통과한 뒤 같은 명령이 시간 제한(host 부하)으로 끊겨, 남은 파일을 따로 실행해 85 passed(22분). merge 뒤 새로 들어온 `tools/test_real_crontab.py`·`tools/test_distribution_boundary.py`·api boundary는 18 passed.
- `python -m pytest -q -n 8 install/tests`: merge 전 구현 commit에서 318 passed, 2 skipped(1시간 49분. host 부하, T42는 진짜 cargo build 포함). merge 뒤 바꾼 conftest의 영향을 받는 `install/tests/test_install.py`·`test_rust_build.py`만 다시 실행해 115 passed, 1 skipped.
- 문서: 고친 문서 4개(`docs/install.md`, TUI 계획, 제품 지도, 설치 계약)의 상대 link·anchor 검사 이상 없음(script로 확인). `test_distribution_boundary.py` 통과(위 18건에 포함). `spec.md`를 바꾸지 않아 `test_remote.py`는 실행하지 않았습니다.
- **근거 재사용·재실행 판정**: merge(`origin/main`)는 agent-session(`git_ops.py`, `lifecycle.py`, `workspace.py`), test 공통 conftest(crontab 차단), 문서만 바꿨고 Board·설치기 코드는 바꾸지 않았습니다. 그래서 cargo test는 재사용했고(Rust 입력 불변), conftest가 바뀐 project-board test 전체와 install 중 내가 바꾼 두 파일, 새 `test_real_crontab.py`를 merge 뒤에 다시 실행했습니다. install 전체와 네 번째 명령 전체는 merge 뒤에 다시 실행하지 않았습니다(install의 나머지 파일과 `integrations/tmux`는 merge가 바꾼 conftest만 입력이 달라졌고, 내 변경과 겹치지 않습니다).

### 화면 증거 (`/primehome/swain/tmp/board028/`)
격리 tmux server에서 release 배치(`releases/0.11.0-aaaaaaaaaaaa`, `0.12.0-bbbbbbbbbbbb`, `current` 전환)의 binary로 캡처했습니다. 각 화면은 `.txt`(평문)와 `.ansi.txt`(`capture-pane -p -e`)입니다.
- `1-before-switch`, `2-after-switch`: 전환 전후. 화면 평문은 같고(`diff` 무차이), `facts.json`에서 pane `%0`, 크기 `25x30@0,0`, process 1642288, 접힘 `["Falcon2"]`, `@project_board_ready=1`이 그대로이며 `exe`만 `0.11.0-…`에서 `0.12.0-…`의 binary로 바뀝니다.
- `3-restart-needed-no-binary`: 새 release에 binary가 없을 때(`재시작 필요: 새 release 0.13.0-cccccccccccc에 project-board-sidebar가 없거나 실행할 수 없습니다. Board를 껐다 켜세요(prefix B 두 번).`), process·exe는 그대로이고 목록은 계속 그립니다.
- `4-restart-needed-exec-failed`: 실행할 수 없는 binary(`Exec format error`)일 때의 같은 알림.

### 알아둘 점
- 창을 다시 시작하면 그 창이 답변을 보내는 중이었던 경우 전송이 끊깁니다(답변은 먼저 접수되므로 잃지 않고, Leader 알림만 끊길 수 있음). 종류가 다른 창을 다시 시작하는 기존 동작과 같은 수준이며 `busy`를 별도로 보지 않았습니다.
- 전환하는 순간 click socket에 들어온 클릭은 새 process가 socket을 열 때까지 연결이 거절됩니다(한 번 더 누르면 됩니다).
- 이 workstation의 Board는 이번 변경이 `current`가 되기 전에는 옛 binary이므로, 이 변경을 처음 설치한 뒤 한 번은 사람이 Board를 껐다 켜야 합니다(옛 binary에는 전환 코드가 없음).

### 수정 제출 (2026-11-12, Leader 검토 2건)
- 제출 commit: 8c00220ea408e200a90fd2ec7f96649487604fc1
  (`cr/BOARD-028`, origin에 push함. `827b1c3` 위의 수정 commit 하나이고 `origin/main`에 새 commit이 없어 merge는 없습니다.)

1. **실행은 되지만 바로 끝나는 새 binary**: `release::probe`를 더했습니다. `current`가 바뀐 때(`snapshot_loop`의 비교 결과가 달라졌을 때) 한 번만, 새 binary를 `release` 인자로 실행해(10초 제한, 넘으면 kill) exit 0이고 `{"release": "<바꿀 이름>"}`을 내는지 봅니다. 통과할 때만 전환합니다. 실패하면 `재시작 필요: 새 release X의 sidebar가 시작하지 못합니다(<이유>)`를 보입니다. 이유는 종료 코드와 출력 일부(80자), 다른 release 이름, 출력 없음, 시간 초과, 실행 불가입니다. 2초 읽기가 같은 결과를 찾을 때는 돌지 않아 주기 읽기에 process가 늘지 않습니다.
2. **thread가 도는 중의 환경 변경**: `exec_into`가 `set_var`·`remove_var`를 부르지 않습니다. 현재 환경(`vars_os`)에서 `PROJECT_BOARD_SUCCESSOR`를 빼고 `PROJECT_BOARD_SUCCESSOR=1`을 더한 envp를 만들어 `execve`로 넘깁니다. 시작할 때의 `remove_var`는 thread를 띄우기 전이라 그대로입니다.

- test: Rust 단위 3건(probe 통과, 바로 끝남·다른 release 이름·출력 없음·실행 불가의 이유, 시간 제한). `test_sidebar_release.py`의 전환 불가 case에 "exits at once"(`exit 1` script), "another release name", "says nothing"을 더해, 각각 notice가 나오고 pid·pane·크기·접힘 등 `_facts`가 그대로이며 옛 binary로 계속 도는지 확인합니다. 기존 전환 test는 새 binary가 probe를 통과해야 하므로 probe의 통과 경로도 지킵니다.
- 문서: TUI 계획 "Sidebar의 release"와 설치 계약 7.1절 4항에 probe와 `execve`를 적었습니다.
- 검증(수정 commit): `cargo test --offline --locked` 97 passed. `python -m pytest -q -n 8 tools/project-board/tests` 539 passed(536 + 새 case 3). 네 번째 명령(`test_real_crontab.py` 포함) 156 passed — Rust binary를 바꾼 뒤 project-board test는 binary를 먼저 build한 뒤 다시 돌렸고(그 전 실행은 8 worker가 stale binary를 동시에 build하다 `test_rust_equivalence`에서 98 errors가 났으나 test 실패가 아닌 build 경쟁이었습니다), 네 번째 명령은 Rust·Python Board 코드를 입력으로 하지 않아 같은 실행을 씁니다. 설치기·Python 창·`install/**`는 이 수정에서 바뀌지 않아 이전 근거를 재사용했습니다(문서 두 곳은 link를 바꾸지 않음).
- 화면 증거 추가: `/primehome/swain/tmp/board028/5-restart-needed-exits-at-once.txt`(·`.ansi.txt`). 실행 권한이 있는 `exit 1` script일 때 pid 265736, pane `%0`, `25x30@0,0`, 접힘, `@project_board_ready`가 그대로이고 `재시작 필요: … 바로 끝납니다(종료 코드 1: GLIBC_2.99 not found)`가 보입니다. `facts.json`의 `restart_exits_at_once`에 같은 값이 있습니다.
