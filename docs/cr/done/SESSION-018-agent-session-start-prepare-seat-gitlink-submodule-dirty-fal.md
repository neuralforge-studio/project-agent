# SESSION-018: agent-session start: 중단된 prepare 가 seat 를 되돌리지 않고, gitlink 만 다른 submodule 을 dirty 로 봐 재시작·반납이 막힘(falcon2 seat1, 0.11.0)

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S2
- Requester: falcon2, /primehome/swain/Project/falcon2/git/fc2.base, 2026-11-12
- Base: baa8258c505ecd336283bd717da5a5b4108a23d7 2026-11-12T15:30:08+09:00
- Outcome: fixed

## Symptom
- falcon2 `agent-session start --job MCUDES-014`(PATH `~/.local/bin/agent-session`, release 0.11.0-fc4ce6b9d115, 2026-11-12 13:2x KST)가 seat1 에서 `timeout` 으로 끝났습니다(출력 `{"ok": false, ... "code": "timeout"}`). 이때 seat1 HEAD 는 `main`(ce64071d3b)에서 새 base `1488536ad7`(detached)로 바뀐 채 남았습니다.
- 두 결함:
  1. 중단된 prepare 가 seat 를 되돌리지 않습니다. 같은 `start` 를 다시 실행하니 `workspace_dirty` "Keep existing changes before preparing main." 로 거절됐고, `agent-session stop --job MCUDES-014` 도 reasons `['the CR is still in-progress ...', 'seat has uncommitted or untracked files']` 로 반납하지 못했습니다. 다른 seat 로 `start --seat 3` 은 `assignment_mismatch` 였습니다. 결과적으로 Leader 가 seat 를 손으로 고치기 전에는 진행할 수 없었습니다.
  2. gitlink 만 다른 submodule 을 dirty 로 봅니다. seat1 의 변경은 `git status --porcelain` 27 건 모두 submodule gitlink 차이(`*/lec` 13, `*/syn` 14)였고 submodule 안 content 변경은 0 이었습니다(예 `01.design/02.cpu_blk/00.cpu_blk/syn`: superproject `d0839c4330` ↔ submodule HEAD `dc8aa1e681`, `git status --porcelain` 0 줄). `submodule.recurse=false` 로 base 를 checkout 하면 gitlink 가 바뀐 submodule 은 항상 이렇게 됩니다.

## Evidence
- Requester: falcon2 Leader, /primehome/swain/Project/falcon2/git/fc2.base, 2026-11-12. agent Leader 지시로 project-agent 에 직접 요청합니다.
- seat1 reflog(`git -C /primehome/swain/Project/falcon2/git/fc2.seat1 reflog`): `1488536ad7 checkout: moving from main to 1488536ad74b...`(timeout 난 start), 그 앞 `ce64071d3b checkout: moving from cr/CHIPVER-008 to ce64071d3b...`.
- 우회: Leader 가 `git -C <seat1> -c submodule.recurse=false checkout main`(reflog 의 직전 상태)으로 되돌려 dirty 0 을 확인한 뒤 `start --job MCUDES-014 --timeout 600` 을 다시 실행했습니다.
- state.json 당시: `"1": {"job_id": "MCUDES-014", "git_hash": null, "session": null}`.

