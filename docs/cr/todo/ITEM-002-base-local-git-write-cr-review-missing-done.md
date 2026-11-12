# ITEM-002: base 밖 저장소(원격 없는 local git)에 제출한 write CR 이 review_missing 으로 done 에 갈 수 없음

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S3
- Requester: falcon2, /primehome/swain/Project/falcon2/git/fc2.base, 2026-11-12

- Requester: falcon2 Leader (D-20261112-15 A)

## Symptom
- write CR 의 산출물이 base 의 `origin/main` 이 아니라 원격 없는 local git(예: `/primehome/swain/Project/falcon2/git/agent`)에 있으면, Leader 가 `project-item accept` 로 인수해도 `project-item move <CR> done --outcome fixed` 가 `review_missing: the submitted commit <hash> is not on origin/main` 으로 거절합니다. 그래서 in-progress CR 과 seat 를 닫을 정상 경로가 없습니다.
- falcon2 OPS-007 에서 실제로 막혔고, 사용자 결정(D-20261112-15 A)으로 in-progress → todo → done(fixed) 경유로 닫았습니다. 이것은 검사를 거치지 않는 우회이므로 지원되는 경로가 필요합니다.

## Evidence
- 재현: falcon2 OPS-007(Worker seat0). 제출 행 `- 제출 commit: b6a2e539c38b4f8f654bcc9027b132a5b78fff5b`(`/primehome/swain/Project/falcon2/git/agent`, remote 없음, master).
  - `project-item accept OPS-007 --commit b6a2e539c3…` → accepted.
  - `project-item move OPS-007 done --outcome fixed --by Leader` → `review_missing: OPS-007 was not reviewed: the submitted commit b6a2e539c38b4f8f654bcc9027b132a5b78fff5b is not on origin/main`.
- 원인: `/primehome/swain/.local/lib/project-agent/releases/0.11.0-fc4ce6b9d115/tools/project-item/project_item/guard.py:30-41` `_origin_main_has()` 는 항상 base 의 `origin/main` 에서 `merge-base --is-ancestor` 를 봅니다. `:69-76` 이 write CR in-progress → done(fixed) 에 이를 강제합니다. 제출 commit 이 어느 저장소에 있는지 적을 칸이 없습니다.
- 선례: falcon2 OPS-002·OPS-005 는 Leader 직접 구현이라 in-progress 를 거치지 않아 검사를 받지 않았습니다.

## Contract
- 요청: base 밖 저장소에 제출하는 write CR 을 검사 아래에서 done 으로 옮길 수 있게 해 주십시오. 방법은 project-agent 판단입니다. 예: Result 의 제출 행에 저장소 경로를 함께 적고(예 `- 제출 commit: <hash> (repo <abs path>)`), 그 저장소에 commit 이 있는지(원격이 없으면 local branch 조상인지) 확인.
- 유지할 것: 지금처럼 인수 기록(accept)은 필수. base 의 write CR 은 지금처럼 `origin/main` 검사.
- 완료 기준: 위 재현에서 저장소를 밝힌 제출 행이면 move 가 통과하고, 저장소에 없는 hash 면 지금처럼 `review_missing` 으로 거절.

## Disposition
- 2026-11-12 Leader 판정: 고칩니다. Write CR을 검사를 거쳐 닫을 경로가 없어서, in-progress CR과 seat가 남습니다. 요청자는 결국 검사를 거치지 않는 우회로 닫았습니다. 재현과 근거가 있는 운영 결함이므로 Leader가 판정합니다. 요청자는 방법을 project-agent 판단에 맡겼습니다.
  - **근본 원인**: write CR이 어느 저장소의 어느 ref로 통합되는지가 어디에도 선언되어 있지 않습니다. 그런데 guard는 그 대상을 base의 `origin/main`으로 고정해서 가정합니다(`tools/project-item/project_item/guard.py` `_origin_main_has`, `branch.on_origin_main`).
  - **택하지 않은 방법**: 요청서의 예시(제출 행에 저장소 경로를 적음)는 택하지 않습니다. 이 방식에서는 검사받는 Worker가 제출마다 검사 대상을 고릅니다. 같은 저장소 경로와 통합 branch를 CR마다, 제출마다 다시 적어야 하고, 통합 ref(원격이 없을 때 어느 branch인지)를 정할 곳도 없습니다.
  - **택한 방법**: 통합 대상의 원본은 project 등록 하나입니다. 등록은 base 밖 저장소마다 저장소 경로와 통합 ref를 한 번만 선언합니다. CR에서는 Leader가 header로 그중 하나를 이름으로 고릅니다. header가 없으면 지금처럼 base의 `origin/main`입니다. 인수 기록(accept)은 지금처럼 필수입니다.
  - 지금 하던 release 검증을 늦추지 않도록, 시작은 다음 release(TEST-016 통합 뒤)를 설치한 다음에 합니다.
- 2026-11-12 Leader: open -> todo.

