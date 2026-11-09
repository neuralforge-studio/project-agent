# RELEASE-003: 개인 설정이 없는 새 계정에서 release를 시범 설치하고 계약 밖 변경이 없음을 기록합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3
- Mode: read-only
- Base: e41a82631c6e0cb277989c3c668c6f56bbdb57fc 2026-11-09T19:45:16+09:00

## Symptom
새 계정에서 설치해 계약 밖 변경이 없는지 확인한 기록이 없습니다. 격리 HOME 인수 test(INSTALL-001)는 실제 계정의 shell·tmux·provider 환경을 모두 흉내 내지 못합니다.

## Evidence
- RELEASE-001 Contract 3항: 시범 설치는 INSTALL·TMUX 요청을 통합한 release로, 개인 설정이 없는 계정에서 합니다. 계정 준비는 사용자와 정합니다.
- agent DIST-001 Verification: 새 계정 시범 설치에서 계약 밖의 파일 변경이 없습니다.

## Contract
- 사용자 결정(agent D-20261109-08 C): 설치 중 다른 설정에 영향이 없어야 합니다.
- 계정 준비 방법은 사용자 결정 항목으로 정합니다.

## Disposition
- 2026-11-09 Leader: 판정 보류(open 유지). 계정 준비 방법을 사용자 결정 D-20261109-02로 묻습니다. 선행 INSTALL-001·002·004·005, RELEASE-001·002가 통합된 뒤 결정에 맞춰 Implementation·Verification을 쓰고 판정합니다. 사용자 지시(2026-11-09 "남은 CR은 전부 등록해서 얼마나 남았는지 알 수 있게 해줘")에 따라 RELEASE-001에서 떼어 냈습니다.
- 2026-11-09 Leader: 조사한다(read-only, 사용자 결정 D-20261109-02 C). 사용자 답변 원문(Project Board): "C". 시범 설치는 이 계정에서 빈 디렉터리를 HOME으로 지정한 login shell로 합니다. 같은 uid라서 기본 tmux socket·provider 인증·`/tmp`가 실제 새 계정과 다르며, 이 한계는 Result에 적습니다. 선행 CR이 모두 통합된 뒤 시작합니다.
- 2026-11-09 Leader: 선행에 TMUX-002를 더합니다. 시범 환경(`env -i`의 시스템 PATH)은 `/usr/bin/tmux` 2.7을 만나므로, 최소 버전 판정과 안내가 들어간 뒤 시범 설치해야 실제 새 직원의 경험을 확인할 수 있습니다. 시범 설치에서 PATH 첫 tmux가 2.7인 경우와 사내 3.8을 앞에 둔 경우를 모두 기록하십시오.
- 2026-11-09 Leader: 선행이 모두 통합되었습니다(마지막 TMUX-002 5b73d6a). 원본은 지금 `origin/main`입니다. 시범은 안내문(`docs/install.md`)을 그대로 따르고, 시스템 PATH(첫 tmux가 `/usr/bin/tmux` 2.7)인 경우와 사내 tmux 3.8을 앞에 둔 경우를 모두 기록합니다. 사내 tmux는 `LD_LIBRARY_PATH`가 필요할 수 있습니다(TMUX-002 Result). 안내문이나 설치기의 문제를 찾으면 고치지 말고 Leader에게 보고합니다. 이 workstation의 실제 설치본(`~/.local/lib/project-agent`, agent DIST-005가 설치)은 건드리지 않습니다.
- 2026-11-09 Leader: in-progress -> open. 시범 설치 결과 검토: 계약 2·3·7절 밖의 변경 없음, 실제 HOME·기본 tmux server 불변(같은 uid 한계 기록됨). F1(LD_LIBRARY_PATH 없는 환경에서 사내 Python이 sys.prefix=/usr로 떠 textual이 안 보임)은 Leader가 재현해 결함으로 판정하고 INSTALL-006으로 열었습니다. F2(check·uninstall이 기본 tmux server에 읽기 질의)는 계약 7.2절대로의 읽기라 결함이 아닙니다. INSTALL-006 통합 뒤 변형 A의 F1 경로만 다시 확인하고 닫습니다.

