# SESSION-004: Worker가 끝났는데 CR이 in-progress라 반납이 거절되면 seat가 배정된 채 놀게 됩니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2

## Symptom
다른 project의 Leader 보고(사용자 전달): RUST-058 조사가 16:20쯤 끝났는데 Leader가 CR을 done으로 옮기기 전에 seat1을 stop해서 "CR이 아직 진행 중"이라 반납이 거절됐고, Leader가 다른 일을 하는 동안 seat1이 약 40분 놀았습니다. 사용자 요청: "이런일이 발생하지 않게 script 보완 필요."
출처: 사용자 개선 요청 2026-11-09(대화, 11개 항목 중 10번).

## Evidence
- `agent-session stop`은 CR이 in-progress에 남아 있으면 반납하지 않고 `released: false`와 이유를 돌려줍니다(project-team skill Leader 절, 명세 7절). 그 뒤 반납은 Leader가 CR을 옮긴 다음 stop을 다시 실행해야 일어납니다.
- 반납 거절 상태를 알리는 장치(Board 표시, 알림)는 없습니다.

## Contract
- Worker가 끝난 seat는 사람의 기억에 기대지 않고 반납이 끝나야 합니다. 보존할 작업이 있는 CR을 잃지 않는다는 기존 보호는 유지합니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 운영에서 seat가 40분 논 결함이고, 사람의 순서에 기대는 설계가 원인이므로 위임 범위입니다. 사용자 지시(2026-11-09 대화): "위와 같이 11개의 개선 요청 사항이 있어."

## Implementation
읽을 문서: [동작 명세](../../project-team/spec.md) 3·7절, [project-team skill](../../../skills/project-team/SKILL.md), [README 검증 표](../../../README.md#검증).

근본 원인: 반납이 "CR이 in-progress에서 나간 뒤 Leader가 stop을 다시 실행"하는 두 번째 수동 단계에 달려 있습니다. stop이 거절된 뒤 그 seat는 끝난 Worker를 가진 채 배정 상태로 남고, 이를 완료할 주체가 없습니다.

1. 반납 보류 상태를 기록합니다. stop이 실제 종료를 확인했지만 CR이 in-progress라 반납하지 못하면, 그 seat에 "반납 대기"와 이유를 state 밖의 실행 근거(window option 또는 run 기록)에 남깁니다. state의 배정은 지금처럼 유지합니다(작업 보존).
2. 반납을 CR 이동에 묶습니다. Leader가 `project-item move`로 그 CR을 in-progress에서 옮기면(done·todo·open·deferred), 같은 명령이 반납 대기인 seat의 반납을 마칩니다. 반납 조건(결과가 origin에 있음 등)은 지금 stop의 판정을 그대로 씁니다. 조건이 맞지 않으면 반납하지 않고 그 이유를 출력합니다.
3. 순서가 반대인 경우(CR을 먼저 옮기고 stop)는 지금처럼 동작합니다.
4. Board sidebar와 `project-item ls`가 반납 대기 seat를 보이게 합니다(Leader가 놓쳐도 보임).
5. 명세 7절 stop과 project-team skill Leader 절의 문장을 새 동작에 맞춥니다.

의존: 선행 없음. 후행 SESSION-003.

위험 등급: 중간. 반납 판정을 project-item 명령에서도 부릅니다. 도구 경계(`agent_session.api`만 사용)를 지킵니다.

## Verification
1. 재현(수정 전): stop을 CR이 in-progress일 때 실행 → `released: false`, 이어 CR을 done으로 옮겨도 seat가 배정된 채 남음.
2. 수정 뒤: 같은 순서에서 `project-item move`가 반납을 마치고 seat가 비며, 다음 start가 그 seat를 쓸 수 있음. 결과가 origin에 없는 등 반납 조건이 맞지 않으면 반납하지 않고 이유를 출력. Board·`project-item ls`에 반납 대기 표시.
3. README 검증 표의 `tools/agent-session/**`·`tools/project-item/**` 행(공개 API를 바꾸면 그 표의 추가 행).
