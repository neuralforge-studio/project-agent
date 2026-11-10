# PERF-005: 큰 저장소 seat에서 start의 Git 준비가 명령마다 1~7분 걸려 첫 start가 한도 600초를 다 씁니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: SESSION-014
- Base: bacf7491632de23af9f0f905227f7670b1486db1 2026-11-10T22:43:10+09:00

## Symptom
fc2_cpu처럼 큰 저장소의 seat에서는 start의 Git 준비(switch main, fetch, merge --ff-only, switch -c, submodule update)가 명령마다 1~7분 걸립니다. 그래서 seat를 반납한 직후의 start가 기본 한도 600초를 Git 준비에만 다 씁니다. SESSION-014는 한도가 지나면 다음 Git 명령을 멈추고 단계를 알리게 했지만, 첫 시도가 실패하는 일은 그대로입니다.

## Evidence
- SESSION-014 Result: fc2_cpu seat의 `git reflog --date=iso` 완료 시각 기준(2026-11-10)입니다.
  - seat0: `switch main` 20:33:52 → `merge --ff-only` 20:35:43 → `switch -c` 20:37:07
  - seat1: `merge` 21:05:31 → `switch -c` 21:07:37
  - seat4: `merge` 21:16:22 → `switch -c` 21:23:32. 같은 commit에서 branch만 만드는 데 7분이 걸렸습니다.
- seat 규모는 파일 약 67k개, submodule 30개, `core.untrackedcache=true`이고 `/primehome`은 NFS4(`acregmin=60`)입니다.
- `git_ops.py`·`workspace.py`는 0.4.0과 같습니다. 명령마다 index refresh와 untracked 검사로 tree 전체를 lstat하는 것이 원인이라는 가설은 아직 확인하지 않았습니다.
- SESSION-014 뒤로는 start의 timeout details `git_steps`가 명령별 시간을 남깁니다.

## Contract
- start의 Git 준비 결과는 바꾸지 않습니다. 결과는 `origin/main` 기준의 `cr/<CR>` branch, Base 기록, 변경이 남은 tree·lock의 거절 사유, 기록된 commit의 submodule입니다.
- 다른 project의 seat에서는 측정하지 않습니다. 같은 규모의 합성 저장소로 재현합니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 다른 project(fc2_cpu)에서 하루 3번 재현된 start 실패의 남은 원인이며 reflog 시각 근거가 있습니다.
- 2026-11-10 Leader: open -> todo. fc2_cpu start 실패의 남은 원인, reflog 근거
- 2026-11-10 Leader: 제출 63a6663 검토. 원인 측정(훑기 3→1, 자식 git 약 93→1)과 ref 단계의 의미는 확인했습니다. 수정 요청: local main이 없는 seat에서 옛 흐름(`switch main`의 DWIM 생성)과 달리 git_failed로 멈추는 회귀가 있습니다. origin/main에서 main을 만들어 옛 결과와 같게 하고 oracle test를 더합니다.
- 2026-11-10 Leader: 제출 8de0c43add6027717a23abbb5b463413f599f056를 인수합니다. 검토 8de0c43(63a6663 + local main 없는 seat 처리). 첫 제출에서 확인한 원인 측정과 ref 단계의 의미는 재사용합니다. 바뀐 것은 sync_main의 tip 없음 분기(origin/main을 target으로 두고 전환 뒤 branch --track main으로 생성)와 tip==upstream일 때 branch 갱신이 없는 순서뿐이며, 옛 명령열 oracle과 같다는 test(write·read-only)가 수정 전 실패를 확인했습니다. tools/agent-session/tests + distribution boundary 855 passed, 문서는 spec 한 줄과 install-contract line 참조.

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), [동작 명세](../../project-team/spec.md)의 Git 준비와 "한도를 넘긴 start", `tools/agent-session/agent_session/git_ops.py`(`prepare`), `workspace.py`, SESSION-014 Result, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 재현: scratchpad의 NFS 경로(`/primehome`)에 fc2_cpu seat와 같은 규모의 합성 저장소를 만듭니다. 규모는 파일 약 67k개, submodule 30개, `core.untrackedcache=true`, origin과 seat clone입니다. start의 Git 준비가 실행하는 명령을 순서대로 실행해 명령별 시간을 잽니다. 61초 넘게 손대지 않은 뒤(cold, `acregmin=60`)와 바로 다시 실행한 때(warm)를 나눕니다. 어느 명령이 tree 전체를 몇 번 훑는지(index refresh, untracked 검사, submodule별 반복)를 근거와 함께 적습니다.
2. 같은 결과를 내는 더 적은 Git 일로 바꿉니다. 예는 다음과 같습니다. 방법은 Worker가 근거로 정합니다.
   - `switch main`과 `merge --ff-only`, `switch -c`를 `origin/main`에서 바로 만드는 한 번의 전환으로 줄입니다.
   - gitlink가 바뀌지 않았으면 submodule 갱신을 건너뜁니다.
   - 검사용 `status`의 untracked·submodule 검사 범위를 거절 판정에 필요한 만큼으로 줄입니다.
