# SESSION-007: 관리 대화가 스스로 끝나면(/exit, 비정상 종료) 누군가 stop할 때까지 dead pane과 window가 남습니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Base: d4911beec6060bc2f46a88a17e979b1e9a675319 2026-11-09T21:55:14+09:00

## Symptom
관리 대화(Leader·Worker) 안에서 `/exit`하거나 CLI가 비정상 종료하면 pane이 dead로 바뀌고 window가 그대로 남습니다. 정리는 누군가 `agent-session stop`을 실행하거나 다음 start의 sweep이 돌 때만 일어납니다. 사용자 보고(2026-11-09, 11개 요청의 9번): "exit을 해도 pane, window가 최종 destory까지 안됨."

## Evidence
- SESSION-003 재현 표(2026-11-09, `docs/cr/done/SESSION-003-*.md` Result): "대화 안 `/exit`(CLI 종료)만 한 뒤: pane은 dead, window 유지. state 배정·포인터 그대로(반납 전이므로 종료 근거로 남는 것이 명세 동작)". CLI 비정상 종료도 같은 행.
- 명세 3절: 관리 window는 `remain-on-exit on`이고 dead pane을 종료 근거로 남깁니다. 명세 5절: SessionEnd hook이 정상 CLI 종료를 관찰하고(`spec.md:701`), Claude는 turn hook·SessionEnd·실제 process 종료로 작업이 끝났음을 확인합니다(`spec.md:926`).
- SESSION-003은 반납이 끝난 뒤 사용자 pane이 있는 경우만 고쳤습니다(Leader가 CR 범위를 "반납까지 끝난 뒤"로 좁게 쓴 누락).

## Contract
- 사용자가 대화를 끝내면(또는 CLI가 끝나면) 그 run의 마무리(종료 확인, 반납 또는 반납 대기, window 정리)가 누군가의 추가 명령 없이 끝나야 합니다. 보존할 작업을 잃지 않는다는 기존 보호(CR in-progress면 반납하지 않음)는 유지합니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 사용자가 보고한 동작 결함이고 위임 범위입니다. 근본 원인은 run의 마무리가 `stop`이라는 별도 명령에만 묶여 있어, CLI가 스스로 끝난 경우에는 마무리할 주체가 없다는 점입니다(SESSION-001의 게시, SESSION-004의 반납과 같은 모양의 결함).

## Implementation
읽을 문서: [동작 명세](../../project-team/spec.md) 3절(종료한 window 정리, 실행 근거)·5절(hook)·7절(stop), SESSION-003·SESSION-004 Result, [README 검증 표](../../../README.md#검증).

1. 마무리 주체: CLI가 끝났음을 처음 아는 곳(tmux의 `pane-died`, 또는 Claude `SessionEnd` hook)에서 agent-session의 마무리를 실행합니다. 마무리는 `stop`이 종료를 확인한 뒤 하는 일과 같은 함수를 씁니다: 종료 근거를 run 기록에 남김 → 반납(CR이 in-progress면 SESSION-004의 반납 대기) → window 정리(SESSION-003 규칙, 사용자 pane이 있으면 관리 pane만).
2. 종료 근거: 지금 dead pane이 맡는 종료 근거를 window를 닫기 전에 run 기록(또는 state 밖의 실행 근거)에 옮겨, window가 없어도 stop·restart·start가 종료를 확인할 수 있게 합니다. 명세 3절에 먼저 적습니다.
3. 경합: 사용자가 `stop`·`restart`를 실행하는 중이거나 대상 제어 잠금이 잡혀 있으면 마무리는 그 명령에 맡기고 끝납니다(중복 마무리 없음). 실행 중인 restart가 새 run을 띄우는 window는 닫지 않습니다.
4. Leader·Worker 모두 같은 규칙입니다. shutdown으로 끝난 run(재개할 기록이 있음)은 정리하지 않습니다(resume이 씁니다).

의존: 선행 SESSION-003·004(done). 병렬 SESSION-006(`lifecycle.py`·`internal.py`가 겹칠 수 있으니 제출 전 `origin/main` merge).

위험 등급: 중간. 종료 근거의 위치를 바꿉니다. stop·restart·start의 종료 판정이 새 근거로 같은 결과를 내는지 test로 확인합니다.

## Verification
README 검증 표의 `tools/agent-session/**` 행(tmux option·hook을 바꾸면 그 행의 추가 명령과 `integrations/tmux/**` 행).
1. 재현(수정 전): fake provider의 CLI를 스스로 끝내면(정상 종료, 비정상 종료) dead pane과 window가 남고 state 배정이 그대로.
2. 수정 뒤: 같은 경우에 추가 명령 없이 window(사용자 pane이 있으면 관리 pane)가 정리되고, CR이 in-progress가 아니면 반납되며, in-progress면 반납 대기로 남고 다음 `project-item move`가 반납을 마침. 그 뒤 stop·restart·start가 새 종료 근거로 지금과 같은 결과.
3. stop·restart 실행 중에 CLI가 끝나도 마무리가 한 번만 일어남. shutdown으로 끝난 run은 정리되지 않고 resume이 이어받음.
