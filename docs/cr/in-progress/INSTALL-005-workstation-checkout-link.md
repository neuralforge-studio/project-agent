# INSTALL-005: 이 workstation 전환을 위해 설치기가 옛 개발 checkout을 가리키는 진입점 link를 명시 옵션으로 넘겨받습니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3
- Base: 4c4168325298d1ae1515696acbc16417de5d152e 2026-11-09T17:40:07+09:00

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
- 2026-11-09 Leader: 제출 f4253c5 수정 요청(한 항목). 넘겨받기 조건·기록(`adopted_from`)·uninstall의 원자적 되돌림·T24~T28과 수정 전 23/24 실패를 확인했습니다. 결함: 정방향 교체 `swap_link`(`actions.py:487-490`)가 계획 때 읽은 link 글자를 undo에만 적고, 실행 때 지금 글자가 그것과 같은지 확인하지 않고 바꿉니다. 계획과 실행 사이(release 만들기)에 사용자가 link를 바꾸면 그 link를 덮어쓰고 옛 글자를 기록합니다(원칙 B). CHANGELOG 항목은 Leader가 통합 때 씁니다(버전 규칙 5절). Result의 6단계 참고 사항(`~/.codex/skills/project-*`가 실제 디렉터리)은 통합 뒤 Leader가 agent Leader에게 알립니다.
- 2026-11-09 Leader: 제출 b5f74a11b10e184ec1cf0c0cca60913743e2e432를 인수합니다. Leader review: 수정 delta(swap_link가 실행 직전에 link 글자·소유자를 계획 때와 대조하고 다르면 Changed로 실패해 되돌림, CHANGELOG 변경 제거)를 확인했습니다. T29 수정 전 실패, install/tests 221 passed·2 skipped. 이전 검토(f4253c5의 넘겨받기 조건·adopted_from·uninstall 원자적 되돌림·T24~T28)를 재사용합니다.

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

## Result

- 제출 commit: b5f74a11b10e184ec1cf0c0cca60913743e2e432

### 구현
- `install --adopt-dev-links CHECKOUT`(install에만). 옵션이 없으면 규칙 1대로 전체 거절(T24).
- 넘겨받는 조건: symlink, 소유자가 현재 사용자, link 글자가 `codex/tools/<도구>/bin/<도구>`·`codex/skills/<이름>`으로 끝남(상대 글자 포함), 가리키는 곳이 `CHECKOUT`의 그 경로와 같은 파일. 하나라도 어긋나면 전체 거절(T26). 판정은 `commands._adopt_dev_link`, 모양은 `paths.Places.dev_target`·`dev_shaped`(원칙 A: 설치 기록의 `adopted_from`도 같은 모양일 때만 받음).
- 교체는 기존 `swap_link`(임시 link 후 rename)이며 undo 스펙이 이전 글자를 갖습니다. 설치 기록 항목에 `adopted_from`.
- `uninstall` 규칙(계약 2절 규칙 8): 넘겨받은 진입점은 지우지 않고 `adopted_from`으로 원자적으로 되돌립니다. 설치기가 만든 link일 때만(사용자가 바꿨다면 알리고 둠). 되돌림은 release·`current` 삭제보다 먼저 해서 제거 도중 진입점이 끊어지지 않습니다. 규칙 6의 runtime link는 종전대로 지웁니다. 되돌림 step은 journal의 `swap` redo 스펙이라 중단돼도 다음 `uninstall`이 마칩니다(journal format 2 그대로).
- 부모가 symlink인 skill 경로(규칙 4): 상대 글자는 link가 실제로 놓인 디렉터리 기준으로 풉니다. 이 workstation의 `~/.claude/skills`는 개발 checkout의 `claude/skills`라 그 안의 link 파일이 바뀝니다(출력에 실제 위치 표시).
- Leader 피드백 1차 반영(f4253c5 검토): `actions.swap_link`가 실행 때 link의 글자와 소유자가 계획 때와 같은지 확인하고, 다르면 `Changed`로 실패해 되돌립니다(`_op_swap`과 같은 판정, 사용자가 바꾼 link는 덮어쓰지 않음). 모든 `swap_link` 사용(현재 release 교체, runtime link 넘겨받기 포함)에 적용됩니다. 계획 뒤 link를 바꾸는 T29(shim·Claude skill·Codex skill)를 수정 전 실패(종료 코드 0, 사용자 link 덮어씀)로 먼저 두었고 수정 뒤 통과합니다. CHANGELOG 변경은 뺐습니다(Leader가 통합 때 씀).
- 계약: 2절 규칙 1 예외·규칙 8, 7절 옵션·install·uninstall 행, 8절 T24~T28 추가. README test 범위 T1~T28.

