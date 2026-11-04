---
name: project-team
description: "등록 프로젝트의 tmux Leader·Worker를 agent-session으로 시작·배정·통신·인계·종료합니다. 프로젝트 팀 운영이나 seat에서 CR을 수행할 때 사용합니다. 일반 개발 작업 자체에는 적용하지 않습니다."
---

# Project Team

세션 관리는 설치한 `agent-session`으로 수행합니다.
명령의 상세 입력과 오류는 `agent-session --help`와 해당 하위 명령의 `--help`에서 확인합니다.
등록·상태·provider 계약을 확인할 때는 [동작 명세](../../../docs/project-team/spec.md)를 읽습니다.
JOB은 CR 파일입니다. CR 형식과 상태는 [project-item skill](../project-item/SKILL.md)이 소유합니다.

## 프로젝트와 역할

- 등록 base 또는 seat 안에서 명령을 실행합니다. 현재 경로로 프로젝트를 선택합니다.
- Provider, seat 경로, CR 위치(`path_cr`), 실행 인자(`launch`)는 등록 파일에서 읽습니다. 실행할 때 다시 지정하지 않습니다.
- 실제 배정은 `<base>/agent/state.json`에서 확인합니다.
- 상태 JSON, tmux 소유 정보, CR의 `- Base:` header를 직접 편집하여 배정을 변경하지 않습니다.

모든 명령의 `--job`은 `leader` 또는 CR ID입니다.
Worker seat는 start가 자동으로 선택합니다. Seat 디렉토리가 없으면 start가 만듭니다.

## Leader

1. 사용자 지시에서 작업 범위와 완료 기준을 정합니다.
2. `project-item new cr`로 CR을 만들고 Implementation·Verification을 채웁니다. 역할 지침과 읽을 문서는 CR 본문에 link로 적습니다.
3. 사용자 합의를 Disposition에 기록하고 CR을 todo로 옮깁니다. Todo에 있다는 사실이 승인입니다.
4. `agent-session start --job <CR-ID>`로 Worker를 시작합니다. CR은 in-progress로 옮겨집니다.
5. Review를 시작할 때 `agent-session review --job <CR-ID>`를 실행합니다. Worker가 CR의 `## Result`에 쓴 제출 hash와 실제 검증 결과를 review합니다. 검토 결과(인수·수정 요청)는 검토한 제출 hash와 함께 Disposition에 기록합니다. 수정이 필요하면 같은 CR에 feedback을 보냅니다. Feedback을 보내면 review 표시는 자동으로 지워집니다. Review를 멈추고 다른 일을 하면 `agent-session review --clear`를 실행합니다.
6. Write CR은 검토한 hash를 통합하고 원격 반영을 확인한 뒤 done(Outcome fixed)으로 옮깁니다. Read-only CR은 결과에 따라 todo(고치기로 함)·open(판정 필요)·done(Outcome waived, 문제 없음)으로 옮깁니다. 보류는 todo, 재판정은 open입니다.
7. Worker의 정리 완료를 확인한 뒤 stop으로 실제 종료와 반납을 확인합니다.

```sh
agent-session start --job leader
agent-session start --job TOOL-012
agent-session review --job TOOL-012
agent-session send --job TOOL-012 --file FEEDBACK.md
agent-session stop --job TOOL-012
```

사용자 결정이 필요한 질문은 `project-item` skill의 결정 항목으로 남깁니다.
새 대화로 교체된 Leader는 `project-item ls`로 결정 대기와 CR todo·in-progress를 이어받습니다.

제출 hash가 바뀌면 새 hash를 다시 검토합니다.
완료 보고만으로 CR을 done으로 옮기거나 seat를 비우지 않습니다.
`released: false`이면 배정을 보존하고 반환한 이유를 처리합니다. CR이 in-progress에 남아 있거나 결과가 origin에 없으면 반납하지 않습니다.

Codex의 동료 보고는 현재 turn이 끝난 뒤 처리될 수 있습니다.
배정·feedback 뒤 외부 보고만 기다리는 시점에는 현재 turn을 끝냅니다.
Tmux window와 provider session은 유지하고 후속 메시지에서 관리를 이어갑니다.
같은 turn에서 보고를 기다리며 반복 조회하지 않습니다.
보고를 받으면 CR 파일·run·제출 hash를 대조합니다.
이전 run이나 종결 CR의 늦은 보고만으로 완료한 CR을 다시 배정하지 않습니다.

## Worker

1. 최초 prompt의 CR 본문, 범위, 작업 경로, 검증 기준, link한 지침 문서를 확인합니다.
2. 지정한 범위에서 작업하고 해당 검증을 수행합니다.
3. Write CR이면 `cr/<CR-ID>` branch에 commit·push합니다.
4. CR 파일의 `## Result`에 들여쓰지 않은 제출 행 `- 제출 commit: <40자리 hash>`와 검증 명령·결과를 추가합니다. Read-only CR은 제출 행 없이 결과만 씁니다. 다른 절은 고치지 않습니다.
5. `agent-session send --job leader "CR-ID와 제출 commit"`로 보고합니다.
6. 같은 CR의 feedback을 받으면 해당 범위의 작업·검증·제출을 반복합니다.
7. Leader가 인수하면 자기 작업의 불필요한 산출물을 정리하고 종료를 보고합니다.

Main 동기화·Base 기록·CR branch 준비는 start가 수행합니다.
Worker는 이를 다시 실행하여 기준을 바꾸지 않습니다.
Read-only CR은 업무 branch·제품 코드를 변경하거나 commit·push하지 않습니다. 결과는 `## Result`에 씁니다.
정리할 때는 자기 작업의 산출물만 제거합니다. 보존할 변경과 사용자 파일을 일괄 삭제하지 않습니다.
Commit 형식은 프로젝트 규약을 우선하며 공통 초안은 [commit 양식](assets/commit-message.txt)을 사용합니다.

## 인계와 제어 결과

Restart는 새 대화 ID를 만듭니다.
이전 대화는 보존하고 현재 CR·인계 파일로 작업을 이어받습니다.
Seat·CR·시작 Git 기준·branch는 유지합니다.
Restart 전에 `<base>/agent/handoff/<slot>.md`에 현재 HEAD·미완료 작업·제출·다음 행동을 씁니다. Slot은 `leader` 또는 `seat-N`입니다.
이 파일이 현재 실행 중에 갱신되지 않았으면 restart는 `handoff_required`로 거절합니다.

```sh
agent-session restart --job leader
agent-session restart --job TOOL-012
```

같은 CR의 대화가 유효하면 feedback은 send로 전달합니다.
새 CR은 기존 CR 반납 뒤 start로 배정합니다.

자기 stop·restart의 `accepted: true, completed: false`는 예약 결과입니다.
이 응답을 받으면 현재 turn을 끝냅니다.
Controller의 최종 결과와 현재 연결을 확인한 뒤에만 종료·반납·교체 완료로 판단합니다.
메시지의 accepted·held도 읽음·작업 완료·사용자 승인을 뜻하지 않습니다.
전달·종료 여부가 unknown이면 자동 재전송·강제 종료·배정 삭제로 처리하지 않습니다.
