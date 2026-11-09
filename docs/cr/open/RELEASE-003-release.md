# RELEASE-003: 개인 설정이 없는 새 계정에서 release를 시범 설치하고 계약 밖 변경이 없음을 기록합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3

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
