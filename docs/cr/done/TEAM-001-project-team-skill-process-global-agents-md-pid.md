# TEAM-001: project-team skill의 process 종료 문구를 global AGENTS.md의 PID 규칙을 가리키게 줄입니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S3
- Related: PERF-004
- Base: 05c57b137fa66c102731ae3646f1b2a883b51eda 2026-11-11T00:09:32+09:00
- Outcome: fixed

## Symptom
process를 PID로만 멈추라는 규칙이 이제 global AGENTS.md "환경과 권한"에 있습니다(agent CONFIG-007, 2e6e17e). 그런데 project-team skill의 Worker 절에도 같은 규칙을 독립적으로 적은 문단이 남아 있습니다(`pgrep -f`·`pkill -f` 설명). 두 곳이 따로 관리되므로 SSOT가 깨집니다.

## Evidence
- `/primehome/swain/.claude/AGENTS.md`(agent `codex/AGENTS.md`) 19행: 자기가 띄운 process만 `TaskStop` 또는 `kill <PID>`로 멈추고, `kill -0 <PID>`로 기다리며, 이름·pattern 종료와 `pgrep` 대기 loop를 금지합니다. Claude에서는 hook이 거절합니다.
- `skills/project-team/SKILL.md` 124행: "다른 process를 기다릴 때는 PID(...)나 provider의 background 완료 알림을 씁니다. `pgrep -f`·`pkill -f`는 ... Sub-agent에게 일을 맡길 때도 이 규칙을 지시합니다."
- agent Leader의 CONFIG-007 완료 메시지(2026-11-11)가 Contract 3(이 문구 축소)을 진행해도 된다고 알렸습니다.

## Contract
- 규칙의 원본은 global AGENTS.md입니다. skill은 그 규칙을 가리키기만 합니다.
- project-team 고유 절차는 skill에 남깁니다. 종료 보고 전 `ps --ppid $PPID` 자식 확인, provider의 background 완료 알림 사용, sub-agent에게도 지시하기가 해당합니다.

## Disposition
- 2026-11-11 Leader: 고친다(Leader 판정). 자기 산출물 정리이며 사용자 요청(2026-11-10 "agent leader session에 요청해~")으로 agent가 반영한 global 규칙의 후속입니다.
- 2026-11-11 Leader: open -> todo. global PID 규칙의 후속 문서 정리
- 2026-11-11 Leader: 제출 9ad4a6c635d3fe1b5b803898f8a7d7e4c1cee831를 인수합니다. 검토 9ad4a6c. SKILL.md 124행 한 문단만 global AGENTS.md를 가리키게 줄였고, 원격 seat가 global AGENTS.md를 받지 못한다는 확인(remote.py GUIDANCE_FILES)에 따라 핵심 한 문장을 남겼습니다. 122행 자식 확인과 대기 예시는 그대로입니다. skills/** 행: distribution boundary + test_remote 70 passed, link 변경 없음.
- 2026-11-11 Leader: in-progress -> done, Outcome fixed. 통합 ae30dbe (origin/main)

## Implementation
읽을 문서: [README 검증](../../../README.md#검증), `/primehome/swain/.claude/AGENTS.md`의 "환경과 권한"(읽기만 합니다), [project-team SKILL.md](../../../skills/project-team/SKILL.md)의 Worker 절과 [self-check.md](../../../skills/project-team/references/self-check.md).

1. SKILL.md의 124행 문단을 다음 내용으로 줄입니다. process를 멈추고 기다리는 방법은 global AGENTS.md "환경과 권한"을 따른다고 적고, provider의 background 완료 알림을 쓸 수 있다는 것과 sub-agent에게도 지시한다는 것만 남깁니다. 같은 규칙을 다시 풀어 쓰지 않습니다.
2. 122행(종료 보고 전 `ps --ppid $PPID` 확인, 남은 것은 PID로 멈춤), 111행과 self-check.md의 "끝나지 않는 대기" 예시는 그대로 둡니다. 다만 global 규칙과 충돌하는 표현이 있으면 고칩니다.
3. 원격 guidance(Codex 원격 seat)가 이 문서를 보낸다면, 원격 seat에서 global AGENTS.md를 읽을 수 없을 때도 규칙의 핵심 한 문장이 남는지 확인합니다. 남지 않으면 한 문장만 남깁니다.

의존: 없음.

위험 등급: 낮음. 문서입니다.

## Verification
1. README 검증 표 `skills/**` 행을 실행합니다. 고친 문서의 상대 link 검사, `tools/test_distribution_boundary.py`, `tools/agent-session/tests/test_remote.py`가 해당합니다.
2. 제출 전에 `origin/main`을 merge하고, merge가 입력을 바꾼 명령만 merge commit에서 다시 실행합니다.

## Result

- 제출 commit: 9ad4a6c635d3fe1b5b803898f8a7d7e4c1cee831

변경: `skills/project-team/SKILL.md`의 process 종료 문단(124행) 1개를 줄였습니다.
- global AGENTS.md "환경과 권한"을 따른다고 가리킵니다. `kill -0` loop 예시와 `pgrep -f` loop·`pkill -f`가 자기 shell과 맞는 이유 설명은 지웠습니다.
- provider background 완료 알림 사용과 sub-agent에게 이 규칙을 지시한다는 것은 남겼습니다.
- 원격 seat 확인(Implementation 3): `remote.py`의 `GUIDANCE_FILES`에 global AGENTS.md가 없어 원격 seat는 이 문서를 받지 못합니다. 그래서 "자기가 띄운 process만 PID로 멈추고 이름·pattern(`pgrep -f`·`pkill -f`)으로 고르지 않는다"는 한 문장만 남겼습니다.
- Implementation 2: 122행(`ps --ppid $PPID` 확인), 111행, self-check.md 25행, `watch.py` 점검 문구의 "끝나지 않는 `pgrep -f` loop" 예시는 global 규칙과 충돌하지 않아 그대로 둡니다.

검증:
- `python -m pytest -q tools/test_distribution_boundary.py tools/agent-session/tests/test_remote.py` → 70 passed.
- 상대 link 검사: 이번 변경은 link를 추가·수정하지 않았고 기존 link 줄도 건드리지 않았습니다.
- `origin/main`은 base(05c57b1)에서 진행하지 않아(`git log HEAD..origin/main` 비어 있음) merge가 없고 재실행할 검증도 없습니다.
- `origin/cr/TEAM-001`에 push해 hash 일치를 `git ls-remote`로 확인했습니다.
