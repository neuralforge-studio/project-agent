# PERF-005: 큰 저장소 seat에서 start의 Git 준비가 명령마다 1~7분 걸려 첫 start가 한도 600초를 다 씁니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Related: SESSION-014

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
