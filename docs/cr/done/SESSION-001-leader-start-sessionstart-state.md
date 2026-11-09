# SESSION-001: Leader start가 SessionStart 등록 성공 뒤 state를 게시하지 않은 채 끝났습니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Base: 477516bef5be923ccdbeefb999c832a77d604171 2026-11-09T15:12:26+09:00
- Outcome: fixed

## Symptom
2026-11-09 13:52 project-agent Leader(run `df0fad2994a0410095a7024e7c34585d`)를 시작했습니다. SessionStart 내부 등록은 성공했습니다(window option `registered: true`, `start_error: null`, hook의 session_id가 기대값과 같음). 그러나 `agent/state.json`의 `leader`가 null이고 `ready: false`였습니다. 게시를 맡는 시작 controller process는 이미 없었습니다. Leader가 같은 `agent-session start --job leader`를 다시 실행하자 `_wait_ready`가 게시했습니다(`connected_at` 2026-11-09T04:55:03Z). 게시 전까지 Worker는 `send --job leader`로 보고할 수 없습니다.

## Evidence
- window `@379` option: `@agent_session_registered true`, `@agent_session_ready false`, `@agent_session_start_error null`, `@agent_session_hook_observations`의 SessionStart `observed_at` 2026-11-09T04:53:30Z, `source: startup`
- `agent/state.json` mtime 13:52:27(예약 기록), 내용 `"leader": null`
- 13:54 `ps`에 `agent_session` 관련 controller process 없음. `agent/diagnostics/` 없음
- 명세 `docs/project-team/spec.md` 5절 "Provider 내부 등록"(시작 controller가 등록을 기다려 게시), 4절 Leader(다시 실행한 start는 등록을 기다려 게시)
- 코드: 실행한 library는 agent 저장소의 동결 사본(`/primehome/swain/Utils/agent/agent.base/codex/tools/agent-session`), `lifecycle.py:351-375`(`_wait_ready`), `:461-475`(Leader start)
- 시작 방법(터미널 명령, Board, 다른 session의 Bash tool 등)은 아직 확인하지 않았습니다.

## Contract
- 명세 4절·5절: start는 등록을 기다려 canonical state에 게시한 뒤 시작 완료를 반환합니다. 게시 전에 controller가 끝나면 다음 start가 게시합니다.

