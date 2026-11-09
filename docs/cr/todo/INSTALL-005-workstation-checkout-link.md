# INSTALL-005: 이 workstation 전환을 위해 설치기가 옛 개발 checkout을 가리키는 진입점 link를 명시 옵션으로 넘겨받습니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3

## Symptom
이 workstation은 `~/.local/bin`의 세 CLI와 skill link가 agent 저장소의 개발 checkout을 가리킵니다. 설치 계약 2절 규칙 1은 설치기 소유가 아닌 같은 이름을 충돌로 보고 전체를 거절합니다. 그래서 이 workstation에서는 설치가 진행되지 않고, agent DIST-001 6단계(무중단 전환)를 할 수 없습니다.

## Evidence
- `readlink ~/.local/bin/agent-session` → `/primehome/swain/Utils/agent/agent.base/codex/tools/agent-session/bin/agent-session`(2026-11-09)
- `readlink -f ~/.claude/skills/project-team` → `/primehome/swain/Utils/agent/agent.base/codex/skills/project-team`
- 설치 계약 2절 규칙 1, INSTALL-001 Contract 5항, agent DIST-001 6단계 2·3·5항

## Contract
- 명시 옵션으로만 켭니다. 대상이 알려진 옛 개발 checkout 경로를 가리키는 symlink일 때만 원자적으로 교체하고, 이전 대상을 설치 기록에 남겨 되돌릴 수 있게 합니다.
- 그 밖의 충돌은 규칙 1대로 거절합니다. 계약 2절에 규칙으로 더합니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). INSTALL-001 Contract 5항이 정한 일을 INSTALL-001에서 떼어 냈습니다(사용자 지시 2026-11-09 "병렬로 진행 가능 한 것은 병렬로 진행해. 남은 CR은 전부 등록해서…"). 승인한 계획(agent DIST-001 6단계를 위한 4단계 요구)의 하위 작업이므로 위임 범위입니다. INSTALL-001이 통합된 뒤 시작합니다.
- 2026-11-09 Leader: agent DIST-001 6단계에 전달할 사항(RELEASE-001 review에서 확인): 옛 통합 파일(agent `tmux/scripts/project_board.conf`)은 hook을 `[board]` 이름으로 넣고, 새 통합 파일은 `[project-agent]` 이름으로 넣습니다. 새 파일을 읽어도 server에 남은 `[board]` hook은 지워지지 않아 Board sync가 두 번 돕니다. 옛 binding은 명령에 `tmux_project_board.sh`가 있어 새 파일이 제품 것으로 보고 바꿉니다(TMUX-001). 이 CR의 Result 보고 때 Leader가 6단계 절차(`set-hook -gu '<event>[board]'`, window scope는 `-gwu`)로 agent Leader에게 함께 알립니다.
- 2026-11-09 Leader: 선행 INSTALL-001이 ecc5bce로 통합되었습니다. 설치기 구조를 따르십시오: 경로는 `paths.Places`의 닫힌 식별자에서만 계산(원칙 A), 되돌림·제거는 설치기가 만든 상태일 때만(원칙 B), 사용자 tmux 파일은 원자적 교체(원칙 C), journal format 2(계약 2절 규칙 5). INSTALL-004와 INSTALL-005는 병렬로 진행하므로 같은 설치기 파일을 고칠 수 있습니다. 제출 전에 `origin/main`을 merge하십시오.

## Implementation
읽을 문서: [설치 계약](../../project-team/install-contract.md) 2절 규칙 1·5·6, 7절, 8절 T11·T12, INSTALL-001의 설치기 코드.

1. 명시 옵션(이름은 구현이 정함, 예: `--adopt-dev-links`)을 `install`에 더합니다. 옵션이 없으면 지금과 같이 규칙 1로 거절합니다.
2. 넘겨받는 조건: 진입점이 symlink이고, 소유자가 현재 사용자이며, 대상이 알려진 옛 모양입니다. 알려진 모양은 `<checkout>/codex/tools/<도구>/bin/<도구>`(세 CLI)와 `<checkout>/codex/skills/<이름>`(두 skill)이고, `<checkout>`은 옵션 값으로 받거나 대상에서 계산해 같은 checkout인지 확인합니다. 하나라도 다르면 그 경로는 충돌로 거절합니다(전체 거절, 규칙 1).
3. 교체는 원자적입니다(임시 link를 만든 뒤 rename). 이전 대상을 설치 기록에 남깁니다.
4. `uninstall`이 넘겨받은 진입점을 지운 뒤 이전 대상으로 되돌릴지 정합니다. agent DIST-001 6단계 5항(되돌리기: link를 동결 사본 쪽으로 원자적으로 되돌림)을 고려합니다. 정한 규칙을 계약 2절에 적습니다.
5. `~/.claude/skills`처럼 부모 디렉터리가 symlink인 경우(규칙 4)를 함께 다룹니다.

범위 밖: 이 workstation에서 실제로 실행하는 일(agent DIST-001 6단계).

의존: 선행 INSTALL-001. 후행 agent DIST-001 6단계, RELEASE-002.

위험 등급: 중간. 이 workstation의 진입점을 바꾸는 기능입니다. 실제 실행은 agent 6단계가 하고, 이 CR은 격리 HOME에서만 검증합니다.

## Verification
1. 옵션 없음: 옛 모양 link가 있으면 T11처럼 전체 거절, snapshot 불변.
2. 옵션 있음: 알려진 모양의 link만 교체되고 설치 기록에 이전 대상이 남습니다. 대상이 알려지지 않은 link, 다른 사용자 소유 link, 서로 다른 checkout을 가리키는 link는 거절되고 snapshot이 같습니다.
3. 교체 중 관찰자가 진입점이 없거나 끊어진 상태를 보지 못합니다(T8과 같은 방식).
4. 4단계에서 정한 `uninstall` 규칙대로 진입점이 남거나 되돌려집니다.
5. 부모 디렉터리가 symlink인 skill 경로에서도 같은 결과입니다.
6. README의 설치기 test 명령과 기존 네 명령이 통과합니다.
