# SESSION-011: 16 project × seat 16에서 등록 hook이 한도에 닿아 Worker start가 실패하거나 600초를 기다립니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: PERF-001, SESSION-010, SESSION-012
- Base: 78e6f77fb5e9bbc28d361fe8c9af9bdddfd0050b 2026-11-10T15:56:42+09:00
- Outcome: fixed

## Symptom
project 16개 × seat 16개에서 Worker `start`의 등록 hook(SessionStart)이 seat 수와 host 부하에 비례해 길어져 한도(`_HOOK_BUDGET` 25초, settings의 hook timeout 30초)에 닿습니다. 부하가 높으면 `start`가 `registration_failed`로 실패합니다. hook이 timeout으로 강제 종료되면 실패 기록이 남지 않아 `start`가 약 600초를 기다린 뒤에야 끝납니다. 사용자가 물은 규모(2026-11-10: "project가 굉장히 여러개 일때도? 예를 들어 각 seat가 16개씩 project 16개?")에서 Worker를 시작할 수 없는 결함입니다.

## Evidence
- PERF-001 측정(2026-11-10, `tools/tests/perf`, 격리 tmux server, 가짜 `claude`):
  - shim 없는 timing 환경, load 34~74:
    - v0.3.0: hook 15.5초·13.8초, `start` 38.6초·30.1초
    - v0.4.0(main d417943): hook 8.5초, `start` 24.0초
    - load 73일 때 v0.4.0 hook이 25.97초 만에 rc=1로 끝나고 `start`가 `registration_failed`("Claude MCP did not reply before the deadline")로 실패했습니다.
    - 4×4에서는 둘 다 정상입니다(v0.4.0 `start` tmux 177번, 4.8초).
  - shim이 붙은 counting pass: 둘 다 hook이 30초를 넘었고, `start`는 604초·608초 뒤 timeout으로 끝났습니다. v0.4.0의 `start` tmux 2208번은 등록 완료를 0.1초 간격으로 기다린 조회입니다.
- 코드(`tools/agent-session/agent_session/internal.py`):
  - `_run`(24행)은 `leader`와 모든 seat를 돌며 slot마다 `get_current`를 부릅니다. seat 16개면 tmux 실행이 34번입니다. `mark_process`와 등록 hook이 모두 이 함수를 지납니다. SESSION-010의 `server_view`를 쓰지 않는 반복 조회입니다.
  - `_bind` → `_verify_binding`은 provider의 binding 확인(Claude MCP 시동과 ListAgents)을 1초 간격으로 되풀이할 수 있습니다(`_BINDING_TIMEOUT` 20초).
  - `_record_failure`는 hook이 SessionError로 끝날 때만 실패를 남깁니다. hook process가 Claude의 hook timeout으로 죽으면 아무것도 남지 않습니다.

