# TEAM-004: Worker 보고 기준과 watch 재보고 지시를 정합해 중간·중복 알림을 줄입니다

- Opened: 2026-11-13
- Scope: project-agent
- Severity: S2
- Requester: haroo, /Users/swkim/Work/haroo/haroo.desk, 2026-11-13
- Base: e2d19e97bc782777fd104c9d2ec256159c4df438 2026-11-13T02:32:38+09:00
- Outcome: fixed

## Symptom
HAROO Worker가 준비·사전검토·개별 실행·병합·SHA 확인을 매번 장문 send로 전달하고, Leader가 다시 단계별 지시를 하면서 완료 배치가 잘게 나뉩니다. 현재 보고 원칙에는 중간·중복 보고 금지가 있지만 자동 watch는 제출 대기 Worker에게 동일 제출 재보고를 지시합니다.

## Evidence
- `skills/project-team/SKILL.md`의 보고와 검증 절은 상대의 다음 행동에 필요한 새 정보만 send하고 중간 hash/자체 해결 실패를 따로 보내지 않도록 합니다.
- `tools/agent-session/agent_session/watch.py:43-45`의 WORKER_NOTICE는 제출 대기 중 `send`로 CR ID와 제출 commit을 다시 알리라고 지시합니다. Leader에게도 별도 알림을 전하므로 같은 제출이 중복 전달됩니다.
- `skills/project-team/references/self-check.md:12`와 skill 정체 점검 절도 동일 재보고를 요구합니다.
- HAROO에서 이전 수정한 `/Users/swkim/Agent/agent.stable/codex/skills/project-team/SKILL.md`는 현재 런타임 원본이 아닙니다. 실제 `~/.codex/skills/project-team`은 `~/.local/lib/project-agent/current/skills/project-team`으로 연결되고 current는 `releases/0.11.0-cfa0856113ed`입니다. 옛 사본만 수정하면 실제 Worker 지침은 바뀌지 않습니다.

## Contract
보고 skill과 자동 prompt가 같은 기준을 제공해야 합니다. 작업 상세 근거는 CR Result, 알림은 상대의 다음 조치에 필요한 요약이 원본입니다. 기존 제한·안전 사고·실제 외부 차단은 숨기지 않고, 전달 불명 메시지를 자동 재전송하지 않습니다. 설치 release를 직접 편집하지 않고 소유 원본과 정상 배포 경로로 반영해야 합니다.

## Disposition
- 2026-11-13 Leader 판정: 재보고 지시는 watch.py의 WORKER_NOTICE와 spec의 watch·check에 명시한 정책입니다. 기존 코드가 명세를 위반한 결함으로 단정하지 않습니다. 정책 변경은 위임 범위 밖이므로 D-20261113-01에서 사용자에게 A(동일 제출 재보고 제거, Leader 점검 유지) 또는 B(현행 예외 유지)를 묻습니다. 동료 요청은 사용자 승인으로 사용하지 않습니다. 결정 전 원본·설치 release·다른 project는 수정하지 않습니다.

- 2026-11-13 Leader: D-20261113-01의 저장된 사용자 답변 원문 "A"를 확인했습니다. 동일 제출 재보고 지시를 제거하고 Leader 점검을 유지하는 범위를 승인했습니다. 정체 판정·주기·전송 불명 처리·안전 알림은 바꾸지 않습니다.
- 2026-11-13 Leader: open -> todo. D-20261113-01 A에 따라 동일 제출 재보고 지시 제거, Leader 점검 유지

- 2026-11-13 Leader 판정: 최초 start가 기존 seat의 main(b2772f8)과 origin/main 이력 차이로 fast-forward를 거절했습니다. 기존 checkout 전체를 `/Users/swkim/Agent/project-agent.seat0.backup-20261113-TEAM-004`에 보존했습니다. 설치본은 없는 seat를 자동 생성하지 않고 seat_unavailable로 거절하여, 같은 등록 경로에 origin을 clone한 뒤 정식 start를 재실행했습니다. seat 0, run 7a0485ea905146b8a198bf222a8e608b의 ready=true를 확인했습니다. 상태 JSON과 기존 branch는 직접 고치지 않았습니다.