### 추가 증상(2026-11-12 falcon2 Leader 보고, Leader 확인)
- seat를 main으로 되돌린 뒤 `start --job MCUDES-014 --timeout 600`은 준비까지 성공했습니다(CR Base `a3049d9f81`, state seat1 `git_hash` 기록). 그러나 Worker 연결에서 `target_changed: The waiting pane process no longer matches this run.`으로 실패했고, 다시 실행해도 같습니다. state seat1의 `session`은 null입니다.
- Leader가 읽기만 하며 확인한 사실:
  - 현재 run `68936e5dc11640d78c39718965e8053f`의 window `falcon2-seat1-MCUDES-014-exited-68936e5d`(@942)는 pane이 dead이고(`Pane is dead (signal 15, Thu Nov 12 13:45:09 2026)`), `@agent_session_provider_launch_attempted false`입니다. provider를 띄우기 전에 대기 process(placeholder pid 4120311)가 SIGTERM으로 죽었습니다. `finish-result.json`(13:45:16)은 `lock_timeout`이고, `launch.sh`는 14:14:18에 다시 쓰였습니다(같은 run의 재시도).
  - 코드(0.11.0과 main): `Manager._start_existing`은 `provider_launch_attempted`가 False인 run을 같은 run으로 다시 준비하고 `Tmux.launch`로 갑니다. `Tmux.launch`는 대기 process가 죽었으면 `target_changed`를 냅니다. 죽은 run을 새 run으로 바꾸는 조건 `_unregistered_ended`는 `provider_launch_attempted`가 False가 아닌 run에만 적용됩니다. 그래서 provider를 띄우기 전에 대기 process가 죽은 run은 start를 몇 번 다시 해도 같은 실패를 반복합니다.
  - 누가 대기 process에 SIGTERM을 보냈는지는 확인하지 않았습니다.
  - 같은 seat1의 이전 window(DCPUSAN-005, @933)는 Board sidebar pane(0.10.0 Python)만 남아 이름이 `python3`입니다.
- falcon2 Leader는 복구 방법을 알 때까지 MCUDES-014를 멈춰 둡니다. 이 CR의 첫 일은 현재 release에서 falcon2 seat1을 안전하게 복구하는 방법을 확인해 Result에 적는 것입니다(Leader가 falcon2에 전달). 실제 falcon2 seat·state·tmux는 건드리지 않고 격리 환경에서 확인합니다.

## Contract
- (1) prepare 가 중간에 끊기면 seat 를 시작 전 HEAD/branch 로 되돌리거나, 다시 실행한 start 가 자기 prepare 의 흔적을 이어받아 끝내도록 합니다. 배정만 남고 session 이 없는 seat 를 stop 으로 반납할 수 있어야 합니다.
- (2) dirty 판정에서 gitlink 만 다른 submodule(submodule 안 content 변경 0)은 사용자 변경으로 보지 않습니다(또는 prepare 가 그 상태를 정상으로 다룹니다).
- 재현 조건과 검증은 project-agent 판단에 맡깁니다.

## Disposition
- 2026-11-12 Leader 판정: 구현한다. 재현 근거가 있는 결함입니다(falcon2 seat1 reflog, state의 `git_hash: null`·`session: null`). 다른 project(falcon2)가 요청했습니다.
  - 판단 기준은 사용자 지시 "판단의 주요관점은 ** Root cause & SSOT **"입니다.
  - Leader가 본 원인(확인할 것): [동작 명세](../../project-team/spec.md) "Start의 Git 준비"는 마지막에 `git submodule update --init --recursive`(timeout 600초)로 submodule을 HEAD의 gitlink에 맞춥니다. 요청서의 두 증상은 한 원인으로 보입니다. prepare가 base checkout 뒤, submodule 맞춤 전에 끊겼습니다(start `timeout`). 그 결과 seat는 base로 옮겨졌지만 submodule은 옛 commit이었고, 다시 실행한 start의 dirty 검사는 자기 prepare의 흔적(gitlink만 다름)을 사용자 변경으로 보고 거절했습니다.
  - 따라서 "gitlink만 다른 submodule을 무조건 무시"는 근본 수정이 아닐 수 있습니다. seat가 base에 맞는지(submodule 포함)의 정의와, prepare가 중단에서 이어지거나 되돌아가는 규칙을 한 곳에서 정해야 합니다.
  - seat 4개가 모두 차 있습니다. 먼저 비는 seat에서 시작합니다(BOARD-028보다 먼저. falcon2가 막혀 있습니다).
