# INSTALL-004: 동작 중 갱신을 위해 release 형식 버전으로 upgrade·rollback을 거절하고, 사용하지 않는 release를 정리하는 명령을 만듭니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2

## Symptom
설치·갱신·되돌리기는 관리 run이 떠 있는 동안 합니다. 옛 release와 새 release가 한동안 같은 state·tmux option·CR 파일을 함께 씁니다. 형식이 호환되지 않는 갱신을 막는 장치가 없습니다. 또 `upgrade`는 이전 release를 지우지 않으므로 release가 계속 쌓이고, 정리 명령이 없습니다.

## Evidence
- INSTALL-001 Contract 4항(사용자 지적 2026-11-09 "조용한 시점이 어디있어.. 없을 건데..")
- 설치 계약 7.1절 2항(사용 중인 release는 지우지 않음), 3항(정리 명령의 이름과 시점은 4단계가 정함)
- run의 script는 release의 해석된 절대 경로를 가집니다(`tools/agent-session/agent_session/launch_artifacts.py:23`).
- agent DIST-001 6단계: 첫 release는 agent 저장소의 동결 사본과 state·tmux option·CR 형식이 같아야 합니다.

## Contract
- 떠 있는 run의 release와 형식이 호환되지 않는 `upgrade`·`rollback`은 거절하고, 그 run의 project·slot과 restart 안내를 출력합니다.
- 사용 중인 release, `current`, `previous`는 지우지 않습니다(계약 7.1절).
- 형식 버전의 선언 위치와 값은 RELEASE-001이 정합니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). INSTALL-001 Contract 4항과 설치 계약 7.1절 3항이 정한 일을 INSTALL-001에서 떼어 냈습니다(사용자 지시 2026-11-09 "병렬로 진행 가능 한 것은 병렬로 진행해. 남은 CR은 전부 등록해서…"). 승인한 계획(agent DIST-001 4단계)의 하위 작업이므로 위임 범위입니다. INSTALL-001과 RELEASE-001이 통합된 뒤 시작합니다.
- 2026-11-09 Leader: 선행 INSTALL-001이 ecc5bce로 통합되었습니다. 설치기 구조를 따르십시오: 경로는 `paths.Places`의 닫힌 식별자에서만 계산(원칙 A), 되돌림·제거는 설치기가 만든 상태일 때만(원칙 B), 사용자 tmux 파일은 원자적 교체(원칙 C), journal format 2(계약 2절 규칙 5). INSTALL-004와 INSTALL-005는 병렬로 진행하므로 같은 설치기 파일을 고칠 수 있습니다. 제출 전에 `origin/main`을 merge하십시오.

## Implementation
읽을 문서: [설치 계약](../../project-team/install-contract.md) 7절·7.1절·7.2절·8절, INSTALL-001의 설치기 코드와 test 하네스, RELEASE-001이 정한 형식 버전의 선언.

1. 떠 있는 run 찾기: INSTALL-001이 둔 함수(등록된 모든 project의 `<base>/agent/runs/*/` script의 release 경로 + `agent_session.api.liveness`)를 씁니다. `alive`·`unknown`을 떠 있는 것으로 봅니다(7.2절과 같은 기준).
2. 형식 호환 판정: release마다 RELEASE-001이 정한 위치의 형식 버전(state·tmux option·CR)을 읽습니다. `upgrade`·`rollback`의 대상 release와 떠 있는 run의 release 중 하나라도 형식 버전이 다르면 거절합니다. 거절하면 아무것도 바꾸지 않고, run의 project·slot과 "그 run을 restart한 뒤 다시 실행" 안내를 출력합니다.
3. release가 아닌 경로에서 시작한 run(agent 저장소의 동결 사본 `…/codex/tools/agent-session`)의 판정 규칙을 정합니다. 첫 release는 그 사본과 형식이 같으므로 agent DIST-001 6단계의 전환을 막지 않아야 합니다. 예: 동결 사본을 형식 버전 1로 봅니다. 규칙을 계약 7.1절에 적습니다.
4. 정리 명령: 이름을 정하고(예: `prune`), `current`·`previous`·사용 중인 release를 뺀 release 디렉터리를 지웁니다. `--dry-run`을 받습니다. 지운 release를 설치 기록에서도 뺍니다. 7.1절 3항에 이름과 규칙을 적습니다.
5. 7.1절 4항(Board process가 지워진 release를 읽는지 미확인)은 정리 명령이 Board가 켜져 있으면 그 사실을 알리는 것으로 다룹니다. 확인한 사실이 있으면 계약에 적습니다.

범위 밖: 형식 버전의 선언 위치와 값(RELEASE-001), 설치기 핵심(INSTALL-001).

의존: 선행 INSTALL-001, RELEASE-001. 후행 RELEASE-002.

위험 등급: 중간. release 삭제는 되돌릴 수 없습니다. 사용 중 판정이 틀리면 떠 있는 run의 hook·controller가 지워진 코드를 부릅니다. 인수 전에 Leader가 삭제 경로를 독립 검토로 확인합니다.

## Verification
격리 HOME과 fake run(state·run 파일·격리 tmux window)으로 자동 test를 만듭니다(INSTALL-001 하네스).
1. 형식 버전이 다른 release로의 `upgrade`·`rollback`: 떠 있는 run이 있으면 거절, snapshot이 같고 출력에 project·slot이 있습니다. 떠 있는 run이 없거나 형식이 같으면 진행합니다.
2. 동결 사본 경로의 run: 3단계 규칙대로 판정합니다(첫 release로의 `install`·`upgrade`를 막지 않음).
3. 정리 명령: `current`·`previous`·`alive`/`unknown` run이 쓰는 release는 남고, 나머지만 지워집니다. `--dry-run`의 목록과 실제 삭제 목록이 같습니다.
4. README의 설치기 test 명령과 기존 네 명령이 통과합니다.
