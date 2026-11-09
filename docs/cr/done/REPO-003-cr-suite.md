# REPO-003: 바꾼 경로별 검증 기준이 없어 CR마다 전체 suite를 반복합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3
- Outcome: fixed

## Symptom
저장소에 "무엇을 바꾸면 어느 test를 실행하는가"의 기준이 없습니다. Leader가 CR Verification에 "README의 네 명령"을 영향 회귀로 적었고, Worker는 바뀌지 않은 영역의 suite까지 실행했습니다. agent-session suite(704개)는 이 workstation의 평소 부하에서 한 번에 10~17분입니다. 사용자 질문(2026-11-09): "하나 수정할 때마다 전체 regression 검증하니?"

## Evidence
- INSTALL-001·002·004·005의 Verification이 "README의 네 명령"을 요구했고, 네 CR 모두 `install/`·launcher·문서만 바꿨는데 agent-session suite를 실행했습니다(INSTALL-005는 `tools/`를 바꾸지 않고 2회).
- 전역 지침: 일반 개발은 변경에 대응하는 focused check와 직접 영향 regression으로 완료하고, full suite는 release-readiness가 요청에 포함될 때만 합니다.
- README 검증 절은 명령 목록만 있고 선택 기준이 없었습니다.

## Contract
- 검증 명령과 선택 기준의 원본은 README 검증 절 한 곳입니다(AGENTS.md는 link).
- 전체 다섯 명령은 release를 낼 때 한 번 실행합니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 운영 결함(검증 비용 낭비)이며 원인이 Leader의 CR 작성과 저장소의 기준 부재이므로 Leader가 직접 고칩니다. 앞으로 CR Verification의 영향 회귀는 README 검증 절의 표를 가리킵니다.
- 2026-11-09 Leader: todo -> done, Outcome fixed. Leader 직접 수정 50555ed. origin/main 반영 확인. CHANGELOG Unreleased에 더했습니다.

## Implementation
- README 검증 절에 "바꾼 경로 → 실행할 명령" 표와, 전체 다섯 명령은 release 때 한 번이라는 규칙, merge 뒤 재실행 조건을 더합니다. 표의 의존은 제품 지도 "의존 관계"를 따릅니다.

## Verification
- README의 새 link(버전 규칙 5절, 제품 지도 의존 관계)가 실제 제목을 가리킵니다.
- `python -m pytest -q tools/test_distribution_boundary.py`가 통과합니다(표의 문서 행 기준).

## Result
- 제출 commit: 50555edc8ab3c618f3a788f42a9fe26048045839
- Leader가 직접 고쳤습니다. README 검증 절에 바꾼 경로별 실행 명령 표, release 때 전체 다섯 명령, merge 뒤 재실행 조건을 더했습니다.
- 새 link 두 개의 대상 제목 확인: `docs/project-team/release.md:42` "5. 변경 기록과 release 절차", `docs/project-team/README.md:49` "의존 관계".
- `python -m pytest -q tools/test_distribution_boundary.py`: 9 passed.