- 2026-11-12 Leader: open -> todo.
- 2026-11-12 Leader 검토(제출 06744b36141b557d4ee0597f465c4cf89e5aab9a): 수정 요청(merge만).
  - 설계와 구현은 그대로 둡니다. "seat에 변경이 있다"의 판정은 `git_ops.dirty` 한 곳입니다(준비의 clean 확인, 배정·반납 검사가 함께 씀). 준비 시작 때의 표지 ref `refs/agent-session/aligned`로, 끊긴 준비의 흔적(안쪽 변경 없이 표지 commit의 gitlink에 있는 submodule)과 사람의 변경을 구분합니다. 마지막 `submodule update` 뒤에 표지를 지웁니다. 대기 process가 죽은 run은 `_waiting_ended` 한 곳에서 판정하고 `_replace_waiting`으로 새 run으로 바꿉니다. 명세 4절에 "seat의 변경" 절이 있고, 수동 복구 3항도 고쳤습니다.
  - 요청: TEAM-003이 통합되어(9ad637a) `origin/main`과 `tools/agent-session/agent_session/git_ops.py`(`prepare`: `prune_integrated`와 `_finish`), `docs/project-team/spec.md`(Git 준비 문단)가 충돌합니다. merge해서 두 변경을 모두 살리십시오. `prune_integrated`가 지우는 local `cr/*`가 표지나 끊긴 준비의 재개와 부딪치지 않는지 확인하십시오. merge가 agent-session의 입력을 바꾸므로 `python -m pytest -q -n 8 tools/agent-session/tests`를 다시 실행하고 한 번 제출하십시오.
- 2026-11-12 Leader 검토(수정 제출 0a620dfaa8b250cb2c9055adfea70d938f1d4aa4): 인수. 앞 검토(06744b3)의 근거는 재사용합니다. 바뀐 것은 TEAM-003 merge입니다. `prepare`는 `prune_integrated` → `submodule update` → 표지 삭제 순서이고, prune은 `cr/*`와 원격 추적 ref만 지워 표지·재시도와 부딪치지 않습니다(`test_pruning_old_cr_branches_leaves_the_marker_and_the_retry_alone`). 다시 실행한 결과: agent-session 949 passed, `test_distribution_boundary.py` 9 passed. TMUX-004 통합(f4605ad) 뒤의 `origin/main`과는 충돌이 없습니다.
- 2026-11-12 Leader: 제출 0a620dfaa8b250cb2c9055adfea70d938f1d4aa4를 인수합니다.
- 2026-11-12 Leader: in-progress -> done, Outcome fixed. 통합 245a60c (origin/main)

