# ITEM-001: project-item new가 번호를 정할 때 전체 git 이력을 매번 읽어 NFS 부하에서 몇 분 걸립니다

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S2

## Symptom
`project-item new cr`가 host 부하에서 몇 분 걸립니다. 그동안 그 CR root의 잠금을 잡고 있어서 같은 root의 다른 `new`·`move`·`accept`도 기다립니다.

- 2026-11-12 01:44 KST, 이 저장소(base)에서 `project-item new cr --area BOARD ...`(BOARD-027): 3분 33초, CPU 1.2초.
- 2026-11-11에도 같은 일이 있었습니다(Leader 인계: "부하에서 몇 분 걸리는 일이 있었습니다(CPU 0%, 원인 미조사)").

## Evidence
- 번호를 정하는 `tools/project-item/project_item/store.py`의 `new_cr`은 root 잠금 안에서 `history_high`를 부르고, `history_high`는 `git log --all --name-only --format= -z --relative -- .`로 모든 ref의 전체 이력을 읽습니다. 번호를 재사용하지 않는 계약([CR 계약](../../../skills/project-item/references/cr.md) "번호는 AREA마다 3자리이고 그 저장소 안에서 재사용하지 않습니다", 지운 파일 포함) 때문입니다.
- 같은 명령만 따로 재면(2026-11-12 01:58, load 73~89, `docs/cr`에서) **3분 49초, CPU 0.98초**였습니다. 실행 중인 `git log`는 상태 `D`(I/O 대기), CPU 0이었습니다.
- base 저장소에는 loose object가 3,866개(22.6 MiB), pack 안 객체가 2,395개였습니다. 이력은 676 commit, ref 83개입니다. `git rev-list --all --count`(commit만 읽음)도 32초였습니다. 저장소는 NFS(`/primehome/swain`, nfs4)에 있습니다.
- 원인 확인: Leader가 base에서 `git repack -d`(8분 46초, 도달 가능한 객체만 pack에 넣음)로 loose object를 229개로 줄인 뒤 같은 명령을 다시 쟀습니다. **3.9초**였습니다(02:12, load 83~89, 출력 바이트 같음). 시간 대부분은 `--name-only`가 commit마다 읽는 tree·commit 객체를 loose 파일로 하나씩 NFS에서 여는 비용입니다.
- 다시 생깁니다: base에서 commit·fetch할 때마다 loose object가 쌓이고(`gc.auto` 기본 6,700에 닿기 전까지 묶지 않음), `new`는 매번 전체 이력을 처음부터 읽습니다. repack은 지금의 증상만 없앴습니다.

## Contract
1. `project-item new cr`의 번호 결정은 이력 전체 길이와 무관하게, 마지막 번호 결정 뒤 새로 생긴 commit만큼만 git 객체를 읽습니다. 같은 root에서 연이어 부르면 git 이력 읽기가 거의 없습니다.
2. 번호 규칙은 그대로입니다: 모든 ref의 이력에서 지운 파일을 포함해 쓰인 적 있는 번호를 다시 쓰지 않습니다. 원본은 git 이력이고, 저장하는 값은 그 이력에서 계산한 결과를 commit ID와 함께 기억하는 cache뿐입니다.
3. cache가 없거나, 깨졌거나, 기억한 commit을 더 읽을 수 없으면(gc·강제 push) 지금처럼 전체를 읽습니다. 어느 경우에도 틀린(이미 쓴) 번호를 내지 않습니다.
4. 잠금 안에서 하는 일이 줄어서 같은 root의 `move`·`accept`가 `new` 때문에 수 분 기다리지 않습니다.
5. `new decide`·`move`·출력 형식은 바뀌지 않습니다.

## Disposition
- 2026-11-12 Leader: 구현한다. Leader 판정: 재현과 근거가 있는 운영 결함입니다(Symptom·Evidence의 측정). repack은 증상만 없앤 운영 조치이고, 재발하지 않게 하려면 번호 결정이 이력 전체를 매번 읽지 않아야 합니다. 번호 재사용 금지 계약은 바꾸지 않습니다.
- 2026-11-12 Leader: open -> todo. Leader 판정: 재현·근거가 있는 운영 결함

## Implementation
읽을 문서: `tools/project-item/project_item/store.py`(`root_lock`, `history_high`, `new_cr`), `tools/project-item/project_item/cr.py`의 `next_id`, `tools/project-item/README.md`, [CR 계약](../../../skills/project-item/references/cr.md)의 파일명·번호 규칙, `tools/project-item/tests`(번호 발급 test, `conftest.py`의 격리 HOME), [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. 번호 결정에 증분 cache를 둡니다. root마다 "이미 읽은 commit(ref 끝)과 그때까지 AREA별 최고 번호"를 기억하고, 다음 호출은 그 commit에서 닿지 않는 새 commit만 읽어(`git log --all --not <기억한 commit>` 등) 기억한 값과 합칩니다. 위치는 잠금과 같은 `~/.cache/project-item/` 아래, 쓰기는 root 잠금 안에서 원자적으로(임시 파일 후 rename) 합니다.
2. cache가 없음·깨짐·형식 다름·기억한 commit이 저장소에 없음이면 전체를 읽고 cache를 새로 씁니다. git 밖 root는 지금처럼 0입니다.
3. Test(실패 경로마다 하나): 지운 파일의 번호를 다시 쓰지 않음(cache 있음·없음), 다른 branch에만 있는 번호를 다시 쓰지 않음, cache 뒤 새 commit의 번호를 반영함, cache 깨짐·형식 다름에서 전체 읽기, 기억한 commit이 없어진 경우(강제 push 뒤 gc를 흉내), 두 번째 호출이 기억한 commit 이전을 읽지 않음(git에 넘긴 인자나 GIT_TRACE2 등 관찰 가능한 방법), 두 process가 동시에 `new`해도 번호가 겹치지 않음(기존 test가 있으면 유지).
4. README(project-item)에 cache의 위치·의미·지워도 되는 이유를 적습니다.

의존: 없음. 위험 등급: 중간(번호 발급 규칙).

## Verification
1. README 검증 표의 `tools/project-item/**` 행: `python -m pytest -q tools/project-item/tests`, `python -m pytest -q tools/agent-session/tests/test_api_boundary.py`. `project_item/api.py`나 CR·결정 형식(`cr.py`, `decide.py`, `kinds.py`)을 바꾸면 그 행의 나머지(`python -m pytest -q -n 8 tools/agent-session/tests`, `python -m pytest -q tools/project-board/tests`, 네 번째 명령)도 실행합니다.
2. 문서를 바꾸면 해당 행: 고친 문서의 상대 link 검사, `tools/test_distribution_boundary.py`. `skills/project-item`의 형식 문서를 바꾸면 `tools/project-item/tests/test_doc_contract.py`, `skills/**`를 바꾸면 `tools/agent-session/tests/test_remote.py`도.
3. 측정(대상 시나리오만, test와 병렬): 이 저장소를 임시 위치(NFS, `/primehome/swain/tmp/item001/`)에 clone하고 objects를 loose로 푼 상태(`git unpack-objects`)에서, 기준(`origin/main`)과 이 CR의 `project-item new cr`을 번갈아 3회 잽니다. 이 CR은 첫 호출(cache 없음)과 두 번째 호출(cache 있음)을 따로 적습니다. wall·CPU와 그때의 load를 Result에 적습니다.
