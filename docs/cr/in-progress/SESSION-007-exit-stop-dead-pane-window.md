# SESSION-007: 관리 대화가 스스로 끝나면(/exit, 비정상 종료) 누군가 stop할 때까지 dead pane과 window가 남습니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Base: d4911beec6060bc2f46a88a17e979b1e9a675319 2026-11-09T21:55:14+09:00

## Symptom
관리 대화(Leader·Worker) 안에서 `/exit`하거나 CLI가 비정상 종료하면 pane이 dead로 바뀌고 window가 그대로 남습니다. 정리는 누군가 `agent-session stop`을 실행하거나 다음 start의 sweep이 돌 때만 일어납니다. 사용자 보고(2026-11-09, 11개 요청의 9번): "exit을 해도 pane, window가 최종 destory까지 안됨."

## Evidence
- SESSION-003 재현 표(2026-11-09, `docs/cr/done/SESSION-003-*.md` Result): "대화 안 `/exit`(CLI 종료)만 한 뒤: pane은 dead, window 유지. state 배정·포인터 그대로(반납 전이므로 종료 근거로 남는 것이 명세 동작)". CLI 비정상 종료도 같은 행.
- 명세 3절: 관리 window는 `remain-on-exit on`이고 dead pane을 종료 근거로 남깁니다. 명세 5절: SessionEnd hook이 정상 CLI 종료를 관찰하고(`spec.md:701`), Claude는 turn hook·SessionEnd·실제 process 종료로 작업이 끝났음을 확인합니다(`spec.md:926`).
- SESSION-003은 반납이 끝난 뒤 사용자 pane이 있는 경우만 고쳤습니다(Leader가 CR 범위를 "반납까지 끝난 뒤"로 좁게 쓴 누락).

## Contract
- 사용자가 대화를 끝내면(또는 CLI가 끝나면) 그 run의 마무리(종료 확인, 반납 또는 반납 대기, window 정리)가 누군가의 추가 명령 없이 끝나야 합니다. 보존할 작업을 잃지 않는다는 기존 보호(CR in-progress면 반납하지 않음)는 유지합니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 사용자가 보고한 동작 결함이고 위임 범위입니다. 근본 원인은 run의 마무리가 `stop`이라는 별도 명령에만 묶여 있어, CLI가 스스로 끝난 경우에는 마무리할 주체가 없다는 점입니다(SESSION-001의 게시, SESSION-004의 반납과 같은 모양의 결함).
- 2026-11-09 Leader: 제출 31af38e 검토. pane-died에서 stop과 같은 마무리(`_settle`), 종료 근거 `ended.json`, 경합 규칙, Leader `/exit`·Worker SIGKILL·사용자 pane 경우의 실제 tmux test, 760 passed를 확인했습니다. Worker 판단 1(CR in-progress면 window를 반납 대기 근거로 유지, CR 이동 때 정리)은 받아들입니다: Leader의 자기 점검(SESSION-006)이 반납 대기를 보고 CR을 옮기므로 무기한 남지 않고, 근거를 window 밖으로 옮기는 비용(약 30곳)에 비해 이득이 작습니다. 수정 요청: (1) 새 server 전체 hook `pane-died[agent-session]`을 설치 계약 5.3절 표와 `uninstall`의 되돌림 명령에 넣을 것, (2) 이름 붙은 hook index는 tmux 3.8부터이므로(TMUX-002) 더 낮은 tmux에서의 start 동작을 정할 것.
- 2026-11-09 Leader: 제출 cf0295a6d01972d367539a84b4516e7a7f8b3812를 인수합니다. Leader review: 수정 delta(설치 계약 5.3·3.1·3.2에 pane-died[agent-session]와 되돌림, uninstall 출력과 이름 대조 test, start·restart·resume의 시작 전 tmux 버전 확인과 tmux_too_old 거절, 최소 버전 원본은 project-agent.conf 한 줄)를 확인했습니다. install/tests 261 passed, 바꾼 모듈 test 통과, 경계 9. 이전 검토(31af38e의 마무리 구조·ended.json·경합 규칙)와 판단 1 수용을 재사용합니다.