- 2026-11-13 Leader 검토: 제출 4a104a2d59d7b569a645504b4815cab52368c560의 5개 파일 변경은 사용자 선택 A 범위에 맞습니다. watch 판정과 Leader 알림을 유지하며 Worker prompt·skill·self-check·spec을 정합했습니다. 직접 영향 및 문서 검사 근거는 재사용합니다. 다만 필수 회귀 19건 중 기존 실패인지 입증되지 않은 항목과 원인 미확인 cron 4건이 있어 인수를 보류합니다. 동일 실패의 Base 비교 또는 독립적인 환경 원인 근거를 요청합니다. 변경 없는 전체 suite 반복은 요구하지 않습니다.

- 2026-11-13 Leader 검토 완료: 제출 4a104a2d59d7b569a645504b4815cab52368c560의 기존 코드 검토와 직접 영향 22 passed·문서 70 passed 근거를 재사용합니다. `/tmp/team004-base-failures.log`에서 14건의 동일 Base 실패를 확인했고 `/tmp/team004-submission-tmux.log`에서 나머지 5건 재실행 통과를 확인했습니다. 제품 변경은 Worker prompt 문자열과 동반 문서·검사뿐이므로 Base 동일 실패는 이번 변경의 회귀가 아닙니다. tmux 최초 실패의 원인은 미확정이며 해소됐다고 주장하지 않습니다. 이 제한을 남겨 소스 변경을 인수합니다. 전체 회귀 통과·release readiness·실제 배포를 뜻하지 않습니다. macOS 검증 실패의 후속 소유 범위는 본 저장소 agent-session test이며 근거는 Result에 유지합니다.
- 2026-11-13 Leader: 제출 4a104a2d59d7b569a645504b4815cab52368c560를 인수합니다. 직접 영향 통과, 14건 Base 동일 실패 및 tmux 5건 양쪽 재실행 통과 근거 확인. 최초 tmux 실패 원인과 전체 macOS 회귀 제한은 Result에 보존
- 2026-11-13 Leader: in-progress -> done, Outcome fixed. 제출 4a104a2를 f5c1f0d로 통합하고 origin/main 반영 확인. 설치 release 미반영

## Implementation
요청자가 제안한 범위이며 대상 Leader가 판정하십시오. 공통 skill의 보고와 검증/Worker/정체 점검, self-check 및 watch의 WORKER_NOTICE에서 중간·동일 상태 재보고 지시를 없애고 완료 배치 제출·외부 차단·종료만 간결하게 알리도록 정합하십시오. 준비→실행→검증마다 선검토 회신을 기본 요구하지 않고 feedback은 한 배치로 모으십시오. 기존 Leader 점검과 안전 알림은 유지합니다. 자동 보고 억제를 위한 새 queue/상태 원장은 만들지 않습니다. 변경 후 실제 사용 release까지 반영 여부를 구분해 알려 주십시오.