## Implementation
- Mode는 read-only입니다. 제품 코드와 문서를 고치지 않고 commit·push하지 않습니다. 결과는 `## Result`에 씁니다. 안내문이나 설치기의 문제를 찾으면 고치지 않고 Leader에게 보고합니다(Leader가 CR을 엽니다).
- 읽을 문서: RELEASE-002의 직원용 안내문, [설치 계약](../../project-team/install-contract.md) 2·3·4·5·7절, RELEASE-001의 버전 규칙 문서.

> **경고:** 실제 HOME(`/primehome/swain`)의 설정을 바꾸지 않습니다. 기본 tmux server(`/tmp/tmux-<uid>/default`)에 binding·hook을 넣지 않습니다. 시범용 tmux는 반드시 별도 socket(`tmux -L <시범 이름>`)을 씁니다.

1. 기준: 선행 CR이 통합된 `origin/main`의 commit을 원본으로 하고 그 hash를 Result에 적습니다.
2. 시범 환경: 새 빈 디렉터리를 만들어 `HOME`으로 씁니다. `env -i`로 `HOME`, `USER`, `LOGNAME`, `SHELL`, `TERM`, 시스템 기본 `PATH`만 남긴 login shell(`bash -l`)을 엽니다. 개인 rc 파일과 `~/.local/bin`이 없는 상태여야 합니다.
3. 안내문 그대로 따라 합니다: 전제 확인, 한 줄 설치, `check`, PATH 안내, 시범 tmux server(`-L`)에서 설치된 `~/.tmux.conf` 읽기, Board 키와 결정 표시 한 줄, 시범 project(임시 git 저장소) 등록, `project-item new cr`·`ls`, Board 한 번 열기. provider 인증이 없으므로 실제 Claude·Codex 대화 시작은 하지 않고 한계로 적습니다.
4. `upgrade`(같은 원본의 다른 commit 또는 다시 만든 release)와 `rollback`, release 정리 명령, `uninstall`을 안내문대로 실행합니다.
5. 끝나면 시범 tmux server를 끄고 시범 HOME을 지웁니다.

의존: 선행 INSTALL-001·002·004·005, RELEASE-001·002. 후행: 첫 release tag(Leader).

위험 등급: 낮음. 시범 HOME과 별도 tmux socket에서만 실행합니다.

## Verification
1. 시범 HOME의 설치 전후 파일 목록(경로·종류·권한·내용 해시·link 대상) 차이가 계약 2·3절의 경로와 정확히 같습니다. `uninstall` 뒤에는 계약 7절이 남긴다고 한 것(등록 파일 등)만 남습니다.
2. 실제 HOME 불변: 실행 전후로 `~/.local/lib/project-agent`, `~/.local/bin`의 세 이름, `~/.claude/skills`·`~/.codex/skills`의 두 이름, `~/.config/project-agent`, `~/.tmux.conf`, `~/.claude.json`, `~/.codex/config.toml`의 상태(종류·link 대상·내용 해시·`mtime_ns`)가 같습니다. 기본 tmux server의 `list-keys`·`show-hooks -g`·`show-hooks -gw`가 같습니다.
3. 안내문의 단계마다 기대 결과와 실제 결과를 표로 적고, 다른 곳은 재현 명령과 함께 보고합니다.
4. 같은 uid라서 확인하지 못한 항목(provider 로그인, 다른 사용자의 기본 tmux socket·`/tmp` 권한)을 Result에 한계로 적습니다.

## Result

Read-only CR이므로 제출 commit은 없습니다. 제품 코드·문서를 고치지 않았고 commit·push하지 않았습니다. 시범 설치는 `origin/main`에서 받은 원본 그대로 했습니다.

