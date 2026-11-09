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
