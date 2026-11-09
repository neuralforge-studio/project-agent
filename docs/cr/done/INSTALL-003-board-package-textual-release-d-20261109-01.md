# INSTALL-003: 설치기가 Board의 외부 package(textual)를 release에 넣습니다(D-20261109-01에 따름)

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Outcome: waived

## Symptom
`project-board`는 `textual==8.2.8`이 필요합니다. 설치기는 이 package를 release 안에 넣어야 합니다(설치 계약 2절·6.1절). 승인된 계획의 방법(`pip install --target`)은 이 workstation에서 동작하지 않습니다. pip가 package 저장소에 닿지 않기 때문입니다.

## Evidence
- `tools/project-board/requirements.txt`: `textual==8.2.8`
- 2026-11-09 `timeout 40 /primehome/tools/Inhouse/Python3/latest/bin/python3 -m pip download textual==8.2.8 --no-deps --timeout 10 --retries 0` → 종료 124, 출력 없음
- 사내 Python 3.12.13에 textual 8.2.8과 의존 7개가 설치되어 있고 모두 순수 Python입니다(`agent/decide/open/D-20261109-01.md` Evidence).
- agent DIST-001 2단계: `pip install --target`, 전역 Python에는 설치하지 않음

## Contract
- 사용자 결정 D-20261109-01이 가져오는 방법을 정합니다.
- 설치 계약 2절(release 안의 외부 package), 6.1절(`PROJECT_AGENT_PYTHONPATH`). 전역 Python과 사용자 site에는 설치하지 않습니다.

## Disposition

- 2026-11-09 Leader: open -> done, Outcome waived. 사용자 결정 D-20261109-01 waive. 사용자 답변 원문: "D-20261109-01 Waive / Refactoring 이후에, rust로 변경가능한 것들은 변경할 것임. 너무 느림." 기각 근거: 외부 package를 release에 넣지 않습니다. Board는 설치 interpreter의 site-packages에 있는 textual을 씁니다(PYTHONNOUSERSITE=1이므로 사용자 site는 쓰지 않음). 설치 계약 2절·6.1절의 release 안 package 서술은 INSTALL-001이 이 결정에 맞게 고칩니다. 다시 볼 조건: Board를 Python으로 계속 배포하는데 설치 interpreter에 textual이 없는 직원 환경이 생길 때, 또는 Rust 전환 계획이 바뀔 때.
