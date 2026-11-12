# SESSION-016: crontab의 check 작업이 cron 환경의 낮은 tmux로 server에 닿지 못해 정체를 점검하지 못합니다

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S2
- Base: 263aaa50ae2e57b5b85f0733c5bdc79c222d8bb9 2026-11-12T08:03:07+09:00
- Outcome: fixed

## Symptom
SESSION-015(0.10.0)가 만든 project 구역의 `check` 작업은 한 번도 점검하지 못했습니다. 2026-11-12 07:43 KST 마지막 실행 기록(`agent/cron/check.json`)은 `{"ok": false, "result": "error"}`입니다.

그동안 BOARD-018 Worker는 01:50부터 6시간 넘게 멈춰 있었습니다. Worker는 `nohup`으로 분리 실행한 test의 완료 알림을 기다렸고, 그 test는 03:43에 이미 끝나 있었습니다. 그런데 `[agent-session watch]` 메시지가 Worker에게도 Leader에게도 가지 않았습니다. 사용자가 "BOARD-018은 21시간 43분 작업 중인데, 어떤게 문제인거야?"라고 물은 뒤에야 Leader가 정체를 발견했습니다.

## Evidence
- crontab 줄은 `13,43 * * * * <release>/tools/agent-session/bin/agent-session --config ... --socket-path /tmp/tmux-1028/default check --project project-agent >/dev/null 2>&1`입니다. `tools/agent-session/agent_session/cron.py`의 `check_command`가 만듭니다. cron은 PATH `/usr/bin:/bin`으로 실행합니다.
- cron과 같은 환경(`env -i HOME=... PATH=/usr/bin:/bin`)에서 같은 명령을 직접 실행했습니다. 모든 대상이 `tmux_command_failed`(`display-message`, reason `lost server`)였고, run 결과는 `error`였습니다.
- `agent_session/tmux.py`의 `_argv`는 `tmux`를 PATH에서 찾습니다. cron의 PATH에서는 `/usr/bin/tmux` 2.7이 잡힙니다. 실행 중인 server는 사내 tmux 3.8(`/primehome/tools/Inhouse/tmux/latest/bin`)입니다. `/usr/bin/tmux -S /tmp/tmux-1028/default display -p x`는 `lost server`로 끝납니다(client와 server의 protocol 불일치).
- Leader의 대화형 shell은 PATH 앞에 사내 tmux가 있어서 같은 명령이 성공합니다. [설치 계약](../../project-team/install-contract.md) 3.2절은 사내 tmux 경로를 PATH 앞에 두라고 안내하지만, cron 환경에는 이 안내가 닿지 않습니다.
- 실패 이유가 `check.json`에 남지 않습니다. `result`는 `error` 한 단어이고, 대상별 오류를 담은 출력은 줄 끝 `>/dev/null 2>&1`이 버립니다. 이유를 알려면 같은 명령을 손으로 다시 돌려야 했습니다.
- 임시 조치(2026-11-12 08:01 KST, Leader): crontab의 이 줄 명령 앞에 `PATH=/primehome/tools/Inhouse/tmux/latest/bin:/usr/bin:/bin`을 붙였습니다.
  - 같은 환경에서 다시 실행하니 `{"ok": true, "result": "idle"}`였습니다. `agent-session cron ls`도 구역을 정상으로 읽습니다.
  - 이 접두는 다음 Leader 시작 때 `ensure_check`가 명령을 release의 것으로 맞추면 사라집니다.

