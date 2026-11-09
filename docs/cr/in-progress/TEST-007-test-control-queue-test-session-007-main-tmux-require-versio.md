# TEST-007: test_control_queue의 test가 SESSION-007 이후 main에서 실패합니다(가짜 Tmux에 require_version 없음)

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S2
- Base: fec73916af748c9bca5b69ff956d0141076e6d33 2026-11-10T00:42:14+09:00

## Symptom
`tools/agent-session/tests/test_control_queue.py::test_external_control_cannot_overtake_a_pending_self_request`가 main에서 `AttributeError: 'Tmux' object has no attribute 'require_version'`로 실패합니다.

## Evidence
- TEST-006 Result·SESSION-008 Result(2026-11-10): 단독 실행으로도 같은 오류. `lifecycle.py:826`의 restart 경로가 SESSION-007 수정 제출(cf0295a, tmux 최소 버전 확인)에서 `require_version`을 부르게 되었고, 이 test의 가짜 Tmux에는 그 method가 없습니다.
- SESSION-007 수정 제출의 검증은 Leader 지시("바뀐 부분의 test만")로 agent-session 전체 suite가 아니라 일부 파일만 실행해 이 실패를 놓쳤습니다. README 검증 표는 `tools/agent-session/**`를 바꾸면 그 도구의 test 전체를 실행하라고 정합니다(Leader의 지시가 표보다 좁았던 누락).

