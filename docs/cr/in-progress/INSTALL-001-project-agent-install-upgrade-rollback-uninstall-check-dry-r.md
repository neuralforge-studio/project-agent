# INSTALL-001: 설치 계약대로 project-agent 설치기(install·upgrade·rollback·uninstall·check·dry-run)와 격리 HOME 인수 test를 만듭니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Requester: agent, /primehome/swain/Utils/agent/agent.base, 2026-11-09
- Base: 9458aba01535c1a12ee034ce725048aca5448c10 2026-11-09T14:40:54+09:00

## Symptom
project-agent를 다른 직원에게 배포하려면 설치기가 있어야 합니다. 설치·갱신·되돌리기·제거 중 그 사람의 다른 설정에 영향이 없어야 합니다. 설치 계약은 정해졌지만 설치기는 아직 없습니다. 지금은 개발 checkout을 symlink로 거는 방식만 있습니다.

## Evidence
- 설치 계약: `docs/project-team/install-contract.md`(REPO-001 뒤에는 새 docs 위치). 2절(만드는 것과 규칙 1~7), 3절(tmux include 블록), 4절(건드리지 않는 것), 6절·6.1절(등록 파일, `PROJECT_AGENT_PYTHON`·`PROJECT_AGENT_PYTHONPATH`), 7절(명령의 동작, 7.1 떠 있는 run, 7.2 uninstall 거절), 8절(인수 test T1~T23)
- launcher: `codex/tools/python-launcher.sh`. 원격 runtime은 설치 기록 `~/.local/lib/project-agent/install.json`이 있으면 skill link를 만들지 않습니다(`remote_runtime.py`의 `_install_skills`).
- 외부 package: `codex/tools/project-board/requirements.txt`(`textual==8.2.8`). 2026-11-09 workstation 사내 Python 3.12.13에는 8.2.8이 설치되어 있습니다. 이 workstation에서 외부 package index에 닿는지는 확인하지 않았습니다.

## Contract
- 사용자 결정(agent D-20261109-08 C, -09 C): 배포 중 다른 설정에 영향이 없어야 합니다. 기존 파일 수정은 tmux 설정의 include 블록 한 줄뿐입니다. 이름이 겹치면 아무것도 바꾸지 않고 거절합니다. 제거하면 설치가 만든 것만 지웁니다.
- 설치 계약의 2·3·6.1·7절이 설치기의 원본이고, 8절이 인수 test의 원본입니다. 계약과 다르게 구현해야 할 사정이 생기면 계약을 먼저 고치고 그 이유를 기록합니다.
- 갱신은 떠 있는 run에 영향을 주지 않습니다. run은 해석된 release 경로를 쓰고, 그 release는 참조가 남아 있는 동안 지우지 않습니다.
- 동작 중 갱신(사용자 지적 2026-11-09: "조용한 시점이 어디있어.. 없을 건데.."): 조용한 시점은 없습니다. 설치·갱신·되돌리기는 관리 run이 떠 있는 동안 해야 합니다. 한동안 옛 release와 새 release가 같은 state·tmux option·CR 파일을 함께 쓰므로, release마다 이 형식의 버전을 밝힙니다. 떠 있는 run의 release와 형식이 호환되지 않는 갱신은 거절하고, 그 run이 restart로 빠질 때까지 기다리게 안내합니다.
- 옛 개발 checkout link 넘겨받기(이 workstation 전환용, agent DIST-001 6단계): 진입점이 이미 있고, 알려진 옛 개발 checkout 경로를 가리키는 symlink일 때만 넘겨받습니다. 예: `~/.local/bin/agent-session` → `<checkout>/codex/tools/agent-session/bin/agent-session`. 넘겨받을 때는 원자적으로 교체하고, 이전 대상을 설치 기록에 남겨 되돌릴 수 있게 합니다. 그 밖의 이름 충돌은 지금 계약대로 거절합니다. 명시 옵션으로만 켜고, 계약 2절에 규칙으로 더합니다.

