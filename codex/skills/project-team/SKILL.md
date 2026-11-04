---
name: project-team
description: "등록 프로젝트의 tmux Leader·Worker를 agent-session으로 시작·배정·통신·인계·종료합니다. 프로젝트 팀 운영이나 seat에서 JOB을 수행할 때 사용합니다. 일반 개발 작업 자체에는 적용하지 않습니다."
---

# Project Team

세션 관리는 설치한 `agent-session`으로 수행합니다.
명령의 상세 입력과 오류는 `agent-session --help`와 해당 하위 명령의 `--help`에서 확인합니다.
등록·상태·provider 계약을 확인할 때는 [동작 명세](../../../docs/project-team/spec.md)를 읽습니다.

## 프로젝트와 역할

- 등록 base 또는 seat 안에서 명령을 실행합니다. 현재 경로로 프로젝트를 선택합니다.
- Provider와 seat 경로는 등록 파일에서 읽습니다. 실행할 때 다시 지정하지 않습니다.
- 전달받은 역할과 공식 JOB을 사용합니다. 실제 배정은 `<base>/agent/state.json`에서 확인합니다.
- 상태 JSON과 tmux 소유 정보를 직접 편집하여 배정을 변경하지 않습니다.

Start의 `--job`은 `leader` 또는 공식 JOB 파일 경로입니다.
다른 명령의 `--job`은 `leader` 또는 배정된 JOB ID입니다.
Worker seat는 start가 자동으로 선택합니다.

## Leader

1. 사용자 지시에서 작업 범위와 완료 기준을 정합니다.
2. 프로젝트의 공식 JOB writer로 작업을 만듭니다. [JOB 양식](assets/job.md)의 metadata를 사용합니다.
3. 실제 사용자 승인 근거를 기록합니다. 근거 확인 전에는 `approved`를 true로 만들지 않습니다.
4. `agent-session start --job /absolute/path/JOB.md`로 Worker를 시작합니다.
5. 제출한 hash와 실제 검증 결과를 review합니다. 수정이 필요하면 같은 JOB에 feedback을 보냅니다.
6. 프로젝트의 승인 범위에서 검토한 hash를 통합하고 원격 반영과 인수를 기록합니다.
7. Worker의 정리 완료를 확인한 뒤 stop으로 실제 종료와 반납을 확인합니다.

```sh
agent-session start --job leader
agent-session send --job J-20261103-07 --file FEEDBACK.md
agent-session stop --job J-20261103-07
```

제출 hash가 바뀌면 새 hash를 다시 검토합니다.
완료 보고만으로 JOB을 인수하거나 seat를 비우지 않습니다.
`released: false`이면 배정을 보존하고 반환한 이유를 처리합니다.

Codex의 동료 보고는 현재 turn이 끝난 뒤 처리될 수 있습니다.
배정·feedback 뒤 외부 보고만 기다리는 시점에는 현재 turn을 끝냅니다.
Tmux window와 provider session은 유지하고 후속 메시지에서 관리를 이어갑니다.
같은 turn에서 보고를 기다리며 반복 조회하지 않습니다.
보고를 받으면 현재 공식 JOB 원본·run·제출 hash를 대조합니다.
이전 run이나 종결 JOB의 늦은 보고만으로 완료한 JOB을 다시 배정하지 않습니다.

## Worker

1. 공식 JOB의 범위·작업 경로·승인·검증 기준과 현재 배정을 확인합니다.
2. 지정한 범위에서 작업하고 해당 검증을 수행합니다.
3. JOB에서 승인한 commit·push를 수행하고 실제 제출 hash와 검증 결과를 공식 writer에 기록합니다.
4. `agent-session send --job leader "결과와 공식 JOB 경로"`로 보고합니다.
5. 같은 JOB의 feedback을 받으면 해당 범위의 작업·검증·제출을 반복합니다.
6. Leader가 인수하면 자기 작업의 불필요한 산출물을 정리하고 종료를 보고합니다.

최초 Git 동기화·기준 기록·JOB branch 준비는 start가 수행합니다.
Worker는 이를 다시 실행하여 기준을 바꾸지 않습니다.
Read-only 작업은 업무 branch·제품 코드를 변경하거나 commit·push하지 않습니다.
정리할 때는 자기 작업의 산출물만 제거합니다. 보존할 변경과 사용자 파일을 일괄 삭제하지 않습니다.
Commit 형식은 프로젝트 규약을 우선하며 공통 초안은 [commit 양식](assets/commit-message.txt)을 사용합니다.

## 인계와 제어 결과

Restart는 새 대화 ID를 만듭니다.
이전 대화는 보존하고 현재 JOB·인계 문서로 작업을 이어받습니다.
Seat·JOB·시작 Git 기준·branch는 유지합니다.
재시작 전에 현재 HEAD·미완료 작업·제출·다음 행동을 프로젝트의 인계 원본에 기록합니다.

```sh
agent-session restart --job leader
agent-session restart --job J-20261103-07
```

같은 JOB의 대화가 유효하면 feedback은 send로 전달합니다.
다른 JOB 파일을 send해도 새 JOB으로 배정되지 않습니다.
새 JOB은 기존 JOB 반납 뒤 start로 배정합니다.

자기 stop·restart의 `accepted: true, completed: false`는 예약 결과입니다.
이 응답을 받으면 현재 turn을 끝냅니다.
Controller의 최종 결과와 현재 연결을 확인한 뒤에만 종료·반납·교체 완료로 판단합니다.
메시지의 accepted·held도 읽음·작업 완료·사용자 승인을 뜻하지 않습니다.
전달·종료 여부가 unknown이면 자동 재전송·강제 종료·배정 삭제로 처리하지 않습니다.