- 원본: `origin/main` = `e41a82631c6e0cb277989c3c668c6f56bbdb57fc`(`VERSION` 0.1.0, release 이름 `0.1.0-e41a82631c6e`). `upgrade` 시험용으로 시범 checkout에만 로컬 commit 둘(`62fd884d96a5`, `0bbbef238ca4`, docs/install.md 한 줄 추가)을 만들었고 push하지 않았습니다. 시범 checkout은 지웠습니다.
- 결론: 설치 중 계약 밖의 변경은 찾지 못했습니다. 안내문·설치기의 계약 위반은 없습니다. 아래 "Leader에게 알릴 발견" 둘(F1·F2)은 계약 위반이 아니라 안내문의 사실 진술과 새 계정의 환경 사이의 차이입니다. 고치지 않았습니다.

### 시범 환경(재현 방법)

- 시범 HOME은 빈 새 디렉터리(scratchpad 아래 `trial/home`)입니다. 시범 checkout은 같은 `trial/work/`에 있고 HOME 밖입니다.
- 실행은 `env -i HOME=<시범 HOME> USER LOGNAME SHELL=/bin/bash TERM PATH=… /bin/bash -l -c '<명령>'` 한 줄입니다. `env -i`가 `TMUX`·`TMUX_TMPDIR`·`CLAUDE_CONFIG_DIR`·`CODEX_HOME`·`XDG_*`·`LD_LIBRARY_PATH`·`AGENT_SESSION_*`를 모두 지웁니다.
- 변형 A(시스템 PATH만): `/usr/local/bin:/usr/bin:/usr/local/sbin:/usr/sbin`. 첫 tmux는 `/usr/bin/tmux` 2.7입니다. `/etc/profile`이 `/usr/share/Modules/bin`을 PATH 앞에 붙였고 빈 `~/.cache`(0700)를 만들었습니다. 설치 전 snapshot(s0)은 이 login shell 뒤에 찍었으므로 `~/.cache`는 설치와 무관합니다.
- 변형 B(사내 tmux 3.8을 앞에 둠): PATH 앞에 `/primehome/tools/Inhouse/tmux/latest/bin`, 그리고 `LD_LIBRARY_PATH`(Python3/latest/lib, libs/libevent·sqlite·readline·ncurses의 lib). libevent 경로가 없으면 사내 tmux가 `libevent_core-2.1.so.7`을 못 찾아 실행되지 않습니다(TMUX-002 Result와 같음).
- 시범 tmux는 `tmux -L cr3b`(서버 `/tmp/tmux-1028/cr3b`)만 썼습니다. 변형 B의 설치기 명령에는 `AGENT_SESSION_SOCKET=/tmp/tmux-1028/cr3b`를 주었습니다. 설치기가 `@project_agent_board_skipped`·`@project_board_enabled`를 묻는 서버를 기본 서버가 아니라 시범 서버로 돌리기 위해서입니다. 새 계정에서는 그 계정의 기본 서버가 이 자리입니다.
- 두 번에 나눠 했습니다. 1차(변형 A): provider 홈(`~/.claude`, `~/.codex`) 없음. 2차(변형 B): 안내문 1절대로 provider 홈을 먼저 만든 뒤(빈 디렉터리 둘) 설치. 두 홈이 없는 경우와 있는 경우를 모두 봤습니다.
- 도구: snapshot·비교 script(`snap.py`, `expect.py`, `tshell.sh`, `ptyclient.py`)와 모든 단계의 출력은 scratchpad(`/primehome/swain/tmp/claude-1028/-primehome-swain-Utils-project-agent-project-agent-seat0/e7256ed4-621b-48eb-b119-5d41edd11b37/scratchpad`)의 `out/`에 있습니다. snapshot은 symlink를 따라가지 않고 경로·종류·권한·내용 sha256·link 글자·`mtime_ns`를 기록합니다.

