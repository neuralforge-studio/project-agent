# project-agent 설치 안내

이 문서는 project-agent를 자기 계정에 설치하는 직원을 위한 안내입니다. 직원이 할 일과 확인할 결과만 씁니다. 설치가 만드는 경로, 고치는 파일, 거절 조건의 원본은 [설치 계약](project-team/install-contract.md)입니다. 명령과 옵션의 원본은 설치기의 `--help`입니다.

설치는 자기 HOME 아래에만 씁니다. 다른 설정은 바꾸지 않습니다. 기존 파일 중 고치는 것은 tmux 설정 한 개이고, 그 파일에는 줄 세 개짜리 블록 하나만 더합니다([계약 3절](project-team/install-contract.md#3-설치가-고치는-기존-파일은-하나뿐입니다)).

## 1. 전제

| 필요한 것 | 확인 |
| --- | --- |
| Python 3.10 이상 | `python3 --version` |
| tmux | `tmux -V`가 [계약 3.2절](project-team/install-contract.md#32-tmux-최소-버전)의 최소 버전 이상이어야 합니다. 낮으면 `check`가 실패로 알리고, 그 tmux는 설정을 읽을 때 오류 한 줄만 보이며 Board binding·hook을 넣지 않습니다. 사내 tmux는 `/primehome/tools/Inhouse/tmux/latest/bin/tmux`입니다. PATH에서 새 tmux가 앞에 오는지 확인합니다. |
| git | `git --version` |
| Claude Code 또는 Codex CLI | 쓰려는 provider의 CLI가 실행됩니다. |
| Board용 `textual` | 설치에 쓰는 Python에 있어야 합니다. 버전은 [requirements.txt](../tools/project-board/requirements.txt)입니다. 사내 workstation의 Python(아래)에는 있습니다. |

- 설치기를 실행한 Python이 설치본의 Python이 됩니다. 설치 뒤에 바꾸려면 다시 설치합니다.
- 설치기는 그 Python이 사내 환경 설정(`LD_LIBRARY_PATH`) 없이도 같은 Python(같은 `sys.prefix`)으로 뜨는지 시험하고, 필요한 library 경로를 설치본에 기록합니다([계약 6.1절](project-team/install-contract.md#61-python-선택)). 그래서 사내 환경 설정이 없는 계정이나 cron, 그런 환경에서 시작한 tmux server에서도 설치본은 같은 Python과 그 package(`textual`)를 씁니다. 그 경로로도 같아지지 않는 Python은 설치를 거절합니다(`python_environment`).
- 사내 workstation의 Python은 `/primehome/tools/Inhouse/Python3/latest/bin/python3`입니다.
- `textual`이 없어도 설치는 됩니다. Board만 시작하지 않으며 `check`가 알려 줍니다(5절).
- 사내 tmux(`/primehome/tools/Inhouse/tmux/latest/bin/tmux`)도 library(libevent 등)가 필요하고, 설치기는 tmux의 경로를 기록하지 않습니다. 사내 환경 설정이 없는 계정에서는 `LD_LIBRARY_PATH`에 사내 library 경로(`/primehome/tools/Inhouse/libs/libevent/lib`, `/primehome/tools/Inhouse/libs/ncurses/lib`)가 있어야 tmux가 뜹니다. 사내 환경 설정이 있는 계정에서는 이미 맞습니다.
- Claude Code와 Codex의 skill link는 그 provider의 홈(`~/.claude`, `~/.codex`)이 이미 있을 때만 만듭니다. 쓰려는 CLI를 한 번 실행해 홈을 만든 뒤에 설치합니다.
- 홈이 생기기 전에 설치했다면 `install`을 다시 실행해도 link를 더하지 않습니다("No change"). 홈을 만든 뒤 `uninstall`과 `install`을 차례로 실행합니다(7절).

## 2. 설치

먼저 무엇이 바뀌는지 봅니다. `--dry-run`은 아무것도 만들지 않습니다.

```sh
git clone ssh://git@git.primemas.com:222/swain/project-agent.git
PY=/primehome/tools/Inhouse/Python3/latest/bin/python3
$PY project-agent/install/project-agent-install install --dry-run
```

목록이 맞으면 한 줄로 설치합니다.

```sh
$PY project-agent/install/project-agent-install install
```

- 설치기는 작업 트리가 commit과 같은 checkout만 설치합니다. 파일을 고쳤다면 되돌립니다.
- 설치본은 복사본입니다. 설치한 뒤에도 checkout을 두면 갱신(6절)에 씁니다.
- 같은 이름이 이미 있고 설치기 것이 아니면 아무것도 바꾸지 않고 충돌 경로를 모두 출력한 뒤 끝납니다(종료 코드 3). 그 경로를 사용자가 정리한 뒤 다시 실행합니다.
- 실패하거나 중단되면 설치기가 실행 전 상태로 되돌립니다.

설치 뒤에 확인합니다.

```sh
$PY ~/.local/lib/project-agent/current/install/project-agent-install check
```

`check`는 읽기만 합니다. 마지막 줄이 `OK`이고 종료 코드가 0이면 통과입니다. `Note:` 안내는 실패가 아닙니다. 안내가 나오면 아래 3~4절에서 해당 항목을 처리합니다.

## 3. 설치가 만드는 경로와 고치는 파일

| 경로 | 내용 |
| --- | --- |
| `~/.local/lib/project-agent/` | release(`releases/<버전>-<hash>/`), `current` link, `tmux.conf`, 설치 기록 `install.json`, 고친 파일의 원본 `backup/` |
| `~/.local/bin/agent-session`, `project-item`, `project-board` | `current`를 거치는 link |
| `~/.claude/skills/`, `~/.codex/skills/` 아래 `project-team`, `project-item` | skill link. `CLAUDE_CONFIG_DIR`·`CODEX_HOME`이 있으면 그 디렉터리를 씁니다. |
| `~/.config/project-agent/project.json` | 등록 파일 초안(`{}`). 등록 파일이 어디에도 없을 때만 만듭니다. |
| tmux 설정 파일 | 블록 하나를 더합니다. 원본은 `backup/`에 둡니다. |

전체 목록과 규칙은 [계약 2절](project-team/install-contract.md#2-설치가-만드는-것)입니다. Claude·Codex 설정 파일, `CLAUDE.md`, `AGENTS.md`, shell 설정, project 저장소는 건드리지 않습니다([계약 4절](project-team/install-contract.md#4-설치가-절대-건드리지-않는-것)).

설치가 tmux 파일을 고치지 않는 경우가 있습니다. 대상이 symlink이거나, hard link가 여럿이거나, 소유자가 다르거나, 읽기 전용이거나, ACL·확장 속성이 있거나, 1 MiB를 넘는 경우입니다([계약 3절](project-team/install-contract.md#3-설치가-고치는-기존-파일은-하나뿐입니다)). 이때 설치는 계속하고 종료 코드는 0이며, 출력이 넣을 줄을 알려 줍니다. `check`는 그 파일에 이 줄이 아직 없을 때 "수동 연결 필요"로 알립니다. 줄을 넣은 뒤에는 알리지 않습니다. 사용자가 tmux 설정에 직접 넣을 줄은 다음과 같습니다.

```tmux
source-file -q ~/.local/lib/project-agent/tmux.conf
```

## 4. 설치 뒤 한 번 할 일

### PATH

`~/.local/bin`이 PATH에 없으면 설치와 `check`가 알려 줍니다. 설치기는 shell 설정을 고치지 않습니다. 자기 shell 설정에 한 줄을 넣습니다.

```sh
export PATH="$HOME/.local/bin:$PATH"
```

새 shell에서 `agent-session --help`가 나오면 됩니다.

### 이미 떠 있는 tmux server

새로 시작하는 tmux server는 tmux 설정을 읽습니다. 이미 떠 있는 server는 읽지 않으므로 다음 명령을 한 번 실행합니다. 사용자의 전체 설정은 다시 읽지 않습니다.

```sh
tmux source-file ~/.local/lib/project-agent/tmux.conf
```

이 명령은 prefix `B`(Board 열기·닫기)와 마우스 클릭 binding, hook을 server에 넣습니다. 사용자가 이미 정한 binding은 덮어쓰지 않고 건너뜁니다. 건너뛴 키는 `check`가 "binding 건너뜀"으로 알립니다([계약 3.1절](project-team/install-contract.md#31-통합-파일이-server에-넣는-binding)).

### Board 키 바꾸기

Board의 기본 키는 prefix `B`입니다. 다른 키를 쓰려면 통합 파일을 읽기 전에 tmux option `@project_agent_board_key`를 정합니다. 자기 tmux 설정에서 설치 블록보다 앞에 둡니다.

```tmux
set-option -g @project_agent_board_key X
```

떠 있는 server에는 이 줄을 실행한 뒤 위의 `tmux source-file` 명령을 다시 실행합니다. 이미 넣은 이전 키(`B`)의 binding은 server가 끝날 때까지 남습니다. 필요하면 `tmux unbind-key B`로 지웁니다.

### 결정 대기 표시

결정을 기다리는 항목 수를 status에 보이려면 자기 tmux 설정에 한 줄을 넣습니다([계약 5.3절](project-team/install-contract.md#53-tmux-server)). 경로를 알 필요가 없습니다.

```tmux
set-option -ag status-right '#{E:@project_agent_decide_status}'
```

## 5. project 등록

`agent-session`과 `project-item`은 등록 파일에서 project를 찾습니다. 등록 파일은 다음 중 하나입니다([명세 2절](project-team/spec.md#2-등록과-프로젝트-선택)).

1. `~/.config/project-agent/project.json`
2. `~/.codex/project.json`
3. `~/.claude/project.json`

서로 다른 파일이 둘 이상이면 `registry_ambiguous`로 거절합니다. 하나만 두고 나머지는 지웁니다.

설치가 만든 초안은 `{}`입니다. 이 파일에 project를 더합니다. key는 project의 base(기본 checkout)의 절대 경로입니다. 항목 형식은 [등록 예제](project-team/project-registry.example.json)를 따릅니다.

```json
{
  "/home/me/work/example.base": {
    "project": "example",
    "provider": "claude",
    "seats": ["../example.seat0"],
    "path_cr": "agent/cr",
    "path_decide": "agent/decide"
  }
}
```

등록한 뒤 base 안에서 확인합니다.

```sh
cd /home/me/work/example.base
project-item ls
```

오류 없이 끝나면 등록이 읽힙니다. 항목 디렉터리가 아직 없으면 `no directory yet`이 나오며 정상입니다. 이어서 `agent-session start --job leader`로 Leader를 시작합니다. 역할별 절차는 [project-team skill](../skills/project-team/SKILL.md)입니다.

### base의 `agent/`가 untracked로 보일 때

제품은 base의 `agent/` 아래에 실행 기록을 씁니다. 새 project 저장소에서 `git status`가 이 파일을 untracked로 보여 줍니다. 설치는 project 저장소를 고치지 않으므로, 사용자가 자기 저장소의 ignore 설정(`.gitignore` 또는 `.git/info/exclude`)에 넣습니다. 어느 파일에 넣을지는 사용자가 정합니다. 개인 설정으로 충분하면 `.git/info/exclude`에 넣습니다.

```gitignore
agent/state.json
agent/state.lock
agent/suspend.json
agent/suspend.lock
agent/allocation.lock
agent/control/
agent/runs/
agent/diagnostics/
agent/handoff/
agent/decide/decide.html
```

`agent/cr/`와 `agent/decide/`의 CR·결정 항목 파일은 추적 대상입니다. 위 목록에 넣지 않습니다. 경로는 위 등록 예의 `path_cr`·`path_decide` 기본값 기준입니다. 다른 값을 쓰면 그 경로에 맞춥니다([계약 9.1절](project-team/install-contract.md#91-7단계-안내문이-다룰-항목)).

## 6. 갱신·되돌리기·정리

설치할 때 쓴 `$PY`와 checkout에서 실행합니다. `current/install/`의 설치기가 아니라 checkout의 설치기가 새 release의 원본을 읽습니다.

| 할 일 | 명령 |
| --- | --- |
| 갱신 | `git -C project-agent pull` 뒤 `$PY project-agent/install/project-agent-install upgrade` |
| 되돌리기 | `$PY project-agent/install/project-agent-install rollback` |
| 오래된 release 정리 | `$PY project-agent/install/project-agent-install prune` |

각 명령은 `--dry-run`으로 먼저 볼 수 있습니다.

- 갱신과 되돌리기는 `current`만 바꿉니다. shim, skill link, tmux 설정, 등록 파일은 그대로입니다. 이미 떠 있는 run은 시작한 release를 계속 씁니다. 새 run부터 새 release를 씁니다.
- 갱신은 이전 release를 지우지 않습니다. `rollback`은 바로 이전 release 하나로만 돌아갑니다.
- `prune`은 `current`, 바로 이전 release, 떠 있는 run이 쓰는 release를 남기고 나머지를 지웁니다.
- 갱신·`prune` 뒤에는 Board를 닫고 다시 엽니다. 이미 떠 있는 Board는 시작한 release의 파일을 계속 씁니다.
- 떠 있는 run이 있고 새 release와 형식 버전이 다르면 `upgrade`와 `rollback`은 `formats_differ`로 거절합니다. 출력에 나온 run을 `agent-session restart --job <leader 또는 CR ID>`로 다시 시작합니다. 이미 `current`를 쓰는 run은 `agent-session stop`으로 끝낸 뒤 다시 실행합니다([계약 7.1.1절](project-team/install-contract.md#711-떠-있는-run과-형식-버전), [버전 규칙](project-team/release.md)).

## 7. 제거

```sh
$PY ~/.local/lib/project-agent/current/install/project-agent-install uninstall --dry-run
$PY ~/.local/lib/project-agent/current/install/project-agent-install uninstall
```

- 설치기가 만든 것만 지웁니다. tmux 설정은 설치 전과 byte 단위로 같아집니다. 설치 전에 파일이 없었다면 제거 뒤에도 없습니다.
- 등록 파일, base의 `agent/`, `~/.cache`의 잠금은 지우지 않습니다. 남은 경로를 출력합니다.
- 설치가 tmux server에 넣은 binding과 hook은 server가 끝날 때까지 남습니다. `uninstall`이 되돌리는 명령을 출력합니다. 필요하면 사용자가 실행합니다.
- Leader를 시작하면 `agent-session`이 crontab에 `check` 작업을 둡니다. `uninstall`은 crontab을 고치지 않습니다. 남은 구역을 알리고 지우는 명령을 출력하니, 남은 작업이 조용히 실패하지 않게 실행합니다([계약 7.3절](project-team/install-contract.md#73-crontab에-남은-project-구역)). 설치 뒤 `check`도 지운 release를 가리키는 작업을 알립니다.

### `uninstall`이 거절될 때

관리 run이 살아 있으면 `uninstall`은 아무것도 바꾸지 않고 거절합니다. 출력이 project와 slot을 알려 줍니다. `--force`는 없습니다([계약 7.2절](project-team/install-contract.md#72-uninstall의-거절)).

| 거절 사유 | 해소 |
| --- | --- |
| run이 살아 있음(`alive`) 또는 확인할 수 없음(`unknown`) | `agent-session stop --job <leader 또는 CR ID>`로 끝냅니다. `execution_unknown`으로 거절되면 [수동 복구](project-team/spec.md#종료-근거가-부족한-실행의-수동-복구)를 따릅니다. |
| run은 없고 `shutdown` 기록이 남음 | `agent-session resume`으로 재개한 뒤 `stop`으로 끝냅니다. |
| `registry_unreadable`: 등록 파일을 읽을 수 없음 | 등록 파일을 고칩니다(5절). |
| `run_unjudgeable`: 한 project의 run을 판정할 수 없음 | `--json` 출력의 `details.reason`을 읽고 그 project의 `<base>/agent/state.json`이나 등록을 고칩니다. |

## 8. 문제가 생길 때

| 증상 | 확인 |
| --- | --- |
| `check`가 실패(종료 코드 1) | 출력이 어긋난 경로를 알립니다. 사용자가 바꾼 경로는 설치기가 고치지 않습니다. |
| `check`가 "A run was interrupted"로 실패 | 설치기가 중단된 흔적입니다. `check` 외의 명령(예: `install`)을 다시 실행하면 먼저 되돌립니다. `uninstall`과 `prune`은 같은 명령만 마무리합니다([계약 2절 규칙 5](project-team/install-contract.md#2-설치가-만드는-것)). |
| `python_unavailable`, `python_version` | 설치에 쓴 Python이 없어졌거나 3.10 미만입니다. 올바른 Python으로 다시 설치합니다. |
| `check`가 "empty environment"의 `sys.prefix` 불일치로 실패 | 설치 때와 다른 Python으로 뜹니다. 설치 때 쓴 Python이 옮겨지거나 바뀌었는지 확인하고, 그 Python으로 다시 설치합니다. |
| `python_environment`로 설치가 거절됨 | 설치기를 실행한 Python이 빈 환경에서 자기 `sys.prefix`로 뜨지 않고 `<prefix>/lib`도 도움이 되지 않습니다. 다른 Python으로 설치합니다. |
| Board가 시작하지 않음 | 설치 Python에 `textual`이 있는지 `check`의 안내를 봅니다. |

## 관련 문서

- [설치 계약](project-team/install-contract.md): 경로, 고치는 파일, 명령의 동작
- [버전 규칙](project-team/release.md): 버전과 형식 버전의 호환
- [제품 지도](project-team/README.md): 구성 요소와 공개 진입점
