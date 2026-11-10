# BOARD-015: BOARD-013이 project-board에서 agent_session.config를 import해 API 경계 test가 실패합니다(0.7.0 release gate)

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S2
- Related: BOARD-013

## Symptom
0.7.0 release gate(e6ff6c0, 2026-11-11 00:41)의 `python -m pytest -q -n 8 tools/agent-session/tests`가 1개 실패했습니다. 실패한 test는 `tools/agent-session/tests/test_api_boundary.py::test_other_tools_import_only_the_public_api`입니다. BOARD-013이 `tools/project-board/project_board/model.py`에 `from agent_session.config import registry_path`를 더했습니다. 다른 도구는 `agent_session.api`만 import해야 합니다.

## Evidence
- gate 기록: "FAILED tools/agent-session/tests/test_api_boundary.py::test_other_tools_import_only_the_public_api 1 failed, 845 passed".
- `tools/project-board/project_board/model.py:27`(BOARD-013 merge cddba10).
- BOARD-013 Worker는 README 검증 표의 `tools/project-board/**` 행(`tools/project-board/tests`)만 실행했고 그 행은 지켰습니다. 경계 test는 agent-session test에 있어 표의 행이 이 실패를 고르지 못했습니다.
- release commit e6ff6c0은 push하지 않았고 Leader가 main 이력에서 뺐습니다.

## Contract
- project-board와 project-item은 `agent_session.api`만 import합니다.
- `api.__all__`에 이름을 더하면 [명세 5절](../../project-team/spec.md#프로젝트-consumer용-python-api)의 목록도 함께 고칩니다.

## Disposition
- 2026-11-11 Leader: 고친다(Leader 판정). 승인한 작업(BOARD-013)에서 나온 결함이며 release gate가 재현했습니다.
- 2026-11-11 Leader: open -> todo. release gate 재현, BOARD-013 하위 결함

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), `tools/agent-session/tests/test_api_boundary.py`, `tools/agent-session/agent_session/api.py`의 `__all__`, [명세 5절](../../project-team/spec.md#프로젝트-consumer용-python-api), [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. `model.py`가 `agent_session.api`로만 registry 경로를 얻게 합니다. 권장은 `api`가 `registry_path`를 공개하고(`__all__`, 명세 5절 목록) `model.py`가 그것을 쓰는 것입니다. 다른 방법이 더 단순하면 근거를 적고 씁니다. BOARD-013의 동작(registry stat 재사용)은 바꾸지 않습니다.
2. README 검증 표의 `tools/project-board/**`와 `tools/project-item/**` 행에 `tools/agent-session/tests/test_api_boundary.py`를 더합니다. 다른 도구의 import 경계를 이 test가 지키므로, 그 도구를 바꾸면 이 test도 실행해야 합니다.

의존: 없음.

위험 등급: 낮음.

## Verification
1. 수정 전 `tools/agent-session/tests/test_api_boundary.py`가 실패하고 수정 후 통과합니다. git stash는 쓰지 않습니다.
2. README 검증 표에서 바꾼 경로의 행을 모두 실행합니다(`-rf`). `api.py`를 바꾸면 `tools/agent-session/tests`, `tools/project-item/tests`, `tools/project-board/tests`, `install/tests`를 실행합니다. README를 바꾸면 상대 link 검사와 `tools/test_distribution_boundary.py`를 실행합니다.
3. 제출 전에 `origin/main`을 merge하고, merge가 입력을 바꾼 명령만 merge commit에서 다시 실행합니다. 측정은 하지 않습니다.