## Disposition
- 2026-11-09 Leader: 조사한다(Leader 판정, read-only). 이 project의 Leader 시작에서 관찰한 이상이며 원인은 확인하지 않았습니다. 조사는 위임 범위입니다. 결과에 따라 Leader가 고치기(todo), 판정 보류(open), 문제 없음(done waived)으로 옮깁니다. 시작 방법은 사용자에게 확인을 요청했습니다(2026-11-09 대화). 답을 받으면 이 절에 적습니다.
- 2026-11-09 Leader: in-progress -> open. Result 검토: 관찰은 현재 계약(게시는 시작 controller만 함)대로의 결과이며 기존 test가 같은 동작을 확인합니다. 원인은 시작 dialog 대기로 controller가 먼저 끝난 경우가 가장 유력하나, 시작 방법을 확인하지 못해 확정하지 않습니다. 빈틈을 메우는 방법(안내 보강, hook 게시, 유지)은 설계 선택이므로 사용자 결정 D-20261109-03으로 묻습니다. 결정 뒤 고칠 일은 이 CR을 todo로 옮겨 Implementation을 씁니다.
- 2026-11-09 Leader: D-20261109-03을 철회했습니다. 사용자 지시 원문: "D-20261109-03: 이걸 나한테 물어봐야해? 동작에 있어서 완벽하게 동작하지 못하는 거잖아. 어떻게 해야 최적의 방법인지는 너가 찾아야지. 절대 문제가 발생하지 않을 방법을 찾아야할거 잖아."
- 2026-11-09 Leader: 고친다(Leader 판정, write로 전환). 등록에 성공한 run이 게시되지 않는 것은 동작 결함입니다. 결함 수정은 위임 범위이고, 결함을 없애는 데 필요한 명세 5절 계약 변경도 이 수정에 포함합니다. 근본 원인: canonical state 게시가 시작 controller 한 process의 생존에 달려 있습니다. 그 process는 dialog 대기 반환, signal, timeout, 호출한 shell의 종료로 등록 전에 끝날 수 있습니다. 안내나 자기 확인(이전 선택지 A)은 누군가의 행동에 기대므로 빈틈이 남습니다. 그래서 "등록에 성공한 run은 어느 경로로든 게시가 끝난다"는 닫힌 설계로 고칩니다(아래 Implementation). read-only 조사 때의 `- Base:`(aad704d)는 지웠습니다. write CR은 배정할 때의 main을 기준으로 새로 시작합니다. 이 수정은 project-agent 저장소에 들어가며, 이 workstation의 실행본(agent 저장소의 동결 사본)에는 agent DIST-001 6단계 전환 때 반영됩니다.
- 2026-11-09 Leader: 직전 Implementation(게시 함수를 여러 곳에서 부르는 재시도 지점)을 철회합니다. 근본 원인을 확정하지 않고 여러 경로에 게시를 붙인 땜질이었습니다. 사용자 지적 원문: "등록에 성공한 run은 어떤 경로로든?? 무책임하게 뭔가 되게만 하겠다는거야?? 정확한 계획을 가지고 해야하지 어떤 경로로든? 땜질 하겠다는거야? root cause를 찾아야지? 뭐하는거야?"
- 2026-11-09 Leader: 근본 원인 확정. (1) agent Leader가 04:47:46Z에 base를 새로 clone하고 04:48:09Z에 등록했으며 workspace trust를 기록하지 않았습니다(agent Leader 대화 `399cefc7…jsonl`, 그 구간에 `.claude.json` 쓰기 없음). (2) Claude provider의 start는 자기가 clone한 seat에만 trust를 기록하고 base에는 기록하지 않습니다(명세 5절, `lifecycle.py:536` `trust_new_seat`). Claude는 trust를 cwd부터 git root까지만 찾으므로, 새 base의 첫 Leader 시작은 반드시 workspace trust dialog(`providers/claude.py:74`)에서 멈춥니다. (3) start는 dialog를 감지하면 `needs_user_action`(exit 3)을 반환하고 끝납니다(`lifecycle.py:385-390`). 그런데 canonical state 게시는 그 시작 controller만 합니다(`internal.py` `_register`의 주석 "Only the controller that holds the target lock publishes canonical state", `lifecycle.py:358-370`). (4) 이번 run의 등록은 launch 63초 뒤(다른 run은 6~8초)였고, 지금 `.claude.json`의 base 항목은 `hasTrustDialogAccepted: true`입니다. 사용자가 dialog에 답한 시간과 맞습니다. 결론: 결함은 게시 책임이 등록 사건이 아니라 호출자에 묶인 시작 process에 있다는 설계입니다. 그 process는 dialog(설계상 정상 경로)·signal·timeout으로 등록 전에 끝날 수 있고, 그러면 게시할 주체가 없습니다. 고칠 것은 게시 책임의 위치 하나입니다. dialog 자체(새 workspace에 대한 사용자 승인)는 정상 동작이므로 바꾸지 않습니다.
- 2026-11-09 Leader: 제출 8054b7a 수정 요청. 설계(게시는 등록의 일부, 게시 주체는 등록 함수, controller는 잠금 없이 기다림)와 경로별 test는 맞습니다. 독립 검토(sub-agent)가 찾고 Leader가 코드에서 확인한 결함: (1) 이전 code가 남긴 `registered`·미게시 run을 만나면 `_wait_ready`(`lifecycle.py:383-405`)가 끝날 조건 없이 timeout까지 기다림, (2) `publish_session`(`state.py:133-135`)이 state를 쓴 뒤 window를 쓰므로 그 사이 hook 종료·`write_meta` 실패에서 state만 게시된 상태가 남고, 시간 한도(binding 20초 + 잠금 8초 + state 잠금 8초)가 hook 30초를 넘음, (3) 잠금을 놓은 틈에 끼어든 shutdown의 기록을 `forget("leader")`(`lifecycle.py:500`)가 run 구분 없이 지움, 낮음: `_abandon`이 잠금 밖, 게시 성공 뒤 잠금 재취득 실패가 실패로 보고됨. Worker 판단 요청 답: Leader 재실행 start의 `leader_exists`는 명세 4절과 같아 맞습니다. 형식 버전은 1을 유지합니다(새 run은 `registered`와 `ready`를 함께 쓰고, 이전 상태는 아래 규칙으로 다룸). 그 밖에: `git stash` 사용은 전역 규칙(사용자 요청 없이 stash를 만들지 않음) 위반이므로 다시 하지 않습니다. `remote_runtime` 변경은 `_register` 공유의 결과로 받아들이고 실제 원격 검증은 SESSION-002에 넘깁니다.
- 2026-11-09 Leader: 제출 9ced69100ed8f965365883c61806f5ce3086a4a3를 인수합니다. Leader review: 지적 5건 반영을 확인했습니다. state.publish_session을 직접 읽어 commit 절차(의도 기록 → state 쓰기 commit → window 한 번에 쓰기, commit 뒤 실패면 같은 잠금 안 되돌림, 되돌릴 수 없이 끝나면 complete_publication이 state가 의도 session을 가리킬 때만 window를 마침)를 확인했습니다. 25초 하나의 deadline으로 hook 30초 제한에 걸려 두 쓰기 사이에서 죽는 경로가 없어졌고, 남는 것은 강제 종료(SIGKILL·OOM)뿐이며 다음 start가 결정적으로 마무리합니다. 새 window option publishing은 이전 release가 무시하는 추가이므로 형식 버전 1 유지. 이전 상태는 registration_incomplete로 즉시 보고. 수정 전 실패 test 15건, 3458d98 전체 suite와 9ced691의 영향 test 재실행 근거를 재사용합니다.
- 2026-11-09 Leader: in-progress -> done, Outcome fixed. 통합 a825c04(Merge cr/SESSION-001, 제출 9ced691). origin/main 반영 확인. CHANGELOG Unreleased에 더했습니다.

