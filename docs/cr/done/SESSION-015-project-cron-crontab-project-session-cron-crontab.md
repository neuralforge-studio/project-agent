# SESSION-015: project별 cron을 crontab의 project 구역으로 관리하고, 자기 점검을 session cron에서 crontab으로 옮깁니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S2
- Base: 82fe650528592b9262d08ce94e540fcf5224eb46 2026-11-11T19:46:19+09:00
- Outcome: fixed

## Symptom
지금 project-agent의 cron은 Leader·Worker 자기 점검 하나뿐이고, 각 Claude session 안의 session cron입니다. 그래서 다음 문제가 있습니다.
- 밖에서 볼 수도 관리할 수도 없습니다.
- 7일 뒤 만료되고, session이 끝나면 사라집니다.
- 할 일이 없어도 Leader 화면에 30분마다 두 줄이 남습니다(TEAM-002의 한계).

사용자 요청과 결정(D-20261111-04, decided C):
- 요청: "Cron에 대해서 표시할 방법에 대해서 제안해줘. project 별로 cron 관리하게. crontab을 이용하는건가? crontab은 모든 내용을 한번에 나오겠지만, 그럼에도 불구하고 project 단위로 관리가 될 수 있게."
- 답: "3. C, side bar에도 추가해줘. …"
- 이어서 sidebar 표시는 "그냥 cron이 몇개 있는지만 보이는게 더 깔끔할까? D:?  C:?"로 바뀌었습니다. 표시는 BOARD 쪽 CR이 맡습니다.