3. 거절 판정의 의미를 유지합니다. 변경이 남은 tree, lock, 다른 branch의 commit, submodule 상태가 대상입니다. 바꾼 판정은 test로 보입니다.
4. 다른 project의 seat에서는 아무것도 실행하지 않습니다.

의존: 없음.

위험 등급: 높음. 모든 Worker start의 Git 경로입니다.

## Verification
1. 합성 저장소 cold에서 수정 전후 start Git 준비의 명령별 시간과 합계를 표로 적습니다. 반복은 3회, host load를 함께 적습니다. 측정 도구 A/B(16×16 lifecycle)는 이 경로를 재지 못하므로 하지 않습니다.
2. 준비 결과가 같다는 test를 둡니다. branch, Base 기록, tree, submodule commit, 거절 사유를 봅니다.
3. README 검증 표에서 바꾼 경로의 행을 모두 실행합니다(`-rf`). 측정과 동시에 돌립니다.
4. 제출 전에 `origin/main`을 merge하고, merge가 입력을 바꾼 명령만 merge commit에서 다시 실행합니다.

## Result
- 제출 commit: 63a66636dd09037f10d261f1ed6f45a6b45a13a7

### 원인 (측정으로 확인)
합성 저장소: tracked 65,031 + submodule 30개(각 120 파일) ≈ 68.6k 파일, `core.untrackedcache=true`, `/primehome`(NFS4 `acregmin=60`). seat는 old CR branch에 있고 origin/main이 5개 파일·gitlink 1개 앞선 상태(반납 직후 start와 같은 모양)입니다.
- `strace -f -c`로 센 명령별 lstat·자식 process 수(저장소 한 번 훑기 = 약 6.8만 lstat):
  | 명령 | lstat | execve(자식 git) |
  | --- | --- | --- |
  | `status --porcelain --untracked-files=all` | 73,919 | 31 (submodule 30개마다 `git status` 자식) |
  | `switch main` / `switch -c` (같은 commit) | 73,937~73,970 | 31 (`show_local_changes`의 submodule 검사) |
  | `status --ignore-submodules=all` | 67,828 | 1 |
  | `switch --quiet --detach` | 67,821 | 1 |
  | `submodule update --init --recursive` | 4,873 | 48 (부모 tree를 훑지 않음) |
  | `submodule status --recursive` | 8,477 | 168 |
- 즉 시작 경로의 `switch main`·`merge`·`switch -c`가 각각 부모 tree 전체를 훑고(lstat 약 7.4만) submodule마다 자식 git을 띄웁니다. 확인된 사실입니다. 가설 일부는 기각: submodule update는 tree를 훑지 않아 느린 원인이 아니고, 건너뛰는 검사(`submodule status`)가 update보다 비쌉니다(15~22 s 대 9~10 s). 그래서 submodule 갱신은 바꾸지 않았습니다.
- fc2_cpu의 "같은 commit에서 branch만 만드는 데 7분"은 `switch -c`가 이 훑기 한 번을 그대로 치르기 때문입니다. `acregmin=60`이라 한 명령이 60초를 넘기면 다음 명령이 속성 cache를 다시 채우므로 명령마다 cold입니다(추정: NFS cache 만료는 이 합성 환경에서 직접 확인하지 않았고, 훑기 횟수와 자식 수만 계측).

### 변경
`git_ops.sync_main`·`_first` (`tools/agent-session/agent_session/git_ops.py`): `switch main` → `fetch` → `merge --ff-only` → `switch -c`(훑기 3번, 자식 git 약 93개)를 `fetch` → ref 확인(`rev-parse`·`merge-base --is-ancestor`) → `switch --quiet --no-overwrite-ignore --detach <기준>`(훑기 1번, 자식 없음) → `branch --force main` → `branch cr/<ID>` + `symbolic-ref HEAD`(ref만)로 바꿉니다. 의미는 그대로입니다: local main은 앞으로만 움직이고(앞서 있으면 그 tip이 Base, 갈라지면 `git_failed`), ignored 파일 덮어쓰기는 이 전환이 거절하며, Base는 branch 만들기 전에 기록합니다. 재시도·재배정 경로(`_resume_branch`)와 check_seat·check_release는 바꾸지 않았습니다. 가정: seat에 local `main`이 있습니다(옛 흐름은 없으면 `switch main`이 origin/main에서 만들었음. clone이 만드는 seat에는 항상 있음). Spec(`docs/project-team/spec.md` Git 준비)와 `install-contract.md`의 명령 목록을 갱신했습니다.