## Implementation
읽을 문서: [동작 명세](../../project-team/spec.md) 3절(실행 근거와 잠금), 4절 Leader·Worker, 5절 "Provider 내부 등록", 이 CR의 Disposition(근본 원인)과 Result(조사).

목표 계약(명세를 먼저 고칩니다): **게시는 등록의 일부입니다.** 로컬 run의 등록 함수가 binding을 검증한 뒤 같은 단계에서 대상 제어 잠금을 잡고 canonical state에 게시합니다. 게시 주체는 등록 함수 하나입니다. 시작 controller는 게시하지 않고, 등록 결과(`ready` 또는 `start_error`)를 기다려 호출자에게 보고만 합니다. 시작 controller가 언제 끝나든 게시에 영향이 없습니다.

1. 명세 5절 "Provider 내부 등록"과 4절을 고칩니다.
   - "Canonical state는 시작 controller가 게시하며 등록 함수는 그 준비 결과를 기다립니다"를 위 계약으로 바꿉니다.
   - 등록과 게시는 한 단계입니다. 게시가 실패하면 등록 실패이고 `start_error`에 남습니다. 성공하면 `registered`와 `ready`가 함께 참이 됩니다. 등록됐지만 게시되지 않은 상태는 없습니다.
   - 4절의 "dialog에 답한 뒤 같은 start를 다시 실행해야 게시"를 "답하면 등록이 게시까지 마칩니다. 다시 실행한 start는 이미 게시된 결과를 돌려줍니다"로 바꿉니다. project-team skill(`skills/project-team/SKILL.md`)의 같은 문장도 맞춥니다.
2. 시작 controller의 잠금 범위를 바꿉니다(`lifecycle.py`).
   - 지금은 Leader·Worker start가 대상 제어 잠금을 잡은 채 `_launch` → `_wait_ready`에서 등록을 기다립니다. 등록 함수가 같은 잠금으로 게시하려면 controller가 기다리는 동안 잠금을 놓아야 합니다.
   - window 생성·예약·launch까지는 지금처럼 잠금 안에서 하고, 등록 대기는 잠금 밖에서 합니다. 잠금 없는 대기 상태는 새로 생기는 상태가 아닙니다. `needs_user_action` 반환 뒤에 이미 존재합니다. 그동안 다른 명령(`send`는 not ready로 거절, `stop`·`restart`, 다시 실행한 start)의 동작은 지금 그 상태에서의 동작과 같아야 합니다. 이를 test로 확인합니다.
   - `_wait_ready`는 게시 코드(`store.update(publish)`, `write_meta(ready=True)`)를 없애고 `ready`·`start_error`·pane 종료·dialog를 관찰해 보고만 합니다. 게시 뒤의 `_sweep`은 지금처럼 controller가 합니다. controller가 먼저 끝났으면 다음 start의 sweep이 정리합니다(정리 대상이 남을 뿐 state는 맞습니다).
3. 등록 함수가 게시합니다(`internal.py`).
   - `_register`: `_bind` 성공 뒤 대상 제어 잠금(`<base>/agent/control/<slot>.lock`)을 hook 제한(30초) 안의 한도로 잡습니다. 잠금 안에서 현재 pointer(run·window·pane·JOB)와 seat의 JOB 배정을 다시 대조하고, 지금 `_wait_ready`의 게시와 같은 내용(같은 slot의 기존 session과 비교해 `connected_at`·`reviewing` 보존, `_bound`)으로 state를 쓴 뒤 window에 `registered`·`ready`를 함께 씁니다. 대조가 다르면 `target_changed`로 아무것도 쓰지 않습니다.
   - 잠금을 한도 안에 얻지 못하거나 state 쓰기가 실패하면 `_record_failure`로 `start_error`를 남기고 실패로 끝납니다.
   - `register_from_hook`(SessionStart)과 `register_current`(Codex)의 "controller의 ready를 최대 120초 기다림"(`internal.py` `_wait_ready`)을 없앱니다. 게시가 등록 안에서 끝나기 때문입니다.
   - 게시 코드는 controller와 등록 함수가 나눠 갖지 않습니다. `lifecycle.py`의 `_bound` 같은 helper를 등록 쪽에서 쓰도록 옮기거나 공용 module에 둡니다(한 곳).
4. 원격 seat(Codex SSH)는 등록이 원격 host에서 일어나 Leader host의 등록 함수가 없습니다. 같은 결함이 있지만 고치는 방법(원격 등록을 Leader host로 올리는 경로)이 달라 SESSION-002로 나눴습니다. 이 CR은 원격 경로의 동작을 바꾸지 않습니다. 지금 등록된 project에는 원격 seat가 없습니다(2026-11-09 등록 파일 확인).

범위 밖: workspace trust dialog 자체(새 base에 대한 사용자 승인, 정상 동작), 원격 seat(SESSION-002).

