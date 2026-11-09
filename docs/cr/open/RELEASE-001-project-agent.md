# RELEASE-001: project-agent 첫 배포를 위해 버전 규칙·변경 기록·직원용 설치 안내를 만들고 새 계정에서 시범 설치합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3
- Requester: agent, /primehome/swain/Utils/agent/agent.base, 2026-11-09

## Symptom
project-agent에는 버전 규칙, 변경 기록, 다른 직원이 읽을 설치 안내가 없습니다. 새 계정에서 설치해 계약 밖 변경이 없는지 확인한 기록도 없습니다.

## Evidence
- 계획: agent `DIST-001` 7단계(버전 tag와 변경 기록, 전제·한 줄 설치·설치가 만드는 경로·제거를 담은 안내, 새 계정 시범 설치)
- 설치 계약 9.1절: 새 사용자의 project base에서 `agent/` 아래 실행 파일(`runs/`, `control/`, lock 등)이 untracked로 보입니다. 설치는 project 저장소를 고치지 않으므로 안내문이 다룹니다. PATH에 `~/.local/bin`이 없을 때의 안내도 계약에 있습니다.
- 전제: Python 3.10 이상(launcher의 `python_version` 검사), tmux(Board·관리 session), Claude Code 또는 Codex CLI

## Contract
- 사용자 결정(agent D-20261109-08 C): 다른 직원에게 배포하며, 설치 중 다른 설정에 영향이 없어야 합니다.
- 안내문은 설치 계약을 다시 쓰지 않고 link합니다. 직원이 할 일과 확인할 결과만 적습니다.
- 시범 설치는 INSTALL·TMUX 요청을 통합한 release로, 개인 설정이 없는 계정에서 합니다. 계정 준비는 사용자와 정합니다.
- 배포·갱신은 동작 중에 합니다(조용한 시점 없음). 버전 규칙에 state·tmux option·CR 형식 버전과 호환 범위를 포함하고, 변경 기록에 형식 변경 여부를 적습니다.

## Disposition
- 2026-11-09 Leader: 판정 보류(open 유지). REPO-001·TMUX-001·INSTALL-001이 통합된 release를 기준으로 Implementation·Verification을 써서 판정합니다. 판정에 필요한 입력은 세 CR이 통합한 release입니다. 순서는 사용자가 2026-11-09 대화에서 지시했습니다. 사용자 원문: "제안 진행 순서대로 진행". 새 계정에서 하는 시범 설치의 계정 준비는 판정할 때 결정 항목으로 사용자에게 묻습니다.
