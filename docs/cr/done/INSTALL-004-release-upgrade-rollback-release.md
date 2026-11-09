# INSTALL-004: 동작 중 갱신을 위해 release 형식 버전으로 upgrade·rollback을 거절하고, 사용하지 않는 release를 정리하는 명령을 만듭니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Base: 4c4168325298d1ae1515696acbc16417de5d152e 2026-11-09T17:40:07+09:00
- Outcome: fixed

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
- 2026-11-09 Leader: 제출 cf29dcc4d55aaec355b3bd5cfc94e93582d66908를 인수합니다. Leader review: 삭제는 이미 검토한 _op_rm_tree(digest 대조 뒤 예약 임시 이름으로 rename·삭제)를 그대로 씁니다. plan_prune은 current·previous·사용 중 release와 digest가 없거나 다른 release를 남기고 알림만 하며, origins_in_use는 alive·unknown slot을 쓰는 것으로 보고 script를 못 찾으면 그 project의 모든 run 디렉터리를 쓰는 것으로 셉니다(보수적). 계획 뒤 시작하는 run은 current를 쓰므로 겹치지 않습니다. 형식 버전 거절(formats_differ, 동결 사본=1)과 Worker 판단 5건을 확인했습니다. install/tests 239 passed·2 skipped(merge 뒤 commit), 다른 suite는 53ce59a 근거 재사용(merge가 tools를 바꾸지 않음).
- 2026-11-09 Leader: in-progress -> done, Outcome fixed. 통합 0d6e99b(Merge cr/INSTALL-004, 제출 cf29dcc). origin/main 반영 확인. CHANGELOG Unreleased에 더했습니다.

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

## Result
- 제출 commit: cf29dcc4d55aaec355b3bd5cfc94e93582d66908

`origin/cr/INSTALL-004`에 push했습니다. 작업 commit은 53ce59a이고, 그 뒤 통합된 INSTALL-005(e49f466 등, `origin/main` 39022f7)를 merge했습니다. 충돌은 README·계약 8.2절·`cli.py`였습니다. INSTALL-005가 T24~T28을 썼으므로 이 CR의 인수 경우를 T29~T32로 매겼습니다.

변경:
- `install/project_agent_install/runs.py`: `origin_of_run`(run의 script가 가리키는 코드가 release인지, release가 아닌 사본인지), `origins_in_use`, `releases_in_use`(기존 함수, 같은 기준). 떠 있는 run은 `alive`·`unknown`입니다. tmux에 run이 없는 `unknown` slot처럼 script를 못 찾으면 그 project의 모든 run 디렉터리가 가리키는 코드를 쓴다고 봅니다(구분 못 하면 쓰는 것으로 봄).
- `release.py`: `read_formats`(`tools/formats.json`, 세 정수 검증)와 `FROZEN_FORMATS`(release가 아닌 경로의 run은 세 값 모두 1).
- `commands.py`: `upgrade`·`rollback`이 `_require_compatible`로 대상 release와 떠 있는 run의 형식 버전을 비교하고 다르면 `formats_differ`(종료 코드 3, 변경 없음)로 거절합니다. 출력은 project·slot·상태·다른 값과 restart 안내입니다. 선언을 읽을 수 없으면 `formats_unreadable`입니다. 떠 있는 run이 없으면 읽지도 않습니다. `plan_prune`: `current`·`previous`·사용 중인 release를 뺀 release를, 설치 기록의 `digest`가 지금과 같을 때만 지웁니다. 다르면 남기고 알립니다. Board가 켜져 있으면(`@project_board_enabled`=1) 알립니다.
- `actions.py`·`paths.py`·`record.py`·`journal.py`·`cli.py`: `prune` 명령(`--dry-run`, `--json`). release마다 "디렉터리 삭제(`rm_tree`, 먼저 `.tmp-<이름>`으로 옮김) → 설치 기록에서 뺌(`forget`, journal에는 release 식별자만)"을 하나씩 하는 redo journal(format 2 그대로)입니다. 중단되면 같은 `prune`만 끝내고 다른 명령은 `prune_interrupted`로 거절합니다(`uninstall`의 `uninstall_interrupted`는 그대로).
- 계약: 7절 명령 표에 `prune`, 7.1절 3·4항, 새 7.1.1절(형식 버전 판정, 동결 사본 규칙), 7.1.2절(`prune`), 8.2절 T29~T32, 2절 규칙 5의 중단 처리. `release.md` 3절은 7.1.1절을 가리킵니다. README의 test 범위 문구를 T1~T32로 고쳤습니다.
- test: `install/tests/test_prune.py`(18개)와 하네스의 `Runs.start_leader_from`.

