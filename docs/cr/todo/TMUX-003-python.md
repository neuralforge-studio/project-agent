# TMUX-003: 상태줄의 결정 개수 표시가 캐시가 유효해도 매초 Python을 띄웁니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: PERF-001, SESSION-010

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