### 단계별 기대와 실제(안내문 순서)

| 단계 | 기대(안내문·계약) | 실제 |
| --- | --- | --- |
| 1절 전제(A) | python3 ≥ 3.10, tmux, git, provider CLI | python3 3.12.13, `tmux -V` = 2.7(`/usr/bin/tmux`), git 2.43.7, `/usr/local/bin/claude`만 있음(codex 없음) |
| 1절 전제(B) | tmux ≥ 최소 버전, textual | tmux 3.8, `$PY`에서 textual 8.2.8. **A에서는 `$PY -c 'import textual'`이 ModuleNotFoundError**(F1) |
| 2절 `install --dry-run`(A, 홈 없음) | 아무것도 만들지 않고 목록 출력 | 전후 snapshot 차이 0건. 목록: `~/.local/**`, `current`, shim 셋, `~/.config/project-agent/project.json`(초안), `~/.tmux.conf`, `install.json`. provider 홈이 없다는 Note 둘, PATH Note, "첫 tmux가 2.7, 최소 3.8" Note |
| 2절 `install`(A, 홈 없음) | dry-run과 같은 목록, 종료 0 | 목록·Note가 dry-run과 같음, 종료 0. skill link 없음 |
| 2절 `check`(A) | tmux 2.7이면 실패(종료 1), 해소 방법 안내 | `FAIL: The tmux first in PATH is 2.7 (/usr/bin/tmux), older than the minimum 3.8 … Put /primehome/tools/Inhouse/tmux/latest/bin before it in PATH.` 종료 1. `Note:` textual 없음, PATH 없음 |
| 4절 PATH(A) | `~/.local/bin`을 앞에 두면 `agent-session --help` | 나옴. `project-item --help`도 나옴 |
| 4절 tmux 2.7 서버가 `~/.tmux.conf` 읽음(A) | 오류 한 줄, binding·hook·option 없음 | `new-session -d`(설정 자동 읽음) 뒤 `prefix B`·hook·`@project_agent_*` 없음, 기본 `MouseDown1Pane` 그대로. 안내문의 `tmux source-file ~/.local/lib/project-agent/tmux.conf`는 `invalid option: project-agent needs tmux 3.8 or newer: put /primehome/tools/Inhouse/tmux/latest/bin first in PATH`, 종료 1. 실제 client 화면에서 첫 오류 표시는 확인하지 못함(한계 5) |
| 7절 `uninstall`(A, 1차 마무리) | 설치기가 만든 것만 제거, tmux 설정은 설치 전과 byte 동일(설치 전 없었으므로 없어짐) | 제거 목록 13건, 종료 0. 설치 전과 차이는 `~/.config/project-agent/project.json`(초안, `{}`)과 그 부모 `.config`뿐. 7절이 남긴다고 한 것과 같음 |
| 2절 `install`(B, provider 홈 있음) | 계약 2·3절의 경로 전부 | 아래 검증 1의 목록과 정확히 같음. `~/.claude/skills`, `~/.codex/skills` 디렉터리와 skill link 넷이 더해짐. 등록 초안은 이미 있어(1차) 만들지 않음, 종료 0 |
| 2절 `check`(B) | 마지막 줄 `OK`, 종료 0 | `Note: ~/.local/bin is not in PATH.` 다음 `OK`, 종료 0. PATH를 넣으면 Note도 사라짐. textual Note 없음 |
| 4절 시범 서버 `-L`이 설치된 `~/.tmux.conf` 읽음(B) | binding·hook이 server에 들어감 | `prefix B`와 root `MouseDown1Pane`이 `tmux_project_board.sh`를 부름. `-g` hook 5개(`after-resize-pane`, `client-attached`, `client-detached`, `client-session-changed`, `session-window-changed`)와 `-gw` hook 3개(`pane-died`, `window-created`, `window-closed`)가 모두 `[project-agent]` 이름. 계약 5.3절과 같음. `@project_agent_board_skipped ''`. `check`(서버 실행 중) `OK` |
| 4절 이미 떠 있는 server에 `tmux source-file …`(B) | 같은 binding, 건너뜀 없음 | 종료 0, binding 그대로, skipped 빈 값 |
| 4절 Board 키 바꾸기(B) | `@project_agent_board_key X` 뒤 source-file이면 `prefix X` 추가, 이전 `B`는 남음 | `prefix X`와 `prefix B` 둘 다 있음. `unbind-key B`로 B만 지움. 안내문과 같음 |
| 4절 결정 표시 한 줄(B) | `status-right`에 `#{E:@project_agent_decide_status}` 추가 | `show-options status-right`에 붙음. client를 붙인 화면에서 `결정 1`이 보임(결정 항목 1개를 만든 뒤). 첫 시도에서는 `#()`가 첫 평가 전이라 3초 안에 안 보였고 재시도에서 보임. `tmux_decide_status.sh`를 직접 실행하면 `결정 1` |
| 5절 시범 project 등록(B) | 등록 후 `project-item ls`가 오류 없이 끝남, 디렉터리 없으면 `no directory yet` | 임시 git 저장소(`trial/work/proj/trialproj.base`)를 `~/.config/project-agent/project.json`에 안내문 형식으로 등록. `project-item ls`가 `(no directory yet)` 둘을 내고 종료 0 |
| 5절 `project-item new cr`·`new decide`·`ls`(B) | 항목 생성, 목록 | `TRIAL-001`(`agent/cr/open/`), `D-20261109-01`(`agent/decide/open/`), `decide.html`. `ls`가 두 항목을 표시. 결정 본문을 `## Question`만 써서 `format: section '## Background' missing` 등 경고 4줄이 나왔습니다(내 입력의 문제, 제품 문제 아님). `git status`에 `?? agent/`(안내문 5절이 예고한 untracked) |
| 4절 Board 한 번 열기(B) | prefix `B`가 사이드바를 열고 닫음 | client를 붙인 pty에서 `Ctrl-b B` → 25칸 pane(`python3`, `@project_board_managed=1`)에 `trialproj / D:1 / O:1 T:0 I:0`이 그려짐. 다시 `Ctrl-b B` → pane이 닫힘. `project-board sidebar`를 별도 window에서 실행해도 같은 화면 |
| 6절 `upgrade --dry-run`·`upgrade`(B) | 새 release, `current`·`install.json`만 바뀜 | 목록 3건(새 release `0.1.0-62fd884d96a5`, `current` 교체, `install.json` 교체), dry-run은 차이 0. 실행 뒤 같은 3건만 차이. 이전 release는 byte 동일. `check` OK |
| 6절 `rollback --dry-run`·`rollback`(B) | `current`를 이전 release로 | `current` → `0.1.0-e41a82631c6e`, `install.json`만 바뀜. `check` OK |
| 6절 `prune`(B) 지울 것 없음 | `No release to remove` | `No change.` + 남긴 release 둘의 이유(current·previous), 변경 0건 |
| 6절 세 번째 `upgrade` 뒤 `prune --dry-run`·`prune`(B) | current·previous가 아닌 release만 삭제 | `0.1.0-62fd884d96a5`만 삭제(198개 항목), `0.1.0-0bbbef238ca4`(current)·`0.1.0-e41a82631c6e`(previous) 유지. dry-run과 실제 목록 같음. `check` OK |
| 7절 `uninstall --dry-run`·`uninstall`(B) | 설치기가 만든 것만 제거 | 목록 20건(release 둘, `current`, `tmux.conf`, shim 셋, skill link 넷, `tmux` 블록 파일, 빈 디렉터리 `~/.claude/skills`·`~/.codex/skills`·`~/.local/**`), dry-run은 차이 0. 설치기가 server에 넣은 binding·hook을 되돌리는 명령 10줄을 출력. 그 10줄을 시범 서버(`-L cr3b`)에 그대로 실행하자 `list-keys`·`show-hooks -g`·`show-hooks -gw`가 설정을 읽지 않은 서버(`-f /dev/null`)와 같아짐 |
| 5단계 정리 | 시범 서버를 끄고 시범 HOME 삭제 | `kill-server`, 시범 HOME·checkout 삭제, 아래 `/tmp` 잔여물 삭제 |

