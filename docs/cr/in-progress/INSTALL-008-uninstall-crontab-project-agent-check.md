# INSTALL-008: uninstall 뒤 crontab에 project-agent의 check 작업이 남아 조용히 실패합니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S3

## Symptom
SESSION-015 뒤 Leader를 시작하면 사용자 crontab에 project 구역(`check` 작업)이 생깁니다. 이 작업의 명령은 Leader를 시작한 release의 `bin/agent-session`을 가리킵니다. 설치기 `uninstall`은 crontab을 고치지 않으므로, 제거한 release를 가리키는 작업이 30분마다 남아 실패합니다. 출력은 버려지므로 실패가 보이지 않습니다.

## Evidence
- SESSION-015 Result: "`uninstall`은 crontab을 고치지 않으므로(설치 계약 5.4절에 적음) 제거한 release를 가리키는 `check` 작업이 남습니다. 출력이 버려져 조용히 실패합니다. `agent-session cron rm`으로 지웁니다. 설치기가 지우게 할지는 별도 판단이 필요합니다."
- 설치 계약 3.1절 4·5항: 통합 파일이 넣은 tmux binding·hook은 `uninstall`이 되돌리는 명령을 출력하고 실행하지는 않습니다. 실행 중인 server를 바꾸지 않는 원칙입니다.
- crontab 구역 형식과 `agent-session cron`의 원본은 [동작 명세](../../project-team/spec.md) 7절 cron입니다(SESSION-015).

## Contract
- `uninstall`(그리고 `uninstall --dry-run`)은 사용자 crontab에 남은 project-agent 구역을 찾아 알리고, 지우는 명령(project마다 `agent-session cron rm …`, 또는 같은 효과의 명령)을 출력합니다. tmux binding을 되돌리는 명령을 출력하는 방식과 같습니다. 구역 밖의 사용자 줄은 건드리지 않습니다.
- 지우기를 직접 실행할지, 출력만 할지는 설치 계약 3.1절의 원칙(실행 중 상태를 바꾸지 않음)과 맞춰 정하고 그 근거를 계약에 적습니다.
- `check`(설치 점검)는 구역의 명령이 가리키는 release가 없으면 그 사실을 알립니다.

## Disposition
- 2026-11-11 Leader: 고친다(Leader 판정). 승인한 작업(SESSION-015)에서 나온 하위 결함입니다. 제거한 설치본의 작업이 crontab에 남아 조용히 실패합니다.
- 2026-11-11 Leader: open -> todo. Leader 판정: SESSION-015 하위 결함

## Implementation
읽을 문서: [설치 계약](../../project-team/install-contract.md) 3.1·5.4·7·8절, `install/project_agent_install/commands.py`(`uninstall`, `check`, `binding_undo`), [동작 명세](../../project-team/spec.md) 7절 cron, `tools/agent-session/agent_session/cron.py`(구역 읽기), `tools/tests/fake_crontab.py`, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. Contract를 구현합니다. 구역 해석은 `cron.py`의 형식을 따릅니다. 형식을 다시 정의하지 않습니다.
2. 설치 계약에 uninstall·check의 crontab 처리와 인수 test 번호를 더합니다.
3. Test: 구역 없음·하나·여럿, 사용자 줄 보존, dry-run, check의 없는 release 알림. 실제 crontab은 쓰지 않습니다(`fake_crontab`).

의존: SESSION-015가 통합된 뒤 시작합니다.

위험 등급: 낮음.

## Verification
1. README 검증 표의 `install/**` 행(`install/tests`)과 바꾼 문서 행.
