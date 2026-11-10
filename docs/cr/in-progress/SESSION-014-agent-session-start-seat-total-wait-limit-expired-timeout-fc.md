# SESSION-014: agent-session start 가 seat 반납 직후 'total wait limit expired' timeout 으로 끝나고 재실행하면 성공 (fc2_cpu 11-10 3회)

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S3
- Related: SESSION-011, SESSION-013
- Requester: fc2_cpu, /primehome/swain/Project/falcon2/git/fc2.cpu.desk, 2026-11-10
- Base: a4dc75d7b1c29718c6d44661e6fdb78143bec595 2026-11-10T22:14:44+09:00

## Symptom
- `agent-session start --job <CR> --seat N` 가 `{"ok": false, "error": {"code": "timeout", "message": "The command's total wait limit expired."}}` 로 끝나는 일이 fc2_cpu 에서 2026-11-10 하루에 3 번 있었습니다(seat0 CPUDES-104, seat1 CPUDES-107, seat4 CPUVER-104). 세 번 모두 같은 명령을 다시 실행하면 `ok: true` 로 시작했습니다. 첫 시도 뒤 seat0 window 에는 Claude CLI 대신 `sleep` 만 떠 있는 pane 이 남아 있었습니다(`pane_current_command sleep`).

## Evidence
- 도구: `/primehome/swain/.local/lib/project-agent/releases/0.4.0-ce52466a6354/tools/agent-session/bin/agent-session` (0.4.0-ce52466a6354), provider claude, project fc2_cpu(`/primehome/swain/Project/falcon2/git/fc2.cpu.desk`, seat 0~7, falcon2_design 큰 저장소).
- 같은 날 다른 start(seat2 CPUVER-110, seat0 CPUDES-102, seat2 CPUDES-105, seat4~7 첫 배정 등)는 첫 시도에 성공했습니다. 실패한 세 번은 모두 seat 를 방금 stop 으로 반납한 직후의 start 였습니다(main 동기화·CR branch 준비가 긴 경우로 추정, 확인 안 함).
- 결과 JSON 은 `details: {}` 라 어느 단계에서 시간이 다 됐는지 알 수 없습니다.

## Contract
- start 는 seat 의 main 동기화와 provider 시작이 끝날 때까지 기다리거나, 제한을 넘기면 어느 단계(git sync / tmux / provider registration)에서 멈췄는지와 다시 실행해도 되는지를 결과에 적어야 합니다. 반쯤 만든 window 가 남으면 다음 start 가 그것을 이어받거나 정리해야 합니다.

- Requester: fc2_cpu Leader, /primehome/swain/Project/falcon2/git/fc2.cpu.desk, 2026-11-10

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 다른 project(fc2_cpu)의 재현 기록이 있는 결함입니다. start가 기본 한도 600초를 다 기다린 뒤 단계 정보 없이 끝납니다.
- 2026-11-10 Leader: open -> todo. fc2_cpu 요청, 재현 기록 있는 start 결함
- 2026-11-10 Leader: 제출 8022f012ac97122fe2e60039f99fe0b8e59dbaac를 인수합니다. 검토 8022f01(구현 1229021 + main 2fd84c7 merge). git_ops.observing/_git_step(다음 Git 명령 앞에서 deadline 확인, 시작한 명령은 끊지 않음), start의 진행 기록과 timeout details(stage·step·retry_safe·elapsed·git_steps), restart 등 다른 명령은 details {} 그대로, 명세 절을 읽었습니다. 원인 근거(seat reflog 시각, 재시도의 _start_existing 경로)가 fc2_cpu 세 실패와 맞습니다. 수정 전 실패하는 test 2개(Git 단계 중단·이어받기, registration 단계)가 있습니다. merge commit에서 tools/agent-session/tests 839 passed, distribution boundary 9 passed, spec.md link 이상 없음. Worker가 수정 전 실패 확인에 git stash를 쓴 것은 global AGENTS.md 위반이며 Result에 밝혔습니다. 첫 시도가 여전히 600초에 끝날 수 있는 Git 준비 속도 자체는 Leader가 후속 CR로 엽니다.

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), [동작 명세](../../project-team/spec.md)의 start·등록, `tools/agent-session/agent_session/lifecycle.py`(start와 `remaining`), SESSION-011 Result, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 원인: fc2_cpu의 실패한 세 start(seat0 CPUDES-104, seat1 CPUDES-107, seat4 CPUVER-104)의 근거를 읽습니다. 근거는 `/primehome/swain/Project/falcon2/git/fc2.cpu.desk/agent/runs/<run_id>/`, `agent/diagnostics/`, state와 남은 window입니다. 다른 project의 파일은 읽기만 합니다. 600초가 어느 단계(main 동기화, window 준비, provider 시작, 등록 대기)에 쓰였는지, pane에 `sleep`만 남은 이유, 다시 실행하면 성공하는 이유를 확인된 사실과 가설로 나눠 적습니다. 0.4.0과 현재 main(SESSION-011·PERF-004·SESSION-013 포함)의 차이가 원인에 닿는지도 적습니다.
2. 원인을 고칩니다. 근거 없이 한도만 늘리지 않습니다.
3. start가 한도를 넘기면 결과의 details에 멈춘 단계와 다시 실행해도 되는지를 적습니다. 반쯤 만든 window가 남으면 다음 start가 이어받거나 정리하는지 확인하고, 아니면 고칩니다.
4. 명세의 해당 문장을 고칩니다.