### 검증 1: 시범 HOME의 전후 차이

경로 집합이 기대(계약 2·3절)와 정확히 같은지 `expect.py`로 판정했습니다(기대 밖 0건, 빠진 것 0건).

- 2차 `install`: `~/.local`, `~/.local/lib`, `~/.local/lib/project-agent`, `…/releases`, `…/releases/0.1.0-e41a82631c6e`(197개 항목), `…/current`, `…/tmux.conf`, `…/install.json`, `~/.local/bin`, shim 셋, `~/.claude/skills`와 link 둘, `~/.codex/skills`와 link 둘, `~/.tmux.conf`. 그리고 디렉터리 mtime만 바뀐 `.`, `.claude`, `.codex`. `~/.tmux.conf`는 줄바꿈 하나와 3절 블록 세 줄뿐입니다(설치 전에 없었음, `cat -A`로 확인). `backup/`은 만들어지지 않았습니다(고친 기존 파일 없음).
- release: 모든 파일 0444, 디렉터리 0555, 쓰기 가능한 항목 0건. `test`·`docs/cr`는 없음, `__pycache__` 7개 디렉터리·`.pyc` 64개는 미리 compile한 것입니다(계약 2절). `tools/python.env`는 `PROJECT_AGENT_PYTHON=/primehome/tools/Inhouse/Python3/latest/bin/python3`, `PROJECT_AGENT_PYTHONPATH=`(빈 값)입니다.
- `upgrade`: 새 release 디렉터리, `current`, `install.json`(+`releases/`·`project-agent/` 디렉터리 mtime)만. shim·skill link·`tmux.conf`·`~/.tmux.conf`·등록 파일은 같음.
- `rollback`: `current`, `install.json`만. `prune`: 지운 release 하나만.
- `uninstall`(1차, 2차 모두): 제거 뒤 설치 전(provider 홈 있음, s3)과 차이는 디렉터리 mtime(`.`, `.claude`, `.codex`)과 아래뿐입니다. 모두 7절이 남긴다고 한 것 또는 5.1절의 실행 중 쓰기입니다.
    - `~/.config/project-agent/project.json`(초안, 안내문 5절에 따라 내가 project를 더한 내용으로 바뀜. 7절: 등록 파일은 지우지 않음)
    - `~/.cache/project-item/locks/<hash>.lock` 둘(`path_cr`·`path_decide` 루트, 5.1절), `~/.cache/tmux-decide-status.json`과 `.lock`(5.1절)
