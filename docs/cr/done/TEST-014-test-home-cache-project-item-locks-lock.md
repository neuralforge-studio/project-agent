# TEST-014: test가 실제 HOME의 ~/.cache/project-item/locks에 lock 파일을 남깁니다

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S3
- Base: ae564453bf327bd7b17f518f4930d0d6449e4409 2026-11-12T02:13:57+09:00
- Outcome: fixed

## Symptom
test 실행이 실제 사용자 HOME의 `~/.cache/project-item/locks/`에 lock 파일을 남깁니다. 2026-11-12 02:00 KST 현재 2,906개이고(디렉터리 항목 크기 225 KB, NFS), 하루에 수백 개씩 늘어납니다(11일 748개, 12일 0시~2시 55개). 가장 새 파일(01:59:14~15)은 seat들이 test를 돌리던 시각에 생겼습니다. 실제 등록 project의 root는 20개 안팎이므로 나머지는 test가 만든 임시 root의 잠금입니다.

[README 검증](../../../README.md#검증)의 규칙 "Test가 사용자 계정에 남기는 자원은 test가 끝나면(통과·실패·중단 모두) test 전 수준으로 돌아갑니다"를 어깁니다.

## Evidence
- 잠금 파일 경로는 `tools/project-item/project_item/store.py`의 `lock_path`가 정합니다: `Path.home() / ".cache" / "project-item" / "locks" / <root 경로 sha256 앞 16자>.lock`. 잠금을 놓아도 파일은 지우지 않습니다(지우면 같은 root의 다른 process와 상호 배제가 깨지므로 지우지 않는 것이 맞습니다).
- `tools/project-item/tests/conftest.py`는 HOME을 격리합니다("an isolated HOME (lock files)"). `tools/project-board/tests`에는 HOME을 바꾸는 곳이 없습니다. `tools/agent-session/tests`는 일부 파일만 HOME을 바꿉니다(`test_config.py`, `test_remote_skills.py`, `fixtures/agent_session_fixture.py`의 일부).
- 잠금을 잡는 호출: agent-session의 `jobs.claim`·`unclaim`(start·stop·resume), `remote_bridge`, project-board 결정 창의 답변 접수(`answer_decide`), `render`. 이 경로를 실행하는 test가 임시 root로 실제 HOME에 파일을 만듭니다(어느 test인지는 Worker가 확인합니다).
- 쓰레기 파일 말고도, test가 실제 HOME의 잠금 디렉터리를 쓰면 실제 운영 잠금과 같은 디렉터리를 공유합니다.

## Contract
1. 어떤 test도 실제 HOME의 `~/.cache/project-item/`에 파일을 만들지 않습니다(통과·실패·중단 모두). 다섯 검증 명령 전부와 `cargo test`에 적용합니다.
2. 이 규칙은 test가 지키고, 새 test가 어겨도 드러나게 합니다(예: 공통 conftest가 실제 HOME의 잠금 디렉터리를 test 전후로 비교하거나, test 중에는 실제 HOME에 쓸 수 없게 함). 방법은 Worker가 정하되 각 도구 test의 독립 실행(README "다섯 명령은 서로 독립")을 유지합니다.
3. 제품의 잠금 경로와 동작(실제 운영)은 바뀌지 않습니다.
4. 이미 쌓인 파일은 이 CR을 통합한 뒤 Leader가 정리합니다. 실제 등록 root(등록 파일의 `path_cr`·`path_decide`)의 잠금 파일은 남기고 나머지만 지웁니다.

## Disposition
- 2026-11-12 Leader: 구현한다. Leader 판정: README 검증의 자원 규칙을 어기는 test 결함입니다(Symptom의 파일 수와 시각). 제품 동작은 바꾸지 않습니다.
- 2026-11-12 Leader: open -> todo. Leader 판정: README 자원 규칙을 어기는 test 결함
- 2026-11-12 Leader: 제출 8272163을 검토했습니다. 수정 요청은 하나입니다. run의 HOME을 바꾸면 HOME에서 위치를 정하는 도구 탐색(Python 사용자 site, rustup)도 바뀌어, `pip install --user`나 rustup cargo를 쓰는 host에서 xdist worker·자식 Python·Rust build가 깨질 수 있습니다. HOME을 바꾸기 전에 `PYTHONUSERBASE`와 `RUSTUP_HOME`을 비어 있을 때만 격리 전 값으로 고정하고 test로 확인합니다. 그 밖의 구현(계측과 새는 test 17개, configure·finish, 내부 pytest 장치, test_workspace 신원, README)은 문제없습니다.
- 2026-11-12 Leader: 제출 1ce00b911328fc201a15251b7420520f77b23e1a를 인수합니다. 검토 1ce00b9(8272163 위 수정 하나). _isolate_home이 HOME을 바꾸기 전에 PYTHONUSERBASE(site.getuserbase())와 RUSTUP_HOME(~/.rustup)을 비어 있을 때만 고정, CARGO_HOME은 run HOME. test가 내부 pytest(default·basetemp·xdist)와 자식 Python에서 값 유지와 기존 값 보존을 확인. 다섯 명령 통과(agent-session 921, project-item 141, project-board 229, 네 번째 141, install 283+2 skipped), 대용 HOME에 .cache/project-item 0개. 8272163의 나머지는 앞 검토를 재사용합니다. 제출 뒤 main에 들어온 INSTALL-008과의 조합은 Leader가 merge 뒤 확인합니다.
- 2026-11-12 Leader: 제출 1d72df5e7d82e19c3135c4d31065a2ee7b1d6717를 인수합니다. 최종 제출 1d72df5는 1ce00b9에 origin/main(INSTALL-008) merge만 더한 것이고, Leader가 같은 조합을 merge한 tree(a3e524d, push 안 함)와 tree가 같습니다. 그 tree에서 Leader 실행: install/tests/test_crontab.py 12 passed, agent-session test_cron.py와 tools/test_private_root.py 71 passed. Worker 재실행(test_cron+api_boundary 63, test_crontab 12, private_root+distribution 21)과 일치합니다.
- 2026-11-12 Leader: in-progress -> done, Outcome fixed. 통합 dcbfc96 (origin/main)

## Implementation
읽을 문서: [README 검증](../../../README.md#검증)의 자원 규칙, `tools/project-item/project_item/store.py`의 `lock_path`·`root_lock`, `tools/project-item/tests/conftest.py`(격리 HOME의 예), `tools/conftest.py`, 각 도구의 `tests/conftest.py`, `tools/tests/private_root.py`, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 실제 HOME에 lock 파일을 만드는 test를 찾습니다(예: test 전후로 실제 HOME 잠금 디렉터리의 목록을 비교하는 일시 계측). 찾은 test 목록과 경로(어느 호출이 잠금을 잡는지)를 Result에 적습니다.
2. 그 test들이 격리된 HOME(또는 잠금 위치)을 쓰게 합니다. 제품 코드에 test 전용 분기를 넣지 않는 방법을 우선합니다.
3. 새 test가 어겨도 드러나게 하는 장치를 둡니다(Contract 2). 다른 seat가 같은 시각에 옛 코드로 test를 돌려 실제 HOME에 파일을 만들 수 있으므로, 장치는 "이 test process가 만든 파일"만 판정하거나 실제 HOME에 쓰지 못하게 하는 방식이어야 합니다(디렉터리 전체 개수 비교는 다른 seat 때문에 거짓 실패가 납니다).
4. README 검증의 자원 규칙 목록에 이 항목을 더합니다.

의존: 없음. BOARD-018이 `tools/project-board/tests`를 크게 고치고 있으니 제출 전에 `origin/main`을 merge합니다. 위험 등급: 낮음.

## Verification
1. README 검증 표에서 바꾼 경로의 행 명령 전부를 제출 commit에서 실행합니다. `tools/conftest.py`나 여러 도구가 함께 쓰는 test helper를 바꾸면 다섯 명령 모두(`python -m pytest -q -n 8 tools/agent-session/tests`, `python -m pytest -q tools/project-item/tests`, `python -m pytest -q tools/project-board/tests`, 네 번째 명령, `python -m pytest -q -n 8 install/tests`). 도구별 conftest만 바꾸면 그 도구 행의 명령 전부. 문서를 바꾸면 상대 link 검사와 `tools/test_distribution_boundary.py`.
2. 그 실행들에서 이 CR의 test process가 실제 HOME의 `~/.cache/project-item/`에 만든 파일이 0개임을 Result에 적습니다(1번의 계측 방법으로).

## Result
- 제출 commit: 1d72df5e7d82e19c3135c4d31065a2ee7b1d6717

**구현** (`cr/TEST-014`: 0a849e9, 99a3bc5, `origin/main`(ITEM-001까지) merge 8272163)
- 새는 test(일시 계측: test마다 새 lock 파일을 기록하는 pytest plugin을 두고 worker별 임시 HOME으로 다섯 명령을 실행해 test별 신규 파일 수를 셌습니다). 새는 곳은 두 곳이고, 둘 다 같은 프로세스 안에서 `store.root_lock`이 `Path.home()`(실제 HOME)으로 잠금을 만드는 경로입니다.
  - `tools/agent-session/tests/test_remote.py`의 `test_result_return_preserves_new_leader_disposition_and_accepts_a_retry`(2), `test_first_remote_result_can_fill_an_empty_result_section`, `test_result_conflict_preserves_the_authoritative_cr`, `test_result_return_rejects_a_cr_that_left_in_progress`: remote result 반환(`remote_bridge`)의 잠금.
  - `tools/project-board/tests/test_answer.py` 13개(`test_no_leader_is_recorded_without_sending`, `test_stopped_current_leader_is_recorded_without_sending`, `test_old_stopped_verdict_cannot_block_a_new_leader`, `test_answer_reaches_agent_session_with_the_user_text`, `test_answer_is_recorded_once_before_notifying`, `test_board_receipt_and_leader_confirmation_keep_unicode_separator` 2개, `test_concurrent_answers_accept_only_one`, `test_page_write_failure_does_not_lose_an_accepted_answer`, `test_agent_session_refusal_preserves_its_error`, `test_unknown_send_result_is_not_reported_as_a_failure`, `test_send_timeout_and_start_failure_are_distinct` 2개): `answer_decide`의 잠금.
  - `tools/project-item/tests`, 네 번째 명령, `install/tests`에서는 새 파일이 없었습니다.
- 수정: `tools/tests/private_root.py`의 `configure`가 run마다 HOME을 `<basetemp>-home`(기본은 `TMPDIR/pt-*` 안)으로 바꿉니다. `os.environ["HOME"]`이므로 `Path.home()`과 자식 process(xdist worker 포함)가 모두 따릅니다. 통과한 run은 지우고(`finish`), 실패한 run은 `pt-*`와 함께 남아 기존 prune이 정리합니다. `tools/conftest.py`와 `install/tests/conftest.py`가 이미 `private_root`를 부르므로 두 conftest는 그대로이고, 다섯 명령 모두 적용됩니다(네 번째 명령의 `integrations/tmux`는 같은 run의 `tools/conftest.py`가 덮습니다). 제품 코드·잠금 경로는 바뀌지 않았습니다. 실제 HOME을 쓰는 새 test도 `~`가 run의 HOME이라 실제 HOME에 쓸 수 없습니다(다른 seat의 옛 코드 run과도 겹치지 않습니다).
- 새 test 장치: `tools/test_private_root.py`에 `test_the_home_of_the_run_is_private`와, 내부 pytest를 default·`--basetemp`·xdist로 실행해 test가 `~/.cache/project-item/locks`에 쓴 뒤에도 실제 HOME이 비어 있고 TMPDIR(root·HOME)과 `--basetemp` 옆 HOME이 지워짐을 보는 test 3개. `os.environ["HOME"]` 대입을 빼고 돌리면 4개가 실패함을 확인했습니다.
- 부수 발견: 격리 HOME에는 전역 git 신원이 없어, `test_workspace.py::test_new_seat_defers_submodule_initialization`이 실제 HOME의 git 신원에 의존하고 있었음이 드러났습니다(깨끗한 계정이면 실패). 그 test가 repo 신원을 직접 설정하게 고쳤습니다(99a3bc5). 다른 test는 영향이 없었습니다.
- README 검증의 자원 규칙에 "실제 HOME" 항목을 더했습니다.

**검증** (실제 HOME 대용으로 `HOME=<빈 임시 디렉터리>`를 주고 실행해, 그 디렉터리에 `.cache/project-item`이 생기는지로 판정)
- 0a849e9에서: `agent-session/tests`(-n 8) 920 passed 1 failed(위 부수 발견), `project-item/tests` 125 passed, `project-board/tests` 229 passed, 네 번째 명령 140 passed, `install/tests`(-n 8) 283 passed 2 skipped.
- 99a3bc5에서: `agent-session/tests`(-n 8) 921 passed.
- merge(8272163) 뒤: merge가 바꾼 `tools/project-item/`만 `project-item/tests` 141 passed, `agent-session/tests/test_api_boundary.py` 4 passed, `test_private_root.py`+`test_distribution_boundary.py` 20 passed. 나머지 명령은 merge 입력이 달라지지 않아 위 근거를 재사용합니다.
- 이 실행들이 만든 `.cache/project-item` 파일: **0개**(대용 HOME에는 `.gitconfig` 사본만 남음). 대조: 같은 명령을 격리 없이 계측했을 때 `test_remote.py` 4개, `test_answer.py` 13개 test가 새 파일을 만들었습니다.
- 문서: README의 새 link 대상이 존재하고 `test_distribution_boundary.py` 통과.
- 이미 쌓인 실제 HOME의 파일은 Contract 4대로 Leader가 정리합니다(이 Worker는 건드리지 않았습니다).

**수정 제출 (Leader 검토: 도구 위치 고정)**
- `private_root._isolate_home`이 HOME을 바꾸기 전에 `PYTHONUSERBASE`(=그때의 `site.getuserbase()`)와 `RUSTUP_HOME`(=그때의 `~/.rustup`)을 값이 비어 있을 때만 고정합니다. 이미 값이 있으면 그대로 두고 `CARGO_HOME`은 고정하지 않습니다. `private_root.py` 머리 설명과 README "실제 HOME" 항목에 예외와 이유를 적었습니다. 커밋 1ce00b9.
- Test(`tools/test_private_root.py`): 내부 pytest(default·`--basetemp`·xdist)의 test와 그 자식 Python이 보는 `site.getuserbase()`가 격리 전 값(`<실제 HOME>/.local`)과 같고 `RUSTUP_HOME`이 격리 전 `~/.rustup`임을 확인합니다. 이미 설정된 값이 그대로 남는 test 1개를 더했습니다.
- 검증 (제출 commit, 빈 임시 HOME을 실제 HOME 대용으로 사용): `agent-session/tests`(-n 8) 921 passed, `project-item/tests` 141 passed, `project-board/tests` 229 passed, 네 번째 명령 141 passed(link 검사 대상 `test_distribution_boundary.py` 포함), `install/tests`(-n 8) 283 passed 2 skipped. 대용 HOME에 `.cache/project-item` 파일 0개(`.gitconfig` 사본만 있음). 그 뒤 `origin/main`(INSTALL-008)이 진행해 merge했습니다(제출 commit). merge가 바꾼 입력만 다시 실행했습니다: `agent-session/tests/test_cron.py`+`test_api_boundary.py` 63 passed, `install/tests/test_crontab.py` 12 passed, `test_private_root.py`+`test_distribution_boundary.py` 21 passed, 대용 HOME에 `.cache` 없음. 나머지는 위 근거를 재사용합니다.

- 2026-11-12 Leader(Contract 4): 실제 HOME의 `~/.cache/project-item/locks/`를 정리했습니다. 등록 project 10개의 root 20개(`path_cr`·`path_decide`, project-item 등록 API로 계산) 잠금은 남기고, 그 밖에서 3시간 넘은 파일 2,894개(모두 0 byte)를 지웠습니다. 실행 중일 수 있는 최근 파일 5개는 남겼습니다(2,919 → 25).
