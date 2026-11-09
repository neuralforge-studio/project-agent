# INSTALL-007: check가 tmux 연결 상태 manual이면 include 줄이 이미 있어도 수동 연결 필요 안내를 냅니다

- Opened: 2026-11-10
- Scope: project-agent
- Severity: S3
- Base: d55bd3013d4d6ffa0b5cb7e32b04d9eacb01506b 2026-11-10T03:00:15+09:00

## Symptom
2026-11-10 이 workstation을 0.2.0으로 upgrade한 뒤 `check`가 다음 안내를 냈습니다: `Note: Manual connection needed (수동 연결 필요): ~/.tmux.conf was not changed. Add this line to it: source-file -q ~/.local/lib/project-agent/tmux.conf`. 그러나 `~/.tmux.conf`(→ `Utils/agent/agent.base/tmux/tmux.conf` symlink)의 117행에 그 줄이 이미 있습니다. 직원은 이미 한 연결을 다시 하라는 안내를 받습니다.

## Evidence
- `install/project_agent_install/commands.py` `_plan_tmux_block`: 대상이 symlink이면 파일을 고치지 않고 `tmux.state = "manual"`로 기록합니다(설치 계약의 원칙 B).
- 같은 파일의 check(559-561행 부근): `state == "manual"`이면 파일 내용을 보지 않고 항상 안내를 더합니다. 설치 뒤 사람이 그 줄을 넣었는지 확인하지 않습니다.
- `~/.local/lib/project-agent/install.json`의 `tmux`는 `{"file": "~/.tmux.conf", "state": "manual"}`입니다. `grep -n 'source-file -q ~/.local/lib/project-agent/tmux.conf' ~/.tmux.conf`의 결과는 `117:`입니다.

## Contract
- `check`는 읽기만 합니다. 안내(`Note:`)는 지금 사실과 맞아야 합니다. 연결이 이미 되어 있으면 연결을 다시 하라고 안내하지 않습니다.

## Disposition
- 2026-11-10 Leader: 고친다(Leader 판정). 재현 근거가 있는 결함입니다(0.2.0 upgrade 직후의 `check`). 동작에는 영향이 없고 안내만 틀립니다.
- 2026-11-10 Leader: 제출 5bdb14829295ad9058a67bd180722a543372686e를 인수합니다. Leader review: tmuxconf.has_source(줄 판정 규칙 한 곳, symlink를 따라 읽기 전용, 공백을 뗀 줄 전체가 SOURCE와 같을 때만, 읽기 실패는 False)와 check의 manual 분기, 계약 3절 표·T4 행과 설치 안내 문장을 확인했습니다. 수정 전 재현(줄이 있는 두 사례에서 안내), 수정 뒤 6사례와 HOME snapshot 불변, install/tests 267 passed+2 skipped. README 표의 docs 행은 Leader가 제출 commit에서 실행: tools/test_distribution_boundary.py 9 passed, 고친 두 문서의 상대 link 깨짐 없음. 첫 0.2.0 run의 확인(self-check cron을 첫 prompt 지시로 등록, launch.sh가 0.2.0-e87364816d43 release를 씀)도 기록했습니다.

