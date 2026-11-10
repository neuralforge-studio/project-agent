# BOARD-015: BOARD-013이 project-board에서 agent_session.config를 import해 API 경계 test가 실패합니다(0.7.0 release gate)

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S2
- Related: BOARD-013
- Base: c64f2728ca470b52fe2eb40c8e5f4fff25aab525 2026-11-11T00:32:59+09:00
- Outcome: fixed

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
- 2026-11-11 Leader: 제출 517921f87852d78766ae0f6c62fdf591cba38911를 인수합니다. 검토 517921f(구현 920421f + main 1a14398 merge). api.py의 registry_path 공개(__all__), model.py의 api import, 명세 5절 행, README 표의 project-board·project-item 행에 test_api_boundary.py 추가를 읽었습니다. 수정 전 경계 test 실패 확인. api.py 행의 명령(agent-session 846, project-item 125, project-board 171, install/tests 280) 모두 통과, 문서는 distribution boundary와 link 검사. merge는 perf 도구·CR 문서만 들여와 입력이 바뀌지 않음.
- 2026-11-11 Leader: in-progress -> done, Outcome fixed. 통합 5222e30 (origin/main)

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

## Result
- 제출 commit: 517921f87852d78766ae0f6c62fdf591cba38911

변경(수정 commit 920421f, origin/main merge 517921f):
- `api.py`가 `registry_path`를 import하고 `__all__`에 더했습니다. `model.py`는 `from agent_session.api import ... registry_path`로 얻습니다. `_registry`의 동작(stat 재사용)은 그대로입니다. 권장안을 썼습니다. `registry_path`는 `load_registry`와 같은 등록 파일을 고르는 규칙이라 api에 공개하는 것이 `model.py`가 경로 규칙을 따로 갖는 것보다 단순합니다.
- 명세 5절 표에 `registry_path(config_path=None)` 행을 더했습니다.
- README 검증 표의 `tools/project-board/**`·`tools/project-item/**` 행에 `tools/agent-session/tests/test_api_boundary.py`를 더했습니다.

검증:
1. 수정 전 `python -m pytest -q tools/agent-session/tests/test_api_boundary.py`: 1 failed, 3 passed(`line 27: from agent_session.config import ...`). 수정 후 통과.
2. 수정 commit(920421f 내용)에서 `-rf`로 실행: `python -m pytest -q -n 8 tools/agent-session/tests` 846 passed, `tools/project-item/tests` 125 passed, `tools/project-board/tests` 171 passed, `python -m pytest -q -n 8 install/tests` 280 passed 2 skipped. README·spec 변경은 `tools/test_distribution_boundary.py` 9 passed와 두 문서의 상대 link·anchor 검사(깨진 것 0)로 확인했습니다.
3. origin/main(1a14398) merge: 들어온 변경은 `tools/tests/perf/**`와 `docs/cr/**`뿐이라 위 명령의 입력이 바뀌지 않았습니다. 전체 명령은 재사용하고, merge commit에서 `test_api_boundary.py`와 `test_distribution_boundary.py`만 다시 실행해 13 passed. 측정은 하지 않았습니다.
- `origin/cr/BOARD-015`에 push했습니다.
