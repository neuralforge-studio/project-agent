# RELEASE-002: 직원용 설치 안내문을 씁니다(전제, 한 줄 설치, 설치가 만드는 경로, 갱신·제거, tmux 연결)

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3

## Symptom
다른 직원이 읽고 따라 할 설치 안내문이 없습니다.

## Evidence
- RELEASE-001 Symptom·Evidence(전제: Python 3.10 이상, tmux, Claude Code 또는 Codex CLI. 설치 계약 9.1절: 새 project base의 `agent/` 아래 실행 파일이 untracked로 보임, PATH에 `~/.local/bin`이 없을 때의 안내)
- 설치 계약 3절(tmux 블록, 다시 읽는 명령), 5.3절(결정 대기 표시 한 줄 `set-option -ag status-right '#{E:@project_agent_decide_status}'`)
- agent DIST-001 7단계

## Contract
- 사용자 결정(agent D-20261109-08 C): 다른 직원에게 배포하며 설치 중 다른 설정에 영향이 없어야 합니다.
- 안내문은 설치 계약을 다시 쓰지 않고 link합니다. 직원이 할 일과 확인할 결과만 적습니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). RELEASE-001에서 떼어 낸 직원용 안내문입니다(사용자 지시 2026-11-09 "남은 CR은 전부 등록해서 얼마나 남았는지 알 수 있게 해줘"). 승인한 계획 agent DIST-001 7단계의 하위 작업이므로 위임 범위입니다. 설치기 명령이 확정되는 INSTALL-001·002·004·005와 RELEASE-001이 통합된 뒤 시작합니다.
- 2026-11-09 Leader: 선행이 모두 통합되었습니다(INSTALL-001 ecc5bce, INSTALL-002 298ea6e, INSTALL-005 e49f466, INSTALL-004 0d6e99b, RELEASE-001 0cbacc6). 안내문이 다룰 명령은 설치기 `--help`와 계약 7절이 원본입니다(`install`·`upgrade`·`rollback`·`prune`·`uninstall`·`check`, `--dry-run`). `--adopt-dev-links`는 이 workstation 전환용이므로 직원 안내에 넣지 않습니다. Board 전제(설치 interpreter의 textual, D-20261109-01 waive)와 tmux 파일을 고치지 않는 경우(계약 3절: symlink·hard link·다른 소유자·읽기 전용·ACL/xattr·1 MiB 초과)의 안내를 포함합니다. 검증 1의 명령 실행은 격리 HOME(`HOME=<빈 디렉터리>`, 별도 tmux socket)에서만 합니다.

## Implementation
읽을 문서: [설치 계약](../../project-team/install-contract.md) 전체, RELEASE-001의 버전 규칙 문서, INSTALL-001·002·004·005의 Result.

1. 직원용 안내문 한 개를 씁니다(위치 예: `docs/install.md`, 한국어). README의 관련 문서에 link합니다.
2. 내용(직원이 할 일과 확인할 결과만):
   - 전제: Python 3.10 이상, tmux, Claude Code 또는 Codex CLI. Board는 설치 interpreter에 `textual`(`tools/project-board/requirements.txt`의 버전)이 있어야 합니다(사용자 결정 D-20261109-01 waive). 사내 Python에는 있습니다.
   - 한 줄 설치 명령, 설치 뒤 `check`로 확인하는 방법.
   - 설치가 만드는 경로와 고치는 기존 파일: 계약 2절·3절 link와 한 문장 요약.
   - PATH에 `~/.local/bin`이 없을 때, 실행 중 tmux server에 다시 읽는 명령, 결정 대기 표시를 status에 넣는 한 줄(계약 5.3절), Board 키 바꾸기(`@project_agent_board_key`).
   - project 등록 파일 위치와 첫 등록, 새 project base의 `agent/`가 untracked로 보일 때의 처리(계약 9.1절).
   - 갱신·되돌리기·제거, 오래된 release 정리, `uninstall`이 거절되는 경우와 해소 방법(계약 7.2절).
3. 계약의 내용을 다시 쓰지 않고 link합니다. 명령과 옵션의 원본은 설치기의 `--help`입니다.

의존: 선행 INSTALL-001·002·004·005, RELEASE-001. 후행 RELEASE-003.

위험 등급: 낮음. 문서만 씁니다.

## Verification
1. 격리 HOME(INSTALL-001 하네스 또는 임시 `HOME`)에서 안내문의 명령을 순서대로 실행해 안내한 결과가 나옵니다. 실행 기록을 Result에 적습니다. 실제 HOME에서는 실행하지 않습니다.
2. 안내문의 Markdown 상대 link가 실제 파일을 가리킵니다.
3. `tools/test_distribution_boundary.py`가 통과합니다.
