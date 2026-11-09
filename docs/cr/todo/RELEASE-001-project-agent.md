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
- 2026-11-09 Leader: 고친다(Leader 판정), 범위를 나눕니다. 사용자 지시(2026-11-09 대화): "seat 3자리인데, 4자리 만들어서, 병렬로 진행 가능 한 것은 병렬로 진행해. 남은 CR은 전부 등록해서 얼마나 남았는지 알 수 있게 해줘." 이 CR은 버전 규칙, `VERSION` 파일, 형식 버전 선언, 변경 기록만 맡고 INSTALL-001과 병렬로 진행합니다. 직원용 안내문은 RELEASE-002, 새 계정 시범 설치는 RELEASE-003으로 떼어 냈습니다. 승인한 계획 agent DIST-001 7단계의 하위 작업이므로 위임 범위입니다. 버전 체계는 아래 Implementation의 기본값(SemVer, 첫 값 0.1.0)으로 정합니다. 사용자는 이 판정을 되돌릴 수 있습니다.

## Implementation
읽을 문서: [CR 계약의 "release와 CR"](../../../skills/project-item/references/cr.md), [설치 계약](../../project-team/install-contract.md) 1절(release)·7.1절, INSTALL-001·INSTALL-004의 Implementation(이 CR이 정한 값을 씁니다).

1. 버전 값: 저장소 root에 `VERSION` 파일을 둡니다. 첫 줄 하나가 `MAJOR.MINOR.PATCH`(SemVer)이고 첫 값은 `0.1.0`입니다. INSTALL-001의 설치기가 이 파일을 읽어 release 이름(`<version>-<hash>`)에 씁니다. 이름과 형식은 INSTALL-001과 맞춘 interface이므로 바꾸지 않습니다.
2. 형식 버전: release가 함께 쓰는 세 형식(agent-session state·window option, tmux 통합 option, CR·결정 파일)의 버전을 release 안의 한 곳에 선언합니다. 위치와 형식을 정합니다(예: `tools/formats.json`). 첫 값은 모두 1입니다. agent 저장소의 동결 사본(`/primehome/swain/Utils/agent/agent.base/codex/tools/`)과 이 release의 세 형식이 같은지 code diff로 확인하고 결과를 Result에 적습니다. 다르면 그 차이를 Leader에게 보고합니다(agent DIST-001 6단계의 전제).
3. 버전 규칙 문서: 한 곳에 씁니다(예: `docs/project-team/release.md`). 내용은 MAJOR·MINOR·PATCH를 올리는 조건, 형식 버전을 올리는 조건과 호환 범위(INSTALL-004가 다르면 거절), git tag 이름 규칙(예: `v0.1.0`), release note가 CR ID 목록으로 답하는 방법(CR 계약 "release와 CR")입니다. README와 제품 지도는 이 문서를 link합니다.
4. 변경 기록: root에 `CHANGELOG.md`를 만듭니다. 항목은 버전별 CR ID 목록과 형식 변경 여부입니다. 다음 release 전까지 쌓이는 CR을 어디에 적는지(예: `Unreleased` 절) 규칙을 3단계 문서에 적습니다. 지금까지 통합된 CR(REPO-001, TMUX-001)을 적습니다.
5. tag 만들기와 push는 이 CR에서 하지 않습니다. 첫 release의 tag는 RELEASE-003의 시범 설치가 통과한 뒤 Leader가 만듭니다.

범위 밖: 직원용 안내문(RELEASE-002), 새 계정 시범 설치(RELEASE-003), 형식 버전 판정 코드(INSTALL-004).

의존: 선행 없음. 병렬 INSTALL-001(`VERSION` interface). 후행 INSTALL-004, RELEASE-002, RELEASE-003.

위험 등급: 낮음. 문서와 데이터 파일만 만듭니다.

## Verification
1. `VERSION`의 첫 줄이 SemVer 형식이고 `0.1.0`입니다.
2. 형식 버전 선언 파일이 2단계의 위치에 있고 세 값이 1입니다. 동결 사본과의 code diff 명령과 결과(같음 또는 차이 목록)를 Result에 적습니다.
3. 버전 규칙 문서와 `CHANGELOG.md`가 있고, README·제품 지도에서 link됩니다. 고친 문서의 Markdown 상대 link가 실제 파일을 가리킵니다.
4. `tools/test_distribution_boundary.py`가 통과합니다(새 문서가 개인 지침을 가리키지 않음). 새 파일이 제품 경로면 `PRODUCT_PATHS`에 들어가는지 확인합니다.
