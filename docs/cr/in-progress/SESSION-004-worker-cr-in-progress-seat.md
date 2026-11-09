# SESSION-004: Worker가 끝났는데 CR이 in-progress라 반납이 거절되면 seat가 배정된 채 놀게 됩니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Base: 7e35d2411a827df482e386643624eb7663330833 2026-11-09T19:53:55+09:00

## Symptom
다른 project의 Leader 보고(사용자 전달): RUST-058 조사가 16:20쯤 끝났는데 Leader가 CR을 done으로 옮기기 전에 seat1을 stop해서 "CR이 아직 진행 중"이라 반납이 거절됐고, Leader가 다른 일을 하는 동안 seat1이 약 40분 놀았습니다. 사용자 요청: "이런일이 발생하지 않게 script 보완 필요."
출처: 사용자 개선 요청 2026-11-09(대화, 11개 항목 중 10번).

## Evidence
- `agent-session stop`은 CR이 in-progress에 남아 있으면 반납하지 않고 `released: false`와 이유를 돌려줍니다(project-team skill Leader 절, 명세 7절). 그 뒤 반납은 Leader가 CR을 옮긴 다음 stop을 다시 실행해야 일어납니다.
- 반납 거절 상태를 알리는 장치(Board 표시, 알림)는 없습니다.

## Contract
- Worker가 끝난 seat는 사람의 기억에 기대지 않고 반납이 끝나야 합니다. 보존할 작업이 있는 CR을 잃지 않는다는 기존 보호는 유지합니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 운영에서 seat가 40분 논 결함이고, 사람의 순서에 기대는 설계가 원인이므로 위임 범위입니다. 사용자 지시(2026-11-09 대화): "위와 같이 11개의 개선 요청 사항이 있어."
- 2026-11-09 Leader: 제출 cf0b72d 검토. 반납 대기 기록(`release_pending`), `project-item move`가 같은 판정(`workspace.check_release`)으로 반납을 마침, 조건 불충족 시 이유 출력, `ls`·Board 표시, 수정 전 재현과 새 test를 확인했습니다. 내용은 인수 가능합니다. 수정 요청 한 가지: 제출 뒤 SESSION-005(39c915d)가 main에 통합되어 `docs/project-team/spec.md`, `tools/agent-session/agent_session/tmux.py`(`_RUN_VALUES`), `tools/agent-session/tests/test_tmux.py`가 충돌합니다. `origin/main`을 merge해 두 CR의 window option을 모두 살리십시오. `test_registration_publishes_when_the_controller_ends_before_it[sigint]`의 부하 실패는 세 번째 관찰이라 TEST-005로 따로 고칩니다.
- 2026-11-09 Leader: 제출 5c6f4dd715ad859373dc03fe410d26dded26ca59를 인수합니다. Leader review: 수정 제출은 origin/main(5af70ab) merge만 더했습니다. 충돌 3건(spec.md, tmux.py _RUN_VALUES, test_tmux.py)에서 release_pending과 SESSION-005의 last_sent·last_received·watch를 모두 살렸고, merge가 바꾼 test(test_tmux·test_watch·test_cli·test_api_boundary 147, test_lifecycle 관련 44)를 다시 실행해 통과했습니다. 이전 검토(cf0b72d의 반납 대기·move의 반납 마무리·ls/Board 표시·수정 전 재현)를 재사용합니다.

