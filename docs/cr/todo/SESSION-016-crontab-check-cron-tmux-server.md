# SESSION-016: crontab의 check 작업이 cron 환경의 낮은 tmux로 server에 닿지 못해 정체를 점검하지 못합니다

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S2

## Symptom
SESSION-015(0.10.0)가 만든 project 구역의 `check` 작업은 한 번도 점검하지 못했습니다. 2026-11-12 07:43 KST 마지막 실행 기록(`agent/cron/check.json`)은 `{"ok": false, "result": "error"}`입니다.

그동안 BOARD-018 Worker는 01:50부터 6시간 넘게 멈춰 있었습니다. Worker는 `nohup`으로 분리 실행한 test의 완료 알림을 기다렸고, 그 test는 03:43에 이미 끝나 있었습니다. 그런데 `[agent-session watch]` 메시지가 Worker에게도 Leader에게도 가지 않았습니다. 사용자가 "BOARD-018은 21시간 43분 작업 중인데, 어떤게 문제인거야?"라고 물은 뒤에야 Leader가 정체를 발견했습니다.

## Evidence
- crontab 줄은 `13,43 * * * * <release>/tools/agent-session/bin/agent-session --config ... --socket-path /tmp/tmux-1028/default check --project project-agent >/dev/null 2>&1`입니다. `tools/agent-session/agent_session/cron.py`의 `check_command`가 만듭니다. cron은 PATH `/usr/bin:/bin`으로 실행합니다.
- cron과 같은 환경(`env -i HOME=... PATH=/usr/bin:/bin`)에서 같은 명령을 직접 실행했습니다. 모든 대상이 `tmux_command_failed`(`display-message`, reason `lost server`)였고, run 결과는 `error`였습니다.
- `agent_session/tmux.py`의 `_argv`는 `tmux`를 PATH에서 찾습니다. cron의 PATH에서는 `/usr/bin/tmux` 2.7이 잡힙니다. 실행 중인 server는 사내 tmux 3.8(`/primehome/tools/Inhouse/tmux/latest/bin`)입니다. `/usr/bin/tmux -S /tmp/tmux-1028/default display -p x`는 `lost server`로 끝납니다(client와 server의 protocol 불일치).
- Leader의 대화형 shell은 PATH 앞에 사내 tmux가 있어서 같은 명령이 성공합니다. [설치 계약](../../project-team/install-contract.md) 3.2절은 사내 tmux 경로를 PATH 앞에 두라고 안내하지만, cron 환경에는 이 안내가 닿지 않습니다.
- 실패 이유가 `check.json`에 남지 않습니다. `result`는 `error` 한 단어이고, 대상별 오류를 담은 출력은 줄 끝 `>/dev/null 2>&1`이 버립니다. 이유를 알려면 같은 명령을 손으로 다시 돌려야 했습니다.
- 임시 조치(2026-11-12 08:15 KST, Leader): crontab의 이 줄 명령 앞에 `PATH=/primehome/tools/Inhouse/tmux/latest/bin:/usr/bin:/bin`을 붙였습니다.
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