## Implementation
읽을 문서:
- [동작 명세](../../project-team/spec.md)의 로컬 seat 생성, Start의 Git 준비(첫 준비·재시도·재배정), 반납 검사, `workspace_dirty`·`assignment_mismatch`.
- 코드: `tools/agent-session/agent_session/git_ops.py`(준비, `submodule update`), `workspace.py`, lifecycle의 start·stop 반납 검사.
- 증거: falcon2 seat1 reflog(요청서 Evidence). 읽기만 하고 그 저장소는 고치지 않습니다.
- 절차: [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 원인 확인: start의 어느 단계에서 `timeout`이 났는지(전체 start 한도와 `submodule update`의 600초 한도의 관계 포함), 중단 뒤 seat·state가 어떤 상태로 남는지 재현합니다. 확인한 사실과 가설을 Result에 나눠 적습니다.
2. 준비의 원자성: prepare가 중간에 끊겨도 다음 둘 중 하나가 되게 하고, 고른 규칙을 명세에 적습니다.
   - 다시 실행한 start가 자기 준비의 흔적을 알아보고 이어서 끝냅니다(예: 준비 시작 전 HEAD와 목표 base를 기록).
   - 또는 seat를 시작 전 상태로 되돌립니다.
   - 어느 쪽이든 사용자 변경과 자기 흔적을 구분하는 근거가 한 곳에 있어야 합니다.
3. dirty 판정: submodule의 gitlink만 다르고 그 안의 내용 변경이 없는 상태를 어떻게 다룰지 정합니다. 준비가 끝나지 않은 흔적이면 준비가 맞추고, 준비를 마친 seat에서 생긴 gitlink 차이(Worker가 submodule을 옮김)는 사용자 변경입니다. 이 구분을 명세에 적습니다.
4. 반납: 배정만 있고 session이 없는 seat(준비 중 실패)는 stop으로 반납할 수 있어야 합니다. 이때 준비의 흔적만 있고 사용자 변경이 없으면 반납이 막히지 않습니다.
5. Test(관측 동작): 격리 git 원격과 submodule이 있는 fixture로 확인합니다.
   - 준비를 checkout 뒤·submodule 맞춤 전에 끊습니다. 이어서 같은 start가 성공하는지, stop이 반납하는지 봅니다.
   - 준비를 마친 seat에서 사람이 submodule을 옮긴 경우는 여전히 dirty로 거절되는지 봅니다.

위험 등급: 중간(seat Git 준비, 반납 규칙).

## Verification
- README 검증 표에서 바꾼 경로의 행 명령을 모두 제출 commit에서 실행합니다.
  - `tools/agent-session/**`: `python -m pytest -q -n 8 tools/agent-session/tests`.
  - `agent_session/api.py`·state 형식·tmux option 이름을 바꾸면 `python -m pytest -q tools/project-item/tests`, `python -m pytest -q tools/project-board/tests`, `python -m pytest -q -n 8 install/tests`도 실행합니다.
- 문서: 고친 문서의 상대 link 검사, `python -m pytest -q tools/test_distribution_boundary.py`. `docs/project-team/spec.md`를 바꾸면 `python -m pytest -q tools/agent-session/tests/test_remote.py`도 실행합니다.
- 다른 project의 실제 seat는 건드리지 않습니다.

## Result
- 제출 commit: 0a620dfaa8b250cb2c9055adfea70d938f1d4aa4

### 원인 (확인한 사실)
- 준비는 `switch --detach`(`-c submodule.recurse=false`)로 HEAD만 옮기고 submodule은 마지막 `submodule update`에서 맞춥니다. 그 사이에 끊기면(start `timeout`) gitlink가 바뀐 submodule은 옛 commit에 남아 `git status`에 gitlink-only 변경으로 나옵니다. fixture로 재현했습니다(`branch --force` 앞, `submodule update` 앞에서 끊음).
- 그 흔적을 다시 실행한 start(`sync_main`의 clean 확인), `stop`·반납 검사(`_status_reasons`)가 모두 사용자 변경으로 봤습니다. 사용자 변경과 구분할 근거가 어디에도 없었습니다. Leader 판정대로 한 원인입니다.
- 한도 안에서 start가 쓰는 시간: 잠금·seat 검사 → Git 준비의 각 명령 → launch → 등록. 시작한 Git 명령은 한도를 넘겨도 끊지 않습니다(spec 4절). 이 host는 git 명령 하나가 0.5~2초(작은 fixture)~분 단위여서 큰 seat에서는 switch·submodule update가 한도를 씁니다. 실제 falcon2의 단계별 시간은 timeout JSON의 `details.git_steps`·`elapsed`에 있으나 이 세션은 그 출력을 보지 못했습니다(가설: seat1은 switch 직후, seat3은 준비 뒤 launch 전).
- 추가 증상: `Tmux.launch`는 대기 process가 죽었으면 `target_changed`를 내고, `_unregistered_ended`는 `provider_launch_attempted`가 False인 run을 제외했습니다. 0.11.0 시점 코드(baa8258)의 격리 fixture에서 start, stop, CR을 todo로 옮긴 뒤 stop·start 모두 `target_changed`가 반복됐고 stop은 `released:false`였습니다. 명령으로 복구되지 않습니다.

### 고른 규칙 (spec 4절 "seat의 변경", "Git 준비")
- 준비가 시작할 때 표지(seat의 `refs/agent-session/aligned` = submodule이 gitlink에 맞춰 있는 commit)를 없으면 HEAD로 만들고, `submodule update`가 끝나면 지웁니다. 표지가 있으면(이전 준비가 끊김) 바꾸지 않습니다. Git 명령이 하나 늘 뿐 작업 tree를 훑지 않습니다.
- `git_ops.dirty`가 "seat에 변경이 있다"의 한 곳입니다(준비의 clean 확인, 배정 검사, 반납 검사). 표지가 있고, 비staged이며 submodule 안 변경이 없고(`SC..`), 지금 checkout된 commit이 표지 commit의 gitlink와 같으면 변경이 아닙니다.
- 따라서 다시 실행한 start는 자기 흔적을 보고 이어서 끝내고, 준비의 흔적만 있는 seat는 반납 검사가 막지 않습니다. 준비를 마친 seat(표지 없음)에서 사람이 submodule을 옮기면, 준비 중에 사람이 옮기거나 그 안을 고치면 모두 여전히 변경입니다("무조건 무시"하지 않음).
- 대기 process가 죽은 run(pane dead, 기록한 대기 process·process group 없음)은 start가 새 run으로 교체합니다(`lifecycle._waiting_ended`, `_replace_waiting`). Worker는 Git 준비의 재시도 규칙으로 이어서 준비한 뒤 launch합니다. 원격 seat는 대상이 아니고, 종료를 확인하지 못하면(기록 없음) 교체하지 않습니다. Leader의 같은 경우도 포함합니다.

### 검증 (제출 commit 06744b3)
- `python -m pytest -q -n 8 tools/agent-session/tests`: 1 failed, 946 passed. 실패 1건(`test_remote.py::test_launch_response_loss_retries_the_same_run_without_git_preparation`)은 내 변경이 원격 run에서도 `pane_info`를 불러서 생겼고, 원격 run을 건너뛰게 고친 뒤 재실행했습니다.
- 고친 뒤 재실행: `test_remote.py`·`test_remote_lifecycle.py`·`test_start_timeout.py`·`test_lifecycle.py` 192 passed. 나머지 파일은 고치기 전 전체 실행에서 통과했고, 고친 한 줄은 원격 run만 제외하므로 그 파일의 근거를 재사용합니다(전체를 다시 돌리지 않음).
- 새 테스트(관측 동작): `test_git_ops.py` 8개 — 준비를 `branch --force` 앞·`submodule update` 앞에서 끊은 뒤(write·read-only) 같은 준비가 끝까지 가는지, 반납 검사가 막히지 않는지, 준비를 마친 seat와 준비가 끊긴 seat에서 사람이 옮긴 submodule과 안쪽 편집이 여전히 변경인지(`workspace_dirty`). `test_lifecycle.py` 3개 — 죽은 대기 run의 Worker·Leader가 새 run으로 교체돼 ready가 되는지, 살아 있는 대기 run은 같은 run을 이어받는지.
- `python -m pytest -q tools/test_distribution_boundary.py`: 9 passed. `docs/project-team/spec.md`를 고쳐 `test_remote.py`도 실행했습니다(위). 고친 문서의 상대 link 검사: 깨진 link 없음.
- `api.py`·state 형식·tmux option 이름은 바꾸지 않아 project-item·project-board·install 테스트는 실행하지 않았습니다.
- 다른 project의 실제 seat·state·tmux는 읽기만 했고 고치지 않았습니다.

### falcon2 복구 (Leader에게 중간 보고함)
- seat3(대기 process 생존): 같은 `agent-session start --job MCUVER-027 --timeout 1800`이 같은 run을 이어받습니다.
- seat1(대기 process 사망): 0.11.0에서는 명령으로 복구되지 않습니다. 이 제출이 설치되면 같은 `start --job MCUDES-014`가 새 run으로 이어서 끝냅니다. 그 전에는 멈춰 두거나 운영자 수동 절차(spec 7절 10번)입니다. 이 수동 절차는 확인하지 못했습니다.
- 한계: 표지가 없는 seat(이 제출 이전에 끊긴 준비)는 gitlink 차이를 여전히 변경으로 봅니다. 중간에 끊긴 `submodule update`의 중첩 submodule 흔적(`SC..` 밖)도 변경으로 봅니다.

### 수정 제출 (0a620df): origin/main(TEAM-003, 9ad637a) merge
- 충돌 2곳(`git_ops.prepare`, spec 4절 Git 준비 문단)을 두 변경을 모두 살려 풀었습니다. `prepare`는 `prune_integrated` → `submodule update` → 표지 삭제 순서입니다.
- `prune_integrated`는 `cr/*` local branch와 원격 추적 ref만 지우므로 표지(`refs/agent-session/aligned`)와 부딪치지 않습니다. 준비가 prune 뒤에 끊기면 표지가 남고 재시도가 끝납니다. 그 전에 끊겨도 `keep`이 이 JOB의 branch를 지키므로 재시도가 막히지 않습니다. 테스트 `test_pruning_old_cr_branches_leaves_the_marker_and_the_retry_alone`을 더했습니다.
- 검증(merge한 제출 commit): `python -m pytest -q -n 8 tools/agent-session/tests`: 949 passed. `python -m pytest -q tools/test_distribution_boundary.py`: 9 passed(spec을 다시 고쳤고 `test_remote.py`는 전체에 포함).
