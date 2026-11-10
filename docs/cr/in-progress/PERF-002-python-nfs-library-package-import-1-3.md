# PERF-002: 명령마다 Python 시동과 NFS의 표준 library·package import에 1~3초가 듭니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: PERF-001, SESSION-010, TMUX-003, RUST-001
- Base: 73d45379ada1a537b49b31c59ddc6c85c0914d2d 2026-11-10T08:38:15+09:00

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
