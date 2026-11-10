# PERF-001: 16 project × seat 16 규모에서 명령·Board·상태줄의 시간과 비용을 재고 원인을 나눕니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: RUST-001
- Mode: write
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
- (2026-11-10 변경) 이 CR은 측정 도구를 저장소에 commit하는 write CR입니다. 제품 코드(`tools/*/` 패키지·`integrations/`·`install/`)와 release는 바꾸지 않습니다.
- 측정 도구는 두 실행본(기준과 후보)을 같은 host·같은 격리 환경에서 번갈아 실행해 비교합니다. 기준은 v0.3.0입니다. 수정 CR과 release는 이 도구의 결과로 개선량을 숫자로 보입니다(사용자 2026-11-10: "측정은 필요해. 개선이 얼마나 된것인지 명확한 비교대상. 정량적 평가가 되어야 하니까.").
- 측정은 사용자의 실제 tmux server(`/tmp/tmux-1028/default`)·등록 파일·state·캐시(`~/.cache/tmux-decide-status.json`)를 바꾸지 않습니다. 사용자 server에서는 읽기만 하는 호출(`model.snapshot`·`model.liveness`·status script)만 잽니다.
- 측정 대상 규모는 사용자가 예로 든 16 project × seat 16입니다. 비례를 보이도록 더 작은 규모도 함께 잽니다.

## Disposition
- 2026-11-10 Leader: 측정한다(Leader 판정). 사용할 수 없을 만큼 느리다는 사용자 보고와 재현 측정(위 Evidence)이 있는 결함의 원인 조사입니다. 수정 범위는 이 CR의 결과로 나눕니다. 알고리즘 결함(같은 tmux·파일 조회의 반복 등)은 Leader 판정으로 수정 CR을 엽니다. Rust 전환 범위는 RUST-001의 Disposition대로 이 결과를 근거로 사용자 결정 항목으로 묻습니다.
- 2026-11-10 Leader: open -> todo. Leader 판정: 측정(read-only). 사용자 보고와 재현 측정이 있는 속도 결함의 원인 조사
- 2026-11-10 Leader: Mode를 read-only에서 write로 바꿉니다. 사용자 지시(2026-11-10 대화 원문: "측정은 필요해. 개선이 얼마나 된것인지 명확한 비교대상. 정량적 평가가 되어야 하니까.")로 측정 도구를 저장소에 남겨 v0.3.0을 기준으로 A/B 비교합니다. Base(2fd2739)는 그대로이고, Worker는 start가 write CR에 하는 것과 같이 `git switch --no-overwrite-ignore -c cr/PERF-001 2fd273983ce67607b63b3ae1c44be5b90d751c45`로 branch를 만듭니다.

