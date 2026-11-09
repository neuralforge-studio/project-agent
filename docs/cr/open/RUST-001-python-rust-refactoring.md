# RUST-001: 느린 Python 구현 중 Rust로 바꿀 수 있는 부분을 정하고 바꿉니다(Refactoring 이후)

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3

## Symptom
사용자 평가(2026-11-09 대화): "Refactoring 이후에, rust로 변경가능한 것들은 변경할 것임. 너무 느림." 어느 명령·경로가 얼마나 느린지, 무엇을 Rust로 바꿀지 아직 정하지 않았습니다.

## Evidence
- 사용자 답변 원문(D-20261109-01): "D-20261109-01 Waive / Refactoring 이후에, rust로 변경가능한 것들은 변경할 것임. 너무 느림."
- 현재 구현: `tools/agent-session`, `tools/project-item`, `tools/project-board`(Python 3.10 이상), `integrations/tmux/tmux_decide_status.py`(tmux status-interval 1초마다 실행)
- 측정값은 아직 없습니다.

## Contract
- 관측 동작(CLI·JSON·파일 형식, 원격 실행본, hook entry)은 바꾸지 않습니다(실행 경로 계약, `docs/project-team/README.md`).
- 범위와 시점은 사용자가 정합니다("Refactoring 이후").

## Disposition
- 2026-11-09 Leader: 판정 보류(open 유지). 사용자가 방향만 정했고 시점을 "Refactoring 이후"로 두었습니다. 지금 진행 중인 배포 준비(INSTALL·RELEASE)가 끝난 뒤, 느린 경로의 측정값과 전환 후보를 근거로 범위를 사용자 결정 항목으로 묻습니다. 그 전에는 측정·후보 조사(read-only)도 시작하지 않습니다.
