# SESSION-003: exit 뒤에도 pane·window가 끝까지 정리되지 않습니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2

## Symptom
사용자 보고: "exit을 해도 pane, window가 최종 destory까지 안됨." 어느 exit(관리 대화의 `/exit`, `agent-session stop`, CLI 비정상 종료)인지는 아직 구분하지 않았습니다.
출처: 사용자 개선 요청 2026-11-09(대화, 11개 항목 중 9번).

## Evidence
- 관리 window는 `remain-on-exit on`이고, 명세는 종료 근거로 dead pane을 남기며 managed pane만 남은 window를 정리 대상으로 봅니다([명세 3절 종료한 window 정리](../../project-team/spec.md#종료한-window-정리)).

## Contract
- 종료가 확인되고 반납까지 끝난 run의 window·pane은 사용자가 붙인 pane이 없으면 남지 않아야 합니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 재현 가능한 동작 결함이므로 위임 범위입니다. SESSION-004가 stop·반납 경로를 고치므로 그 뒤에 시작합니다. 사용자 지시(2026-11-09 대화): "위와 같이 11개의 개선 요청 사항이 있어."

## Implementation
읽을 문서: [동작 명세](../../project-team/spec.md) 3·7절, [project-team skill](../../../skills/project-team/SKILL.md), [README 검증 표](../../../README.md#검증).

1. 재현: 관리 대화를 끝내는 경로(대화 안의 `/exit`, `agent-session stop`, `restart`, CLI 비정상 종료, `shutdown`)마다 끝난 뒤 window·pane이 어떻게 남는지와 언제 정리되는지(다음 start의 sweep 등) 기록합니다.
2. 원인 확정: 명세가 종료 근거로 dead pane을 남기는 이유와, 정리가 일어나지 않는 경로를 구분합니다. 근거를 남겨야 하는 동안은 남기되, 반납까지 끝난 뒤에도 남는 경우가 결함입니다.
3. 고침: 종료가 확인되고 반납이 끝난 run의 window는 사용자가 붙인 pane이 없으면 그 시점에 정리합니다. 사용자 pane이 있으면 managed pane만 정리합니다. 규칙을 명세 3절 "종료한 window 정리"에 먼저 적습니다.

의존: 선행 SESSION-004.

## Verification
1. 1단계의 경로마다 수정 전 남음과 수정 뒤 정리됨(사용자 pane이 있는 경우 포함), 격리 tmux.
2. README 검증 표의 `tools/agent-session/**` 행.