- `~/.tmux.conf`: 설치 전에 없었고 제거 뒤에도 없습니다(3절 보장).
- 이 시범은 `agent-session start`를 하지 않았으므로 5.1절의 `~/.claude.json`·`~/.codex/config.toml` 쓰기 경로는 실행하지 않았습니다. 시범 HOME에 두 파일은 생기지 않았습니다.

### 검증 2: 실제 HOME 불변

실행 전후로 `~/.local/lib/project-agent`(전체 tree), `~/.local/bin`의 세 이름, `~/.claude/skills`·`~/.codex/skills`와 두 이름씩, `~/.config/project-agent`(없음), `~/.tmux.conf`·`~/.claude.json`·`~/.codex/config.toml`(종류·link 글자·link 대상 내용 해시·`mtime_ns`)을 비교했습니다(219개 항목). 기본 tmux server(`/tmp/tmux-1028/default`, 3.8)의 `list-keys`·`show-hooks -g`·`show-hooks -gw`(428줄)도 전후 diff가 없습니다.

차이는 2건이고 시범과 무관합니다.

- `~/.cache/tmux-decide-status.json`: 내용 sha256은 같고 `mtime_ns`만 바뀝니다. 이 workstation의 실제 tmux status가 약 30초마다 다시 쓰는 파일입니다(`stat`을 20초 간격으로 두 번 찍어 확인: 19:52:47 → 19:53:19, 시범 종료 뒤).
- `~/.claude.json`: 내용과 `mtime_ns`가 바뀌었습니다. 이 Claude Code 대화가 쓰는 파일입니다. 시범 시작 전 첫 `ls`에서도 mtime이 19:45(이미 변하는 중)였고, 시범은 `HOME`이 달라 이 파일에 접근하지 않았으며 `agent-session start`(이 파일을 쓰는 제품 경로, 계약 5.1절)를 실행하지 않았습니다. 이 파일은 "불변" 기준을 mtime까지 요구하면 실행 중인 Claude 세션에서는 만족할 수 없는 항목입니다. 시범이 쓴 증거는 없다는 판단은 이 사실에 근거한 추정입니다.