의존: 없음. INSTALL-001·002와 병렬(바꾸는 파일이 겹치지 않음).

위험 등급: 높음. 모든 로컬 Leader·Worker의 시작과 게시 경로, 잠금 범위를 바꿉니다. 인수 전에 Leader가 잠금·게시 경로를 독립 검토(sub-agent)로 확인합니다.

## Verification
모두 격리 tmux server와 fake provider(기존 fixture)로 실행합니다.

1. 재현(수정 전 실패): 근본 원인 경로 그대로. start가 시작 dialog에서 `needs_user_action`으로 끝난 뒤 사용자가 답해 등록되면, Base에서는 `state.leader`가 null로 남습니다. 수정 뒤에는 다시 start하지 않아도 등록 직후 게시됩니다. 기존 `test_start_held_at_a_startup_dialog_needs_the_user_and_resumes`(`test_lifecycle.py:302-325`)의 기대를 새 계약으로 고칩니다. 다시 실행한 start는 같은 session을 돌려주고 `connected_at`이 바뀌지 않습니다.
2. 게시 주체가 하나임을 확인합니다. controller가 살아 있는 정상 시작에서 state의 session은 등록 함수가 쓴 것이고, controller는 state를 쓰지 않습니다. controller를 등록 전에 SIGKILL해도 결과가 같습니다.
3. 등록과 게시가 한 단계임을 확인합니다. 게시 실패(잠금 한도 초과, state 쓰기 실패 주입)면 `registered`와 `ready`가 모두 거짓이고 `start_error`가 남으며, 기다리던 start는 `registration_failed`를 반환합니다. 등록됐지만 게시되지 않은 상태가 어떤 test에서도 관찰되지 않습니다.
4. 늦은 hook: 더 새로운 run이 slot을 이어받은 뒤 옛 run의 등록은 `target_changed`로 아무것도 쓰지 않습니다(기존 test 유지).
5. 잠금 범위: controller가 등록을 기다리는 동안 같은 slot의 `send`(not ready 거절)·`stop`이 잠금 대기 없이 동작하고, 그 결과가 지금 `needs_user_action` 뒤 상태에서의 결과와 같습니다.
6. Codex `register_current` 경로가 1~4와 같은 결과를 냅니다.
7. 영향 회귀: README의 agent-session suite(`-n 8`)와 project-item suite가 모두 통과합니다.
8. 명세·skill의 고친 문장이 코드 동작과 맞고, 고친 문서의 상대 link가 열립니다.

## Result
- 제출 commit: 9ced69100ed8f965365883c61806f5ce3086a4a3

### 수정 제출 (Leader 검토 5건 반영, Base 8054b7a 위에 3458d98 + 9ced691)
명세 5절·3절에 규칙을 먼저 적고 코드를 고쳤습니다. 항목마다 수정 전 commit(8054b7a)에서 실패하는 test를 두었습니다(새 test 17건을 8054b7a에 놓고 실행: 15건 실패, 2건은 두 경로에서 모두 성립하는 음성 test).

1. commit 절차(높음): `state.publish_session`의 순서를 대조 → window에 게시 의도(`publishing`) 기록 → state 쓰기(commit) → window `session_id`·`registered`·`ready` 한 번에 쓰기·`publishing` 해제로 바꿨습니다. window 쓰기가 실패하면 같은 잠금 안에서 그 slot을 쓰기 전 값으로 되돌리고(state 쓰기 전 실패면 의도만 지움) `start_error`를 남깁니다. 되돌림 자체가 실패하면 의도를 남겨 roll-forward가 마무리합니다. roll-forward는 `state.complete_publication`(window 쓰기만): 기다리는 start의 `_observe_ready`가 대상 제어 잠금 안에서 "현재 run·window ready 아님·state가 `publishing` session을 가리킴"일 때만 부릅니다. 그 밖에서 controller는 state를 쓰지 않습니다. 의도는 새 window option `publishing`(window 생성·재사용 때 null)이며 이전 release가 무시하는 추가입니다(형식 버전 1 유지).
   - test: `test_a_failed_window_update_puts_the_published_session_back`, `…leaves_nothing_published`(fixture CLI에 window 쓰기 실패 주입 → state 불변, `start_error`, `registration_failed`), `test_a_process_that_ends_after_the_commit_leaves_what_complete_publication_finishes`(되돌릴 수 없이 끝남), `test_complete_publication_finishes_nothing_the_state_does_not_name`, `test_a_start_finishes_a_publication_whose_registration_committed_the_state`(다음 start가 window를 마치고 같은 session 보고), `test_a_start_publishes_nothing_for_an_intent_the_state_does_not_name`.
