# PERF-003: 짧은 명령의 시간 대부분이 Python 시동과 NFS import이며 0.3~3초로 흔들립니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: PERF-001, PERF-002, RUST-001, D-20261110-02
- Base: 0eb2e262e2a939ae4497cd541a1d456db4e36108 2026-11-10T13:05:25+09:00
- Outcome: fixed

## Symptom
짧은 명령(`agent-session review`·`send`, `project-item ls`, `--help`)의 시간 대부분이 Python 시동과 NFS에서의 import입니다. 같은 명령이 NFS 상태와 유휴 시간에 따라 0.3초에서 3초까지 걸립니다. 반복 tmux 조회를 고친 뒤(SESSION-010) 명령 자체의 일은 수십 ms인데, 시동이 그 몇 배에서 수십 배입니다.

## Evidence
- Leader 측정(2026-11-10 13:00 전후, 설치본 0.4.0, load 45~52, `/primehome` NFS4 `acregmin=60`):
  - 0.3.0과 0.4.0 진입점을 번갈아 3회 실행했습니다. 첫 회(유휴 뒤)는 `agent-session --help`가 1.43~1.52초, `project-item --help`가 1.88~2.19초였습니다. 이어진 2·3회는 0.33~0.57초와 0.43~1.55초였습니다. `python3 -c pass`는 0.08~0.24초였습니다.
  - 그 직전 5회 연속 측정의 중앙값은 `agent-session --help` 2.79초, `review --clear` 4.89초, `project-item --help` 2.96초, `project-item ls` 2.06초였습니다. `python3 -S -c pass`는 0.18초였습니다.
- SESSION-010 Result(격리 fleet): `review --clear`의 tmux 일은 2번, 0.06초입니다.
- PERF-002 Result(설치본 0.3.0, strace):
  - `review --clear` 한 번에 `openat` 2971건이 있고, 그중 2683건이 ENOENT입니다. 대부분은 사용자 `LD_LIBRARY_PATH`의 NFS 디렉터리(× `glibc-hwcaps`·`haswell`·`tls`)에서 library를 찾는 것입니다. process를 exec할 때마다 반복됩니다.
  - `execve` 107건 중 92건이 실패합니다.
  - PERF-002는 이 가운데 진입 script의 `env` PATH 탐색과 `dirname`·`readlink` exec만 줄였습니다. 또 import 수를 줄였습니다(`project-item ls` 167 → 141 module).
- D-20261110-02 A: Rust 전환을 해법으로 정한 RUST-001은 닫았습니다. 남은 시동 비용은 해법을 정하지 않은 이 CR에서 측정으로 고릅니다.

