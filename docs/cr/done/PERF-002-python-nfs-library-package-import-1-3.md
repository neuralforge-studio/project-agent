# PERF-002: 명령마다 Python 시동과 NFS의 표준 library·package import에 1~3초가 듭니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: PERF-001, SESSION-010, TMUX-003, RUST-001
- Base: 73d45379ada1a537b49b31c59ddc6c85c0914d2d 2026-11-10T08:38:15+09:00
- Outcome: fixed

## Symptom
`agent-session`·`project-item`·`project-board` 명령과 tmux hook은 실행할 때마다 bash launcher와 Python interpreter를 새로 띄웁니다. 그리고 표준 library와 도구 package를 NFS(`/primehome`)에서 읽습니다. 실제 사용처럼 명령 사이가 1분을 넘으면 이 시동만으로 명령 하나에 1~3초가 걸립니다. 사용자 지시(2026-11-10): "Python 시동이 느린 것도 같이 고쳐줘."

## Evidence
- Leader 측정(2026-11-10, 설치본 0.3.0, interpreter `/primehome/tools/Inhouse/Python3/latest`(3.12), 도구와 interpreter 모두 NFS4이고 mount 옵션 `acregmin=60,acdirmin=60`):
  - 연속 실행(warm, 7회 중앙값, load 79~88):

    | 실행 | 시간 |
    | --- | --- |
    | `python3 -c pass` | 58ms |
    | `-S` | 37ms |
    | `-I -S` | 29ms |
    | `import agent_session.cli` | 152ms |
    | `agent-session --help` | 222ms |
    | bash launcher(`python-launcher.sh` 선택만) | 40ms |

  - 간격을 둔 실행(cold, load 45~65):
    - `python3 -c pass`: 133ms
    - `agent-session review --clear`: 3.1초
      - cProfile 안의 시간은 1.1초이고, 그중 import가 0.85초입니다.
      - import 시간은 대부분 `.pyc` 68개를 NFS에서 여닫는 시간(`open_code`·`__exit__` 0.66초)입니다.
      - 나머지 약 2초는 launcher와 interpreter 시동, 그리고 sys.path 탐색입니다(가설. 측정은 이 CR과 PERF-001에서).
  - `-X importtime`(`import agent_session.cli`):
    - site 97ms. 그중 `_distutils_hack` 36ms는 Inhouse site-packages의 `.pth`입니다.
    - argparse 209ms. 그중 re 180ms입니다.
    - encodings 58ms.
    - 실제로 import한 module 65개 가운데 62개가 표준 library와 site입니다.
  - `review --clear` cProfile:
    - claude project인데 `providers/codex.py`를 import합니다(0.24초).
    - `load_registry`가 tomllib을 import합니다(0.10초).
- `sys.path`는 cwd·도구 디렉터리·없는 `python312.zip`·stdlib·lib-dynload·site-packages 순입니다. import마다 이 경로를 차례로 확인합니다.

## Contract
- CLI의 인자·JSON·exit code와 Python API는 바꾸지 않습니다. [설치 계약 6.1](../../project-team/install-contract.md)의 interpreter 선택 규칙(`PROJECT_AGENT_PYTHON`·`python.env`·platform 규칙)도 그대로 지킵니다. 규칙을 바꿔야 하면 계약 문서를 먼저 고치고 그 이유를 적습니다.
- 사용자 site-packages와 환경 변수가 도구 동작을 바꾸지 않는다는 기존 규칙(`PYTHONNOUSERSITE` 등)을 유지합니다.
- 상주 process(daemon)와 Rust 전환은 이 CR의 범위가 아닙니다. Rust는 RUST-001이 측정값을 근거로 사용자 결정 항목으로 정합니다.

