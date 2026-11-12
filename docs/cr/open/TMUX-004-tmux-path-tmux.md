# TMUX-004: 쓸 tmux를 정하는 원본이 없어 구성 요소마다 자기 PATH에서 tmux를 찾습니다

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S2

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
