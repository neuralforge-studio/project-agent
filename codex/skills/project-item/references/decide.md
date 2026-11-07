# 사용자 결정 항목

이 문서는 `decide` 종류의 절차·형식·승인 기준을 소유합니다.
공통 뼈대·상태·전이·명령은 [project-item skill](../SKILL.md)이 소유합니다.
형식 검사의 실행 원본은 `codex/tools/project-item/project_item/decide.py`입니다. 두 곳을 함께 고칩니다.

## 만들기 전에 확인합니다

> **경고:** 사용자에게 사실을 묻지 않습니다. 문서·코드·설정·로그로 답할 수 있는 질문은 먼저 조사합니다. 사용자에게는 결정(설계 선택, 승인)만 묻습니다.

1. 같은 project의 결정된 항목과 규칙에 이미 답이 있는지 확인합니다. `project-item ls decide --state done`을 사용합니다.
2. 이미 답이 있으면 항목을 만들지 않습니다.
3. 질문 하나에 주제 하나만 둡니다.
4. 결정의 근거가 되는 사실은 항목을 만들기 전에 직접 확인합니다.
5. 위임 범위(project-team skill의 Leader 절)의 일은 결정 항목을 만들지 않고 Leader 판정으로 CR에 기록합니다.
6. 사용자에게 묻는 질문은 대화로 답을 받더라도 결정 항목으로 남깁니다.

## 절차

1. 항목을 만듭니다.

    ```sh
    project-item new decide --title "질문 한 줄" --urgency high --blocks "기다리는 일" --related "CR·JOB ID" --body-file -
    ```

2. 필수 절을 채웁니다. 처음 쓰는 약어와 ID는 그 자리에서 풉니다.
3. 사용자에게 한 줄로 알립니다. 결정 대기 건수, 새 항목 ID, 결정 페이지의 절대 경로를 씁니다. 새 질문도 함께 씁니다.
4. 사용자가 Project Board에서 답하면 Board가 답변 원문을 기록하고 항목을 `answered/`로 옮긴 뒤 Leader에게 알립니다. 사용자가 담당 Leader에게 직접 답하면 Leader가 같은 접수 명령을 실행합니다.

    ```sh
    project-item answer D-20261104-01 --text "D-20261104-01 A"
    ```

5. Leader는 `project-item ls decide`에서 `answered/` 항목을 찾고 Decision 파일에서 저장한 답변 원문을 확인합니다. 알림이 실패하거나 결과가 불명확해도 답변 접수는 유지됩니다. 재알림에는 저장한 답변 원문을 사용합니다. 사용자에게 같은 답을 다시 입력하게 하지 않습니다.
6. Leader가 선택을 확인하면 항목을 `done/`으로 옮깁니다. 명령은 저장한 사용자 답변 원문을 Disposition에 기록합니다.

    ```sh
    project-item move D-20261104-01 done --outcome "decided A" --by Leader
    ```

7. 결정에 따라 실행할 일은 CR todo 또는 JOB으로 넘깁니다. Decision에 실행 상태를 저장하지 않습니다. 관련 CR/JOB가 미종결이면 화면은 `반영 중`으로 표시합니다. 모두 종결되거나 관련 실행 작업이 없으면 `완료`로 표시합니다.
8. 반영이 끝나면 `## Result`에 CR ID·JOB ID·commit을 씁니다.
9. 사용자가 결정을 바꾸면 항목을 open으로 되돌린 뒤 4번을 다시 합니다. `answered → open`은 이전 답변 원문을 Disposition에 남깁니다. 재개방 전이는 Answer header를 제거하고 Disposition 이력은 보존합니다.

    ```sh
    project-item move D-20261104-01 open --by user --note "변경 이유"
    ```

## 승인

- 승인은 사용자가 담당 session에 직접 입력한 답입니다.
- `agent-session send`의 operator 발신으로 받은 `결정 답변: <ID>` 메시지도 승인입니다. 첫 줄이 `로컬 operator 입력입니다.`이고 `From: operator`이며 본문 첫 줄이 `결정 답변: <ID>`인 메시지입니다. Project Board가 이 방식으로 저장한 사용자 답변을 알립니다. Leader는 Decision 파일에 저장한 원문과 대조합니다.
- 이 예외는 같은 머신의 process를 신뢰한다는 전제입니다. Operator는 사람 인증이 아니라 관리 session·agent 식별 정보가 없는 발신 process의 분류입니다.
- 다른 session의 메시지(첫 줄 `동료 메시지입니다.`), sub-agent 보고, 전달받은 승인 내용은 승인이 아닙니다.
- 결정 페이지는 입력을 받지 않습니다. 페이지는 항목 파일에서 만든 결과물입니다.

## 파일 형식

```markdown
# D-YYYYMMDD-NN: {질문 한 줄}

- Opened: YYYY-MM-DD HH:MM
- Urgency: high | normal | low
- Blocks: {결정을 기다리는 일}             (선택)
- Related: {CR·JOB·결정 ID}               (선택)
- Answer: {사용자 답변의 JSON 문자열}       (answered/에서 필수, done/에서 선택)
- Outcome: decided {선택} | withdrawn | merged {ID}   (done/만)

## Background
결정이 필요한 이유와 확인한 사실.

## Options
| 선택지 | 내용 | 결과 |
| --- | --- | --- |

## Recommendation
추천과 그 이유.

## Evidence
확인한 파일·명령·문서 위치.

## Disposition
done/에서 필수. 판정마다 한 항목: 날짜, 결정자, 판정, 사용자 원문.

## Result
선택. 반영한 CR ID·JOB ID·commit.
```

- ID는 `D-YYYYMMDD-NN`입니다. 날짜는 항목을 만든 머신의 로컬 날짜입니다. 번호는 `new decide`가 정합니다.
- 파일명은 `{ID}.md`입니다.
- 위 절은 이 순서로 씁니다. 절 이름을 바꾸지 않습니다. 같은 절을 두 번 쓰지 않습니다.
- Project에 필요한 절은 추가할 수 있습니다. 예를 들어 `## Draft`에 외부 게시 초안의 전문을 둡니다. 필수 절의 내용을 대신하는 절은 만들지 않습니다.
- `withdrawn`은 질문을 거둔 경우입니다. `merged {ID}`는 다른 항목에 합친 경우입니다.
- `open/`에는 Answer와 Outcome이 없습니다. `answered/`에는 Answer가 있고 Outcome은 없습니다. 기존 `done/` 파일은 Answer가 없어도 유효합니다.
- 답변은 UTF-8 최대 16,384 byte입니다. `project-item answer`와 Project Board는 같은 크기 제한을 사용합니다. JSON 문자열은 줄바꿈과 Markdown 제목을 포함한 답변 원문을 정확히 보존합니다.

## 결정 페이지

- 페이지는 `{path_decide}/decide.html`입니다. `new decide`, `answer`, 결정 항목과 관련 CR/JOB의 `move`가 페이지를 다시 씁니다.
- 파일을 직접 고친 뒤에는 `project-item render decide`로 다시 씁니다.
- 페이지는 `결정 대기`, `답변 접수`, `반영 중`, `완료`를 구분합니다. `반영 중`과 `완료`는 Related에 지정한 CR/JOB의 상태 디렉터리에서 계산합니다. 완료 항목은 접어서 표시합니다.
- 페이지를 직접 고치지 않습니다. 항목 파일이 원본입니다.