읽을 지침: [Worker 절](../../../skills/project-team/SKILL.md#worker), [README 검증](../../../README.md#검증), [동작 명세 watch·check](../../project-team/spec.md#watch).
- 소유 범위: `tools/agent-session/agent_session/watch.py`의 WORKER_NOTICE, 직접 연관 test, `skills/project-team/SKILL.md`, `skills/project-team/references/self-check.md`, `docs/project-team/spec.md`의 동일 제출 재보고 설명.
- watch의 Worker 지시는 CR에 제출과 보고를 마쳐 Leader 회신만 기다리는 경우 같은 hash를 재전송하지 않도록 합니다. 새 제출·새 외부 차단·종료 준비 완료 보고는 유지합니다. Leader 점검 prompt와 알림은 유지합니다.
- 문서가 같은 계약을 설명하도록 정합하고, 불필요한 단계별 선검토 요구가 있는지 해당 범위만 확인합니다. 새로운 queue·원장·상태를 추가하지 않습니다.
- 위험: 낮음. 정체 판정과 관리 동작은 그대로이며 prompt와 문서를 정합합니다. 설치된 release를 직접 수정하거나 실제 HOME에 설치기를 실행하지 않습니다. VERSION·release tag는 변경하지 않습니다.

## Verification
- README의 변경 경로 필수 검사: `python -m pytest -q -n 8 tools/agent-session/tests` (xdist가 없으면 -n 제외).
- 문서: 변경한 상대 link 검사, `python -m pytest -q tools/test_distribution_boundary.py`, `python -m pytest -q tools/agent-session/tests/test_remote.py`.
- focused: watch prompt의 제출 대기 재전송 억제, 새 차단 보고 유지, Leader 점검 유지에 대한 관찰 가능한 검사를 기존 watch test에 맞춰 수행합니다. 변경 전후 명령과 결과를 Result에 적습니다.
- 배포 확인은 소스 제출과 실제 설치 release를 구분해 보고합니다. 설치·전체 release 검증은 Worker 범위가 아닙니다.
변경된 watch prompt와 제출 대기/차단 시나리오의 focused 검사, 기존 직접 영향 검사 및 문서 상충 문구 확인. 실제 프로젝트 start/stop·장시간 fixture·전체 regression을 이 요청의 기본 검증으로 수행하지 않습니다. 실제 배포는 대상 프로젝트의 정상 정책을 따릅니다.

## Result
요청 프로젝트 HAROO에서는 `docs/operations/management.md#worker-reports`를 추가하고 현재 Worker에게 같은 기준을 적용합니다. 공통 도구/skill 원본은 요청자가 수정하지 않았습니다.

- 제출 commit: 4a104a2d59d7b569a645504b4815cab52368c560
- 변경: watch Worker prompt와 skill·self-check·명세에서 같은 제출 재보고를 없애고 새 제출·새 외부 차단·종료 준비 보고를 유지했습니다. Leader 점검과 정체 판정은 변경하지 않았습니다. 단계별 선검토 요구 및 상충 재보고 문구는 대상 범위에서 발견하지 않았습니다.
- 변경 전 focused: `/Users/swkim/python/.venv/bin/python -m pytest -q tools/agent-session/tests/test_watch.py::test_a_worker_that_waits_for_the_leader_is_woken_and_told_to_remind_the_leader` 1 passed. 새 기대를 적용한 같은 검사는 구현 전 1 failed(재보고 금지 문구 부재), 구현 후 1 passed.
- 제출 commit 직접 영향: `TMPDIR=/tmp /Users/swkim/python/.venv/bin/python -m pytest -q -n 8 tools/agent-session/tests/test_watch.py tools/agent-session/tests/test_check.py::test_the_check_wakes_a_stalled_worker_as_watch_does` 22 passed, 1 skipped. Worker 메시지의 재보고 억제·새 외부 차단 보고 및 Leader 알림·반복 점검을 확인했습니다.
- 필수 검사: `/Users/swkim/python/.venv/bin/python -m pytest -q -n 8 tools/agent-session/tests` 947 passed, 3 skipped, 19 failed. macOS의 긴 임시 Unix socket 경로에 따른 websocket 실패 9건, tmux respawn 실패 5건, cron 실행 결과 관련 실패 4건, `/proc` 접근 기대 실패 1건입니다. 짧은 `TMPDIR=/tmp`로 watch·check를 재실행하면 40 passed, 1 skipped, cron 실행 결과 관련 4 failed였고 해당 4건의 원인은 미확인입니다. 전체 회귀 통과는 확인하지 못했습니다.
- 문서 검사: 상대 링크 및 anchor 25개 정상, `python -m pytest -q tools/test_distribution_boundary.py tools/agent-session/tests/test_remote.py` 70 passed, `git diff --check` 정상. macOS 실제 crontab 전후 비교 동일.
- `origin/main`은 시작 Base와 동일하여 merge 및 그에 따른 재실행은 불필요했습니다. 제출 branch를 origin에 push했습니다. 현재 설치 release `0.11.0-cfa0856113ed`에는 반영하지 않았으며 설치·배포는 이 Worker 범위가 아닙니다.

### 필수 회귀 실패 후속 조사 (제출 4a104a2)

- Base `e2d19e97bc782777fd104c9d2ec256159c4df438`를 `git archive`로 `/tmp/team004-base.7yldMn`에 풀어 branch 전환 없이 실패 node와 `test_websocket.py`를 재실행했습니다. 명령과 상세 traceback·node 목록은 `/tmp/team004-base-failures.log`에 있습니다. 결과 14 failed, 6 passed이며 14건은 제출에서 난 동일 실패입니다. 최초 전체 실행의 traceback은 이 대화의 pytest 도구 출력에 있고 별도 로그 파일은 생성되지 않았습니다.
- cron 4건: `test_check.py::test_the_check_line_reaches_the_recorded_tmux_where_a_wrong_tmux_stands_in_cron_path`, `::test_a_line_that_ignores_the_record_fails_with_the_wrong_tmux_in_cron_path`, `::test_a_record_without_a_tmux_names_tmux_unavailable`, `::test_a_missing_tmux_file_names_tmux_unavailable`. Base에서도 같은 4건이 실패했습니다. 최소 환경 PATH가 `/usr/bin:/bin`인 test에서 macOS `/usr/bin/python3`은 3.9.6입니다. Base에서 `env -i HOME=/tmp PATH=/usr/bin:/bin tools/agent-session/bin/agent-session --help`를 실행하면 `python_version`(Python 3.10 이상 필요), exit 5가 나오며 cron 명령은 출력을 버립니다. 따라서 check 실행 전 종료되어 `check.json`이 없거나 exit 5가 발생한 것입니다. 네 test의 `wrong_tmux` PATH도 python3을 제공하지 않아 같은 선택을 합니다. Base 재현과 실행기 확인으로 이번 prompt 변경의 영향이 아님을 확인했습니다.
- Unix socket 9건: `test_websocket.py::test_masked_initialize_and_fragmented_response_with_ping`, `::test_pagination_reads_every_page`, `::test_repeated_cursor_is_an_error`, `::test_rejects_bad_handshake`, `::test_rejects_invalid_or_truncated_frames[large]`, `::test_rejects_invalid_or_truncated_frames[continuation]`, `::test_rejects_invalid_or_truncated_frames[masked]`, `::test_rejects_invalid_or_truncated_frames[truncated]`, `::test_rpc_error_is_not_an_empty_success`. Base에서도 모두 `OSError: AF_UNIX path too long`으로 실패했습니다. 기본 macOS TMPDIR의 긴 임시 경로에서 socket bind가 실패한 것으로 이번 변경과 독립적입니다.
- process 1건: `test_process.py::test_session_holders_reports_an_unreadable_process_list_as_unknown`. Base에서도 동일하게 `DID NOT RAISE SessionError`로 실패했습니다. `/proc` cmdline 읽기 실패를 가정하는 검사이며 macOS에서는 그 경로가 Linux와 다릅니다.
- tmux 5건: `test_internal.py::test_registration_waits_for_the_control_lock_inside_its_limit`, `test_lifecycle.py::test_rejected_stop_request_does_not_mark_a_ready_session_stopping`, `::test_a_run_of_another_base_gets_no_input_through_its_socket`, `::test_accepted_feedback_reports_a_failed_review_clear_without_failing`, `test_check.py::test_the_check_is_for_one_project_and_the_operator_or_its_leader`. 최초 전체 실행에서는 모두 `respawn-pane`의 `tmux_command_failed`였으나 stderr 상세는 pytest traceback에 표시되지 않았습니다. 동일 node만 Base에서 5 passed, 제출 commit에서 `-n 8`로 재실행해 5 passed(`/tmp/team004-submission-tmux.log`)였습니다. 원인은 확인되지 않았고 최초의 환경성·간헐성은 가설입니다. 두 소스의 개별 재실행 결과는 이번 변경에 의한 지속 실패를 뒷받침하지 않지만 최초 실패의 인과를 확정하지는 못합니다.
- 위 node ID는 `tools/agent-session/tests/` 기준입니다. 후속 조사 전후 실제 crontab은 동일했습니다. 제품 변경은 추가하지 않았으며 기존 직접 영향·문서 검증을 재사용합니다.