## Contract
1. Leader 시작이 보장하는 `check` 작업은 cron 환경(PATH `/usr/bin:/bin`, 최소 환경 변수)에서도 Leader가 쓰는 tmux server에 닿습니다. 그 server와 맞는 tmux client를 쓰고, 사용자의 PATH나 login 설정에 기대지 않습니다.
2. 어느 tmux를 쓰는지는 한 곳이 정하고 [동작 명세 7절 cron](../../project-team/spec.md#cron)(check 작업 줄)에 적습니다. 방법은 Worker가 정합니다. 예를 들어 Leader를 시작한 환경의 tmux를 줄에 기록할 수 있습니다. tmux를 찾지 못하거나 server와 맞지 않으면 그 이유가 run 결과에 남습니다.
3. 실패한 `check` run의 기록(`agent/cron/check.json`)은 실패 이유의 code를 담습니다(예: `tmux_command_failed`). 기존 필드 `at`·`ok`·`result`의 뜻과 성공 결과(`idle` 등)는 그대로이고, 형식은 명세가 정합니다.
4. 이미 있는 `check` 줄은 다음 Leader 시작 때 `ensure_check`가 새 명령으로 맞춥니다(명세: "명령만 이 release의 것으로 맞춥니다"). Leader가 손으로 붙인 `PATH=` 접두도 이때 정리됩니다.
5. 사용자가 `cron add`로 넣은 작업의 명령은 바꾸지 않습니다.

## Disposition
- 2026-11-12 Leader 판정: 구현한다. 재현과 근거가 있는 결함입니다(SESSION-015에서 나온 하위 결함). cron과 같은 환경에서 같은 명령이 `lost server`로 실패하는 것을 재현했고, PATH에 사내 tmux를 두면 성공합니다. 정체 점검이 없으면 멈춘 Worker를 아무도 알아채지 못하므로(BOARD-018에서 6시간) 다음 release에 넣습니다.
- 2026-11-12 Leader: open -> todo.
- 2026-11-12 Leader 검토(제출 04f00295ed4f6e18791dd9f3dec31e42b59d0365): 수정 요청. agent-session 변경, 명세, test, 실제 재현은 그대로 둡니다. 회귀가 1건 있습니다. 설치기 `check`(INSTALL-008, 설치 계약 7절·7.3절, T35)는 작업 명령의 첫 단어를 프로그램으로 읽는데, 새 줄은 `env`로 시작합니다. 그래서 지운 release를 가리키는 check 줄을 알리지 못합니다. 앞의 `env`·`NAME=값`을 건너뛰어 읽고, 계약 문구와 T35를 고치고, `install/tests`를 실행하도록 요청했습니다.
- 2026-11-12 Leader 검토(수정 제출 f438a6c108b61c5cd58064b6e501782e3a1b8c76): 인수. 설치기 `_command_path`가 앞의 `env`·`NAME=값`을 건너뛰어 Leader 시작이 쓰는 줄과 사람이 붙인 `PATH=` 줄 모두에서 release 진입점을 읽습니다. 설치 계약 7절·7.3절과 T35를 고쳤고, 세 모양의 T35 test가 지운 release만 알리는지 확인했습니다. `install/tests` 298 passed, 2 skipped. agent-session 쪽은 앞 검토(04f0029)의 근거를 재사용합니다(이 수정이 바꾸지 않음).
- 2026-11-12 Leader: 제출 f438a6c108b61c5cd58064b6e501782e3a1b8c76를 인수합니다.
- 2026-11-12 Leader: in-progress -> done, Outcome fixed. 통합 95eff34 (origin/main)

## Implementation
읽을 문서: [동작 명세](../../project-team/spec.md)의 watch·check·cron 절과 Leader 시작, [설치 계약](../../project-team/install-contract.md) 3.2절(tmux 최소 버전과 사내 tmux 경로), `tools/agent-session/agent_session/cron.py`(`check_command`, `ensure_check`, `last_run` 기록), `tools/agent-session/agent_session/tmux.py`(`_argv`), [SESSION-015 CR](../done/SESSION-015-project-cron-crontab-project-session-cron-crontab.md), [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. `check` 작업이 쓸 tmux를 정합니다. 그 방법을 `check_command`·`ensure_check`와 명세 7절에 반영합니다. 명령 줄은 csh가 아니라 cron의 `/bin/sh`가 실행하지만, 사람이 그대로 복사해 실행할 수 있게 유지합니다.
2. `check` run 기록에 실패 이유 code를 더하고 명세에 형식을 적습니다.
3. Test(관측 동작):
   - 생성한 `check` 줄을 `env -i`와 PATH `<틀린 tmux가 있는 디렉터리>:/usr/bin:/bin`인 `/bin/sh`로 실행합니다. 이때 Leader 시작 때의 tmux를 쓰는지 확인합니다. 격리 tmux server(`tools/tests/tmux_test_server.py`)를 씁니다.
   - tmux를 쓸 수 없을 때 run 기록에 이유 code가 남는지 확인합니다.
   - 이미 있는 줄(옛 명령, 손으로 붙인 `PATH=` 접두)을 `ensure_check`가 새 명령으로 맞추는지 확인합니다.
4. Leader가 손으로 붙인 crontab 접두는 Worker가 건드리지 않습니다. 통합·설치 뒤 Leader 시작이 정리합니다.

위험 등급: 낮음~중간(사용자 crontab의 줄 형식, 명세 변경).

## Verification
README 검증 표에서 바꾼 경로의 행 명령을 모두 제출 commit에서 실행합니다.
- `tools/agent-session/**`: `python -m pytest -q -n 8 tools/agent-session/tests`. `agent_session/api.py`·state 형식·tmux option 이름을 바꾸면 `python -m pytest -q tools/project-item/tests`, `python -m pytest -q tools/project-board/tests`, `python -m pytest -q -n 8 install/tests`도 실행합니다.
- 문서(`docs/project-team/spec.md` 등): 고친 문서의 상대 link 검사, `python -m pytest -q tools/test_distribution_boundary.py`, `python -m pytest -q tools/agent-session/tests/test_remote.py`.
- 실제 재현: 제출 tree의 `check` 줄을 cron과 같은 환경(`env -i HOME=$HOME PATH=/usr/bin:/bin /bin/sh -c '<줄>'`)에서 격리 server를 대상으로 실행합니다. 결과와 run 기록을 Result에 적습니다. 실제 운영 crontab은 고치지 않습니다.

## Result
- 제출 commit: 04f00295ed4f6e18791dd9f3dec31e42b59d0365

변경(구현 commit 33e98c8, 이후 `origin/main` merge는 CR 파일 이동 1건뿐이라 검증 입력이 같습니다):
- `cron.check_command`(한 곳)가 Leader를 시작한 환경 PATH의 `tmux` 디렉터리를 줄 앞에 `env PATH=<디렉터리>:/usr/bin:/bin`으로 적습니다. symlink(`latest`)는 풀지 않고, tmux가 `/usr/bin`·`/bin`에 있거나 못 찾으면 `env`를 붙이지 않습니다. 줄은 `/bin/sh`와 사람의 shell에서 같게 동작합니다.
- `ensure_check`는 그대로 줄의 명령만 맞춥니다. 옛 명령과 손으로 붙인 `PATH=` 접두가 새 명령으로 바뀌고, `cron add`로 넣은 다른 작업은 그대로입니다.
- 실패한 `check` run은 이유 code를 `agent/cron/check.json`(`{at, ok, result, code}`)과 명령 결과 `run`에 남깁니다. project 오류가 있으면 그 code, 아니면 처음 실패한 target의 code입니다. 성공 run과 기존 필드의 뜻은 그대로입니다.
- 명세(spec 7절 check·cron)와 설치 계약 표·self-check·agent-session README의 형식 문구를 고쳤습니다.

검증(제출 tree 기준):
- `python -m pytest -q -n 8 tools/agent-session/tests`: 929 passed. 1 failed는 제 새 test가 PATH를 통째로 바꿔 crontab shim이 가려진 것이었고(아래 사고), 고친 뒤 `test_cron.py` 62 passed. `api.py`·state 형식·tmux option 이름은 바꾸지 않아 다른 도구 test와 `install/tests`는 실행하지 않았습니다.
- `python -m pytest -q tools/test_distribution_boundary.py tools/agent-session/tests/test_remote.py`: 70 passed. 문서에 새 link는 없습니다.
- 새 test: `test_cron.py`(tmux 접두 형식·접두 없음 조건·`ensure_check`의 옛 명령·`PATH=` 접두 교체와 사용자 작업 보존), `test_check.py`(잘못된 tmux가 앞에 있는 cron PATH에서 줄이 Leader의 tmux를 씀, 접두 없는 줄은 `tmux_command_failed`가 code로 남음, tmux가 없으면 `tmux_unavailable`).
- 실제 재현(격리 server, Leader+Worker, `env -i HOME=... PATH=/usr/bin:/bin /bin/sh -c '<줄>'`; 시스템 tmux 2.7, server는 3.8):
  - 접두 없는 줄: `{"ok": false, "result": "error", "code": "tmux_command_failed"}`.
  - 제출 tree가 만든 줄(`env PATH=/primehome/tools/Inhouse/tmux/latest/bin:/usr/bin:/bin ... check --project fixture >/dev/null 2>&1`): `{"ok": true, "result": "idle"}`.

판정·남은 사실:
- 처리할 일이 없고 배정된 Worker도 없는 project의 `check`는 tmux를 부르지 않아 tmux가 깨져도 `idle`입니다(명세에 적었습니다). 정체를 점검할 대상이 있을 때부터 실패가 code와 함께 남습니다.
- Leader가 crontab에 붙인 `PATH=` 접두는 건드리지 않았습니다(통합·설치 뒤 Leader 시작이 정리).
- CHANGELOG는 Leader가 통합할 때 더하므로 고치지 않았습니다.

사고와 복구(보고합니다): 위 새 test 가운데 `ensure_check` test가 처음에 PATH를 `…:/usr/bin:/bin`으로 통째로 바꿔 `crontab` shim이 가려졌고, 시험 중 실제 사용자 crontab에 `# >>> project-agent: alpha >>>` 구역(test의 가짜 project)이 써졌습니다. 발견한 즉시 백업(scratchpad)한 뒤 그 구역만 지웠고, 나머지(사용자 작업 3줄, `project-agent` 구역의 Leader 임시 `PATH=` 줄)는 바이트 단위로 그대로입니다. test는 shim이 있는 기존 PATH 앞에 붙이도록 고쳤고, 고친 뒤 실제 crontab이 변하지 않음을 확인했습니다.

### 수정 제출 (Leader 검토: 설치기 check 회귀)
- 제출 commit: f438a6c108b61c5cd58064b6e501782e3a1b8c76

변경(수정 commit 606e2ba, 이후 `origin/main` merge는 TEST-015 CR 파일 추가뿐이라 검증 입력이 같습니다):
- `install/project_agent_install/crontab.py`의 `_command_path`가 앞의 `env`(`/usr/bin/env`)와 `NAME=값` 단어를 건너뛰고 프로그램을 읽습니다. 사람이 붙인 `PATH=... 프로그램` 모양도 읽힙니다. 지운 release면 지금처럼 project·작업 ID·경로를 알립니다.
- 설치 계약의 "첫 단어" 문구 두 곳과 T35 행을 새 줄 모양으로 고쳤습니다. `install/tests/test_crontab.py`에 T35 test를 더했습니다(`env PATH=...`, `PATH=...` 접두, `env A=1 B='x y'` 세 모양에서 지운 release만 알리고 살아 있는 release는 알리지 않으며 crontab은 변경 없음).

검증:
- `python -m pytest -q -n 8 install/tests`: 298 passed, 2 skipped.
- `python -m pytest -q tools/test_distribution_boundary.py`: 9 passed.
- agent-session 쪽은 이 수정이 건드리지 않아 앞의 검증(929 passed 등)을 재사용합니다.
- 이번 시험 동안 실제 crontab에 `alpha`·`fixture` 구역이 생기지 않았음을 확인했습니다.
