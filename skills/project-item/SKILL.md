---
name: project-item
description: "등록 project의 CR(변경 요청)과 사용자 결정 항목을 project-item 도구로 만들고 판정·이동·검사합니다. 사용자 결정을 기다리는 질문을 남길 때, CR을 열거나 상태를 옮길 때 사용합니다. 일반 질문과 일반 리뷰에는 적용하지 않습니다."
---

# Project Item

이 skill은 등록 project의 항목 파일을 관리합니다.
항목은 두 종류입니다.

| 종류 | 뜻 | 종류별 절차 |
| --- | --- | --- |
| `cr` | 발견한 문제와 판정·수정 기록 | [CR 계약](references/cr.md) |
| `decide` | 사용자 결정을 기다리는 질문과 그 결정 | [결정 항목 절차](references/decide.md) |

CR은 JOB을 겸합니다. project-team의 `agent-session start --job <CR-ID>`가 todo의 CR을 seat에 배정하고 in-progress로 옮깁니다.
어느 seat·session이 맡았는지는 `<base>/agent/state.json`이 소유합니다.

## 위치

- 항목 위치는 project 등록 파일의 `path_cr`·`path_decide`가 정합니다. [등록 계약](../../docs/project-team/spec.md#2-등록과-프로젝트-선택)을 따릅니다.
- Key가 없는 project는 그 종류를 쓰지 않습니다. 도구는 `item_path_unset`으로 거절합니다. 기본 위치를 만들지 않습니다.
- 항목 파일의 commit 여부는 project 운영이 정합니다. 이 skill은 정하지 않습니다.

## 공통 뼈대

```markdown
# {ID}: {한 줄 제목}

- Opened: {날짜}
- {종류별 header}
- Outcome: {종결 종류}

## {종류별 필수 절}

## Disposition
- {날짜} {결정자}: {판정}. {근거}

## Result
```

- 상태는 파일이 있는 디렉토리가 소유합니다. 본문에 상태 줄을 쓰지 않습니다.
- `Outcome`은 종결 상태(`done/`, `deferred/`)에만 씁니다.
- `Disposition`에는 판정마다 항목 하나를 더합니다. 이전 항목을 지우지 않습니다.
- 다른 문서에 항목 개수와 상태를 복사하지 않습니다. 다른 문서는 항목 ID만 가리킵니다.
- 종류별 header·절·Outcome 값은 종류별 절차 문서가 소유합니다.

## 상태와 전이

| 종류 | 상태 디렉토리 | 허용 전이 |
| --- | --- | --- |
| `cr` | `open`, `todo`, `in-progress`, `done`, `deferred` | open→todo, open→done, open→deferred, todo→in-progress, todo→done, todo→deferred, todo→open, in-progress→done, in-progress→todo, in-progress→open, in-progress→deferred, done→open, deferred→open |
| `decide` | `open`, `answered`, `done` | open→answered, open→done(철회·병합), answered→done, answered→open, done→open |

- 상태를 더 늘리지 않습니다.
- `in-progress`는 CR이 seat에서 실행 중이라는 뜻입니다. 팀 project(seat가 있는 project)에서는 `agent-session start`만 CR을 in-progress로 옮깁니다. `project-item move`는 `agent_session_only`로 거절합니다. 팀이 없는 project는 담당자가 `project-item move`로 옮깁니다.
- `cr`의 `Outcome: fixed`는 todo 또는 in-progress에서만 done으로 갈 수 있습니다.
- Open으로 되돌리는 전이에는 `--by`와 `--note`가 필요합니다. 도구가 Disposition 항목을 쓰고 Outcome을 지웁니다.
- 결정 답변은 `answer`가 open/에서만 받습니다. 같은 항목의 두 번째 답변은 거절합니다. 답변 원문을 파일에 기록하고 answered/로 옮긴 뒤 알림을 보냅니다. `answered → done`은 Leader가 확인합니다. `decided` 결론은 open/에서 바로 done/으로 옮길 수 없습니다. 기존 done/ 파일은 답변 기록이 없어도 유효합니다.
- `answered → done`에서 도구는 저장한 답변 원문을 Disposition에 기록합니다. `answered → open`은 원문을 Disposition에 남긴 뒤 Answer header를 제거합니다. `done → open`도 Answer header를 제거하고 이전 Disposition은 보존합니다.
- 항목을 옮기는 주체는 담당 session입니다. 팀 project에서는 Leader입니다.
  도구가 팀 project(seat가 있는 project)에서 이를 확인합니다. 호출자 판정은 agent-session의 규칙(`agent_session.api.caller`)을 씁니다.
  - in-progress의 CR을 done·todo·open·deferred로 옮기는 호출자는 그 project의 현재 Leader(실제 실행 대조 통과)나 operator(관리 session·agent가 아닌 CLI)입니다. Worker와 다른 agent session은 `role_denied`로 거절합니다.
  - `--by Leader`는 현재 Leader만 쓸 수 있습니다. 다른 호출자는 `role_denied`입니다.
  - Write CR의 in-progress→done(`Outcome: fixed`)은 review 기록이 있어야 합니다. `## Result`의 마지막 `- 제출 commit: <40자리 hash>`가 있고, `## Disposition`에 `project-item accept`가 쓴 그 hash의 인수 기록이 있고, 그 hash가 base 저장소의 `origin/main`에 있어야 합니다. 하나라도 없으면 `review_missing`으로 거절하고 파일을 바꾸지 않습니다. Read-only CR과 fixed가 아닌 Outcome은 이 확인을 하지 않습니다.
  - 같은 이동(Write CR의 in-progress→done, `fixed`)이 끝나면 `move`가 origin의 `cr/<ID>`를 지웁니다. 조건·지우지 않는 경우·실패했을 때는 [CR 계약의 branch 수명](references/cr.md#crid-branch의-수명)이 정합니다.
- 다른 project의 요청자는 `new cr`로 그 project의 open에 만들기만 합니다.

`move`의 동작 단계·오류 code·잠금은 [project-item README](../../tools/project-item/README.md)가 설명합니다.
`check`는 파일이 지금 디렉토리의 형식에 맞는지만 봅니다. 전이 허용 여부는 `move`가 봅니다.

## 언제 무엇을 쓰는가

| 상황 | 명령 |
| --- | --- |
| 등록 project의 항목 위치와 상태별 개수를 확인합니다. | `project-item projects` |
| 미결 항목을 확인합니다. 담당 session이 작업을 시작할 때 합니다. | `project-item ls` |
| 문제나 작업을 발견해 CR을 엽니다. 다른 project의 파일이면 요청 CR을 엽니다. | `project-item new cr` |
| 사용자에게 결정을 묻습니다. | `project-item new decide` |
| 사용자의 결정 답변을 접수합니다. | `project-item answer` |
| Worker의 제출을 인수합니다. Leader만 합니다. | `project-item accept` |
| 판정이나 결과에 따라 항목의 상태를 옮깁니다. | `project-item move` |
| 통합한 Write CR의 origin `cr/<ID>`를 다시 지웁니다(`move`의 삭제가 실패했을 때). | `project-item drop-branch` |
| 항목 파일을 직접 고친 뒤 형식을 확인합니다. | `project-item check` |
| 결정 페이지를 다시 씁니다. | `project-item render decide` |
| 관리 Leader가 없는 project에 알릴 담당 session을 찾습니다. | `project-item owner` |

옵션과 입력은 `project-item <명령> --help`가 소유합니다. 설치와 진입점은 [README](../../tools/project-item/README.md)를 봅니다.
다른 project에 CR을 만들면 생성 경로와 [알림 계약](references/cr.md#다른-project에-요청할-때)의 위치를 출력합니다. 알림은 자동 전송하지 않습니다.