## Implementation
읽을 문서: [설치 계약](../../project-team/install-contract.md)(check와 tmux 연결 상태), [설치 안내 2·3·4절](../../install.md), [README 검증](../../../README.md#검증), [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. `check`는 `manual` 상태의 연결이 지금 되어 있는지 읽어서 판정합니다. 기록된 파일을 symlink를 따라 읽기 전용으로 엽니다. 주석이 아닌 줄에 `tmuxconf.SOURCE`가 있으면 안내하지 않습니다. 없거나 읽을 수 없을 때만 지금 안내를 냅니다. 줄의 판정 규칙은 `tmuxconf`에 한 곳으로 둡니다. 설치 때 쓰는 판정과 같은 것을 재사용할 수 있으면 재사용합니다.
2. 설치 계약의 check 설명과 설치 안내의 해당 문장을 동작에 맞춥니다.
3. 격리 HOME test에 사례를 둡니다: symlink인 tmux 설정에 줄이 없으면 안내가 나오고, 줄이 있으면 안내가 없으며, 주석 처리된 줄은 없는 것으로 봅니다.

의존: 없음.

위험 등급: 낮음.

## Verification
1. 수정 전: 위 세 사례 중 줄이 있는 경우에 안내가 나오는 재현.
2. 수정 뒤: 세 사례 통과.
3. README 검증 표의 `install/**` 행(`install/tests`, `-n 8`).
4. 이 Worker는 0.2.0으로 시작하는 첫 run입니다. Result에 다음 두 가지를 적습니다.
   - 시작 직후 `CronList`에 self-check 작업(project-team `references/self-check.md`)이 등록됐는지
   - `ps -o pid,args --ppid $PPID`의 Claude 실행 경로가 아니라 `echo $AGENT_SESSION_*`·launch 파일이 가리키는 release가 `0.2.0-e87364816d43`인지(볼 수 있는 범위에서)

## Result
- 제출 commit: 5bdb14829295ad9058a67bd180722a543372686e
- 변경: `tmuxconf.has_source(path)`를 더했습니다(줄 판정 규칙의 한 곳). 기록된 파일을 symlink를 따라 읽기 전용으로 열어 `SOURCE`가 공백을 뗀 한 줄 전체와 같으면 True이고(주석 줄·`tmux.conf.old` 같은 접미 줄은 아님), 읽을 수 없으면 False입니다. `commands.py` `run_check`의 `manual` 분기는 `has_source`가 False일 때만 안내를 냅니다. 설치 때 쓰는 판정(`has_block`)은 시작 표시 블록을 보는 다른 규칙이라 재사용하지 않았습니다. 설치 계약(3절 표·T4 행)과 설치 안내 해당 문장을 동작에 맞췄습니다.
- 검증 1(수정 전 재현): 새 test `test_t4_check_announces_the_manual_connection_only_while_the_line_is_missing`을 먼저 실행해, 줄이 있는 두 사례(한 줄, 앞뒤 공백)에서 `Note: Manual connection needed`가 나오는 실패를 확인했습니다(6 중 2 실패).
- 검증 2(수정 뒤): 같은 test 5사례(줄 없음→안내, 줄 있음→없음, 공백 낀 줄→없음, 주석 처리 줄→안내, `tmux.conf.old` 줄→안내)와 link 대상이 없는 사례(→안내)가 통과합니다. test는 check 전후 HOME snapshot이 같음(읽기만 함)도 확인합니다. `-k 'check_announces or t4'` 8 passed.
- 검증 3: `python -m pytest -q -n 8 install/tests` → 267 passed, 2 skipped(제출 commit의 내용에서 실행). 다른 README 표 행은 바꾼 경로(`install/**`, `docs`의 계약·안내)에 해당하지 않아 실행하지 않았습니다.
- 검증 4(첫 run 확인):
  - `CronList`: 시작 직후 첫 `CronList`는 "No scheduled jobs."였습니다. 즉 첫 prompt 지시를 따라 내가 self-check(`13,43 * * * *`, Worker 절 prompt)를 그때 등록했고(job 5c53d199) 시작 시점에 자동으로 등록돼 있지는 않았습니다.
  - release: `echo $AGENT_SESSION_*`는 `AGENT_SESSION_BASE`·`_SOCKET`·`_CONFIG`만 보여 release를 담지 않습니다. `~/.local/lib/project-agent/current`는 `releases/0.2.0-e87364816d43`이고, `~/.local/bin/agent-session`과 `~/.claude/skills/project-team`은 `current/` 아래를 가리키며, 이 run의 launch.sh(`base/agent/runs/243d3d83.../launch.sh`)에서 `0.2.0-e87364816d43`가 나옵니다. 따라서 이 run은 `0.2.0-e87364816d43` release를 씁니다(`ps` 출력의 자식은 내 shell뿐이라 Claude 실행 경로는 보지 않았습니다).