## Contract
- 16×16 규모에서 host load 70 이상일 때도 Worker `start`가 성공합니다.
- 등록 hook이 결과(게시 또는 실패 기록) 없이 끝나면 `start`는 hook 한도에 짧은 여유를 더한 시간 안에 오류로 끝납니다. 오류는 이유를 담은 `registration_failed`입니다. 600초를 그냥 기다리지 않습니다.
- CLI JSON·state 형식·tmux option의 의미는 바꾸지 않습니다. 새 필드나 option이 필요하면 동작 명세와 형식 버전 규칙(release.md 3절)을 따릅니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 재현 측정이 있는 결함입니다. 사용자가 물은 규모에서 Worker 시작이 실패합니다.
- 2026-11-10 Leader: open -> todo. 16x16에서 start 실패, 재현 측정 있음
- 2026-11-10 Leader: 제출 3cb144015197000574d90e9781da355442df93a2를 인수합니다. 검토 3cb1440(구현 81d4322 + main 2e73d06·c784f59 merge, providers/는 main과 같음). Tmux.current_with_run(포인터 한 번 읽기, 이 run을 가리키는 slot만 window 읽기; 포인터의 run_id는 v0.1.0부터 _IDENTITY에 있어 옛 run과도 맞습니다), register_from_hook의 두 번째 _run 제거, hook_started 기록과 start 대기의 종료 판정(재읽기 뒤 ready·start_error 우선, remote seat 제외), process.age로 센 hook deadline(최대 10초 차감), 명세 문구를 읽었습니다. README 표 행(tools/agent-session/**: 833 passed, spec.md의 test_remote 포함)과 merge가 입력을 바꾼 네 번째 명령(130 passed)을 merge commit에서 실행했습니다. 수정 전 실패하는 hook 강제 종료 test, seat 2·6·16 호출 수 test가 있습니다. 16x16 A/B start wall 0.71·CPU 0.72 improved, v0.4.0은 start 2회 registration_failed였고 후보 timing pass는 6회 모두 성공. 한도 조정 제안과 hook의 MCP 시동 비용은 후속 CR로 Leader가 판정합니다.
- 2026-11-10 Leader: in-progress -> done, Outcome fixed. 통합 1999c5d (origin/main)

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), [동작 명세](../../project-team/spec.md)의 등록·게시(3절, 5절), `tools/agent-session/agent_session/internal.py`, `providers/claude.py`, SESSION-010의 `ServerView`, 측정 도구 `tools/tests/perf/perf_bench.py` 머리말(가짜 `claude`의 `hooks.log`), [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 시간 분해: 4×4와 16×16에서 등록 hook의 단계별 시간을 잽니다. 단계는 interpreter 시동, `_run`, provider binding 확인(MCP 시동·ListAgents·close), 잠금 대기, 게시입니다. 각 단계의 tmux·subprocess 수도 함께 잽니다.
2. hook 경로의 반복 조회를 없앱니다. `_run`이 slot마다 `get_current`를 부르지 않게 하고, `server_view` 같은 한 번의 읽기로 run을 찾습니다. `mark_process` 등 같은 함수를 지나는 다른 경로도 함께 바뀝니다. 그 밖에 hook 안에서 slot·project 수에 비례하는 일이 있으면 함께 고칩니다.
3. provider 확인의 비용을 1단계 근거로 줄입니다. 예: 되풀이 확인에서 MCP client를 다시 띄우지 않기, 불필요한 close 대기 없애기. Claude CLI와의 계약(`claude mcp serve`, ListAgents)은 바꾸지 않습니다.
4. hook이 결과 없이 끝나면 `start`가 hook 한도에 짧은 여유를 더한 시간 안에 `registration_failed`로 끝나게 합니다. hook이 시작했고 결과 없이 끝났다는 사실이 남아야 합니다. 예: hook이 자기 시작 시각과 process를 run 기록에 남기고, `start`가 그 process의 종료를 봅니다. 방법은 Worker가 정하고 명세에 적습니다.
5. 1~4로도 부하가 높을 때 한도가 부족하다는 근거가 나오면, 한도(`_HOOK_BUDGET`, settings timeout)의 조정을 근거와 함께 제안합니다. 한도만 늘리는 것은 해법이 아닙니다.

의존: 없음. SESSION-012와 `lifecycle.py`·`providers/claude.py`가 겹칠 수 있습니다. 제출 전에 `origin/main`을 merge합니다.

위험 등급: 높음. 모든 run의 시작 등록 경로입니다.

## Verification
1. 측정 도구로 v0.4.0과 후보를 비교합니다. 규모는 16×16과 4×4이고, `start`(Leader·Worker), 등록 hook 단계 시간, tmux 수를 봅니다. host load도 함께 적습니다.
2. 16×16에서 load가 높은 때(70 이상)에 `start`가 성공함을 보입니다. 그런 때를 얻기 어려우면 CPU 부하를 걸어 재현합니다.
3. hook이 결과 없이 끝나는 경우(예: hook을 강제로 죽이는 test)에 `start`가 한도 안에서 `registration_failed`로 끝나는 test. 수정 전에 실패해야 합니다.
4. hook 경로의 tmux 실행 수가 seat 수와 무관하다는 호출 수 test.
5. README 검증 표에서 바꾼 경로의 행을 모두 실행합니다(`-rf`). `api.py`·state 형식·tmux option을 바꾸면 project-item·project-board·`install/tests`도 실행합니다.
6. 제출 전에 `origin/main`이 움직여 위 명령의 입력을 바꿨으면 merge하고 merge commit에서 다시 실행합니다.

## Result
- 제출 commit: 3cb144015197000574d90e9781da355442df93a2

`origin/main`(PERF-003 2e73d06, SESSION-012 c784f59까지)을 merge한 commit입니다. `cr/SESSION-011`을 push했습니다. 검증은 아래 "검증"의 근거 재사용 표를 따릅니다.

### 원인 (1단계 시간 분해, 수정 전 측정)
가짜 `claude`와 sitecustomize 추적(분석용, 저장소에는 없음)으로 hook 한 번의 단계를 쟀습니다.

| 규모(host load) | hook 전체 | interpreter+import | `_run` 2회 | MCP 시동 | `close` | 게시 | hook의 subprocess |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 4×4 (42) | 6.4초 | 1.96초 | 0.97+0.68초 | 0.87초 | 1.0초 | 0.32초 | tmux 37 + claude 1 |
| 4×4 (64) | 8.0초 | 2.19초 | 1.08+0.92초 | 1.07초 | 1.0초 | 0.45초 | tmux 37 + claude 1 |
| 16×16 (78) | 27.2초, `registration_failed` | 6.6초 | 7.25+4.22초 | 2.25초 | 1.02초 | - | tmux 76 + claude 1 |

- `_run`이 `leader`와 모든 seat의 `get_current`를 불러(slot마다 tmux 2번) hook이 run을 두 번 찾았습니다(`register_from_hook`과 `_register`). 4×4에서 tmux 37번, 16×16에서 76번이고, 16×16에서는 이 두 호출이 11.5초였습니다.
- `MCPClient.close`가 입력을 닫은 뒤 종료를 1초 기다립니다. 실제 `claude mcp serve`를 3번 확인했을 때 2번은 입력이 닫혀도 5초 뒤까지 계속 실행했습니다(1번은 0.26초 만에 종료). 그래서 이 1초는 대개 낭비입니다.
- hook의 25초 deadline은 hook이 import를 마친 뒤부터 쟀습니다. Claude의 30초 제한은 process 시작부터 세므로, 부하로 interpreter 시동에 6.6초가 걸리면 hook이 자기 실패를 기록하기 전에 죽을 수 있습니다(그러면 `start`는 600초를 기다림).
- 그 밖에 slot·project 수에 비례하는 일: 등록 파일 읽기는 16×16 규모에서 0.05~0.08초라 무시할 수 있습니다.
- 진짜 `claude mcp serve`의 시동(initialize)은 load 약 75에서 7.8~8.2초, 다른 한 번은 31.8초였습니다(측정 중 host load가 321까지 올랐습니다). 이 시간은 이 저장소가 줄일 수 없습니다(아래 제안).

### 변경 (`tools/agent-session`, `docs/project-team/spec.md`)
1. `Tmux.current_with_run`: 한 번의 tmux 읽기로 모든 slot의 포인터를 읽고 이 run_id를 가리키는 slot의 window만 읽습니다. `_run`은 tmux 2번이고 seat 수와 무관합니다. `register_from_hook`이 찾은 run을 `_register(resolved=)`에 넘겨 두 번째 `_run`을 없앴습니다.
2. `hook_started`(새 module): SessionStart hook이 binding 확인 전에 `agent/runs/<run_id>/hook-started.json`(PID·birth)을 씁니다. `start`의 대기 루프가 그 hook process의 종료를 보고, run이 `ready`도 `start_error`도 아니면 window를 한 번 더 읽은 뒤 `registration_failed`(`hook_error.code = registration_hook_ended`)로 끝냅니다. 새 tmux option·state 필드·JSON 필드는 없습니다(run 디렉터리 파일은 `ended.json`과 같은 종류의 진단 기록). 형식 버전은 올리지 않습니다.
3. hook deadline을 hook process의 생성 시각부터 셉니다(`process.age`, 시동에 쓴 시간은 최대 10초까지만 뺍니다).
4. (MCP `close`의 1초 대기: 이 CR은 binding 확인만 대기를 없앴으나, SESSION-012가 `MCPClient.EXIT_GRACE = 0.1`로 모든 close의 대기를 줄여 merge에서 그쪽을 채택하고 이 CR의 per-call grace 코드·test·명세 문구를 뺐습니다. Claude CLI와의 계약은 그대로입니다.)
5. 동작 명세의 해당 절(등록 deadline, `start_error`와 hook 종료 판정, run 디렉터리, MCP 종료)을 고쳤습니다.

### 검증
- 제출 commit `3cb1440`(merge commit)에서 실행한 명령:
  - `python -m pytest -q -n 8 tools/agent-session/tests` → **833 passed** (17분). README 표의 `tools/agent-session/**` 행입니다.
  - `python -m pytest -q integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py` → **130 passed**. PERF-003이 launcher·bin 진입점을 바꿔 `tools/python-launcher.sh` 행에 해당합니다.
- 근거 재사용: `install/tests`는 PERF-003 merge(`19f3c22`)에서 276 passed, 2 skipped였습니다. SESSION-012 merge는 `install/`·launcher를 바꾸지 않아 재실행하지 않았습니다. `api.py`·`state.py`·tmux option 이름은 바꾸지 않아 project-item·project-board test는 실행하지 않았습니다. 문서(`spec.md`)의 상대 link 검사는 이상 없었습니다.
- `19f3c22`에서 agent-session test 2개가 실패했으나(`test_suspend.py::test_a_failed_lost_resume_keeps_its_evidence_and_start_takes_over`, `test_git_ops.py::test_timed_out_git_releases_its_lock_and_reports_the_interruption`; host load 100 이상에서 39분 동안 돌린 실행) 단독 재실행과 두 파일 전체 재실행(79 passed)에서 통과했고, `3cb1440`의 전체 실행에서도 통과했습니다. 부하로 시간이 어긋난 실패로 판단합니다.
- 새 test (Verification 3·4):
  - `test_start_reports_a_hook_that_ended_without_a_result_before_its_timeout`(hook을 SIGKILL로 죽임, `registration_failed`, 120초 timeout 안에 끝나고 60초 미만). **감지 조건을 끄면 실패합니다**(120초 뒤 `timeout`, 확인함). 재실행한 start가 같은 오류를 바로 반환함도 확인합니다.
  - `test_a_hook_that_ends_after_it_published_is_not_a_failed_registration`(hook이 게시하고 끝나는 경합).
  - `test_finding_the_run_of_a_hook_starts_two_tmux_processes_whatever_the_seats`(seat 2·6·16 모두 tmux ≤ 2; 수정 전은 2×(seat+1)). `test_a_registration_starts_the_same_tmux_processes_whatever_the_seats`(찾기·binding·게시 전체가 seat 2·6·16 모두 tmux 10번).
  - `current_with_run`의 판정, hook 시작 기록·종료 판정, deadline, `process.age` test.

### A/B 측정 (Verification 1·2, 새 측정 도구 9d746d8)
`perf_bench.py run --exe v040=<v0.4.0 트리> --exe cand=<이 checkout> --scales 4x4,16x16 --groups lifecycle --reps 3 --slow-reps 3 --cold-reps 0`. 가짜 `claude`. host load는 4×4에서 38~127, 16×16에서 45~80이었습니다(같은 host의 다른 작업 때문에 높음). 값은 median [95% 구간]이고 판정은 도구의 improved/same/worse입니다.

| 규모 | start (Worker) wall 초 | start CPU 초 | start tmux(count) | hook의 tmux(count) |
| --- | --- | --- | --- | --- |
| 4×4 | 50.1 [40.3-66.8] → 42.8 [36.7-57.8] (same) | 3.59 → 2.96 (**improved**) | 198 → 118.5 | 54 → 20 |
| 16×16 | 41.4 [35.6-49.0] → 29.5 [24.5-38.1] (**improved**, 0.71) | 4.75 → 3.43 (**improved**, 0.72) | - | 117 → 11(count pass가 실패해 부분 값) |

- 4×4에서 restart·send·stop의 CPU도 모두 improved(0.76~0.89배)입니다.
- **16×16에서 시작 실패**: v0.4.0은 start 시도 중 2번이 `registration_failed`("Claude MCP did not reply before the deadline")였습니다(load 65 count pass, load 79.6 timing pass). 후보는 timing pass 6번이 모두 성공했고(load 45~71, 그중 load 70.8에서도 성공), 실패는 count pass(tmux·git·ps shim을 PATH에 둬 느림) 1번(load 80)뿐입니다. 한도에 닿는 일이 사라진 것은 아닙니다(아래).
- 16×16의 restart·send·stop·finish_ended는 v0.4.0의 start 실패로 일부 반복이 빠져 비교 구간이 없습니다(표본 2/3). 비교 가능한 행은 위 start뿐입니다.
- 측정 환경이 없어졌으므로 hook 단계 시간(hooks.log)은 최종 비교에 없습니다. 위 "원인" 표는 수정 전 단계 시간입니다. 수정 후의 hook 시간은 직접 재지 못했습니다(16×16 환경 구축이 15분 걸림). 수정 후 hook의 tmux 수와 단계 비용은 호출 수 test와 4×4의 hook tmux 54→20으로 갈음합니다.

### 한도 조정 제안 (5단계, Leader 판단 필요)
1~4로 hook의 일은 줄었지만, 한도에 닿지 않는다고는 증명하지 못했습니다. 근거: (1) 후보도 load 80 count pass에서 MCP 응답을 기다리다 25초 deadline(binding은 deadline−6초까지)에 걸렸습니다. (2) 진짜 `claude mcp serve`의 시동만 load 약 75에서 8초, 최악 31.8초였습니다. 그래서 hook의 settings timeout(30초)과 `_HOOK_BUDGET`(25초)을 올리는 방안을 제안합니다. 예: timeout 60초, budget 50초(`_PUBLISH_RESERVE` 6초·`_BINDING_TIMEOUT` 20초도 함께 검토). 이 조정은 spec·settings·hook timeout test를 함께 바꾸는 변경이라 이 제출에는 넣지 않았습니다. 한도만 늘리는 것은 해법이 아니므로 위 1~4를 먼저 제출합니다.
- 되풀이 확인에서 MCP client를 다시 띄우지 않는 개선(3단계 예시)은 하지 않았습니다. 수정 전 측정에서 재시도가 발생한 근거가 없었고(ListAgents가 pane을 못 찾는 경우만 반복), provider 인터페이스를 바꾸는 일이라 근거 없이 넣지 않았습니다.

### 근거 재사용·재실행
- SESSION-012 merge에서 `providers/mcp.py`가 한 곳 충돌했습니다(close 대기: 이 CR의 per-call `grace` 대 SESSION-012의 `EXIT_GRACE = 0.1`). SESSION-012를 채택했고, 이 CR의 `providers/` 변경과 그 test·명세 문구는 없어졌습니다. `providers/`는 `origin/main`과 같습니다.
- A/B(위 표)는 merge 전 후보 `cfb0da4`로 쟀고, Leader 지시로 다시 재지 않았습니다. 그 사이 후보에서 바뀐 것은 close 대기뿐입니다(per-call grace 0초 → 전역 0.1초). 이 CR의 핵심 효과(`_run`의 tmux 수, hook 종료 감지, deadline)는 `3cb1440`에서도 위 test가 확인합니다.
