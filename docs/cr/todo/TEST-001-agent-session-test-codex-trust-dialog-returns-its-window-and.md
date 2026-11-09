# TEST-001: agent-session test_codex_trust_dialog_returns_its_window_and_reuses_the_run이 load가 높을 때 6초 제한을 넘겨 실패합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3

## Symptom
병렬 실행(`-n 8`)이나 host load가 높을 때 이 test가 간헐적으로 실패합니다. 단독 실행은 통과합니다. 매 검증에서 알려진 실패로 따로 확인해야 해서 회귀 판정을 흐립니다.

## Evidence
- `tools/agent-session/tests/test_lifecycle.py:328-341`: `env.manager(timeout=6).start(job)` 뒤 `assert time.monotonic() - started < 6`
- agent DIST-004 Result(2026-11-09, load average 30~60): `-n 8` 실행에서 6.24초로 실패, 단독 실행 통과(11.28초)
- REPO-001 Result: 같은 test가 이번에는 통과(간헐)

## Contract
- README의 검증 명령은 load와 무관하게 같은 결과를 내야 합니다. test는 관찰 가능한 동작을 검증하고, host 속도에 기대는 시간 단언은 그 동작의 계약일 때만 둡니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 여러 CR(agent DIST-004, REPO-001, TMUX-001)의 Result에 같은 간헐 실패가 재현 근거와 함께 남아 있습니다. 근거가 있는 결함 수정이므로 위임 범위입니다. 사용자 지시(2026-11-09 "남은 CR은 전부 등록해서 얼마나 남았는지 알 수 있게 해줘")에 따라 열었습니다.

## Implementation
읽을 문서: [README의 검증](../../../README.md#검증), 해당 도구의 README.

1. 근본 원인을 찾습니다. 실패가 test의 기다리는 방식(고정 시간, 화면 갱신 전 조회) 때문인지, 제품 동작(시간 제한, popup 생성 순서) 때문인지 구분하고 근거를 Result에 적습니다.
2. test가 원인이면 관찰 가능한 동작을 기다리는 방식으로 고칩니다. host 속도에 기대는 시간 단언은 그 시간이 제품 계약일 때만 남기고, 남기면 계약 위치를 적습니다. 제품이 원인이면 제품을 고치고 그 동작의 test를 둡니다.
3. 같은 원인의 다른 test가 있으면 같은 방식으로 고치고 목록을 Result에 적습니다. 원인이 다른 실패는 고치지 않고 Leader에게 보고합니다.

의존: 없음. 다른 CR과 병렬로 진행합니다.

위험 등급: 낮음. test 또는 좁은 제품 경로만 바꿉니다.

## Verification
1. 재현(수정 전 실패): load가 높은 조건(예: 해당 suite를 `-n 8`로 돌리면서 같은 test를 반복, 또는 CPU 부하 process를 함께 실행)에서 그 test를 20번 이상 실행해 실패 횟수를 기록합니다.
2. 수정 뒤 같은 조건, 같은 횟수에서 실패 0번입니다.
3. 영향 회귀: 해당 suite 전체(README의 명령)가 통과합니다.
