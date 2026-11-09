# TMUX-002: tmux 최소 버전이 정해지지 않아, 시스템 tmux 2.7에서 통합 파일이 오류로 읽히고 check도 알리지 않습니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Base: 742d60b97631c837788b218a138ed6b21b70b832 2026-11-09T19:09:15+09:00
- Outcome: fixed

## Symptom
통합 파일 `integrations/tmux/project-agent.conf`는 tmux 3.x 문법(`{ }` 명령 블록, 이름 붙은 hook index, `#{d:current_file}`, `run-shell -C` 등)을 씁니다. 이 workstation의 `/usr/bin/tmux`는 2.7이고, 사내 tmux 3.8(`/primehome/tools/Inhouse/tmux/latest/bin/tmux`)은 PATH에 사내 경로가 먼저 올 때만 쓰입니다. 개인 설정이 없는 새 직원은 2.7을 쓸 수 있습니다. 그러면 설치는 성공하지만 tmux 설정을 읽을 때 통합 파일이 오류를 내고, Board binding·hook이 들어가지 않습니다. 설치 계약에 tmux 최소 버전이 없고 설치기 `check`도 이를 알리지 않습니다.

## Evidence
- RELEASE-002 Worker 확인(2026-11-09, `docs/cr/done/RELEASE-002-tmux.md` Result): tmux 2.7은 통합 파일의 `{ }` 문법을 읽지 못함. 안내문 `docs/install.md` 1절은 "3.8에서 검증, 2.7 불가, 그 사이 미검증"으로만 적음.
- `/usr/bin/tmux -V` → `tmux 2.7`, `which -a tmux` → 사내 3.8이 먼저, 그 다음 `/usr/bin/tmux`.
- 설치 계약 3절·3.1절·5.3절: 통합 파일의 동작은 적었지만 필요한 tmux 버전은 없음. 7절 `check` 항목에도 없음.

## Contract
- 사용자 결정(agent D-20261109-08 C): 다른 직원에게 배포합니다. 설치본만으로 동작하거나, 동작할 수 없으면 그 사실과 해소 방법을 분명히 알려야 합니다.
- 설치 계약 7절: `check`는 설치가 동작하는지 확인하고 실패를 알립니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). RELEASE-002 Worker가 결정을 요청했으나, 지원하는 tmux에서 동작하지 않는데 알리지도 않는 것은 결함이므로 위임 범위입니다(사용자 지시 2026-11-09: 동작 결함은 Leader가 최적의 방법을 정함). RELEASE-003(빈 HOME 시범 설치)은 시스템 PATH의 tmux 2.7을 만나므로 이 CR 뒤에 합니다.
- 2026-11-09 Leader: 제출 adcd37e1c8e3c35a09cabbef96cd3b94ea03c830를 인수합니다. Leader review: Worker 확인 요청(외부 망 차단으로 CHANGES 없음)에 대한 판정: 이 host의 2.7·3.6a·3.8 실행 결과로 만든 근거 표를 받아들입니다. 가장 높은 요구는 이름 붙은 hook index이며 3.6a 실패·3.8 동작을 직접 확인했으므로, 검증된 가장 낮은 동작 버전 3.8을 최소로 둔 것은 사실에 맞는 보수적 판정입니다(3.7은 확인되면 값만 바꿈). 판정은 release 안의 파일에서 2.7도 읽는 문법으로 하고 고정 파일은 그대로라 upgrade로 적용됩니다. 2.7·3.6a는 한 줄 안내만, check는 PATH 첫 tmux가 낮으면 실패와 해소 방법. 수정 전 재현, README 표대로 네 번째 명령 83·test_tmux_control 15·install/tests 253 passed(merge 뒤).
- 2026-11-09 Leader: in-progress -> done, Outcome fixed. 통합 5b73d6a(Merge cr/TMUX-002, 제출 adcd37e). origin/main 반영 확인. CHANGELOG Unreleased에 더했습니다.

## Implementation
읽을 문서: [설치 계약](../../project-team/install-contract.md) 3절·3.1절·5.3절·7절, `integrations/tmux/project-agent.conf`, [안내문](../../install.md) 1절, tmux의 `CHANGES`(사내 tmux 설치본 또는 tmux 저장소).