## Disposition
- 2026-11-09 Leader: 판정 보류(open 유지). REPO-001이 저장소 배치를 바꾸는 중이므로, 그 통합 뒤의 경로로 Implementation·Verification을 써서 판정합니다. 판정에 필요한 입력은 REPO-001이 통합한 배치입니다. 순서는 사용자가 2026-11-09 대화에서 지시했습니다. 사용자 원문: "제안 진행 순서대로 진행".
- 2026-11-09 Leader: 고친다(Leader 판정). REPO-001(1e06cac)과 TMUX-001(e5ac6db)이 통합되어 판정 입력이 갖춰졌습니다. 이 CR은 agent의 승인한 계획 DIST-001 4단계이고, 동작과 인수 test는 설치 계약 2·3·6.1·7·8절이 이미 정했습니다. 그러므로 위임 범위(승인한 작업의 하위 작업)입니다. 단, 외부 package를 가져오는 방법은 사용자 결정 D-20261109-01로 묻습니다. 2026-11-09 확인 결과 이 workstation의 pip는 저장소에 닿지 않아(`pip download` 시간 초과) 계획의 `pip install --target`만으로는 설치가 끝나지 않습니다. 그 단계 밖의 구현은 결정을 기다리지 않습니다.
- 2026-11-09 Leader: 범위를 나눕니다(Leader 판정). 사용자 지시(2026-11-09 대화): "seat 3자리인데, 4자리 만들어서, 병렬로 진행 가능 한 것은 병렬로 진행해. 남은 CR은 전부 등록해서 얼마나 남았는지 알 수 있게 해줘." 이 CR은 핵심 설치기(release, 2절 진입점, 3절 tmux 블록, 7절 명령, 8절 T1~T23)만 맡습니다. 떼어 낸 일: release 진입점의 interpreter 선택은 INSTALL-002, 외부 package는 INSTALL-003(D-20261109-01), 형식 버전 거절과 release 정리 명령은 INSTALL-004, 옛 checkout link 넘겨받기는 INSTALL-005, 버전 값과 형식 버전의 선언은 RELEASE-001입니다. INSTALL-002·RELEASE-001과 병렬로 진행하므로 그 사이의 interface는 아래 Implementation이 정합니다.
- 2026-11-09 Leader: 사용자 결정 D-20261109-01 waive를 반영합니다. 외부 package를 release에 넣지 않으므로 Implementation 2단계의 package 항목을 고쳤습니다. 사용자 답변 원문: "D-20261109-01 Waive / Refactoring 이후에, rust로 변경가능한 것들은 변경할 것임. 너무 느림."

