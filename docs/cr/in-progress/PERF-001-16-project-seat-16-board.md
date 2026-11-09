# PERF-001: 16 project × seat 16 규모에서 명령·Board·상태줄의 시간과 비용을 재고 원인을 나눕니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: RUST-001
- Mode: read-only
- Base: 2fd273983ce67607b63b3ae1c44be5b90d751c45 2026-11-10T08:01:10+09:00

## Symptom
사용자 평가(2026-11-10 대화): "정말 너무 느려서 쓸 수가 없는데... 속도가 느리다는 평가등은 다 한거야? project가 굉장히 여러개 일때도? 예를 들어 각 seat가 16개씩 project 16개?" 지금까지 어느 release도 속도를 재지 않았습니다. 0.2.0·0.3.0은 정확성 수정 release입니다. 이 workstation(등록 project 10개, slot 약 46개)에서도 Leader의 명령 하나가 수 초에서 수십 초 걸리고, project·seat 수가 늘면 얼마나 느려지는지 모릅니다.

## Evidence
- 실제 사용 시간(2026-11-09~10 Leader 대화 기록의 Bash 호출 시작·결과 시각 차이. Claude 도구 호출 대기가 조금 섞임):

  | 명령 | 횟수 | 중앙값 | 최대 |
  | --- | --- | --- | --- |
  | `agent-session review` | 40 | 7.3초 | 20.7초 |
  | `agent-session send` | 9 | 4.3초 | 24.8초 |
  | `agent-session start` | 7 | 12.0초 | 39.2초 |
  | `agent-session stop` | 38 | 29.5초 | 102.6초 |
  | `project-item check` | 1 | 8.5초 | |
  | `project-item accept` | 2 | 5.9초 | |

- Leader 측정(2026-11-10 07:56~08:00, 설치본 0.3.0, host load 45~65 / 64코어, `/primehome`은 NFS4):
  - `agent-session review --clear`: 전체 3.1초. tmux 호출 8번에 0.3초. cProfile 안에서는 1.1초이고 그중 import가 0.85초입니다. `.pyc` 68개를 NFS에서 여닫는 데(`open_code`·`__exit__`) 0.66초가 듭니다. 나머지는 bash launcher와 interpreter 시동입니다.
  - Board `model.liveness()` 한 번: 3.8~4.6초. tmux subprocess를 396번 띄웁니다(slot 약 46개, slot마다 8~9번). `get_current` 46번, `_session_target`의 `list-sessions` 138번, `project_pending_releases` 10번에 1.55초가 듭니다. Board pane마다 10초 주기(`tui.py` 256행)로 돕니다.
  - Board `model.snapshot()`: 처음 1.06초, 다음 0.24초. Board pane마다 2초 주기(`tui.py` 255행).
  - `integrations/tmux/tmux_decide_status.sh`: 캐시가 유효해도 0.44~0.95초(bash와 Python 시동). 상태줄 `#()`로 client마다 `status-interval`마다 돕니다. 이 workstation은 사용자 설정이 1초입니다.
  - 비례 추정(측정 아님): 16 project × seat 16(slot 272개)이면 liveness 한 번에 tmux 호출이 약 2,300번이고 20초를 넘습니다. 10초 주기를 따라가지 못합니다.
- 관련 CR: RUST-001(open)의 Disposition은 "배포 준비가 끝난 뒤, 느린 경로의 측정값과 전환 후보를 근거로 범위를 사용자 결정 항목으로 묻는다"입니다. 이 CR의 결과가 그 측정값입니다.

## Contract
- 이 CR은 측정과 원인 분해만 하는 read-only CR입니다. 제품 코드·문서·release를 바꾸지 않고 commit·push하지 않습니다.
- 측정은 사용자의 실제 tmux server(`/tmp/tmux-1028/default`)·등록 파일·state·캐시(`~/.cache/tmux-decide-status.json`)를 바꾸지 않습니다. 사용자 server에서는 읽기만 하는 호출(`model.snapshot`·`model.liveness`·status script)만 잽니다.
- 측정 대상 규모는 사용자가 예로 든 16 project × seat 16입니다. 비례를 보이도록 더 작은 규모도 함께 잽니다.

## Disposition
- 2026-11-10 Leader: 측정한다(Leader 판정). 사용할 수 없을 만큼 느리다는 사용자 보고와 재현 측정(위 Evidence)이 있는 결함의 원인 조사입니다. 수정 범위는 이 CR의 결과로 나눕니다. 알고리즘 결함(같은 tmux·파일 조회의 반복 등)은 Leader 판정으로 수정 CR을 엽니다. Rust 전환 범위는 RUST-001의 Disposition대로 이 결과를 근거로 사용자 결정 항목으로 묻습니다.
- 2026-11-10 Leader: open -> todo. Leader 판정: 측정(read-only). 사용자 보고와 재현 측정이 있는 속도 결함의 원인 조사