## Contract
- README 검증 표: agent-session의 test는 main에서 모두 통과해야 합니다. test의 가짜 객체는 제품 interface를 따라가야 합니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 재현 근거가 있는 결함입니다. 앞으로 Leader의 수정 요청도 README 검증 표의 행 단위(도구의 test 전체)를 줄이지 않습니다.
- 2026-11-10 Leader: 제출 6bf9005 검토. `FakeTmux`(제품 `Tmux` 파생, 정의 시점의 method 이름·인자 이름 대조, 쓰지 않은 method의 tmux 호출은 `_run`에서 `AssertionError`)와 두 test 파일의 수정, 수정 전 실패 재현, agent-session 전체 784 passed, merge 근거 재사용 판정(merge가 `tools/agent-session/**`를 바꾸지 않음)을 확인했습니다. `require_version`의 `tmux -V` 직접 호출은 `_run` 뒤의 대체 경로라 가짜에서 닿지 않음도 확인했습니다. 수정 요청 한 가지: Implementation 1의 "같은 문제를 가진 다른 가짜"에 `SimpleNamespace`로 만든 Tmux 대역이 남았습니다(`test_remote.py` 8곳, `test_remote_lifecycle.py` 1곳, 예: `tmux=SimpleNamespace(get_current=lambda *args: …)`). 제품 method 이름이 바뀌어도 이 test들은 통과하므로 같은 결함입니다. Result의 "그 밖의 가짜는 Tmux가 아님"은 이 대역을 빠뜨렸습니다. 이 대역들도 같은 두 guard(제품 `Tmux`에 있는 method, 같은 인자 이름)를 거치게 하십시오. 방법은 Worker가 정합니다.
- 2026-11-10 Leader: 수정 제출 dbdcf93 검토. `FakeTmux.replace`·`fake_tmux`(callable도 제품 method 존재·이름 붙인 인자의 위치별 이름을 대조), `test_remote.py`·`test_remote_lifecycle.py`의 Tmux 대역 11곳 교체, guard test, 785 passed를 확인했습니다. 코드 수정 요청은 없습니다. 검증 보완 한 가지: 제출이 `origin/main` 235877b를 포함하지 않습니다. Result의 "겹치는 파일이 없어"는 기준이 아닙니다. README 규칙은 merge가 명령의 입력을 바꿨는지로 정하며, BOARD-011은 `FakeTmux`가 파생하고 대조하는 `agent_session/tmux.py`(`run_quiet` 추가, `run_controller` 본문)와 `tests/test_tmux.py`를 바꿨습니다. merge하고 그 commit에서 `tools/agent-session/tests` 전체를 다시 실행하십시오.
- 2026-11-10 Leader: 제출 0530de33fa700cdd570be9f5ebb3521505ad686f를 인수합니다. Leader review: 재제출 0530de3은 dbdcf93 위의 origin/main 235877b merge뿐임을 확인했습니다(제품 diff는 BOARD-011과 같음). merge가 FakeTmux가 대조하는 제품 Tmux를 바꿨으므로 merge commit에서 tools/agent-session/tests 전체 790 passed(실패 0)로 README 표의 tools/agent-session/** 행을 충족합니다. 앞 검토(6bf9005·dbdcf93)의 코드 판정을 재사용합니다.

## Implementation
1. 가짜 Tmux가 제품 `Tmux`의 interface를 따라가게 고칩니다. 가짜 객체가 제품 class에 있는 method를 빠뜨리면 test가 곧바로 알리는 방법(예: 가짜를 제품 class에서 파생, 또는 interface 대조 test)을 둡니다. 같은 문제를 가진 다른 가짜 객체가 있으면 함께 고칩니다.
2. 제품 코드는 바꾸지 않습니다(원인이 제품이면 Leader에게 먼저 보고).

의존: 없음.

위험 등급: 낮음.

## Verification
1. 수정 전 실패(main에서 그 test), 수정 뒤 통과.
2. README 검증 표의 `tools/agent-session/**` 행 전체(`tools/agent-session/tests`)가 통과.

## Result
- 제출 commit: 6bf90058857c4569055c185dd604a309831793f5

변경(테스트만, 제품 코드 변경 없음):
- `tools/agent-session/tests/fake_tmux.py` 신설: `FakeTmux`는 제품 `Tmux`의 하위 class입니다. 가짜가 쓴 method가 제품 `Tmux`에 없거나 인자 이름이 다르면 class 정의 시점에 실패합니다. 가짜가 쓰지 않은 제품 method가 tmux를 부르면 `AssertionError`(어떤 tmux 호출을 가짜로 만들어야 하는지 표시)로 즉시 실패합니다. 실제 tmux는 부르지 않습니다.
- `test_control_queue.py`의 가짜 `Tmux`: `FakeTmux` 파생, `require_version` 추가, guard가 찾아낸 인자 이름 불일치(`get_current`·`write_meta`·`read_meta`·`run_controller`)를 제품에 맞춤. guard 자체를 확인하는 test 추가.
- `test_run_modules.py`의 가짜 `Tmux`(같은 문제를 가진 다른 가짜): `FakeTmux` 파생, `command(*arguments)`·`close_window(window_id, expected)` 이름을 제품에 맞춤. 그 밖의 가짜(`FakeManager`·`FakeFleet`·`FakeRPC`·`FakeMCP`·FakeProvider)는 Tmux가 아니어서 범위 밖입니다.

검증:
1. 수정 전(main fec7391): `python -m pytest -q tools/agent-session/tests/test_control_queue.py` → 1 failed(`test_external_control_cannot_overtake_a_pending_self_request`, `AttributeError: 'Tmux' object has no attribute 'require_version'`), 3 passed. 수정 뒤: `test_control_queue.py test_run_modules.py` 23 passed.
2. README 검증 표 `tools/agent-session/**` 행: `python -m pytest -q -n 8 tools/agent-session/tests` → 784 passed (1027초, host load 약 190).
3. 근거 재사용 판정: 위 전체 실행은 제출 전 commit 4d4810b4에서 했고, 이후 `origin/main`(BOARD-010: integrations/tmux·docs)을 merge해 6bf9005가 되었습니다. merge가 가져온 변경은 `tools/agent-session/**`와 이 test의 입력(`agent_session/tmux.py`·`minimum_version` 입력의 `tools`)을 건드리지 않아(가짜는 integration 파일을 읽지 않음) 다시 실행하지 않았습니다. `git diff --check` 통과.

### 수정 제출 (Leader 검토: SimpleNamespace Tmux 대역)
- 제출 commit: dbdcf93d1e9a108d0e47a82b6b576029aaf40403

- `tests/fake_tmux.py`에 `FakeTmux.replace(**methods)`와 `fake_tmux(**methods)`를 추가했습니다. callable로 준 method도 같은 두 guard를 거칩니다. 제품 `Tmux`에 있는 method여야 하고, callable이 이름을 붙인 인자(`*args`·`**kw` 제외)는 제품의 같은 위치 인자 이름과 같아야 합니다. 안 쓴 method는 `AssertionError`입니다.
- `test_remote.py`의 `tmux=SimpleNamespace(...)` 8곳(27·45·212·250·330·364·583·713행)과 뒤늦은 대입 2곳(587·645행), `test_remote_lifecycle.py` 1곳(17행)을 `fake_tmux(...)`/`.replace(...)`로 바꿨습니다. 그 밖의 SimpleNamespace(project·provider·manager 등)는 Tmux 대역이 아니어서 그대로입니다.
- 드러난 인자 이름 불일치를 제품에 맞췄습니다: `pane_info`·`capture_pane`(`pane_id`), `has_session`(`project_id`), `write_meta`(`window_id, updates`).
- `test_control_queue.py`에 `fake_tmux` guard test를 추가했습니다(없는 method, 다른 인자 이름, 여분 인자는 실패).
- 검증: `python -m pytest -q -n 8 tools/agent-session/tests` → 785 passed (1804초, host load 높음). `git diff --check` 통과. `origin/main`(BOARD-011, integrations/tmux·문서)은 merge하지 않았습니다. 이 변경과 겹치는 파일이 없어 통합은 Leader에게 맡깁니다.

### 재제출 (origin/main 235877b merge)
- 제출 commit: 0530de33fa700cdd570be9f5ebb3521505ad686f

- `origin/main` 235877b(BOARD-011: `agent_session/tmux.py`의 `quiet_shell`·`run_quiet`·`run_controller`, `tests/test_tmux.py`)를 `cr/TEST-007`에 merge했습니다(충돌 없음). merge가 `FakeTmux`가 대조하는 제품 `Tmux`를 바꾸었으므로 그 commit에서 전체를 다시 실행했습니다.
- 검증: `python -m pytest -q -n 8 tools/agent-session/tests` → 790 passed (1413초). 제품 `Tmux`의 `run_controller(script_path, cwd)` 등 FakeTmux·fake_tmux가 쓰는 method의 인자 이름은 그대로여서 guard가 통과합니다.