### 검증 (제출 commit 기준, 격리 HOME에서만 실행)
| Verification | 결과 |
| --- | --- |
| 1 옵션 없음 | T24 통과: 일곱 경로 나열, 종료 코드 3, HOME·checkout snapshot 불변 |
| 2 옵션 있음 | T25 통과: 알려진 모양만 교체, `adopted_from` 기록(상대 글자 byte 동일), `check` 통과. 거절 T26(모양 다름·다른 checkout·파일·디렉터리·다른 사용자 소유·옵션 checkout 불일치·상대 link가 다른 곳) 모두 snapshot 동일 |
| 3 교체 중 관찰자 | T28 통과: 일곱 진입점을 계속 `stat`하는 thread가 install·uninstall 동안 없음/끊김을 못 봄 |
| 4 uninstall | T25 통과: 설치 전 snapshot과 같아짐. 사용자가 바꾼 link는 건드리지 않음. 변조된 `adopted_from`은 `record_invalid`(3) |
| 5 부모 symlink | T27 통과 |
| 6 README 명령 | `install/tests` 218 passed, 2 skipped (새 24건 포함). `tools/project-item/tests` 120, `tools/project-board/tests` 114, tmux·launcher·boundary·private_root·release_files 70 모두 통과. `tools/agent-session/tests` 729 passed, 1 failed |

- agent-session 실패 1건: `test_lifecycle.py::test_registration_publishes_when_the_controller_ends_before_it[sigint]`가 host 부하(다른 seat의 pytest 동시 실행)에서 subprocess 60초 시간 초과. 같은 test를 다시 실행해 통과(4 passed). 이 CR은 `tools/`를 바꾸지 않았습니다.
- 근거 재사용·재실행: 전체 검증은 구현·문서 확정 뒤 제출 commit과 같은 내용에서 한 번 실행했습니다. `origin/main`은 Base(4c41683)에서 진행하지 않아 merge가 없었습니다. 새 test는 옛 설치기(`PROJECT_AGENT_INSTALLER`)로 23/24건이 실패해 새 동작을 검증함을 확인했습니다.

### Leader·agent DIST-001 6단계에 알릴 사항 (읽기 전용으로 확인, 2026-11-09)
- 이 workstation의 `~/.codex/skills/project-team`·`project-item`은 symlink가 아니라 실제 디렉터리입니다. 이 옵션이 넘겨받지 못하므로 규칙 1로 거절됩니다. 6단계가 따로 다뤄야 합니다(이 CR 범위 밖).
- `~/.claude/skills`는 `agent.base/claude/skills`로 가는 symlink이고 안의 link는 상대 글자(`../../codex/skills/<이름>`)입니다. 옵션을 쓰면 그 checkout 안의 link 파일이 바뀝니다(git 상태 영향 가능).
- 되돌리기(6단계 5항): `uninstall`이 진입점을 이전 대상으로 되돌리지만 설치 전체를 제거합니다. link만 따로 되돌리는 명령은 없습니다.
- 이 CR은 이 workstation에서 실제로 실행하지 않았습니다(범위 밖).

### 수정 제출 검증 (b5f74a1)
- `install/tests`(제출 commit에서 한 번): 221 passed, 2 skipped. 새 `test_adopt.py` 27건은 단독으로 두 번 더 반복해 모두 통과했습니다.
- 다른 suite(agent-session·project-item·project-board·tmux 등)는 이전 제출의 결과를 재사용합니다. 이 수정은 `install/`과 문서만 바꿉니다.
