# PERF-003: 짧은 명령의 시간 대부분이 Python 시동과 NFS import이며 0.3~3초로 흔들립니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: PERF-001, PERF-002, RUST-001, D-20261110-02
- Base: 0eb2e262e2a939ae4497cd541a1d456db4e36108 2026-11-10T13:05:25+09:00

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