의존: 없음. SESSION-013(Leader가 main에 통합 중)이 `internal.py`·`providers/claude.py`를 바꿉니다. 제출 전에 `origin/main`을 merge합니다.

위험 등급: 중간. start 경로입니다.

## Verification
1. 원인 단계를 재현하는 test를 둡니다. 수정 전에는 실패해야 합니다. timeout 결과의 details(단계, 재실행 가능 여부) test도 둡니다.
2. README 검증 표에서 바꾼 경로의 행을 모두 실행합니다(`-rf`).
3. 제출 전에 `origin/main`을 merge하고, merge가 입력을 바꾼 명령만 merge commit에서 다시 실행합니다.
4. 속도 CR이 아니므로 측정 도구 A/B는 하지 않습니다. 사용자가 빠른 반영을 요구했습니다.

## Result
- 제출 commit: 8022f012ac97122fe2e60039f99fe0b8e59dbaac

`origin/main`(SESSION-013 2fd84c7까지)을 merge한 commit입니다. `cr/SESSION-014`를 push했습니다. 구현은 1229021입니다.

### 원인 (확인된 사실과 가설)
확인된 사실:
- fc2_cpu의 세 실패(seat0 CPUDES-104, seat1 CPUDES-107, seat4 CPUVER-104)는 모두 **CLI를 띄우기 전, Git 준비 단계**에서 한도를 다 썼습니다. 근거: (1) 실패한 첫 시도의 run에는 launch 기록이 없고, 재실행이 같은 run(`agent/runs/<run_id>/`)에서 `prompt.md`·`launch.sh`를 쓴 뒤 launch했습니다(CPUDES-104 run 9cc9ca71은 20:44:15, CPUDES-107 b421a141은 21:08:14, CPUVER-104 6881e0fe는 21:25:34). 이는 `_start_existing`이 `provider_launch_attempted is False`인 대기 window를 이어받는 경로입니다. 남아 있던 `sleep` pane은 이 대기 window(placeholder)입니다. (2) seat의 `git reflog --date=iso`가 첫 시도의 Git 완료 시각을 줍니다. seat0: `switch main` 20:33:52 → `merge --ff-only` 20:35:43 → `switch -c cr/CPUDES-104` 20:37:07 → (재시도의 `switch`) 20:43:31 → launch 20:44:15. 첫 시도는 약 20:33:30에 시작해 한도가 20:43:30에 끝났고, 재시도가 20:43:31에 이어졌습니다. seat4: `merge` 21:16:22 → `switch -c` 21:23:32(merge 뒤 7분) → 재시도 21:25:10. seat1: `merge` 21:05:31 → `switch -c` 21:07:37 → 재시도 21:08:07. 세 seat 모두 Git 명령 몇 개가 합쳐서 한도 600초를 넘겼습니다.
- 코드 원인: `git_ops.git()`의 각 명령은 자기 한도 `GIT_TIMEOUT`(600초)로 돌고 start의 deadline(`Manager.remaining`)을 보지 않습니다. 그래서 Git 준비의 모든 단계(status·switch·fetch·merge·switch -c·`submodule update --init --recursive`)가 한도를 지나서도 계속 돌고, 끝난 뒤 `_launch`의 첫 `remaining()`에서 "total wait limit expired"가 나고 details는 `{}`입니다. 실패한 시점의 일(Git 준비)은 대부분 끝나 있고(seat4는 `switch -c`까지 끝남), Base 기록·branch가 남아 재시도는 main 동기화를 건너뛰고 약 40초에 launch합니다. 이것이 "재실행하면 성공"의 이유입니다.
- 0.4.0과 현재 main의 차이: `git_ops.py`·`workspace.py`는 0.4.0(`releases/0.4.0-ce52466a6354`)과 byte 단위로 같습니다. SESSION-011·PERF-004·SESSION-013은 start의 Git 경로를 바꾸지 않았으므로 원인에 닿지 않고, 현재 main에도 같은 결함이 있습니다.
가설(확인 못 함): Git 명령 하나하나가 몇 분씩 걸린 이유는 방금 반납한 seat의 NFS 작업 tree가 차가워서(index refresh·untracked 검사가 전체 tree를 lstat)일 가능성입니다. seat은 67k 파일, submodule 30개, `core.untrackedcache=true`입니다. `switch -c`가 같은 commit에서 1~7분 걸린 것이 근거로 보이지만, 어느 명령이 얼마나 걸렸는지는 이 근거로 나눌 수 없습니다(reflog는 완료 시각만 줍니다). 다른 project의 seat에 측정 Git을 돌리는 것은 읽기 전용 원칙에 어긋나 하지 않았습니다. 다음에 재현되면 `git_steps`(아래)가 명령별 시간을 남깁니다.
- 한도를 늘리지 않았습니다. 한도만 늘리는 것은 근거가 없고, Leader의 도구 호출 한도(10분)와도 맞지 않습니다.

