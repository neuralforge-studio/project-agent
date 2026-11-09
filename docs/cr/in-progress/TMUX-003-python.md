# TMUX-003: 상태줄의 결정 개수 표시가 캐시가 유효해도 매초 Python을 띄웁니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: PERF-001, SESSION-010
- Base: 6a2c0f09a9a30b88c9ab4b9794442e5b84674a92 2026-11-10T08:17:51+09:00

## Symptom
상태줄의 결정 개수 표시(`integrations/tmux/tmux_decide_status.sh`)는 결정 디렉터리를 15초에 한 번만 읽습니다(`CACHE_TTL`). 그런데 캐시가 유효한 실행도 매번 bash launcher와 Python interpreter를 띄웁니다. tmux는 이 script를 client마다 `status-interval`마다 실행합니다. 이 workstation의 사용자 설정은 1초입니다. 사용자 평가(2026-11-10): "정말 너무 느려서 쓸 수가 없는데", "반복 조회 수정은 측정 결과 기다리지 말고 바로 시작해줘. 너무 느려."

## Evidence
- Leader 측정(2026-11-10, 설치본 0.3.0, host load 45~65 / 64코어, `/primehome` NFS4):
  - 캐시가 유효한 실행 한 번이 0.44~0.95초입니다.
  - bare interpreter 시동(`python3 -c pass`)만으로 0.13초입니다.
- `tmux_decide_status.py`의 `load_known`과 `refresh`: 캐시가 유효하면 디렉터리를 읽지 않고 마지막 값을 출력합니다. 즉 매초 드는 비용은 거의 interpreter·import 시동입니다.
- 상태줄 설정: `@project_agent_decide_status`가 `#(...tmux_decide_status.sh)`로 정의되어 있습니다(`integrations/tmux/project-agent-main.conf`).

## Contract
- 상태줄 출력 문구와 형식, 새 결정 알림(display-message·BEL)의 조건과 횟수는 바꾸지 않습니다. `CACHE_TTL` 동안 디렉터리를 한 번만 읽는 규칙과, lock을 못 얻거나 읽기가 실패하면 마지막 값을 출력하는 규칙도 그대로입니다.
- 캐시가 유효한 실행은 Python interpreter를 띄우지 않습니다. 디렉터리를 다시 읽을 때만 Python을 실행합니다.
- 상태줄은 `.py`를 직접 부르지 않고 `.sh`를 부릅니다([설치 계약 6.1](../../project-team/install-contract.md)).