1. 최소 버전을 근거로 정합니다. 통합 파일과 `project_agent_bind.sh`·`tmux_decide_status.sh`가 쓰는 tmux 기능을 모두 나열하고, 각 기능이 들어온 tmux 버전을 `CHANGES`로 확인해 표로 Result에 적습니다. 그중 가장 높은 버전이 최소 버전입니다. 이 host에서 실행해 볼 수 있는 버전(2.7, 3.8)은 실제로 확인합니다.
2. 계약 3절에 최소 버전을 원본으로 한 곳에 적습니다. 안내문 1절의 tmux 행은 그 절을 link하고 값을 다시 쓰지 않습니다(지금 "3.8 검증, 2.7 불가" 문장을 바꿈). 사내 tmux 경로 안내는 유지합니다.
3. 오래된 tmux에서의 동작을 정합니다. 최소 버전보다 낮은 tmux가 설치된 `tmux.conf`를 읽으면 parse 오류 대신 한 줄 안내(최소 버전과 사내 tmux 경로)를 보이고 아무것도 binding하지 않습니다. 2.7이 통합 파일 전체를 parse하기 전에 갈라야 하므로, 버전 판정은 2.7도 읽을 수 있는 문법으로 하십시오. 갈래를 두는 위치가 계약 2절의 고정 파일(`~/.local/lib/project-agent/tmux.conf`, "설치 때 한 번 쓰고 갱신하지 않음")이면 그 계약을 먼저 고치고, 이미 설치된 사람에게 미치는 영향(그 파일은 갱신되지 않음)을 적으십시오. 고정 파일을 바꾸지 않고 release 안의 파일에서 가를 수 있으면 그쪽을 택합니다.
4. 설치기 `check`가 PATH에서 처음 찾은 `tmux`의 버전을 확인합니다. 최소 버전보다 낮으면 실패(종료 코드 1)이고, 해소 방법(사내 tmux 경로를 PATH 앞에 둠)을 알립니다. `install`도 같은 사실을 안내합니다(설치는 진행). 계약 7절의 `check` 항목에 더합니다.

범위 밖: tmux 2.x용으로 통합 파일을 다시 쓰는 일(최소 버전 아래는 지원하지 않음을 알리는 것까지가 범위).

의존: 선행 없음. 후행 RELEASE-003.

위험 등급: 중간. 모든 사용자가 읽는 tmux 설정 경로를 바꿉니다.

## Verification
1. 재현(수정 전): 격리 tmux server를 `/usr/bin/tmux`(2.7)로 띄워 설치본 `tmux.conf`를 읽으면 parse 오류가 납니다. 같은 격리 HOME에서 `check`는 통과합니다(알리지 않음).
2. 수정 뒤: 2.7로 읽으면 오류 없이 한 줄 안내만 보이고 binding·hook·`@project_agent_*` option이 없습니다. 3.8로 읽으면 지금과 같이 binding·hook이 들어갑니다(기존 `integrations/tmux` test 통과). PATH 첫 `tmux`가 2.7인 격리 HOME에서 `check`가 실패와 해소 방법을 보이고, 3.8이면 통과합니다.
3. 최소 버전 근거 표(기능 → 도입 버전 → 출처)가 Result에 있습니다.
4. 영향 회귀: `install/tests`와 README 네 번째 명령(`integrations/tmux` 포함)이 통과합니다.

## Result
- 제출 commit: adcd37e1c8e3c35a09cabbef96cd3b94ea03c830

`origin/cr/TMUX-002`에 push했습니다. 첫 구현은 d9b6339이고, adcd37e는 `origin/main`(TEST-004, REPO-003)을 merge하고 충돌을 푼 것입니다.

### 결정과 변경
- **최소 버전은 tmux 3.8입니다.** 이 host에서 실행해 본 가장 낮은 동작 버전이 3.8이고, 3.6a에서도 통합 파일이 동작하지 않습니다(아래 표). 3.7은 이 host에 없어 검증하지 못했고 지원하지 않는다고 적었습니다.
- 판정 위치는 release 안의 파일입니다. 계약 2절의 고정 파일 `~/.local/lib/project-agent/tmux.conf`는 바꾸지 않았으므로 이미 설치한 사람도 `upgrade`로 적용됩니다.
  - `integrations/tmux/project-agent.conf`: tmux 2.x도 parse하는 문법만 씁니다. `#{version}`을 `@project_agent_tmux_min`과 비교해, 이상이면 `source-file -F`로 본체를 읽고 아니면 오류 한 줄(최소 버전과 사내 tmux 경로)을 냅니다. option은 판정 뒤 지웁니다.
  - `integrations/tmux/project-agent-main.conf`: 옛 `project-agent.conf` 내용(`git mv`)입니다. 읽는 쪽 경로 `project-agent.conf`는 그대로입니다.
