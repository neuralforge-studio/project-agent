# TEST-007: test_control_queue의 test가 SESSION-007 이후 main에서 실패합니다(가짜 Tmux에 require_version 없음)

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Base: fec73916af748c9bca5b69ff956d0141076e6d33 2026-11-10T00:42:14+09:00

## Symptom
`tools/agent-session/tests/test_control_queue.py::test_external_control_cannot_overtake_a_pending_self_request`가 main에서 `AttributeError: 'Tmux' object has no attribute 'require_version'`로 실패합니다.

## Evidence
- TEST-006 Result·SESSION-008 Result(2026-11-10): 단독 실행으로도 같은 오류. `lifecycle.py:826`의 restart 경로가 SESSION-007 수정 제출(cf0295a, tmux 최소 버전 확인)에서 `require_version`을 부르게 되었고, 이 test의 가짜 Tmux에는 그 method가 없습니다.
- SESSION-007 수정 제출의 검증은 Leader 지시("바뀐 부분의 test만")로 agent-session 전체 suite가 아니라 일부 파일만 실행해 이 실패를 놓쳤습니다. README 검증 표는 `tools/agent-session/**`를 바꾸면 그 도구의 test 전체를 실행하라고 정합니다(Leader의 지시가 표보다 좁았던 누락).

## Contract
- README 검증 표: agent-session의 test는 main에서 모두 통과해야 합니다. test의 가짜 객체는 제품 interface를 따라가야 합니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 재현 근거가 있는 결함입니다. 앞으로 Leader의 수정 요청도 README 검증 표의 행 단위(도구의 test 전체)를 줄이지 않습니다.

## Implementation
1. 가짜 Tmux가 제품 `Tmux`의 interface를 따라가게 고칩니다. 가짜 객체가 제품 class에 있는 method를 빠뜨리면 test가 곧바로 알리는 방법(예: 가짜를 제품 class에서 파생, 또는 interface 대조 test)을 둡니다. 같은 문제를 가진 다른 가짜 객체가 있으면 함께 고칩니다.
2. 제품 코드는 바꾸지 않습니다(원인이 제품이면 Leader에게 먼저 보고).

의존: 없음.

위험 등급: 낮음.

## Verification
1. 수정 전 실패(main에서 그 test), 수정 뒤 통과.
2. README 검증 표의 `tools/agent-session/**` 행 전체(`tools/agent-session/tests`)가 통과.
