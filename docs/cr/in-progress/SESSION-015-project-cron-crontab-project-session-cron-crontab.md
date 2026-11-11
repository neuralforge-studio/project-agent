# SESSION-015: project별 cron을 crontab의 project 구역으로 관리하고, 자기 점검을 session cron에서 crontab으로 옮깁니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S2

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
