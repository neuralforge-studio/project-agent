# SESSION-003: exit 뒤에도 pane·window가 끝까지 정리되지 않습니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Base: afc5dc25ff13e85251ff5e46ebfd3fb33f0653ca 2026-11-09T21:09:33+09:00

## Symptom
사용자 보고: "exit을 해도 pane, window가 최종 destory까지 안됨." 어느 exit(관리 대화의 `/exit`, `agent-session stop`, CLI 비정상 종료)인지는 아직 구분하지 않았습니다.
출처: 사용자 개선 요청 2026-11-09(대화, 11개 항목 중 9번).

## Evidence
- 관리 window는 `remain-on-exit on`이고, 명세는 종료 근거로 dead pane을 남기며 managed pane만 남은 window를 정리 대상으로 봅니다([명세 3절 종료한 window 정리](../../project-team/spec.md#종료한-window-정리)).

## Contract
- 종료가 확인되고 반납까지 끝난 run의 window·pane은 사용자가 붙인 pane이 없으면 남지 않아야 합니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 재현 가능한 동작 결함이므로 위임 범위입니다. SESSION-004가 stop·반납 경로를 고치므로 그 뒤에 시작합니다. 사용자 지시(2026-11-09 대화): "위와 같이 11개의 개선 요청 사항이 있어."
- 2026-11-09 Leader: 제출 f833183915067410d11c31a96e5d608e311f50d7를 인수합니다. Leader review: 종료 경로별 재현 표와 원인(반납 뒤에도 사용자 pane이 있으면 window 전체 보존, tmux.close_window의 window_shared)을 확인했습니다. 수정: 관리 pane만 닫고 관리 정보·remain-on-exit을 지워 window를 사용자에게 돌려줌, 명세 3절 규칙 먼저. agent-session 749 passed, 경계 test 9. 재현 표의 '/exit만 한 뒤 window 유지(종료 근거)'는 이 CR 범위(반납 뒤) 밖이며, 사용자 보고(exit 뒤 destroy 안 됨)의 주된 경우로 보여 SESSION-007로 엽니다(Leader의 CR 범위 축소 누락).

## Implementation
읽을 문서: [동작 명세](../../project-team/spec.md) 3·7절, [project-team skill](../../../skills/project-team/SKILL.md), [README 검증 표](../../../README.md#검증).

1. 재현: 관리 대화를 끝내는 경로(대화 안의 `/exit`, `agent-session stop`, `restart`, CLI 비정상 종료, `shutdown`)마다 끝난 뒤 window·pane이 어떻게 남는지와 언제 정리되는지(다음 start의 sweep 등) 기록합니다.
2. 원인 확정: 명세가 종료 근거로 dead pane을 남기는 이유와, 정리가 일어나지 않는 경로를 구분합니다. 근거를 남겨야 하는 동안은 남기되, 반납까지 끝난 뒤에도 남는 경우가 결함입니다.
3. 고침: 종료가 확인되고 반납이 끝난 run의 window는 사용자가 붙인 pane이 없으면 그 시점에 정리합니다. 사용자 pane이 있으면 managed pane만 정리합니다. 규칙을 명세 3절 "종료한 window 정리"에 먼저 적습니다.

의존: 선행 SESSION-004.

## Verification
1. 1단계의 경로마다 수정 전 남음과 수정 뒤 정리됨(사용자 pane이 있는 경우 포함), 격리 tmux.
2. README 검증 표의 `tools/agent-session/**` 행.

## Result
- 제출 commit: f833183915067410d11c31a96e5d608e311f50d7

수정 commit은 f46a592이고, 제출 commit은 여기에 `origin/main`(문서 CR 변경만)을 merge한 것입니다.

### 1. 재현(수정 전, fake provider + 격리 tmux, `agent-session` Manager 직접 호출)
| 경로 | 수정 전 결과 |
| --- | --- |
| 대화 안 `/exit`(CLI 종료)만 한 뒤 | pane은 dead, window 유지. state 배정·포인터 그대로(반납 전이므로 종료 근거로 남는 것이 명세 동작) |
| `/exit` 뒤 `stop`(CR done) Worker·Leader | 반납과 함께 window 닫힘 |
| `/exit` 뒤 `stop`(CR in-progress) → CR 이동 | stop은 `released: false`, window 유지. CR 이동의 `finish_release`가 반납하고 window를 닫음 |
| `stop`(반납됨), window에 사용자 pane 있음(`/exit` 유무 무관) | **결함**: `cleanup.kept = window_shared`. 관리 pane(dead)과 `-exited-` 이름이 다음 start까지 남음 |
| restart | 종료한 window를 이어받음(사용자 pane 유지) |
| shutdown | 반납하지 않으므로 이 CR 범위 밖(근거 유지) |
CLI 비정상 종료도 pane이 dead가 되는 것은 `/exit`과 같고 같은 행으로 처리됩니다. 실제 Claude/Codex CLI는 쓰지 않았습니다.

### 2. 원인
정리 조건이 "window의 pane이 관리 pane 하나뿐"이어서(`tmux.close_window`의 `window_shared`), 반납까지 끝난 run도 사용자 pane이 있으면 window 전체가 보존됐습니다. 반납 후 남는 경우는 이것 하나였습니다.

### 3. 수정
- 명세 3절 "종료한 window 정리"에 규칙을 먼저 썼습니다. 사용자 pane이 있으면 관리 pane만 닫고 같은 tmux 명령 sequence로 관리 정보와 `remain-on-exit`을 지워 사용자의 window로 돌려줍니다. 결과에는 `cleanup.pane_closed`(있을 때만)를 둡니다. "재사용" 절과 Leader 시작 절의 반납 뒤 사용자 pane 문구도 맞췄습니다.
- `tmux.close_window`가 `"window"`/`"pane"`을 반환하고, `windows.sweep`과 `lifecycle`의 cleanup 병합이 `pane_closed`를 전달합니다.
- 호환: 사용자 pane이 없는 window의 동작과 `cleanup` 모양은 그대로입니다. 반납 뒤 사용자 pane이 있던 window를 다음 start가 이어받던 동작은 이 CR의 계약대로 사라졌습니다(새 window를 만듭니다). 반납 보류·restart는 종전대로 이어받습니다.

### 4. 검증
- 수정 뒤 격리 tmux: 사용자 pane이 있는 stop(Leader)·반납 보류 뒤 `finish_release`(Worker)·같은 seat의 다음 CR start에서 관리 pane만 닫히고 사용자 pane과 window가 남고, 관리 정보가 지워지며, 없을 때는 window가 닫힘(`tests/test_lifecycle.py`, `tests/test_tmux.py`, `tests/test_run_modules.py`에 추가·수정).
- `python -m pytest -q -n 8 tools/agent-session/tests`: 749 passed (수정 commit 기준).
- `python -m pytest -q tools/test_distribution_boundary.py`: 9 passed.
- 변경 경로상 `api.py`·`state.py`·tmux option 이름은 바꾸지 않아 project-item·project-board test는 실행하지 않았습니다. `docs/project-team/spec.md`를 바꿨지만 원격 guidance(`test_remote.py`)는 전체 agent-session 실행에 포함되어 통과했습니다.
- origin/main merge는 `docs/cr`만 바꾸므로 검증을 다시 실행하지 않고 위 근거를 재사용했습니다.