2. 시간 한도(중간): `_register`가 hook 시작 시각(`register_from_hook` 진입)에서 25초 deadline 하나를 정하고(hook 30초보다 짧음), binding 확인은 deadline 6초 전에 끝나며 제어 잠금·state 잠금이 남은 시간을 나눠 씁니다. test: `test_every_step_of_a_registration_ends_inside_its_one_deadline[binding|control_lock|state_lock]`(deadline 3초에서 각 단계가 느릴 때 전체가 안에 끝나고 state 불변, window 미등록, `start_error`).
3. 이전 release가 남긴 상태(중간): 로컬 run이 `registered`이고 `ready`가 아니면 `_wait_ready`가 기다리지 않고 곧바로 `registration_incomplete`(exit 4)로 끝나며 `stop`·`restart --job <JOB>` 해소 방법을 출력합니다. 게시하지 않습니다. 명세 5절에 적었습니다. test: `test_a_registered_run_that_was_never_published_is_reported_not_waited_for[leader|worker]`.
4. 잠금 공백 뒤(중간): Leader·suspended start의 기록 제거를 `SuspendStore.forget_before(slot, 이 run의 run_id)`로 바꿨습니다(그 run의 기록은 남기고 이전 run의 기록만 지움). `_wait_ready`는 기다린 뒤 현재 pointer를 다시 읽어 run이 바뀌었으면 `target_changed`, 멈추는 중이면 `target_stopping`으로 보고합니다. test: `test_a_start_reports_the_run_as_it_is_after_waiting_without_the_lock[stopping|replaced]`(shutdown 기록이 남고 보고가 사실과 맞음), `test_starting_a_leader_keeps_a_shutdown_record_made_for_the_new_run`.
5. 낮음: `_abandon`이 대상 제어 잠금 안에서 실행되도록 `Manager._regain(slot)`을 두었습니다(`test_a_failed_resume_leaves_the_record_and_start_can_take_over`에 잠금 보유 확인 추가). 대기 뒤 잠금 재취득이 실패해도(`_unlocked`) start는 게시 사실을 보고하고 정리는 건너뛰어 `cleanup.kept`에 이유를 남깁니다(`test_a_published_run_is_reported_even_when_the_lock_cannot_be_taken_again`).

검증: 마지막 기능 commit 3458d98에서 `AGENT_SESSION_TEST_TIMEOUT=60 python -m pytest -q -n 8 tools/agent-session/tests` → 727 passed, 3 failed. 실패 3건 중 2건은 새 option이 재사용 window에만 나타나 두 test의 key 비교를 어긋나게 한 것(`test_tmux`·`test_lifecycle`의 window 재사용 test)이고, 9ced691에서 `publishing`을 새 window에도 두어(생성 시 null) 고쳤습니다. 1건(`test_a_failed_resume_leaves_the_record_and_start_can_take_over`의 seat-0이 `provider_exited` 대신 `timeout`)은 호스트 부하 시간 초과였으며 같은 test를 다시 실행해 통과했습니다. 9ced691에서는 영향받은 test(`test_tmux.py`, `test_lifecycle`의 window 재사용·restart, `test_suspend`의 failed resume, `test_internal.py` 전체)만 다시 실행해 통과했고 전체 suite는 다시 돌리지 않았습니다(Leader 지침: 바뀐 부분만). 다른 suite(project-item 120, 4번째 명령 55)는 이전 근거를 재사용합니다(이번 수정은 그 대상 파일을 바꾸지 않았습니다).

### 이전 제출 (8054b7aa6079d7c115a54c66b7682c19ec92f9a5)

Worker seat2 구현 결과입니다. Base는 ee5edf0이며 `origin/cr/SESSION-001`에 push했습니다(origin/main 진행 없음, merge 불필요).

### 변경 (명세를 먼저 고쳤고 코드가 따릅니다)
- 게시 함수 하나: `state.py`의 `publish_session`(현재 run·JOB·window·pane 대조 → state 쓰기 → window `registered`·`ready` 한 번에 쓰기). 공유 helper `bound`(옛 `lifecycle._bound`), `control_lock`(대상 제어 잠금 파일 이름의 원본), `FileLock`(release·acquire 가능한 잠금)도 `state.py`에 둡니다.
- 등록이 게시: `internal._register`가 `_bind` 뒤 대상 제어 잠금(한도 8초: 바인딩 20초와 합쳐 hook 30초 안)을 잡고 `publish_session`을 부릅니다. 실패(잠금 한도, state 쓰기)는 `start_error`로 남고 `registered`·`ready`는 거짓입니다. `register_from_hook`·`register_current`의 "controller ready 120초 대기"(`internal._wait_ready`)는 없앴습니다.
- controller는 게시하지 않음: `lifecycle._wait_ready`는 로컬 run에서 `Manager._unlocked`로 대상 제어 잠금을 놓고 `ready`·`start_error`·pane 종료·dialog만 관찰합니다. 끝나면 잠금을 다시 잡아(대기 재취득은 항상 blocking) 호출자의 `_sweep` 등을 이어갑니다.
- 원격 seat: Leader 호스트 controller의 게시 경로는 같은 `publish_session`으로 유지했고(잠금 유지) 동작은 같습니다. capsule에서는 `_register`가 cache를 직접 게시하므로, 그것을 대신하던 `remote_runtime` poll의 게시 단계만 없앴습니다(poll은 `ready`를 보고만 합니다). 실제 원격 host 검증은 하지 못했습니다(SESSION-002 범위).
- 문서: 명세 3절(상태·잠금 규칙·SSH Worker 절), 4절(Leader·Worker), 5절(Provider 내부 등록), 7절 restart 단계, project-team skill, agent-session README의 문장을 새 계약에 맞췄습니다. 고친 문서의 상대 link는 모두 열립니다.

