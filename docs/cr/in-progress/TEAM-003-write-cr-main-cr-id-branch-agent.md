# TEAM-003: Write CR을 main에 통합한 뒤 cr/<ID> branch를 지우는 단계를 절차와 도구에 넣습니다(agent 요청)

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S3
- Requester: agent, /primehome/swain/Utils/agent/agent.base, 2026-11-12

## Symptom
Write CR을 main에 통합한 뒤 `cr/<ID>` branch를 지우는 단계가 절차와 도구에 없습니다. 그래서 통합을 마친 branch가 원격과 seat에 계속 쌓입니다. Leader가 규칙을 어긴 것이 아니라 절차에 단계가 없는 것입니다.

사용자 지시(2026-11-12, agent Leader 대화 원문): "main에 merge 하고 나면 cr branch는 삭제하도록 절차 문서 업데이트 하고, script에도 반영이 되어야 겠네."

## Evidence
- 절차 확인(release `0.11.0-fc4ce6b9d115`): `skills/project-team/SKILL.md` Leader 7단계는 "통합 → 원격 반영 확인 → done"뿐이고 branch 삭제가 없습니다. `skills/project-item/references/cr.md:165`는 보류할 때 branch를 남긴다는 규칙만 있습니다. `docs/project-team/spec.md`의 `cr/<ID>` 절(543·573-576·599·602행)도 생성·이어받기만 정합니다.
- agent 원격: `git ls-remote --heads origin 'cr/*'` = 55개. 모두 `origin/main`에 포함되어 있습니다(`git branch -r --merged origin/main`).
- 다른 project의 remote-tracking 기준(`git branch -r`, prune하지 않은 값): project-agent 72(merged 72), socsim 73(73), memgen 67(64), balvian 133(130), ipweaver 166(166).
- Seat local `cr/*`: agent.seat0 31, agent.seat1 21, agent.seat2 4, project-agent.seat0 19. 반납한 seat의 HEAD는 다음 start까지 마지막 `cr/<ID>`에 남아 있습니다(예: agent.seat1 HEAD `cr/DIST-004`).

## Contract
- 요청: Write CR을 통합해 done(Outcome fixed)으로 옮길 때 `origin`의 `cr/<ID>`를 지우는 단계를 절차 문서와 도구에 넣어 주십시오. 규칙의 원본은 한 곳에 두고 나머지는 link합니다.
- 지켜야 할 조건:
  - branch tip이 `origin/main`의 조상일 때만 지웁니다. 인수한 hash 뒤에 push된 commit이 있으면 지우지 않고 이유를 알립니다.
  - 보류(in-progress→todo) 중인 CR의 branch는 지금처럼 남깁니다(cr.md:165).
  - 통합하지 않고 닫은 write CR의 branch는 지우지 않습니다.
  - 원격 삭제가 실패해도 통합·done 기록은 그대로 두고, 실패와 다시 지우는 방법을 알립니다.
- Base와 seat의 local `cr/<ID>`가 쌓이지 않게 언제 지울지도 정해 주십시오. Seat에서는 다음 start 전까지 해당 branch에 HEAD가 붙어 있을 수 있습니다.
- 이미 쌓인 branch(위 Evidence)의 일괄 정리는 이 요청에 넣지 않습니다. 되돌리기 어려운 원격 삭제라서 각 project에서 따로 사용자 결정을 받습니다.
- 참고: agent에는 "merge·push·branch 삭제·done을 명령 하나로 하는 통합 script" 결정(agent D-20261112-02)이 사용자 답변을 기다리고 있습니다. 답이 오면 별도 요청으로 보냅니다. 이번 변경이 그 방향과 충돌하지 않게 해 주십시오.
- 형식·명령 위치(`project-item move`, 새 명령 등)·version은 담당 project가 정합니다.

## Disposition
- 2026-11-12 Leader 판정: 구현한다. 사용자 지시입니다(agent Leader 대화 원문, Symptom): "main에 merge 하고 나면 cr branch는 삭제하도록 절차 문서 업데이트 하고, script에도 반영이 되어야 겠네."
  - 지우는 대상은 tip이 `origin/main`의 조상인 branch뿐이므로 commit을 잃지 않습니다.
  - 이미 쌓인 branch의 일괄 삭제는 요청서대로 이 CR에 넣지 않습니다.
  - 판단 기준은 사용자 지시 "판단의 주요관점은 ** Root cause & SSOT **"입니다. 원인은 CR 상태 전이에 branch의 수명이 묶여 있지 않은 것입니다. branch를 만드는 곳(`agent-session start`)과 상태 전이를 하는 곳(`project-item move`)이 이미 있으므로, 수명 규칙은 한 곳에 두고 그 두 도구가 그 규칙을 실행하게 합니다.
  - seat 4개가 모두 차 있습니다. 먼저 비는 seat에서 시작합니다.
