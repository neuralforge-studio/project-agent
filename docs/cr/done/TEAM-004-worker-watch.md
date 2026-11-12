# TEAM-004: Worker 보고 기준과 watch 재보고 지시를 정합해 중간·중복 알림을 줄입니다

- Opened: 2026-11-13
- Scope: project-agent
- Severity: S2
- Requester: haroo, /Users/swkim/Work/haroo/haroo.desk, 2026-11-13

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
