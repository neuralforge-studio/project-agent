# Change Request(CR) 리뷰 계약

## 목적

이 문서는 사용자가 요청하거나 저장소 정책이 요구하는 CR 리뷰를 **발견 / 판정 / 구현**으로 분리하고, project-team의 JOB으로 사용하는 CR 형식을 정합니다. 일반 리뷰에는 이 파일 형식과 상태 관리를 자동 적용하지 않습니다. 저장소별 CR 디렉토리 위치와 AREA 목록은 각 저장소의 CR 문서가 소유합니다. 파일 형식과 상태 규칙은 이 문서가 소유합니다. 저장소 CR 문서는 이 규칙을 다시 적지 않고 이 문서를 가리킵니다.

아래 Phase 1~3과 범위 완료 조건은 요청되거나 정책이 요구한 CR 리뷰에 적용합니다. CR을 project-team의 JOB으로 사용할 때는 [JOB 절](#job으로-쓸-때)과 project-team의 배정·인수 절차를 적용합니다.

발견 즉시 구현으로 넘어가는 리뷰는 두 가지 비용을 뒤로 미룹니다. 여러 증상이 사실 하나의 원인이라는 사실을 늦게 알게 되고, "이건 의도된 동작"이라는 결론이 기록되지 않아 계속 재논의됩니다. CR은 그 두 비용을 리뷰 앞단으로 옮깁니다.

계획·검증 범위는 `~/.codex/references/planning-execution.md`를, 필요한 독립 검토는 `~/.codex/references/plan-review-budget.md`를, release evidence는 `~/.codex/references/verification-rtm.md`를 따릅니다. CR은 작업 흐름이며 별도의 검증 정책을 만들지 않습니다.

## 운영 대상

CR 항목은 각 저장소의 git CR 디렉토리(`open/`, `todo/`, `done/`, `deferred/`) 파일로 관리합니다. 등록 project와 CR 디렉토리의 대응은 project 등록(`project.json`)의 `path_cr`가 소유합니다. 담당 session은 전역 지침의 조회 조건에 따라 `project-item ls`로 자기 project의 미결 항목을 확인합니다. 등록 대상이 아닌 저장소도 CR 방식을 적용할 때 같은 형식을 씁니다.

## 도구

`project-item`을 사용합니다. Codex와 Claude Code가 같은 도구를 씁니다. 명령, 허용 전이, `move`의 동작은 [project-item skill](../SKILL.md)이 소유합니다.

- `project-item new cr --project <project> --area <AREA> --title ...`: 다음 번호로 `open/`에 파일을 만듭니다.
- `project-item ls [--project <project>]`: `open/`, `todo/`, `deferred/`의 항목과 상태별 개수를 보여 줍니다.
- `project-item check cr`: 이 문서의 파일 형식을 검사합니다.
- `project-item owner <project>`: 담당 session 이름을 보여 줍니다. 관리 Leader가 없는 project에 `SendMessage`로 알릴 때만 씁니다("다른 project에 요청할 때").
- `project-item move <ID> <STATE>`: 허용 전이에 따라 상태를 옮깁니다.

## 상태와 소유권

상태는 디렉토리가 소유합니다. 파일 본문에 상태를 적지 않습니다(`Status:` 줄 금지). 전이는 `git mv` 또는 `project-item move`로 수행해 이력이 남게 합니다. 허용 전이와 되돌림 전이는 `project-item` skill의 "상태와 전이"를 따릅니다.

| 디렉토리 | 의미 | 진입 조건 | 나가는 조건 |
| --- | --- | --- | --- |
| `open/` | 문제 의심 또는 작업 제안. 아직 판정되지 않음. | 근거와 함께 열림 | CR 리뷰의 Phase 2 또는 JOB 판정 |
| `todo/` | 수행하기로 판정·승인된 JOB. | 구현 방법과 변경 유형별 검증 기준, 사용자 결정 또는 위임 범위의 Leader 판정을 적은 Disposition이 작성됨 | 배정(in-progress) 또는 구현 + 검증 통과 |
| `in-progress/` | seat에서 실행 중인 것. | 팀 project는 `agent-session start --job <ID>`가 옮김 | Leader가 done·todo·open·deferred로 옮김 |
| `done/` | 결론이 난 것. | `Outcome`과 그 종류의 필수 기록이 작성됨 | — |
| `deferred/` | 다른 프로그램이나 범위의 소관으로 확인된 것. | 대상 쪽 `open/`에 항목이 열리고 `Outcome: moved`가 작성됨 | — |

- `open/`에 있는 동안에는 **제품 코드를 수정하지 않습니다.** 발견 단계에서의 수정은 Phase 2의 판정 대상을 오염시킵니다.
- 기각(waive)도 결론이므로 `todo/`를 거치지 않고 곧바로 `done/`으로 갑니다.
- 상태를 더 늘리지 않습니다. `verifying` 같은 중간 상태는 두지 않고, 진행은 `## Result`와 evidence로 계산합니다.
- `in-progress/`의 형식 조건은 `todo/`와 같습니다. 어느 seat·session이 맡았는지는 CR에 쓰지 않습니다. `<base>/agent/state.json`이 소유합니다.
- `done/`과 `deferred/`의 파일은 `- Outcome:` 헤더로 종결의 종류를 적습니다. Outcome은 상태가 아니고 결론의 종류입니다.

| Outcome | 뜻 | 필수 기록 |
| --- | --- | --- |
| `fixed` | 고쳤습니다 | `## Implementation`, `## Verification`, `## Result` |
| `waived` | 기각했습니다 | `## Disposition`의 기각 근거, 결정자, 다시 볼 조건 |
| `merged <ID>` | 다른 항목에 합쳤습니다 | `## Disposition`의 병합 근거. Implementation과 Verification 절은 쓰지 않습니다 |
| `moved <program> <ID>` | 다른 프로그램이나 범위로 넘겼습니다(`deferred/`만) | 대상 쪽에 연 항목의 ID |

### 다른 문서에 상태를 복사하지 않습니다

- README, 순서 문서(`ORDER*.md`), 요약 문서, `TODO.md`에 항목 개수와 상태를 적지 않습니다. 개수는 `project-item ls`가 디렉토리에서 계산합니다.
- 순서 문서에는 실행 순서와 묶음을 ID로만 적습니다. 끝난 항목을 순서 문서에서 지우거나 표시하지 않습니다. 디렉토리가 그 사실을 보여 줍니다.
- 다른 문서(spec, coverage plan, 코드 주석)는 CR ID만 가리킵니다.

### release와 CR

- release 때 CR 파일을 고치지 않습니다. `## Result`에는 commit과 검증 결과를 적고 version은 적지 않습니다.
- 어느 version에 어느 CR이 들어갔는지는 release note가 CR ID 목록으로 답합니다.

## Phase 1 — 열거

1. 리뷰 범위를 먼저 선언합니다. 어떤 파일/모듈이 이 범위이고, 어떤 인접 surface가 읽기 전용 증거인지 명시합니다.
2. 선언한 리뷰 범위에서 근거가 있는 의심 항목을 `open/`에 엽니다. 이미 같은 원인의 CR이 있으면 그 항목의 증거를 보강하고 새 항목은 만들지 않습니다. 문제 여부의 판정은 Phase 2에서 합니다.
3. 제품 동작에 관한 항목은 **code-grounded**여야 합니다. `path:line` 인용과 관찰된 동작, 그 동작이 어긋나는 계약(spec, 코드 주석, 테스트, 설정 스키마 중 무엇인지)을 함께 적습니다. 제품 동작을 확인하지 않고 문서끼리 비교한 것만으로 제품 동작 결함을 열지 않습니다. 문서·설정 자체가 리뷰 대상이면 대상 원문과 지배 계약의 `path:line`, 적용 범위가 겹치는 조건과 충돌 내용을 근거로 항목을 열 수 있습니다. 단순한 표현 차이만으로는 항목을 열지 않습니다.
4. **원인 단위로 묶습니다.** 증상마다 파일을 만들지 않고, 하나의 의심 메커니즘에 하나의 파일을 만든 뒤 증상을 그 안에 나열합니다. 개수 목표나 상한은 두지 않습니다. 항목 수는 그 범위가 실제로 가진 문제 수가 결정합니다.
5. 서로 다른 원인으로 열었으나 나중에 같은 원인으로 확인된 항목은 `Related`에 적어두고 Phase 2에서 병합합니다.

## Phase 2 — 일괄 재검토

이번 리뷰에서 연 `open/` 항목과 판정에 직접 관련된 기존 `open/` 항목을 함께 읽습니다. 무관한 기존 backlog는 재판정하지 않습니다. 이 단계에서 다음을 수행합니다.

- **인용 확인**: 같은 리뷰에서 대상 원본과 계약을 확인한 유효한 근거는 재사용합니다. 관련 원본이나 계약이 바뀌었거나 인용의 정확성이 불명확하면 다시 확인합니다.
- **정말 문제인지 판정**: 위반되는 계약을 지목할 수 있어야 문제입니다. 지목할 수 없으면 취향이거나 의도된 설계이며, 기각 대상입니다.
- **병합과 공통 원인**: 여러 항목이 하나의 원인을 공유하면 하나로 합칩니다. 증상은 합쳐진 항목 안에 모두 남깁니다.
- **함께 처리할 것 묶기**: 같은 파일·같은 계약·같은 트랜잭션 경계를 건드리는 항목은 한 단위로 묶습니다. 따로 고치면 서로의 수정을 되돌립니다.
- **순서와 의존**: 어떤 항목이 다른 항목의 선행인지 결정합니다. 이 순서가 Phase 4의 실행 순서가 됩니다.
- **소관 판정**: 이 범위 밖 원인이면 대상 쪽 `open/`에 같은 내용을 열고(`project-item new cr --project <project>`), 이 항목은 `deferred/`로 보냅니다.

판정 결과는 다섯 중 하나입니다. 판정마다 `## Disposition`에 날짜와 결정자를 붙인 항목을 하나 추가합니다. 이전 판정은 지우지 않습니다. 재판정도 같은 절에 항목을 추가합니다.

| 판정 | 이동 | 필수 기록 |
| --- | --- | --- |
| 고친다 | `todo/` | 구현 방법 + 변경 유형별 검증 기준 |
| 기각한다 | `done/`, `Outcome: waived` | 기각 근거(왜 의도된 동작인지), 결정자, 재발 시 다시 볼 조건 |
| 병합한다 | `done/`, `Outcome: merged <ID>` | 병합 근거. 증상은 병합 대상 항목으로 옮깁니다 |
| 다른 범위 소관 | `deferred/`, `Outcome: moved <program> <ID>` | 대상 쪽에 연 항목 |
| 증거 부족 | `open/` 유지 | 판정에 필요한 확인 항목을 명시 (막연한 보류 금지) |

## Phase 3 — 이관 형식

`todo/`로 옮기는 항목은 다음을 **작성한 채로** 옮깁니다. 구현 단계가 다시 설계로 되돌아가지 않게 하는 것이 목적입니다.

- **구현 방법**: 변경할 파일과 심볼, 소유자 경계, 무엇을 어떻게 바꾸는지. 대안을 검토했다면 선택 근거.
- **검증 기준**: 변경 동작의 관찰 가능한 합격 기준을 적습니다. 관찰된 제품 동작 결함을 코드에서 수정할 때는 공통 Behavioral bug gate의 수정 전 실패와 동일 case의 수정 후 PASS를 포함합니다. 그 외 변경에 의도된 수정 전 실패를 요구하지 않습니다.
- **영향 회귀**: 통과해야 하는 직접 영향 범위의 검사.
- **의존**: 선행 항목과 후행 항목.
- **위험 등급**: `planning-execution.md`의 등급. 독립 검토 발동 여부가 여기서 결정됩니다.

기각 항목은 근거를 남기고 즉시 `done/`으로 옮깁니다. "확인했으나 문제 아님"만 적힌 기각은 다음 라운드에서 같은 항목을 다시 열게 만들므로 무효입니다.

## Phase 4 — 실행

CR 리뷰에서 구현하기로 판정한 항목과 Write JOB을 승인된 의존 순서로 처리합니다. CR 리뷰에서 판정한 항목은 Phase 2의 순서를 따릅니다. 관찰된 제품 동작 결함의 수정에는 `~/.codex/references/planning-execution.md`의 Behavioral bug gate를 적용합니다. 다른 변경에는 해당 문서의 변경 유형별 검증 기준을 적용합니다. Read-only JOB에는 아래 구현·commit 단계를 적용하지 않습니다.

1. 관찰된 제품 동작 결함을 코드에서 수정하면 공통 Behavioral bug gate의 수정 전 실패와 근본 원인을 확인합니다. 다른 변경은 해당 검증 기준과 유효한 기존 근거를 확인합니다.
2. 구현합니다.
3. 제품 동작 결함 수정은 동일 case의 수정 후 PASS를 확인합니다. 다른 변경은 변경 동작의 focused check를 확인합니다.
4. 필요한 직접 영향 회귀를 실행합니다.
5. `## Result`에 실행한 검증 명령과 결과, 증거 경로를 적습니다. 구현 commit이 있으면 생성한 뒤 그 hash를 기록합니다. 같은 commit 안에 자기 hash를 넣으려고 반복해서 amend하지 않습니다.
6. 팀 project의 Write JOB은 Worker 제출과 Leader 인수·통합 후 [project-team 절차](../../project-team/SKILL.md#leader)에 따라 `done/`으로 옮깁니다. 제출 hash·인수·종결 기록은 제출 commit 이후 CR 관리 경로에 남깁니다. 팀이 아닌 project는 검증을 마친 뒤 `project-item move`로 `Outcome: fixed`를 기록하고 `done/`으로 옮깁니다. Commit이 필요한 경우 종결 기록은 구현 commit 이후 저장소 규약에 따라 기록합니다.

Phase 4 중의 중단, 되돌림, 리뷰 후속 조치는 새 절을 만들지 않습니다. 판정이 바뀌면 `## Disposition`에, 실행 기록이면 `## Result`에 날짜를 붙여 추가합니다.

CR 리뷰의 범위 완료 조건은 이번 리뷰에 속한 `open/`, `todo/`, `in-progress/` 항목이 모두 종결된 것입니다. 다른 범위의 기존 항목은 완료 조건에 넣지 않습니다. 사용자나 적용 정책이 독립 clean 리뷰를 요구하면 마지막 실질 변경 이후 지정 범위를 검토합니다. 남은 실패 테스트가 있다면 각각의 소유자와 성격(미구현 기능에 대한 forward coverage인지, 의도된 pre-fix인지)이 기록되어야 하며, 소유자 없는 실패는 완료를 막습니다.

## 파일 형식

```markdown
# <AREA>-<NNN>: <한 줄 제목>

- Opened: YYYY-MM-DD
- Scope: <리뷰 범위 이름>
- Severity: S1 | S2 | S3
- Related: <다른 항목 ID>                          (없으면 생략)
- Requester: <program>, <session cwd>, YYYY-MM-DD   (다른 프로그램이 연 항목만)
- Mode: write | read-only                           (JOB으로 배정할 때. 없으면 write)
- Cwd: <seat 기준 상대 경로>                         (JOB 작업 디렉토리. 없으면 seat root)
- Base: <commit> <ISO 시각>                          (agent-session만 씀. 시작 기준)
- Outcome: fixed | waived | merged <ID> | moved <program> <ID>   (done/·deferred/만)

## Symptom
관찰된 동작 또는 문서·설정의 문제 내용. 여러 개면 나열.

## Evidence
제품 동작은 `path:line` 인용과 코드의 동작, 재현 명령, 입력, 도구 version. 문서·설정 자체는 대상 원문의 `path:line`, 적용 조건과 충돌 내용.

## Contract
무엇을 위반하는가. 제품 동작은 spec/주석/테스트/스키마 중 근거 위치. 문서·설정 자체는 지배 계약의 `path:line`과 적용 범위.

## Suspected cause
Phase 2에서 확정·수정·병합됨.

## Disposition
판정마다 한 항목: 날짜, 결정자, 판정, 근거.

## Implementation
## Verification
todo/ 진입 때 필수. waived·merged는 생략.

## Result
제출과 종결 때: commit, 실행한 검증 명령과 결과, 증거 경로.
```

### JOB으로 쓸 때

CR은 project-team의 JOB을 겸합니다. 기능·리팩터링·조사 작업도 CR로 씁니다. Symptom은 현재 상태, Contract는 요구사항이나 근거 계약으로 씁니다. JOB은 Phase 1~3의 일괄 CR 리뷰와 범위 완료 조건을 자동 실행하지 않습니다. Leader는 현재 JOB의 판정과 검증 기준을 작성하고 project-team 절차에 따라 배정·인수합니다. 관찰된 제품 동작 결함을 코드에서 수정하는 JOB에만 위 Phase 4의 수정 전 실패 단계를 적용합니다.

| 주체 | 고치는 곳 |
| --- | --- |
| Leader | CR 생성, Disposition(판정·사용자 결정 또는 Leader 판정·검토 결과·수정 요청), 상태 이동. 제출을 인수할 때 `project-item accept <CR-ID> --commit <hash>`를 실행합니다. |
| Worker | 자기 CR이 in-progress인 동안 `## Result`에 제출 commit과 검증 결과만 추가. 팀 project에서 CR을 옮기면 `role_denied`입니다. |
| agent-session | todo→in-progress 이동, `- Base:` 기록 |

- 역할 지침·읽을 문서·필요한 submodule은 본문에 link와 문장으로 적습니다. 예: `## References` 절.
- Read-only CR(조사)은 결과를 `## Result`에 씁니다. Leader는 결과에 따라 CR을 옮깁니다: 문제를 확인하고 고치기로 하면 todo, 판정이 더 필요하면 open, 문제가 없으면 done(Outcome waived)입니다.
- Write CR의 Worker는 제출할 때마다 `## Result`에 들여쓰지 않은 제출 행 `- 제출 commit: <40자리 hash>`를 한 줄 씁니다. Hash는 backtick으로 감싸도 됩니다. 검증 명령·비교 기준 같은 다른 hash는 이 행에 쓰지 않습니다. 들여쓴 행과 code fence 안의 행은 제출 행이 아닙니다.
- Leader는 검토 결과(인수·수정 요청)를 Disposition에 쓸 때 검토한 제출 hash를 함께 적습니다. 앞 7자리 이상이면 됩니다. Project Board는 마지막 제출 행의 hash가 Disposition에 없으면 review 대기로 표시합니다.
- Write CR의 작업 branch는 `cr/<ID>`입니다. 보류(in-progress→todo)하면 branch를 origin에 게시한 상태로 둡니다. 다시 배정하면 그 branch를 이어받습니다.
- 새 기준으로 다시 시작하려면 Leader가 `- Base:`를 지우고 Disposition에 이유를 적습니다.

- 위 절은 이 순서로 씁니다. 절 이름은 바꾸지 않습니다. 같은 이름의 절을 두 번 쓰지 않습니다.
- 저장소에 필요한 절(예: `## Owner request`, `## Blocking`)은 추가할 수 있습니다. 위 절의 내용을 대신하는 절은 만들지 않습니다.
- 헤더는 위 목록만 씁니다. 저장소에 필요한 헤더는 그 저장소 CR 문서에 선언한 뒤 씁니다. 상태를 뜻하는 헤더는 선언할 수 없습니다.
- Severity는 영향 기준입니다. S1은 기능 결함이나 release 차단, S2는 계약 위반이지만 우회 가능, S3은 정리·문서·비용입니다.
- 파일명은 `<AREA>-<NNN>-<슬러그>.md`입니다. 번호는 AREA마다 3자리이고 그 저장소 안에서 재사용하지 않습니다. 새 번호는 `project-item new cr`가 정합니다. 병합된 항목의 번호와 파일은 살려둡니다.
- 2026-10-20 이전의 ID와 파일은 바꾸지 않습니다. 이 형식은 새 항목과 2026-10-20 이관 항목(`- Migrated:` 헤더)에 적용합니다. 이관 항목은 작업할 때 이 형식으로 정리합니다.

## 다른 project에 요청할 때

다른 등록 project(`project-item projects`의 목록)가 소유한 파일의 결함 수정, 기능 추가, update(version·release 반영 등)는 그 project가 수행합니다. 요청자는 그 파일을 직접 고치지 않습니다.

담당 project는 고칠 파일이 들어 있는 등록 base의 project입니다. 설치본·runtime 경로만 알면 `inhouse-tool-registry`로 원본 저장소를 찾습니다. 등록 project가 아닌 도구에 수정이 필요하면 요청할 대상이 없으므로 자기 project의 결정 항목으로 사용자에게 알립니다.

1. 최소 재현이나 필요한 동작을 확인하십시오. 명령, 입력, 도구 경로와 version을 기록하십시오.
2. `project-item new cr --project <project> --area <AREA> --title ... --body-file -`로 대상 project의 `open/`에 CR을 여십시오. 본문 절은 `project-item new cr -h`를 따르십시오. `- Requester:`를 남기십시오. 요청자는 파일을 commit하지 않습니다. 담당 project가 판정과 함께 commit합니다.
3. 대상 project의 Leader에게 `agent-session send --project <project> --job leader "<CR ID> <제목> <파일 경로>"`로 한 줄 알리십시오. 상세 내용은 CR 파일에만 쓰십시오. 관리 Leader가 없는 project(팀이 없는 project)에만 `project-item owner <project>`로 담당 session 이름을 찾아 `SendMessage`로 알리십시오. 둘 다 없으면 알림을 생략하십시오.
4. 자기 작업은 우회 방법으로 계속하십시오. 막힌 항목에는 CR ID를 기록하고 다음 항목으로 넘어가십시오. 회신을 기다리며 멈추지 마십시오.

Worker는 다른 project에 `agent-session send --project`를 보낼 수 없습니다(`role_denied`, [spec 6절](../../../../docs/project-team/spec.md#project-간-leader-협업)). Worker는 자기 Leader에게 보고하고, Leader가 2·3을 합니다.

요청자 쪽에 같은 CR 항목이 있으면 `deferred/`로 보내고 `Outcome: moved <program> <ID>`를 적습니다. 받은 쪽 담당 session은 받은 요청을 현재 작업이 끝나는 시점에 확인합니다. Phase 2 판정은 사용자 결정 또는 위임 범위의 Leader 판정을 `## Disposition`에 기록합니다. 위임 범위는 project 운영 문서(팀이 있으면 project-team skill의 Leader 절)가 정합니다. 팀이 없는 project는 사용자와 합의한 뒤 기록합니다. 처리가 끝나면 요청 project의 Leader에게 `agent-session send --project <요청 project> --job leader`로 결과(commit, version)를 알립니다. 관리 Leader가 없는 요청 project에는 `SendMessage`를 쓰고, 둘 다 없으면 알림을 생략합니다. 이 협업 메시지는 동료 메시지이며 사용자 승인·읽음·작업 완료가 아닙니다([spec 6절](../../../../docs/project-team/spec.md#project-간-leader-협업)).

## 위임 규칙

CR 단계를 sub agent에 위임할 때 프롬프트에는 다음을 **반드시** 포함합니다. 전역 문서가 있어도 프롬프트에 없으면 지켜지지 않으며, 작업 트리를 혼동한 리뷰가 실재하지 않는 회귀를 보고한 사례가 있습니다.

- 작업 디렉토리의 **절대 경로**와, 혼동 가능한 mirror/worktree가 있다면 그 사실
- 현재 phase와 그 phase에서 **하면 안 되는 일** (Phase 1이면 수정 금지)
- 출력 계약: 어느 디렉토리에 어떤 파일 형식으로 쓰는지
- 이 문서의 경로
- 해당 저장소의 알려진 false positive 목록이 있다면 그 전문

## 금지사항

- Phase 1에서의 제품 코드 수정.
- 근거 없는 기각, 그리고 판정 없이 `open/`에 남겨두는 것.
- 구현 방법 없이 `todo/`로 옮기는 것. 그 항목은 아직 판정이 끝나지 않은 것입니다.
- 개수를 맞추기 위한 항목 분할 또는 병합.
- 본문의 상태 줄, 그리고 다른 문서에 항목 개수나 상태를 복사하는 것.
- release 때 CR 파일을 고치는 것.