## Implementation
읽을 문서: [README 검증](../../../README.md#검증)(test tmux server 규칙), [동작 명세 5절 Python API](../../project-team/spec.md#프로젝트-consumer용-python-api), [project-team Worker 절](../../../skills/project-team/SKILL.md), [tmux 통합](../../../integrations/tmux/project-agent-main.conf).

이 CR은 read-only입니다. 측정 script와 산출물은 seat 밖 임시 디렉터리에 두고 Result에 경로를 적습니다. 저장소에 commit하지 않습니다.

1. 격리 환경을 만듭니다.
   - tmux server: [`tools/tests/tmux_test_server.py`](../../../tools/tests/tmux_test_server.py)의 `claim`으로 받고 끝나면 `release`합니다.
   - 등록 파일: 임시 `--config`를 씁니다.
   - 캐시: `XDG_CACHE_HOME`을 임시 디렉터리로 둡니다.
   - 규모 세 가지:
     - 4 project × seat 4
     - 8 × 8
     - 16 × 16 (slot 272개)
   - slot마다 Leader·Worker run이 살아 있는 상태를 만듭니다. 실제 provider는 띄우지 않습니다. test fixture([`agent_session_fake_provider.py`](../../../tools/agent-session/tests/fixtures/agent_session_fake_provider.py) 등)로 run 상태·tmux window·CLI process를 만듭니다. 방법은 Worker가 정하고 Result에 적습니다.
   - CR·결정 항목 디렉터리에는 project마다 실제와 비슷한 수의 파일을 둡니다(예: done 40개, open 몇 개).
2. 아래 연산마다 다음 값을 잽니다. 같은 측정을 3회 이상 반복해 중앙값을 씁니다. 측정 시각의 host load도 적습니다.
   - 벽시계 시간
   - tmux subprocess 수
   - 그 밖의 subprocess 수(git·ps 등)
   - interpreter 시동과 import 시간
   - 의도한 대기(sleep·poll·provider 응답)
   - **agent-session**:
     - `start`(Worker)
     - `send`
     - `review`·`review --clear`
     - `stop`
     - `restart`
     - `watch`
     - `pane-died` hook의 `finish_ended`
   - **project-item**:
     - `ls`
     - `new`
     - `move`
     - `accept`
     - `check`
   - **project-board**:
     - `model.snapshot`·`model.liveness`·context 갱신 한 번
     - `toggle`
     - `sync`
     - popup 열기
     - `project_board_visibility.sh`
   - **상태줄**: `tmux_decide_status.sh`. 캐시가 유효할 때와 만료될 때를 따로 잽니다.
3. Board를 켠 정상 상태의 지속 비용을 잽니다. 조건은 다음과 같습니다.
   - Board pane 1개와 4개
   - client 1개, `status-interval` 1초
   - 위 세 규모
   - 1분 동안의 CPU 시간과 subprocess 수
4. 실제 사용의 `start`·`stop`·`send`(Evidence 표)가 수 초~수십 초인 이유를 나눕니다. 다음 셋을 구분합니다.
   - 우리 코드의 비용
   - provider 대기(Claude의 준비·종료)
   - git(NFS 작업 트리)

   Fixture로 나눌 수 없는 provider 대기는 사용자 server의 run 기록(`<base>/agent/runs/*/`의 시각 파일)과 코드의 대기 지점을 근거로 추정하고, 추정이라고 적습니다.
5. 원인을 다음 넷으로 분류합니다. 항목마다 `file:line`과 근거 수치를 적습니다.
   - (a) 같은 조회를 slot·project마다 반복하는 알고리즘 결함
   - (b) interpreter 시동·NFS import
   - (c) 의도한 대기
   - (d) host 부하
6. 항목마다 다음을 적습니다.
   - 고치는 방법과 예상 효과
   - 그 방법이 관측 동작(CLI·JSON·파일 형식·hook entry)을 바꾸는지
   - Rust로 바꾸면 얼마나 줄어드는지 또는 줄지 않는지(예: tmux fork 횟수는 언어와 무관)

   마지막으로 연산별 목표 시간 제안을 적습니다.

의존: 없음.

위험 등급: 낮음(read-only, 격리 server).

## Verification
1. Result에 다음을 적습니다. 숫자는 Result 안에 바로 적고, 내용은 Leader가 같은 명령으로 다시 재현할 수 있어야 합니다.
   - 측정 script 경로와 실행 명령
   - 환경(규모·fixture·host load)
   - 연산 × 규모 표
   - 지속 비용
   - 원인 분류와 항목별 제안
2. Evidence의 Leader 측정 두 개(`review --clear` 3.1초, liveness 396번)를 같은 방법으로 다시 재서 측정 방법이 맞는지 보입니다.
3. 측정이 끝난 뒤 격리 tmux server와 그 process·socket이 남지 않았음을 확인합니다. 확인 기준은 README 검증의 test 자원 규칙입니다.
