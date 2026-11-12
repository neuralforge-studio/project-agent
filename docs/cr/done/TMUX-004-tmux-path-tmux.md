# TMUX-004: 쓸 tmux를 정하는 원본이 없어 구성 요소마다 자기 PATH에서 tmux를 찾습니다

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S2
- Base: 6b7b41bad5e0cd15ae157ab3e71f4f2fcb11dee7 2026-11-12T11:40:17+09:00
- Outcome: fixed

## Symptom
project-agent 구성 요소는 쓸 tmux를 각자 정합니다. 호출한 process의 PATH에서 처음 찾은 `tmux`를 씁니다. 이 host에는 서로 통신하지 못하는 tmux 두 개가 있습니다. 시스템 tmux는 `/usr/bin/tmux` 2.7이고, 사내 tmux는 `/primehome/tools/Inhouse/tmux/latest/bin/tmux` 3.8입니다. 그래서 PATH가 다른 환경에서 부르면 같은 명령이 실패합니다.
- 2026-11-12 crontab `check` 작업은 cron의 PATH(`/usr/bin:/bin`)에서 2.7을 써서 server에 닿지 못했습니다(`lost server`). SESSION-015로 생긴 뒤 한 번도 점검하지 못했고, 그동안 BOARD-018 Worker가 6시간 멈춘 것을 아무도 알리지 않았습니다.
- SESSION-016은 이 증상만 고쳤습니다. Leader를 시작한 환경 PATH의 tmux 디렉터리를 crontab 줄에 `env PATH=...`로 복사했습니다. 그 결과 설치기가 crontab 줄을 해석하는 규칙도 바꿔야 했습니다(앞의 `env`·`NAME=값` 건너뛰기).
- 사용자 지시(2026-11-12): "판단의 주요관점은 ** Root cause & SSOT ** 변경이 적은쪽? 절대 아니야. … 하나하나 예전에 설계한게 잘못되었으면 근간부터 바꾸는게 맞아."

## Evidence
- **tmux를 PATH에서 찾는 곳**(구성 요소마다 따로):
  - `tools/agent-session/agent_session/tmux.py` `_argv`의 `["tmux"]`. `remote_lifecycle.py`도 같습니다.
  - `tools/project-board/project_board/tmux_control.py`.
  - BOARD-018의 Rust sidebar: `rust/src/tmuxio.rs`, `rust/src/data/tmux.rs`의 `Command::new("tmux")`.
  - `integrations/tmux/tmux_decide_status.py`.
  - 설치기 `install/project_agent_install/tmuxconf.py`의 `shutil.which("tmux")`(최소 버전 검사, "The tmux first in PATH is …").
  - SESSION-016의 `cron.check_command` `tmux_directory()`(Leader 시작 환경의 PATH).
- **기존 설계의 결정**: [설치 안내](../../install.md) "설치기는 tmux의 경로를 기록하지 않습니다". [설치 계약](../../project-team/install-contract.md) 3.2절은 사용자에게 사내 tmux 경로를 PATH 앞에 두라고 안내합니다. 즉 올바른 tmux를 고르는 책임이 모든 호출 환경의 PATH에 흩어져 있습니다. 대화형 shell에서는 맞지만, cron처럼 사용자 설정을 읽지 않는 환경에서는 맞지 않습니다.
- **같은 사실이 여러 곳에 있습니다**:
  - 사내 tmux 경로 상수가 두 곳에 있습니다: `agent_session/tmux.py`의 `COMPANY_TMUX`, `install/project_agent_install/tmuxconf.py`의 `COMPANY_TMUX`.
  - SESSION-016 뒤로는 tmux 디렉터리가 crontab 줄에도 복사됩니다(Leader 시작 때의 값).
  - 설치 안내는 사내 tmux가 library 경로(`LD_LIBRARY_PATH`)도 필요할 수 있다고 적습니다. 이 runtime 환경 역시 호출 환경에 맡겨져 있습니다.
- **crontab 줄 형식을 해석하는 곳이 둘입니다**: 줄을 쓰는 쪽은 `agent_session/cron.py`이고, 설치기 `install/project_agent_install/crontab.py` `_command_path`가 같은 줄을 자기 규칙으로 다시 해석합니다(INSTALL-008, SESSION-016에서 고침). 형식이 바뀔 때마다 두 곳을 함께 고쳐야 하고, 실제로 SESSION-016 첫 제출이 이 회귀를 냈습니다.

