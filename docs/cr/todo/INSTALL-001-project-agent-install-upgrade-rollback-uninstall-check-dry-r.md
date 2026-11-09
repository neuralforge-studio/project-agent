# INSTALL-001: 설치 계약대로 project-agent 설치기(install·upgrade·rollback·uninstall·check·dry-run)와 격리 HOME 인수 test를 만듭니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Requester: agent, /primehome/swain/Utils/agent/agent.base, 2026-11-09

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

## Implementation
읽을 문서: [설치 계약](../../project-team/install-contract.md) 전체(원본), [제품 지도](../../project-team/README.md)의 실행 경로 계약, [README의 검증](../../../README.md#검증). 이 CR의 Contract와 설치 계약이 범위의 원본입니다. 계약과 다르게 구현해야 하면 계약을 먼저 고치고 이유를 적습니다.

> **경고:** 개발 중 설치기를 실제 HOME(`/primehome/swain`)에 실행하지 않습니다. 모든 실행은 8.1절의 격리 HOME에서 합니다. `--dry-run`도 격리 HOME에서만 실행합니다. 이 workstation의 전환은 agent DIST-001 6단계가 합니다.

1. 설치기 위치와 진입점: `install/` 아래에 표준 library만 쓰는 Python 설치기를 둡니다. 개발 checkout과 release(`current/install/`) 양쪽에서 실행됩니다. 명령은 `install`, `upgrade`, `rollback`, `uninstall`, `check`와 공통 `--dry-run`(7절)입니다. 오래된 release 정리 명령(7.1절 3항이 4단계에 맡김)의 이름과 규칙을 정해 구현하고 계약 7.1절에 적습니다. 사용 중인 release(7.1절 2항)와 `current`·`previous`는 지우지 않습니다.
2. release 만들기: 원본 checkout의 제품 경로(`tools/`, `skills/`, `docs/`, `integrations/`, `install/`, root 문서)를 `releases/<version>-<hash>/`에 같은 상대 배치로 복사합니다. test·`__pycache__`·`docs/cr`는 넣지 않습니다. `<version>`의 값은 저장소 root의 파일 하나를 원본으로 둡니다. 버전 규칙과 첫 값은 RELEASE-001이 정합니다. 이 CR은 자리 값을 둡니다. `<hash>`는 원본 commit입니다(작업 트리가 깨끗하지 않으면 거절하거나, 내용 해시를 쓰고 그 사실을 기록합니다. 둘 중 하나를 정해 계약에 적습니다). release는 만든 뒤 바꾸지 않습니다.
3. 2절의 진입점: shim 3개, skill link 4개(규칙 7의 provider 홈), `tmux.conf`, 설치 기록 `~/.local/lib/project-agent/install.json`(원격 runtime의 `INSTALL_RECORD`와 같은 경로), 등록 파일 초안(6절 조건). 규칙 1~7(충돌 거절, 부모 디렉터리 기록, provider 홈 없음, 부모 symlink, 실패 시 원상 복구, 원격 runtime link 넘겨받기, provider 홈 변수)을 구현합니다. shim 형태를 정하고 2절에 적습니다.
4. 3절의 tmux 블록: 대상 선택, 블록 넣기·지우기의 byte 보장, backup, symlink 대상의 안내, 실행 중 server에는 다시 읽는 명령만 출력합니다. 표시 줄의 정확한 글자를 계약 3절에 옮깁니다.
5. release의 진입점이 shim 없이도 설치 interpreter와 release package 경로로 실행되게 합니다. tmux helper(`integrations/tmux/tmux_project_board.sh` → `tools/project-board/bin/project-board`)와 `@project_agent_decide_status`의 `tmux_decide_status.py`(지금 `#!/usr/bin/env python3`)는 shim을 거치지 않습니다. 새 직원 환경에서 그 interpreter는 Python 3.10 미만이거나 package가 없을 수 있습니다. 예: 설치기가 release를 만들 때 interpreter·package 경로를 release 안의 파일에 쓰고, `tools/python-launcher.sh`가 환경 변수가 없을 때 그 파일을 읽습니다. 개발 checkout의 규칙은 바꾸지 않습니다. 계약 6.1절을 먼저 고칩니다. TMUX-001 review에서 넘긴 일입니다.
6. 외부 package(`tools/project-board/requirements.txt`): 가져오는 방법은 D-20261109-01의 결정을 따릅니다. 결정 전에는 이 단계를 interface(받은 package 디렉터리를 release에 두고 5단계의 경로로 넘김)까지만 만들고, Leader가 결정을 전달하면 완성합니다. 어떤 방법이든 전역 Python과 사용자 site에는 설치하지 않습니다. `check`는 release의 package 버전이 요구 버전과 같은지 확인합니다.
7. 7절의 `upgrade`·`rollback`·`uninstall`·`check`를 구현합니다. 7.1절(떠 있는 run의 release를 지우지 않음, `current`의 원자적 교체)과 7.2절(`uninstall` 거절: `agent_session.api.liveness`의 `alive`·`unknown`, `suspend.json`, `--force` 없음)을 따릅니다. `check`의 "binding 건너뜀"은 server option `@project_agent_board_skipped`(계약 3.1절)를 읽습니다. `uninstall`의 되돌림 명령은 계약 5.3절의 binding·hook 목록에서 만듭니다.
8. 동작 중 갱신(Contract 4항): release마다 state·tmux option·CR 형식의 버전을 release 안의 한 곳에 밝힙니다. `upgrade`·`rollback`은 떠 있는 run의 release와 형식 버전이 다르면 거절하고, 그 run의 project·slot과 restart 안내를 출력합니다. 떠 있는 run은 등록된 모든 project의 `<base>/agent/runs/*/`와 `liveness`로 찾습니다. release가 아닌 경로(agent 저장소의 동결 사본)에서 시작한 run의 판정 규칙을 정합니다. 첫 release는 그 사본과 형식이 같으므로 agent DIST-001 6단계의 전환을 막지 않아야 합니다. 규칙을 계약 7.1절에 적습니다.
9. 옛 개발 checkout link 넘겨받기(Contract 5항): 명시 옵션으로만 켭니다. 대상이 알려진 옛 경로(`<checkout>/codex/tools/<도구>/bin/<도구>`, `<checkout>/codex/skills/<이름>` 같은 모양)를 가리키는 symlink일 때만 원자적으로 교체하고, 이전 대상을 설치 기록에 남깁니다. `uninstall`·`rollback` 때 이전 대상으로 되돌릴 수 있는지 정하고 계약 2절에 규칙으로 더합니다. 그 밖의 충돌은 규칙 1대로 거절합니다.
10. 인수 test: 8절 T1~T23을 자동 test로 구현합니다(8.1절 하네스: 격리 HOME, snapshot diff, 격리 tmux server는 `-S` private socket). 5·8·9단계와 package 단계의 test를 더합니다. README의 검증 절에 설치기 test 명령을 더합니다.

범위 밖: 버전 규칙·변경 기록·안내문·새 계정 시범 설치(RELEASE-001), 이 workstation의 전환(agent DIST-001 6단계), 제품 동작(CLI·JSON·state 형식)의 변경.

의존: 선행 REPO-001·TMUX-001(done), D-20261109-01(6단계만). 후행 RELEASE-001, agent DIST-001 6단계.

위험 등급: 높음. 이 설치기는 다른 직원의 HOME에 쓰고, 틀리면 사용자 파일을 바꾸거나 지울 수 있습니다. 계약 8절 인수 test가 주된 방어입니다. 인수 전에 Leader가 설치기의 쓰기·삭제 경로를 독립 검토(sub-agent)로 한 번 확인합니다.

## Verification
1. 8절 T1~T23이 자동 test로 모두 통과합니다. 각 경우의 기대 변경 목록은 계약 문서에서 얻고 설치 기록에서 얻지 않습니다(8절 머리말). T19는 fake provider CLI로 실행합니다.
2. 추가 자동 test:
   - release의 `bin/` 진입점 세 개와 `tmux_decide_status.py`가 shim 환경 변수 없이 실행될 때 설치 interpreter를 씁니다. `PATH`의 `python3`를 Python 3.10 미만인 가짜로 바꿔도 결과가 같습니다. 개발 checkout의 진입점은 기존 `tools/test_python_launcher.py`대로 동작합니다.
   - 격리 tmux server에서 설치본의 `tmux.conf`를 읽은 뒤 Board 키 binding의 helper가 release의 `bin/project-board`를 설치 interpreter와 package 경로로 실행합니다(`--help` 수준으로 확인).
   - 형식 버전이 다른 release로의 `upgrade`·`rollback`이 떠 있는 run(fake)이 있으면 거절되고 snapshot이 같습니다. 같은 형식이면 진행합니다. 동결 사본 경로의 run 판정이 계약 7.1절의 규칙대로입니다.
   - 옛 checkout link 넘겨받기: 옵션이 없으면 T11처럼 거절, 있으면 알려진 모양의 link만 교체되고 설치 기록에 이전 대상이 남습니다. 알려지지 않은 대상의 link는 옵션이 있어도 거절합니다.
   - release 정리 명령이 사용 중인 release·`current`·`previous`를 지우지 않습니다.
   - package 단계: D-20261109-01의 결정에 맞는 경우(성공, 버전 불일치 거절, 가져올 수 없을 때 거절과 snapshot 불변).
3. 실제 HOME 불변: test 실행 전후로 실제 HOME의 2절 경로(`~/.local/lib/project-agent`, `~/.local/bin`의 세 이름, skill link, `~/.config/project-agent`)와 `~/.tmux.conf`의 상태가 같음을 Result에 기록합니다.
4. 영향 회귀: README의 기존 네 명령이 통과합니다. 알려진 timing test 2개는 단독 실행으로 통과를 확인합니다.
5. 고친 계약 절과 문서의 Markdown 상대 link가 실제 파일을 가리킵니다.