## Implementation
읽을 문서: [동작 명세](../../project-team/spec.md) 3절(종료한 window 정리, 실행 근거)·5절(hook)·7절(stop), SESSION-003·SESSION-004 Result, [README 검증 표](../../../README.md#검증).

1. 마무리 주체: CLI가 끝났음을 처음 아는 곳(tmux의 `pane-died`, 또는 Claude `SessionEnd` hook)에서 agent-session의 마무리를 실행합니다. 마무리는 `stop`이 종료를 확인한 뒤 하는 일과 같은 함수를 씁니다: 종료 근거를 run 기록에 남김 → 반납(CR이 in-progress면 SESSION-004의 반납 대기) → window 정리(SESSION-003 규칙, 사용자 pane이 있으면 관리 pane만).
2. 종료 근거: 지금 dead pane이 맡는 종료 근거를 window를 닫기 전에 run 기록(또는 state 밖의 실행 근거)에 옮겨, window가 없어도 stop·restart·start가 종료를 확인할 수 있게 합니다. 명세 3절에 먼저 적습니다.
3. 경합: 사용자가 `stop`·`restart`를 실행하는 중이거나 대상 제어 잠금이 잡혀 있으면 마무리는 그 명령에 맡기고 끝납니다(중복 마무리 없음). 실행 중인 restart가 새 run을 띄우는 window는 닫지 않습니다.
4. Leader·Worker 모두 같은 규칙입니다. shutdown으로 끝난 run(재개할 기록이 있음)은 정리하지 않습니다(resume이 씁니다).

의존: 선행 SESSION-003·004(done). 병렬 SESSION-006(`lifecycle.py`·`internal.py`가 겹칠 수 있으니 제출 전 `origin/main` merge).

위험 등급: 중간. 종료 근거의 위치를 바꿉니다. stop·restart·start의 종료 판정이 새 근거로 같은 결과를 내는지 test로 확인합니다.

## Verification
README 검증 표의 `tools/agent-session/**` 행(tmux option·hook을 바꾸면 그 행의 추가 명령과 `integrations/tmux/**` 행).
1. 재현(수정 전): fake provider의 CLI를 스스로 끝내면(정상 종료, 비정상 종료) dead pane과 window가 남고 state 배정이 그대로.
2. 수정 뒤: 같은 경우에 추가 명령 없이 window(사용자 pane이 있으면 관리 pane)가 정리되고, CR이 in-progress가 아니면 반납되며, in-progress면 반납 대기로 남고 다음 `project-item move`가 반납을 마침. 그 뒤 stop·restart·start가 새 종료 근거로 지금과 같은 결과.
3. stop·restart 실행 중에 CLI가 끝나도 마무리가 한 번만 일어남. shutdown으로 끝난 run은 정리되지 않고 resume이 이어받음.

## Result
- 제출 commit: cf0295a6d01972d367539a84b4516e7a7f8b3812

구현 (`cr/SESSION-007`, origin/main(SESSION-006 포함) merge 완료):
- 마무리 시작: tmux server의 `pane-died`. start·restart·resume·Worker 배정이 CLI를 띄우기 직전에 server 전체 hook 요소 `pane-died[agent-session]`을 씁니다(`Tmux.install_exit_hook`). 관리 pane일 때만 `python -m agent_session.internal finish-ended <socket> <window> <pane>`을 실행합니다. 사용자 설정의 `pane-died` hook(Board의 `pane-died[project-agent]` 포함)은 그대로 실행됩니다. window scope hook은 server hook을 대체함을 tmux 3.8에서 확인해 쓰지 않았습니다. 이 hook이 server 전체를 쓰는 것이 새 계약이므로 명세 3절과 실행 경로 계약(README 3항)에 적었습니다.
- 마무리 함수: `Manager.finish_ended`. stop이 종료 확인 뒤 하는 일을 `Manager._settle`로 뽑아 stop과 공유합니다(종료 근거 기록 → 반납 또는 반납 대기 → window 정리, 사용자 pane이 있으면 관리 pane만). 대상 제어 잠금 안에서 현재 포인터·게시 완료·stopping/control_pending/살아 있는 controller 없음을 확인하고, 아니면 `finished: false`와 이유만 남깁니다. 잠금이 잡혀 있으면 5초 기다린 뒤 명령에 맡깁니다.
- 종료 근거: `agent/runs/<run_id>/ended.json`(`ended.py`). `_observe`가 pane dead + 같은 run·session·`cli_pid`·`cli_birth`이면 이 기록으로 종료를 판정하므로 window가 없어도 stop·restart·start·window 정리가 같은 판정을 씁니다. Claude는 강제 종료된 CLI가 SessionEnd를 못 남기므로, pane dead + CLI·process group·추적 PID 없음이면 `basis: process`로 확인합니다(forced shutdown과 같은 근거, 최대 15초 기다림). 결과는 `runs/<run_id>/finish-result.json`.
- 명세: 3절 "스스로 끝난 run의 마무리" 신설, 3절 정리 시점 4항, 5절 hook 문단, 7절 stop 문단, 제품 지도의 실행 경로 계약.

판단·가정 (Leader 확인 필요):
1. CR이 in-progress인 run은 반납 대기이며, window·포인터는 SESSION-004대로 `release_pending`의 근거로 유지합니다. window는 `project-item move`가 반납을 마칠 때 정리됩니다(test로 확인). 이 경우까지 즉시 window를 닫으려면 `release_pending`과 현재 포인터를 window 밖으로 옮겨야 하는데, `get_current`를 쓰는 소비처가 api·suspend·watch·windows·board 등 약 30곳이라 이 CR에서 하지 않았습니다. 그렇게 해야 하면 별도 CR이 필요합니다.
2. 등록하지 못한 run과 원격 seat는 마무리 대상이 아닙니다(기존 start/stop 규칙 유지).
3. shutdown은 stopping을 쓰므로 그 run은 마무리가 건드리지 않습니다(resume 유지).

검증 (README 검증 표 `tools/agent-session/**` 행. `api.py`·`state.py`·option 이름은 바꾸지 않아 다른 도구 test는 해당 없음, `integrations/tmux/**`도 변경 없음):
- `python -m pytest -q -n 8 tools/agent-session/tests` merge 전 전체: 760 passed.
- merge 뒤(SESSION-006이 바꾼 lifecycle·launch_artifacts·suspend·watch·remote·spec): `test_self_ended.py test_lifecycle.py test_suspend.py test_watch.py test_run_modules.py test_remote.py test_remote_skills.py`: 271 passed. 영향 없는 나머지 파일의 근거는 merge 전 전체 실행을 재사용했습니다.
- `python -m pytest -q tools/test_distribution_boundary.py`: 9 passed.
- 새 test `tools/agent-session/tests/test_self_ended.py`(실제 tmux·Git, fixture provider는 `fixtures/agent_session_finish_hook.py`로 hook command에 주입):
  - Leader `/exit` → 추가 명령 없이 반납·window 정리·`ended.json`.
  - Worker 비정상 종료(SIGKILL)·CR done → 반납·포인터·window 정리. 사용자 pane이 있으면 관리 pane만 닫음(`pane_closed`).
  - CR in-progress → 반납 대기(`release_pending`, 배정·포인터 유지, `pending_releases`에 표시), CR을 todo로 옮긴 뒤 `finish_release`가 반납·window 정리.
  - 같은 run의 두 번째 마무리는 변경 없음. 잠금 보유·control_pending·stopping 중에는 마무리 안 함, 현재 run이 아니거나 CLI가 살아 있으면 안 함.
  - Claude 비정상 종료에서 provider가 종료를 말하지 못해도 `basis: process`로 마무리, 이어서 stop·restart가 새 근거로 성공. process group이 남아 있으면 확인하지 않음.
  - 실제(생성된) hook command가 server에서 실행되어 `finish-result.json`을 남김. 사용자 설정의 다른 `pane-died` hook도 실행됨.
- 기존 self-restart/self-stop test(control_pending 경합)가 마무리와 같은 server에서 통과.

검증하지 않은 것:
- 검증 1의 "수정 전 재현"은 다시 돌리지 않았습니다. 수정 전 동작은 SESSION-003 Result 표(dead pane·window 유지)와 코드(종료를 알리는 hook 없음)로 갈음했습니다.
- 검증 3의 shutdown은 실제 shutdown을 돌린 test가 아니라 stopping이 있으면 마무리하지 않는 규칙으로 확인했습니다(shutdown은 stopping을 씀, 기존 test_suspend 통과).
- start가 `ended.json` 근거로 종료를 확인하는 경우를 따로 test하지 않았습니다(`_observe` 공용 경로이고 stop·restart·window 정리 test로 확인).
- 실제 Claude·Codex CLI로는 실행하지 않았습니다(fixture CLI).

### 수정 제출 (Leader review 31af38e 반영)
- 제출 commit은 위 행(`cf0295a`: 수정 `041d856` + origin/main의 CR 문서 commit만 merge, 코드 입력 변화 없음). 이전 제출은 31af38e입니다.
1. 설치 계약: 5.3절 표에 `agent-session`의 hook(`pane-died[agent-session]`: 시점·되돌림·근거)을 추가하고, 3.1절 4항에 `set-hook -gwu 'pane-died[agent-session]'`이 agent-session이 넣는 hook의 되돌림임을 적었습니다. 설치기 `uninstall`은 이 명령을 출력합니다(`commands.py` `AGENT_SESSION_HOOK`; 이름이 `tmux.py` `EXIT_HOOK`과 같은지 `install/tests/test_tmux.py`가 비교). tmux 3.8에서 `-g`로 쓴 이 hook을 `-gwu`로 지워짐을 확인했고, uninstall test가 실제 server에서 이를 실행해 확인합니다.
2. 최소 버전: 계약 3.2절에 agent-session도 같은 최소 버전을 요구한다고 적었습니다. 값의 원본은 `project-agent.conf`의 `@project_agent_tmux_min` 한 줄입니다. `Tmux.minimum_version()`이 같은 파일을 읽고(`integrations/tmux/`가 없는 tree, 즉 원격 bundle은 검사하지 않음), `Tmux.require_version()`이 실행 중인 server의 `#{version}`(server가 없으면 PATH의 첫 `tmux -V`)과 비교합니다. `start`·`restart`·`resume`(relaunch)이 시작 전에 호출하고, 낮으면 JSON 오류 `tmux_too_old`(exit 5, message와 details에 현재 버전·최소 버전·`/primehome/tools/Inhouse/tmux/latest/bin`)로 거절해 아무것도 만들지 않습니다. `stop`은 hook이 필요 없어 그대로 동작합니다. 그 밖에 tmux가 hook 쓰기를 거절하면 그 오류(`tmux_command_failed`)로 start가 실패합니다(이전의 삼킴을 뺐습니다). 경로에 따옴표·공백이 있어 hook command를 만들 수 없을 때만 hook 없이 진행하고 `stop`이 마무리합니다(spec 3절에 적음).
3. spec 3절에 위 내용을 적었습니다. 원격 guidance 목록 test(`test_remote.py`)가 spec의 새 link를 거절해 설치 계약은 link 없이 경로로 적었습니다.

수정 검증(바꾼 부분만):
- `python -m pytest -q -n 8 install/tests`: 261 passed, 2 skipped(이 변경과 무관한 기존 skip).
- `python -m pytest -q -n 8 tools/agent-session/tests/test_self_ended.py test_tmux.py test_start_seat.py test_suspend.py test_lifecycle.py test_remote.py`: 315 passed, 2 failed(`test_remote.py` guidance 2건, spec의 install-contract link가 원인). link를 지우고 `test_remote.py -k guidance` 3 passed로 재확인했습니다. test_remote 나머지는 첫 실행에서 통과했고 이후 바뀐 것은 spec 문장뿐입니다.
- `tools/test_distribution_boundary.py`: 9 passed.
- 새 test: tmux 버전 판정(3.8·3.10·next-3.9 통과, 3.6a·2.7·master·빈 값 거절, stub `tmux`), 최소 버전이 계약 3.2절·conf와 같음, 낮은 tmux에서 start·restart가 거절되고 state·window 변화 없이 stop은 동작함.
- 검증하지 않은 것: 3.7 계열 tmux(이 host에 없음, 계약 3.2절과 같이 미지원).