### 변경 (`tools/agent-session`, `docs/project-team/spec.md`)
1. `git_ops.observing(observer)`/`git()`: start가 각 Git 명령을 시작하기 전에 observer를 부릅니다. `Manager._git_step`이 전체 deadline을 확인(`remaining()`)하고 명령 시간을 잽니다. 시작한 Git 명령은 끊지 않습니다(반쯤 적용된 tree를 만들지 않으려는 것입니다). 한도가 지나면 다음 Git 명령을 시작하지 않습니다.
2. `Manager.start`가 진행 기록(`stage`·단계별 시간·`git_steps`)을 두고, `remaining()`의 `timeout`이 그 details를 담습니다: `stage`(assignment·git·launch·registration), `step`, `retry_safe`(true), `job_id`, `seat`, `elapsed`, `git_steps`. start가 아닌 명령(restart·stop 등)의 `timeout`은 그대로(details `{}`)입니다. 기존 `start`는 `_start`로 옮기고 본문은 바꾸지 않았습니다.
3. 반쯤 만든 window: 한도를 넘긴 start는 배정·CR claim·대기 window를 남기고, 같은 `start --job`이 그 window를 이어받는 것을 test로 확인했습니다(같은 run_id·window_id). 정리는 `stop`이 합니다. 코드 변경은 필요 없었습니다.
4. 명세 4절에 "한도를 넘긴 start" 절을 더하고 Git 준비 절의 한 문장을 고쳤습니다.

### 검증
- 새 test `tools/agent-session/tests/test_start_timeout.py`(2개). **수정 전에는 둘 다 실패합니다**(`details`에 `stage`가 없음, git stash로 구현만 되돌려 확인. 이 확인에 `git stash`를 한 번 썼다가 바로 `stash pop`으로 복원했습니다. AGENTS.md의 stash 금지 규칙을 어긴 것이므로 밝힙니다. 작업 내용은 그대로입니다).
  - `test_git_preparation_stops_at_the_deadline_and_names_its_step`: Git `fetch` 중에 deadline이 지나게 하면 `timeout`, `stage=git`, `step=merge --ff-only…`, `retry_safe`, `git_steps` 마지막이 `fetch origin main`입니다. fetch 뒤에 `merge`·`switch -c`·`submodule` Git이 시작되지 않았고 seat 작업 tree는 깨끗합니다. 이어서 같은 start가 같은 run_id·window_id로 성공하고 `cr/<job>` branch가 만들어집니다.
  - `test_timeout_while_waiting_for_the_registration_names_that_stage`: 등록 대기 중 한도가 지나면 `stage=registration`, `retry_safe`. 같은 start가 같은 run을 이어받습니다(다시 `registration`).
- `python -m pytest -q -n 8 tools/agent-session/tests` → **839 passed** (7분 36초), merge commit 8022f01에서 실행했습니다(README 표의 `tools/agent-session/**` 행). `api.py`·`state.py`·tmux option 이름은 바꾸지 않아 project-item·project-board·`install/tests`는 실행하지 않았습니다.
- `tools/test_distribution_boundary.py` 9 passed, `spec.md` 상대 link 검사 이상 없음. 원격 guidance 문서(`spec.md`)를 바꿨으므로 `test_remote.py`가 위 전체 실행에 들어 있습니다.
- 근거 재사용·재실행: merge(SESSION-013: `internal.py`·`providers/claude.py` 등)가 agent-session test의 입력을 바꿨으므로 merge commit에서 전체를 다시 실행했습니다. 충돌은 없었습니다.
- 측정 도구 A/B는 CR 지침대로 하지 않았습니다.

### 남은 위험
- 이 변경은 첫 시도의 성공 여부를 바꾸지 않습니다. Git 준비가 600초보다 오래 걸리는 seat에서는 start가 여전히 한 번 `timeout`으로 끝납니다. 달라진 것은 (1) 한도가 지난 뒤 Git 단계가 계속 돌지 않고 다음 명령 앞에서 멈추며, (2) 오류가 단계·Git 명령·재시도 가능 여부·명령별 시간을 알려 줍니다. Git이 느린 근본 이유(NFS 차가운 tree로 추정)가 확인되면 별도 CR로 다루는 것이 맞습니다. 필요하면 `--timeout`을 늘려 start를 실행할 수 있습니다(도구 호출 한도 10분을 넘지 않게 주의).