## Contract
1. project-agent가 쓰는 tmux(실행 파일과, 필요하면 실행에 필요한 환경)는 원본 하나가 정합니다. 모든 구성 요소가 그 원본을 따르고, 호출한 process의 PATH나 사용자 login 설정에 기대지 않습니다. 대상은 agent-session(Python, 원격 포함), project-board(Python), Rust sidebar, tmux 통합 script, 설치기, cron 작업입니다.
2. 원본의 위치와 정하는 시점(설치 때 최소 버전을 만족하는 tmux를 기록할지, 실행 중인 server에서 얻을지 등)은 근거를 들어 Worker가 정하고 명세와 설치 계약에 적습니다. 사용자가 tmux를 바꾸는 방법(재설치, 기록 갱신 등)도 함께 적습니다. 선택에 사용자 결정이 필요한 trade-off가 있으면 Leader에게 보고합니다.
3. crontab의 `check` 줄에는 환경의 사본(`env PATH=...`)이 없습니다. cron에서도 1항의 원본을 따릅니다. SESSION-016이 더한 복사와 그 때문에 생긴 규칙은 필요 없으면 지웁니다.
4. crontab 줄 형식을 해석하는 곳은 그 형식을 쓰는 `agent_session/cron.py` 하나입니다. 설치기가 작업의 프로그램이 필요하면 `agent_session.api`의 결과로 받고, 명령 문자열을 다시 해석하지 않습니다.
5. 사내 tmux 경로 같은 상수는 한 곳에만 둡니다.
6. 이미 설치된 환경은 upgrade와 다음 Leader 시작으로 새 방식으로 옮겨갑니다(옛 crontab 줄 포함). 이전 과정은 명세에 적습니다.

## Disposition
- 2026-11-12 Leader 판정: 구현한다. 근거는 사용자 지시입니다: "판단의 주요관점은 ** Root cause & SSOT ** 변경이 적은쪽? 절대 아니야. 확실히 정확하게 해결해 나가려고 해도 버그가 생기는데, 하나하나 예전에 설계한게 잘못되었으면 근간부터 바꾸는게 맞아. 앞으로는 그렇게 작업해줘."
  - SESSION-016의 cron 실패와 그 수정이 낳은 설치기 회귀는 같은 설계에서 나왔습니다. 쓸 tmux를 호출 환경의 PATH에 맡기는 설계와, crontab 줄을 두 곳에서 해석하는 설계입니다.
  - 원본의 위치는 Worker가 근거와 함께 정합니다. 사용자 결정이 필요한 trade-off가 나오면 결정 항목으로 올립니다.
  - Rust sidebar도 바뀌므로 BOARD-018(Rust sidebar)을 통합한 뒤 todo로 옮겨 시작합니다.
- 2026-11-12 Leader: BOARD-018을 통합했습니다(2bcd290). 시작합니다. BOARD-027(Board `C:n`·cron 창)이 같은 때 Rust sidebar(`window.rs` 등)를 고치므로, 먼저 통합된 쪽을 `origin/main`에서 merge해 맞춥니다.
- 2026-11-12 Leader: open -> todo.
- 2026-11-12 Leader 검토(제출 2b858a0b3c4c918e674dfabd6c90c204f5dbf19d): 수정 요청(merge만).
  - 설계와 구현은 그대로 둡니다. 원본은 release의 `tools/tmux.env` 하나이고(실행 파일과 library 경로, `python.env` 선례), Python `tmux_program.py`·shell `tmux-launcher.sh`·Rust `tmuxprog.rs`는 같은 13사례로 비교하는 일치 test가 지킵니다. crontab 줄 해석은 `cron.command_program` 한 곳이고, 설치기는 `api.crontab_sections`의 `program`을 씁니다. check 줄에는 환경 사본이 없습니다. 사내 tmux 상수는 `agent_session.api.COMPANY_TMUX` 한 곳입니다. 후보 비교(server에서 얻기는 순환, 상수는 macOS에서 틀림, Leader 시작 때 기록은 소유자가 둘)도 맞습니다.
  - 요청: BOARD-027이 통합되어(bc2605c) `origin/main`과 `docs/project-team/README.md`, `docs/project-team/spec.md`, `tools/agent-session/agent_session/api.py`가 충돌합니다. merge해서 두 변경을 모두 살리십시오. BOARD-027의 Rust 창 알림(`window.rs`)과 cron 읽기가 새 tmux 원본을 따르는지(`Tmux::from_env` 경로), 중복 예외 표에 두 CR의 행이 모두 있는지 확인하십시오. merge가 바꾼 입력의 행을 다시 실행하고 제출하십시오.
  - trade-off(기록이 release에 묶여 tmux만 바꾸려면 새 commit이 필요)는 받아들입니다. 같은 경로의 `latest` 갱신은 기록을 바꿀 필요가 없기 때문입니다.
