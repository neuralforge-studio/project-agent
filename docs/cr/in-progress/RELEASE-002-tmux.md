# RELEASE-002: 직원용 설치 안내문을 씁니다(전제, 한 줄 설치, 설치가 만드는 경로, 갱신·제거, tmux 연결)

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3
- Base: 77a9bb8fcd6a0728227fe63ea7beb4eb6a6cd0b2 2026-11-09T18:55:26+09:00

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
- 2026-11-09 Leader: 제출 aae91a2c05a6f884f66150f8915a0856fd28fd91를 인수합니다. Leader review: docs/install.md와 README link를 확인했습니다. 전제·설치·check·경로·tmux 연결(고치지 않는 경우와 직접 넣을 줄)·PATH·Board 키·결정 표시·등록을 계약 link로 안내하고 내용을 다시 쓰지 않습니다. 격리 HOME 실행 기록·link 검사·test_distribution_boundary 9 passed를 확인했습니다. Worker 질문(tmux 최소 버전)은 결정 사항이 아니라 호환성 결함이므로 TMUX-002로 열어 Leader 판정으로 고칩니다. 안내문의 tmux 전제 줄은 TMUX-002가 확정 값으로 고칩니다.

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

## Result
- 제출 commit: aae91a2c05a6f884f66150f8915a0856fd28fd91

변경: `docs/install.md`(직원용 설치 안내문, 한국어)와 README 관련 문서의 link 한 줄. 코드·테스트는 바꾸지 않았습니다. Base 77a9bb8 위에 commit 2개이며 `origin/main`은 진행하지 않아 merge가 없습니다. `origin/cr/RELEASE-002`에 push했습니다.

안내문의 구성: 전제(Python 3.10+, tmux, git, provider CLI, Board용 textual) → 설치(`--dry-run`, 한 줄 설치, `check`) → 설치가 만드는 경로와 tmux 파일을 고치지 않는 경우 → PATH·실행 중 tmux server 재읽기·Board 키·결정 대기 표시 → project 등록과 base `agent/`의 untracked 처리 → 갱신·되돌리기·`prune` → 제거와 `uninstall` 거절 해소 → 문제 확인표. 계약은 link하고 한 문장 요약만 적었습니다. `--adopt-dev-links`는 넣지 않았습니다.