- 안내가 오류 한 줄인 이유: 2.7과 3.6a 모두 시작할 때 `run-shell`·`display-message` 출력은 첫 client에 보이지 않았고, 설정 오류만 보였습니다(pty로 attach해 확인).
- 설치기(`install/project_agent_install/tmuxconf.py`, `commands.py`): PATH 첫 `tmux -V`를 판정 파일의 `@project_agent_tmux_min` 줄과 비교합니다. `check`는 낮으면 실패(종료 코드 1)와 해소 방법을 알리고, `install`은 같은 안내를 하며 설치는 진행합니다. PATH에 tmux가 없으면 둘 다 안내만 합니다(실패 아님).
- 문서: 계약 3.2절 신설(최소 버전, 판정, 코드 원본), 5.3절 링크·option 설명, 7절 `check` 항목. 안내문 1절 tmux 행은 3.2절을 link하고 값을 쓰지 않습니다(사내 tmux 경로 안내는 유지). 제품 지도 README의 파일 목록을 갱신했습니다.
- SSOT: 코드의 원본은 `project-agent.conf`의 `@project_agent_tmux_min` 한 줄이고, 계약 3.2절의 "최소 버전: tmux 3.8" 줄과 같은지는 `install/tests/test_tmux_version.py`가 검사합니다. 판정 파일은 2.7이 읽을 수 있어야 해서 오류 문구에 같은 값을 한 번 더 씁니다(test가 일치를 검사). 사내 tmux 경로 문자열도 판정 파일·설치기·안내문에 있으며 test가 판정 파일과 안내 문구의 일치를 검사합니다.
- 형식 버전: 남는 server option이나 CLI·JSON 형식은 바뀌지 않았습니다(`@project_agent_tmux_min`은 읽는 동안만 있음). `tools/formats.json`은 건드리지 않았습니다.

### 근거 표: 기능 → 도입 버전 → 출처
**한계(Leader 확인 필요):** 이 host는 외부 망이 막혀(`curl`, WebFetch가 접속 거부·시간 초과) tmux 3.x의 `CHANGES`를 얻지 못했습니다. `/usr/share/doc/tmux/CHANGES`는 2.6→2.7 구간뿐이고, WebSearch는 3.7 changelog의 제목만 돌려줬습니다. 그래서 "도입 버전"은 CHANGES가 아니라 이 host의 세 바이너리(2.7, 사내 3.6a, 사내 3.8)에서 각 문법을 같은 격리 server에 읽혀 본 결과입니다. 출처 열의 ✗/✓는 그 바이너리에서의 실행 결과입니다. 그래서 정확한 도입 버전 대신 "이 구간에서 들어옴"만 압니다.

| 기능 (사용처) | 2.7 | 3.6a | 3.8 | 알 수 있는 것 |
| --- | --- | --- | --- | --- |
| `{ }` 명령 블록 (`after-resize-pane`·`pane-died` hook, `MouseDown1Pane` binding) | ✗ `usage: if-shell`, `unknown command: {` | ✓ | ✓ | 2.7 이후 ~ 3.6a |
| 이름 붙은 hook index `hook[project-agent]` (hook 8개 전부, 이름 기준 교체) | 읽히지만 hook으로 동작하지 않음 | ✗ `invalid option: client-attached[project-agent]` | ✓ | **3.6a 초과 ~ 3.8: 가장 높은 요구 → 최소 버전 결정** |
| `set-hook -gw`·`-gwu` (window scope hook 3개) | ✗ usage | ✗ (이름 index 때문에 `invalid option`, 분리 못 함) | ✓ | 위와 같음 |
| `run-shell -C` | ✗ usage | ✓ | ✓ | 2.7 이후 ~ 3.6a |
| `list-keys -T <table> <key>` (`project_agent_bind.sh`) | ✗ usage: 키 인자 없음 | ✓ | ✓ | 2.7 이후 ~ 3.6a |
| `display-popup` (Board) | ✗ unknown command | ✓ | ✓ | 2.7 이후 ~ 3.6a |
| `#{d:current_file}`, `set-option -gF`, `#{q:..}`, `#{E:..}`, `#{==:}`·`#{!=:}`·`#{&&:}`, `if-shell -F`, `run-shell -b`, `source-file -q`, `source-file -F`(판정 파일), `show-options -gqv`, `set-option -gu`, `#{version}` | 오류 없이 읽힘(2.7에서의 의미는 검증하지 않음. 판정 파일은 `#{version}`이 2.7에서 `2.7`로 풀리는 것만 확인) | ✓ | ✓ | 3.6a에서 모두 동작. 최소 버전을 높이지 않음 |