## Contract
- CLI의 인자·JSON·exit code, Python API, 설치 계약의 interpreter 선택 규칙(6.1)은 바꾸지 않습니다. 바꿔야 하면 계약 문서를 먼저 고치고 이유를 적습니다.
- 개선량은 PERF-001의 측정 도구(`tools/tests/perf`)로 v0.4.0과 비교해 숫자로 보입니다. warm과 cold를 나눠 보입니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 재현 측정이 있는 속도 결함입니다. 해법은 측정으로 고릅니다(D-20261110-02 A). Rust 진입점이 필요하다는 결론이 나오면 범위를 사용자 결정 항목으로 묻고, 그 전에는 Rust 코드를 저장소에 넣지 않습니다.
- 2026-11-10 Leader: open -> todo. 재현 측정이 있는 속도 결함, 해법은 측정으로 선택
- 2026-11-10 Leader: 제출 5088d52e048b467608d712c2e0711f93ea7e13ac를 인수합니다. 검토 5088d52(구현 07a0959 + main 9d746d8 merge). 번들 writer·reader, 세 진입점, launcher, 설치기 연결, 문서를 읽었습니다. agent_session.py → run_module('agent_session')은 같은 main을 부릅니다. 도구 package에 importlib.resources·pkgutil·__loader__ 사용이 없어 loader 차이의 영향이 없습니다. README 표의 명령은 모두 실행됐습니다(변경 경로: install·launcher·세 도구·문서). merge 뒤 board·네 번째 명령도 다시 실행됐습니다. 고친 문서 세 개의 상대 link는 Leader가 확인했습니다(0 broken). A/B 결과 v0.4.0 대비 warm wall 비 0.18~0.27(명령 시동), CPU 비 0.49~0.62입니다. 95% 구간이 모두 1에서 멀어 A/A는 판정에 필요 없다고 Leader가 판정하고 생략합니다(사용자가 진행 속도를 요구). 구현 commit 제목이 wip(perf)인 것은 이력에 남지만 rewrite로 시간을 쓰지 않습니다. hook·controller의 번들 사용은 SESSION-011이 들어온 뒤 측정으로 판단합니다.
- 2026-11-10 Leader: in-progress -> done, Outcome fixed. 통합 2e73d06 (origin/main)

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), [설치 계약](../../project-team/install-contract.md)(6.1 interpreter 선택, release 구성), [실행 경로 계약](../../project-team/README.md#실행-경로-계약), 측정 도구 [`tools/tests/perf/perf_bench.py`](../../../tools/tests/perf/perf_bench.py) 머리말, [PERF-002 Result](PERF-002-python-nfs-library-package-import-1-3.md), [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 시간 분해: 대표 명령(`agent-session --help`·`review --clear`·`send`, `project-item ls`, `project-board sync`)의 시간을 warm·cold로 나눕니다.
   - (a) 동적 링크(`LD_LIBRARY_PATH` 탐색)
   - (b) interpreter 시동
   - (c) 표준 library import
   - (d) 도구 package import
   - (e) 명령 자체
   - 각 몫을 strace 등으로 근거와 함께 적습니다.
2. 후보를 시제품으로 만들어 측정 도구로 v0.4.0과 A/B합니다. 후보는 다음과 같고, Worker가 더해도 됩니다.
   - (A) 도구 package와 그 명령이 쓰는 표준 library module을 미리 compile한 한 archive로 묶어 import합니다(zipimport 등). 설치기가 release에 만듭니다.
   - (B) 우리 진입점이 exec하는 process의 동적 링크 탐색을 줄입니다. 예: 설치기가 고른 interpreter의 library 경로만 쓰는 방법이 있습니다. 단 자식 tmux·claude가 쓰는 사용자 `LD_LIBRARY_PATH`는 바꾸지 않습니다.
   - (C) 비교 기준(구현이 아님): 같은 host에서 아무 일도 하지 않는 최소 실행 파일(C 또는 Rust 한 줄)과 `python3 -S -c pass`의 warm·cold 시간을 잽니다. 언어를 바꿔 얻을 수 있는 한계를 숫자로 보이기 위해서이며, 저장소에는 넣지 않습니다.
3. 가장 효과가 큰 Python 쪽 방법을 구현합니다. 판정 기준은 cold 중앙값과 p90입니다. 남은 시간이 (C)의 최소 실행 파일보다 얼마나 큰지 Result에 적습니다.
4. 상주 process(daemon)는 이 CR의 범위가 아닙니다. 필요하다고 판단하면 근거와 함께 Leader에게 보고합니다.

의존: 없음.

위험 등급: 중간. 모든 명령의 진입 경로와 설치 결과가 바뀝니다.

## Verification
1. 측정 도구로 v0.4.0 대 후보의 warm·cold 표를 냅니다. 중앙값, p90, 반복 횟수, host load를 적습니다. 같은 실행본끼리의 A/A로 오차 범위도 함께 보입니다.
2. 1단계 분해표와 2단계 (C) 기준값을 Result에 적습니다.
3. README 검증 표에서 바꾼 경로의 행을 모두 실행합니다(`-rf`). 설치기를 바꾸면 `install/tests`를, launcher를 바꾸면 네 번째 명령과 `install/tests`를 실행합니다.
4. 제출 전에 `origin/main`이 움직여 위 명령의 입력을 바꿨으면 merge하고 merge commit에서 다시 실행합니다.

## Result
- 제출 commit: 5088d52e048b467608d712c2e0711f93ea7e13ac

branch `cr/PERF-003`(origin에 push). 검증을 마친 구현 commit 07a0959에 `origin/main`(9d746d8)을 merge한 commit입니다.

### 선택한 해법: 시동 번들 (후보 A를 한 파일 읽기로 바꾼 것)
- 설치기가 release를 만들 때 세 도구의 모든 모듈과 각 도구가 시동할 때 import하는 표준 library 모듈의 compile한 code를 한 파일 `tools/__pycache__/bundle.<cache tag>.pyc`에 씁니다([`install/project_agent_install/bundle.py`](../../../install/project_agent_install/bundle.py)). 세 CLI 진입점(`project-board`는 `sync`·`click`·`toggle`)은 launcher가 읽은 [`tools/bundle_boot.py`](../../../tools/bundle_boot.py)로 파일을 한 번 열고 header(색인)만 읽습니다. 모듈은 import할 때 `pread`로 가져옵니다. 파일 형식과 계약은 `bundle_boot.py` 머리말과 설치 계약 6.1절에 적었습니다.
- 보존 동작: `__file__`과 code의 파일 이름은 원래 source 경로입니다. 번들에 없는 모듈은 원래 경로에서 찾습니다. 번들이 없거나(개발 checkout), magic·`sys.version`이 다르거나, `-O`이거나, `bundle_boot.py`가 없으면 아무것도 하지 않고 일반 import가 맡습니다. CLI의 인자·JSON·exit code, Python API, interpreter 선택 규칙(6.1)은 바꾸지 않았습니다. release 지문은 번들을 `__pycache__`의 `.pyc`로 보아 뺍니다.
- 바뀐 파일: `tools/bundle_boot.py`(새), `tools/python-launcher.sh`(`project_agent_read_boot` 추가), 세 `bin/` 진입점(`agent-session`은 `agent_session.py` 대신 `run_module("agent_session")`), `install/project_agent_install/{bundle.py(새),actions.py}`, 설치 계약 6.1·2절, README, 제품 지도, CHANGELOG, test(`install/tests/test_bundle.py` 새, `tools/test_python_launcher.py` 한 건, `tools/test_distribution_boundary.py`).
- 설치 비용: `bundle.build`가 release마다 약 5초(load 40)입니다. 세 recorder 하위 process를 동시에 실행합니다.

### 1단계 분해표 (host srv04, load 36~50, `/primehome` NFS4 `acregmin=60`)
| 몫 | 근거 | 값 |
| --- | --- | --- |
| (a) 동적 링크 | `agent-session --help` strace(0.4.0): `openat` 788건 중 ENOENT 690건(사용자 `LD_LIBRARY_PATH` 8개 디렉터리 × hwcaps). 실패 open의 시간은 strace 합 0.03초(전체 1.4초). `python -S -c pass` 사용자 LD 전체 0.052초, python lib만 0.044초(warm, n=12). | warm 약 0.01초, 무시할 만함 |
| (b) interpreter 시동 | `python -S -c pass` warm 중앙값 0.044~0.124초(load에 따라), cold 0.07~0.10초(n=5 중앙값 0.099). bash launcher 0.035~0.064초. interpreter가 시동에 NFS에서 여는 `encodings` 3파일이 포함됩니다. | 0.05~0.12초 |
| (c)+(d) 표준 library·도구 import | 0.4.0 `project-item --help` 모듈 144개(표준 library 63+도구 20+동적 15+내장·frozen). strace: `.pyc` open 102건(0.236초)·`.so` 35건(0.045초)·close 160건(0.230초). 파일 하나의 open+close가 NFS에서 약 12ms입니다(load 47). 도구와 interpreter를 `/dev/shm`에 복사해 모두 local로 실행하면 `--help`가 0.20초(NFS 0.77~3.2초)입니다. | 시간의 약 85%, 파일 수에 비례 |
| (e) 명령 자체 | 번들 뒤 CPU 시간: `project-item ls` 0.286초, `--help` 0.189초. `review --clear` 0.232초(tmux 3회 포함). | 0.05~0.1초 CPU |

후보 시제품 결과:
- zipimport(표준 library만 한 zip): `project-item --help` warm 중앙값 1.04초 대 기준 0.77초로 개선이 없습니다. strace에서 zip을 모듈마다 다시 열었습니다(153회). 그래서 한 파일을 한 번 여는 번들로 바꿨습니다. (도구 모듈을 zip에 넣는 방법은 `__file__`의 `parents[n]`을 쓰는 코드 여러 곳 때문에 쓸 수 없습니다.)
- (B) `LD_LIBRARY_PATH` 축소: 번들 후보에서 사용자 LD를 뺀 cold `project-item --help` 중앙값 0.39초 대 0.49초(n=5, p90은 0.78 대 0.57로 뒤집힘). warm은 차이가 없습니다(0.351 대 0.369). 오차 범위 안이고 자식 환경 복원 코드와 계약 변경이 따라서 채택하지 않았습니다.
- (C) 기준(저장소에 넣지 않음, load 36~45, n=15):

| 실행 | warm 중앙값 [p90] | cold 중앙값 |
| --- | --- | --- |
| C 정적 최소 | 0.021 [0.057] | - |
| C 동적 최소 | 0.021 [0.066] | 0.011(n=1) |
| Rust 최소 | 0.032 [0.075] | 0.011(n=1) |
| `python3 -S -c pass` | 0.124 [0.312] | 0.099(n=5) |
| 0.4.0 `agent-session --help` | 1.806 [2.430] | - |
| 후보 `agent-session --help` | 0.385 [0.607] | - |
| 0.4.0 `project-item --help` | 3.181 [5.164] | 1.281 [1.794] (n=5) |
| 후보 `project-item --help` | 0.584 [0.965] | 0.486 [0.571] (n=5) |

남은 시간은 `python -S -c pass`보다 `--help`가 CPU 0.05초→0.12~0.19초 큽니다. 남은 시간은 모듈 body 실행 CPU와 NFS에서 읽는 동적 모듈 `.so` 13~15개입니다(`tempfile`→`shutil`·`random`이 `.so` 6~7개, `hashlib` 2개 등. 도구가 지연 import하면 줄일 수 있으나 이 CR에서는 하지 않았습니다). 최소 실행 파일(C·Rust, 0.01~0.03초)과의 차이는 `python -S -c pass`(0.05~0.12초)로 이미 큽니다. Python 시동 자체는 Python 쪽에서 줄일 수 없습니다. 언어를 바꾸면 얻는 한계가 약 0.1초 안팎이고, 이번 변경 뒤의 나머지(0.2~0.4초)도 대부분 모듈 import에서 옵니다.

### A/B (측정 도구 9d746d8, 4x4, `reps 9`, cold 5회 61초 간격, v0.4.0 설치본 대 후보 설치본, 격리 tmux)
host load는 warm 48~53, cold 71~83으로 높았습니다. 시간 대신 CPU 시간과 95% 구간으로 판정합니다(wall은 load에 따라 흔들립니다).

warm (n=9/9):
| 명령 | v0.4.0 wall s | 후보 wall s | wall 비 | 판정 | v0.4.0 cpu s | 후보 cpu s | cpu 비 | 판정 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| agent-session --help | 1.963 [1.478-3.988] | 0.439 [0.389-0.775] | 0.22 [0.12-0.38] | improved | 0.230 | 0.117 | 0.51 [0.48-0.55] | improved |
| project-item --help | 4.016 [2.643-6.658] | 0.740 [0.529-0.921] | 0.18 [0.12-0.27] | improved | 0.384 | 0.189 | 0.49 [0.47-0.54] | improved |
| agent-session review --clear | 4.597 [3.194-6.627] | 0.905 [0.598-1.180] | 0.20 [0.13-0.31] | improved | 0.447 | 0.232 | 0.52 [0.50-0.57] | improved |
| project-item ls | 5.020 [3.727-5.724] | 1.362 [1.119-1.951] | 0.27 [0.21-0.45] | improved | 0.512 | 0.286 | 0.56 [0.54-0.61] | improved |
| project-item check | 5.813 [5.066-8.684] | 3.833 [2.200-4.792] | 0.66 [0.32-0.89] | improved | 0.563 | 0.350 | 0.62 [0.61-0.70] | improved |
| agent-session watch | 7.101 [4.604-10.462] | 3.686 [3.280-5.187] | 0.52 [0.35-0.77] | improved | 0.835 | 0.617 | 0.74 [0.72-0.76] | improved |
| board_context·board_visible·board_snapshot_* | | | 0.87~1.12 | same | | | 0.97~1.05 | same | (번들을 쓰지 않는 경로, 변화 없음) |
| status_script (cache expired·none) | 5.0~5.7 | 4.0~4.7 | 0.70~0.93 | same | 0.40 | 0.32 | 0.78~0.80 | improved | (번들을 쓰지 않습니다. 이 CR의 변경이 아니라 측정 차이로 봅니다) |

cold (n=5/5, 61초 idle 뒤):
| 명령 | v0.4.0 wall s | 후보 wall s | wall 비 | 판정 | cpu 비 |
| --- | --- | --- | --- | --- | --- |
| agent-session review --clear | 7.188 [3.597-11.334] | 1.539 [0.933-2.547] | 0.21 [0.12-0.51] | improved | 0.61 [0.54-0.65] improved |
| project-item ls | 8.573 [2.633-11.839] | 2.479 [2.102-3.155] | 0.29 [0.20-0.94] | improved | 0.62 [0.59-0.72] improved |

tmux 호출 수와 다른 process 수는 모든 행에서 같습니다(3→3, 17→17 등). 전체 표는 도구의 `summary.md`에 있고 이 Result에는 위 행만 옮겼습니다.
- 같은 호스트의 별도 interleaved 측정(`vbench`, load 45~80): 번들 전 `project-item --help` warm 0.77초→번들 후 0.25초(첫 시제품), cold 1.28초→0.49초(중앙값).

### 검증
구현 commit 07a0959(merge 전)에서 바꾼 경로에 해당하는 README 표 명령을 모두 `-rf`로 실행했습니다.
- `integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py`: 130 passed
- `tools/project-item/tests`: 125 passed
- `tools/project-board/tests`: 161 passed
- `install/tests` (`-n 8`): 276 passed, 2 skipped (36분. 설치 시도마다 번들 build가 더해져 길어졌습니다)
- `tools/agent-session/tests` (`-n 8`): 810 passed
- 새 test `install/tests/test_bundle.py`: 9 passed(위 `install/tests`에 포함). 번들이 있는 release에서 모듈이 번들에서 오고 `__file__`·code 파일 이름이 source와 같은지, 번들에 없는 모듈은 원래 경로에서 오는지, source를 바꿔도 진입점이 번들의 code로 실행되는지, 다른 interpreter·없는 번들·`-O`에서 일반 import로 돌아가는지를 확인합니다.
- `tools/test_python_launcher.py`에 `bundle_boot.py`가 없는 tree도 `--help`를 실행하는 test를 더했습니다(위 130에 포함).

`origin/main`(9d746d8: BOARD-012의 `project_board/tmux_control.py`, 측정 도구, CR 문서, CHANGELOG)을 merge했습니다(CHANGELOG 충돌은 두 항목을 모두 두었습니다). merge가 입력을 바꾼 명령만 merge commit 5088d52에서 다시 실행했습니다. `tools/project-board/tests` 163 passed, 네 번째 명령 130 passed. merge는 `tools/project-item`·`tools/agent-session`·`install`·launcher를 바꾸지 않아 그 test의 근거는 재사용합니다. A/B는 merge commit에서 설치한 release로 쟀습니다.

### 이 Result에 아직 없는 것
A/A(같은 release 두 번)와 `--help` cold 표는 측정 중이라 끝나면 아래에 덧붙입니다. 이 제출은 그 결과를 기다리지 않습니다. A/A와 cold 측정은 merge 뒤 test를 실행한 시간과 겹쳐 부하가 올랐습니다.

### Leader 판단이 필요한 것 (범위 밖이라 하지 않았음)
- 떠 있는 hook·controller command(`python -m agent_session.internal ...`, `launch.sh`·`controller.sh`가 부름)는 번들을 쓰지 않습니다. 생성 script 내용을 바꿔야 해서(호환 규칙) 이 CR에서 하지 않았습니다. 필요하면 별도 CR입니다.
- 도구 모듈의 지연 import(`tempfile`→`shutil`·`random` 등)로 `.so` 6~7개를 줄이는 후속은 가능하며 효과는 `--help` 기준 warm 약 10~20%로 추정합니다(측정하지 않음).
- daemon은 필요하지 않다고 판단합니다. 번들 뒤 `--help` 0.12~0.19초 CPU는 이미 `python -S -c pass`(0.05초)의 2~4배이며, 남은 시간은 호스트 부하와 모듈 body 실행입니다.
- Rust 진입점이 필요하다는 결론은 나오지 않았습니다.