### 판단이 필요했던 점 (Leader 확인)
1. CR Verification 1의 "다시 실행한 start는 같은 session을 돌려줌"은 Worker에만 맞습니다. Leader는 실행 중이면 `leader_exists`로 거절하는 기존 계약(spec 4절, `test_lifecycle.py` 기존 `leader_exists` test)이 있어 바꾸지 않았습니다. 그래서 dialog에 답한 뒤 Leader의 다시 실행한 start는 `leader_exists`입니다(게시는 이미 끝남). 명세 4·5절에 그렇게 적었습니다. 다르게 하려면 별도 결정이 필요합니다.
2. 이전(구) 코드로 이미 `registered` 이고 미게시인 run이 업그레이드 뒤에 남아 있으면, 새 `_wait_ready`는 그 run을 게시하지 않고 기다립니다(로컬은 controller가 게시하지 않으므로). 신규 run은 이 상태가 만들어지지 않습니다. 동결 사본에서 이 코드로의 전환 시 떠 있는 미게시 run이 있으면 그 run은 한 번 stop/restart가 필요합니다.
3. 형식 버전(`tools/formats.json`)은 바꾸지 않았습니다(필드·option 이름 변경 없음). window의 `registered`와 `ready`가 이제 한 번에 참이 됩니다(관측 의미 변화). 판정과 CHANGELOG는 Leader 몫입니다.

### 검증 (CR Verification 대응)
- 1 재현: 수정 전 Base에서 `test_start_held_at_a_startup_dialog_needs_the_user_and_resumes[leader]`를 새 계약으로 고친 형태가 실패했습니다(`state.leader`가 null로 남아 `wait_until(published)` 시간 초과). 수정 뒤 [leader]·[worker] 모두 통과. Leader는 답한 뒤 `leader_exists`, Worker는 같은 run·같은 session을 돌려주며 `connected_at` 불변.
- 2 controller가 등록 전에 끝남: `test_registration_publishes_when_the_controller_ends_before_it[returned|sigint|sigterm|sigkill]`(별도 process controller에 실제 signal), `test_start_timeout_before_registration_still_publishes_the_registration`. 모두 다시 start하지 않아도 게시되고 잠금은 비어 있습니다.
- 3 정상 경로: `test_the_start_controller_does_not_publish`(lifecycle의 `publish_session` 호출 시 실패하게 막고도 Leader·Worker가 게시됨), `test_registering_the_same_conversation_again_changes_nothing`, `test_republished_connection_keeps_its_time_and_review`. 게시 주체가 하나라 동시 게시 경합은 없습니다.
- 4 게시 실패: `test_a_registration_that_cannot_publish_is_not_registered[lock|state]`(잠금 한도 초과·state 쓰기 실패 주입 → `registered`·`ready` 거짓, `start_error`, 기다린 start는 `registration_failed`, state 불변), `test_registration_waits_for_the_control_lock_inside_its_limit`. 이 설계에는 "다음 hook이 재시도"하는 경로가 없습니다(Leader의 재작성 계획에 따라).
- 5 늦은 hook: 기존 `test_late_registration_cannot_replace_a_new_run_after_native_check` 유지·통과.
- 잠금 범위: `test_commands_do_not_wait_for_a_controller_that_waits_for_registration`(controller 대기 중 잠금이 비어 있고 `send`·`stop`의 결과 code가 controller 종료 뒤와 같음).
- 6 Codex 경로(`register_current`)는 fixture CLI가 쓰는 경로라 위 test 전부가 거칩니다. Claude hook 진입점은 `test_session_start_hook_publishes_the_new_conversation`, `test_registration_binds_and_publishes_in_one_step`(test_internal).
- 7 회귀: `AGENT_SESSION_TEST_TIMEOUT=60 python -m pytest -q -n 8 tools/agent-session/tests` → 첫 전체 실행 4 failed / 711 passed. 실패 4건은 모두 이 CR의 test 수정 누락(새 test의 tmux session 준비 전 조회 1건 포함 2건, dialog 뒤 다시 start를 기대하던 기존 test 2건)이었고 고친 뒤 해당 test만 다시 실행해 통과했습니다(전체 재실행은 안 했습니다). project-item suite 120 passed. 4번째 명령(`integrations/tmux`와 launcher·boundary·release test) 55 passed.
- 근거 재사용 판정: 호스트 load가 높아 첫 시도(timeout 기본값)의 65건 실패는 부하로 인한 시간 초과였고(Base 사본 측정: Leader start 15초, Worker start 27초) 코드 회귀가 아니어서 `AGENT_SESSION_TEST_TIMEOUT`을 올려 다시 실행했습니다.
- 정리: 내 작업의 `__pycache__`와 임시 test를 지웠습니다. `git stash`를 한 번 `stash`·`pop` 쌍으로 실수로 실행했으나 stash는 비어 있고 작업 트리는 그대로입니다.