### Leader에게 알릴 발견(고치지 않음)

- **F1. 안내문 1절의 "사내 Python에는 [textual이] 있습니다"는 `LD_LIBRARY_PATH`가 사내 환경일 때만 사실입니다(확인된 사실).** `env -i`의 `/primehome/tools/Inhouse/Python3/latest/bin/python3`는 `sys.prefix=/usr`(시스템 libpython과 시스템 site-packages)로 뜨고 `import textual`이 실패합니다. `LD_LIBRARY_PATH=/primehome/tools/Inhouse/Python3/latest/lib`를 주면 `sys.prefix=/primehome/tools/Inhouse/Python3/latest`가 되어 textual 8.2.8이 보입니다. 재현: `env -i /primehome/tools/Inhouse/Python3/latest/bin/python3 -c 'import sys,textual; print(sys.prefix)'`(실패)와 `env -i LD_LIBRARY_PATH=/primehome/tools/Inhouse/Python3/latest/lib /primehome/tools/Inhouse/Python3/latest/bin/python3 -c 'import sys,textual; print(sys.prefix)'`(`/primehome/tools/Inhouse/Python3/latest`). 변형 A의 `check`가 `Note: Project Board needs textual==8.2.8 … (not installed). Board will not start until it is installed there.`를 낸 것이 이 때문입니다. 설치기는 계약대로 안내(Note)만 하고 실패하지 않았습니다. 그래서 `LD_LIBRARY_PATH`를 주는 사내 환경 설정(로그인 때 module 등)이 없는 새 계정이면 같은 증상일 수 있습니다. 새 계정의 기본 환경에 그 설정이 있는지는 같은 uid로는 확인하지 못했습니다(한계 1). 이 환경에서 Board가 실제로 시작하지 않는지는 실행하지 않았습니다(`check`의 안내만 근거). 사내 tmux가 같은 환경 변수(libevent)를 필요로 하는 것은 TMUX-002 Result에 이미 있습니다.
- **F2. 설치기의 `check`·`uninstall`은 `AGENT_SESSION_SOCKET`이 없으면 사용자의 기본 tmux server에 읽기 명령(`show-options -gqv`)을 보냅니다(확인된 사실).** 계약 7.2절이 이미 이렇게 정합니다. 변형 A의 `uninstall`이 `The tmux server could not be asked which keys were skipped`를 낸 것은 tmux 2.7 client가 이 workstation의 기본 server(3.8)에 version 불일치로 접속하지 못했기 때문입니다(추정: 출력 문구와 두 버전만 근거). 기본 server의 `list-keys`·`show-hooks`는 변하지 않았으므로 쓰기는 없었습니다. 안내문·계약과 어긋난 점은 아니고, 이 시범이 변형 B에서 `AGENT_SESSION_SOCKET`을 시범 서버로 돌린 이유입니다.
- 관찰(원인 미확인, 결함 판정 아님): 시범 server를 `kill-server`한 뒤 `/tmp/project-board-1028-<시범 server pid>/`에 `control.lock`과 `<16자>.sock`이 남았습니다. 계약 5.4절은 "kill-server·crash로 끝난 server의 디렉터리는 다음 Board 명령이 지운다"고 하므로 계약과 어긋나지는 않습니다. 시범 중 `project-board sidebar`를 별도 window에서 실행해 `kill-window`로 끝낸 적이 있어 그 소켓일 수 있습니다. 시범 산출물이라 직접 지웠습니다. 같은 이유로 `/tmp/tmux-1028/`에 남은 시범 소켓 둘(`cr3b`, `cr3c`)도 지웠습니다(tmux가 `kill-server` 뒤에도 파일을 남김).