- 2026-11-10 Leader: 제출 1(0a77448, 측정 도구만)을 검토했고 수정을 요청합니다. 계측(`tools/tests/perf/site/sitecustomize.py`)이 측정 대상 interpreter의 site 처리와 `PYTHONPATH`에 기대고 있습니다. 그래서 PERF-002처럼 site 처리를 없앤 후보에서는 두 문제가 생깁니다. tmux·subprocess 수가 0으로 기록되고, 가짜 provider 치환이 빠집니다. 또 시간을 재는 실행에 계측 비용이 들어갑니다. 요구 사항은 넷입니다. (a) 시간을 재는 실행에는 측정 대상 process 안의 계측이 없어야 합니다. (b) 호출 수는 process 경계에서 셉니다. (c) 가짜 provider는 process 경계에서 넣습니다. (d) `-I -S` 후보로 같은 숫자가 나오는지 확인하는 test를 둡니다. README 검증 code block의 여섯 번째 명령은 release의 다섯 명령 규칙(release.md 5절)과 어긋나므로 표의 행에만 둡니다. 위치, ABAB 교대, warm/cold 분리, 격리, 산출물 형식은 인정합니다.
- 2026-11-10 Leader: 제출 76ef704108fb1b14ae66427ece49cd6c1d682ae9를 인수합니다. Leader review(제출 2, 도구 부분 인수·선통합): 계측이 process 경계로 옮겨졌습니다. 시간을 재는 pass에는 shim이 없고 counting pass에서만 PATH shim으로 셉니다. 가짜 provider는 PATH 앞의 claude 실행 파일이라 제품의 실제 provider 코드와 hook·MCP client 비용이 측정에 들어갑니다. -I -S 후보 test가 있고, README code block은 release 다섯 명령으로 돌아왔습니다. 측정하지 못하는 것(실제 Claude CLI 시동·모델 turn)을 명시한 점도 인정합니다. CR은 in-progress로 둡니다. 기준선·A/B 표·원인 분류 제출을 기다립니다.
- 2026-11-10 Leader: RUST-001은 D-20261110-02 A로 닫혔습니다(waived). 6단계의 "Rust로 바꾸면 얼마나 줄어드는지" 추정은 그대로 적습니다. 이 값은 남은 시동 비용을 다루는 PERF-003의 판단 근거가 됩니다.
- 2026-11-10 Leader: 제출 3(265ef84, 도구 수정)을 검토했습니다. 명령별 자식 CPU 시간, 중앙값 95% bootstrap 구간과 ratio 구간 기준 판정(구간이 1을 벗어날 때만 improved/worse), 반복 9회, lifecycle 실패 내성을 인정합니다. 남은 것: merge(265ef84)로 들어온 BOARD-012가 바꾼 `tools/project-board`는 `tools/tests/perf` 통합 test의 입력(측정하는 제품 tree)입니다. README 표 `tools/tests/perf/**` 행의 명령 전체를 merge commit에서 다시 실행해야 하므로 통합은 그 결과를 받은 뒤에 합니다. 진행 중인 측정의 부하와 겹치지 않도록 현재 측정 단계 뒤에 실행해도 됩니다.
- 2026-11-10 Leader: 제출 55a6313a25b796ee9145e203902c221c2cd7c135를 인수합니다. Leader review(제출 3·4, 도구 부분 인수·선통합): 자식 CPU 시간, 중앙값 95% bootstrap 구간과 ratio 구간 판정, 반복 9회, lifecycle 실패 내성, 가짜 claude의 hook 시간 기록을 인정합니다. README 표 tools/tests/perf/** 행 전체(통합 test 포함 8 passed, 배포 경계 9 passed, link 확인)를 BOARD-012가 들어간 tree에서 다시 실행했습니다. 이후 main은 CR 문서만 움직였습니다. CR은 in-progress로 둡니다. v0.3.0과 v0.4.0, PERF-002 후보의 측정표와 원인 분류 제출을 기다립니다.
- 2026-11-11 Leader: 제출 7df707f6904a4d9dd037eed1df51a81dbe22634a를 인수합니다. 최종 제출 7df707f 검토. 도구 수정(start timeout 180초와 count pass 재시도, 실패 뒤 seat·CR 복구, unit 실패 내성, SIGTERM 처리, steady의 Board ready 대기, -S launcher 후보)과 측정 결과 A~D, 원인 분류(a~d)·연산별 목표 시간을 읽었습니다. 제출 뒤 main에 들어온 BOARD-013이 통합 test가 실행하는 project-board를 바꿨으므로 Leader가 merge commit(8055c85와 tree가 같은 395e3f9 clone)에서 tools/tests/perf를 다시 실행했습니다: 8 passed(780초). 결과 D의 board_popup·sidebar_ready 증가(n=2)는 BOARD-014가 n=5로 재현되지 않음을 확인했습니다. (c)의 MCP close 1초 대기와 stop의 observe마다 세션은 SESSION-012(v0.5.0)가 이미 고쳤습니다.
## Implementation
읽을 문서: [README 검증](../../../README.md#검증)(test tmux server 규칙), [동작 명세 5절 Python API](../../project-team/spec.md#프로젝트-consumer용-python-api), [project-team Worker 절](../../../skills/project-team/SKILL.md), [tmux 통합](../../../integrations/tmux/project-agent-main.conf).

측정 도구는 저장소에 commit합니다(아래 7단계). 측정 산출물(JSON·표)은 seat 밖 임시 디렉터리에 두고 Result에 숫자와 경로를 적습니다.

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

7. (2026-11-10 추가) 측정 도구를 저장소에 둡니다.
   - 위치: 배포하지 않는 개발 도구로 둡니다. 위치는 [`tools/test_distribution_boundary.py`](../../../tools/test_distribution_boundary.py)의 규칙을 따르고, README의 디렉터리 지도와 검증 절에 한 줄로 적습니다.
   - 입력:
     - 비교할 실행본 둘(설치 release 디렉터리 또는 checkout. 예: `git archive v0.3.0`으로 푼 사본과 현재 checkout)
     - 규모(project 수 × seat 수)
     - 반복 횟수
   - 실행 순서: 두 실행본을 같은 격리 환경에서 번갈아 실행합니다(ABAB). 시간대마다 달라지는 host 부하가 한쪽에만 실리지 않게 하기 위해서입니다.
   - 실행 간격 두 가지:
     - 연속 실행(warm)
     - NFS attribute cache가 만료된 실행(cold). 이 workstation의 `/primehome` mount는 `acregmin=60`이라, 실제 사용처럼 명령 사이가 60초를 넘으면 매번 파일 속성을 다시 확인합니다. 방법과 간격은 Worker가 정하고 근거를 적습니다.
   - 출력: 연산 × 규모 × 실행본마다 다음 값을 JSON과 Markdown 표로 냅니다.
     - 중앙값과 p90
     - tmux process 수
     - 그 밖의 subprocess 수
     - 두 실행본의 비율
     - 측정 중 host load
   - test: 측정 도구 자신의 test(작은 규모 1회 실행과 출력 형식)를 두고 README 검증 표에 그 행을 더합니다.
   - 기준선: 이 도구로 v0.3.0과 Base(2fd2739)를 같은 실행본으로 비교한 결과(A/A, 차이가 오차 범위임을 보임)와 v0.3.0의 연산 × 규모 표를 Result에 적습니다. 이 표가 이후 모든 개선의 비교 대상입니다.
   - 단계 1~6의 측정은 이 도구로 합니다.

의존: 없음.

위험 등급: 낮음(제품 코드 변경 없음, 격리 server).

## Verification
1. Result에 다음을 적습니다. 숫자는 Result 안에 바로 적고, 내용은 Leader가 같은 명령으로 다시 재현할 수 있어야 합니다.
   - 측정 script 경로와 실행 명령
   - 환경(규모·fixture·host load)
   - 연산 × 규모 표
   - 지속 비용
   - 원인 분류와 항목별 제안
   - 측정 도구의 commit과 v0.3.0 기준선 표, A/A 비교 결과(7단계)
2. Evidence의 Leader 측정 두 개(`review --clear` 3.1초, liveness 396번)를 같은 방법으로 다시 재서 측정 방법이 맞는지 보입니다.
3. 측정이 끝난 뒤 격리 tmux server와 그 process·socket이 남지 않았음을 확인합니다. 확인 기준은 README 검증의 test 자원 규칙입니다.
4. (2026-11-10 추가) README 검증 표에서 바꾼 경로의 행을 모두 실행합니다. 측정 도구 자신의 test, 고친 문서의 상대 link 검사, `tools/test_distribution_boundary.py`가 포함됩니다. 제출 전에 `origin/main`이 움직여 그 입력을 바꿨으면 merge하고 merge commit에서 다시 실행합니다.

## Result

### 제출 1: 측정 도구 (기준선·원인 분류는 이어지는 제출)
- 제출 commit: 0a77448c76f1ca32667aed9cd67276613f17fb87
- 내용: `tools/tests/perf/`(release 제외 경로, `install/project_agent_install/release.py`의 `tests` 규칙) 아래에 두 실행본 A/B 도구를 추가했습니다. README 디렉터리 지도·검증 표에 행을 더했습니다. 제품 코드(`tools/*/` 패키지·`integrations/`·`install/`)는 바꾸지 않았습니다.
  - 사용: `python tools/tests/perf/perf_bench.py run --exe BASE=PATH --exe CANDIDATE=PATH --workdir DIR --out DIR [--scales 4x4,8x8,16x16] [--reps 3] [--cold-reps 3 --cold-seconds 61] [--steady-seconds 60]`, 보고서만 다시 만들 때 `... report --out DIR`. 자세한 설명은 `perf_bench.py` 머리말입니다.
  - 실행본은 `git archive <tag> | tar -x -C DIR`로 푼 사본, checkout, 설치 release 디렉터리입니다(`tools/`·`integrations/tmux`·`tools/agent-session/tests/fixtures`가 있어야 합니다).
  - 두 실행본을 단위(연산)마다 A B A B로 번갈아 실행합니다. warm(연속)과 cold(`--cold-seconds` 유휴 뒤, `/primehome`의 `acregmin=60` 때문에 기본 61초)를 나눕니다.
  - 격리: 규모마다 자기 tmux server(`tmux_test_server.claim`·`release`), 등록 파일, 캐시(`XDG_CACHE_HOME`), git remote·base·seat clone을 만듭니다. 모든 명령의 환경에 `TMUX`·`AGENT_SESSION_SOCKET`·`HOME`을 격리 값으로 항상 지정해 사용자 server에 닿지 않습니다.
  - 산출물: `results.jsonl`(명령 하나당 한 줄), `meta.json`, `summary.json`, `summary.md`(중앙값·p90·tmux 수·그 밖의 subprocess 수·ratio·host load).
- 검증(이 commit에서): `python -m pytest -q tools/tests/perf` 5 passed(작은 규모 A/A 1회 실행과 출력 형식, 서버·socket 잔존 없음 확인 포함, host load 약 100에서 180초), `python -m pytest -q tools/test_distribution_boundary.py` 9 passed, README 상대 link 검사 이상 없음.
- 아직 없는 것: v0.3.0 기준선 표, A/A 비교, 지속 비용, 원인 분류(5·6단계), Verification 2. 측정 중이며 다음 제출에 넣습니다.

### 제출 2: 계측을 process 경계로 옮긴 도구 (제출 1에 대한 Leader 피드백 반영)
- 제출 commit: 76ef704108fb1b14ae66427ece49cd6c1d682ae9
- 바뀐 것:
  - (a)(b) 측정 대상 interpreter 안의 계측을 없앴습니다(`sitecustomize`·`PYTHONPATH`·`PROJECT_AGENT_PYTHON` 제거). 호출 수는 `PATH` 앞의 `tmux`·`git`·`ps` shim(호출 기록만 남기고 진짜 프로그램을 exec)이 세고, shim은 별도 counting pass에서만 켭니다. 시간을 재는 warm·cold pass에는 shim이 없습니다. counting pass의 시간은 보고하지 않습니다(row의 `mode`가 `count`). 호출 수는 규모·실행본마다 1회입니다.
  - (c) 가짜 provider를 process 경계에서 넣습니다. `tools/tests/perf/fake_claude.py`를 `claude` 이름으로 `PATH` 앞에 두고 제품의 실제 Claude provider 코드가 그것을 실행합니다. `claude --version`, `claude agents --json`, `claude mcp serve`(MCP: initialize·tools/list·ListAgents·SendMessage), 인터랙티브 CLI(settings의 SessionStart·Stop hook 실행, SIGTERM에 SessionEnd hook 후 143 종료)를 흉내 냅니다. 그래서 provider 코드(MCPClient 시동·종료 대기, ListAgents 조회)와 제품 hook의 비용이 측정에 들어갑니다. `mcp serve`는 실제처럼 stdin이 닫혀도 계속 살아 있어 MCPClient.close의 1초 대기가 그대로 재현됩니다.
  - 경계에서 넣을 수 없는 것(그 연산이 재지 않는 것): 실제 Claude CLI의 시동 시간(node, 수 초), 모델 turn, 네트워크. 가짜 `claude`는 python(`-I -S`)이라 시동이 짧습니다. 그래서 `start`·`restart`·`stop`·`send` 숫자는 "제품 코드 + 제품이 띄우는 hook·MCP client + 가짜 provider"의 비용이고 실제 사용 시간보다 짧습니다. 실제 provider의 시동·종료 대기는 `provider_probe.py`(읽기 전용 실측)와 사용자 server의 run 기록으로 따로 추정합니다.
  - tmux 안에서 PATH는 pane을 만든 tmux client의 PATH로 정해집니다(이 workstation에서 server 환경이나 `set-environment`로는 바뀌지 않음을 확인). 그래서 shim이 shim PATH로 진짜 프로그램을 exec해 shim PATH가 pane까지 전해집니다. server가 대신 일으키는 process(Worker 등록, hook)의 호출 수는 `pane_spawns`로 따로 세어 명령의 호출 수에 더합니다. counting pass에서는 fake CLI의 hook이 끝난 뒤(`busy-*` 파일) 다음 명령을 셉니다. 늦은 hook이 다음 명령의 tmux 읽기와 겹치면 읽기를 반복해 호출 수가 달라지기 때문입니다.
  - `pane-died` hook의 `finish_ended`는 hook을 그대로 두고 CLI를 죽인 뒤 `finish-result.json`이 생길 때까지의 시간으로 잽니다(제품이 만든 hook 명령 그대로).
  - 상태줄: main의 view 파일(`tmux-decide-status.view`) 변경에 맞춰 cache와 view를 함께 지우고 만료시킵니다.
  - (d) `test_small_run_with_an_isolated_candidate_...`: launcher가 `-I -S`로 Python을 시작하는 실행본(agent-session·project-item)을 후보로 A/B를 돌려, 시간 측정 row에는 shim이 없고 후보의 tmux 호출 수가 기준과 같게(0이 아니게) 나옴을 확인합니다. 서버·socket·환경 디렉터리가 남지 않음도 확인합니다.
  - README: code block의 여섯 번째 명령을 뺐습니다. `tools/tests/perf/**` 표 행에만 test 명령과 "release 검증 아님·host 부하에 따라 수 분~수십 분"을 적었습니다.
- origin/main(SESSION-010 통합, 8d6365c까지)을 merge(c7e9052)한 뒤 그 merge 위에서 검증했습니다. 이 merge가 상태줄 view 파일과 tmux 읽기 횟수를 바꿔 도구 test가 두 번 실패했고(view 파일을 지우지 않아 cache가 안 생김, 후속 hook과 겹친 읽기 반복으로 호출 수 28 대 15), 위 두 가지를 고쳤습니다.
- 검증(76ef704에서): `python -m pytest -q tools/tests/perf` 6 passed(host load 80~180에서 1695초), `python -m pytest -q tools/test_distribution_boundary.py` 9 passed, README 상대 link 검사 이상 없음. 제품 코드는 바꾸지 않았습니다.
- 다음 제출: v0.3.0 대 Base(2fd2739) 기준선(A/A)과 연산 × 규모 표, 지속 비용, Verification 2, 원인 분류. 이전에 scratch harness로 잰 값은 계측 방식이 달라 쓰지 않고 이 도구로 다시 잽니다.

### 측정 1·2: 기준선 A/A와 v0.3.0 대 v0.4.0 (측정 중간 보고, 제출 commit 아님)
도구는 제출 2의 `tools/tests/perf`(main d417943)입니다. 측정 결과는 scratchpad의 `out/<이름>/{results.jsonl,summary.json,summary.md}`에 있고, 아래 표는 `summary.json`의 시간 중앙값(경과 초)과 counting pass의 tmux·그 밖의 process 수입니다. `ratio`는 후보/기준(1보다 작으면 후보가 빠름)입니다.

**실행과 환경.** host srv04, tmux 3.8, Python 3.12.13, 작업 디렉터리는 `/primehome/swain`의 NFS4(`acregmin=60`)입니다. 규모마다 격리 환경(project N × seat S, slot마다 Leader·Worker run이 살아 있음, project 0에 run이 없는 seat 1개 추가, project마다 done CR 40·open 2·in-progress S, 결정 12)에서 두 실행본을 A B A B로 번갈아 실행했습니다. 실행본: `v0.3.0` = `git archive v0.3.0`, `base` = `git archive 2fd2739`, `main` = `git archive d417943`(v0.4.0 tag ce52466와 제품 코드가 같고 VERSION과 test 한 줄만 다름). 명령: `cd tools/tests/perf && python3 perf_bench.py run --exe v0.3.0=DIR --exe main=DIR --workdir W --out O --scales 4x4 --reps 3 --cold-reps 0 --steady-seconds 60`. 8x8·16x16은 `--reps 2`입니다.
- **줄인 것(시간 때문):** 규모를 따로 돌렸고 4×4는 3회, 8×8·16×16은 2회로 줄였습니다. cold는 16×16에서만 2회 잽니다. 호출 수는 규모·실행본마다 1회(counting pass)라 줄인 영향이 없습니다. 이 host는 다른 사용자의 부하(load 30~180)가 시간대마다 크게 달라 시간 값의 오차가 큽니다(아래 A/A).
- 환경 격리: 모든 명령에 `TMUX`·`AGENT_SESSION_SOCKET`·`HOME`·`XDG_CACHE_HOME`을 격리 값으로 지정했습니다. 사용자 server·등록 파일·cache는 읽지도 쓰지도 않았습니다(Verification 3은 마지막에 확인합니다).

**측정 1: A/A (v0.3.0 대 Base 2fd2739, 4×4, 3회).** 두 실행본의 제품 코드는 같습니다. 호출 수는 같고(tmux 차이는 start 589 대 571, restart 648 대 640처럼 3% 이내이며, 늦은 hook과 겹친 읽기 반복 때문입니다), 시간 중앙값의 ratio는 41개 연산에서 0.55~2.35(기하평균 0.98, 중앙값 0.95)로 흩어졌습니다. 0.7~1.43 안에 30개, 0.5~2 안에 39개입니다(host load 55~95). 결론: 이 host에서 3회 중앙값 시간은 ±40% 안의 차이를 구분하지 못합니다. 호출 수는 결정적이라 알고리즘 변경의 개선량은 호출 수로 보이고, 시간 개선은 호출 수 감소와 함께 일관될 때 믿을 수 있습니다.

| scale | operation | v0.3.0 s | base s | ratio | tmux v0.3.0->base | other v0.3.0->base |
|---|---|---|---|---|---|---|
| 4x4 | agent_finish_ended | 3.49 | 7.59 | 2.17 | 62->61 | 3->3 |
| 4x4 | agent_restart_worker | 37.94 | 26.75 | 0.71 | 648->640 | 0->0 |
| 4x4 | agent_review | 3.55 | 2.49 | 0.70 | 24->24 | 0->0 |
| 4x4 | agent_review_clear | 3.25 | 2.38 | 0.73 | 8->8 | 0->0 |
| 4x4 | agent_review_clear_after | 2.00 | 1.45 | 0.73 | 8->8 | 0->0 |
| 4x4 | agent_send_to_leader | 5.13 | 3.95 | 0.77 | 48->48 | 0->0 |
| 4x4 | agent_send_to_worker | 5.01 | 4.10 | 0.82 | 48->48 | 0->0 |
| 4x4 | agent_start_worker | 22.39 | 19.07 | 0.85 | 589->571 | 18->18 |
| 4x4 | agent_stop_ended_worker | 5.42 | 6.57 | 1.21 | 66->66 | 3->3 |
| 4x4 | agent_stop_worker | 17.96 | 13.07 | 0.73 | 145->143 | 3->3 |
| 4x4 | agent_watch | 6.33 | 5.09 | 0.80 | 52->52 | 0->0 |
| 4x4 | bin_agent_session_help | 0.96 | 2.26 | 2.35 | 0->0 | 0->0 |
| 4x4 | bin_project_item_help | 1.76 | 2.16 | 1.23 | 0->0 | 0->0 |
| 4x4 | board_context | 0.01 | 0.03 | 1.93 | 1->1 | 0->0 |
| 4x4 | board_import | 1.20 | 0.78 | 0.64 | 0->0 | 0->0 |
| 4x4 | board_liveness | 8.35 | 8.06 | 0.97 | 308->308 | 0->0 |
| 4x4 | board_popup_ready | 5.68 | 7.59 | 1.34 | 0->0 | 0->0 |
| 4x4 | board_sidebar_ready | 8.54 | 9.03 | 1.06 | 0->0 | 0->0 |
| 4x4 | board_snapshot_first | 0.99 | 0.64 | 0.65 | 0->0 | 0->0 |
| 4x4 | board_snapshot_warm | 0.13 | 0.13 | 1.02 | 0->0 | 0->0 |
| 4x4 | board_sync_nochange | 4.10 | 4.57 | 1.11 | 100->100 | 6->6 |
| 4x4 | board_sync_off | 3.50 | 4.33 | 1.24 | 70->70 | 2->2 |
| 4x4 | board_toggle_off | 3.45 | 4.00 | 1.16 | 116->123 | 6->8 |
| 4x4 | board_toggle_on | 4.83 | 4.58 | 0.95 | 106->105 | 3->4 |
| 4x4 | board_visibility_sh | 0.08 | 0.12 | 1.39 | 3->4 | 0->0 |
| 4x4 | board_visibility_sh_off | 0.08 | 0.06 | 0.80 | 2->2 | 0->0 |
| 4x4 | board_visible | 0.03 | 0.05 | 1.64 | 2->2 | 0->0 |
| 4x4 | import_agent_session | 2.13 | 2.14 | 1.00 | 0->0 | 0->0 |
| 4x4 | import_project_board | 10.52 | 9.93 | 0.94 | 0->0 | 0->0 |
| 4x4 | import_project_item | 2.22 | 2.99 | 1.34 | 0->0 | 0->0 |
| 4x4 | project_item_accept | 2.72 | 1.50 | 0.55 | 8->8 | 0->0 |
| 4x4 | project_item_check | 3.18 | 4.12 | 1.29 | 0->0 | 6->6 |
| 4x4 | project_item_ls | 3.71 | 2.41 | 0.65 | 32->32 | 0->0 |
| 4x4 | project_item_move_done | 9.58 | 6.09 | 0.64 | 58->58 | 8->8 |
| 4x4 | project_item_move_done_waived | 2.43 | 3.69 | 1.52 | 56->56 | 5->5 |
| 4x4 | project_item_move_todo | 2.49 | 2.27 | 0.91 | 8->8 | 2->2 |
| 4x4 | project_item_new | 1.67 | 1.25 | 0.75 | 0->0 | 2->2 |
| 4x4 | startup_python | 0.17 | 0.17 | 0.97 | 0->0 | 0->0 |
| 4x4 | status_cache_expired | 2.66 | 2.55 | 0.96 | 0->0 | 0->0 |
| 4x4 | status_cache_valid | 0.85 | 0.55 | 0.64 | 0->0 | 0->0 |
| 4x4 | status_no_cache | 2.34 | 2.02 | 0.86 | 0->0 | 0->0 |

**측정 2: v0.3.0 대 v0.4.0(main d417943), 4×4, 3회.**

| scale | operation | v0.3.0 s | main s | ratio | tmux v0.3.0->main | other v0.3.0->main |
|---|---|---|---|---|---|---|
| 4x4 | agent_finish_ended | 2.63 | 1.82 | 0.69 | 61->18 | 3->3 |
| 4x4 | agent_restart_worker | 13.80 | 10.71 | 0.78 | 661->177 | 0->0 |
| 4x4 | agent_review | 0.62 | 0.48 | 0.77 | 24->8 | 0->0 |
| 4x4 | agent_review_clear | 0.46 | 0.71 | 1.55 | 8->3 | 0->0 |
| 4x4 | agent_review_clear_after | 0.60 | 0.43 | 0.72 | 8->3 | 0->0 |
| 4x4 | agent_send_to_leader | 2.18 | 1.86 | 0.85 | 48->16 | 0->0 |
| 4x4 | agent_send_to_worker | 2.18 | 1.88 | 0.86 | 48->15 | 0->0 |
| 4x4 | agent_start_worker | 8.14 | 4.80 | 0.59 | 568->177 | 18->18 |
| 4x4 | agent_stop_ended_worker | 2.77 | 1.86 | 0.67 | 66->17 | 3->3 |
| 4x4 | agent_stop_worker | 6.66 | 6.08 | 0.91 | 142->43 | 3->3 |
| 4x4 | agent_watch | 1.68 | 1.54 | 0.92 | 52->17 | 0->0 |
| 4x4 | bin_agent_session_help | 0.40 | 0.23 | 0.58 | 0->0 | 0->0 |
| 4x4 | bin_project_item_help | 0.44 | 0.72 | 1.64 | 0->0 | 0->0 |
| 4x4 | board_context | 0.01 | 0.01 | 1.75 | 1->1 | 0->0 |
| 4x4 | board_import | 0.19 | 0.26 | 1.32 | 0->0 | 0->0 |
| 4x4 | board_liveness | 5.30 | 0.20 | 0.04 | 308->3 | 0->0 |
| 4x4 | board_popup_ready | 2.00 | 2.39 | 1.19 | 0->0 | 0->0 |
| 4x4 | board_sidebar_ready | 2.35 | 2.01 | 0.85 | 0->0 | 0->0 |
| 4x4 | board_snapshot_first | 0.21 | 0.30 | 1.38 | 0->0 | 0->0 |
| 4x4 | board_snapshot_warm | 0.05 | 0.06 | 1.06 | 0->0 | 0->0 |
| 4x4 | board_sync_nochange | 1.60 | 1.34 | 0.84 | 100->105 | 6->8 |
| 4x4 | board_sync_off | 1.22 | 1.37 | 1.13 | 70->70 | 2->2 |
| 4x4 | board_toggle_off | 1.39 | 1.80 | 1.29 | 130->85 | 4->6 |
| 4x4 | board_toggle_on | 1.75 | 2.07 | 1.19 | 106->105 | 3->4 |
| 4x4 | board_visibility_sh | 0.07 | 0.07 | 1.12 | 3->3 | 0->0 |
| 4x4 | board_visibility_sh_off | 0.04 | 0.05 | 1.08 | 2->2 | 0->0 |
| 4x4 | board_visible | 0.02 | 0.02 | 0.95 | 2->2 | 0->0 |
| 4x4 | import_agent_session | 0.30 | 0.35 | 1.17 | 0->0 | 0->0 |
| 4x4 | import_project_board | 1.92 | 1.94 | 1.01 | 0->0 | 0->0 |
| 4x4 | import_project_item | 0.57 | 0.57 | 1.00 | 0->0 | 0->0 |
| 4x4 | project_item_accept | 0.60 | 0.50 | 0.83 | 8->3 | 0->0 |
| 4x4 | project_item_check | 0.73 | 0.79 | 1.08 | 0->0 | 6->6 |
| 4x4 | project_item_ls | 1.34 | 0.80 | 0.60 | 32->3 | 0->0 |
| 4x4 | project_item_move_done | 2.96 | 2.89 | 0.98 | 58->17 | 8->8 |
| 4x4 | project_item_move_done_waived | 1.39 | 0.90 | 0.65 | 56->16 | 5->5 |
| 4x4 | project_item_move_todo | 0.60 | 0.59 | 0.98 | 8->3 | 2->2 |
| 4x4 | project_item_new | 0.45 | 0.54 | 1.18 | 0->0 | 2->2 |
| 4x4 | startup_python | 0.04 | 0.06 | 1.32 | 0->0 | 0->0 |
| 4x4 | status_cache_expired | 0.67 | 0.52 | 0.78 | 0->0 | 0->0 |
| 4x4 | status_cache_valid | 0.20 | 0.03 | 0.13 | 0->0 | 0->0 |
| 4x4 | status_no_cache | 0.39 | 0.44 | 1.12 | 0->0 | 0->0 |

steady(Board pane을 켜고 client 1개, status-interval 1초, 60초): 4×4에서 Board pane 1개는 v0.3.0 16.72 CPU초, v0.4.0 5.99(상태줄 script CPU 7.28 대 1.46, 실행 54회 대 59회)입니다. Board pane 4개(client 1개라 보이는 pane은 1개)는 20.22 대 5.92(상태줄 7.15 대 1.65)입니다. pane 안 process 수는 이 run의 steady counting이 PATH를 잘못 이어 0으로 기록됐습니다(도구 결함이며 고쳤고 4×4 steady를 다시 잽니다).

**측정 2: 같은 비교, 8×8, 2회.**

| scale | operation | v0.3.0 s | main s | ratio | tmux v0.3.0->main | other v0.3.0->main |
|---|---|---|---|---|---|---|
| 8x8 | agent_finish_ended | 5.77 | 6.34 | 1.10 | 69->18 | 3->3 |
| 8x8 | agent_restart_worker | 38.21 | 31.93 | 0.84 | 846->240 | 0->0 |
| 8x8 | agent_review | 1.48 | 2.31 | 1.56 | 24->8 | 0->0 |
| 8x8 | agent_review_clear | 0.72 | 0.48 | 0.66 | 8->3 | 0->0 |
| 8x8 | agent_review_clear_after | 1.21 | 3.97 | 3.28 | 8->3 | 0->0 |
| 8x8 | agent_send_to_leader | 3.33 | 7.30 | 2.19 | 48->16 | 0->0 |
| 8x8 | agent_send_to_worker | 2.78 | 5.93 | 2.13 | 48->15 | 0->0 |
| 8x8 | agent_start_worker | 18.03 | 21.27 | 1.18 | 738.5->199.5 | 18->18 |
| 8x8 | agent_stop_ended_worker | 5.67 | 8.67 | 1.53 | 74->17 | 3->3 |
| 8x8 | agent_stop_worker | 16.70 | 16.86 | 1.01 | 183->52 | 3->3 |
| 8x8 | agent_watch | 4.53 | 2.56 | 0.57 | 88->29 | 0->0 |
| 8x8 | bin_agent_session_help | 0.43 | 0.32 | 0.75 | 0->0 | 0->0 |
| 8x8 | bin_project_item_help | 0.66 | 0.49 | 0.74 | 0->0 | 0->0 |
| 8x8 | board_context | 0.01 | 0.01 | 1.00 | 1->1 | 0->0 |
| 8x8 | board_import | 0.32 | 0.28 | 0.90 | 0->0 | 0->0 |
| 8x8 | board_liveness | 16.77 | 0.46 | 0.03 | 1160->3 | 0->0 |
| 8x8 | board_popup_ready | 1.86 | 2.53 | 1.36 | 0->0 | 0->0 |
| 8x8 | board_sidebar_ready | 3.10 | 4.00 | 1.29 | 0->0 | 0->0 |
| 8x8 | board_snapshot_first | 0.73 | 0.62 | 0.85 | 0->0 | 0->0 |
| 8x8 | board_snapshot_warm | 0.19 | 0.22 | 1.17 | 0->0 | 0->0 |
| 8x8 | board_sync_nochange | 7.10 | 8.40 | 1.18 | 579->306 | 4->4 |
| 8x8 | board_sync_off | 3.62 | 3.46 | 0.95 | 226->226 | 2->2 |
| 8x8 | board_toggle_off | 3.94 | 5.34 | 1.36 | 241->239 | 6->4 |
| 8x8 | board_toggle_on | 4.84 | 5.27 | 1.09 | 338->321 | 5->5 |
| 8x8 | board_visibility_sh | 0.06 | 0.16 | 2.44 | 3->5 | 0->0 |
| 8x8 | board_visibility_sh_off | 0.05 | 0.10 | 1.80 | 2->2 | 0->0 |
| 8x8 | board_visible | 0.03 | 0.02 | 0.84 | 2->2 | 0->0 |
| 8x8 | import_agent_session | 0.48 | 0.60 | 1.24 | 0->0 | 0->0 |
| 8x8 | import_project_board | 2.88 | 1.84 | 0.64 | 0->0 | 0->0 |
| 8x8 | import_project_item | 0.49 | 0.46 | 0.93 | 0->0 | 0->0 |
| 8x8 | project_item_accept | 2.64 | 1.91 | 0.72 | 8->3 | 0->0 |
| 8x8 | project_item_check | 1.06 | 0.77 | 0.72 | 0->0 | 6->6 |
| 8x8 | project_item_ls | 1.73 | 1.05 | 0.61 | 64->3 | 0->0 |
| 8x8 | project_item_move_done | 6.93 | 9.55 | 1.38 | 66->17 | 8->8 |
| 8x8 | project_item_move_done_waived | 4.82 | 3.92 | 0.81 | 64->16 | 5->5 |
| 8x8 | project_item_move_todo | 1.02 | 2.85 | 2.81 | 8->3 | 2->2 |
| 8x8 | project_item_new | 1.11 | 2.11 | 1.91 | 0->0 | 2->2 |
| 8x8 | startup_python | 0.08 | 0.09 | 1.19 | 0->0 | 0->0 |
| 8x8 | status_cache_expired | 0.89 | 0.91 | 1.03 | 0->0 | 0->0 |
| 8x8 | status_cache_valid | 0.26 | 0.03 | 0.10 | 0->0 | 0->0 |
| 8x8 | status_no_cache | 0.75 | 0.63 | 0.84 | 0->0 | 0->0 |

steady 8×8: Board pane 1개는 v0.3.0 17.47 CPU초, v0.4.0 9.95(상태줄 5.99 대 2.19)입니다. pane 4개는 56.4 대 10.54(상태줄 9.75 대 2.22)입니다.

**16×16: 진행 중.** 첫 시도에서 v0.3.0의 counting pass가 보인 값입니다(그 run은 도구 결함으로 중단돼 다시 재는 중입니다). `Board liveness` 한 번이 tmux 4,496번·340초, `project-item ls`가 128번·7.4초(main은 3번·2초)였습니다. v0.3.0의 `start`는 host load 82에서 92초 만에 `provider_exited`로 실패했습니다. 등록 hook이 slot 17개를 모두 조회해 pane의 tmux가 316번이었습니다. 원인은 등록 hook(예산 25초)의 시간 초과로 보이며, 재측정에서 확인합니다. 정식 표는 재측정 뒤에 적습니다.

### 제출 3: 도구 수정 (CPU 시간·구간·반복·실패 내성, Leader 요청 반영)
- 제출 commit: 265ef84403fd61647cc80dd527a71099ed64fb29
- 바뀐 것(`tools/tests/perf`만, 제품 코드 변경 없음):
  - 명령마다 자식 process의 CPU 시간(user+sys, `RUSAGE_CHILDREN`의 차)을 `cpu`로 기록하고 표에 wall과 함께 냅니다. 측정 대상 밖에서 재는 값이며, 측정 명령의 자손이 아닌 process(tmux server가 대신 하는 일, Worker 등록·hook)는 들어가지 않습니다. 이 한계를 보고서(`summary.md`) 머리에 적습니다. Board 읽기(`board_*`)는 probe process 안에서 lap별 CPU(RUSAGE_SELF+CHILDREN)를 잽니다.
  - 중앙값마다 95% percentile-bootstrap 구간(3개 이상일 때)과 후보/기준 ratio의 구간을 냅니다. `improved`/`worse`는 ratio 구간 전체가 1의 한쪽에 있을 때만이고, 아니면 `same`(이 run의 오차를 넘는 차이 없음)입니다. 같은 값 두 묶음이 `same`이 되고 구간이 1을 포함함을 test합니다.
  - 반복: `--reps` 기본 9, 분 단위로 걸리는 lifecycle·board_cli는 `--slow-reps`로 따로 줄입니다. 줄였으면 표 머리에 반복 수가 적힙니다.
  - 실패 내성: lifecycle의 한 명령이 실패하면 그 row를 `rc != 0`(보고서의 `failed`)으로 남기고 나머지를 건너뛴 뒤 spare seat의 창·run 포인터·배정·CR을 되돌립니다. 가짜 `claude`는 hook 실패·시간 초과로 죽지 않고(실제 CLI와 같음) `start`가 `registration_failed`를 보고하게 둡니다.
  - Board probe는 liveness를 한 번만 읽고(v0.3.0의 16×16 liveness가 340초라 세 번이면 timeout), Board pane의 steady 호출 수 계수가 PATH를 잘못 이어 0이던 결함을 고쳤습니다.
  - 상태줄: main의 view 파일 변경에 맞춰 cache와 view를 함께 지우고 만료시킵니다. 병합된 main의 launcher(`-S`)가 바뀌어도 후보를 `-I -S`로 만드는 test가 깨지지 않게 정규식으로 바꿨습니다.
- 검증: 5491579(= 이 commit의 앞 commit)에서 `python -m pytest -q tools/tests/perf` 8 passed(host load 55~100에서 1902초), `tools/test_distribution_boundary.py` 9 passed, README 상대 link 검사 이상 없음. 그 뒤 origin/main이 BOARD-012(`project_board/tmux_control.py`와 그 test, CHANGELOG, CR 문서)로 움직여 merge(265ef84)했고, merge 위에서 통합 test를 뺀 도구 test 7 passed와 `test_distribution_boundary.py` 9 passed만 다시 실행했습니다. 통합 test(약 30분)는 merge 위에서 다시 돌리지 않았습니다. merge가 바꾼 파일에 `tools/tests/perf`가 없고 통합 test의 입력(제품 tree)은 BOARD-012가 Board의 tmux 호출만 바꿨기 때문입니다. 필요하면 Leader가 지시하십시오.
- 측정 진행: v0.3.0 대 main(v0.4.0)의 16×16(4회, lifecycle 2회)을 먼저 새 도구로 재는 중입니다(count pass 단계). 이어서 4×4(9회), A/A(9회), cold(16×16, 3회), PERF-002 후보(main d2326ce)의 4×4와 16×16, 8×8 순입니다. 16×16 등록 hook 시간 초과가 v0.4.0에서도 나는지는 이 run의 `start` row로 먼저 보고합니다.

### 제출 4: merge commit에서 도구 test 전체 재실행 (제출 3 검토 반영)
- 제출 commit: 55a6313a25b796ee9145e203902c221c2cd7c135
- 265ef84(BOARD-012 merge 포함)에 가짜 `claude`가 hook 소요 시간을 환경의 `hooks.log`에 남기는 한 commit(`tools/tests/perf/fake_claude.py`)만 더했습니다. 이 변경은 16×16 `start` 등록 hook이 얼마나 걸리는지 직접 재려고 넣었습니다.
- 검증: README 표 `tools/tests/perf/**` 행 전체를 이 tree(작업 트리가 55a6313과 같은 상태)에서 실행했습니다. `python -m pytest -q tools/tests/perf` **8 passed**(통합 test 포함, host load 120~240에서 2028초). `python -m pytest -q tools/test_distribution_boundary.py` 9 passed, README 상대 link 검사 이상 없음. 이 뒤 origin/main은 CR 문서 commit(3d104c8)만 움직였습니다.
- 16×16 `start` 등록 hook(요청 3): shim 없는 timing 환경에서 직접 잰 값(load 34~74): v0.3.0 hook 15.5초·13.8초(start 38.6·30.1초), v0.4.0(main d417943) hook 8.5초(start 24.0초)이고 load 73에서 v0.4.0 hook이 25.97초 만에 `registration_failed`로 실패했습니다. 등록 hook의 25초 예산에 대한 여유가 slot 수와 부하에 따라 줄어듭니다. counting pass(shim, load 50~117)에서는 두 실행본 모두 600초 기다리다 timeout했습니다. 결함으로 여는 것은 Leader가 판정합니다.

### 측정 결과 A (새 도구, 4×4): A/A와 v0.3.0 대 v0.4.0
앞의 "측정 1·2" 중간 보고는 이전 도구(CPU·구간 없음)의 값이라 이 절이 대신합니다. 도구는 main 9d746d8(제출 4) 위에 이 branch에서 고친 것(아래 "도구 수정")을 더한 것입니다. 원본: scratchpad `out/f-aa-4x4`, `out/f-main-4x4`(`results.jsonl`·`summary.json`·`summary.md`).

**실행.** `python3 tools/tests/perf/perf_bench.py run --exe v0.3.0=DIR --exe main=DIR --workdir W --out O --scales 4x4 --reps 9 --slow-reps 3 --cold-reps 0 --steady-seconds 60`(A/A는 `--exe base=<git archive 2fd2739>`, `--groups startup,readonly,board_cli,lifecycle`). warm 9회(lifecycle·board_cli는 3회, `n` 열이 실행 수). 실행본 `main`은 d417943(= v0.4.0 제품 코드). host load는 A/A 46~105, 비교 run 40~240(행마다 `load`). 표의 wall은 경과 초, cpu는 명령과 그 자손의 user+sys 초(tmux server가 대신 하는 일은 제외), 괄호는 95% bootstrap 구간, verdict는 ratio 구간이 1을 벗어날 때만 improved/worse입니다. tmux·other는 counting pass의 호출 수(규모·실행본당 1회, 늘 같음)입니다. 호출 수가 `-`인 lifecycle 연산은 그 run의 counting pass에서 start가 host 부하로 3번 모두 실패한 경우입니다(비교 run 표에서 같은 연산의 호출 수를 봅니다).

**A/A (v0.3.0 대 Base 2fd2739, 같은 제품 코드).** wall verdict 41개 모두 `same`, cpu verdict 38개 모두 `same`입니다(거짓 improved/worse 0건). 9회 연산의 cpu ratio 구간은 0.8~1.15 안(예: ls 1.00 [0.93-1.06], review_clear 0.98 [0.87-1.07], liveness 1.01 [0.96-1.07]), 3회 연산은 0.7~1.5까지 넓습니다. wall ratio 구간은 훨씬 넓어서(9회 연산 [0.4-2.1] 안팎, 3회 연산 [0.2-5.9]) 이 host에서 wall 시간으로는 ±2배 안의 차이를 구분하지 못하고, cpu 시간은 9회 기준 약 ±15%를 구분합니다. 따라서 이 CR의 "개선"은 cpu 구간이 1을 벗어나는 경우와 호출 수 감소로 판정합니다.

| scale | operation | n | v0.3.0 wall s | base wall s | wall ratio [95% CI] | verdict | v0.3.0 cpu s | base cpu s | cpu ratio [95% CI] | verdict | tmux v0.3.0->base | other v0.3.0->base |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 4x4 | agent_finish_ended | 3/3 | 13.30 | 12.72 | 0.96 [0.64-3.29] | same | - | - | - | - | -->- | -->- |
| 4x4 | agent_restart_worker | 3/3 | 75.83 | 53.89 | 0.71 [0.46-3.25] | same | 6.915 | 6.264 | 0.91 [0.79-1.43] | same | -->- | -->- |
| 4x4 | agent_review | 3/3 | 7.90 | 4.16 | 0.53 [0.28-3.66] | same | 0.691 | 0.666 | 0.96 [0.81-1.14] | same | -->- | -->- |
| 4x4 | agent_review_clear | 9/9 | 4.04 | 4.16 | 1.03 [0.52-2.11] | same | 0.492 | 0.483 | 0.98 [0.87-1.07] | same | 8->8 | 0->0 |
| 4x4 | agent_review_clear_after | 3/3 | 6.84 | 3.26 | 0.48 [0.22-3.75] | same | 0.501 | 0.459 | 0.92 [0.88-1.12] | same | -->- | -->- |
| 4x4 | agent_send_to_leader | 3/3 | 11.41 | 10.72 | 0.94 [0.19-3.93] | same | 1.044 | 1.039 | 1.00 [0.74-1.22] | same | -->- | -->- |
| 4x4 | agent_send_to_worker | 3/3 | 12.38 | 11.45 | 0.93 [0.33-1.99] | same | 1.047 | 1.057 | 1.01 [0.85-1.06] | same | -->- | -->- |
| 4x4 | agent_start_worker | 6/6 | 48.58 | 52.93 | 1.09 [0.65-2.95] | same | 5.856 | 5.961 | 1.02 [0.87-1.26] | same | -->- | -->- |
| 4x4 | agent_stop_ended_worker | 3/3 | 12.83 | 11.27 | 0.88 [0.63-3.64] | same | 1.265 | 1.305 | 1.03 [0.94-1.22] | same | -->- | -->- |
| 4x4 | agent_stop_worker | 3/3 | 33.00 | 29.33 | 0.89 [0.70-4.42] | same | 2.190 | 2.194 | 1.00 [0.93-1.51] | same | -->- | -->- |
| 4x4 | agent_watch | 9/9 | 9.81 | 8.42 | 0.86 [0.66-1.11] | same | 1.188 | 1.179 | 0.99 [0.92-1.04] | same | 52->52 | 0->0 |
| 4x4 | bin_agent_session_help | 9/9 | 1.36 | 1.85 | 1.36 [0.44-1.66] | same | 0.237 | 0.230 | 0.97 [0.89-1.06] | same | 0->0 | 0->0 |
| 4x4 | bin_project_item_help | 9/9 | 2.86 | 2.97 | 1.04 [0.51-1.88] | same | 0.388 | 0.373 | 0.96 [0.89-1.05] | same | 0->0 | 0->0 |
| 4x4 | board_context | 9/9 | 0.04 | 0.04 | 1.05 [0.33-1.37] | same | 0.011 | 0.011 | 0.98 [0.85-1.03] | same | 1->1 | 0->0 |
| 4x4 | board_import | 9/9 | 2.02 | 2.26 | 1.12 [0.68-1.78] | same | 0.214 | 0.227 | 1.06 [0.97-1.12] | same | 0->0 | 0->0 |
| 4x4 | board_liveness | 9/9 | 16.69 | 15.05 | 0.90 [0.72-1.23] | same | 3.144 | 3.175 | 1.01 [0.96-1.07] | same | 308->308 | 0->0 |
| 4x4 | board_popup_ready | 3/3 | 13.48 | 23.34 | 1.73 [0.25-3.74] | same | - | - | - | - | 0->0 | 0->0 |
| 4x4 | board_sidebar_ready | 3/3 | 18.39 | 26.57 | 1.45 [0.22-4.11] | same | - | - | - | - | 0->0 | 0->0 |
| 4x4 | board_snapshot_first | 9/9 | 1.77 | 2.23 | 1.26 [0.60-1.75] | same | 0.126 | 0.130 | 1.03 [0.94-1.13] | same | 0->0 | 0->0 |
| 4x4 | board_snapshot_warm | 9/9 | 0.17 | 0.23 | 1.31 [0.73-2.15] | same | 0.048 | 0.053 | 1.09 [0.92-1.31] | same | 0->0 | 0->0 |
| 4x4 | board_sync_nochange | 3/3 | 7.67 | 11.31 | 1.47 [0.28-2.56] | same | 1.501 | 1.504 | 1.00 [0.89-1.08] | same | 200->210 | 8->10 |
| 4x4 | board_sync_off | 3/3 | 7.81 | 9.18 | 1.18 [0.27-1.27] | same | 1.206 | 1.184 | 0.98 [0.87-1.07] | same | 70->70 | 2->2 |
| 4x4 | board_toggle_off | 3/3 | 7.45 | 11.43 | 1.53 [0.36-2.54] | same | 1.285 | 1.349 | 1.05 [0.88-1.11] | same | 85->125 | 6->12 |
| 4x4 | board_toggle_on | 3/3 | 12.17 | 10.58 | 0.87 [0.38-2.37] | same | 1.723 | 1.686 | 0.98 [0.89-1.04] | same | 106->105 | 3->4 |
| 4x4 | board_visibility_sh | 3/3 | 0.27 | 0.24 | 0.90 [0.26-2.37] | same | 0.058 | 0.057 | 0.98 [0.84-1.17] | same | 3->7 | 0->2 |
| 4x4 | board_visibility_sh_off | 3/3 | 0.14 | 0.17 | 1.23 [0.33-3.37] | same | 0.046 | 0.047 | 1.02 [0.80-1.22] | same | 2->2 | 0->0 |
| 4x4 | board_visible | 9/9 | 0.10 | 0.09 | 0.98 [0.58-1.80] | same | 0.019 | 0.019 | 0.96 [0.89-1.13] | same | 2->2 | 0->0 |
| 4x4 | import_agent_session | 9/9 | 4.09 | 3.18 | 0.78 [0.46-1.69] | same | 0.304 | 0.292 | 0.96 [0.91-1.02] | same | 0->0 | 0->0 |
| 4x4 | import_project_board | 9/9 | 14.78 | 16.66 | 1.13 [0.45-1.51] | same | 1.200 | 1.150 | 0.96 [0.89-1.01] | same | 0->0 | 0->0 |
| 4x4 | import_project_item | 9/9 | 3.11 | 4.44 | 1.43 [0.58-2.17] | same | 0.325 | 0.329 | 1.01 [0.95-1.05] | same | 0->0 | 0->0 |
| 4x4 | project_item_accept | 3/3 | 6.46 | 4.74 | 0.73 [0.34-4.34] | same | 0.520 | 0.486 | 0.93 [0.84-1.10] | same | -->- | -->- |
| 4x4 | project_item_check | 9/9 | 6.11 | 6.41 | 1.05 [0.46-2.13] | same | 0.561 | 0.562 | 1.00 [0.84-1.08] | same | 0->0 | 6->6 |
| 4x4 | project_item_ls | 9/9 | 5.67 | 5.09 | 0.90 [0.43-2.18] | same | 0.794 | 0.791 | 1.00 [0.93-1.06] | same | 32->32 | 0->0 |
| 4x4 | project_item_move_done | 3/3 | 19.22 | 20.12 | 1.05 [0.56-5.93] | same | 1.428 | 1.418 | 0.99 [0.96-1.25] | same | -->- | -->- |
| 4x4 | project_item_move_done_waived | 3/3 | 12.21 | 7.39 | 0.61 [0.38-2.74] | same | 1.116 | 1.132 | 1.01 [0.95-1.16] | same | -->- | -->- |
| 4x4 | project_item_move_todo | 6/6 | 6.84 | 6.19 | 0.90 [0.46-4.04] | same | 0.560 | 0.550 | 0.98 [0.87-1.14] | same | 8->8 | 2->2 |
| 4x4 | project_item_new | 6/6 | 6.06 | 6.00 | 0.99 [0.58-4.00] | same | 0.466 | 0.452 | 0.97 [0.91-1.26] | same | 0->0 | 2->2 |
| 4x4 | startup_python | 9/9 | 0.31 | 0.32 | 1.02 [0.63-2.94] | same | 0.051 | 0.056 | 1.09 [0.92-1.14] | same | 0->0 | 0->0 |
| 4x4 | status_cache_expired | 9/9 | 4.52 | 4.60 | 1.02 [0.64-2.01] | same | 0.401 | 0.416 | 1.04 [0.93-1.08] | same | 0->0 | 0->0 |
| 4x4 | status_cache_valid | 9/9 | 1.35 | 1.24 | 0.92 [0.56-1.52] | same | 0.185 | 0.187 | 1.01 [0.96-1.13] | same | 0->0 | 0->0 |
| 4x4 | status_no_cache | 9/9 | 3.93 | 4.13 | 1.05 [0.46-1.71] | same | 0.392 | 0.403 | 1.03 [0.92-1.10] | same | 0->0 | 0->0 |

**v0.3.0 대 v0.4.0 (main d417943), 4×4.**

| scale | operation | n | v0.3.0 wall s | main wall s | wall ratio [95% CI] | verdict | v0.3.0 cpu s | main cpu s | cpu ratio [95% CI] | verdict | tmux v0.3.0->main | other v0.3.0->main |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 4x4 | agent_finish_ended | 3/3 | 10.86 | 8.27 | 0.76 [0.30-1.09] | same | - | - | - | - | 61->18 | 3->3 |
| 4x4 | agent_restart_worker | 3/3 | 51.70 | 28.39 | 0.55 [0.33-0.80] | improved | 6.262 | 3.131 | 0.50 [0.41-0.56] | improved | 662->234 | 0->0 |
| 4x4 | agent_review | 3/3 | 4.25 | 3.58 | 0.84 [0.51-1.61] | same | 0.618 | 0.488 | 0.79 [0.67-0.85] | improved | 24->8 | 0->0 |
| 4x4 | agent_review_clear | 9/9 | 2.06 | 1.59 | 0.77 [0.31-3.98] | same | 0.415 | 0.397 | 0.96 [0.71-1.14] | same | 8->3 | 0->0 |
| 4x4 | agent_review_clear_after | 3/3 | 3.40 | 3.10 | 0.91 [0.44-2.20] | same | 0.478 | 0.382 | 0.80 [0.75-0.87] | improved | 8->3 | 0->0 |
| 4x4 | agent_send_to_leader | 3/3 | 7.59 | 7.15 | 0.94 [0.45-1.58] | same | 1.009 | 0.699 | 0.69 [0.66-0.73] | improved | 48->16 | 0->0 |
| 4x4 | agent_send_to_worker | 3/3 | 9.58 | 7.62 | 0.80 [0.59-1.20] | same | 1.015 | 0.674 | 0.66 [0.62-0.74] | improved | 48->15 | 0->0 |
| 4x4 | agent_start_worker | 6/6 | 36.81 | 28.63 | 0.78 [0.45-0.95] | improved | 5.689 | 2.992 | 0.53 [0.50-0.56] | improved | 590->203.5 | 18->18 |
| 4x4 | agent_stop_ended_worker | 3/3 | 10.37 | 10.20 | 0.98 [0.49-1.46] | same | 1.250 | 0.824 | 0.66 [0.61-0.68] | improved | 66->17 | 3->3 |
| 4x4 | agent_stop_worker | 3/3 | 34.01 | 17.70 | 0.52 [0.40-1.17] | same | 2.113 | 1.276 | 0.60 [0.60-0.67] | improved | 146.5->45 | 3->3 |
| 4x4 | agent_watch | 9/9 | 4.15 | 3.77 | 0.91 [0.31-2.78] | same | 1.095 | 0.780 | 0.71 [0.63-0.77] | improved | 52->17 | 0->0 |
| 4x4 | bin_agent_session_help | 9/9 | 1.46 | 0.84 | 0.57 [0.27-1.98] | same | 0.232 | 0.208 | 0.90 [0.83-1.17] | same | 0->0 | 0->0 |
| 4x4 | bin_project_item_help | 9/9 | 2.53 | 1.19 | 0.47 [0.17-2.55] | same | 0.357 | 0.324 | 0.91 [0.70-1.21] | same | 0->0 | 0->0 |
| 4x4 | board_context | 9/9 | 0.04 | 0.03 | 0.70 [0.35-2.54] | same | 0.010 | 0.011 | 1.11 [0.97-1.61] | same | 1->1 | 0->0 |
| 4x4 | board_import | 9/9 | 2.27 | 1.31 | 0.58 [0.19-3.94] | same | 0.178 | 0.183 | 1.03 [0.85-1.40] | same | 0->0 | 0->0 |
| 4x4 | board_liveness | 9/9 | 12.30 | 0.63 | 0.05 [0.02-0.10] | improved | 2.916 | 0.092 | 0.03 [0.03-0.04] | improved | 308->3 | 0->0 |
| 4x4 | board_popup_ready | 3/3 | 17.87 | 21.32 | 1.19 [0.42-2.83] | same | - | - | - | - | 0->0 | 0->0 |
| 4x4 | board_sidebar_ready | 3/3 | 14.71 | 18.53 | 1.26 [0.42-3.56] | same | - | - | - | - | 0->0 | 0->0 |
| 4x4 | board_snapshot_first | 9/9 | 1.15 | 0.92 | 0.80 [0.18-2.73] | same | 0.115 | 0.105 | 0.91 [0.77-1.11] | same | 0->0 | 0->0 |
| 4x4 | board_snapshot_warm | 9/9 | 0.15 | 0.12 | 0.85 [0.37-1.87] | same | 0.044 | 0.042 | 0.95 [0.84-1.26] | same | 0->0 | 0->0 |
| 4x4 | board_sync_nochange | 3/3 | 8.69 | 7.67 | 0.88 [0.23-2.42] | same | 1.464 | 1.441 | 0.98 [0.91-1.02] | same | 197->107 | 5->8 |
| 4x4 | board_sync_off | 3/3 | 9.13 | 7.85 | 0.86 [0.35-2.11] | same | 1.173 | 1.225 | 1.04 [0.97-1.07] | same | 70->70 | 2->2 |
| 4x4 | board_toggle_off | 3/3 | 7.12 | 9.96 | 1.40 [0.47-3.12] | same | 1.292 | 1.289 | 1.00 [0.97-1.06] | same | 153->95 | 8->10 |
| 4x4 | board_toggle_on | 3/3 | 10.68 | 8.33 | 0.78 [0.19-2.66] | same | 1.698 | 1.594 | 0.94 [0.86-1.05] | same | 106->105 | 3->4 |
| 4x4 | board_visibility_sh | 3/3 | 0.17 | 0.34 | 2.04 [0.61-3.79] | same | 0.053 | 0.055 | 1.04 [0.96-1.24] | same | 7->3 | 0->0 |
| 4x4 | board_visibility_sh_off | 3/3 | 0.19 | 0.22 | 1.13 [0.52-2.84] | same | 0.049 | 0.043 | 0.88 [0.82-1.03] | same | 2->2 | 0->0 |
| 4x4 | board_visible | 9/9 | 0.06 | 0.06 | 1.09 [0.43-2.81] | same | 0.018 | 0.020 | 1.11 [0.93-1.42] | same | 2->2 | 0->0 |
| 4x4 | import_agent_session | 9/9 | 1.65 | 1.36 | 0.83 [0.34-2.90] | same | 0.262 | 0.265 | 1.01 [0.87-1.26] | same | 0->0 | 0->0 |
| 4x4 | import_project_board | 9/9 | 8.00 | 6.25 | 0.78 [0.33-2.30] | same | 1.034 | 1.040 | 1.01 [0.76-1.17] | same | 0->0 | 0->0 |
| 4x4 | import_project_item | 9/9 | 1.34 | 1.50 | 1.12 [0.32-3.54] | same | 0.289 | 0.301 | 1.04 [0.65-1.18] | same | 0->0 | 0->0 |
| 4x4 | project_item_accept | 3/3 | 3.02 | 3.25 | 1.07 [0.33-2.12] | same | 0.475 | 0.408 | 0.86 [0.80-1.05] | same | 8->3 | 0->0 |
| 4x4 | project_item_check | 9/9 | 4.43 | 3.31 | 0.75 [0.22-2.38] | same | 0.546 | 0.523 | 0.96 [0.82-1.02] | same | 0->0 | 6->6 |
| 4x4 | project_item_ls | 9/9 | 3.25 | 2.38 | 0.73 [0.30-2.07] | same | 0.765 | 0.478 | 0.62 [0.57-0.74] | improved | 32->3 | 0->0 |
| 4x4 | project_item_move_done | 3/3 | 14.61 | 12.05 | 0.83 [0.41-1.06] | same | 1.346 | 0.981 | 0.73 [0.68-0.84] | improved | 58->17 | 8->8 |
| 4x4 | project_item_move_done_waived | 3/3 | 6.86 | 6.08 | 0.89 [0.55-1.18] | same | 1.055 | 0.751 | 0.71 [0.61-0.78] | improved | 56->16 | 5->5 |
| 4x4 | project_item_move_todo | 6/6 | 4.80 | 4.53 | 0.94 [0.48-1.23] | same | 0.542 | 0.475 | 0.88 [0.81-0.91] | improved | 8->3 | 2->2 |
| 4x4 | project_item_new | 6/6 | 4.01 | 4.10 | 1.02 [0.54-1.82] | same | 0.434 | 0.440 | 1.01 [0.98-1.08] | same | 0->0 | 2->2 |
| 4x4 | startup_python | 9/9 | 0.26 | 0.16 | 0.62 [0.35-2.48] | same | 0.046 | 0.044 | 0.96 [0.81-1.33] | same | 0->0 | 0->0 |
| 4x4 | status_cache_expired | 9/9 | 2.87 | 2.92 | 1.02 [0.21-7.06] | same | 0.377 | 0.381 | 1.01 [0.73-1.30] | same | 0->0 | 0->0 |
| 4x4 | status_cache_valid | 9/9 | 0.86 | 0.05 | 0.06 [0.02-0.22] | improved | 0.181 | 0.017 | 0.09 [0.08-0.12] | improved | 0->0 | 0->0 |
| 4x4 | status_no_cache | 9/9 | 2.30 | 4.20 | 1.83 [0.30-6.08] | same | 0.349 | 0.368 | 1.06 [0.88-1.38] | same | 0->0 | 0->0 |

해석: 호출 수 감소(tmux liveness 308→3, `project-item ls` 32→3, start 590→204, restart 662→234, stop 147→45, send 48→15)는 확정입니다. 시간은 cpu로 start 0.53배(구간 [0.50-0.56]), restart 0.50배, send 약 0.67배, stop 0.60배, `project-item ls` 0.62배, 상태줄(cache 유효) 0.09배, Board liveness 0.03배로 개선입니다. wall은 구간이 넓어 start(0.78 [0.45-0.95])·restart(0.55 [0.33-0.80])·liveness·상태줄만 improved이고 나머지는 구간에 1이 들어 있습니다. 개선이 없는 것(cpu verdict `same`): Python 시동·import(startup_python 0.044/0.046초, import_project_board 1.03/1.04초), `bin_*_help`, `project-item check`/`new`, Board `sync`·`toggle`(호출 수 197→107, 106→105, 153→95이나 cpu는 1.0배), 상태줄 cache 만료·없음(0.38초 안팎). 이들이 남은 비용입니다(원인 분류에서 다룹니다).

steady(이 표의 4×4 값은 Board TUI가 부하 아래 시작하는 중에 측정 창이 겹쳐 신뢰하지 않습니다. 도구를 고쳐 TUI가 ready를 표시한 뒤 재므로 이후 run의 값을 씁니다):
 (Board panes, one client, status-interval 1)

| scale | exe | board panes | seconds | board CPU s | status runs | status CPU s | tmux per s | other per s | load |
|---|---|---|---|---|---|---|---|---|---|
| 4x4 | main | 1 (1) | 60 | 6.71 | 42 | 1.67 | 0.3 | 0.0 | 83 |
| 4x4 | v0.3.0 | 1 (1) | 60 | 13.2 | 33 | 6.5 | 1.2 | 0.1 | 59 |
| 4x4 | main | 4 (4) | 60 | 8.79 | 58 | 2.46 | 1.8 | 0.8 | 49 |
| 4x4 | v0.3.0 | 4 (4) | 60 | 24.87 | 53 | 9.94 | 4.3 | 0.7 | 47 |


**도구 수정(이 branch, 다음 제출에 hash).** (1) lifecycle `start`의 `--timeout`을 180초로 두고 count pass의 lifecycle은 실패하면 최대 3번 다시 합니다(host 부하로 등록 hook이 예산을 넘는 일이 실제로 있어서, 실패를 10분 기다리지 않고 알아봅니다). (2) 실패한 lifecycle 뒤 spare seat의 git clone(남은 cr branch)과 벤치마크 CR을 되돌립니다(CR은 지웁니다). (3) 어떤 unit이 실패해도 run이 계속되고 그 row는 `failed`로 남습니다. (4) SIGTERM이 `SystemExit`이 아닌 예외라 unit의 실패 처리에 삼켜지지 않습니다. (5) steady 측정은 Board pane이 ready를 표시할 때까지 기다린 뒤 잽니다.

### 측정 결과 B (16×16): v0.3.0 대 v0.4.0 (main d417943)
원본: scratchpad `out/f-main-16x16`. 명령: `perf_bench.py run --exe v0.3.0=DIR --exe main=DIR --scales 16x16 --reps 4 --slow-reps 2 --cold-reps 0 --steady-seconds 60`. 환경은 project 16 × seat 16(slot 272개, project 0에 spare seat 1개 더), host load는 행마다 `load`(대부분 20~65, 이 run은 앞 run들보다 낮음). `n`이 2인 연산(lifecycle·board_cli)은 반복이 3 미만이라 구간과 verdict가 없습니다. 9회가 아니라 4회·2회로 줄였습니다(v0.3.0의 Board liveness 한 번이 1분이 넘어 시간이 오래 걸림). wall·cpu 정의와 구간·verdict 규칙은 측정 결과 A와 같습니다. 이 run의 counting pass에서 v0.3.0의 `start`가 `registration_failed`로 2번 실패한 뒤 성공했고(행은 `failed`로 남음) v0.4.0은 첫 시도에 성공했습니다.

| scale | operation | n | v0.3.0 wall s | main wall s | wall ratio [95% CI] | verdict | v0.3.0 cpu s | main cpu s | cpu ratio [95% CI] | verdict | tmux v0.3.0->main | other v0.3.0->main |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 16x16 | agent_finish_ended | 2/2 | 3.38 | 2.58 | 0.76 | - | - | - | - | - | 86->18 | 3->3 |
| 16x16 | agent_restart_worker | 2/2 | 23.34 | 13.33 | 0.57 | - | 6.669 | 2.602 | 0.39 | - | 1358->387 | 0->0 |
| 16x16 | agent_review | 2/2 | 0.84 | 0.75 | 0.89 | - | 0.586 | 0.459 | 0.78 | - | 24->8 | 0->0 |
| 16x16 | agent_review_clear | 4/4 | 0.58 | 0.52 | 0.88 [0.60-1.29] | same | 0.427 | 0.364 | 0.85 [0.71-1.14] | same | 8->3 | 0->0 |
| 16x16 | agent_review_clear_after | 2/2 | 0.63 | 0.56 | 0.88 | - | 0.453 | 0.390 | 0.86 | - | 8->3 | 0->0 |
| 16x16 | agent_send_to_leader | 2/2 | 2.70 | 2.09 | 0.77 | - | 0.946 | 0.638 | 0.67 | - | 48->16 | 0->0 |
| 16x16 | agent_send_to_worker | 2/2 | 3.17 | 2.07 | 0.65 | - | 0.994 | 0.642 | 0.65 | - | 48->15 | 0->0 |
| 16x16 | agent_start_worker | 4/4 | 13.83 | 6.58 | 0.48 [0.37-0.50] | improved | 5.916 | 2.119 | 0.36 [0.34-0.37] | improved | 1145->275.5 | 18->18 |
| 16x16 | agent_stop_ended_worker | 2/2 | 3.25 | 2.42 | 0.75 | - | 1.382 | 0.741 | 0.54 | - | 90->17 | 3->3 |
| 16x16 | agent_stop_worker | 2/2 | 12.54 | 6.87 | 0.55 | - | 2.458 | 1.281 | 0.52 | - | 265.5->67 | 3->3 |
| 16x16 | agent_watch | 4/4 | 6.37 | 5.17 | 0.81 [0.65-1.02] | same | 3.524 | 2.536 | 0.72 [0.67-0.87] | improved | 160->53 | 0->0 |
| 16x16 | bin_agent_session_help | 4/4 | 0.21 | 0.21 | 1.02 [0.77-1.33] | same | 0.145 | 0.149 | 1.03 [0.91-1.16] | same | 0->0 | 0->0 |
| 16x16 | bin_project_item_help | 4/4 | 0.36 | 0.30 | 0.84 [0.60-1.37] | same | 0.214 | 0.200 | 0.94 [0.75-1.15] | same | 0->0 | 0->0 |
| 16x16 | board_context | 4/4 | 0.01 | 0.02 | 1.36 [0.56-2.44] | same | 0.009 | 0.009 | 1.11 [0.86-1.69] | same | 1->1 | 0->0 |
| 16x16 | board_import | 4/4 | 0.17 | 0.27 | 1.62 [0.25-7.20] | same | 0.095 | 0.133 | 1.40 [0.56-2.34] | same | 0->0 | 0->0 |
| 16x16 | board_liveness | 4/4 | 66.79 | 1.83 | 0.03 [0.01-0.03] | improved | 39.250 | 0.428 | 0.01 [0.01-0.01] | improved | 4496->3 | 0->0 |
| 16x16 | board_popup_ready | 2/2 | 6.02 | 2.96 | 0.49 | - | - | - | - | - | 0->0 | 0->0 |
| 16x16 | board_sidebar_ready | 2/2 | 4.65 | 5.40 | 1.16 | - | - | - | - | - | 0->0 | 0->0 |
| 16x16 | board_snapshot_first | 4/4 | 1.62 | 1.98 | 1.22 [0.55-3.40] | same | 0.541 | 0.688 | 1.27 [0.97-1.59] | same | 0->0 | 0->0 |
| 16x16 | board_snapshot_warm | 4/4 | 0.41 | 0.39 | 0.94 [0.73-1.27] | same | 0.241 | 0.243 | 1.01 [0.91-1.13] | same | 0->0 | 0->0 |
| 16x16 | board_sync_nochange | 2/2 | 19.56 | 16.87 | 0.86 | - | 10.330 | 9.627 | 0.93 | - | 2090->1118 | 6->4 |
| 16x16 | board_sync_off | 2/2 | 15.02 | 13.80 | 0.92 | - | 7.369 | 7.693 | 1.04 | - | 826->826 | 2->2 |
| 16x16 | board_toggle_off | 2/2 | 12.67 | 13.55 | 1.07 | - | 7.475 | 7.509 | 1.00 | - | 1344->847 | 7->6 |
| 16x16 | board_toggle_on | 2/2 | 21.51 | 18.25 | 0.85 | - | 10.374 | 9.957 | 0.96 | - | 1274->1122 | 5->6 |
| 16x16 | board_visibility_sh | 2/2 | 0.09 | 0.08 | 0.87 | - | 0.065 | 0.055 | 0.84 | - | 6->3 | 0->0 |
| 16x16 | board_visibility_sh_off | 2/2 | 0.08 | 0.08 | 1.03 | - | 0.056 | 0.057 | 1.02 | - | 2->2 | 0->0 |
| 16x16 | board_visible | 4/4 | 0.03 | 0.03 | 1.11 [0.44-2.86] | same | 0.018 | 0.018 | 1.03 [0.63-1.32] | same | 2->2 | 0->0 |
| 16x16 | import_agent_session | 4/4 | 0.34 | 0.25 | 0.74 [0.53-0.97] | improved | 0.159 | 0.147 | 0.92 [0.64-1.03] | same | 0->0 | 0->0 |
| 16x16 | import_project_board | 4/4 | 1.31 | 1.06 | 0.81 [0.59-1.09] | same | 0.649 | 0.567 | 0.87 [0.73-1.05] | same | 0->0 | 0->0 |
| 16x16 | import_project_item | 4/4 | 0.27 | 0.29 | 1.05 [0.70-1.72] | same | 0.156 | 0.168 | 1.08 [0.83-1.41] | same | 0->0 | 0->0 |
| 16x16 | project_item_accept | 2/2 | 0.78 | 0.52 | 0.67 | - | 0.495 | 0.416 | 0.84 | - | 8->3 | 0->0 |
| 16x16 | project_item_check | 4/4 | 0.86 | 0.85 | 0.99 [0.59-1.39] | same | 0.494 | 0.520 | 1.05 [0.83-1.19] | same | 0->0 | 6->6 |
| 16x16 | project_item_ls | 4/4 | 2.49 | 0.83 | 0.33 [0.27-0.51] | improved | 1.691 | 0.565 | 0.33 [0.30-0.40] | improved | 128->3 | 0->0 |
| 16x16 | project_item_move_done | 2/2 | 4.23 | 2.93 | 0.69 | - | 1.607 | 1.087 | 0.68 | - | 82->17 | 8->8 |
| 16x16 | project_item_move_done_waived | 2/2 | 1.86 | 1.08 | 0.58 | - | 1.270 | 0.744 | 0.59 | - | 80->16 | 5->5 |
| 16x16 | project_item_move_todo | 4/4 | 0.69 | 0.71 | 1.03 [0.62-1.36] | same | 0.466 | 0.452 | 0.97 [0.78-1.19] | same | 8->3 | 2->2 |
| 16x16 | project_item_new | 4/4 | 0.79 | 0.72 | 0.91 [0.73-1.08] | same | 0.541 | 0.532 | 0.98 [0.81-1.08] | same | 0->0 | 2->2 |
| 16x16 | startup_python | 4/4 | 0.05 | 0.04 | 0.85 [0.41-1.15] | same | 0.034 | 0.031 | 0.90 [0.73-1.04] | same | 0->0 | 0->0 |
| 16x16 | status_cache_expired | 4/4 | 0.69 | 0.70 | 1.02 [0.72-4.19] | same | 0.410 | 0.403 | 0.98 [0.82-1.39] | same | 0->0 | 0->0 |
| 16x16 | status_cache_valid | 4/4 | 0.17 | 0.03 | 0.15 [0.11-0.19] | improved | 0.127 | 0.016 | 0.13 [0.10-0.17] | improved | 0->0 | 0->0 |
| 16x16 | status_no_cache | 4/4 | 1.12 | 0.86 | 0.77 [0.55-1.32] | same | 0.433 | 0.438 | 1.01 [0.84-1.24] | same | 0->0 | 0->0 |

해석(16×16): 호출 수는 Board liveness 4,496→3, `project-item ls` 128→3, start 1,145→276(자기 tmux와 서버가 대신 한 등록 호출의 합), restart 1,358→387, stop 266→67, send 48→15~16, watch 160→53으로 줄었습니다. cpu 시간 개선: Board liveness 0.01배(39.3초→0.43초, wall 66.8초→1.8초), `project-item ls` 0.33배 [0.30-0.40](wall 2.49→0.83초), start 0.36배 [0.34-0.37](cpu 5.9→2.1초, wall 13.8→6.6초), watch 0.72배, 상태줄(cache 유효) 0.13배. 반복 2회라 구간은 없지만 같은 방향: restart cpu 0.39배, stop 0.52배, send 0.65~0.67배, `project-item` accept·done 0.58~0.84배. **개선이 없는 것**: Board `sync`·`toggle`(호출 수는 줄었어도 cpu 9.6~10.4초 → v0.4.0에서 한 번 실행에 tmux 약 1,100번, cpu 약 10초; 창 수에 비례), Python 시동·import(startup_python 0.03초, import_project_board 0.65초), `project-item check`·`new`, 상태줄 cache 만료·없음. `stop`은 v0.4.0에서도 16×16 6.9초(cpu 1.28초)이고 4×4의 약 2배입니다.

steady 16×16(Board TUI가 ready를 표시한 뒤 60초):
 (Board panes, one client, status-interval 1)

| scale | exe | board panes | seconds | board CPU s | status runs | status CPU s | tmux per s | other per s | load |
|---|---|---|---|---|---|---|---|---|---|
| 16x16 | main | 1 (1) | 60 | 32.0 | 58 | 2.64 | 1.3 | 1.0 | 29 |
| 16x16 | v0.3.0 | 1 (1) | 60 | 46.91 | 55 | 9.06 | 13.2 | 1.0 | 39 |
| 16x16 | main | 4 (4) | 60 | 25.12 | 41 | 1.87 | 1.3 | 1.0 | 64 |
| 16x16 | v0.3.0 | 4 (4) | 60 | 95.73 | 54 | 9.83 | 133.0 | 1.0 | 33 |


v0.3.0 대 v0.4.0: Board pane 1개 cpu 46.9초→32.0초(60초 중 78%→53% 코어), 4개(client 1개, 보이는 pane 1개) 95.7초→25.1초. 상태줄 script cpu 9.06초→2.64초. **v0.4.0에서도 16×16의 보이는 Board pane 하나가 1분에 약 25~32 cpu초(코어의 약 40~53%)를 씁니다**: liveness를 읽는 3번의 호출은 작지만 snapshot(2초 주기, CR·결정 파일 stat)과 Textual TUI 갱신의 비용이 남는 것으로 보이며 원인 분류에서 다룹니다. `tmux per s`는 count pass(30초)의 Board pane 호출 수이며 v0.3.0 4개 pane의 133/s는 pane 4개가 모두 liveness를 읽은 때의 값으로 보입니다(client 1개가 한 window만 보이는데도, 새로 만든 pane들이 시작하는 동안 보임으로 간주된 구간이 있었을 가능성). 이 값은 참고용입니다.

### 측정 결과 C (16×16 cold, v0.3.0 대 v0.4.0)
원본: `out/f-cold-16x16`. 명령: `perf_bench.py run --exe v0.3.0=DIR --exe main=DIR --scales 16x16 --reps 1 --cold-reps 3 --groups readonly`. 각 측정 명령 앞에 61초 유휴(`/primehome`의 `acregmin=60`이라 파일 속성 cache가 만료됨)를 두었습니다. 읽기 전용 연산만이고 3회입니다(cold lifecycle은 시간이 너무 길어 하지 않았습니다. Leader가 8×8과 cold 확대를 줄였습니다).

| scale | operation | n | v0.3.0 wall s | main wall s | wall ratio [95% CI] | verdict | v0.3.0 cpu s | main cpu s | cpu ratio [95% CI] | verdict | tmux v0.3.0->main | other v0.3.0->main |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 16x16 | agent_review_clear | 3/3 | 0.88 | 2.46 | 2.80 [0.44-5.64] | same | 0.534 | 0.633 | 1.18 [0.79-1.45] | same | 8->3 | 0->0 |
| 16x16 | board_context | 3/3 | 0.01 | 0.01 | 1.20 [1.09-1.40] | worse | 0.007 | 0.007 | 0.96 [0.81-1.29] | same | 1->1 | 0->0 |
| 16x16 | board_import | 3/3 | 0.24 | 0.25 | 1.06 [0.32-3.24] | same | 0.110 | 0.119 | 1.08 [0.49-1.73] | same | 0->0 | 0->0 |
| 16x16 | board_liveness | 3/3 | 75.98 | 1.36 | 0.02 [0.02-0.03] | improved | 38.967 | 0.374 | 0.01 [0.01-0.01] | improved | 4496->3 | 0->0 |
| 16x16 | board_snapshot_first | 3/3 | 1.55 | 1.86 | 1.19 [0.30-2.06] | same | 0.585 | 0.650 | 1.11 [0.78-1.32] | same | 0->0 | 0->0 |
| 16x16 | board_snapshot_warm | 3/3 | 0.36 | 0.32 | 0.90 [0.52-2.35] | same | 0.235 | 0.209 | 0.89 [0.76-1.42] | same | 0->0 | 0->0 |
| 16x16 | board_visible | 3/3 | 0.03 | 0.03 | 0.78 [0.20-1.31] | same | 0.017 | 0.019 | 1.12 [0.68-1.27] | same | 2->2 | 0->0 |
| 16x16 | project_item_ls | 3/3 | 3.77 | 1.50 | 0.40 [0.24-1.07] | same | 1.631 | 0.707 | 0.43 [0.32-0.51] | improved | 128->3 | 0->0 |
| 16x16 | status_cache_expired | 3/3 | 0.87 | 0.99 | 1.14 [0.65-1.57] | same | 0.426 | 0.392 | 0.92 [0.90-0.99] | improved | 0->0 | 0->0 |
| 16x16 | status_cache_valid | 3/3 | 0.32 | 0.02 | 0.08 [0.03-0.25] | improved | 0.146 | 0.018 | 0.12 [0.08-0.17] | improved | 0->0 | 0->0 |
| 16x16 | status_no_cache | 3/3 | 1.11 | 1.07 | 0.97 [0.58-1.78] | same | 0.440 | 0.474 | 1.08 [0.77-1.34] | same | 0->0 | 0->0 |

cold는 warm보다 파일 접근이 많은 연산에서 길어집니다(예: `project-item ls` v0.3.0 wall 2.49초 warm → 3.77초 cold, v0.4.0 0.83초 → 1.50초; 상태줄 cache 유효 0.17초 → 0.32초, v0.4.0은 0.03초 → 0.02초). 개선은 cold에서도 같은 방향이고 cpu 구간이 1을 벗어납니다(liveness 0.01배, ls 0.43배, 상태줄 0.12배). `board_context`의 `worse`는 0.01초 단위 연산의 wall 구간이고 cpu는 `same`이라 무시합니다.

### 측정 결과 D (16×16, v0.4.0 대 v0.5.0)
원본: `out/f-v040-v050-16x16`. 명령: `perf_bench.py run --exe v0.4.0=<git archive v0.4.0> --exe v0.5.0=<git archive v0.5.0> --scales 16x16 --reps 3 --slow-reps 2 --cold-reps 0 --steady-seconds 60`. host가 한산해(load 9~40) 이전 run보다 시간 값이 안정적입니다. n이 2인 행(lifecycle·board_cli)은 구간·verdict가 없습니다. 모든 명령이 성공했습니다(`failed` 0).

| scale | operation | n | v0.4.0 wall s | v0.5.0 wall s | wall ratio [95% CI] | verdict | v0.4.0 cpu s | v0.5.0 cpu s | cpu ratio [95% CI] | verdict | tmux v0.4.0->v0.5.0 | other v0.4.0->v0.5.0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 16x16 | agent_finish_ended | 2/2 | 3.76 | 1.36 | 0.36 | - | - | - | - | - | 18->19 | 3->3 |
| 16x16 | agent_restart_worker | 2/2 | 24.94 | 7.23 | 0.29 | - | 3.255 | 1.820 | 0.56 | - | 321->107 | 0->0 |
| 16x16 | agent_review | 2/2 | 1.33 | 1.77 | 1.33 | - | 0.516 | 0.431 | 0.83 | - | 8->8 | 0->0 |
| 16x16 | agent_review_clear | 3/3 | 0.58 | 0.37 | 0.63 [0.58-0.73] | improved | 0.455 | 0.274 | 0.60 [0.50-0.74] | improved | 3->3 | 0->0 |
| 16x16 | agent_review_clear_after | 2/2 | 1.01 | 1.30 | 1.28 | - | 0.452 | 0.336 | 0.74 | - | 3->3 | 0->0 |
| 16x16 | agent_send_to_leader | 2/2 | 4.50 | 1.64 | 0.37 | - | 0.820 | 0.604 | 0.74 | - | 16->16 | 0->0 |
| 16x16 | agent_send_to_worker | 2/2 | 5.06 | 1.84 | 0.36 | - | 0.780 | 0.573 | 0.73 | - | 15->15 | 0->0 |
| 16x16 | agent_start_worker | 4/4 | 9.19 | 4.02 | 0.44 [0.21-0.93] | improved | 2.379 | 1.448 | 0.61 [0.45-0.85] | improved | 265.5->88.5 | 18->18 |
| 16x16 | agent_stop_ended_worker | 2/2 | 4.26 | 1.28 | 0.30 | - | 0.829 | 0.576 | 0.69 | - | 17->17 | 3->3 |
| 16x16 | agent_stop_worker | 2/2 | 11.84 | 4.22 | 0.36 | - | 1.571 | 1.013 | 0.64 | - | 68->32 | 3->3 |
| 16x16 | agent_watch | 3/3 | 4.17 | 3.97 | 0.95 [0.69-1.02] | same | 2.561 | 2.055 | 0.80 [0.71-0.88] | improved | 53->53 | 0->0 |
| 16x16 | bin_agent_session_help | 3/3 | 0.20 | 0.16 | 0.79 [0.62-0.89] | improved | 0.151 | 0.123 | 0.81 [0.63-0.82] | improved | 0->0 | 0->0 |
| 16x16 | bin_project_item_help | 3/3 | 0.32 | 0.26 | 0.81 [0.64-0.86] | improved | 0.220 | 0.175 | 0.80 [0.67-1.04] | same | 0->0 | 0->0 |
| 16x16 | board_context | 3/3 | 0.02 | 0.02 | 0.94 [0.74-1.27] | same | 0.010 | 0.010 | 1.02 [0.93-1.09] | same | 1->1 | 0->0 |
| 16x16 | board_import | 3/3 | 0.16 | 0.15 | 0.97 [0.73-1.16] | same | 0.099 | 0.085 | 0.86 [0.71-1.21] | same | 0->0 | 0->0 |
| 16x16 | board_liveness | 3/3 | 1.35 | 1.25 | 0.92 [0.86-0.99] | improved | 0.356 | 0.298 | 0.84 [0.73-0.89] | improved | 3->3 | 0->0 |
| 16x16 | board_popup_ready | 2/2 | 1.78 | 3.54 | 1.99 | - | - | - | - | - | 0->0 | 0->0 |
| 16x16 | board_sidebar_ready | 2/2 | 3.42 | 8.61 | 2.52 | - | - | - | - | - | 0->0 | 0->0 |
| 16x16 | board_snapshot_first | 3/3 | 0.93 | 0.88 | 0.95 [0.69-1.43] | same | 0.418 | 0.354 | 0.85 [0.66-1.01] | same | 0->0 | 0->0 |
| 16x16 | board_snapshot_warm | 3/3 | 0.26 | 0.22 | 0.84 [0.68-1.00] | improved | 0.191 | 0.138 | 0.72 [0.54-0.77] | improved | 0->0 | 0->0 |
| 16x16 | board_sync_nochange | 2/2 | 15.12 | 1.20 | 0.08 | - | 9.463 | 0.463 | 0.05 | - | 1118->8 | 6->6 |
| 16x16 | board_sync_off | 2/2 | 10.38 | 0.65 | 0.06 | - | 7.022 | 0.403 | 0.06 | - | 826->4 | 3->3 |
| 16x16 | board_toggle_off | 2/2 | 10.81 | 0.75 | 0.07 | - | 6.994 | 0.501 | 0.07 | - | 842->16 | 6->4 |
| 16x16 | board_toggle_on | 2/2 | 15.04 | 0.91 | 0.06 | - | 9.440 | 0.657 | 0.07 | - | 1123->16 | 8->6 |
| 16x16 | board_visibility_sh | 2/2 | 0.11 | 0.10 | 0.90 | - | 0.070 | 0.065 | 0.94 | - | 3->3 | 0->0 |
| 16x16 | board_visibility_sh_off | 2/2 | 0.08 | 0.09 | 1.11 | - | 0.060 | 0.058 | 0.97 | - | 2->2 | 0->0 |
| 16x16 | board_visible | 3/3 | 0.03 | 0.03 | 1.00 [0.79-1.81] | same | 0.019 | 0.018 | 0.97 [0.84-1.90] | same | 2->2 | 0->0 |
| 16x16 | import_agent_session | 3/3 | 0.28 | 0.22 | 0.77 [0.56-1.13] | same | 0.153 | 0.120 | 0.78 [0.59-0.95] | improved | 0->0 | 0->0 |
| 16x16 | import_project_board | 3/3 | 0.90 | 0.93 | 1.03 [0.96-1.12] | same | 0.613 | 0.567 | 0.92 [0.83-1.13] | same | 0->0 | 0->0 |
| 16x16 | import_project_item | 3/3 | 0.24 | 0.22 | 0.95 [0.71-1.07] | same | 0.154 | 0.135 | 0.88 [0.69-1.11] | same | 0->0 | 0->0 |
| 16x16 | project_item_accept | 2/2 | 0.96 | 0.63 | 0.66 | - | 0.455 | 0.326 | 0.72 | - | 3->3 | 0->0 |
| 16x16 | project_item_check | 3/3 | 0.78 | 0.53 | 0.69 [0.63-0.88] | improved | 0.462 | 0.381 | 0.83 [0.61-0.84] | improved | 0->0 | 6->6 |
| 16x16 | project_item_ls | 3/3 | 0.87 | 0.67 | 0.76 [0.53-1.06] | same | 0.584 | 0.399 | 0.68 [0.55-0.81] | improved | 3->3 | 0->0 |
| 16x16 | project_item_move_done | 2/2 | 4.32 | 2.25 | 0.52 | - | 1.130 | 0.882 | 0.78 | - | 17->17 | 8->8 |
| 16x16 | project_item_move_done_waived | 2/2 | 1.56 | 1.04 | 0.67 | - | 0.881 | 0.566 | 0.64 | - | 16->16 | 5->5 |
| 16x16 | project_item_move_todo | 4/4 | 1.08 | 0.57 | 0.53 [0.18-1.37] | same | 0.482 | 0.330 | 0.69 [0.53-0.88] | improved | 3->3 | 2->2 |
| 16x16 | project_item_new | 4/4 | 0.87 | 0.54 | 0.63 [0.21-1.41] | same | 0.557 | 0.347 | 0.62 [0.51-0.75] | improved | 0->0 | 2->2 |
| 16x16 | startup_python | 3/3 | 0.05 | 0.05 | 0.95 [0.72-1.35] | same | 0.030 | 0.031 | 1.04 [0.64-1.33] | same | 0->0 | 0->0 |
| 16x16 | status_cache_expired | 3/3 | 0.76 | 0.53 | 0.69 [0.56-0.90] | improved | 0.409 | 0.251 | 0.61 [0.60-0.72] | improved | 0->0 | 0->0 |
| 16x16 | status_cache_valid | 3/3 | 0.02 | 0.02 | 0.74 [0.64-0.84] | improved | 0.018 | 0.013 | 0.74 [0.61-0.84] | improved | 0->0 | 0->0 |
| 16x16 | status_no_cache | 3/3 | 0.97 | 0.52 | 0.53 [0.41-1.31] | same | 0.368 | 0.266 | 0.72 [0.57-0.82] | improved | 0->0 | 0->0 |

해석: BOARD-012가 Board `sync`·`toggle`의 창별 tmux 호출을 없앴습니다(sync 1118→8, toggle_on 1123→16, toggle_off 842→16, sync_off 826→4번, cpu 9.5초→0.46초·7.0초→0.40초, wall 15→1.2초). PERF-002·003이 Python 시동 쪽을 약 20% 줄였습니다(`bin_agent_session_help` cpu 0.151→0.123초 [0.63-0.82], import_agent_session 0.153→0.120초, project-item check·new·move 0.62~0.83배, 상태줄 cache 만료 0.409→0.251초). start는 cpu 0.61배 [0.45-0.85](tmux 266→89번, wall 9.2→4.0초), restart cpu 0.56배(tmux 321→107), stop tmux 68→32, 상태줄 만료 0.61배입니다. 개선 없음: Board snapshot·import(import_project_board cpu 0.57~0.61초 그대로), `agent_watch`(tmux 53번 그대로, cpu 0.80배), `agent_review`·`send`의 호출 수(8·15·16번 그대로. send는 MCP 세션 비용이 남음).

steady 16×16(Board TUI ready 후 60초):
 (Board panes, one client, status-interval 1)

| scale | exe | board panes | seconds | board CPU s | status runs | status CPU s | tmux per s | other per s | load |
|---|---|---|---|---|---|---|---|---|---|
| 16x16 | v0.4.0 | 1 (1) | 60 | 30.08 | 60 | 2.57 | 1.3 | 1.5 | 17 |
| 16x16 | v0.5.0 | 1 (1) | 60 | 25.57 | 60 | 1.6 | 1.3 | 1.5 | 17 |
| 16x16 | v0.4.0 | 4 (4) | 60 | 30.68 | 59 | 2.1 | 1.3 | 1.9 | 22 |
| 16x16 | v0.5.0 | 4 (4) | 60 | 27.19 | 60 | 1.53 | 1.3 | 1.5 | 16 |


**Board pane 하나의 steady cost는 v0.5.0에서도 60초에 cpu 25.6초(코어의 43%)**이고 v0.3.0의 46.9초에서 약 절반입니다. 상태줄 script는 9.06초→2.57초→1.60초입니다. 호출 수(`tmux per s` 1.3)는 작아졌는데 cpu가 남으므로 이 비용은 tmux 호출이 아니라 Board TUI 안(snapshot 2초 주기의 CR·결정 파일 stat과 `model` 변환, Textual 갱신)에서 나옵니다(BOARD-013으로 열림).

### 원인 분류와 연산별 목표 시간 (짧게)
**(a) 같은 조회를 slot·project마다 반복하는 알고리즘 결함** — 호출 수가 `slot` 수에 비례합니다(v0.3.0 근거: 4×4 / 8×8 / 16×16).
- `Tmux.get_current`(`tools/agent-session/agent_session/tmux.py:411`)는 한 번에 tmux 8번(list-sessions 3, show-options 2, display-message 1, read_meta 2)이고 호출자가 slot마다 부릅니다. `api.project_liveness`(`api.py:100`, slot마다 get_current+`pane_info` 9번)·`project_pending_releases`(`api.py:230`, assigned seat마다 8번): Board liveness **308 / 1,160 / 4,496번**(16×16 wall 66.8초, cpu 39.3초; 부하 100에서는 340초). `project-item ls`(`cli.py:78` → `lifecycle.py:1034`, seat마다 8번): **32 / 64 / 128번**. 등록 hook과 launch의 `internal._run`(`internal.py:24-31`, 모든 slot의 get_current)과 `watch`(`watch.py:97`)도 같은 형태입니다. 이 때문에 16×16의 등록 hook(제한 25초)이 8.5~26초 걸려 부하 73에서 start가 `registration_failed`가 됐습니다. 고침: SESSION-010(v0.4.0)이 `list-windows` 한 번의 snapshot으로 읽음 → liveness 3번, ls 3번, start 1,145→276번. 관측 동작 변경 없음. Rust로 바꿔도 tmux fork 수는 그대로입니다(호출 하나 15~32 ms는 python과 bash가 같음).
- Board `_reconcile`(`tools/project-board/project_board/tmux_control.py:417`, `_panes`·`_board_pane`·`_managed_pane_dead` 창마다 5~6번): sync·toggle **100 / 306 / 1,118~2,090번**, cpu 9.5~10.4초(16×16). 고침: BOARD-012(v0.5.0) → 8~16번, cpu 0.4~0.7초. 관측 동작 변경 없음. Rust 이점 없음.
- Board 갱신마다 `reap_runtime_directories`(`tmux_control.py:144`, `_private_dir` :183, `tui.py:455`의 snapshot 적용마다)가 다른 server 디렉터리마다 `ps`를 부릅니다(2초마다 1~2번). 상태줄 script는 매초 bash+Python을 띄웠습니다(v0.3.0 cache 유효 0.86초 wall·cpu 0.18초). 고침: TMUX-003(v0.4.0, view 파일, cache 유효 0.02초 cpu 0.016초).
- 남은 것: Board TUI 자체 비용(위 steady, BOARD-013), `watch`(slot마다 조회, tmux 53번), `review`·`send`·`stop`의 `get_current`+provider 조회 반복(`lifecycle.py:865` 루프가 0.1초마다 observe).

**(b) interpreter 시동·NFS import** — Python 시동 자체는 0.03~0.05초(`startup_python`)로 작고 문제는 import입니다: `import agent_session.lifecycle` cpu 0.12~0.26초, `project_board.tui`(Textual) 0.57~1.0초, `agent-session --help` 0.12~0.23초, `project-item` 명령 0.3~0.55초. 이것이 5초 안쪽 명령(`review --clear` 0.37~0.43 cpu초 등)의 바닥입니다. 고침: PERF-002·003(v0.5.0)이 약 20% 줄임(위). 추가는 module 지연 import·단일 bundle. 관측 동작 변경 없음. **Rust로 바꾸면 줄어드는 유일한 부분**(시동+import 0.12~0.5초 → 수 ms, 명령당 cpu 0.1~0.5초 절감. 1초 안쪽 명령에서만 의미).

**(c) 의도한 대기·provider** — `MCPClient.close`(`providers/mcp.py:68-85`): 입력을 닫고 `wait(timeout=1)` 뒤 `terminate`. 실제 `claude mcp serve` 한 세션 2.5초(open 0.77 + ListAgents 0.2 + close 1.57, `provider_probe.py` 실측 5회 중앙값). `send`·`verify_binding`·`observe`는 세션 하나씩, **`stop`은 observe마다 세션**이라 `lifecycle.py:865`의 0.1초 poll 루프 한 번이 2.5초 이상이고 stop은 최소 3세션 ≈ 7.5초(+CLI 종료)입니다. 사용자 server의 실제 `start`: run 기록(launch.sh와 state의 `connected_at`) 30개 중앙값 6.5초(2.4~22.7초), 등록 hook `_HOOK_BUDGET` 25초(`internal.py:16`)와 `_BINDING_INTERVAL` 1초(:18), start poll 0.1초(`lifecycle.py:445`), 파일 lock poll 0.05초(`state.py:54`), 시작 dialog 확인 1초(`lifecycle.py:15`). 고침: close는 즉시 terminate(대기 1초 제거), stop은 observe마다 새 세션 대신 한 세션 재사용, 등록 hook 예산을 slot 수에 묶지 않는 구조. 관측 동작 변경 없음(내부 대기). Rust 이점 없음(provider 프로세스).

**(d) host 부하** — srv04의 load가 9~240으로 변합니다. A/A에서 wall ratio가 0.4~2.1배로 흩어져 wall로는 ±2배를 구분하지 못했고(cpu는 약 ±15%), 같은 연산이 load에 따라 13.8초(start v0.3.0, load 37)와 53초 이상, 한계 시간 초과까지 갔습니다. 등록 hook(25초 예산)이 slot 수와 load 모두에 비례하므로 16×16에서는 부하 70 이상에서 실패합니다(v0.3.0은 load 37~40에서도 2번 실패). 도구로 줄일 수 없고 예산·구조(위 (a)(c))로만 여유를 만듭니다.

**연산별 목표(16×16, load 50 이하, 제안).** 표의 v0.5.0 값을 기준으로 현실적인 한계를 둡니다.

| 연산 | 지금(v0.5.0, cpu초 / wall초) | 목표 |
| --- | --- | --- |
| Board liveness·snapshot 읽기 | 0.30 / 1.25 | cpu 0.3초, tmux 3번 이하(유지) |
| Board sync·toggle | 0.46~0.66 / 0.7~1.2 | cpu 0.7초, tmux 20번 이하(유지) |
| Board pane steady(60초) | 25.6초 cpu | 코어의 5%(60초 cpu 3초) 이하 |
| 상태줄 cache 유효 | 0.013 / 0.02 | 0.02초 이하(유지) |
| 상태줄 만료 | 0.25 / 0.53 | 0.2초 이하 |
| `project-item ls`·`check`·`new`·`move` | 0.32~0.40 / 0.5~0.7 | cpu 0.25초 이하 |
| `review --clear`·`review` | 0.27~0.43 / 0.4~1.8 | cpu 0.3초 이하, tmux 3번 |
| `send` | 0.57~0.60 / 1.6~1.8 | wall 1.5초 이하(MCP 세션 1.5초 중 close 1초 제거) |
| `watch` | 2.06 / 4.0 | tmux 10번 이하, cpu 1초 |
| `start`(fixture) | 1.45 / 4.0 | wall 5초 이하, 등록 hook 5초 이하(25초 예산의 5배 여유) |
| `stop`(fixture) | 1.01 / 4.2 | wall 3초 이하(observe마다 MCP 세션 제거) |
| `restart` | 1.82 / 7.2 | wall 8초 이하 |
| 프로세스 시동(`--help`) | 0.12 / 0.16 | cpu 0.08초(import 지연) |

### 제출 5: 최종 (도구 수정 + 측정 결과 A~E + 원인 분류)
- 제출 commit: 7df707f6904a4d9dd037eed1df51a81dbe22634a
- 도구 수정(`tools/tests/perf`만, 제품 코드 변경 없음): 측정 결과 A의 "도구 수정" 다섯 가지(start timeout 180초와 count pass 재시도, 실패 뒤 seat clone·CR 복구, unit 실패 내성, SIGTERM이 삼켜지지 않는 예외, steady의 Board ready 대기)와 `-I -S` 후보 test가 이미 `-S`로 시작하는 launcher 형태를 그대로 두도록 한 것. 이 commit은 origin/main 0.6.0(ae30dbe)까지 merge한 것입니다.
- 검증(7df707f에서): `python -m pytest -q tools/tests/perf` **8 passed**(통합 test 포함, 749초, host load 10~60), `python -m pytest -q tools/test_distribution_boundary.py` 9 passed, README 상대 link 검사 이상 없음. 이 뒤 origin/main이 BOARD-013(`tools/project-board`의 코드·test)으로 움직였습니다. 바뀐 파일에 `tools/tests/perf`는 없고(도구는 이 branch가 더 새로움), 통합 test는 그 merge 위에서 다시 돌리지 않았습니다.
- 측정 범위(Leader 조정 반영): A/A와 v0.3.0 대 v0.4.0은 4×4(warm 9회, lifecycle 3회), 16×16(warm 4회, lifecycle 2회, cold 3회)입니다. 8×8은 새 도구로 재지 않았습니다(이전 도구의 호출 수만 있음: liveness 1160, ls 64, start 738→200). v0.4.0 대 v0.5.0은 16×16 한 번(warm 3회, lifecycle 2회, steady 포함, cold 생략)이고 PERF-002 후보 d2326ce는 v0.5.0에 포함돼 따로 재지 않았습니다. 이 세 가지를 줄였다는 사실은 표 머리의 `n`과 위 설명에 있습니다.
- 환경 정리(Verification 3): 이 도구는 `claim`/`release`로 server와 socket을 지우고 작업 디렉터리를 지웁니다. 측정이 끝난 뒤 `/tmp/tmux-1028`에 내 `perf-*` socket이 없음(다른 seat의 측정 socket은 그 seat 것)과 내 자식 process 정리를 확인합니다(종료 보고 직전).
- 재현 명령은 각 결과 절의 "명령"입니다. Leader 측정 두 개의 재측정(Verification 2): `review --clear`는 v0.3.0에서 cpu 0.415초(4×4)·0.427초(16×16)이고 tmux 8번(Leader의 3.1초 중 tmux 8번과 같음, 나머지는 시동·import: `agent-session --help` cpu 0.145~0.232초), Board liveness tmux 호출은 slot당 약 15번(4×4 308번, 8×8 1160번, 16×16 4,496번)으로 46 slot 환경의 396번과 같은 비례입니다(slot 46개 × 8~9번 = 372~414번; 이 도구의 4×4는 20 slot에 308번이라 assigned seat의 `pending_releases` 8번이 더해진 값).