최소 버전 = 가장 높은 요구 = 이름 붙은 hook index. 3.6a에서 안 되고 3.8에서 되는 것을 직접 확인했습니다. 3.7에서 되는지는 확인하지 못했습니다. **3.7 계열을 지원 범위에 넣고 싶으면 3.7 바이너리나 `CHANGES`로 확인한 뒤 판정 파일과 계약 3.2절의 값을 바꾸십시오.**

### 검증
1. 수정 전 재현(`742d60b`의 통합 파일, 격리 server `-S`):
   - 2.7: `unknown command: {`, `usage: run-shell ...` 오류 여러 줄, `'/project_agent_bind.sh --socket ' returned 127`. `@project_agent_*` option 2개가 남음. attach하면 설정 오류 view가 보임.
   - 3.6a: `invalid option: client-attached[project-agent]` 등 hook 8개가 모두 오류. option 3개가 남음.
   - 이 상태에서 설치기 `check`는 tmux 버전을 보지 않아 통과했습니다(수정 전 코드에는 tmux 검사가 없음).
2. 수정 뒤(실제 설치기, 격리 HOME, `env -i`로 PATH만 지정):
   - 2.7 server가 설치본 `tmux.conf`를 읽음: 오류 한 줄 `invalid option: project-agent needs tmux 3.8 or newer: put /primehome/tools/Inhouse/tmux/latest/bin first in PATH`. option·hook·binding 모두 0개.
   - 3.8 server: option 3개, hook 5개(session scope), 제품 binding 2개. 이전과 같음.
   - 3.6a: 2.7과 같이 한 줄만, 아무것도 없음.
   - PATH 첫 tmux가 `/usr/bin/tmux`(2.7)인 격리 HOME에서 `install`은 같은 안내를 하며 종료 코드 0, `check`는 `FAIL: The tmux first in PATH is 2.7 (/usr/bin/tmux), older than the minimum 3.8; ... Put /primehome/tools/Inhouse/tmux/latest/bin before it in PATH.`와 종료 코드 1. 사내 3.8이 먼저이면 `OK`, 종료 코드 0. (`env -i`가 `LD_LIBRARY_PATH`를 지워 사내 tmux가 실행되지 않은 첫 시도는 환경 문제였고, 환경 변수를 넘겨 다시 확인했습니다.)
3. 근거 표: 위.
4. 영향 회귀(README 변경 경로 표: `integrations/tmux/**` → 네 번째 명령, `test_tmux_control.py`, `install/tests`). `origin/main` merge(adcd37e) 뒤 다시 실행했습니다.
   - `python -m pytest -q integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py` → 83 passed
   - `python -m pytest -q tools/project-board/tests/test_tmux_control.py` → 15 passed
   - `python -m pytest -q -n 8 install/tests` → 253 passed, 2 skipped (merge 전 같은 명령도 253 passed, 2 skipped)
   - 새 test: `integrations/tmux/test_project_agent_conf.py`(최소 버전 미만이면 한 줄·아무것도 남기지 않음, 최소 버전이면 본체를 읽음, 문구 일치, 이 host의 실제 2.7로 실제 파일을 읽음 — 2.7이 없는 host에서는 skip), `install/tests/test_tmux_version.py`(stub tmux로 `check` 실패·통과 경계 `2.7`·`3.6a`·`3.0`·`master`·`unknown` 실패, `3.8`·`3.9a`·`3.10`·`next-3.9`·`4.0` 통과, `install` 안내와 설치 진행, tmux 없음은 안내, 계약 값 일치). 새 test의 tmux server는 `tmux_test_server` helper로 만들고 끝내며, 2.7 server는 helper의 cleanup이 PATH의 3.8 client로 접속하지 못하므로 `kill-server`를 그 binary로 한 번 더 부릅니다.
- 범위 밖으로 남긴 것: 2.x용 통합 파일 재작성, 3.7 검증. 영향이 이미 설치된 사람에게 미치는 방식은 위 "판정 위치"와 같습니다(고정 파일은 그대로, release 갱신으로 적용).