## Evidence
- 자기 점검의 원본: [self-check.md](../../../skills/project-team/references/self-check.md). 등록 지시: `launch_artifacts.self_check_text`. 계약: [동작 명세 watch](../../project-team/spec.md#watch). TEAM-002 gate: `agent_session/self_check_gate.py`, `providers/claude.py`의 Leader `UserPromptSubmit` hook.
- `agent-session watch --project X`는 정체한 Worker·Leader를 대화 기록으로 판정해 메시지를 보냅니다. 반복은 명령이 하지 않습니다.
- SESSION-006 결정("instance적으로", 중앙 process·system crontab 없음)은 D-20261111-04로 바뀌었습니다.
- 사용자 crontab에는 project-agent와 무관한 사용자 줄(falcon2 작업 세 줄)이 있습니다.

## Contract
1. **crontab의 project 구역**: project마다 사용자 crontab에 표시한 구역이 하나 있습니다(예: `# >>> project-agent: <project> >>>` … `# <<< project-agent: <project> <<<`).
   - `agent-session cron ls|add|rm --project X`(JSON 결과)는 그 project의 구역만 고칩니다.
   - 구역 밖의 줄(사용자 작업)은 바이트 그대로 둡니다. 동시에 고쳐도 잃는 줄이 없습니다.
   - crontab을 읽지 못하면 아무것도 쓰지 않고 실패합니다.
   - 작업마다 id, 일정(5칸 cron 식), 설명, 명령을 가집니다.
   - crontab이 원본입니다. 같은 사실을 다른 파일에 따로 두지 않습니다.
2. **기본 점검 작업**: project의 점검 작업은 30분마다(`:00`·`:30`을 피한 분) 그 project의 점검 명령을 실행합니다.
   - 점검 명령은 지금 Leader 자기 점검 prompt가 모델에게 시키는 판정을 코드로 합니다: 정체한 Worker·Leader(지금 watch), review 대기 CR(제출 행 hash가 Disposition에 없음), 반납 대기 seat, 빈 seat와 배정 가능한 todo CR, 답을 받고 반영하지 않은 결정, window나 CLI가 사라진 Worker.
   - 조치할 것이 있을 때만 Leader에게 한 번 알립니다. 같은 상태는 반복해서 보내지 않습니다(watch의 반복 방지와 같은 방식).
   - Worker 쪽 점검(제출 뒤 Leader 회신을 30분 넘게 기다림, 진전 없는 대기)도 이 명령이 판정해 해당 Worker에게 보냅니다.
   - 할 일이 없으면 아무에게도 아무것도 보내지 않습니다.
3. **잊지 않는 등록**: Leader를 시작할 때(start·restart·resume) 그 project의 점검 작업이 없으면 만듭니다(idempotent). 사람이 따로 기억할 등록 단계가 없습니다.
4. **session cron 자기 점검 제거**: 첫 prompt와 resume 메시지는 `CronCreate`를 지시하지 않습니다. self-check.md와 명세를 새 방식으로 바꿉니다. TEAM-002의 `UserPromptSubmit` gate는 쓸 일이 없어지므로 지웁니다.
5. **Board가 읽을 값**: project별 작업 목록(id, 일정, 설명, 다음 실행 시각, 마지막 실행 시각과 결과)을 `cron ls --project X --json`으로 제공합니다. sidebar가 2초 주기 안에서 싸게 읽을 수 있는 형태(작업 개수와 가장 가까운 다음 실행)도 제공합니다. 다음 실행 시각 계산 규칙은 한 곳이 소유하고, 다른 언어(Rust sidebar)가 같은 결과를 내는지는 일치 test로 지킵니다. 마지막 실행 결과는 점검 명령이 project의 run 기록 위치에 남깁니다.

## Disposition
- 2026-11-11 Leader: 구현한다. 사용자 결정 D-20261111-04, decided C. 사용자 원문은 Symptom에 있습니다. 방향(crontab project 구역, 점검을 코드로 옮김, 조치할 때만 알림, Leader 시작 때 점검 작업 보장)은 Leader 판정입니다. Board 표시(sidebar의 `C:n`과 cron 창)는 BOARD 쪽 CR이 따로 맡습니다.
- 2026-11-11 Leader: open -> todo. 사용자 결정 D-20261111-04 decided C
- 2026-11-11 Leader: 제출 17148a2를 검토했습니다. 구현과 검증은 인수 가능합니다. 수정 요청은 하나입니다. 제출 뒤 통합된 TEST-013(58efb42, agent-session fixture·test_suspend·install harness의 한도)을 merge하고, merge commit에서 agent-session tests와 install/tests를 다시 실행합니다.
- 2026-11-12 Leader: 제출 92563fbecb69d7131749b14086f8674f43944141를 인수합니다. 재검토 92563fb(앞 검토 17148a2 + main 8947a2f 이전의 TEST-013 merge, 충돌 없음, 코드 변경 없음). merge commit에서 agent-session 921 passed, install/tests 283 passed. 나머지 묶음은 merge가 입력을 바꾸지 않아 앞 근거(project-item 125, project-board 229, 네 번째 명령 136)를 재사용합니다.
- 2026-11-12 Leader: in-progress -> done, Outcome fixed. 통합 9a0a090 (origin/main)

## Implementation
읽을 문서:
- [동작 명세](../../project-team/spec.md)의 watch·start·resume·5절
- [self-check.md](../../../skills/project-team/references/self-check.md), [project-team skill](../../../skills/project-team/SKILL.md)
- `tools/agent-session/agent_session/`의 `watch.py`, `launch_artifacts.py`(`self_check_text`), `providers/claude.py`, `self_check_gate.py`, `jobs.py`, `cli.py`
- [설치 계약](../../project-team/install-contract.md) 5절(실행 중 쓰기 목록: crontab을 더함)
- TEAM-002·SESSION-006 CR

1. `agent-session cron` 하위 명령과 crontab 구역 관리. 잠금, 원자적 교체(`crontab -`), 구역 밖 보존, 읽기 실패 처리를 구현합니다.
2. 점검 명령: watch를 넓히거나 새 하위 명령으로 Contract 2의 판정을 코드로 합니다. 판정의 원본은 project-item(상태, 제출 행, Disposition)과 state.json입니다.
3. Leader 시작 때 점검 작업을 보장합니다.
4. session cron 자기 점검을 지웁니다. 대상은 prompt·resume 메시지, self-check.md, spec, TEAM-002 gate와 hook입니다. 떠 있는 session의 cron은 각 session이 끝날 때 사라집니다. 옮기는 동안 두 방식이 같이 돌지 않게 하는 방법을 Result에 적습니다.
5. Contract 5의 Board용 값과 다음 실행 시각 규칙(5칸 cron 식)을 만들고 문서화합니다.
6. Test: 구역 관리(다른 줄 보존, 동시 수정, 읽기 실패), 점검 판정 경우별(조치 있음·없음, 반복 방지), Leader 시작 때 보장, prompt에 CronCreate 지시 없음, 다음 실행 계산. 실제 crontab을 쓰는 test는 격리 환경에서 하고 사용자 crontab은 건드리지 않습니다. 예: `crontab` 명령을 바꿔 끼운 shim.

의존: 없음. BOARD-018(Rust sidebar)이 진행 중입니다. Board 표시 CR은 이 CR이 Contract 5를 정한 뒤 시작합니다.

위험 등급: 높음. Leader 감시 방식을 바꿉니다. 판정이 불확실하면 Leader에게 알리는 쪽으로 틀리게 합니다.

## Verification
1. README 검증 표에서 바꾼 경로의 행 명령 전부를 실행합니다. 대상은 `tools/agent-session/**`(api·state를 바꾸면 그 행의 추가 명령), `skills/**`·`docs/**`, `install/**`(바꾸면)입니다.
2. 실제 이 workstation에서 `agent-session cron add/ls/rm`을 test project 이름으로 한 번 실행합니다. 사용자 줄이 그대로인지 `crontab -l` 전후 비교로 확인하고, 시험 구역은 지웁니다.

## Result
- 제출 commit: 17148a2d4e5aef4cbbd433d94bd66f713efe5452

`cr/SESSION-015`에 push했습니다(구현 commit 01ebff5 + `origin/main`(5fe6458, CR 파일 이동뿐) merge. merge는 검증 입력을 바꾸지 않아 검증을 다시 하지 않았습니다).

**구현**
- `agent_session/cron.py`: project 구역(`# >>> project-agent: NAME >>>`…) 읽기·쓰기. `~/.cache/agent-session/crontab.lock`, 쓰기 직전 재읽기(다른 편집이 있으면 재시도), `crontab -`로 교체, 구역 밖 바이트 보존, 읽기 실패·구역 손상이면 아무것도 쓰지 않음. `Schedule.next_run`이 다음 실행 계산의 유일한 원본(숫자·`*`·목록·범위·간격, 이름·`@` 줄임은 거절). `Cron` 명령은 `Watch`의 호출자 판정(operator·그 project의 Leader)을 씁니다.
- `agent-session cron ls|add|rm --project X`, `ls --summary`(작업 수와 가장 가까운 다음 실행). 모든 명령이 기존과 같은 JSON 봉투를 냅니다(`--json` 옵션은 따로 두지 않았습니다).
- `agent-session check --project X`와 `agent_session/check.py`: Worker는 `watch`와 같고, Leader는 처리할 일(review 대기 CR, 반납 대기 seat, 빈 seat+todo CR, 답을 받은 결정, window·CLI가 사라진 Worker)을 코드로 판정합니다. 일이 있고 Leader 기록이 30분 넘게 정지했을 때만 한 번 알리고(`resting.nudged_at`으로 반복 방지), 판정하지 못한 묶음은 처리할 일로 적어 알리는 쪽으로 틀립니다. 실행 결과는 `<base>/agent/cron/check.json`(`at, ok, result`)에 남고 `cron ls`의 `last_run`입니다.
- 기본 작업 `check`: `13,43 * * * *`, 명령은 이 release의 `bin/agent-session --config … check --project X >/dev/null 2>&1`(cron 메일 방지). Leader의 새 run(start·restart·resume이 모두 지나는 `_launch`)에서 보장합니다. 있으면 일정·설명은 두고 명령만 이 release로 맞춥니다. 시작 결과에 `cron: {check: added|present|updated|failed}`가 더해지고, crontab 오류는 Leader 시작을 막지 않습니다.
- session cron 자기 점검 제거: `launch_artifacts.self_check_text`, prompt·resume 메시지의 등록 지시, `self_check_gate.py`와 Leader `UserPromptSubmit` hook(`providers/claude.py`), 그 test를 지웠습니다. `self-check.md`는 점검 메시지를 받았을 때의 할 일로 다시 썼고(이름·원격 guidance 목록 유지), 명세 7절에 `check`·`cron`을 더하고 watch·start·resume·session cron 서술을 맞췄습니다. 제품 지도·설치 계약 5절(crontab lock, `agent/cron/*.json`, 사용자 crontab)·agent-session README·SKILL.md도 맞췄습니다.
- 다음 실행 일치 test용 사례: `tools/agent-session/tests/fixtures/cron_next_run.json`(손으로 쓴 16개 + 거절 15개, local 분). **Board CR(Rust)이 이 파일로 일치 test를 만들면 됩니다.** sidebar는 `cron ls --project X --summary`를 부르거나 `crontab -l`의 구역 형식(명세 7절 cron)을 직접 읽을 수 있습니다.
- `review_waiting` 규칙을 `project_item.cr`로 옮기고 `project_item.api`로 공개했습니다(Board의 `review_wait`는 in-progress 조건만 더해 이 함수를 씁니다. 판정 원본이 Board와 `check`에 둘이 되지 않게). 옮기며 기존 결함 하나를 고쳤습니다: hash 인용 판정이 `\b`를 써서 `project-item accept`가 쓰는 "제출 <hash>를 인수합니다."처럼 hash 바로 뒤에 한글 조사가 오면 인용으로 보지 않았습니다(Board는 인수한 CR도 review 대기로 표시). hex 문자 경계로 바꾸고 Board test에 그 문구를 더했습니다.

**검증**(제출 commit과 같은 트리에서 실행. 실행 뒤 `origin/main`과의 merge는 CR 파일 이동만)
- `python -m pytest -q -n 8 tools/agent-session/tests`: 920 passed, 1 failed(`test_cli.py::test_help_lists_only_current_commands`가 새 명령 목록을 모름) → 기대 문자열 수정 뒤 해당 test 통과 확인.
- `python -m pytest -q tools/project-item/tests`: 125 passed. `tools/project-board/tests`: 229 passed(두 묶음은 같은 basename `test_cli.py` 때문에 따로 실행).
- `python -m pytest -q integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py`: 136 passed.
- `python -m pytest -q -n 8 install/tests`: 283 passed, 2 skipped. T19에 crontab lock 경로와 crontab 내용(project 구역 하나) 검사를 더했습니다.
- test는 실제 crontab을 쓰지 않습니다: `tools/tests/fake_crontab.py`(PATH의 `crontab` shell shim, 파일 하나)를 agent-session test 전체(autouse)와 install harness가 씁니다.
- Verification 2(실제 이 workstation): `agent-session cron add/ls/rm`을 project 이름 `zz-cron-verify`(임시 registry)로 실행. `crontab -l` 전후 비교에서 추가분은 그 구역 5줄뿐이었고, rm 뒤 `cmp`로 처음과 바이트 동일을 확인했습니다. 같은 registry에서 `env -i PATH=/usr/bin:/bin … check`(cron 환경 흉내)도 정상(`run: idle`, `check.json` 기록)이었습니다.
- 문서 link: `test_distribution_boundary`·`test_remote`(원격 guidance·skill link)·`test_import_cycle`(check·cron이 lifecycle을 import하지 않음)이 통과했습니다.

**두 방식이 같이 돌지 않게 하는 방법(옮기는 동안)**
- 이 commit 이후에 시작하는 run에는 session cron 등록 지시도 gate hook도 없습니다(settings는 run 시작 때 씁니다). 예전 방식으로 시작한 떠 있는 Claude session의 cron은 그 session이 끝날 때 사라지며(관리 CLI는 exit handoff를 꺼서 CLI와 함께 사라짐), 그동안 옛 Leader 점검이 `watch`를 부르더라도 `watch.lock`과 `resting.nudged_at`으로 한 정체에 한 번만 보내므로 `check`와 겹쳐도 메시지가 두 번 가지 않습니다. 옛 Leader run의 gate hook은 그 run을 시작한 release의 파일을 가리켜 계속 동작합니다. 이 workstation의 관리 run은 동결 사본이라 영향이 없습니다(AGENTS.md).
- 가장 확실한 전환은 각 project의 Leader를 restart하는 것입니다(새 run이 `check` 작업을 보장하고 session cron이 없습니다).

**알려 둘 점·후속 후보(범위 밖이라 구현하지 않음)**
- `uninstall`은 crontab을 고치지 않으므로(설치 계약 5.4절에 적음) 제거한 release를 가리키는 `check` 작업이 남습니다. 출력이 버려져 조용히 실패합니다. `agent-session cron rm`으로 지웁니다. 설치기가 지우게 할지는 별도 판단이 필요합니다.
- 명령의 경로는 Leader를 시작한 release의 `bin/agent-session`입니다. release를 올린 뒤 Leader를 restart하기 전에 그 release가 prune되면 작업이 실패합니다(`last_run.ok`가 false가 되지는 않고 파일이 갱신되지 않아 보입니다). 떠 있는 run이 그 release를 잡아 두므로 prune 대상이 아닙니다.
- 이 host는 부하가 커서(load 70~80) test 시간이 길었습니다(agent-session 전체 37분, install 64분). test 하나가 120초 한도에 가까운 일은 없었습니다.

### 수정 제출: TEST-013 통합 merge
- 제출 commit: 92563fbecb69d7131749b14086f8674f43944141

Leader 검토(17148a2)에서 요청한 대로 `origin/main`(TEST-013, 58efb42와 close daa09bc)을 `cr/SESSION-015`에 merge했습니다. 충돌은 없었고(겹친 파일은 자동 merge), 두 변경이 모두 남았습니다: TEST-013의 한도(`DEFAULT_TIMEOUT` 240초, `INSTALLER_TIMEOUT` 900, fixture 한도를 쓰는 `git()`·resume 한도)와 이 CR의 crontab shim(`isolated_crontab` autouse, `Environment.crontab`, install harness의 `fake_crontab`). 코드 변경은 없고 merge commit뿐입니다.
- merge commit에서 입력이 바뀐 명령을 다시 실행했습니다.
  - `python -m pytest -q -n 8 tools/agent-session/tests`: 921 passed (26분 31초).
  - `python -m pytest -q -n 8 install/tests`: 283 passed, 2 skipped (55분 30초).
- 그 밖의 묶음(project-item, project-board, 네 번째 묶음)은 merge가 입력을 바꾸지 않아(TEST-013은 agent-session·install test와 문서만 변경) 앞선 제출의 결과를 재사용합니다.