### 이전 조사 (read-only, Worker seat3, Base aad704d)

코드 변경·commit 없음. 제출 행 없음. (아래는 이전 조사 결과를 그대로 둔 것입니다.)

### 결론
**(b) 호출 방법의 문제로 보이는 쪽이 가장 유력하나, 시작 방법을 확인하지 못해 확정은 못 합니다. 동시에 (a)의 개선 여지가 있습니다.**
- 확인한 사실: 게시는 시작 controller 한 곳만 합니다. 등록 hook은 게시하지 않습니다. controller가 등록 전에 끝나면 다음 start가 올 때까지 `ready:false`, `leader:null`이 유지되는 것이 현재 계약입니다(spec 4절 Leader·5절). 관찰한 상태는 이 계약대로의 결과입니다.
- 가설(미확인): 이 run의 controller는 등록 전에 끝났습니다. 가장 가까운 원인은 시작 dialog 대기(`needs_user_action`, exit 3)입니다.

### 1. 게시 전에 controller가 끝나는 경우 (모두 `_wait_ready` 대기 중 또는 그 이전)
경로: `cli.py:140 main` → `lifecycle.py:~445 start(leader)` → `_launch`(`:325-338`) → `_wait_ready`(`:351-391`). 게시는 `:358-370`(`registered` 관찰 후 `store.update(publish)`, `write_meta(ready=True)`), 대기 loop 주기 0.1초(`:391`). 등록은 `internal.py:68-84 _register`가 `registered: true`만 씁니다. 게시는 하지 않습니다.

| # | 경우 | 코드 | 남는 흔적 |
| --- | --- | --- | --- |
| 1 | 시작 dialog 감지 → `needs_user_action`(exit 3) 반환, controller 종료. 사용자가 창에서 답하면 CLI는 계속 진행해 등록 | `lifecycle.py:385-390` | stdout JSON(`dialog`)만. window: `registered:true`, `ready:false`, `start_error:null`. state `leader:null`. diagnostics 없음 |
| 2 | 호출한 shell·tool이 시간 제한으로 controller를 SIGTERM/SIGKILL | `cli.py`에 signal handler 없음(`grep signal` 결과 `cli.py`·`lifecycle.py` 없음) | 출력 없음. 위와 같은 window·state. diagnostics 없음 |
| 3 | SIGHUP(터미널·ssh 끊김, tmux pane 닫힘) | 2와 같음. handler 없음 | 같음 |
| 4 | SIGINT(Ctrl-C) | `cli.py:200-203` `KeyboardInterrupt` → `interrupted` JSON, exit 4 | stdout JSON만. diagnostics 없음. 같은 window·state |
| 5 | `--timeout`(기본 600, `cli.py:64`) 만료 | `lifecycle.py:65-70 remaining` → `timeout` exit 4 | stdout JSON만. 같은 window·state |
| 6 | 등록 후 게시 중 오류: `_session` 검증, `_same`, `store.update`(`state_write_failed`, `target_changed` 등) | `lifecycle.py:358-370`, `state.py:202-231` | SessionError는 stdout JSON만. 비 SessionError는 `cli.py:204-210`이 `agent/diagnostics/`에 log를 남김 |
| 7 | `provider_exited`(`:381`), `registration_failed`(`:373-378`), `target_changed`(`:356`) | 같은 함수 | 6과 같은 방식. 이 셋은 `registered`가 아니거나 `start_error`가 있어 관찰과 다름 |

경우 1~5 이후 `registered:true`가 오면 아무도 게시하지 않습니다. 이 때 hook은 `internal.py:157-170 _wait_ready`에서 최대 120초 기다리다 `registration_timeout`으로 끝나지만(Claude hook 한도 30초가 먼저 자름), 이 실패는 `start_error`에 기록하지 않습니다(`_record_failure`는 `_bind` 실패만 호출, `internal.py:73-76`). 그래서 `start_error:null`이 관찰과 일치합니다.

