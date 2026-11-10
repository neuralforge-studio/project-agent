# SESSION-014: agent-session start 가 seat 반납 직후 'total wait limit expired' timeout 으로 끝나고 재실행하면 성공 (fc2_cpu 11-10 3회)

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S3
- Related: SESSION-011, SESSION-013
- Requester: fc2_cpu, /primehome/swain/Project/falcon2/git/fc2.cpu.desk, 2026-11-10

## Symptom
- `agent-session start --job <CR> --seat N` 가 `{"ok": false, "error": {"code": "timeout", "message": "The command's total wait limit expired."}}` 로 끝나는 일이 fc2_cpu 에서 2026-11-10 하루에 3 번 있었습니다(seat0 CPUDES-104, seat1 CPUDES-107, seat4 CPUVER-104). 세 번 모두 같은 명령을 다시 실행하면 `ok: true` 로 시작했습니다. 첫 시도 뒤 seat0 window 에는 Claude CLI 대신 `sleep` 만 떠 있는 pane 이 남아 있었습니다(`pane_current_command sleep`).

## Evidence
- 도구: `/primehome/swain/.local/lib/project-agent/releases/0.4.0-ce52466a6354/tools/agent-session/bin/agent-session` (0.4.0-ce52466a6354), provider claude, project fc2_cpu(`/primehome/swain/Project/falcon2/git/fc2.cpu.desk`, seat 0~7, falcon2_design 큰 저장소).
- 같은 날 다른 start(seat2 CPUVER-110, seat0 CPUDES-102, seat2 CPUDES-105, seat4~7 첫 배정 등)는 첫 시도에 성공했습니다. 실패한 세 번은 모두 seat 를 방금 stop 으로 반납한 직후의 start 였습니다(main 동기화·CR branch 준비가 긴 경우로 추정, 확인 안 함).
- 결과 JSON 은 `details: {}` 라 어느 단계에서 시간이 다 됐는지 알 수 없습니다.

## Contract
- start 는 seat 의 main 동기화와 provider 시작이 끝날 때까지 기다리거나, 제한을 넘기면 어느 단계(git sync / tmux / provider registration)에서 멈췄는지와 다시 실행해도 되는지를 결과에 적어야 합니다. 반쯤 만든 window 가 남으면 다음 start 가 그것을 이어받거나 정리해야 합니다.

- Requester: fc2_cpu Leader, /primehome/swain/Project/falcon2/git/fc2.cpu.desk, 2026-11-10

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 다른 project(fc2_cpu)의 재현 기록이 있는 결함입니다. start가 기본 한도 600초를 다 기다린 뒤 단계 정보 없이 끝납니다.
- 2026-11-10 Leader: open -> todo. fc2_cpu 요청, 재현 기록 있는 start 결함

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), [동작 명세](../../project-team/spec.md)의 start·등록, `tools/agent-session/agent_session/lifecycle.py`(start와 `remaining`), SESSION-011 Result, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 원인: fc2_cpu의 실패한 세 start(seat0 CPUDES-104, seat1 CPUDES-107, seat4 CPUVER-104)의 근거를 읽습니다. 근거는 `/primehome/swain/Project/falcon2/git/fc2.cpu.desk/agent/runs/<run_id>/`, `agent/diagnostics/`, state와 남은 window입니다. 다른 project의 파일은 읽기만 합니다. 600초가 어느 단계(main 동기화, window 준비, provider 시작, 등록 대기)에 쓰였는지, pane에 `sleep`만 남은 이유, 다시 실행하면 성공하는 이유를 확인된 사실과 가설로 나눠 적습니다. 0.4.0과 현재 main(SESSION-011·PERF-004·SESSION-013 포함)의 차이가 원인에 닿는지도 적습니다.
2. 원인을 고칩니다. 근거 없이 한도만 늘리지 않습니다.
3. start가 한도를 넘기면 결과의 details에 멈춘 단계와 다시 실행해도 되는지를 적습니다. 반쯤 만든 window가 남으면 다음 start가 이어받거나 정리하는지 확인하고, 아니면 고칩니다.
4. 명세의 해당 문장을 고칩니다.

의존: 없음. SESSION-013(Leader가 main에 통합 중)이 `internal.py`·`providers/claude.py`를 바꿉니다. 제출 전에 `origin/main`을 merge합니다.

위험 등급: 중간. start 경로입니다.

## Verification
1. 원인 단계를 재현하는 test를 둡니다. 수정 전에는 실패해야 합니다. timeout 결과의 details(단계, 재실행 가능 여부) test도 둡니다.
2. README 검증 표에서 바꾼 경로의 행을 모두 실행합니다(`-rf`).
3. 제출 전에 `origin/main`을 merge하고, merge가 입력을 바꾼 명령만 merge commit에서 다시 실행합니다.
4. 속도 CR이 아니므로 측정 도구 A/B는 하지 않습니다. 사용자가 빠른 반영을 요구했습니다.