## Implementation
읽을 문서: [동작 명세](../../project-team/spec.md) 3·7절, [project-team skill](../../../skills/project-team/SKILL.md), [README 검증 표](../../../README.md#검증).

근본 원인: 반납이 "CR이 in-progress에서 나간 뒤 Leader가 stop을 다시 실행"하는 두 번째 수동 단계에 달려 있습니다. stop이 거절된 뒤 그 seat는 끝난 Worker를 가진 채 배정 상태로 남고, 이를 완료할 주체가 없습니다.

1. 반납 보류 상태를 기록합니다. stop이 실제 종료를 확인했지만 CR이 in-progress라 반납하지 못하면, 그 seat에 "반납 대기"와 이유를 state 밖의 실행 근거(window option 또는 run 기록)에 남깁니다. state의 배정은 지금처럼 유지합니다(작업 보존).
2. 반납을 CR 이동에 묶습니다. Leader가 `project-item move`로 그 CR을 in-progress에서 옮기면(done·todo·open·deferred), 같은 명령이 반납 대기인 seat의 반납을 마칩니다. 반납 조건(결과가 origin에 있음 등)은 지금 stop의 판정을 그대로 씁니다. 조건이 맞지 않으면 반납하지 않고 그 이유를 출력합니다.
3. 순서가 반대인 경우(CR을 먼저 옮기고 stop)는 지금처럼 동작합니다.
4. Board sidebar와 `project-item ls`가 반납 대기 seat를 보이게 합니다(Leader가 놓쳐도 보임).
5. 명세 7절 stop과 project-team skill Leader 절의 문장을 새 동작에 맞춥니다.

의존: 선행 없음. 후행 SESSION-003.

위험 등급: 중간. 반납 판정을 project-item 명령에서도 부릅니다. 도구 경계(`agent_session.api`만 사용)를 지킵니다.

## Verification
1. 재현(수정 전): stop을 CR이 in-progress일 때 실행 → `released: false`, 이어 CR을 done으로 옮겨도 seat가 배정된 채 남음.
2. 수정 뒤: 같은 순서에서 `project-item move`가 반납을 마치고 seat가 비며, 다음 start가 그 seat를 쓸 수 있음. 결과가 origin에 없는 등 반납 조건이 맞지 않으면 반납하지 않고 이유를 출력. Board·`project-item ls`에 반납 대기 표시.
3. README 검증 표의 `tools/agent-session/**`·`tools/project-item/**` 행(공개 API를 바꾸면 그 표의 추가 행).

## Result

- 제출 commit: 5c6f4dd715ad859373dc03fe410d26dded26ca59

`cr/SESSION-004`(origin에 push함). 구현 commit `9011ad0`에 `origin/main`(`ba99bbe`)을 merge한 commit입니다.

변경
- `stop`이 CR in-progress 때문에 반납하지 못하면 종료한 run의 window에 `release_pending`(`since`, `reasons`)을 남깁니다. state 배정은 그대로입니다. 새 window option은 `_RUN_VALUES`에 넣어 window를 이어받으면 null로 돌아갑니다(`tmux.py`, `lifecycle.py` `_hold_release`).
- 반납 본체를 `Manager._release`로 분리해 stop과 새 `finish_release`가 같은 판정(`workspace.check_release`)을 씁니다. 조건이 맞지 않으면 반납하지 않고 reasons를 반환하며 반납 대기는 유지합니다.
- 공개 API `agent_session.api`에 `pending_releases`(읽기)와 `finish_release`(쓰기)를 추가했습니다. project-item은 이 API만 씁니다(`registry.py`).
- `project-item move`가 in-progress에서 CR을 옮긴 뒤(item root lock 밖에서) `finish_release`를 부릅니다. `released seat N` 또는 반납하지 못한 이유를 출력합니다. 실패해도 move는 유지하고 stderr에 warning만 냅니다. CR을 먼저 옮기고 stop하는 순서는 기존 동작 그대로입니다.
- `project-item ls`는 반납 대기 CR 행에 `[release pending: seat N stopped]`를, Board sidebar는 `반납대기` 접두와 tooltip을 보입니다(`status: release_pending`).
- 문서: 명세 3·5·7절(실행 근거 표, 공개 API 표, stop 반납), project-team skill Leader 절, Board README·TUI 계획, project-item README.

검증
- 수정 전 재현(기준 `7e35d24`를 임시 디렉터리에 풀어 실행): stop(`released: false`) 뒤 CR을 done으로 옮겨도 `state["0"]["job_id"]`가 그대로 남음 → 재현됨.
- 수정 뒤 새 test(`test_lifecycle.py`): stop 보류 → `pending_releases` 표시 → CR in-progress인 동안 `finish_release`는 거절(`since` 유지) → done 이동 뒤 반납·seat 비움·다음 start 가능, 변경이 남은 seat는 반납하지 않고 이유 출력, stop 뒤 move가 아닌 순서는 보류를 남기지 않음, 보류 없는 JOB은 None. `test_team_guard.py`: move가 반납 호출·이유 출력·실패해도 move 유지·in-progress가 아닌 move는 호출 안 함·`ls` 표시. Board `test_model.py`·`test_tui.py`: `release_pending` 상태·접두·읽기 실패 시 seat 유지.
- 실행(README 검증 표 기준, 바꾼 경로 `tools/agent-session/**`·`tools/project-item/**`·`tools/project-board/**`·`api.py`·tmux option·docs):
  - `pytest -q -n 8 tools/agent-session/tests`: 732 passed, 2 failed. 하나는 `test_tmux.py`가 `_RUN_VALUES` 목록을 고정해 둔 기대값이어서 `release_pending`을 추가해 고침(`test_tmux.py` 전체 53 passed). 다른 하나 `test_registration_publishes_when_the_controller_ends_before_it[sigint]`는 병렬 부하에서만 실패했고 단독 실행 4 passed(변경과 무관한 timing으로 판단했으나 같은 부하에서의 재실행은 하지 않음).
  - `pytest -q tools/project-item/tests`: 125 passed. `pytest -q tools/project-board/tests`: 122 passed.
  - 네 번째 명령(`integrations/tmux`, launcher·경계·릴리스 파일 test): 83 passed(merge 전), 91 passed(merge 후).
  - `pytest -q -n 8 install/tests`: 253 passed, 2 skipped(merge 전), 260 passed, 2 skipped(merge 후).
- 근거 재사용: `origin/main` merge(`install/**`, `tools/python-launcher.sh`, docs)는 agent-session·project-item·project-board 코드를 바꾸지 않아 그 test는 다시 돌리지 않았고, merge가 입력을 바꾼 `install/tests`와 네 번째 명령만 merge한 상태에서 다시 실행했습니다.
- `git diff --check` 깨끗.

알려진 한계
- 반납 대기는 이 변경 이후의 stop부터 기록됩니다. 이미 거절돼 남은 seat(기록 없음)는 지금처럼 Leader가 stop을 다시 실행해야 합니다.
- 이 workstation의 관리 run은 동결 사본을 쓰므로(AGENTS.md) 실제 run에서는 아직 동작하지 않습니다.

### 수정 제출: SESSION-005 통합 뒤 merge

- 제출 commit: 5c6f4dd715ad859373dc03fe410d26dded26ca59 (위 제출 `cf0b72d`에 `origin/main` `5af70ab`을 merge함. `cr/SESSION-004`에 push함)
- 충돌 3건(`docs/project-team/spec.md` 실행 근거 표, `tools/agent-session/agent_session/tmux.py` `_RUN_VALUES`, `tools/agent-session/tests/test_tmux.py` 재사용 window의 기대값)은 두 CR의 값을 모두 살려 풀었습니다. `release_pending`과 `last_sent`·`last_received`·`watch`가 함께 있습니다. `lifecycle.py`는 자동 merge이며 `finish_release`·`_hold_release`와 SESSION-005의 `WatchMixin`·`last_sent` 기록이 모두 있습니다.
- merge가 입력을 바꾼 test만 merge한 상태에서 다시 실행했습니다.
  - `test_tmux.py`·`test_watch.py`·`test_cli.py`·`test_api_boundary.py`: 147 passed.
  - `test_lifecycle.py -k "stop or release or move or window"`(내가 추가한 4개 포함): 44 passed.
- 근거 재사용: project-item·project-board test와 `install/tests`, 네 번째 명령은 merge가 그 입력(코드·launcher)을 바꾸지 않아 다시 돌리지 않았습니다(앞 제출의 결과 유효). `test_lifecycle.py`의 `-k`에 걸리지 않은 test와 sigint test는 이번에 다시 돌리지 않았습니다. sigint의 부하 실패는 Leader 지시대로 TEST-005가 다룹니다.
- `git diff --check` 깨끗.
