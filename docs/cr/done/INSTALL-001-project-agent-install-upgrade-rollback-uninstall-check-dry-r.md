# INSTALL-001: 설치 계약대로 project-agent 설치기(install·upgrade·rollback·uninstall·check·dry-run)와 격리 HOME 인수 test를 만듭니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Requester: agent, /primehome/swain/Utils/agent/agent.base, 2026-11-09
- Base: 9458aba01535c1a12ee034ce725048aca5448c10 2026-11-09T14:40:54+09:00
- Outcome: fixed

## Symptom
project-agent를 다른 직원에게 배포하려면 설치기가 있어야 합니다. 설치·갱신·되돌리기·제거 중 그 사람의 다른 설정에 영향이 없어야 합니다. 설치 계약은 정해졌지만 설치기는 아직 없습니다. 지금은 개발 checkout을 symlink로 거는 방식만 있습니다.

## Evidence
- 설치 계약: `docs/project-team/install-contract.md`(REPO-001 뒤에는 새 docs 위치). 2절(만드는 것과 규칙 1~7), 3절(tmux include 블록), 4절(건드리지 않는 것), 6절·6.1절(등록 파일, `PROJECT_AGENT_PYTHON`·`PROJECT_AGENT_PYTHONPATH`), 7절(명령의 동작, 7.1 떠 있는 run, 7.2 uninstall 거절), 8절(인수 test T1~T23)
- launcher: `codex/tools/python-launcher.sh`. 원격 runtime은 설치 기록 `~/.local/lib/project-agent/install.json`이 있으면 skill link를 만들지 않습니다(`remote_runtime.py`의 `_install_skills`).
- 외부 package: `codex/tools/project-board/requirements.txt`(`textual==8.2.8`). 2026-11-09 workstation 사내 Python 3.12.13에는 8.2.8이 설치되어 있습니다. 이 workstation에서 외부 package index에 닿는지는 확인하지 않았습니다.

## Contract
- 사용자 결정(agent D-20261109-08 C, -09 C): 배포 중 다른 설정에 영향이 없어야 합니다. 기존 파일 수정은 tmux 설정의 include 블록 한 줄뿐입니다. 이름이 겹치면 아무것도 바꾸지 않고 거절합니다. 제거하면 설치가 만든 것만 지웁니다.
- 설치 계약의 2·3·6.1·7절이 설치기의 원본이고, 8절이 인수 test의 원본입니다. 계약과 다르게 구현해야 할 사정이 생기면 계약을 먼저 고치고 그 이유를 기록합니다.
- 갱신은 떠 있는 run에 영향을 주지 않습니다. run은 해석된 release 경로를 쓰고, 그 release는 참조가 남아 있는 동안 지우지 않습니다.
- 동작 중 갱신(사용자 지적 2026-11-09: "조용한 시점이 어디있어.. 없을 건데.."): 조용한 시점은 없습니다. 설치·갱신·되돌리기는 관리 run이 떠 있는 동안 해야 합니다. 한동안 옛 release와 새 release가 같은 state·tmux option·CR 파일을 함께 쓰므로, release마다 이 형식의 버전을 밝힙니다. 떠 있는 run의 release와 형식이 호환되지 않는 갱신은 거절하고, 그 run이 restart로 빠질 때까지 기다리게 안내합니다.
- 옛 개발 checkout link 넘겨받기(이 workstation 전환용, agent DIST-001 6단계): 진입점이 이미 있고, 알려진 옛 개발 checkout 경로를 가리키는 symlink일 때만 넘겨받습니다. 예: `~/.local/bin/agent-session` → `<checkout>/codex/tools/agent-session/bin/agent-session`. 넘겨받을 때는 원자적으로 교체하고, 이전 대상을 설치 기록에 남겨 되돌릴 수 있게 합니다. 그 밖의 이름 충돌은 지금 계약대로 거절합니다. 명시 옵션으로만 켜고, 계약 2절에 규칙으로 더합니다.

