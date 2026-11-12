# SESSION-018: agent-session start: 중단된 prepare 가 seat 를 되돌리지 않고, gitlink 만 다른 submodule 을 dirty 로 봐 재시작·반납이 막힘(falcon2 seat1, 0.11.0)

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S2
- Requester: falcon2, /primehome/swain/Project/falcon2/git/fc2.base, 2026-11-12

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

## Contract
- (1) prepare 가 중간에 끊기면 seat 를 시작 전 HEAD/branch 로 되돌리거나, 다시 실행한 start 가 자기 prepare 의 흔적을 이어받아 끝내도록 합니다. 배정만 남고 session 이 없는 seat 를 stop 으로 반납할 수 있어야 합니다.
- (2) dirty 판정에서 gitlink 만 다른 submodule(submodule 안 content 변경 0)은 사용자 변경으로 보지 않습니다(또는 prepare 가 그 상태를 정상으로 다룹니다).
- 재현 조건과 검증은 project-agent 판단에 맡깁니다.

## Disposition
- 2026-11-12 Leader 판정: 구현한다. 재현 근거가 있는 결함입니다(falcon2 seat1 reflog, state의 `git_hash: null`·`session: null`). 다른 project(falcon2)가 요청했습니다.
  - 판단 기준은 사용자 지시 "판단의 주요관점은 ** Root cause & SSOT **"입니다.
  - Leader가 본 원인(확인할 것): [동작 명세](../../project-team/spec.md) "Start의 Git 준비"는 마지막에 `git submodule update --init --recursive`(timeout 600초)로 submodule을 HEAD의 gitlink에 맞춥니다. 요청서의 두 증상은 한 원인으로 보입니다. prepare가 base checkout 뒤, submodule 맞춤 전에 끊겼습니다(start `timeout`). 그 결과 seat는 base로 옮겨졌지만 submodule은 옛 commit이었고, 다시 실행한 start의 dirty 검사는 자기 prepare의 흔적(gitlink만 다름)을 사용자 변경으로 보고 거절했습니다.
  - 따라서 "gitlink만 다른 submodule을 무조건 무시"는 근본 수정이 아닐 수 있습니다. seat가 base에 맞는지(submodule 포함)의 정의와, prepare가 중단에서 이어지거나 되돌아가는 규칙을 한 곳에서 정해야 합니다.
  - seat 4개가 모두 차 있습니다. 먼저 비는 seat에서 시작합니다.
- 2026-11-12 Leader: open -> todo.

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
