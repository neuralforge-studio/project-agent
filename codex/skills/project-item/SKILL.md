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

- 항목 위치는 project 등록 파일의 `path_cr`·`path_decide`가 정합니다. [등록 계약](../../../docs/project-team/spec.md#2-등록과-프로젝트-선택)을 따릅니다.
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
| `decide` | `open`, `done` | open→done, done→open |

- 상태를 더 늘리지 않습니다.
- `in-progress`는 CR이 seat에서 실행 중이라는 뜻입니다. 팀 project(seat가 있는 project)에서는 `agent-session start`만 CR을 in-progress로 옮깁니다. `project-item move`는 `agent_session_only`로 거절합니다. 팀이 없는 project는 담당자가 `project-item move`로 옮깁니다.
- `cr`의 `Outcome: fixed`는 todo 또는 in-progress에서만 done으로 갈 수 있습니다.
- Open으로 되돌리는 전이에는 `--by`와 `--note`가 필요합니다. 도구가 Disposition 항목을 쓰고 Outcome을 지웁니다.
- 항목을 옮기는 주체는 담당 session입니다. 팀 project에서는 Leader입니다.
- 다른 project의 요청자는 `new cr`로 그 project의 open에 만들기만 합니다.

`move`의 동작:

1. 출발·도착 쌍이 위 표에 있는지 확인합니다.
2. `--outcome`이 있으면 Outcome header를 씁니다. `--by`가 있으면 `--note`를 근거로 Disposition 항목을 씁니다.
   판정은 결정자를 남기므로 `--outcome`·`--note`는 `--by`와 함께 씁니다. `--by`가 없으면 `decider_missing`으로 거절합니다.
   도착 상태에 맞지 않는 Outcome은 `invalid_outcome`으로 거절합니다. 예를 들어 cr의 `moved`는 deferred에만 씁니다.
3. 도착 상태 기준 형식 검사를 합니다. 실패하면 파일을 바꾸지 않습니다.
4. Git이 추적하는 파일은 `git mv`로 옮깁니다. 추적하지 않는 파일은 rename합니다.
   이동이 실패하면 원문·경로를 되돌리고 index는 쓰지 않습니다. 되돌리지 못하면 `move_partial` 오류가 남은 경로와 index 항목을 알립니다.
5. 도구는 commit하지 않습니다. Commit은 담당 session이 project 규칙에 따라 합니다.

`check`는 파일이 지금 디렉토리의 형식에 맞는지만 봅니다. 전이 허용 여부는 `move`가 봅니다.

## 명령

진입점은 `project-item`입니다. 설치 link는 `~/.local/bin/project-item`이고 원본은 이 저장소의 `codex/tools/project-item/bin/project-item`입니다.
Project는 현재 경로의 등록 base·seat로 선택합니다. 다른 project는 `--project NAME`으로 지정합니다.

| 명령 | 동작 |
| --- | --- |
| `project-item projects` | 등록 project, 종류별 경로, 상태별 개수 |
| `project-item ls [cr\|decide] [--state S] [--all]` | 항목 목록. 기본은 cr의 open·todo·deferred와 decide의 open |
| `project-item new cr --area A --title T [--severity S] [--body-file F]` | cr open에 생성 |
| `project-item new decide --title T [--urgency U] [--blocks B] [--related R] [--body-file F]` | decide open에 생성하고 결정 페이지를 다시 씀 |
| `project-item move ID STATE [--outcome O] [--by B] [--note N]` | 위 절차로 이동 |
| `project-item check [cr\|decide] [paths]` | 형식과 ID 중복 검사. 위반이 있으면 exit 1 |
| `project-item render decide [--out F]` | 결정 페이지를 다시 씀 |
| `project-item owner PROJECT` | Base·seat 아래의 live Claude 대화형 session 이름 |

입력·등록 오류는 exit 2와 `project-item: <code>: <message>`입니다.

## 동시 실행

- `new`, `move`, 결정 페이지 쓰기는 항목 루트마다 잠금 하나를 잡고 실행합니다. 잠금 파일은 `~/.cache/project-item/locks/`에 있습니다.
- 이 잠금은 같은 머신의 session끼리만 순서를 정합니다.
- 다른 머신이 같은 network 경로에 동시에 발급할 수 있습니다. `check`가 모든 상태의 ID 중복을 위반으로 보고합니다.