## Disposition
- 2026-11-09 Leader: 판정 보류(open 유지). REPO-001이 저장소 배치를 바꾸는 중이므로, 그 통합 뒤의 경로로 Implementation·Verification을 써서 판정합니다. 판정에 필요한 입력은 REPO-001이 통합한 배치입니다. 순서는 사용자가 2026-11-09 대화에서 지시했습니다. 사용자 원문: "제안 진행 순서대로 진행".
- 2026-11-09 Leader: 고친다(Leader 판정). REPO-001(1e06cac)과 TMUX-001(e5ac6db)이 통합되어 판정 입력이 갖춰졌습니다. 이 CR은 agent의 승인한 계획 DIST-001 4단계이고, 동작과 인수 test는 설치 계약 2·3·6.1·7·8절이 이미 정했습니다. 그러므로 위임 범위(승인한 작업의 하위 작업)입니다. 단, 외부 package를 가져오는 방법은 사용자 결정 D-20261109-01로 묻습니다. 2026-11-09 확인 결과 이 workstation의 pip는 저장소에 닿지 않아(`pip download` 시간 초과) 계획의 `pip install --target`만으로는 설치가 끝나지 않습니다. 그 단계 밖의 구현은 결정을 기다리지 않습니다.
- 2026-11-09 Leader: 범위를 나눕니다(Leader 판정). 사용자 지시(2026-11-09 대화): "seat 3자리인데, 4자리 만들어서, 병렬로 진행 가능 한 것은 병렬로 진행해. 남은 CR은 전부 등록해서 얼마나 남았는지 알 수 있게 해줘." 이 CR은 핵심 설치기(release, 2절 진입점, 3절 tmux 블록, 7절 명령, 8절 T1~T23)만 맡습니다. 떼어 낸 일: release 진입점의 interpreter 선택은 INSTALL-002, 외부 package는 INSTALL-003(D-20261109-01), 형식 버전 거절과 release 정리 명령은 INSTALL-004, 옛 checkout link 넘겨받기는 INSTALL-005, 버전 값과 형식 버전의 선언은 RELEASE-001입니다. INSTALL-002·RELEASE-001과 병렬로 진행하므로 그 사이의 interface는 아래 Implementation이 정합니다.
- 2026-11-09 Leader: 사용자 결정 D-20261109-01 waive를 반영합니다. 외부 package를 release에 넣지 않으므로 Implementation 2단계의 package 항목을 고쳤습니다. 사용자 답변 원문: "D-20261109-01 Waive / Refactoring 이후에, rust로 변경가능한 것들은 변경할 것임. 너무 느림."
- 2026-11-09 Leader: 제출 31e7412 수정 요청. Leader가 제출 snapshot에서 `install/tests` 103 passed·1 skipped를 다시 확인했습니다. 실제 기본 tmux server에는 Worker 사건의 흔적이 없습니다(`fx` session 없음, `@project_agent_*` option·`[project-agent]` hook 0개, 사용자 `prefix B` 그대로). 독립 검토(sub-agent)가 찾은 결함을 Leader가 코드에서 확인했습니다: (1) 설치 기록의 항목을 검증하지 않고 지움(`layout.py:63-64` `expand`, `commands.py:309-327`), (2) tmux 블록 제거가 사용자 파일을 O_TRUNC 뒤 한 번 write(`actions.py:198-201`), (3) 블록 추가의 되돌림이 write 뒤에 등록되고 backup이 계획 시점 bytes(`actions.py:169-180`), (4) `force_rmtree`의 `ignore_errors=True`(`actions.py:114-118`), (5) 중단(signal·임시 파일 실패) 뒤 설치 기록 없는 잔여물로 install·uninstall이 모두 막힘. 그 밖에 main과 `install-contract.md` 충돌(INSTALL-002가 6.1·5.3·9절을 고침). 상세는 feedback 파일과 같습니다.
- 2026-11-09 Leader: 수정 제출 3462c8a 수정 요청. 1차 지적 7건의 반영과 수정 전 실패 test(44건 중 43건 실패 확인), `install/tests` 160 passed를 확인했습니다. 두 번째 독립 검토(sub-agent)가 새 안전 장치에서 결함을 찾았고 Leader가 코드에서 확인했습니다: journal의 `drop_journal`이 모든 경로를 허용(`paths.py:141`), `rmtree`의 `temp`·`relink`의 `previous` 미검증(`actions.py:232-250`), `write_file`의 되돌림이 내용 확인 없이 지움(`actions.py:285`, 계획 뒤 생긴 사용자 파일 삭제 가능), SIGKILL 뒤 남는 임시 파일로 다시 잠김, `_cut_block`의 중간 종료로 tmux 파일 손상, `_untruncate`의 prefix 판정 오류, resume의 `Changed`가 traceback으로 끝나 uninstall이 막힘. 공통 원인은 journal이 경로·동작을 자유롭게 담는 두 번째 명령 언어라 동작마다 신뢰 규칙이 따로 필요하다는 점입니다. 원칙 하나(아래 feedback)로 닫도록 요청합니다.
- 2026-11-09 Leader: 2차 수정 제출 9943b6d 수정 요청(마지막 범위 한정). 원칙 A·B·C의 구조 반영과 수정 전 실패 test 13건, `install/tests` 184 passed를 확인했습니다. 세 번째 독립 검토(sub-agent): 높음 등급 결함 없음, 이전 수정의 퇴행 없음. 남은 중간 등급: uninstall의 release·backup 삭제(`_op_rm_tree`, `actions.py:373-379`)가 상태 확인 없이 지움(원칙 B), tmux 파일 교체가 소유자·group·ACL·xattr·읽기 전용을 보존하거나 거절하지 않음(`actions.py:213-240`), backup 파일 mode가 umask를 따라 원본보다 넓어짐(`actions.py:188`), journal의 base64 미검증과 recover가 `OSError`만 잡아 traceback으로 막힘(`journal.py:148·161`, `paths.py:234-236`). provider 홈이 기록·journal 값을 따르는 점은 피해가 link 대상 일치·빈 디렉터리로 제한되므로 계약의 예외로 적어 받아들입니다. 그 밖에 main의 README와 충돌.
- 2026-11-09 Leader: 제출 1c45777f0ad54df18ecf2df4835fd1662f99dc23를 인수합니다. Leader review: 3차 지적 5건만 고친 delta를 확인했습니다. _op_rm_tree는 기록한 digest와 같을 때만 예약 임시 이름으로 rename 뒤 지우고(끊기면 다음 실행이 마저 지움), backup은 기록한 파일만 지운 뒤 빈 디렉터리만 rmdir합니다. tmuxconf.rewrite_problem이 hard link·다른 소유자·읽기 전용·ACL/xattr·1 MiB 초과를 판정하고 계획과 실행이 같이 씁니다. 손상 journal은 정해진 오류로 끝납니다. 새 test 8건 중 7건이 수정 전 실패, merge한 1c45777에서 install/tests 194 passed·2 skipped. 세 차례 독립 검토(31e7412·3462c8a·9943b6d)의 높음·중간 지적이 모두 닫혔습니다.
- 2026-11-09 Leader: in-progress -> done, Outcome fixed. 통합 ecc5bce(Merge cr/INSTALL-001, 제출 1c45777). origin/main 반영 확인. CHANGELOG Unreleased에 더했습니다.