- 2026-11-12 Leader 검토(수정 제출 deeea3638cad714134490d3335a3a843f8faeaf8): 인수. 앞 검토(2b858a0)의 근거는 재사용합니다. 바뀐 것은 BOARD-027 merge입니다. 충돌 셋(`api.py`의 `__all__`, 명세 api 표, 제품 지도 검증 문구)을 두 변경 모두 살려 풀었습니다. BOARD-027의 Rust 창 알림은 `tmuxio::Tmux::from_env`→`tmuxprog`을 따르고, Python cron 창은 `control.program()`을 씁니다. tmux를 글자 그대로 부르는 새 호출은 없습니다. 중복 예외 표에 두 CR의 행이 모두 있습니다. merge 상태에서 다시 실행한 결과: agent-session 956, project-board 512, 네 번째 명령 151, `install/tests` 318 passed·2 skipped, `cargo test` 88 passed. TEAM-003 통합(9ad637a) 뒤의 `origin/main`과는 충돌이 없습니다.
- 2026-11-12 Leader: 제출 deeea3638cad714134490d3335a3a843f8faeaf8를 인수합니다.
- 2026-11-12 Leader: in-progress -> done, Outcome fixed. 통합 f4605ad (origin/main)

## Implementation
읽을 문서:
- [설치 계약](../../project-team/install-contract.md) 3.2절(tmux 최소 버전), 7절 `check`, 7.3절.
- [설치 안내](../../install.md)의 tmux 항목.
- [동작 명세](../../project-team/spec.md)의 tmux 사용, check·cron 절, 원격 seat 절.
- [제품 지도](../../project-team/README.md)의 의존 관계와 중복 예외.
- 코드: `agent_session/tmux.py`, `agent_session/cron.py`, `agent_session/remote_lifecycle.py`, `project_board/tmux_control.py`, `tools/project-board/rust/src/`(BOARD-018 통합본), `integrations/tmux/`, `install/project_agent_install/tmuxconf.py`·`crontab.py`.
- CR: [SESSION-016](../done/SESSION-016-crontab-check-cron-tmux-server.md), [TMUX-002](../done/TMUX-002-tmux-tmux-2-7-check.md).
- 절차: [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. tmux를 고르는 모든 호출 지점을 목록으로 만들어 Result에 적습니다(위 Evidence 외에 빠진 곳 포함).
2. 원본의 위치와 시점을 정합니다. 후보의 장단점(설치 때 기록, server에서 얻기 등)과 고른 이유를 Result에 적고, 명세·설치 계약·설치 안내를 고칩니다.
3. 모든 호출 지점이 그 원본을 따르게 합니다. Rust와 Python이 같은 규칙을 갖는다면 제품 지도의 중복 예외와 일치 test로 지킵니다.
4. crontab 줄 해석을 `agent_session/cron.py` 한 곳으로 모읍니다. `agent_session.api`로 설치기에 작업의 프로그램을 주고, 설치기의 자체 해석을 지웁니다.
5. `check` 줄에서 환경 사본을 없애고, 옛 줄(손으로 붙인 `PATH=` 접두 포함)이 upgrade와 Leader 시작으로 새 줄이 되게 합니다.
6. Test(관측 동작):
   - cron과 같은 최소 환경(PATH `/usr/bin:/bin`, 앞에 틀린 tmux를 둔 경우 포함)에서도 각 구성 요소가 원본의 tmux로 격리 server에 닿습니다.
   - 원본이 없거나 최소 버전보다 낮을 때 오류가 정해진 code로 납니다.
   - 설치기 `check`가 지운 release를 가리키는 check 줄을 계속 알립니다.

위험 등급: 높음(여러 도구와 설치기, 사용자 crontab의 이전).

## Verification
- README 검증 표에서 바꾼 경로의 행 명령을 모두 제출 commit에서 실행합니다. 이 CR은 `tools/agent-session/**`(tmux option·api 변경 포함), `tools/project-board/**`(Rust 포함), `integrations/tmux/**`, `install/**`, 문서를 바꿀 것이므로 다섯 명령 모두와 `(cd tools/project-board/rust && cargo test --offline --locked)`입니다.
- 실제 재현: cron과 같은 환경(`env -i HOME=$HOME PATH=/usr/bin:/bin /bin/sh -c '<check 줄>'`)에서 격리 server를 대상으로 `check`가 성공하고 run 기록이 `ok`인지 확인해 Result에 적습니다.
- 문서: 고친 문서의 상대 link 검사, `python -m pytest -q tools/test_distribution_boundary.py`, `python -m pytest -q tools/agent-session/tests/test_remote.py`.

## Result
- 제출 commit: 2b858a0b3c4c918e674dfabd6c90c204f5dbf19d

`cr/TMUX-004`(origin에 push). 코드·검증 commit은 90edf23과 01b123a이고 2b858a0은 `origin/main`(CR 문서 3개만 진행)의 merge입니다.

### 1. tmux를 고르던 호출 지점 전수
Evidence의 곳에 더해 아래가 빠져 있었습니다.
- `agent_session/tmux.py`: `_argv`, `_run`, `source-file -`의 subprocess(`_run_script`), `require_version`의 `tmux -V`, `quiet_shell`이 만드는 `run-shell` 문장(두 `tmux -S`, hook 안), `install_exit_hook`. (`quiet_shell`은 Evidence에 없었음)
- `tools/project-board/project_board/tmux_control.py`: `_window_command`의 shell 문장과 `_popup`의 `new-pane` 명령(`tmux`를 글자 그대로 씀). Board의 나머지 호출은 `agent_session.api.Tmux`를 거침.
- `tools/project-board/rust/src/tmuxio.rs`, `data/tmux.rs`.
- `integrations/tmux`: `project_agent_run.sh`, `project_agent_bind.sh`, `project_board_visibility.sh`(모두 `tm() { tmux -S …}`), `tmux_decide_status.py`. (script 셋은 Evidence에 없었음)
- 설치기: `tmuxconf.too_old`, `runs.server_option`(`check`·`uninstall`·`prune`이 사용자 server를 읽을 때 PATH의 tmux). (`server_option`은 Evidence에 없었음)
- `cron.check_command`/`tmux_directory`, `remote_lifecycle.attach`의 원격 `tmux attach-session`(원격 host 쪽 실행).
- 사내 tmux 경로 상수: `agent_session/tmux.py`, `tmuxconf.py` 두 곳 + `project-agent.conf`의 오류 문구 + test 여러 곳.

### 2. 원본의 위치와 시점
**고른 것**: 설치기가 `install`·`upgrade`에서 한 번 골라 release의 `tools/tmux.env`에 적습니다(`python.env`와 같은 자리·형식·읽는 방식). 이름 둘: `PROJECT_AGENT_TMUX`(실행 파일 절대 경로), `PROJECT_AGENT_TMUX_LD_LIBRARY_PATH`. 환경 변수는 이름마다 값이 있으면 파일보다 이깁니다. 파일이 없는 tree(개발 checkout, 원격 runtime)는 PATH의 `tmux`. 파일은 있고 program이 비었으면 `tmux_unavailable`. 후보 순서: `PROJECT_AGENT_TMUX`(쓸 수 없으면 `tmux_environment`으로 설치 거절) → PATH의 첫 `tmux` → 사내 tmux. 후보를 빈 환경(`/usr/bin:/bin`)에서 `-V`로 시험하고, 뜨지 않으면 `ldd`가 푼 시스템 밖 library 디렉터리를 `LD_LIBRARY_PATH`로 주어 다시 시험합니다. 계약은 설치 계약 6.2절(새), 3.2절 4항·7절 `check`·T43~T45, 명세 check·api 표, 설치 안내, 제품 지도에 적었습니다.

**근거**: 사내 tmux는 `LD_LIBRARY_PATH` 없이는 `libevent`을 못 찾아 뜨지 않습니다(`env -i PATH=/usr/bin:/bin …/tmux -V` 실패를 이 host에서 확인). 그래서 원본은 경로만이 아니라 library 환경도 담아야 하고, 이는 python.env 선례와 같습니다.

**후보 비교**:
- 실행 중인 server에서 얻기: cron의 `check`는 server에 닿으려면 먼저 tmux가 필요해 순환입니다. 기각.
- 코드 상수(사내 경로): 사내 경로를 모르는 host(macOS)에서 틀리고 library 환경도 못 담습니다. 기각. 사내 경로는 후보로만 씁니다.
- Leader 시작 때 기록: 설치 없이 실행하는 환경과 cron이 의존하는 기록이 state에 생겨 소유자가 둘이 됩니다. 기각.
- PATH를 후보 2순위로 둔 이유: 사용자가 이미 server를 여는 tmux와 통신이 맞습니다.

**사용자가 tmux를 바꾸는 방법**: `PROJECT_AGENT_TMUX=<경로>`를 주고 새 release를 설치(`upgrade`). 같은 경로의 새 버전(`latest` link)은 기록을 바꿀 필요 없음. 기록한 tmux가 지워지거나 낮아지면 `check`가 실패로 알립니다.

**이전**: 기록이 없는 옛 release는 `check`가 안내만 하고 PATH를 씁니다. `upgrade`로 새 release를 만들면 기록이 생기고, 다음 Leader 시작(`ensure_check`)이 옛 `env PATH=`·손으로 붙인 `PATH=` 접두 줄을 새 줄로 바꿉니다(test로 확인).

### 3. 모든 호출 지점이 원본을 따름
- Python: `agent_session/tmux_program.py`(규칙의 원본). `Tmux._argv`·`_run`·`source-file -`·`require_version`·`quiet_shell`·`install_exit_hook`이 씀. Board는 `Tmux.program()`을 씀(`api` 경계 유지). 설치기 `server_option`은 `api.Tmux`로 읽음.
- shell: `tools/tmux-launcher.sh`(`project_agent_select_tmux`) — 네 script가 source. `tmux_decide_status.py`는 launcher가 export한 `PROJECT_AGENT_TMUX`를 읽음.
- Rust: `rust/src/tmuxprog.rs`. `tmux-program` 하위 명령이 선택을 JSON으로 보임.
- 중복 예외: 제품 지도의 Rust·Python 표에 행을 더했고 `tools/project-board/tests/test_tmux_record.py`가 같은 13사례를 Python·`sh`·`bash`·Rust binary에 주어 같은 답인지 비교합니다.
- 사내 tmux 상수는 `agent_session.api.COMPANY_TMUX` 한 곳(설치기와 test가 이를 읽음). `project-agent.conf`의 오류 문구는 tmux 설정 문법상 복사본이라 test가 상수와 같은지 검사합니다.
- 원격: 원격 host의 tmux는 로컬 설치가 정할 수 없어 PATH 규칙을 남기되, 원격 bootstrap과 SSH 표시 명령이 쓰던 두 PATH 정의를 `remote.REMOTE_PATH` 하나로 합쳤습니다(생성되는 문자열은 같음).

### 4. crontab 줄 해석
- `cron.command_program`이 명령 줄을 읽는 유일한 곳이고, `agent_session.api.crontab_sections`가 작업마다 `program`을 줍니다. 설치기 `crontab.py`의 `_command_path`·`ASSIGNMENT`·`shlex`를 지웠고 `missing_programs`는 `job["program"]`을 씁니다.

### 5. check 줄
- `cron.check_command`는 `<release>/bin/agent-session --config … check --project … >/dev/null 2>&1`뿐이고 `tmux_directory`·`CRON_PATH`·`env PATH=`가 없습니다.

### 6. 검증(제출 commit 기준)
README 표의 이 변경에 해당하는 여섯 명령 모두:
- `python -m pytest -q -n 8 tools/agent-session/tests`: 950 passed (90edf23)
- `python -m pytest -q tools/project-item/tests`: 141 passed (90edf23)
- `python -m pytest -q tools/project-board/tests`: 376 passed (90edf23. Rust binary test 포함)
- 네 번째 명령(`integrations/tmux` 등): 첫 실행(90edf23)에서 1 failed — `with_minimum`이 만든 복사본에 `tmux-launcher.sh`가 없어 bind가 실패한 test 결함이었습니다. test helper를 고친 뒤 01b123a 이후 트리(2b858a0)에서 **148 passed**.
- `python -m pytest -q -n 8 install/tests`: 317 passed, 2 skipped, 1 failed(90edf23) — 실패는 release 파일 목록 test가 새 `tools/tmux.env`를 모르던 것이었고 고친 뒤 그 test만 2b858a0에서 통과했습니다. 나머지 317은 90edf23의 결과를 재사용합니다(이후 변경은 test 두 개와 `origin/main`의 `docs/cr` 3개뿐이라 이 명령의 입력을 바꾸지 않음).
- `(cd tools/project-board/rust && cargo test --offline --locked)`: 77 passed (90edf23. 이후 Rust 변경 없음)
- 문서: 바꾼 md의 상대 link 검사 이상 없음. `tools/test_distribution_boundary.py`와 `tools/agent-session/tests/test_remote.py`: 2b858a0에서 70 passed(첫 실행에서 spec.md가 install-contract.md로 건 link가 원격 guidance 목록에 없어 실패했고 plain text로 고침).
- 실제 재현: (a) `install/tests/test_tmux_record.py::test_t45_…`가 격리 HOME에 진짜 `install`(기록은 이 host의 사내 tmux + library 경로)→ Leader 시작 → crontab의 check 줄(`env`·`PATH=` 없음)을 `env -i HOME=… PATH=<server에 닿지 못하는 가짜 tmux>:/usr/bin:/bin /bin/sh -c '<줄>'`로 실행: 종료 코드 0, `check.json`이 `ok: true`, `code` 없음(통과). (b) `tools/agent-session/tests/test_check.py`: 같은 조건에서 기록을 가진 복사본은 성공, 기록이 없는 checkout 줄은 `tmux_command_failed`(대조), 비어 있는 기록·없어진 tmux는 `tmux_unavailable`.
- 계약의 test: 기록 없음/있음/환경 우선/빈 program/없는 파일(`test_tmux_program.py`), 설치기 후보·library 탐지·`tmux_environment`·빈 기록·`check` 판정(`install/tests/test_tmux_record.py` T43·T44), script 네 개가 기록한 tmux를 씀(`integrations/tmux/test_tmux_record_scripts.py`), 옛 줄(`env PATH=`·`PATH=` 접두) 이전과 `command_program` 사례(`test_cron.py`).

### 7. Leader에게 알리는 trade-off
- 기록은 release에 속해 불변입니다. 같은 commit의 release에서 tmux만 바꾸려면 새 commit이 필요합니다(`upgrade`는 변경 없음 / 다른 release와 충돌 시 `release_conflict`). 기록을 가변 파일로 두면 설치기 journal에 가변 파일 갱신을 더해야 해 python.env 선례를 따랐습니다. 가변이 필요하면 별도 CR로 판단해 주십시오.
- 사용자가 자기 shell에서 여는 tmux server는 사용자의 PATH가 정합니다(설치본이 통제할 수 없음). 그 server가 기록한 tmux와 다른 버전이면 설치본이 닿지 못합니다. 안내는 설치 안내·계약 3.2절에 적었습니다.
- 개발 checkout(기록 없음)과 원격 host는 PATH의 tmux를 씁니다. 사용자 결정이 필요한 항목은 아니라고 판단했습니다.
- 이 workstation의 동결 사본(관리 run, `~/.local/bin`)은 이 저장소의 변경을 받지 않으므로(AGENTS.md) 이 변경은 설치기로 새로 설치해야 적용됩니다.

### 8. 수정 제출: BOARD-027 통합(bc2605c)과의 merge
- 제출 commit: deeea3638cad714134490d3335a3a843f8faeaf8

`origin/main`을 merge했습니다(deeea36). 충돌 셋을 두 변경 모두 살려 풀었습니다: `api.py`의 `__all__`(`COMPANY_TMUX`와 `cron_listing`), `spec.md`의 api 표(`crontab_sections`의 `program`과 `cron_listing` 행), 제품 지도 검증 문구(tmux 선택 일치 test와 BOARD-027의 창 알림 test 설명).
- BOARD-027의 Rust 창 알림(`window.rs`)은 `tmuxio::Tmux::from_env`를 거쳐 `tmuxprog`의 기록을 따릅니다. Python 쪽 cron 창(`_popup`)은 `control.program()`을 씁니다. cron 읽기(`rust/src/cron.rs`, `data/crontab.rs`)는 tmux를 부르지 않고 `crontab`만 실행하며 job 명령의 program을 해석하지 않습니다. tmux를 글자 그대로 부르는 새 호출 지점은 없습니다(`Command::new`·`"tmux"` 검색으로 확인).
- 제품 지도 중복 예외 표에 BOARD-027 행(cron 구역·다음 실행 규칙)과 tmux 선택 행이 모두 있습니다.
- merge가 바꾼 입력의 README 표 행을 deeea36에서 다시 실행: `tools/agent-session/tests` 956 passed, `tools/project-board/tests` 512 passed, 네 번째 명령 151 passed, `install/tests` 318 passed·2 skipped, `cargo test --offline --locked` 88 passed. `tools/project-item/**`은 두 변경 모두 건드리지 않아 다시 실행하지 않았습니다(141 passed 결과 재사용).