## Implementation
읽을 문서: [설치 계약](../../project-team/install-contract.md) 전체(원본), [제품 지도](../../project-team/README.md)의 실행 경로 계약, [README의 검증](../../../README.md#검증). 이 CR의 Contract와 설치 계약이 범위의 원본입니다. 계약과 다르게 구현해야 하면 계약을 먼저 고치고 이유를 적습니다.

> **경고:** 개발 중 설치기를 실제 HOME(`/primehome/swain`)에 실행하지 않습니다. 모든 실행은 8.1절의 격리 HOME에서 합니다. `--dry-run`도 격리 HOME에서만 실행합니다. 이 workstation의 전환은 agent DIST-001 6단계가 합니다.

1. 설치기 위치와 진입점: `install/` 아래에 표준 library만 쓰는 Python 설치기를 둡니다. 개발 checkout과 release(`current/install/`) 양쪽에서 실행됩니다. 명령은 `install`, `upgrade`, `rollback`, `uninstall`, `check`와 공통 `--dry-run`(7절)입니다.
2. release 만들기: 원본 checkout의 제품 경로(`tools/`, `skills/`, `docs/`, `integrations/`, `install/`, root 문서)를 `releases/<version>-<hash>/`에 같은 상대 배치로 복사합니다. test·`__pycache__`·`docs/cr`는 넣지 않습니다. release는 만든 뒤 바꾸지 않습니다.
   - `<version>`: 저장소 root의 `VERSION` 파일 첫 줄입니다. 파일의 원본과 규칙은 RELEASE-001이 만듭니다. RELEASE-001이 아직 main에 없으면 test는 fixture 원본 tree에 `VERSION`을 둡니다. 설치기는 `VERSION`이 없으면 거절합니다.
   - `<hash>`: 원본 commit입니다. 작업 트리가 깨끗하지 않을 때의 동작(거절 또는 내용 해시)을 하나로 정해 계약에 적습니다.
   - interpreter 기록(INSTALL-002와의 interface): release를 만들 때 `<release>/tools/python.env`를 씁니다. 한 줄에 `NAME=값` 하나이고, 이름은 `PROJECT_AGENT_PYTHON`(설치 interpreter의 절대 경로)과 `PROJECT_AGENT_PYTHONPATH`(release 안 package 디렉터리. 없으면 빈 값) 두 개뿐입니다. 값은 따옴표 없이 줄 끝까지입니다. 이 파일을 읽는 쪽은 INSTALL-002가 만듭니다. 개발 checkout에는 이 파일이 없습니다.
   - 외부 package: release에 넣지 않습니다(사용자 결정 D-20261109-01 waive, INSTALL-003 done waived). `PROJECT_AGENT_PYTHONPATH`는 빈 값입니다. Board는 설치 interpreter에 있는 `textual`을 씁니다. 설치 계약 2절(release 안의 외부 package)과 6.1절의 서술을 이 결정에 맞게 먼저 고칩니다. `check`는 설치 interpreter에서 `tools/project-board/requirements.txt`의 버전을 import할 수 있는지 안내합니다(실패가 아닙니다).
3. 2절의 진입점: shim 3개, skill link 4개(규칙 7의 provider 홈), `tmux.conf`, 설치 기록 `~/.local/lib/project-agent/install.json`(원격 runtime의 `INSTALL_RECORD`와 같은 경로), 등록 파일 초안(6절 조건). 규칙 1~7(충돌 거절, 부모 디렉터리 기록, provider 홈 없음, 부모 symlink, 실패 시 원상 복구, 원격 runtime link 넘겨받기, provider 홈 변수)을 구현합니다. shim 형태를 정하고 2절에 적습니다.
4. 3절의 tmux 블록: 대상 선택, 블록 넣기·지우기의 byte 보장, backup, symlink 대상의 안내, 실행 중 server에는 다시 읽는 명령만 출력합니다. 표시 줄의 정확한 글자를 계약 3절에 옮깁니다.
5. 7절의 `upgrade`·`rollback`·`uninstall`·`check`를 구현합니다. 7.1절 1·2항(떠 있는 run의 release를 지우지 않음, `current`의 원자적 교체)과 7.2절(`uninstall` 거절: `agent_session.api.liveness`의 `alive`·`unknown`, `suspend.json`, `--force` 없음)을 따릅니다. `check`의 "binding 건너뜀"은 server option `@project_agent_board_skipped`(계약 3.1절)를 읽습니다. `uninstall`의 되돌림 명령은 계약 5.3절의 binding·hook 목록에서 만듭니다. 떠 있는 run과 release의 대응을 찾는 함수는 INSTALL-004가 형식 버전 판정에 다시 쓸 수 있게 한 곳에 둡니다.
6. 인수 test: 8절 T1~T23을 자동 test로 구현합니다(8.1절 하네스: 격리 HOME, snapshot diff, 격리 tmux server는 `-S` private socket). INSTALL-004·005가 같은 하네스에 경우를 더할 수 있게 둡니다. README의 검증 절에 설치기 test 명령을 더합니다.

범위 밖: INSTALL-002(release 진입점의 interpreter 선택), INSTALL-004(형식 버전 거절, release 정리 명령), INSTALL-005(옛 checkout link 넘겨받기), RELEASE-001(버전 값과 규칙), 이 workstation의 전환(agent DIST-001 6단계), 제품 동작(CLI·JSON·state 형식)의 변경.

의존: 선행 REPO-001·TMUX-001(done). 병렬 INSTALL-002, RELEASE-001(위 interface). 후행 INSTALL-004·005, RELEASE-002·003.

위험 등급: 높음. 이 설치기는 다른 직원의 HOME에 쓰고, 틀리면 사용자 파일을 바꾸거나 지울 수 있습니다. 계약 8절 인수 test가 주된 방어입니다. 인수 전에 Leader가 설치기의 쓰기·삭제 경로를 독립 검토(sub-agent)로 한 번 확인합니다.

## Verification
1. 8절 T1~T23이 자동 test로 모두 통과합니다. 각 경우의 기대 변경 목록은 계약 문서에서 얻고 설치 기록에서 얻지 않습니다(8절 머리말). T19는 fake provider CLI로 실행합니다.
2. 추가 자동 test:
   - release에 `tools/python.env`가 위 형식으로 생기고, 값이 설치 interpreter와 package 경로입니다.
   - `VERSION`이 없는 원본에서 `install`이 거절되고 snapshot이 같습니다.
   - 작업 트리가 깨끗하지 않을 때의 동작이 계약에 적은 대로입니다.
3. 실제 HOME 불변: test 실행 전후로 실제 HOME의 2절 경로(`~/.local/lib/project-agent`, `~/.local/bin`의 세 이름, skill link, `~/.config/project-agent`)와 `~/.tmux.conf`의 상태가 같음을 Result에 기록합니다.
4. 영향 회귀: README의 기존 네 명령이 통과합니다. 알려진 timing test 2개(TEST-001, TEST-002)는 단독 실행으로 통과를 확인합니다.
5. 고친 계약 절과 문서의 Markdown 상대 link가 실제 파일을 가리킵니다.