## Implementation
읽을 문서: [설치 계약](../../project-team/install-contract.md) 전체(원본), [제품 지도](../../project-team/README.md)의 실행 경로 계약, [README의 검증](../../../README.md#검증). 이 CR의 Contract와 설치 계약이 범위의 원본입니다. 계약과 다르게 구현해야 하면 계약을 먼저 고치고 이유를 적습니다.

> **경고:** 개발 중 설치기를 실제 HOME(`/primehome/swain`)에 실행하지 않습니다. 모든 실행은 8.1절의 격리 HOME에서 합니다. `--dry-run`도 격리 HOME에서만 실행합니다. 이 workstation의 전환은 agent DIST-001 6단계가 합니다.

1. 설치기 위치와 진입점: `install/` 아래에 표준 library만 쓰는 Python 설치기를 둡니다. 개발 checkout과 release(`current/install/`) 양쪽에서 실행됩니다. 명령은 `install`, `upgrade`, `rollback`, `uninstall`, `check`와 공통 `--dry-run`(7절)입니다.
2. release 만들기: 원본 checkout의 제품 경로(`tools/`, `skills/`, `docs/`, `integrations/`, `install/`, root 문서)를 `releases/<version>-<hash>/`에 같은 상대 배치로 복사합니다. test·`__pycache__`·`docs/cr`는 넣지 않습니다. release는 만든 뒤 바꾸지 않습니다.
   - `<version>`: 저장소 root의 `VERSION` 파일 첫 줄입니다. 파일의 원본과 규칙은 RELEASE-001이 만듭니다. RELEASE-001이 아직 main에 없으면 test는 fixture 원본 tree에 `VERSION`을 둡니다. 설치기는 `VERSION`이 없으면 거절합니다.
   - `<hash>`: 원본 commit입니다. 작업 트리가 깨끗하지 않을 때의 동작(거절 또는 내용 해시)을 하나로 정해 계약에 적습니다.
   - interpreter 기록(INSTALL-002와의 interface): release를 만들 때 `<release>/tools/python.env`를 씁니다. 한 줄에 `NAME=값` 하나이고, 이름은 `PROJECT_AGENT_PYTHON`(설치 interpreter의 절대 경로)과 `PROJECT_AGENT_PYTHONPATH`(release 안 package 디렉터리. 없으면 빈 값) 두 개뿐입니다. 값은 따옴표 없이 줄 끝까지입니다. 이 파일을 읽는 쪽은 INSTALL-002가 만듭니다. 개발 checkout에는 이 파일이 없습니다.
   - 외부 package: release에 넣지 않습니다(사용자 결정 D-20261109-01 waive, INSTALL-003 done waived). `PROJECT_AGENT_PYTHONPATH`는 빈 값입니다. Board는 설치 interpreter에 있는 `textual`을 씁니다. 설치 계약 2절(release 안의 외부 package)과 6.1절의 서술을 이 결정에 맞게 먼저 고칩니다. `check`는 설치 interpreter에서 `tools/project-board/requirements.txt`의 버전을 import할 수 있는지 안내합니다(실패가 아닙니다).
3. 2절의 진입점: shim 3개, skill link 4개(규칙 7의 provider 홈), `tmux.conf`, 설치 기록 `~/.local/lib/project-agent/install.json`(원격 runtime의 `INSTALL_RECORD`와 같은 경로), 등록 파일 초안(6절 조건). 규칙 1~7(충돌 거절, 부모 디렉터리 기록, provider 홈 없음, 부모 symlink, 실패 시 원상 복구, 원격 runtime link 넘겨받기, provider 홈 변수)을 구현합니다. shim 형태를 정하고 2절에 적습니다.
4. 3절의 tmux 블록: 대상 선택, 블록 넣기·지우기의 byte 보장, backup, symlink 대상의 안내, 실행 중 server에는 다시 읽는 명령만 출력합니다. 표시 줄의 정확한 글자를 계약 3절에 옮깁니다.
5. 7절의 `upgrade`·`rollback`·`uninstall`·`check`를 구현합니다. 7.1절 1·2항(떠 있는 run의 release를 지우지 않음, `current`의 원자적 교체)과 7.2절(`uninstall` 거절: `agent_session.api.liveness`의 `alive`·`unknown`, `suspend.json`, `--force` 없음)을 따릅니다. `check`의 "binding 건너뜀"은 server option `@project_agent_board_skipped`(계약 3.1절)를 읽습니다. `uninstall`의 되돌림 명령은 계약 5.3절의 binding·hook 목록에서 만듭니다. 떠 있는 run과 release의 대응을 찾는 함수는 INSTALL-004가 형식 버전 판정에 다시 쓸 수 있게 한 곳에 둡니다.
6. 인수 test: 8절 T1~T23을 자동 test로 구현합니다(8.1절 하네스: 격리 HOME, snapshot diff, 격리 tmux server는 `-S` private socket). INSTALL-004·005가 같은 하네스에 경우를 더할 수 있게 둡니다. README의 검증 절에 설치기 test 명령을 더합니다.

범위 밖: INSTALL-002(release 진입점의 interpreter 선택), INSTALL-004(형식 버전 거절, release 정리 명령), INSTALL-005(옛 checkout link 넘겨받기), RELEASE-001(버전 값과 규칙), 이 workstation의 전환(agent DIST-001 6단계), 제품 동작(CLI·JSON·state 형식)의 변경.

의존: 선행 REPO-001·TMUX-001(done). 병렬 INSTALL-002, RELEASE-001(위 interface). 후행 INSTALL-004·005, RELEASE-002·003.

위험 등급: 높음. 이 설치기는 다른 직원의 HOME에 쓰고, 틀리면 사용자 파일을 바꾸거나 지울 수 있습니다. 계약 8절 인수 test가 주된 방어입니다. 인수 전에 Leader가 설치기의 쓰기·삭제 경로를 독립 검토(sub-agent)로 한 번 확인합니다.

## Verification
1. 8절 T1~T23이 자동 test로 모두 통과합니다. 각 경우의 기대 변경 목록은 계약 문서에서 얻고 설치 기록에서 얻지 않습니다(8절 머리말). T19는 fake provider CLI로 실행합니다.
2. 추가 자동 test:
   - release에 `tools/python.env`가 위 형식으로 생기고, 값이 설치 interpreter와 package 경로입니다.
   - `VERSION`이 없는 원본에서 `install`이 거절되고 snapshot이 같습니다.
   - 작업 트리가 깨끗하지 않을 때의 동작이 계약에 적은 대로입니다.
3. 실제 HOME 불변: test 실행 전후로 실제 HOME의 2절 경로(`~/.local/lib/project-agent`, `~/.local/bin`의 세 이름, skill link, `~/.config/project-agent`)와 `~/.tmux.conf`의 상태가 같음을 Result에 기록합니다.
4. 영향 회귀: README의 기존 네 명령이 통과합니다. 알려진 timing test 2개(TEST-001, TEST-002)는 단독 실행으로 통과를 확인합니다.
5. 고친 계약 절과 문서의 Markdown 상대 link가 실제 파일을 가리킵니다.

## Result
- 제출 commit: 1c45777f0ad54df18ecf2df4835fd1662f99dc23

구현 (`cr/INSTALL-001`, origin에 push, origin/main 477516b를 merge한 뒤):
- `install/project-agent-install`과 `install/project_agent_install/`(표준 library만): `install`·`upgrade`·`rollback`·`uninstall`·`check`, 공통 `--dry-run`, `--json`, `--source`. 각 명령은 계획(Step 목록)을 만들고 `--dry-run`은 그 계획을 출력하며 실제 실행은 같은 계획을 적용합니다. 실패하면 적용한 Step을 되돌립니다(종료 코드 4). 거절은 3, `check` 실패는 1.
- release: Git commit에서 만들고(`<VERSION 첫 줄>-<HEAD 12자>`), release 파일이 commit과 다르면 거절합니다. `tools/python.env`(두 이름, `PROJECT_AGENT_PYTHONPATH` 빈 값)를 씁니다. 외부 package는 넣지 않습니다. 계약에 없던 결정 하나: 실행이 release에 `__pycache__`를 더하면 불변이 깨지므로(T19에서 확인), 만들 때 설치 interpreter로 미리 compile하고 쓰기 권한을 뺍니다. uninstall·되돌림은 권한을 풀고 지웁니다.
- `install/project_agent_install/runs.py`: `run_slots`(liveness, suspend.json)·`release_of_run`·`releases_in_use`. INSTALL-004가 형식 버전 판정에 다시 쓸 한 곳입니다.
- 계약 고침(`docs/project-team/install-contract.md`): 2절 release 내용·shim 형태(절대 경로 symlink), 3절 표시 줄 확정, 6.1절 `python.env`, 7절 명령 공통(종료 코드, release 이름·dirty tree 규칙, textual 안내, uninstall의 등록 파일 없음·state 없음 처리, `current` 변경 시 거절), 8절 test 위치. README(검증 명령, 디렉터리 지도)와 제품 지도에 설치기를 더했습니다.
- 인수 test `install/tests`(`python -m pytest -q -n 8 install/tests`): T1~T23 전부, 추가 경우(VERSION 없음·형식 오류, dirty tree, python.env, 부모 symlink, release 읽기 전용, check 실패 경우 등). 격리 HOME + snapshot diff(기대 목록은 계약에서 직접 씀, 설치 기록에서 얻지 않음) + 격리 tmux(`-S` socket). T7·T10·T19는 설치된 실제 `agent-session`을 쓰고 provider만 fake CLI(agent-session test fixture를 이 test 환경의 `sitecustomize`로 주입)입니다. 한계: T19의 fake provider는 provider별 신뢰 기록(5.1의 `~/.claude.json`, `~/.codex/config.toml` 쓰기)을 하지 않으므로 그 두 쓰기는 이 test가 보지 못합니다.

검증 (제출 commit 31e7412):
1. `python -m pytest -q -n 8 install/tests`: 103 passed, 1 skipped(T11의 "LIB에 link 형태 없음" 조합). 이전 merge 직후 commit에서도 102 passed + T7 순서 의존 1건을 고쳐 3회 통과를 확인했습니다.
2. 추가 test: release의 `tools/python.env` 형식·값, `VERSION` 없음 거절(snapshot 같음), dirty tree 거절(변경·추적 안 된 release 파일, 제외 경로 변경은 통과)이 계약대로 통과합니다.
3. 실제 HOME(`/primehome/swain`) 불변: 이 작업 중 설치기를 실제 HOME에 실행하지 않았습니다. 마지막에 확인: `~/.local/lib/project-agent`와 `~/.config/project-agent` 없음, `~/.local/bin/{agent-session,project-item,project-board}`는 옛 개발 checkout symlink(2026-11-05) 그대로, `~/.claude/skills`·`~/.codex/skills`는 옛 symlink(2026-11-05) 그대로, `~/.tmux.conf`는 옛 symlink(2026-11-05) 그대로.
4. 영향 회귀(merge 후 같은 commit): agent-session 704 passed(`AGENT_SESSION_TEST_TIMEOUT=60`), project-item 120 passed, project-board 113 passed + 1 failed, integrations/tmux·launcher·boundary·private_root·release_files 55 passed(merge 직후 commit). project-board의 실패 `test_many_projects_scroll_and_ipc_fold_the_clicked_project`는 load average 100 근처에서 났고 단독 2회 통과했습니다(이 CR은 project-board를 바꾸지 않았습니다). 앞선 같은 조건의 첫 실행에서 TEST-001 계열 3건과 TEST-002 대상이 시간 초과로 실패했으나, 단독 실행(TEST-001은 timeout 60)에서 통과했습니다.
5. 고친 문서(`README.md`, `docs/project-team/README.md`, `docs/project-team/install-contract.md`)의 Markdown 상대 link가 모두 실제 파일을 가리킵니다(스크립트로 확인).

사건 하나(알림): 개발 중 설치 후의 `agent-session start`를 시험하다가 `--socket-path`를 주지 않아 사용자의 실제 기본 tmux server에 시험용 session `fx`(window 1개, 시험용 fake CLI)가 생겼습니다. 제가 만든 것임을 session의 owner option으로 확인하고 그 session만 kill했습니다. 다른 session은 건드리지 않았습니다. 이후 test 하네스는 모든 명령에 private socket을 명시하고 `TMUX_TMPDIR`도 격리해 실제 server에 닿을 수 없게 했습니다.

인수 전 Leader 독립 검토에서 볼 곳: `actions.py`(쓰기·삭제 Step과 되돌림), `commands.py`의 `plan_uninstall`(지우는 대상 결정과 빈 디렉터리 계산), `tmuxconf.py`·`actions.remove_block`(tmux 파일 byte 보장).

### 수정 제출 (Leader 검토 31e7412 피드백 반영)
수정 제출 commit 3462c8a (origin/main 477516b 이후의 main을 merge한 7b16b92 포함). 각 항목은 수정 전 설치기(31e7412)로 새 test를 먼저 돌려 실패를 확인했습니다(`PROJECT_AGENT_INSTALLER`로 옛 설치기를 가리킴: CLI 수준 44건 중 43건 실패. 통과한 1건은 6번 test로, 그 test는 checkout 자신의 설치기를 쓰므로 옛 설치기와 비교하지 못했습니다).

1. 설치 기록 신뢰: `paths.validate_record`가 `record.read()`에서 모든 항목을 대조합니다(dir은 `releases/<name>`·`backup/`, file은 `tmux.conf`·`install.json`, symlink는 `current`·shim·skill link 자리와 계산한 target, `..` 금지, `created_dirs`는 설치기 경로의 조상만이고 HOME 이상은 금지, `tmux.file`은 후보 중 하나, backup은 `backup/` 바로 아래). 어긋나면 `record_invalid`로 거절. test 10가지 변형 × uninstall·upgrade·rollback·check·install → 거절과 snapshot 같음.
2. tmux 블록 제거: 열린 fd에서 bytes를 계획 때와 대조(다르면 `Changed`로 거절, 첫 변경 전이면 journal도 지움), 블록이 끝이면 `ftruncate` 한 번, 아니면 pwrite loop 뒤 `ftruncate`, 실패하면 바꾸기 전 bytes와 시각 복원. 짧은 write·write 실패·ftruncate 실패·계획 뒤 변경 test.
3. tmux 블록 추가: 되돌림 명세를 journal에 먼저 쓰고, 연 fd에서 bytes를 대조하며, write는 loop, backup은 실행 시점 bytes가 계획과 같을 때만 만듭니다. 짧은 write·실패 주입·계획 뒤 변경 test(T2의 세 원본, backup byte 일치).
4. 삭제 오류: `force_rmtree`는 오류를 모아 `OSError`로 올리고 symlink는 거절합니다. uninstall은 tmux 블록 → 소유 항목 → (journal을 담지 않는) 만든 디렉터리 → 설치 기록 → journal → (journal을 담은) 디렉터리 순입니다. 삭제 실패는 종료 코드 4와 "Nothing was undone" 안내이며 기록이 남고 다시 실행하면 끝납니다(`.local/bin`·`releases`를 읽기 전용으로 만든 test).
5. 중단: 첫 변경 전에 journal(`.project-agent-install-journal.json`)을 씁니다(lib 또는 lib 조상 중 실행 전에 있는 가장 가까운 디렉터리). 실패·SIGINT·SIGTERM·SIGHUP은 즉시 되돌리고, SIGKILL 뒤 다음 명령(`check` 제외)이 먼저 되돌림을 끝낸 뒤 자기 일을 합니다. uninstall은 되돌리지 않고 다음 `uninstall`만 마무리하며 다른 명령은 거절합니다. `--dry-run`은 journal이 있으면 거절합니다. journal의 경로도 `paths.check_spec`으로 대조합니다. test: install 13개·upgrade 4개·uninstall 8개 step 경계에서 SIGKILL(`INSTALLER_STOP` 훅과 `actions.checkpoint`), SIGTERM·SIGINT·SIGHUP. 계약 2절 규칙 5와 7절에 적었습니다. `_write_atomic`의 임시 파일은 실패 때 지웁니다.
6. 설치기와 그것이 import하는 제품 코드는 bytecode를 쓰지 않습니다(`sys.dont_write_bytecode`).
7. origin/main을 merge했습니다. `python.env`의 위치·형식은 6.1절 한 곳(INSTALL-002의 서술)으로 합치고, 설치기가 쓰는 값(설치기를 실행한 interpreter, 빈 PYTHONPATH)만 그 문단에 한 문장으로 더했습니다. 중복 서술은 지웠습니다.

수정 제출의 검증 (commit 3462c8a): `python -m pytest -q -n 8 install/tests` 160 passed, 1 skipped. merge 직후 commit에서 `integrations/tmux`·launcher·boundary·private_root·release_files 70 passed. 설치기 밖의 코드는 바꾸지 않아 agent-session·project-item·project-board suite는 다시 돌리지 않았습니다(첫 제출의 회귀 결과가 유효). 실제 HOME에는 이 작업에서도 설치기를 실행하지 않았습니다(test는 모두 격리 HOME). 문서 relative link 3개 파일 확인.

### 2차 수정 제출 (Leader 검토 3462c8a 피드백: 원칙 A·B·C)
수정 제출 commit 9943b6d. 원칙을 계약 2절 규칙 5와 3절 표(hard link·1 MiB 초과 파일)에 먼저 적고, 원칙마다 수정 전 설치기(3462c8a)로 실패하는 test를 먼저 만들었습니다(`PROJECT_AGENT_INSTALLER`로 옛 설치기 지정, `install/tests/test_principles.py`: 21건 중 13건 실패, 통과한 8건은 새 형식 journal 변형 5건(옛 설치기도 형식 불일치로 거절)과 회귀 보호 3건).

- **A. 경로의 출처는 설치기 하나**: `paths.Places`가 닫힌 식별자(`current`, `shim:<도구>`, `skill:<provider>:<이름>`, `release:<이름>`, `tmux:<번호>`, `backup:<이름>` 등)에서 경로를 계산합니다. journal(format 2)은 operation·식별자·지문만 담고 경로 key가 있으면 거절합니다(`drop_journal`·`rmtree`의 `temp`·`relink`의 `previous` 경로 문제가 구조적으로 사라짐). 설치 기록의 경로는 계산한 값과 정확히 같을 때만 받습니다(기록에 `provider_homes`를 두어 skill link 자리를 provider 홈 아래 `skills/<이름>`으로 좁힘). 임시 파일은 대상에서 정해진 이름(`.<이름>.pi-tmp`, `releases/.tmp-<이름>`, journal의 `.json.tmp`)이라 다음 실행이 지웁니다. test: 조작한 journal 8변형으로 uninstall·install·upgrade·rollback이 모두 거절·snapshot 불변, 임시 파일 생성 직후마다 SIGKILL(install 9곳·upgrade 4곳·uninstall) → 다음 명령 뒤 남는 것 없음, 이어서 성공.
- **B. 만든 그 상태일 때만**: 되돌림·제거는 파일 hash, link 대상, 빈 디렉터리, release 파일 목록 지문이 일치할 때만 지우고 다르면 알림(notes)만 합니다. 새 파일은 임시 파일을 다 쓴 뒤 `link`로 이름을 얻어 기존 이름을 덮어쓰지 않습니다. test: 계획 뒤(실패)·kill 뒤 사용자가 만든 `~/.config/project-agent/project.json`·`~/.tmux.conf`가 그대로.
- **C. tmux 파일은 전 또는 후 bytes**: 제자리 쓰기를 없애고 같은 디렉터리의 임시 파일에 쓰고 fsync → inode·크기·시각 재확인 → rename → 디렉터리 fsync, 권한 유지. journal에 바꾸기 전 bytes와 전·후 hash를 두고 복구는 "후"일 때만 되돌리고 "전"이면 아무것도 안 하며 둘 다 아니면(사용자 편집) 건드리지 않고 알립니다(`_untruncate`의 prefix 판정 삭제). resume의 `Changed`는 traceback이 아니라 알림이며 uninstall은 계속 진행합니다. test: 쓰기 실패·짧은 write 주입, kill 뒤 사용자 편집(빈 줄 포함)·hard link 파일(안내만)·권한 유지.
- 그 밖에: journal 쓰기·디렉터리 fsync 실패는 journal을 지우고 `journal_unwritable`로 알립니다(test).

검증 (commit 9943b6d): `python -m pytest -q -n 8 install/tests` 184 passed, 1 skipped(마지막 제출 commit에서 한 번). 설치기 밖 코드는 바꾸지 않아 다른 suite는 이전 근거를 재사용합니다. 정리: 검증이 끝난 뒤 내 test process·private tmux server·임시 디렉터리·scratchpad를 점검하고 지웠습니다.

### 3차 수정 제출 (Leader 검토 9943b6d 피드백)
수정 제출 commit 1c45777 (origin/main merge 포함, README의 두 검증 안내를 모두 살림). 범위는 지적한 5개 항목뿐입니다. 새 test는 수정 전 설치기(9943b6d)로 먼저 실행해 실패를 확인했습니다(8건 중 7건 실패, 통과 1건은 backup mode 0644 변형으로 옛 동작이 우연히 같음, xattr test는 이 file system이 user xattr를 지원하지 않아 skip).

1. 원칙 B 마무리: 설치 기록의 release 항목에 `digest`(파일과 그 위 디렉터리의 이름 목록 지문, `__pycache__` 디렉터리와 그 안의 `.pyc`만 제외)를 두고 `rm_tree`가 같을 때만 지웁니다. release는 먼저 예약 임시 이름으로 rename한 뒤 지워서, 도중에 끊겨도 다음 실행이 마저 지우고 digest가 어긋난 release가 남지 않습니다. `backup/`은 기록한 backup 파일(`backup_sha256`)만 지우고 비었을 때만 `rmdir`합니다. 다르면 남기고 알립니다. test: release 루트·`__pycache__`·`backup/`에 사용자 파일을 넣고 uninstall → 그 파일과 디렉터리가 남고 알림.
2. 원칙 C 마무리: `tmuxconf.rewrite_problem`이 hard link 여럿, 소유자 다름, 읽기 전용, ACL·확장 속성, 1 MiB 초과를 판정하고 계획과 실행(append·cut·복구) 모두에서 쓰입니다. 해당 파일은 고치지 않고 넣을 줄만 안내하며 `check`는 "수동 연결 필요"입니다. backup 파일은 원본과 같은 mode입니다. 계약 3절 표와 본문에 적었습니다. test: 읽기 전용·backup mode 0600/0640(xattr·소유자는 단위 test).
3. 복구가 막히지 않게: journal의 `previous`(record op)·`before_bytes`(tmux op)를 base64로 검증하고(`journal_invalid`), `recover`는 `ValueError`·`KeyError`도 실패로 모으며 `resume`은 `OSError` 등을 traceback 대신 `command_failed`(종료 코드 4, journal 유지)로 끝냅니다. test: 손상된 base64 journal 2종 × uninstall·install·rollback → 정해진 오류·snapshot 불변·traceback 없음, resume 중 `IsADirectoryError`.
4. 계약 2절 규칙 5: provider 홈이 설치 기록·journal에서 값을 받는 유일한 예외이며 그 아래에서는 link 대상이 계산한 `current/skills/<이름>`과 같을 때만, 디렉터리는 비었을 때만 지우므로 안전하다는 것, 고정 임시 이름(`.<이름>.pi-tmp`, `releases/.tmp-<이름>`, journal의 `.json.tmp`)은 설치기가 예약한 이름이라는 것을 적었습니다.
5. `origin/main`을 merge했습니다(README 충돌은 두 쪽을 모두 살려 해소).

검증 (commit 1c45777): `python -m pytest -q -n 8 install/tests` 194 passed, 2 skipped(root가 아닌 환경에서 막히지 않는 xattr 미지원 1건, T11의 link 형태 없는 조합 1건)을 merge한 마지막 commit에서 실행했습니다. 다른 suite는 이전 근거를 재사용합니다(설치기 밖 코드 변경 없음). 정리: 검증 뒤 내 test process·private tmux server·임시 디렉터리·scratchpad를 점검하고 지웠습니다.
