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