판정·확인한 사실(Leader 확인 요청):
1. **동결 사본 규칙(3단계)**: script가 release 경로가 아닌 `/tools/agent-session`만 가리키는 run은 세 형식 모두 1로 봅니다. 첫 release는 세 값이 1이므로 막지 않습니다(T30).
2. **restart 안내의 한계**: `restart`는 run을 `current`의 release로 다시 시작합니다. run이 이미 `current`의 release를 쓰면 restart해도 형식이 같아지지 않으므로 출력은 그 경우 `agent-session stop`으로 끝낸 뒤 다시 실행하라고 안내합니다(계약 7.1.1절 5항).
3. **7.1절 4항(Board)**: 확인한 사실입니다. Board는 결정 답변을 보낼 때마다 시작한 release 안의 `agent-session`을 실행하므로(`answer.py:13,39-42`, `model.py:13`), 지워진 release에서 시작한 Board는 답변을 `send_unavailable`로 보내지 못합니다. 읽기 전용 목록이 지워진 release의 파일을 나중에 읽는지는 여전히 **(미확인)**이며 계약에 그대로 적었습니다.
4. `suspended`(shutdown 기록만 있는 slot)는 run이 없어 떠 있는 run으로 세지 않습니다. `resume`은 새 window를 현재 release로 시작합니다([suspend.py:_last_run·start_suspended](../../tools/agent-session/agent_session/suspend.py)는 옛 `launch.sh`를 실행하지 않고 대화 ID만 찾습니다).
5. 등록 파일이 있는데 읽을 수 없으면 `upgrade`·`rollback`·`prune`도 7.2절처럼 판정할 수 없어 거절합니다(`registry_unreadable`).

삭제 경로 독립 검토용 위치(Leader 요청 사항): `commands.py:plan_prune`(대상 선정), `actions.py:_op_rm_tree`(기존, digest 확인·rename·삭제)와 `_op_forget`(설치 기록에서 뺌, 디렉터리와 `.tmp-` 둘 다 없을 때만), `runs.py:origins_in_use`.

검증(제출 commit cf29dcc, 저장소 루트, `python`=`/primehome/tools/Inhouse/Python3/latest/bin/python3` 3.12.13):
1. `python -m pytest -q integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py`: 70 passed.
2. `python -m pytest -q -n 8 install/tests`: 239 passed, 2 skipped. 새 test_prune.py 18개 포함. T29(`upgrade`가 세 형식 값 각각이 다른 release를 alive·unknown run이 있으면 거절하고 `--dry-run`도 거절, snapshot 같음, run이 없거나 형식이 같으면 진행, 선언 없음은 `formats_unreadable`), T29b(`rollback`), T30(동결 사본 대용 run: `install`·같은 형식 `upgrade` 통과, 다른 형식은 거절), T31(`prune`: `current`·`previous`·alive/unknown run의 release와 사용자 파일이 있는 release는 남고 나머지만 삭제, `--dry-run --json`의 변경 목록과 실제 목록 같음, 설치 기록에서도 빠짐, `check` 통과, Board 알림), T32(첫 step 앞·뒤 SIGKILL 뒤 같은 `prune`이 마침).
3. 다음 세 명령은 INSTALL-005 merge 전 제출 commit 53ce59a에서 통과했습니다: `tools/project-item/tests` 120 passed, `tools/project-board/tests` 114 passed, `-n 8 tools/agent-session/tests` 730 passed. merge가 들여온 변경(INSTALL-005: 설치기·계약·CHANGELOG·CR 문서)은 이 세 도구의 코드를 바꾸지 않으므로(`git diff 53ce59a cf29dcc -- tools` 중 이 CR 밖 변경 없음) 재실행하지 않고 근거를 재사용했습니다.
4. 근거 재사용·재실행: 설치기 test는 merge 뒤 commit에서 전체를 다시 실행했습니다. 문서·경계 test도 merge 뒤 commit에서 다시 실행했습니다.