## Disposition
- 2026-11-10 Leader: 고친다. 재현 측정이 있는 결함이고, 사용자 지시가 있습니다(2026-11-10 대화 원문: "Python 시동이 느린 것도 같이 고쳐줘."). PERF-001·SESSION-010과 동시에 진행합니다.
- 2026-11-10 Leader: open -> todo. 사용자 지시로 즉시 수정
- 2026-11-10 Leader: 제출 944ab5b0e87922df2079552859a8f97435fd56a7를 인수합니다. Leader review(ad974fe와 944ab5b): 다섯 가지를 확인했습니다. 고른 provider만 import합니다. 표준 library만 쓰는 진입점(agent-session, project-item, 상태줄, Board의 sync·click·toggle)은 -S로 시작합니다. -E·-I는 쓰지 않아 PYTHON* 환경과 PROJECT_AGENT_PYTHONPATH가 그대로입니다. pending_releases 본문을 api.release_waits로 옮겨 원본이 하나입니다. 진입 script는 #!/bin/bash와 builtin 경로 계산을 쓰고, symlink일 때만 readlink -f를 실행합니다. cd -P로 물리 경로를 구하므로 current link를 지나는 호출도 같은 release 경로가 됩니다. 설치 계약 6.1에 이를 적었습니다. 측정은 Worker 표입니다(warm CPU 14~27% 감소, --help·sync wall 20~25% 감소). review --clear·ls와 cold는 오차 안이라 확정하지 못했습니다. 공식 A/B는 PERF-001 도구로 잽니다. 검증은 merge commit 944ab5b에서 다섯 명령입니다. 네 번째 명령의 4건 실패는 TMUX-003 test 격리 결함으로 판정합니다(사용자 cache의 .view를 읽음, origin/main에서도 같음, XDG_CACHE_HOME을 격리하면 125 passed). TEST-012로 엽니다.
- 2026-11-10 Leader: in-progress -> done, Outcome fixed. 통합 d2326ce(Merge cr/PERF-002, 제출 944ab5b). origin/main 반영 확인. CHANGELOG Unreleased에 더했습니다.

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), [설치 계약](../../project-team/install-contract.md)(6.1 interpreter 선택), [실행 경로 계약](../../project-team/README.md#실행-경로-계약), [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 수정 전 기준을 잽니다.
   - 대상 명령:
     - 세 도구의 `--help`
     - `agent-session review --clear`
     - `project-item ls`
     - `project-board` 진입
     - tmux hook entry(`project_agent_run.sh`가 부르는 것)
   - 각 명령을 warm(연속)과 cold(NFS attribute cache 만료 뒤. `acregmin=60`이므로 61초 이상 간격)로 나눠 잽니다.
   - 시간을 다음으로 나눕니다.
     - bash launcher
     - interpreter 시동
     - site 처리
     - module별 import(`-X importtime`)
     - NFS에서 연 파일 수(`strace -c -e trace=file` 등)
   - PERF-001의 측정 도구가 먼저 main에 들어오면 그 도구로 v0.3.0과 A/B 비교합니다. 아직 없으면 같은 방법을 Result에 적고 직접 잽니다.
2. 줄이는 방법은 측정으로 고르고, 고른 근거를 Result에 적습니다. 후보는 다음과 같습니다.
   - (a) 명령이 쓰지 않는 module을 import하지 않음. 예:
     - 등록 project가 쓰지 않는 provider(`providers/codex.py`)
     - `tomllib`
     - subcommand가 쓰지 않는 lifecycle·remote module
   - (b) 표준 library만 쓰는 도구(`agent-session`·`project-item`, tmux hook)는 site 처리를 하지 않음. `-I`·`-S` 같은 interpreter 옵션이나 sys.path를 직접 구성합니다. 외부 package가 필요한 `project-board`는 `PROJECT_AGENT_PYTHONPATH`만 더합니다.
   - (c) import 할 때 확인하는 경로와 파일 수를 줄임. 예: 설치기가 release 안의 package를 미리 compile하거나 한 파일로 묶습니다. 설치기를 바꾸면 [설치 계약](../../project-team/install-contract.md)과 `install/tests`를 함께 고칩니다.
   - (d) bash launcher의 비용을 줄임. 예: 바깥 process(`readlink`·`uname`·`dirname`)를 builtin으로 바꿉니다.
3. 다음을 test로 고정합니다.
   - 대표 명령이 import하지 않아야 할 module이 다시 들어오지 않음. 예: claude project의 명령이 `providers.codex`를 import하지 않음.
   - site를 건너뛴 도구가 사용자 site-packages와 `PYTHONPATH`에 영향받지 않음.

의존: SESSION-010과 `tools/agent-session/agent_session/` 파일이 겹칠 수 있습니다(import 줄). 이 CR은 import와 진입 경로만 바꾸고 tmux 조회 코드는 고치지 않습니다. 제출 전에 `origin/main`을 merge합니다.

위험 등급: 중간. 모든 명령의 진입 경로와 설치 결과가 바뀝니다.

## Verification
1. 수정 전후 표를 Result에 적습니다. 1단계와 같은 방법으로 명령별 warm·cold 중앙값을 재고, 측정 때의 host load를 함께 적습니다. 차이가 측정 오차보다 큰지 보이도록 반복 횟수와 분산(p90 또는 범위)을 함께 적습니다.
2. 3단계의 test가 수정 전에 실패하고 수정 뒤에 통과함을 보입니다.
3. README 검증 표에서 바꾼 경로의 행을 모두 실행합니다. 예:
   - `tools/agent-session/**` → agent-session 전체(`-n 8`). `api.py`를 바꾸면 project-item·project-board·`install/tests`도.
   - `tools/python-launcher.sh` → 네 번째 명령과 `install/tests`.
   - `install/**` → `install/tests`.
   - `tools/project-item/**` → project-item.
   - `tools/project-board/**` → project-board.
4. 제출 전에 `origin/main`이 움직여 위 명령의 입력을 바꿨으면 merge하고 merge commit에서 다시 실행합니다.

## Result
- 제출 commit: ad974fe1baa7a7bba7774e0070c0bfbbcaa24663

branch `cr/PERF-002`(origin에 push함). base 73d4537에 origin/main(SESSION-010·TMUX-003, 36ca2b5 포함)을 merge한 commit입니다. 변경 commit은 35ea1d9(구현)와 3d2545c(test seam 정리)입니다.

### 측정에서 확인한 원인
- `agent-session review --clear` 한 번의 syscall 기록(strace, 설치본 0.3.0):
  - `openat` 2971건 중 2683건, `stat` 3318건 중 2463건이 ENOENT입니다. 대부분은 `LD_LIBRARY_PATH`(사용자 환경의 NFS 디렉터리 8개 이상 × `glibc-hwcaps`·`haswell`·`tls` 하위 디렉터리)에서 `libc.so.6`·`libncursesw.so.6` 등을 찾는 것입니다. exec하는 process마다 반복됩니다.
  - `execve` 107건 중 92건이 실패입니다. 진입 script의 `#!/usr/bin/env bash`가 PATH의 NFS 디렉터리 약 20곳을 차례로 찾고, `readlink`·`dirname`을 진입 script와 launcher가 각각 한 번씩(총 4번) exec합니다.
- import: `project-item ls`는 `pending_releases` 때문에 `lifecycle`(Manager, suspend, watch 등 module 약 14개)을 모두 import했습니다. claude project도 `providers.codex`(tomllib, websocket, urllib)를 import했습니다.
- 바꾸지 않은 것: 사용자 `LD_LIBRARY_PATH`의 NFS 탐색(자식 tmux·claude가 그 경로의 library를 씁니다), cwd가 `sys.path[0]`인 것, `dataclasses`→`inspect` import(project-item도 씁니다), stdlib의 pyc 읽기 수.

### 구현 (고른 방법의 근거는 위 측정)
- (a) 쓰지 않는 module을 import하지 않음:
  - `providers/__init__.py`: `get_provider`가 고른 provider만 import합니다.
  - `cli.py`의 `traceback`, `lifecycle.py`의 `uuid`, `remote.py`의 `zipfile`·`base64`·`io`는 쓰는 함수 안에서 import합니다.
  - `pending_releases`의 본문을 `api.release_waits`로 옮겼습니다. `Manager.pending_releases`는 이것을 부릅니다(SSOT 한 곳). `project-item ls`와 Board는 `lifecycle`을 import하지 않습니다. 결과 모양과 `view` 인자(SESSION-010)는 그대로입니다. `pending_releases(cwd, ...)`는 `require_base`를 적용하지 않는 기존 동작을 유지합니다.
  - `project-item ls`의 import module 수: 167 → 141. `agent-session review --clear`: 147 → 138.
- (b) site 처리를 하지 않음: `agent-session`·`project-item`·`tmux_decide_status.sh`는 `-S`로 시작합니다. `project-board`는 textual을 import하지 않는 `sync`·`click`·`toggle`(tmux hook·key)만 `-S`, TUI 명령은 site를 처리합니다. `-E`·`-I`는 쓰지 않아 `PYTHON*` 환경 변수와 `PROJECT_AGENT_PYTHONPATH`의 효과는 그대로입니다. interpreter 선택 규칙(6.1)은 바꾸지 않았고 6.1절에 `-S`와 아래 (d)를 추가로 적었습니다.
- (d) bash launcher: 진입 script를 `#!/bin/bash`로(project-item·project-board는 원래 그랬음), `dirname`과 launcher의 `readlink`를 builtin(`${var%/*}`, `cd -P`)으로 바꿨습니다. symlink로 부를 때만 `readlink -f`를 한 번 실행합니다(exec 4회 → 1회, `/usr/bin/env`의 PATH 탐색 제거).
- (c) 설치기 변경(미리 compile·묶기)은 하지 않았습니다. 설치기는 이미 release를 미리 compile하고, 위 (a)가 파일 수를 줄입니다.

### 수정 전후 시간
방법: `ab.py`(scratchpad. 수정 전 = 설치된 0.3.0 release, 수정 후 = 작업 tree를 같은 `python.env`로 복사해 미리 compile한 release 모양 복사본). 각 명령을 A·B 번갈아 실행하고 wall(ms)과 `wait4`의 user+sys CPU(ms)를 잽니다. cwd는 이 seat입니다. `pb_sync`는 없는 socket을 줘서 Python 시동·import 경로만 잽니다. PERF-001의 측정 도구는 main에 아직 없어 직접 잰 방법입니다. 수정 후 측정은 merge 전 구현(35ea1d9)과 같은 내용입니다(merge는 pending_releases의 `view` 합치기와 `tmux_decide_status.sh` 충돌 해소만 바꿨습니다).

warm(연속 15회, host load1 30):

| 명령 | 전 wall 중앙/p90 | 후 wall 중앙/p90 | 전 CPU | 후 CPU |
| --- | --- | --- | --- | --- |
| agent-session --help | 293 / 484 | 231 / 327 | 154 | 110 |
| agent-session review --clear | 741 / 904 | 690 / 890 | 352 | 287 |
| project-item --help | 630 / 770 | 479 / 615 | 260 | 201 |
| project-item ls | 1026 / 1561 | 1025 / 1214 | 539 | 453 |
| project-board --help | 238 / 367 | 181 / 226 | 119 | 87 |
| project-board sync | 429 / 831 | 310 / 586 | 236 | 196 |

- CPU는 모든 명령에서 14~27% 줄었습니다. wall은 `--help`·`sync`에서 20~25% 줄었고, `review --clear`·`project-item ls`는 중앙값 차이가 범위(예: ls 전 774~1881, 후 634~1316)보다 작아 측정 오차 안입니다(이 두 명령의 나머지 시간은 tmux 조회와 state 읽기이며 SESSION-010의 범위입니다).
- 같은 방법으로 먼저 잰 9회(host load 105)도 같은 방향이었습니다(as_help 683→653, review --clear 1519→1182, pi_help 1415→1219, pi_ls 1836→1503, pb_sync 925→808).

cold(명령마다 65초 간격, 4회, load1 77→33):

| 명령 | 전 wall 중앙/최대 | 후 wall 중앙/최대 |
| --- | --- | --- |
| agent-session --help | 422 / 859 | 539 / 578 |
| agent-session review --clear | 1195 / 1456 | 858 / 1033 |
| project-item ls | 1317 / 2216 | 1164 / 2824 |
| project-board sync | 624 / 2576 | 519 / 1119 |

- 반복 4회와 분산(최대가 중앙값의 2배 이상)으로는 cold의 개선 폭을 확정하지 못합니다. `review --clear`와 `sync`는 중앙값과 최대가 모두 낮아졌고 `--help`는 반대입니다. 이 host는 사용자 25명이 공유해 NFS의 stdlib 쪽 attribute cache가 항상 따뜻하므로, 1~3초의 cold 시동을 이 host에서 재현하지 못했습니다(Leader의 3.1초 측정은 재현하지 못함). 효과의 근거는 warm CPU 감소와 exec·ENOENT 감소입니다. PERF-001 도구가 들어오면 같은 표를 다시 잴 수 있습니다.

### 검증
- test 고정(Verification 2): 새 test가 수정 전(73d4537)에서 실패하고 수정 뒤 통과합니다. 수정 전 tree에 test 파일만 복사해 실행했습니다.
  - `tools/agent-session/tests/test_startup_imports.py` 4건: claude project가 codex provider·tomllib·websocket을 import하지 않음, codex project가 claude provider를 import하지 않음, `agent_session.api`가 zipfile·base64·lifecycle을 import하지 않음, `pending_releases`가 lifecycle을 import하지 않음(수정 전 4건 모두 실패).
  - `tools/test_python_launcher.py`: site를 건너뜀(`sitecustomize`가 실행되지 않음. agent-session·project-item), `project-board`의 `-S` 여부(sync·click·toggle만), 진입 script가 자기 디렉터리에서·link된 디렉터리를 거쳐 실행됨. 수정 전에는 `-S` 관련 6건이 실패했습니다.
  - 기존 test 중 `ARGV1=-c`·`-m`을 보던 두 곳을 새 호출(`-S`)에 맞췄습니다.
- test seam 두 곳을 고쳤습니다(제품 동작 변경 아님). `-S`가 site 단계를 건너뛰므로 `sitecustomize`로 주입하던 것이 사라집니다.
  - `install/tests/harness.py`: fake provider를 `sitecustomize`로 주입하던 `Runs`가 `-S`만 빼고 실제 interpreter를 실행하는 test 전용 wrapper를 `PROJECT_AGENT_PYTHON`으로 씁니다(고치기 전 install 17건 실패, 고친 뒤 통과).
  - `integrations/tmux/test_project_agent_conf.py`: fake python이 기록하는 인자에 `-S`를 더했습니다.
- README 표 실행(Verification 3, merge commit ad974fe에서 실행. 바꾼 경로 `tools/agent-session/**`(api.py 포함), `tools/project-item/**`, `tools/project-board/**`, `tools/python-launcher.sh`, `integrations/tmux/**`, `install/**`, `docs/**`에 해당하는 다섯 명령 전부):
  - `python -m pytest -q -n 8 tools/agent-session/tests`: 810 passed (20분 32초)
  - `python -m pytest -q tools/project-item/tests`: 125 passed
  - `python -m pytest -q tools/project-board/tests`: 161 passed
  - `python -m pytest -q integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py`: 123 passed
  - `python -m pytest -q -n 8 install/tests`: 267 passed, 2 skipped
- merge 판정(Verification 4): origin/main(SESSION-010, TMUX-003)이 `api.py`·`lifecycle.py`·`tmux_decide_status.sh`의 입력을 바꿨으므로 merge한 commit에서 위 다섯 명령을 모두 다시 실행했습니다. 충돌 세 곳(`pending_releases`의 `view` 인자, `project_pending_releases`, `tmux_decide_status.sh`의 view cache 앞 분기)은 upstream 동작을 그대로 두고 위 변경을 얹었습니다.
- 알려진 한계: 설치본 확인(`install/project-agent-install check`)은 격리 HOME의 install/tests로만 했고, 이 workstation의 관리 run과 `~/.local/bin`은 동결 사본이라 건드리지 않았습니다.

### 수정 제출 (origin/main 4de08e8 merge)
- 제출 commit: 944ab5b0e87922df2079552859a8f97435fd56a7

Leader 요청(v0.4.0 통합 뒤 `origin/main` 4de08e8을 `cr/PERF-002`에 merge)으로 merge commit `944ab5b`를 만들었습니다. 충돌은 없었고(PERF-001 `tools/tests/perf`, TEST-009·010·011, v0.4.0의 VERSION·CHANGELOG), 코드 변경은 추가하지 않았습니다. merge가 README 다섯 명령의 입력을 모두 바꿨으므로 merge commit에서 다섯 명령을 모두 다시 실행했습니다. 이 실행은 TEST-010·TEST-011 통합 뒤 main 조합의 확인을 겸합니다. 측정 표는 이번에 다시 재지 않았습니다(PERF-001이 v0.3.0 대 `cr/PERF-002`로 잽니다).

- `python -m pytest -q -n 8 tools/agent-session/tests`: 810 passed
- `python -m pytest -q tools/project-item/tests`: 125 passed
- `python -m pytest -q tools/project-board/tests`: 161 passed
- `python -m pytest -q integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py`: 처음 실행은 125건 중 4 failed(121 passed)였고, 4건은 모두 `tools/test_python_launcher.py`의 `tmux_decide_status.sh` 케이스입니다. `XDG_CACHE_HOME`을 빈 디렉터리로 격리해 같은 명령을 다시 실행하면 125 passed입니다.
- `python -m pytest -q -n 8 install/tests`: 267 passed, 2 skipped

### 네 번째 명령의 실패 4건: PERF-002 변경과 무관한 test 격리 문제
- 원인(확인한 사실): TMUX-003이 추가한 `tmux_decide_status.sh`는 `~/.cache/tmux-decide-status.view`가 유효하면(첫 줄의 만료 epoch 이전) Python을 실행하지 않고 저장된 상태줄(`#[fg=white,bg=red,bold] 결정 3 #[default]`)을 출력합니다. `tools/test_python_launcher.py`의 `run()`은 환경에서 `PROJECT_AGENT_*`와 `PYTHONPATH`만 빼고 `XDG_CACHE_HOME`·`HOME`은 그대로 넘기므로, 이 test가 실제 사용자 cache를 읽습니다. v0.4.0 설치 뒤 이 host의 tmux 상태줄이 view 파일을 15초마다 갱신하므로 test가 그 순간에 걸리면 fake python이 실행되지 않아 `ARGV1=`·exit 5·`LD=` 기대가 어긋납니다. 앞선 제출 실행(ad974fe, 같은 test)에서는 유효한 view가 없어 통과했습니다.
- 확인: `origin/main`(4de08e8)을 `git archive`로 풀어 같은 4건을 실행하면 기본 cache에서 같은 4건이 실패합니다. 내 merge commit에서 `XDG_CACHE_HOME`만 비운 디렉터리로 바꾸면 `tools/test_python_launcher.py` 46건이 모두 통과합니다.
- 조치: 이 CR에서는 고치지 않았습니다(요청 범위 밖, TMUX-003의 test 결함). 고치려면 `test_python_launcher.py`의 `run()`이 `XDG_CACHE_HOME`을 `tmp_path`로 격리하면 됩니다. 별도 CR이 필요합니다. 그 전에는 이 test를 상태줄이 view를 갱신 중인 host에서 실행할 때 `XDG_CACHE_HOME`을 비우고 실행해야 결과가 안정합니다.