## Implementation
읽을 문서:
- [CR 계약](../../../skills/project-item/references/cr.md): "파일 형식", "JOB으로 쓸 때", "`cr/<ID>` branch의 수명".
- [동작 명세](../../project-team/spec.md): 2절 등록, 8절 CR과 실행 입력. 그리고 [등록 예제](../../project-team/project-registry.example.json).
- [설치 계약](../../project-team/install-contract.md): 형식 version(`tools/formats.json`)과 등록 위치.
- [project-team skill](../../../skills/project-team/SKILL.md): Leader 6·7단계.
- 코드:
  - `tools/project-item/project_item/`: `guard.py`, `branch.py`, `cr.py`, `registry.py`.
  - 등록 검사: `tools/agent-session/agent_session/config.py`.
- 절차: [project-team Worker 절](../../../skills/project-team/SKILL.md#worker).

1. **등록**: base 밖 통합 대상을 선언하는 선택 key를 더합니다(예: `repos`, 이름 → 저장소 경로와 통합 ref).
   - 경로는 `path_cr`과 같이 해석합니다(절대 경로, `~/`, base 기준 상대 경로).
   - 통합 ref는 선언한 그대로 씁니다. 원격 추적 ref(예 `origin/main`)이면 검사 전에 그 remote에서 가져오고, local branch(예 `master`)이면 그대로 봅니다. 저장소에 원격이 있는지로 추측하지 않습니다.
   - 형식 오류는 다른 key처럼 `registry_invalid`입니다. 등록 검사의 원본은 agent-session `config.py` 하나이고, project-item은 그 결과를 읽습니다.
2. **CR header**: 대상 이름을 고르는 header를 하나 더합니다(예: `- Repo: <등록 이름>`). Leader만 씁니다.
   - 형식의 원본은 cr.md "파일 형식"과 `cr.py`입니다. `test_doc_contract.py`가 둘이 같은지 확인합니다.
   - 형식 version을 올릴지는 설치 계약의 규칙을 따르고, CHANGELOG "형식:" 줄에 적습니다.
3. **Guard**: 통합 검사는 대상 하나를 풀고(header가 없으면 base `origin/main`), 제출 commit이 그 ref의 조상인지 봅니다.
   - 이름이 등록에 없거나, 경로가 Git 저장소가 아니거나, ref를 읽거나 가져올 수 없으면 `review_missing`으로 거절하고 이유를 보입니다. 이때 base로 대신 검사하지 않습니다.
   - 문구는 지금처럼 어느 ref에 없는지를 밝힙니다(예: `... is not on master of /abs/path`).
4. **Branch 수명** (`move`의 `drop_integrated`, `project-item drop-branch`, seat의 `prune_integrated`): 대상이 base가 아닌 CR에는 base의 `cr/<ID>` 규칙을 어떻게 적용할지 정해 규칙 절에 적습니다. 예: 대상 저장소에서 같은 판정을 함, 또는 base에는 손대지 않음.
5. **문서**:
   - cr.md 형식과 주체 표.
   - spec 2절과 등록 예제.
   - project-team SKILL Leader 7단계의 "제출 hash가 `origin/main`에 없으면" 문장을 통합 대상 기준으로 고칩니다.
   - spec에 적을 것: 대상이 base 밖이면 seat 격리가 그 저장소를 덮지 않는다는 점과, Worker가 어디서 작업하는지.
6. **Test** (관측 동작, 격리 등록과 임시 Git 저장소):
   - header 없음: 지금 동작(base `origin/main`)이 그대로입니다.
   - 원격 없는 local 저장소를 선언하고, 제출 commit이 그 branch에 있으면 `move ... done --outcome fixed`가 통과합니다(요청 재현).
   - 같은 저장소에 없는 hash는 `review_missing`입니다.
   - 원격 추적 ref를 선언한 외부 저장소: push 전에는 거절하고, push 뒤에는 통과합니다.
   - 등록에 없는 이름이나 사라진 경로는 `review_missing`이고 이유가 나옵니다. base로 대신 검사하지 않습니다.
   - accept가 없으면 지금처럼 거절합니다.
   - 등록 형식 오류는 `registry_invalid`입니다.

위험 등급: 중간. 종결 guard를 바꾸고, 등록 형식과 CR 형식을 늘립니다.

## Verification
- README 검증 표에서 바꾼 경로의 행 명령을 모두 제출 commit에서 실행합니다.
  - `tools/project-item/**`: `python -m pytest -q tools/project-item/tests`, `python -m pytest -q tools/agent-session/tests/test_api_boundary.py`. CR 형식(`cr.py`)을 바꾸므로 `python -m pytest -q -n 8 tools/agent-session/tests`, `python -m pytest -q tools/project-board/tests`, 네 번째 명령도 실행합니다.
  - `tools/agent-session/**`(등록 검사): `python -m pytest -q -n 8 tools/agent-session/tests`. `api.py`를 바꾸면 project-item·project-board test와 `python -m pytest -q -n 8 install/tests`도 실행합니다.
  - `tools/formats.json`을 바꾸면 네 번째 명령과 `python -m pytest -q -n 8 install/tests`를 실행합니다.
  - 문서: 고친 문서의 상대 link 검사, `python -m pytest -q tools/test_distribution_boundary.py`, `python -m pytest -q tools/project-item/tests/test_doc_contract.py`, `python -m pytest -q tools/agent-session/tests/test_remote.py`.
- 재현: 격리 HOME에 falcon2 OPS-007과 같은 모양(원격 없는 local 저장소, `master`)을 만듭니다. 고치기 전 commit에서는 `review_missing`이고 제출 commit에서는 통과하는 것을 Result에 적습니다.