## Disposition
- 2026-11-10 Leader: 고친다. 재현 측정이 있는 결함이고, 사용자 지시가 있습니다(2026-11-10 대화 원문: "반복 조회 수정은 측정 결과 기다리지 말고 바로 시작해줘. 너무 느려."). SESSION-010과 파일이 겹치지 않아 동시에 진행합니다.
- 2026-11-10 Leader: open -> todo. 사용자 지시로 즉시 수정
- 2026-11-10 Leader: 제출 3084323f095af6cd20bcb1bbd123f50c2d226d8f를 인수합니다. Leader review: 캐시가 유효한 실행은 .view만 읽고 Python을 띄우지 않습니다(20회 중앙값 288~396ms -> 19~21ms). CACHE_TTL은 .py에만 있고 view 첫 줄(캐시 mtime+TTL)로 전달되어 원본이 하나입니다. 디렉터리 읽기·lock·새 결정 알림의 조건은 만료 뒤 Python 실행에서만 일어나 수정 전과 같습니다. 출력 문구는 리터럴 비교 test로 고정했습니다. XDG_CACHE_HOME 빈 값 처리도 .py와 .sh가 같습니다. 검증은 README 표 integrations/tmux 행 세 명령과 docs 행(link 확인, distribution boundary)입니다. 지적: 작업 중 git stash를 썼습니다(전역 규칙상 사용자 요청 없이 stash 금지). 바로 pop했고 남은 것이 없어 결과에는 영향이 없습니다.

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), [설치 계약](../../project-team/install-contract.md)(6.1 interpreter 선택, 5.3 run-shell), [tmux 통합](../../../integrations/tmux/project-agent-main.conf), [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 수정 전 기준을 잽니다. 캐시가 유효한 실행과 만료된 실행의 시간을 각각 20회 중앙값으로 잽니다. 이때 `XDG_CACHE_HOME`은 임시 디렉터리로 둡니다.
2. 캐시가 유효하면 `tmux_decide_status.sh`가 Python 없이 마지막 출력을 냅니다. 바깥 process는 쓰지 않거나 최소로 씁니다.
   - 예: Python이 디렉터리를 읽을 때 상태줄 문구를 캐시 옆 파일에 함께 쓰고, `.sh`는 그 파일의 나이가 `CACHE_TTL` 이내이면 그대로 출력합니다.
   - TTL의 원본은 한 곳에 둡니다. `.sh`와 `.py`가 같은 값을 따로 들고 있지 않게 합니다.
   - 캐시 파일 위치·형식이 문서(설치 계약·README·spec)에 적혀 있으면 함께 고칩니다.
3. 만료·lock 경합·읽기 실패의 동작은 지금 `.py` 규칙을 그대로 따릅니다. 첫 실행의 baseline, 새 결정 알림, 마지막 값 출력이 모두 여기에 들어갑니다.
4. test를 추가합니다.
   - 캐시가 유효하면 Python을 실행하지 않음. 예: 실행 가능하지 않은 `PROJECT_AGENT_PYTHON`으로도 출력이 나와야 합니다.
   - 만료되면 다시 읽음.
   - 출력 문구가 수정 전과 같음.

의존: 없음.

위험 등급: 낮음.

## Verification
1. 수정 전후 시간 표(1단계와 같은 방법)를 Result에 적습니다.
2. README 검증 표 `integrations/tmux/**` 행:
   - 네 번째 명령
   - `tools/project-board/tests/test_tmux_control.py`
   - `install/tests`(`-n 8`)
   - 다른 경로를 바꾸면 그 행의 명령도 실행합니다.
3. 제출 전에 `origin/main`이 움직여 위 명령의 입력을 바꿨으면 merge하고 merge commit에서 다시 실행합니다.

## Result
- 제출 commit: 3084323f095af6cd20bcb1bbd123f50c2d226d8f

변경:
- `integrations/tmux/tmux_decide_status.py`: 캐시가 유효한 실행이 끝에서 상태줄 문구를 `tmux-decide-status.view`에 씁니다. 첫 줄은 캐시가 유효한 마지막 epoch 초(`floor(캐시 mtime + CACHE_TTL)`), 나머지는 출력 문구입니다. 그래서 `CACHE_TTL`은 `.py`에만 있습니다. 캐시를 못 읽거나(registry 오류) 만료된 채 lock을 못 얻은 실행은 쓰지 않습니다. 읽기 실패로 캐시 나이를 새로 하면 view도 함께 새로 됩니다. 디렉터리 읽기·lock·알림·출력 문구는 그대로입니다(`render`로 분리만 했습니다).
- `integrations/tmux/tmux_decide_status.sh`: 맨 앞에서 view를 읽습니다. 첫 줄이 숫자이고 `date +%s`가 그 값 이내이면 문구를 그대로 출력하고 끝냅니다(launcher `source`·Python 없음, 바깥 process는 `date` 하나). view가 없거나 깨졌거나 만료되면 기존대로 launcher로 `.py`를 실행합니다. 경로는 `.py`와 같은 규칙(`XDG_CACHE_HOME` 또는 `~/.cache`)이고, test가 두 파일이 같은 파일을 가리키는지 확인합니다.
- `docs/project-team/install-contract.md` 5.1절: 캐시 파일 행에 `tmux-decide-status.view`와 읽는 쪽을 추가하고 옛 줄 번호 근거를 함수 이름으로 바꿨습니다. README·설정 파일은 위치·형식을 적고 있지 않아 바꾸지 않았습니다.

수정 전후 시간(`XDG_CACHE_HOME`은 임시 디렉터리, `tmux_decide_status.sh` 실행 20회 중앙값, base 6a2c0f0는 `git archive`로 푼 사본). Host load가 45~96으로 흔들려 두 번씩 측정했습니다:

| | 수정 전 | 수정 후 |
| --- | --- | --- |
| 캐시 유효 | 396 ms / 288 ms (처음 측정 160 ms / 340 ms) | 19 ms / 21 ms (처음 측정 22~24 ms) |
| 캐시 만료 | 650 ms / 1466 ms (처음 측정 361 ms / 571 ms) | 426 ms / 530 ms |

만료된 실행은 Python을 실행하므로 줄지 않습니다(host load 변동 폭 안). 줄이려는 대상은 캐시가 유효한 매초 실행이며, 그 시간은 `date` 한 번 수준(약 20 ms)이 되었습니다.

Test(`integrations/tmux/test_tmux_decide_status.py`, 9개 추가): 
- 캐시가 유효하면 실행할 수 없는 `PROJECT_AGENT_PYTHON`(`/nonexistent/python3`)으로도 `결정 2`가 나오고 종료 코드 0·stderr 비어 있음. 결정이 0개여도 같음.
- 만료되면 다시 읽음: 결정 하나를 닫은 뒤 유효한 동안은 `결정 2`, view를 만료시키면 실행할 수 없는 interpreter로는 종료 코드 5, 실제 interpreter로는 `결정 1`.
- 출력 문구가 수정 전과 같음: 리터럴 `#[fg=white,bg=red,bold] 결정 2 #[default]`와 비교(첫 실행(Python)과 view 경로가 같은 문구).
- view 첫 줄 = `floor(캐시 mtime + status.CACHE_TTL)`. 비었거나 숫자가 아닌 view는 무시하고 `.py`를 실행. 읽을 수 없는 registry는 view를 쓰지 않음. 읽기 실패가 캐시 나이를 새로 하면 view도 새로 됨.
- 기존 15개(첫 실행 baseline, 새 결정 알림, lock 경합, 읽기 실패)는 수정 없이 통과합니다. 새 test는 `TMUX_TMPDIR`을 빈 임시 디렉터리로 두어 실제 tmux server에 알림이 가지 않게 했습니다.

검증(제출 commit에서, `origin/main` 무변동: 제출 전 fetch 뒤 `HEAD..origin/main` 없음):
1. `python -m pytest -q integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py`: 112 passed
2. `python -m pytest -q tools/project-board/tests/test_tmux_control.py`: 21 passed
3. `python -m pytest -q -n 8 install/tests`: 267 passed, 2 skipped
- 바꾼 경로는 `integrations/tmux/**`와 `docs/project-team/install-contract.md`입니다. 문서 행의 명령(`tools/test_distribution_boundary.py`)은 1번에 들어 있습니다. 모든 검증은 `python3`=`/primehome/tools/Inhouse/Python3/latest/bin/python3`로 실행했습니다.
- 작업 중 측정 비교용으로 `git stash`를 한 번 썼다가 곧바로 pop했습니다(stash 남은 것 없음).
