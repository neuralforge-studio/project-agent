# REPO-002: test 실행이 남기는 __pycache__가 untracked로 남아 seat 반납을 막습니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3
- Outcome: fixed

## Symptom
Worker가 test를 실행하면 `__pycache__` 디렉터리가 untracked로 남습니다. `agent-session stop`은 seat에 untracked 파일이 있으면 반납하지 않습니다(`released: false`, "seat has uncommitted or untracked files"). 그래서 Worker마다 종료 전에 `__pycache__`를 손으로 지워야 하고, 놓치면 반납이 막힙니다.

## Evidence
- 2026-11-09 INSTALL-002 stop: `released: false`, seat1의 untracked는 `__pycache__/` 10개뿐(`git status --short`). Leader가 지운 뒤 다시 stop해 반납했습니다.
- RELEASE-001·TEST-002·SESSION-001 Worker 종료 보고가 모두 `__pycache__`를 손으로 지웠다고 적었습니다.
- root `.gitignore`(INSTALL-002가 만듦)에는 `tools/python.env` 한 줄만 있습니다.

## Contract
- 생성되는 cache는 저장소 상태(반납 판정)에 영향을 주지 않아야 합니다. CR 계약의 정리 원칙: Worker는 자기 작업의 산출물만 정리합니다. 재생성되는 cache를 매번 손으로 지우는 절차는 두지 않습니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 재현 근거가 있는 결함입니다. 원인은 저장소에 Python cache의 ignore 규칙이 없는 것입니다. 변경이 `.gitignore` 두 줄이므로 Leader가 직접 고칩니다.
- 2026-11-09 Leader: todo -> done, Outcome fixed. Leader 직접 수정 b6feada. origin/main 반영 확인. CHANGELOG Unreleased에 더했습니다.

## Implementation
- root `.gitignore`에 `__pycache__/`와 `*.pyc`를 더합니다. 기존 `tools/python.env` 줄은 그대로 둡니다.

## Verification
- `python -m pytest -q tools/project-item/tests`를 실행한 뒤 `git status --short`에 `__pycache__`가 보이지 않습니다.
- `git check-ignore -v tools/__pycache__/x.pyc`가 새 규칙을 가리킵니다.

## Result
- 제출 commit: b6feada856c1b9d3a2fba40a5e23af367e799e87
- Leader가 직접 고쳤습니다. root `.gitignore`에 `__pycache__/`와 `*.pyc`를 더했습니다.
- `python -m pytest -q -p no:cacheprovider tools/project-item/tests`: 120 passed. 그 뒤 `git status --short`의 `__pycache__` 줄 0개.
- `git check-ignore -v tools/__pycache__/x.pyc` → `.gitignore:4:__pycache__/`.