### 측정 (합성 저장소, cold = 65 s 유휴 뒤 첫 실행, 단위 s)
host는 공용(64코어)이라 load가 크게 흔들렸습니다. 같은 실행의 `load`를 적습니다. 실행마다 `reset.sh`로 같은 시작 상태(seat이 old CR branch, main=C0, origin/main=C1)로 되돌렸고 수정 전은 `git archive bacf749`의 사본입니다.
| 실행 | load(1분) | check_seat | prepare(Git 준비) |
| --- | --- | --- | --- |
| 수정 전 cold 1 | 42.4 | 13.6 | 40.1 |
| 수정 후 cold 1 | 23.6 | 11.7 | 8.1 |
| 수정 전 cold 2 | 19.7 | 10.0 | 17.8 |
| 수정 후 cold 2 | 17.0 | 4.3 | 4.6 |
| 수정 전 cold 3 | 9.7 | 5.0 | 8.0 |
| 수정 후 cold 3 | 20.4 | 11.1 | 6.0 |
| 수정 전 warm | 23.8 | 2.3 | 8.0 |
| 수정 후 warm | 22.3 | 2.3 | 5.0 |
cold 1 명령별(수정 전 → 후): status 10.5 → 2.8, `switch main` 9.3 / `merge` 3.4 / `switch -c` 7.4 → 합쳐서 `switch --detach` 1.5, ref 명령들 0.0, submodule update 8.0 → 3.0. 평균 prepare cold 22.0 → 6.2 s. load 변동 때문에 수치 자체보다 훑기 횟수(3 → 1)와 자식 git 수(약 93 → 1)가 신뢰할 근거입니다. `check_seat`(배정 단계 status)와 `status` 두 번, `submodule update`는 그대로이며, submodule 30개의 자식 status가 남은 시간의 대부분입니다. fc2_cpu 실규모는 직접 재지 않았습니다(다른 project seat 실행 금지).

### 검증
- 새 test 4개(`tests/test_git_ops.py`): 옛 명령열(`switch main`·`merge --ff-only`·`switch -c`)을 seat 복사본에서 실행한 결과를 oracle로 삼아 branch·ref·HEAD·status·branch config가 같음(seat이 old branch / main에 있는 두 경우), main이 origin보다 앞선 경우 옛 결과와 같음, 갈라진 main 거절(`git_failed`, HEAD·main 불변, Base·state 기록 없음), 작업 tree 갱신 명령이 `switch` 1번이며 `merge`·`checkout` 없음. 기존 ignored 파일 보존·read-only·재시도·submodule·remote test는 그대로 통과합니다. `test_start_timeout.py`는 deadline 뒤 첫 명령 이름이 바뀌어 기대값(`merge --ff-only` → `rev-parse --verify refs/remotes/origin/main`)과 금지 명령 목록을 고쳤습니다.
- README 표의 `tools/agent-session/**` 행: `python -m pytest -q -n 8 tools/agent-session/tests tools/test_distribution_boundary.py` → 853 passed (6분 29초, 측정과 동시에 실행). `api.py`·`state.py`·tmux option은 바꾸지 않아 다른 도구 test는 해당 없음. 문서 행은 `test_distribution_boundary.py`와 `test_remote.py`(위 실행에 포함)로 확인.
- `origin/main` merge(63a6663): 들어온 변경은 BOARD-013 CR 문서뿐이라 검증 입력이 바뀌지 않아 재실행하지 않았습니다.
- 정리: 합성 저장소와 측정 도구는 scratchpad(`.../scratchpad/perf`)에만 있고 제품 코드·다른 project seat에는 손대지 않았습니다.

### 수정 제출 (Leader 검토 1: local main 없는 seat)
- 제출 commit: 8de0c43add6027717a23abbb5b463413f599f056
- `sync_main`: local main이 없으면 target을 origin/main으로 두고 전환 뒤 `branch --track main refs/remotes/origin/main`으로 만듭니다(옛 `switch main`의 DWIM과 같이 origin을 추적). spec Git 준비 절에 한 줄 추가했고 install-contract의 line 참조를 갱신했습니다.
- test `test_first_preparation_creates_a_missing_local_main_from_origin_as_before`(write·read-only): local main을 지운 seat에서 옛 명령열(oracle)과 branch·ref·HEAD·status·branch config가 같음. 수정 전 코드에서 두 case 모두 실패(`git_failed`)함을 확인한 뒤 고쳤습니다(stash 미사용).
- 검증: `python -m pytest -q -n 8 tools/agent-session/tests tools/test_distribution_boundary.py` → 855 passed. 측정은 다시 하지 않았습니다(명령 수 불변, 정상 경로는 `rev-parse` 하나가 줄어듦).
