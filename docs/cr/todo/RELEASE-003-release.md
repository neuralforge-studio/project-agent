# RELEASE-003: 개인 설정이 없는 새 계정에서 release를 시범 설치하고 계약 밖 변경이 없음을 기록합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3
- Mode: read-only

## Symptom
새 계정에서 설치해 계약 밖 변경이 없는지 확인한 기록이 없습니다. 격리 HOME 인수 test(INSTALL-001)는 실제 계정의 shell·tmux·provider 환경을 모두 흉내 내지 못합니다.

## Evidence
- RELEASE-001 Contract 3항: 시범 설치는 INSTALL·TMUX 요청을 통합한 release로, 개인 설정이 없는 계정에서 합니다. 계정 준비는 사용자와 정합니다.
- agent DIST-001 Verification: 새 계정 시범 설치에서 계약 밖의 파일 변경이 없습니다.

## Contract
- 사용자 결정(agent D-20261109-08 C): 설치 중 다른 설정에 영향이 없어야 합니다.
- 계정 준비 방법은 사용자 결정 항목으로 정합니다.

## Disposition
- 2026-11-09 Leader: 판정 보류(open 유지). 계정 준비 방법을 사용자 결정 D-20261109-02로 묻습니다. 선행 INSTALL-001·002·004·005, RELEASE-001·002가 통합된 뒤 결정에 맞춰 Implementation·Verification을 쓰고 판정합니다. 사용자 지시(2026-11-09 "남은 CR은 전부 등록해서 얼마나 남았는지 알 수 있게 해줘")에 따라 RELEASE-001에서 떼어 냈습니다.
- 2026-11-09 Leader: 조사한다(read-only, 사용자 결정 D-20261109-02 C). 사용자 답변 원문(Project Board): "C". 시범 설치는 이 계정에서 빈 디렉터리를 HOME으로 지정한 login shell로 합니다. 같은 uid라서 기본 tmux socket·provider 인증·`/tmp`가 실제 새 계정과 다르며, 이 한계는 Result에 적습니다. 선행 CR이 모두 통합된 뒤 시작합니다.
- 2026-11-09 Leader: 선행에 TMUX-002를 더합니다. 시범 환경(`env -i`의 시스템 PATH)은 `/usr/bin/tmux` 2.7을 만나므로, 최소 버전 판정과 안내가 들어간 뒤 시범 설치해야 실제 새 직원의 경험을 확인할 수 있습니다. 시범 설치에서 PATH 첫 tmux가 2.7인 경우와 사내 3.8을 앞에 둔 경우를 모두 기록하십시오.
- 2026-11-09 Leader: 선행이 모두 통합되었습니다(마지막 TMUX-002 5b73d6a). 원본은 지금 `origin/main`입니다. 시범은 안내문(`docs/install.md`)을 그대로 따르고, 시스템 PATH(첫 tmux가 `/usr/bin/tmux` 2.7)인 경우와 사내 tmux 3.8을 앞에 둔 경우를 모두 기록합니다. 사내 tmux는 `LD_LIBRARY_PATH`가 필요할 수 있습니다(TMUX-002 Result). 안내문이나 설치기의 문제를 찾으면 고치지 말고 Leader에게 보고합니다. 이 workstation의 실제 설치본(`~/.local/lib/project-agent`, agent DIST-005가 설치)은 건드리지 않습니다.

## Implementation
- Mode는 read-only입니다. 제품 코드와 문서를 고치지 않고 commit·push하지 않습니다. 결과는 `## Result`에 씁니다. 안내문이나 설치기의 문제를 찾으면 고치지 않고 Leader에게 보고합니다(Leader가 CR을 엽니다).
- 읽을 문서: RELEASE-002의 직원용 안내문, [설치 계약](../../project-team/install-contract.md) 2·3·4·5·7절, RELEASE-001의 버전 규칙 문서.

> **경고:** 실제 HOME(`/primehome/swain`)의 설정을 바꾸지 않습니다. 기본 tmux server(`/tmp/tmux-<uid>/default`)에 binding·hook을 넣지 않습니다. 시범용 tmux는 반드시 별도 socket(`tmux -L <시범 이름>`)을 씁니다.

1. 기준: 선행 CR이 통합된 `origin/main`의 commit을 원본으로 하고 그 hash를 Result에 적습니다.
2. 시범 환경: 새 빈 디렉터리를 만들어 `HOME`으로 씁니다. `env -i`로 `HOME`, `USER`, `LOGNAME`, `SHELL`, `TERM`, 시스템 기본 `PATH`만 남긴 login shell(`bash -l`)을 엽니다. 개인 rc 파일과 `~/.local/bin`이 없는 상태여야 합니다.
3. 안내문 그대로 따라 합니다: 전제 확인, 한 줄 설치, `check`, PATH 안내, 시범 tmux server(`-L`)에서 설치된 `~/.tmux.conf` 읽기, Board 키와 결정 표시 한 줄, 시범 project(임시 git 저장소) 등록, `project-item new cr`·`ls`, Board 한 번 열기. provider 인증이 없으므로 실제 Claude·Codex 대화 시작은 하지 않고 한계로 적습니다.
4. `upgrade`(같은 원본의 다른 commit 또는 다시 만든 release)와 `rollback`, release 정리 명령, `uninstall`을 안내문대로 실행합니다.
5. 끝나면 시범 tmux server를 끄고 시범 HOME을 지웁니다.

의존: 선행 INSTALL-001·002·004·005, RELEASE-001·002. 후행: 첫 release tag(Leader).

위험 등급: 낮음. 시범 HOME과 별도 tmux socket에서만 실행합니다.

## Verification
1. 시범 HOME의 설치 전후 파일 목록(경로·종류·권한·내용 해시·link 대상) 차이가 계약 2·3절의 경로와 정확히 같습니다. `uninstall` 뒤에는 계약 7절이 남긴다고 한 것(등록 파일 등)만 남습니다.
2. 실제 HOME 불변: 실행 전후로 `~/.local/lib/project-agent`, `~/.local/bin`의 세 이름, `~/.claude/skills`·`~/.codex/skills`의 두 이름, `~/.config/project-agent`, `~/.tmux.conf`, `~/.claude.json`, `~/.codex/config.toml`의 상태(종류·link 대상·내용 해시·`mtime_ns`)가 같습니다. 기본 tmux server의 `list-keys`·`show-hooks -g`·`show-hooks -gw`가 같습니다.
3. 안내문의 단계마다 기대 결과와 실제 결과를 표로 적고, 다른 곳은 재현 명령과 함께 보고합니다.
4. 같은 uid라서 확인하지 못한 항목(provider 로그인, 다른 사용자의 기본 tmux socket·`/tmp` 권한)을 Result에 한계로 적습니다.