### 2. 관찰한 흔적과 맞는 경우
- `agent/diagnostics/` 없음 → 6의 비 SessionError 예외는 아닙니다.
- run 시작 13:52:27.9(`runs/df0fad.../launch.sh` mtime) → 등록 hook 13:53:30.6(`hook_observations.SessionStart.observed_at`). 63초. 같은 base의 다른 run은 6~8초입니다(`@389` 14:41:01→05:41:07Z, `@395` 14:45:42→14:45:50, `@398` 15:03:47→15:03:55). 이 run만 약 55초 늦었습니다.
- controller가 등록 시점(13:53:30)에 살아 있었다면 0.1초 안에 게시했을 것입니다. 따라서 controller는 13:52:27~13:53:30 사이에 끝났습니다. 이 구간 동안 CLI는 정상 속도로 뜨지 못했습니다.
- 가장 자연스러운 설명은 경우 1입니다. `--permission-mode bypassPermissions`로 시작하므로 `bypass_permissions` dialog(`providers/claude.py:73-77`)에서 CLI가 멈췄고, controller는 1~2초 안에 `needs_user_action`으로 끝났으며, 사용자가 약 1분 뒤 창에서 답해 hook이 등록했을 가능성입니다. 이 경우 spec 4절·5절·README 72행의 절차(답한 뒤 같은 start 재실행)가 게시를 맡습니다. Leader가 재실행하자 게시된 것과 맞습니다.
- 경우 2·3(호출 tool·shell의 중간 종료)도 같은 흔적을 남기며, CLI 지연 55초가 별도 원인이어야 합니다. 현재 근거로 1과 구분할 수 없습니다. 구분에 필요한 것은 처음 start 호출의 stdout(`needs_user_action` 또는 무출력), 호출한 곳(터미널·Board·다른 session의 Bash tool), 13:52~13:54의 pane 화면입니다. 시작 방법은 CR 본문대로 사용자 확인 대기 중입니다.

### 3. 동결 사본과의 차이
실행한 사본(`/primehome/swain/Utils/agent/agent.base/codex/tools/agent-session`)과 이 저장소 `tools/agent-session`을 `diff -r`했습니다. `lifecycle.py`·`cli.py`·`internal.py`·`state.py`는 동일합니다(위 줄 번호는 양쪽에 같음). 다른 파일은 `remote.py`·`remote_runtime.py`·`tmux.py`(주석의 `project_board.conf`→`project-agent.conf`) 뿐이며 이 현상과 무관합니다.

### 4. 재현 (격리 tmux server + fake provider)
저장소의 테스트 fixture(`tests/fixtures/agent_session_fixture.py`의 `session_env`, `agent_session_fake_provider.py`의 `FakeProvider(dialog=True)`)로 경우 1을 재현했습니다. 이 재현은 경우 1의 상태를 만들 뿐 실제 원인이 1임을 증명하지 않습니다. 임시 test는 scratchpad에 두었고 저장소에는 없습니다.
1. `FakeProvider(dialog=True)`로 `manager.start("leader")` → `needs_user_action`(exit 3), controller 종료.
2. 창에 `approve`+Enter를 보내 CLI 등록.
3. 관찰: `registered=True ready=False start_error=None leader=None` (3초 뒤에도 유지). Leader state를 게시하는 process 없음.
4. `manager.start("leader")` 재실행 → `ready=True`, `leader={session_id, connected_at,...}`.
이 결과는 이번 관찰과 같습니다. 같은 현상을 보이는 기존 test: `tools/agent-session/tests/test_lifecycle.py:302-325 test_start_held_at_a_startup_dialog_needs_the_user_and_resumes`(`leader is None` 단언 후 재실행 start가 `ready` 확인). 즉 현재 계약의 의도된 동작입니다. 경우 2·3(signal)은 같은 상태로 이어지는 것을 코드로 확인했고 별도 재현은 하지 않았습니다.

### 5. 판단과 제안 (결정은 Leader 몫)
- 호출 방법 안내(b): `start --job leader`의 stdout이 `needs_user_action`이거나 출력 없이 끝났다면 같은 start를 다시 실행해야 게시됩니다. 호출한 shell·tool의 시간 제한(600초 `--timeout`보다 짧은 제한)과 dialog 대기 시간에 주의합니다. 게시 여부는 `agent/state.json`의 `leader`가 null인지로 확인합니다.
- 제품 개선(a, 범위·정책 선택이라 사용자 결정 대상일 수 있음): 등록과 게시 사이에 원인과 무관한 빈틈이 있습니다. dialog 반환 뒤 사용자가 답하면 등록은 되지만, 사용자가 이를 알 방법은 Leader가 `send`를 못 받는다는 간접 증상뿐입니다. 후보:
  1. 등록 hook(`_register` 뒤)이 같은 게시를 대상 제어 잠금 아래 수행(spec 5절의 "시작 controller만 게시" 계약 변경 필요).
  2. `send --job leader`·Worker 보고가 `registered && !ready`인 현재 run을 보면 게시를 마쳐 줌(`_wait_ready`의 publish 재사용).
  3. 변경 없이 `needs_user_action` 메시지에 "답한 뒤 같은 start 재실행" 안내를 강화하고 `registered && !ready` 상태를 진단 출력에 노출.
  어느 쪽도 이 CR 범위(조사)에서 구현하지 않았습니다.

### 검증 (CR Verification 대응)
1. 경우마다 코드 위치와 흔적: 위 1절 표.
2. 결론 (b)의 근거: 2절 시간 대조(63초 vs 6~8초)와 4절 재현. 확정에 필요한 처음 start의 stdout과 시작 방법이 없음을 명시했습니다. 확정은 아닙니다(c 성격이 일부 남음).
- 실행 명령: `pytest <scratchpad>/test_repro_session001.py -s` 통과(1 passed). 저장소 파일과 `__pycache__`는 정리했고 `git status` clean입니다.