### 한계(같은 uid, 같은 workstation)

1. provider 로그인은 확인하지 못했습니다. `claude`·`codex`를 실행하지 않았고 실제 Claude·Codex 대화 시작(`agent-session start`)도 하지 않았습니다. 따라서 5.1절의 신뢰 기록 쓰기, `~/.claude`·`~/.codex` 홈이 provider CLI의 첫 실행으로 만들어지는 과정, Codex daemon은 시범 밖입니다. provider 홈은 빈 디렉터리로 대신 만들었습니다.
2. 기본 tmux socket·`/tmp`는 이 계정의 실제 것과 공유합니다. 다른 사용자의 `/tmp/tmux-<uid>/` 권한, 새 계정의 기본 socket이 없는 상태, `/tmp` 권한과 정리 정책은 확인하지 못했습니다. 시범은 별도 socket(`-L cr3b`, `-L cr3c`)과 `/tmp/project-board-1028-<시범 pid>/`만 썼고 끝나면 지웠습니다.
3. login shell은 `bash -l`만 확인했습니다. 이 계정의 login shell은 csh이고 새 계정의 로그인 환경(csh의 `.cshrc`·module·`LD_LIBRARY_PATH` 설정)은 재현하지 못했습니다. F1이 이 때문에 확정되지 않습니다.
4. `git clone`은 시범 login shell이 아니라 바깥 shell에서 ssh URL(`ssh://git@git.primemas.com:222/swain/project-agent.git`)로 했습니다. ssh 키·known_hosts는 시범 HOME이 아니라 이 계정의 것이기 때문입니다. 따라서 새 계정의 ssh 키 준비는 확인하지 못했습니다. 이 clone의 위치는 시범 HOME 밖입니다.
5. tmux 2.7의 설정 오류는 `source-file` 명령의 오류 문구로만 확인했습니다. 2.7이 첫 client에 이 오류를 어떻게 보여 주는지는 실제 client로 확인하지 못했습니다(2.7의 `show-messages`는 client가 없으면 쓸 수 없고, pty client 시도는 출력을 얻지 못했습니다).
6. 실행하지 않은 것(CR 범위 밖): 충돌 거절(T11), `--adopt-dev-links`, 떠 있는 run이 있을 때의 `upgrade`·`rollback`(`formats_differ`)·`uninstall` 거절, 원격 seat. 이 계정의 실제 설치본 `~/.local/lib/project-agent`(DIST-005)는 읽기만 했습니다(검증 2).
7. 시범은 한 번의 순차 실행입니다(1차 A → 2차 B). 같은 구성의 반복 실행이나 중단(SIGKILL) 복구는 하지 않았습니다.

- 정리(Worker 종료 준비): 위 "도구" 항의 scratchpad `out/`와 script는 시범 산출물이라 지웠습니다. 시범 HOME·checkout·tmux server·시범 소켓·`/tmp` 잔여물도 없습니다(확인함). 이 Result의 수치는 그 시점의 출력이 근거이며 파일로는 남지 않았습니다.