검증:
1. 격리 HOME에서 안내문의 명령을 순서대로 실행했습니다. 실제 HOME·실제 tmux server는 쓰지 않았습니다(`HOME`·`TMPDIR`을 scratchpad 아래로, `TMUX_TMPDIR`을 격리 socket 디렉터리로, `AGENT_SESSION_*`을 지움). Python은 `/primehome/tools/Inhouse/Python3/latest/bin/python3`(3.12.13, textual 있음), tmux는 사내 3.8입니다. checkout은 5393fbb(안내문 첫 commit)의 clone입니다.
   - `install --dry-run` → `install`: 계약 2절의 경로(release, `current`, `tmux.conf`, shim 3, skill link 2, 등록 초안, `~/.tmux.conf` 블록, `install.json`)가 만들어짐. `check`: `Note: ~/.local/bin is not in PATH.` 뒤 `OK`, 종료 코드 0. PATH에 `~/.local/bin`을 넣은 뒤 `agent-session --help`가 나옴.
   - 실행 중 tmux server에 `tmux source-file ~/.local/lib/project-agent/tmux.conf`: 종료 코드 0, prefix `B`가 Board toggle로 binding됨. `@project_agent_board_key X`를 정하고 다시 읽으면 prefix `X`가 binding됨(이전 `B`는 남으므로 안내문에 `unbind-key B`를 적음). `status-right`에 `#{E:@project_agent_decide_status}` 추가가 적용됨. 사용자가 `B`를 미리 binding한 경우 `@project_agent_board_skipped`가 `prefix:B`이고 `check`가 "Binding skipped (binding 건너뜀)"을 알림(종료 코드 0).
   - 등록: 초안 `{}`를 안내문의 예로 바꾸고 base에서 `project-item ls`가 종료 코드 0으로 끝남(항목 디렉터리가 없으면 `no directory yet`). `project-item new cr`로 `agent/cr/open/…md`를 만듦. 안내문의 ignore 목록을 `.git/info/exclude`에 넣기 전에는 `agent/state.json` 등 열 개가 untracked로, 넣은 뒤에는 CR 파일만 untracked(추적 대상)로 남음.
   - `upgrade`(commit을 더한 scratch upstream을 `git pull`한 뒤): `current`가 0.1.1로 바뀌고 이전 release가 남음. `rollback`: `current`가 0.1.0으로 돌아옴. 세 번째 release(0.1.2) 뒤 `prune`: 0.1.0만 지우고 `current`·`previous`를 남김. 같은 release의 `upgrade`와 `previous`가 없는 `rollback`은 안내문대로 "No change"·`no_previous`.
   - `uninstall`: leader의 `unknown` run을 기록한 state가 있으면 `runs_alive`로 거절(종료 코드 3, 출력이 `run example leader (unknown)`). state를 없앤 뒤 `uninstall`: 설치한 경로가 모두 지워지고 `~/.tmux.conf`(설치 전에 없었음)도 없어짐. 남은 것은 등록 파일과 `~/.cache/project-item/locks`. 그 뒤 `install`을 다시 하면 그 사이 생긴 `~/.codex`의 skill link가 만들어짐(안내문 1·7절의 "홈이 생기기 전에 설치했다면"과 일치). `install`을 다시 실행하기만 하면 "No change"로 link를 더하지 않음을 확인해 안내문에 적음.
   - tmux 설정이 symlink인 HOME: 설치 종료 코드 0, 출력이 "~/.tmux.conf is a symlink, so it was not changed"와 넣을 줄을 알리고 `check`가 "Manual connection needed (수동 연결 필요)"를 알림(실패 아님). 링크 대상 파일은 변하지 않았고 `uninstall` 뒤 symlink가 그대로임.
   - textual이 없는 Python(`/usr/bin/python3.11`)으로 설치: 설치 종료 코드 0, `check`가 `Project Board needs textual==8.2.8 in … (not installed)`를 알림(종료 코드 0).
2. 안내문과 README의 상대 link·`#anchor`를 script로 검사했습니다(대상 파일과 제목 모두 존재, 불일치 0).
3. `python3 -m pytest -q tools/test_distribution_boundary.py`: 9 passed. `docs/install.md`에 개인 지침 참조 패턴이 없음을 grep으로도 확인했습니다.

실행하지 않은 것: 실제 provider 대화로 만든 run의 `stop`·`resume`으로 `uninstall` 거절을 푸는 단계, 형식 버전이 다른 release로의 `upgrade`(`formats_differ`). 두 경우는 설치 계약 7.1.1·7.2절이 원본이며 `install/tests`의 T10·T29가 검증합니다. 안내문은 그 계약을 link합니다. 가짜 state의 `stop`은 `execution_unknown`을 반환했으므로 안내문은 그때 명세의 수동 복구 절로 안내합니다.

Leader에게 알릴 사항:
- 설치 계약·README에 tmux 최소 버전이 없습니다. 안내문에는 "3.8에서 검증, 2.7은 통합 파일의 `{ }` 문법을 읽지 못해 동작하지 않음, 그 사이는 미검증"만 적었습니다. 이 workstation의 `/usr/bin/tmux`는 2.7이어서 PATH 순서에 따라 이 문제가 실제로 생깁니다. 최소 버전 결정은 이 CR 범위 밖입니다.
- 설치기는 `check`의 `run_unjudgeable` 출력에서 사유(`details.reason`)를 `--json`에서만 보입니다. 제품 코드는 바꾸지 않았고 안내문에 `--json`으로 확인하라고 적었습니다.
- 설치 안내문은 `docs/install.md`이며 `tools/test_distribution_boundary.py`의 `PRODUCT_PATHS`(`docs/project-team`만 포함)에는 들어 있지 않습니다. 필요하면 후속으로 더합니다.
- 안내문의 clone URL은 `origin`(`ssh://git@git.primemas.com:222/swain/project-agent.git`)입니다. 직원용 배포 위치와 release tag(`v0.1.0`) 안내는 RELEASE-003이 정할 때 안내문의 2절을 맞춥니다.