- 2026-11-12 Leader: open -> todo.

## Implementation
읽을 문서:
- [CR 계약](../../../skills/project-item/references/cr.md)(상태와 전이, `cr/<ID>` 규칙, 보류).
- [project-team skill](../../../skills/project-team/SKILL.md)의 Leader 6·7단계.
- [동작 명세](../../project-team/spec.md)의 `cr/<ID>` 절(start의 branch 준비, 이어받기)과 반납.
- 코드: `tools/project-item/project_item/`(`move`의 `review_missing` 검사), `tools/agent-session/agent_session/`(start의 branch 준비).
- agent 결정 D-20261112-02(통합 script, 답을 기다림)의 방향. 요청서 Contract의 참고를 봅니다.
- 절차: [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. branch 수명 규칙의 원본을 한 곳에 정합니다. 언제 지우는지(원격, base, seat local), 지우지 않는 경우(보류, 통합하지 않고 닫음, tip이 `origin/main`의 조상이 아님), 실패했을 때를 정합니다. 다른 문서는 그곳을 link합니다.
2. 원격 `cr/<ID>`: Write CR을 done(Outcome fixed)으로 옮기는 도구가, 인수 hash를 확인하는 지금의 검사에 이어서 branch tip이 `origin/main`의 조상이면 원격 branch를 지웁니다.
   - 조상이 아니면 지우지 않고 이유를 출력합니다.
   - 삭제가 실패해도 done 기록은 그대로 두고, 실패와 다시 지우는 명령을 출력합니다.
3. local `cr/<ID>`: seat는 다음 start가 branch를 준비할 때, 통합된 이전 `cr/*`를 지웁니다(HEAD가 붙어 있는 것은 먼저 떼고). base와 remote-tracking ref가 쌓이지 않는 방법도 정합니다(예: fetch의 prune).
4. 나중에 한 명령으로 통합하는 script(agent D-20261112-02)가 생겨도 같은 함수를 부를 수 있게, 삭제는 도구의 한 함수가 합니다.
5. Test(관측 동작): 격리 git 원격에서 확인합니다.
   - 통합된 branch는 done 이동 때 원격에서 사라집니다.
   - 인수 뒤 push된 commit이 있는 branch는 남고, 이유가 출력됩니다.
   - 보류한 CR과 통합하지 않고 닫은 CR의 branch는 남습니다.
   - 원격 삭제가 실패해도 done 기록은 남고 안내가 출력됩니다.
   - 다음 start가 seat의 통합된 `cr/*`를 지웁니다.

위험 등급: 중간(원격 branch 삭제, 두 도구의 경계).

## Verification
- README 검증 표에서 바꾼 경로의 행 명령을 모두 제출 commit에서 실행합니다.
  - `tools/project-item/**`: `python -m pytest -q tools/project-item/tests`, `python -m pytest -q tools/agent-session/tests/test_api_boundary.py`. `project_item/api.py`나 CR 형식을 바꾸면 agent-session·project-board test와 네 번째 명령도 실행합니다.
  - `tools/agent-session/**`: `python -m pytest -q -n 8 tools/agent-session/tests`. `agent_session/api.py`·state 형식·tmux option 이름을 바꾸면 project-item·project-board test와 `python -m pytest -q -n 8 install/tests`도 실행합니다.
  - 문서(`skills/**`, `docs/**`): 고친 문서의 상대 link 검사, `python -m pytest -q tools/test_distribution_boundary.py`. `skills/project-item`의 형식 문서를 바꾸면 `python -m pytest -q tools/project-item/tests/test_doc_contract.py`, `skills/**`나 `docs/project-team/spec.md`를 바꾸면 `python -m pytest -q tools/agent-session/tests/test_remote.py`도 실행합니다.
- 실제 원격(`origin`)의 branch는 test에서 지우지 않습니다. 격리 원격만 씁니다.
