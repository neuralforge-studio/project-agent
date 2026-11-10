# project-agent 설치 계약

이 계약은 확정 기준(사용자 결정 D-20261109-08·09)입니다. 설치기는 `install/`가 구현하고(DIST-001 4단계) 인수 test는 `install/tests`입니다.
이 문서는 설치기와 인수 test의 원본입니다. 설치기 구현과 test는 이 문서를 따릅니다. 이 문서와 다른 동작이 필요하면 먼저 이 문서를 고칩니다.

- 대상: project-team 제품(이하 project-agent). 구성 요소는 [제품 지도](README.md)가 설명합니다.
- 결정의 원문은 CR DIST-001의 Disposition에 있습니다.
  - D-20261109-08 C: 배포하는 과정에서 다른 설정에는 영향이 없어야 합니다.
  - D-20261109-09 C: 기존 파일의 수정은 사용자 tmux 설정의 include 한 줄로 한정합니다. 전용 tmux 설정은 `~/.local/lib/project-agent/` 아래에 둡니다.
- 상태 표시: 이 문서의 모든 항목은 확정 기준입니다. **(미확인)**은 코드에서 확인하지 못한 사실입니다.
- 코드 근거는 `path:line`으로 적습니다. 줄 번호는 2026-11-09 코드(`cb79754`) 기준입니다.

## 1. 용어

| 용어 | 뜻 |
| --- | --- |
| release | 설치 한 번이 만드는 불변 디렉터리 `~/.local/lib/project-agent/releases/<version>-<hash>/`. 만든 뒤에 내용을 바꾸지 않습니다. |
| `current` | `~/.local/lib/project-agent/current`. 활성 release를 가리키는 symlink입니다. |
| 설치 기록 | 설치기가 만든 경로와 소유를 적은 manifest. 위치는 `~/.local/lib/project-agent/install.json`입니다. |
| 소유 | 설치 기록에 적힌 경로입니다. 설치기는 자기 소유만 바꾸거나 지웁니다. |
| 관리 run | `agent-session`이 시작한 Leader·Worker의 실행입니다. state와 tmux 실행 근거로 판단합니다([명세](spec.md)). |

## 2. 설치가 만드는 것

설치는 아래 경로만 만듭니다. 경로마다 설치 기록에 소유를 남깁니다.

| 경로 | 종류 | 내용 |
| --- | --- | --- |
| `~/.local/lib/project-agent/releases/<version>-<hash>/` | 디렉터리 | 불변 release. 도구, skill, 문서, tmux 통합 파일, 설치기(`install/`)를 담고 test·`__pycache__`·`docs/cr`는 담지 않습니다. 설치 interpreter와 그 library 경로를 적은 `tools/python.env`를 더합니다(6.1절). 외부 package는 담지 않습니다(사용자 결정 D-20261109-01 waive). 만들 때 설치 interpreter로 미리 compile하고(`__pycache__`), 시동 번들(6.1절)을 `tools/__pycache__`에 쓰고, 쓰기 권한을 모두 뺍니다. 그래야 실행이 release에 파일을 더하지 않습니다. |
| `~/.local/lib/project-agent/current` | symlink | 활성 release를 가리킵니다. 원자적으로 바꿉니다. |
| `~/.local/lib/project-agent/tmux.conf` | 파일 | tmux include의 고정 대상입니다. `source-file -q ~/.local/lib/project-agent/current/integrations/tmux/project-agent.conf` 한 줄을 담습니다. 설치 때 한 번 쓰고 갱신하지 않습니다. |
| `~/.local/lib/project-agent/install.json` | 파일 | 설치 기록 |
| `~/.local/lib/project-agent/backup/` | 디렉터리 | 설치가 고친 기존 파일의 원본(3절). 고친 파일이 없으면 만들지 않습니다. |
| `~/.local/bin/agent-session`, `project-item`, `project-board` | shim | `current/tools/<도구>/bin/<도구>`를 가리키는 절대 경로 symlink입니다. 반드시 `current`를 거칩니다. |
| `~/.claude/skills/project-team`, `~/.claude/skills/project-item` | symlink | `current` 아래 skill 디렉터리로 가는 link |
| `~/.codex/skills/project-team`, `~/.codex/skills/project-item` | symlink | 같은 skill 디렉터리로 가는 link |
| `~/.config/project-agent/project.json` | 파일 | 등록 파일 초안. 6절의 조건에서만 만듭니다. 내용은 빈 등록(`{}`)입니다. `load_registry`가 빈 object를 project 0개로 읽습니다([config.py:152-153](../../tools/agent-session/agent_session/config.py)). |

경로 규칙은 다음과 같습니다.

1. 이미 같은 이름이 있고 설치기 소유가 아니면, 아무것도 바꾸지 않고 전체를 거절합니다.
   - 같은 이름은 파일, 디렉터리, 다른 곳을 가리키는 link입니다.
   - 같은 대상을 가리키지만 설치 기록에 없는 link도 소유가 아니므로 거절합니다.
   - 거절은 충돌 경로를 한 번에 모두 출력합니다.
   - 예외: 원격 runtime이 만든 skill link는 충돌이 아닙니다. 아래 규칙 6이 정합니다.
   - 예외: `install --adopt-dev-links`를 준 경우, 옛 개발 checkout을 가리키는 사용자 자신의 link는 충돌이 아닙니다. 아래 규칙 8이 정합니다.
2. 부모 디렉터리가 없으면 설치가 만들고 설치 기록에 `created_dirs`로 남깁니다. 제거는 그 디렉터리가 비어 있을 때만 지웁니다.
3. provider 홈이 없으면 그 provider의 skill link를 만들지 않고 안내만 출력합니다. 설치가 쓰지 않는 provider의 홈을 만들지 않기 위해서입니다. provider 홈의 경로는 아래 규칙 7이 정합니다.
4. 부모 디렉터리가 symlink이면 link를 따라가서 만듭니다. link는 가리키는 디렉터리 안에 놓입니다. 설치 기록과 출력에는 `~` 기준 경로를 적고, 실제 위치를 함께 출력합니다. 이 workstation의 `~/.claude/skills`가 그 경우입니다(DIST-001 6단계가 `.gitignore`로 다룹니다).
5. **실패와 중단은 정해진 상태로 돌아갑니다.** 설치기는 첫 변경 전에 진행 기록(journal) `.project-agent-install-journal.json`을 씁니다. 위치는 lib 경로(`~/.local/lib/project-agent`)와 그 조상(`~/.local/lib`, `~/.local`, HOME) 중 실행 전에 있는 가장 가까운 디렉터리입니다. 설치 기록은 마지막에 확정합니다.
   - 실패하거나 SIGINT·SIGTERM·SIGHUP을 받으면 `install`·`upgrade`·`rollback`은 이미 한 변경을 되돌려 실행 전 상태로 돌리고(종료 코드 4) journal을 지웁니다.
   - SIGKILL이나 전원 차단 뒤에는 journal이 남습니다. 다음 명령(`check`는 실패로 알리기만 함)은 요청받은 일보다 먼저 그 되돌림을 끝내고 이어서 자기 일을 합니다. "lib는 있는데 설치 기록이 없어" 막히는 상태가 생기지 않습니다. `--dry-run`은 journal이 있으면 아무것도 바꾸지 않고 거절합니다.
   - `uninstall`과 `prune`은 지운 것을 되돌리지 않습니다. 중단되면 journal이 남고 다른 명령은 거절하며 같은 명령(`uninstall`은 `uninstall`, `prune`은 `prune`)만 지우기를 마칩니다. 삭제 오류는 숨기지 않고 실패(종료 코드 4)로 보고하며 설치 기록은 다른 삭제가 모두 끝난 뒤에 지웁니다. symlink는 tree로 지우지 않습니다.
   - journal을 쓰다가 실패하면(디렉터리 fsync 실패 포함) journal을 지우고 "아무것도 바꾸지 않았다"고만 말합니다.

   복구·제거는 세 원칙을 따릅니다. 이 원칙이 설치기 구현과 test의 원본입니다.

   - **원칙 A. 경로의 출처는 설치기 하나입니다.** 복구·제거가 다루는 모든 경로(대상, 임시 파일, journal 자신)는 설치기가 계산한 배치에서 나옵니다. journal은 step의 종류·식별자(`current`, `shim:<도구>`, `skill:<provider>:<이름>`, `release:<이름>`, `tmux:<후보 번호>` 등 닫힌 집합)와 상태 지문(내용 hash, link 대상)만 담고 경로 문자열은 담지 않습니다. 설치 기록의 경로는 설치기가 계산한 배치와 정확히 같을 때만 받습니다. 둘 다 읽을 때 종류·식별자·형식을 검증하고 어긋나면 아무것도 바꾸지 않고 거절합니다(종료 코드 3). 임시 파일 이름은 대상에서 정해진 이름(`.<이름>.pi-tmp`, release는 `releases/.tmp-<이름>`, journal은 `.project-agent-install-journal.json.tmp`)이며 설치기가 예약한 이름입니다. 그래서 다음 실행과 복구가 찾아 지웁니다. **provider 홈(`CLAUDE_CONFIG_DIR`·`CODEX_HOME` 반영)은 설치 기록과 journal에서 값을 받는 유일한 예외입니다.** 그 아래에서 설치기가 다루는 것은 `skills/<이름>` link와 `skills/` 디렉터리뿐이고, link는 대상이 계산한 `current/skills/<이름>`과 같을 때만, 디렉터리는 비었을 때만 지웁니다(원칙 B). 그래서 값이 조작돼도 사용자의 파일을 지울 수 없습니다.
   - **원칙 B. 되돌림·제거는 "설치기가 만든 그 상태"일 때만 그 경로를 건드립니다.** 파일은 설치기가 쓴 내용의 hash, link는 설치기가 만든 대상, 디렉터리는 비어 있음, release는 설치 기록에 적은 파일 목록 지문(`digest`: 파일과 그 위 디렉터리의 이름 목록이며 `__pycache__` 디렉터리와 그 안의 `.pyc`만 빠집니다)이 지금과 같을 때만 지웁니다. `backup/`은 기록한 backup 파일만 지운 뒤 비어 있을 때만 `rmdir`합니다. 다르면(사용자가 그 사이에 만들거나 고침) 건드리지 않고 알립니다. 오류로 명령을 막지 않습니다. 새 파일은 임시 파일에 다 쓴 뒤 `link`로 이름을 얻으므로 이미 있는 이름은 덮어쓰지 않고, 이름이 생긴 파일은 내용이 완전합니다.
   - **원칙 C. 사용자 tmux 파일은 언제 끊겨도 바꾸기 전 bytes 또는 바꾼 뒤 bytes 둘 중 하나입니다.** 제자리에서 쓰지 않습니다. 같은 디렉터리의 임시 파일에 새 내용을 쓰고 fsync한 뒤 rename하고 디렉터리를 fsync합니다. 권한은 원래 파일과 같습니다. rename 직전에 파일이 읽을 때와 같은지(inode·크기·시각) 다시 확인하고, 다르면 바꾸지 않습니다. journal은 바꾸기 전 bytes와 바꾸기 전·뒤 hash를 두고, 복구와 제거는 지금 hash가 "바꾼 뒤"일 때만 되돌리며, "바꾸기 전"이면 아무것도 하지 않고, 둘 다 아니면(사용자가 고침) 건드리지 않고 알립니다.

6. **원격 runtime의 skill link를 넘겨받습니다.** 원격 runtime은 `~/.codex/skills/project-team`·`project-item` link를 만들고 소유를 `~/.cache/agent-session/skills.json`에 적습니다([remote_runtime.py:46-94](../../tools/agent-session/agent_session/remote_runtime.py)). 같은 제품이 만든 link이므로 설치는 이를 충돌로 보지 않습니다.
   - 넘겨받는 조건은 runtime이 소유를 판단하는 조건과 같습니다. 이름이 `skills.json`에 있고, link의 소유자가 현재 사용자이고, link의 대상이 기록한 대상과 같습니다([remote_runtime.py:72-76](../../tools/agent-session/agent_session/remote_runtime.py)). 하나라도 다르면 충돌입니다.
   - 설치는 그 link를 설치본의 skill 디렉터리를 가리키도록 바꾸고, 설치 기록에 설치기 소유로 적습니다. 설치 기록에는 넘겨받았음을 함께 적습니다.
   - 설치는 `skills.json`을 고치지 않습니다. runtime이 소유하는 기록이기 때문입니다.
   - 설치본이 있으면(`~/.local/lib/project-agent/install.json`이 있으면) runtime은 skill link를 만들지 않고 고치지 않습니다. 이 동작은 코드 변경입니다. 처리 단계는 9절에 적습니다.
7. **provider 홈은 환경 변수를 따릅니다.** 제품 코드가 따르는 규칙과 같습니다([claude.py:104](../../tools/agent-session/agent_session/providers/claude.py), [codex.py:68](../../tools/agent-session/agent_session/providers/codex.py)).
   - Claude: `CLAUDE_CONFIG_DIR`가 설정돼 있으면 그 디렉터리, 없으면 `~/.claude`. skill link는 그 아래 `skills/`에 만듭니다.
   - Codex: `CODEX_HOME`이 설정돼 있으면 그 디렉터리, 없으면 `~/.codex`. skill link는 그 아래 `skills/`에 만듭니다.
   - 설치는 쓴 실제 경로를 설치 기록에 남깁니다. `uninstall`과 `check`는 기록한 경로를 씁니다. 설치 뒤 환경 변수가 바뀌어도 기록한 경로를 씁니다.
   - 위 2절 표의 `~/.claude/skills/…`, `~/.codex/skills/…`는 변수가 없을 때의 기본 경로입니다.
8. **옛 개발 checkout을 가리키는 진입점 link를 명시 옵션으로 넘겨받습니다.** 이 workstation은 shim 셋과 skill link가 agent 저장소의 개발 checkout을 가리킵니다(DIST-001 6단계 전환). 옵션 `install --adopt-dev-links CHECKOUT`을 줄 때만 규칙 1의 거절 대신 아래를 합니다. `CHECKOUT`은 옛 checkout의 root이며 사용자가 정합니다. 옵션이 없으면 규칙 1대로 전체를 거절합니다.
   - 넘겨받는 조건은 모두 맞아야 합니다. 하나라도 다르면 그 경로는 충돌이고 전체를 거절합니다(규칙 1).
     - 그 경로가 symlink이고 소유자가 현재 사용자입니다.
     - link의 글자(`readlink`)가 알려진 모양으로 끝납니다. 세 CLI는 `<checkout>/codex/tools/<도구>/bin/<도구>`, 두 skill은 `<checkout>/codex/skills/<이름>`입니다. 상대 경로 글자(`../../codex/skills/<이름>`)도 같은 모양입니다.
     - link가 가리키는 곳이 `CHECKOUT`의 그 알려진 경로와 같은 파일입니다(상대 글자는 link가 실제로 놓인 디렉터리 기준으로 풉니다). 그래서 서로 다른 checkout을 가리키는 link, 모양이 다른 link, 다른 사용자 소유 link는 거절됩니다.
   - 교체는 임시 link를 만든 뒤 rename하는 한 번의 원자적 교체입니다. 관찰자가 진입점이 없거나 끊어진 것을 보지 못합니다. 설치 기록의 그 항목에 이전 글자를 `adopted_from`으로 적습니다(읽을 때 같은 알려진 모양으로 끝나지 않으면 기록 전체를 거절합니다. 원칙 A).
   - 부모 디렉터리가 symlink이면(규칙 4) link는 가리키는 디렉터리 안에서 바뀝니다. 이 workstation의 `~/.claude/skills`는 개발 checkout의 `claude/skills`이므로, 그 안의 link 파일이 바뀝니다. 출력은 실제 위치를 함께 알립니다.
   - `uninstall`은 넘겨받은 진입점을 지우지 않고 `adopted_from`의 글자로 원자적으로 되돌립니다. 지금도 설치기가 만든 link(대상이 기록과 같음)일 때만 되돌리고, 사용자가 바꿨다면 건드리지 않고 알립니다(T12). 되돌림은 release와 `current`를 지우기 전에 합니다. 그래서 제거 도중에도 진입점이 끊어지지 않습니다. 설치 전 상태와 byte 단위로 같아집니다. 규칙 6의 runtime link는 되돌리지 않고 지웁니다(runtime이 다시 만듭니다).
   - `upgrade`·`rollback`은 이 link를 바꾸지 않습니다(7절). 이 옵션은 `install`에만 있습니다. 이 옵션을 쓰는 실행은 격리 HOME의 test(T24~T28)로 검증하며, 이 workstation에서 실제로 실행하는 일은 agent DIST-001 6단계가 합니다.

## 3. 설치가 고치는 기존 파일은 하나뿐입니다

고치는 파일은 사용자 tmux 설정입니다. 넣는 내용은 시작·끝 표시가 있는 블록 하나입니다.

```
<이전 내용 바로 뒤에 줄바꿈 하나>
# >>> project-agent (managed block, do not edit) >>>
source-file -q ~/.local/lib/project-agent/tmux.conf
# <<< project-agent <<<
```

표시 줄은 위 세 줄의 글자 그대로입니다(설치기가 `~/.local/lib/project-agent/tmux.conf`를 `~` 그대로 적습니다). 블록은 첫 줄의 줄바꿈 하나를 포함합니다. 파일이 없어 새로 만들 때도 같은 블록을 씁니다(파일은 그 줄바꿈으로 시작합니다). 그래야 원본이 줄바꿈으로 끝나지 않아도 제거가 byte 단위로 되돌립니다.

| 상황 | 동작 |
| --- | --- |
| 대상 선택 | `~/.tmux.conf`가 있으면 그 파일입니다. 없고 `~/.config/tmux/tmux.conf`가 있으면 그 파일입니다. 둘 다 있으면 `~/.tmux.conf`입니다(tmux가 읽는 순서와 같습니다). |
| 둘 다 없음 | 블록만 담은 `~/.tmux.conf`를 만듭니다. 설치 기록에 `created: true`로 남깁니다. `~/.config/tmux/`는 만들지 않습니다. |
| 블록이 이미 있음 | 파일을 바꾸지 않습니다. 그 블록을 설치기가 넣지 않았다면, 제거도 그 블록을 지우지 않습니다. |
| 블록을 넣음 | 고치기 전에 원본을 `backup/`에 원본과 같은 권한으로 둡니다. 파일 이름은 `<UTC 시각>-<원본 파일 이름>`입니다. |
| 대상이 symlink이거나, 파일이 hard link가 여럿(`st_nlink > 1`)이거나, 소유자가 현재 사용자가 아니거나, 쓰기 권한이 없거나(읽기 전용), ACL·확장 속성이 있거나, 1 MiB를 넘음 | 파일도 link 대상도 고치지 않습니다(rename으로 바꾸면 다른 이름의 같은 파일과 갈라지거나 소유자·ACL·읽기 전용 표시를 잃기 때문입니다). 그 사실과 사용자가 넣을 줄을 출력합니다. 나머지 설치는 계속합니다. 종료 코드는 0입니다. `check`는 이 상태에서 기록된 파일을 link를 따라 읽기 전용으로 열어, 주석이 아닌 줄에 넣을 줄이 없거나 파일을 읽을 수 없을 때만 "수동 연결 필요"로 알립니다(실패가 아닙니다). 줄이 이미 있으면 알리지 않습니다. |
| 실행 중인 tmux server | 다시 읽히지 않습니다. 설치는 다시 읽는 명령 `tmux source-file ~/.local/lib/project-agent/tmux.conf`만 출력합니다. 사용자의 전체 설정을 다시 읽는 명령은 권하지 않습니다. |
| `upgrade`·`rollback` | 블록을 다시 고치지 않습니다. `current`만 바뀌기 때문입니다. |
| `uninstall` | 설치기가 넣은 표시된 블록(앞의 줄바꿈 포함)만 지웁니다. `created: true`이고 지운 뒤 내용이 없으면 파일도 지웁니다. |

보장: 설치 뒤 사용자가 블록 밖을 고치지 않았다면, 제거 뒤 파일은 설치 전과 byte 단위로 같습니다. 설치 전에 파일이 없었다면 제거 뒤에도 없습니다.

### 3.1 통합 파일이 server에 넣는 binding

tmux 통합 파일은 읽힐 때 tmux server에 binding과 hook을 넣습니다([5.3](#53-tmux-server)). 사용자가 정한 binding은 덮어쓰지 않습니다. 구현은 [project_agent_bind.sh](../../integrations/tmux/project_agent_bind.sh)입니다(tmux 설정 문법은 `list-keys`로 판정할 수 없어 통합 파일이 이 helper를 부릅니다).

1. `prefix B`와 root table의 `MouseDown1Pane`은 비어 있거나 tmux 기본값일 때만 binding합니다. 그 밖의 binding이 있으면 건너뜁니다. 제품이 이미 넣은 binding(명령이 `tmux_project_board.sh`를 부름)은 사용자 binding이 아니므로 다시 읽으면 같은 결과로 바뀝니다. tmux 3.8 기준으로 `prefix B`는 기본 binding이 없고, `MouseDown1Pane`의 기본값은 `select-pane -t = \; send-keys -M`입니다.
2. Board 키는 사용자가 바꿀 수 있습니다. 통합 파일을 읽기 전에 tmux option `@project_agent_board_key`를 설정하면 그 키를 씁니다. 없으면 `B`입니다.
3. 건너뛴 binding은 `check`가 "binding 건너뜀"으로 알립니다. 어느 키를 건너뛰었는지 함께 알립니다. 실패가 아닙니다. 건너뛴 키는 server option `@project_agent_board_skipped`가 `<table>:<key>` 단어를 공백으로 이어 담습니다(예: `prefix:B root:MouseDown1Pane`). 건너뛴 키가 없으면 빈 값입니다. 통합 파일을 읽을 때마다 다시 정해집니다.
4. 통합 파일이 넣은 binding과 hook은 `uninstall` 뒤에도 server가 끝날 때까지 남습니다. `uninstall`은 이를 되돌리는 명령을 출력합니다. 출력하는 명령은 `unbind-key`, 기본값이 있는 `MouseDown1Pane`의 기본값 복원, `set-hook -gu`·`set-hook -gwu`입니다. `set-hook -gwu 'pane-died[agent-session]'`은 통합 파일이 아니라 `agent-session`이 run을 띄울 때 넣는 hook의 되돌림입니다(5.3절). 대상은 5.3절 표의 목록이며, 건너뛴 키(`@project_agent_board_skipped`)는 되돌리지 않습니다. 사용자의 binding은 되돌림 대상이 아닙니다.
5. 설치기는 이 명령을 실행하지 않습니다. 실행 중인 server를 바꾸지 않는 원칙은 3절의 "실행 중인 tmux server" 행과 같습니다.

### 3.2 tmux 최소 버전

최소 버전: tmux 3.8

통합 파일의 본체(`integrations/tmux/project-agent-main.conf`)는 tmux 3.8 이상에서만 읽힙니다. 이름 붙은 hook index(`client-attached[project-agent]`)가 3.8에서 동작하고, 이 host에서 실행해 본 2.7(`{ }` 명령 블록을 읽지 못함)과 3.6a(이름 붙은 hook index를 받지 못함)에서는 동작하지 않기 때문입니다. 3.6a와 3.8 사이(3.7 계열)는 이 host에 없어 검증하지 않았으므로 지원하지 않습니다. 근거 표는 CR TMUX-002의 Result입니다. 이 값을 안내하는 문서(안내문 1절)는 이 절을 link하고 값을 다시 쓰지 않습니다.

`agent-session`도 같은 최소 버전을 요구합니다. run을 띄울 때 server 전체 hook `pane-died[agent-session]`(이름 붙은 hook index, 5.3절)을 쓰기 때문입니다. `start`·`restart`·`resume`은 시작 전에, 실행 중인 server의 `#{version}`(server가 없으면 PATH의 첫 `tmux -V`)을 최소 버전과 비교합니다. 낮으면 JSON 오류 `tmux_too_old`(종료 코드 5)로 거절하고 아무것도 만들지 않습니다. 오류의 message와 details는 이 tmux의 버전, 최소 버전, 사내 tmux 경로(`/primehome/tools/Inhouse/tmux/latest/bin`을 PATH 앞에 둠)를 담습니다. `stop`·`send` 등은 hook이 필요 없어 낮은 tmux에서도 동작합니다. 최소 버전의 값은 아래 3항의 한 원본(`project-agent.conf`)에서 읽으며, 이 파일이 없는 tree(원격 runtime의 bundle)에서는 검사하지 않습니다.

1. **판정은 tmux가 읽는 첫 파일이 합니다.** `tmux.conf`(2절의 고정 파일)가 읽는 `project-agent.conf`는 tmux 2.x도 parse하는 문법만 씁니다. 실행 중인 tmux의 `#{version}`을 최소 버전과 비교해, 최소 버전 이상이면 `source-file -F`로 본체를 읽고 아니면 읽지 않습니다. 고정 파일은 바뀌지 않으므로 이미 설치한 사람도 release를 갱신하면(`upgrade`) 적용됩니다.
2. **최소 버전보다 낮은 tmux가 설정을 읽으면** parse 오류 대신 오류 한 줄을 냅니다. 한 줄은 최소 버전과 사내 tmux 경로(`/primehome/tools/Inhouse/tmux/latest/bin`을 PATH 앞에 둠)를 담고, tmux가 설정 오류를 첫 client에 보이는 방식으로 보입니다. binding·hook과 `@project_agent_*` option은 남지 않습니다.
3. **코드의 원본**은 `project-agent.conf`의 `set-option -g @project_agent_tmux_min '<버전>'` 한 줄입니다. 판정이 이 값을 쓰고(읽은 뒤 option은 지웁니다), 설치기 `check`·`install`이 같은 줄을 읽습니다. 이 절의 "최소 버전" 줄과 같은지는 `install/tests`가 검사합니다. 3.8 이상이면 `#{version}`이 `3.8`, `3.6a`, `next-3.9`처럼 `major.minor`로 시작하는 문자열이고, 그렇지 않은 tmux(`master`, 빈 값)는 낮은 것으로 봅니다.
4. 설치기는 PATH에서 처음 찾은 `tmux`의 `-V`를 최소 버전과 비교합니다. `install`은 낮으면 같은 사실과 해소 방법을 안내하고 설치는 진행합니다. `check`는 실패(종료 코드 1)로 알립니다(7절). PATH에 `tmux`가 없으면 `check`·`install`은 안내만 하고 실패가 아닙니다. 설치기는 PATH를 고치지 않습니다(4절).

## 4. 설치가 절대 건드리지 않는 것

- Claude·Codex 설정 파일: `settings.json`, `config.toml`, `.claude.json`. 실행 중의 신뢰 기록은 5절이 따로 다룹니다.
- `CLAUDE.md`, `AGENTS.md`, 이 계약의 2절에 없는 다른 skill
- shell rc와 PATH. `~/.local/bin`이 PATH에 없으면 안내만 출력합니다.
- 전역 Python package. Board의 외부 package(`textual`)는 설치하지 않습니다. 설치 interpreter에 있어야 하며 `check`가 안내합니다(7절).
- 등록 project의 저장소: `.gitignore`, `.git/info/exclude`, git 설정, project 안의 어떤 파일도 고치지 않습니다. base의 `agent/` 아래 untracked 파일에 대한 안내는 9.1절이 정합니다.
- 위 3절의 한 파일을 뺀 모든 기존 파일. 읽기만 해도 되는 파일은 예외 없이 내용·권한·mtime이 같아야 합니다.

## 5. 실행 중 쓰기 목록

설치가 아니라 제품이 실행 중에 쓰는 위치입니다. 2026-11-09에 코드에서 확인한 사실만 적습니다. 확인하지 못한 것은 **(미확인)**으로 남깁니다.

찾은 방법(재현용): 쓰기 호출 검색과 경로 검색을 `tools/{agent-session,project-item,project-board}`와 `integrations/tmux`에서 했습니다.

```sh
grep -rnE 'write_text|write_bytes|\.open\(|\bopen\(|os\.replace|os\.rename|\.rename\(|shutil\.|mkdir|makedirs|symlink|unlink|rmtree|os\.remove|\.touch\(|chmod|mkstemp|NamedTemporary|TemporaryDirectory|tempfile|fcntl|os\.link|copy2|copyfile|copytree|os\.write|O_CREAT' \
    tools/agent-session tools/project-item tools/project-board --include='*.py' | grep -v /tests/
grep -rnE 'Path\.home|expanduser|XDG|"HOME"|~/|\.cache|/tmp' tools integrations/tmux --include='*.py' --include='*.sh' | grep -v /tests/
grep -rnE '"(new-session|new-window|set-option|set-hook|bind-key|rename-window|kill-window|respawn-pane|send-keys|run-shell|display-message|split-window)"' \
    tools --include='*.py' | grep -v /tests/
```

**범위** 열: "등록"은 등록 파일이 가리키는 경로(base, seat, `path_cr`, `path_decide`)에 한정된다는 뜻입니다. "HOME"은 등록과 무관하게 사용자 HOME 안의 고정 위치입니다. "tmux"는 tmux server의 상태입니다. "tmp"는 HOME 밖의 `/tmp`입니다.

### 5.1 사용자 HOME의 고정 위치

| 위치 | 언제 | 무엇을 쓰는가 | 범위 | 근거 |
| --- | --- | --- | --- | --- |
| `~/.claude.json` (`CLAUDE_CONFIG_DIR`가 있으면 그 디렉터리의 `.claude.json`) | Claude project에서 `start`가 새 seat를 clone했을 때만 | `projects.<seat 절대 경로>.hasTrustDialogAccepted = true` 한 항목. 파일이 없으면 쓰지 않습니다. 이미 true면 쓰지 않습니다. 잠금 디렉터리 `.claude.json.lock`과 임시 파일 `.claude.json.agent-session-<pid>`를 만들고 끝나면 지웁니다. 파일이 symlink면 가리키는 파일을 고칩니다(`resolve()`). | 등록(seat 경로). 새로 clone한 로컬 seat만. Claude Leader의 base에는 쓰지 않습니다. | [claude.py:143-190](../../tools/agent-session/agent_session/providers/claude.py), 호출 [lifecycle.py:535-536](../../tools/agent-session/agent_session/lifecycle.py) → [claude.py:244-246](../../tools/agent-session/agent_session/providers/claude.py) |
| `~/.codex/config.toml` (`CODEX_HOME`가 있으면 그 디렉터리) | Codex project에서 (a) Leader를 시작할 때마다, (b) `start`가 새 로컬 seat를 clone했을 때, (c) 원격 host에서 seat를 clone했을 때 | `[projects."<절대 경로>"]`에 `trust_level = "trusted"`. 이미 trusted면 쓰지 않습니다. **디렉터리 `~/.codex/`와 `config.toml`이 없으면 만듭니다.** 잠금 디렉터리 `config.toml.agent-session.lock`과 임시 파일을 만들고 끝나면 지웁니다. symlink면 가리키는 파일을 고칩니다. | 등록(base 또는 seat 경로) | [codex.py:35-113](../../tools/agent-session/agent_session/providers/codex.py), 호출 [launch_artifacts.py:101-102](../../tools/agent-session/agent_session/launch_artifacts.py), [lifecycle.py:535-536](../../tools/agent-session/agent_session/lifecycle.py), [remote_runtime.py:299-300](../../tools/agent-session/agent_session/remote_runtime.py) |
| `~/.cache/project-item/locks/<hash>.lock` | `project-item`의 `new`·`move`·`record`·`render` 등 item root를 쓰는 모든 명령 | 잠금 파일(내용 없음). 만든 뒤에 지우지 않습니다. `<hash>`는 item root 경로의 해시입니다. | 등록(`path_cr`, `path_decide`)에서 계산한 이름 | [store.py:19-31](../../tools/project-item/project_item/store.py) |
| `~/.cache/tmux-decide-status.json`, `.lock`, `tmux-decide-status.view`, `.<pid>.tmp` (`XDG_CACHE_HOME`가 있으면 그 아래) | tmux status가 `tmux_decide_status.sh`(`tmux_decide_status.py`)를 부를 때. 사용자가 status 설정에 이 script를 넣은 경우만 | 열린 결정 ID 목록과 잠금. `.view`는 상태줄에 낼 문구와 그 문구가 유효한 마지막 epoch 초(캐시 mtime + `CACHE_TTL`)입니다. 캐시가 유효한 동안 `tmux_decide_status.sh`가 이 파일만 읽고 Python을 띄우지 않습니다. 새 결정이 생기면 모든 tmux client에 `display-message`와, Leader window의 pane tty에 BEL(0x07)을 씁니다. | 등록(project마다 `path_decide`를 읽음) | [tmux_decide_status.py `cache_path`·`write_view`·`refresh`](../../integrations/tmux/tmux_decide_status.py), 알림 같은 파일 `alarm`, 읽는 쪽 [tmux_decide_status.sh](../../integrations/tmux/tmux_decide_status.sh) |
| (원격 host의 HOME) `~/.cache/agent-session/runs/<run>/`, `~/.cache/agent-session/runtime/<hash>/`와 `.lock`, `~/.cache/agent-session/skills.json`·`skills.lock` | Codex SSH Worker seat를 쓰는 원격 host에서만 | run 기록, 받은 실행본 압축 해제, skill 소유 기록. 이 host에서는 일어나지 않습니다. | 원격 host의 HOME | [remote_runtime.py:17-20, 46-94, 171-214](../../tools/agent-session/agent_session/remote_runtime.py), [remote.py:15-29](../../tools/agent-session/agent_session/remote.py) |
| (원격 host의 HOME) `~/.codex/skills/project-team`, `~/.codex/skills/project-item` | 같은 원격 host에서 run을 시작할 때. 그 host에 `~/.local/lib/project-agent/install.json`이 있으면 쓰지 않습니다(DIST-003). | 위 실행본의 `guidance/skills/<이름>`을 가리키는 symlink. 이름이 이미 있고 이 runtime이 만든 것이 아니면 건드리지 않습니다. `~/.codex/skills/`가 없으면 만듭니다. | 원격 host의 HOME. **2절의 설치 대상과 같은 이름입니다(2절 규칙 6).** | [remote_runtime.py:46-94](../../tools/agent-session/agent_session/remote_runtime.py) |

읽기만 하는 HOME 위치(쓰지 않음): `~/.claude/projects/`([claude.py:104](../../tools/agent-session/agent_session/providers/claude.py)), `~/.claude/settings.json`([claude.py:279](../../tools/agent-session/agent_session/providers/claude.py)), `~/.claude/sessions/`([registry.py:79-97](../../tools/project-item/project_item/registry.py)), `~/.codex/<profile>.config.toml`([codex.py:327-328](../../tools/agent-session/agent_session/providers/codex.py)), 등록 파일.

### 5.2 등록 project 안

`<base>`는 등록된 base 경로입니다. 아래는 모두 등록 경로 아래입니다.

| 위치 | 언제 | 무엇을 쓰는가 | 범위 | 근거 |
| --- | --- | --- | --- | --- |
| `<base>/agent/state.json`, `state.lock` | 모든 배정·제어 명령 | slot별 배정 state(원자적 교체) | 등록(base) | [state.py:176-231](../../tools/agent-session/agent_session/state.py) |
| `<base>/agent/suspend.json`, `suspend.lock` | `shutdown`·`resume` | shutdown 기록 | 등록(base) | [suspend.py:65-66, 92-95](../../tools/agent-session/agent_session/suspend.py) |
| `<base>/agent/allocation.lock`, `agent/control/<slot>.lock` | `start`·`stop`·`restart`·`send` | 잠금 파일 | 등록(base) | [lifecycle.py:73, 345, 494, 524](../../tools/agent-session/agent_session/lifecycle.py) |
| `<base>/agent/runs/<run_id>/` | run을 시작할 때, stop·restart를 예약할 때 | `prompt.md`, Claude의 `settings.json`(hook 선언), `launch.sh`, `controller.sh`, `control-request.json`, `control-result.json`. 원격 seat는 `bridge.json`도 씁니다. 모든 명령에 **release의 절대 경로**와 python 경로가 들어갑니다. | 등록(base) | [launch_artifacts.py:80-89, 104, 137-152](../../tools/agent-session/agent_session/launch_artifacts.py), [lifecycle.py:864-866](../../tools/agent-session/agent_session/lifecycle.py), [internal.py:234-265](../../tools/agent-session/agent_session/internal.py), [remote_bridge.py:53-74](../../tools/agent-session/agent_session/remote_bridge.py) |
| `<base>/agent/diagnostics/<시각>-<명령>-<pid>.log` | 명령이 내부 오류로 끝났을 때 | traceback | 등록(base) | [cli.py:126-137](../../tools/agent-session/agent_session/cli.py) |
| `<base>/agent/handoff/<slot>.md` | 원격 seat의 restart 검증 때 중앙 사본을 씁니다. 로컬 slot의 파일은 대화가 씁니다(제품 코드가 아닙니다). | 인계 문서 | 등록(base) | [handoff.py:15-28](../../tools/agent-session/agent_session/handoff.py) |
| `path_decide/decide.html` (`render --out`이 있으면 그 경로) | `project-item`이 결정을 바꿀 때마다 | 결정 목록 page(원자적 교체) | 등록(`path_decide`) | [render.py:246-258](../../tools/project-item/project_item/render.py), [cli.py:46-47](../../tools/project-item/project_item/cli.py) |
| `path_cr`·`path_decide`의 item 파일 | `new`·`move`·`record`·`accept`·`answer`, `start`의 배정(`todo`→`in-progress`), Base header 기록, 원격 Worker의 Result 보고 | item 파일 생성(`O_EXCL`), 본문 수정, 상태 디렉터리 사이 이동(git이 추적하면 `git mv`) | 등록(`path_cr`, `path_decide`) | [store.py:131-134, 196, 291-303](../../tools/project-item/project_item/store.py), [assign.py:48-67](../../tools/project-item/project_item/assign.py), [remote_bridge.py:46](../../tools/agent-session/agent_session/remote_bridge.py), 답변 [answer.py:108](../../tools/project-board/project_board/answer.py) |
| base·seat의 git 작업 트리 | `start`가 Worker를 배정할 때 | `fetch origin main`, `switch --detach <origin/main>`, `branch --force main`, `branch cr/<ID>`, `symbolic-ref HEAD`, `submodule update --init --recursive`. 작업 트리와 ref를 바꿉니다. | 등록(base, seat) | [git_ops.py:118-169, 218-223](../../tools/agent-session/agent_session/git_ops.py) |
| 새 seat 디렉터리 | seat 경로가 없을 때 `start`가 | 새 디렉터리 하나를 만들고 base의 origin을 clone합니다. clone이 실패하면 그 디렉터리만 지웁니다. | 등록(seat 경로) | [workspace.py:15-49](../../tools/agent-session/agent_session/workspace.py) |

### 5.3 tmux server

두 도구가 tmux server(사용자의 기본 server 또는 `--socket`)의 상태를 바꿉니다. 이 상태는 server가 끝나면 사라집니다.

| 대상 | 언제 | 무엇을 하는가 | 근거 |
| --- | --- | --- | --- |
| session | project의 첫 run을 만들 때 | `new-session -d -s <project>`와 session option `@agent_session_owner`. 이미 있는 session은 owner가 같을 때만 씁니다. | [tmux.py:200-220](../../tools/agent-session/agent_session/tmux.py) |
| window·pane | run마다 | `new-window`, `rename-window`, `select-window`, `respawn-pane`, `kill-window`, `send-keys`(`/exit`, `Enter`) | [tmux.py:209, 266, 447, 525, 542, 563-569](../../tools/agent-session/agent_session/tmux.py), [windows.py:37, 64](../../tools/agent-session/agent_session/windows.py) |
| window option | run마다 | `remain-on-exit on`과 `@agent_session_*`(run 식별, 현재 run 포인터) | [tmux.py:220, 274-277, 345, 361, 412](../../tools/agent-session/agent_session/tmux.py) |
| 알림 | shutdown 등 | 모든 client에 `display-message`, pane tty에 BEL | [tmux.py:458, 470-474](../../tools/agent-session/agent_session/tmux.py) |
| `run-shell -b` | stop·restart 예약, Board popup | controller script 실행, `display-popup`. 둘 다 `quiet_shell`로 감싸 pane에 아무것도 남기지 않습니다(아래 규칙). Board popup이 실패하면 연 client에 5초 알립니다. | [tmux.py `run_quiet`·`run_controller`](../../tools/agent-session/agent_session/tmux.py), [tmux_control.py `_popup`](../../tools/project-board/project_board/tmux_control.py) |
| Board option | Board를 켜고 끌 때, 크기를 바꿀 때 | server option `@project_board_enabled`, `@project_board_config`, `@project_board_width`, `@project_board_expanded`, window option `@project_board_pane`, `@project_board_restore`, `@project_board_seen`(client가 그 window를 마지막으로 보인 시각), pane option `@project_board_managed`, `@project_board_click_socket`, `@project_board_ready`(TUI가 SIGUSR1 handler를 설치한 뒤 1), `@project_board_visible`(client가 그 pane의 window를 보이면 1) | [tmux_control.py:146, 182-208, 233-237, 289-352](../../tools/project-board/project_board/tmux_control.py) |
| Board pane | Board가 켜져 있을 때, client가 처음 보는 window마다 | `split-window`로 사이드바 pane을 추가합니다. Board를 끄거나 그 window의 관리 pane이 끝날 때까지 유지하되, 동시에 유지하는 pane은 8개까지입니다(`tmux_control.MAX_KEPT`). 9번째를 만들 때 어느 client도 보이지 않는 window 중 `@project_board_seen`이 가장 오래된 것의 pane을 제거합니다. 근거: Board process 하나의 RSS가 약 50 MB이므로 8개는 최대 약 400 MB이고, 보이지 않는 pane은 읽지 않으므로 CPU는 들지 않습니다(BOARD-002 실측). 보이지 않는 pane은 갱신을 멈춥니다. 같은 hook이 `project_board_visibility.sh`(plain sh)를 실행해 pane의 `@project_board_visible`을 고치고, 상태가 바뀌었고 `@project_board_ready`인 pane에 SIGUSR1을 보냅니다. pane은 tmux에 자기 window가 보이는지 묻고 읽기를 멈추거나, 보이게 되면 곧바로 한 번 읽습니다. | [tmux_control.py:218-250](../../tools/project-board/project_board/tmux_control.py) |
| 통합 파일의 binding (`source-file`로 읽힐 때. 규칙은 3.1절, 최소 버전은 3.2절) | tmux 설정을 읽을 때 | prefix table의 Board 키(`@project_agent_board_key`, 없으면 `B`)와 root table의 `MouseDown1Pane`. 제품 binding은 명령에 `tmux_project_board.sh`가 들어 있습니다. `MouseDown1Pane`을 되돌리는 기본값은 `select-pane -t = \; send-keys -M`입니다. Board 키 binding은 `key`, Board pane의 click binding은 `drop` 방식으로 `project_agent_run.sh`를 거칩니다(아래 `run-shell` 규칙). | [project_agent_bind.sh](../../integrations/tmux/project_agent_bind.sh), [project-agent-main.conf](../../integrations/tmux/project-agent-main.conf) |
| 통합 파일의 hook | tmux 설정을 읽을 때 | 이름이 `[project-agent]`인 hook 8개. 앞의 6개(`client-attached`, `client-detached`, `client-session-changed`, `session-window-changed`, `window-created`, `window-closed`)는 `@project_agent_sync_needed` format이 참일 때만 `sync`를 실행합니다. 이미 Board pane이 있고 저장한 폭인 window로 옮길 때는 Python process를 시작하지 않습니다. 이 6개는 Board가 켜져 있으면 `sync` 조건과 별개로 `project_board_visibility.sh`도 실행합니다(위 Board pane 행). session scope(`set-hook -g`로 넣고 `set-hook -gu '<event>[project-agent]'`로 지움) 5개: `client-attached`, `client-detached`, `client-session-changed`, `session-window-changed`, `after-resize-pane`. window scope(`set-hook -gw`로 보이고 `set-hook -gwu`로 지움) 3개: `window-created`, `window-closed`, `pane-died`. 같은 이름의 항목만 바뀌고 사용자 hook은 그대로입니다. `run-shell` 작업은 모두 `hook` 방식으로 `project_agent_run.sh`를 거칩니다(아래 규칙). | [project-agent-main.conf](../../integrations/tmux/project-agent-main.conf) |
| `agent-session`의 hook | run을 띄울 때마다(`start`·`restart`·`resume`·Worker 배정). 같은 값을 다시 씁니다 | server 전체 hook 요소 `pane-died[agent-session]`(`set-hook -g`로 넣고 `set-hook -gwu 'pane-died[agent-session]'`로 지움) 하나. 관리 window의 pane이 끝날 때만 `python -m agent_session.internal finish-ended`를 `run-shell -b`로 실행합니다(스스로 끝난 run의 마무리, [동작 명세 3절](spec.md#스스로-끝난-run의-마무리)). 이 작업도 `quiet_shell`로 감싸 출력·종료 상태를 pane에 남기지 않고, 실패는 `@project_agent_last_error`에 기록합니다. 사용자 hook과 `[project-agent]` hook은 그대로입니다. 최소 버전은 3.2절입니다. `uninstall` 뒤에도 server가 끝날 때까지 남고 3.1절 4항의 명령으로 지웁니다. | [tmux.py `install_exit_hook`](../../tools/agent-session/agent_session/tmux.py) |
| 통합 파일의 server option | tmux 설정을 읽을 때 | `@project_agent_tmux_dir`: 통합 파일을 읽은 디렉터리입니다. 설치본은 `current` link를 풀지 않은 경로입니다. binding·hook·`@project_agent_decide_status`가 이 경로의 helper를 부릅니다. `@project_agent_board_skipped`: 3.1절의 건너뛴 키입니다. `@project_agent_last_error`: `project_agent_run.sh`와 도구의 `quiet_shell`이 실패를 남기는 한 줄입니다(아래 규칙). `@project_agent_decide_status`: 결정 대기 표시 조각입니다(아래). `@project_agent_sync_needed`: 위 hook이 `sync`를 시작할 조건의 tmux format입니다. 판정 파일은 최소 버전을 `@project_agent_tmux_min`에 잠시 두었다가 지웁니다(3.2절). | [project-agent-main.conf](../../integrations/tmux/project-agent-main.conf), [project-agent.conf](../../integrations/tmux/project-agent.conf), [project_agent_bind.sh](../../integrations/tmux/project_agent_bind.sh) |

통합 파일의 `run-shell` 규칙(BOARD-006·BOARD-010). tmux는 `run-shell` 작업의 출력과 0이 아닌 종료 상태를 그때의 활성 pane, 곧 사용자의 작업 pane에 view mode로 보입니다. 그래서 통합 파일(`integrations/tmux/*.conf`·`*.sh`)의 shell 작업(`run-shell`·`run-shell -b`)은 모두 [project_agent_run.sh](../../integrations/tmux/project_agent_run.sh) `<방식> <socket> <명령>`을 거칩니다. 이 script는 출력 없이 종료 코드 0으로 끝나며, 방식이 실패를 다룹니다. tmux 명령을 실행하는 `run-shell -C`는 pane에 보이지 않으므로 해당하지 않습니다.

| 방식 | 대상 | 실패하면 |
| --- | --- | --- |
| `hook` | tmux 이벤트가 부르는 작업(창 이동·client 이벤트의 `sync`·`project_board_visibility.sh`) | server option `@project_agent_last_error`에 `<날짜> <시각> <명령> failed (exit N): <출력 첫 줄>` 한 줄을 씁니다. 다음 실패가 바꿔 쓰므로 반복해도 늘지 않고 파일을 만들지 않습니다. 사용자는 `tmux show-options -gv @project_agent_last_error`로 봅니다. |
| `key` | 사용자가 누른 동작(Board 키 toggle)과 통합 파일을 읽을 때의 `project_agent_bind.sh` | 위와 같이 기록하고, 붙은 모든 client에 `display-message`로 5초 알립니다. pane을 덮지 않습니다. |
| `drop` | 실패가 정상 결과인 작업(항목이 없는 Board click) | 아무것도 남기지 않습니다. |

새 `run-shell`을 통합 파일에 더할 때 이 세 방식 중 하나를 고릅니다. 사용자가 자기 tmux 설정에서 Board를 부르는 binding(예: status line의 `Board` toggle)은 사용자 설정이 소유하며 통합 파일에 없습니다. 그 binding도 같은 방식으로 감쌀 수 있습니다. `integrations/tmux/test_project_agent_conf.py::test_every_run_shell_job_goes_through_the_run_script`가 통합 파일의 모든 shell `run-shell`이 규칙을 따르는지 검사합니다.

도구(`tools/**`)가 만드는 `run-shell`(위 표의 `agent-session` hook, stop·restart controller, Board popup)도 같은 규칙입니다(BOARD-011). 이 도구들은 `project_agent_run.sh`를 부를 수 없습니다. 원격 runtime의 bundle에 이 script가 없고, 원격 host의 tmux에도 hook을 넣기 때문입니다. 대신 `agent_session.tmux.quiet_shell`이 같은 규칙을 구현합니다. job의 출력을 버리고 종료 코드 0으로 끝나며, 실패하면 같은 option에 `<날짜> <시각> <이름> failed (exit N)`을 한 줄로 씁니다(`hook` 방식). 사람이 연 작업(Board popup)은 그 client에 `display-message`로 5초 알립니다(`key` 방식). 이름과 알림 문구만 다르고 규칙의 원본은 이 절입니다. 새 `run-shell`을 도구에 더할 때는 `Tmux.run_quiet`을 쓰거나 `quiet_shell`로 job을 만듭니다. `integrations/tmux/test_project_agent_conf.py::test_every_run_shell_the_product_makes_leaves_nothing_in_the_work_pane`이 `tools/**`·`integrations/**`의 모든 `run-shell` 작성 지점이 규칙을 따르는지 검사합니다. 같은 option 이름은 `test_the_error_record_of_the_tools_is_the_option_the_integration_writes`가 맞춥니다.

사용자 status 배치(`status-left`, `status-format[0]`, `MouseDown1Status`)는 통합 파일에 넣지 않습니다. 각자의 tmux 설정이 소유합니다(DIST-001 5단계). `project_board_home_status.conf`는 각 사용자의 tmux 설정 파일이며 제품에 넣지 않습니다.

결정 대기 표시는 server option `@project_agent_decide_status`가 `tmux_decide_status.sh`를 부르는 `#()` 조각으로 제공합니다. 이 wrapper가 6.1절의 launcher로 interpreter를 골라 `tmux_decide_status.py`를 실행하므로, 설치본에서는 `python.env`의 interpreter가 쓰입니다. 표시 형식은 바뀌지 않습니다. 사용자가 자기 status 설정에 한 줄을 넣어 씁니다. 경로를 알 필요가 없습니다.

```tmux
set-option -ag status-right '#{E:@project_agent_decide_status}'
```

### 5.4 HOME 밖

| 위치 | 언제 | 무엇을 하는가 | 근거 |
| --- | --- | --- | --- |
| `/tmp/project-board-<uid>-<tmux pid>/` (mode 0700), `control.lock`, `<16자>.sock` | Board를 켤 때 | 잠금 파일과 클릭 전달용 unix socket. Board pane이 끝나면 socket을 지웁니다. 디렉터리는 그 pid의 tmux server가 살아 있는 동안만 둡니다. `kill-server`·crash로 끝난 server의 디렉터리는 다음 Board 명령(어느 server의 것이든)이 `_private_dir`에서 지웁니다. 지우는 것은 이름이 형식에 맞고 현재 사용자 소유의 mode 0700 디렉터리(symlink 아님)이며 안에 `control.lock`·`<16자>.sock`만 있는 것입니다. pid가 없거나 tmux가 아니거나, tmux라도 디렉터리의 마지막 변경보다 늦게 시작했으면(pid 재사용) 끝난 server로 봅니다. | [tmux_control.py:84-200, 338](../../tools/project-board/project_board/tmux_control.py), [tui.py:196-223](../../tools/project-board/project_board/tui.py) |
| `/tmp/as-u-<uid>-<run>.sock` | 원격 seat의 SSH 연결 | bridge socket | [remote_bridge.py:63-64](../../tools/agent-session/agent_session/remote_bridge.py) |
| `/tmp/as-<uid>-<run>.sock` (원격 host) | 원격 seat run | 원격 tmux socket | [remote_runtime.py:212](../../tools/agent-session/agent_session/remote_runtime.py) |
| 시스템 임시 디렉터리 `project-board-*` | Board에서 결정 답변을 보낼 때 | 답변 본문 파일. 끝나면 지웁니다. | [answer.py:36-38](../../tools/project-board/project_board/answer.py) |

### 5.5 provider 쪽 부수 효과

- `start`가 Codex Leader·Worker를 시작할 때 Codex daemon이 꺼져 있으면 `codex app-server daemon start`를 실행합니다([codex.py:281-283](../../tools/agent-session/agent_session/providers/codex.py), [lifecycle.py:108](../../tools/agent-session/agent_session/lifecycle.py)). daemon이 Codex 쪽에 무엇을 쓰는지는 **(미확인)**입니다.
- 관리 대화가 `~/.claude`·`~/.codex` 아래에 쓰는 transcript와 설정은 provider가 소유합니다. 제품 코드의 쓰기가 아니므로 이 목록에 넣지 않습니다.

### 5.6 이 목록의 한계

- 위 검색은 `.py`와 tmux script만 봅니다. `bin/` 아래 shell launcher는 쓰기 호출이 없음을 읽어서 확인했습니다.
- 사용자가 `launch.args`로 provider에 넘기는 인자와 그 결과는 이 목록 밖입니다.
- Worker 대화가 seat 안에서 하는 작업(commit, push)은 제품 코드의 쓰기가 아닙니다.
- 인수 test가 이 표를 직접 검증하는지는 8절의 T19가 정합니다 .

## 6. 등록 파일

등록 파일의 형식은 [명세 2절](spec.md#2-등록과-프로젝트-선택)이 소유합니다. 이 절은 위치만 정합니다.

2단계(DIST-003) 전의 선택 규칙([config.py:62-85](../../tools/agent-session/agent_session/config.py)). 아래 계약이 이 규칙을 대체했습니다:

1. `--config`가 있으면 그 파일만 씁니다. `AGENT_SESSION_CONFIG`는 `current_project`가 같은 방식으로 씁니다.
2. 없으면 `~/.codex/project.json`과 `~/.claude/project.json` 중 있는 파일을 씁니다. 둘 다 있고 서로 다른 파일이면 `registry_ambiguous`로 거절합니다. 병합하지 않습니다.

계약: 후보에 제품 전용 위치를 더합니다.

1. `--config`, 환경 변수 `AGENT_SESSION_CONFIG`
2. 후보 셋: `~/.config/project-agent/project.json`, `~/.codex/project.json`, `~/.claude/project.json`. 있는 파일이 하나(또는 같은 파일의 여러 경로)면 그 파일을 씁니다. 서로 다른 파일이 둘 이상이면 지금처럼 `registry_ambiguous`로 거절합니다.
3. 셋 다 없으면 `registry_not_found`입니다. 오류 문구에 세 위치를 모두 적습니다.

설치의 등록 파일 초안은 후보 셋 중 어느 위치에도 파일이 없을 때만 만듭니다. 이 workstation은 기존 파일이 있으므로 초안을 만들지 않습니다. 후보 셋의 선택은 DIST-003이 `registry_path`에 넣었고, 오류 문구와 `--help`의 위치 안내도 같이 바꿨습니다([config.py `REGISTRY_LOCATIONS`](../../tools/agent-session/agent_session/config.py), [project-item cli.py](../../tools/project-item/project_item/cli.py), [registry.py](../../tools/project-item/project_item/registry.py)). 설치기의 초안 조건은 4단계가 구현합니다.

초안은 설치 뒤 사용자의 파일입니다. `upgrade`·`rollback`은 읽거나 고치지 않습니다. `uninstall`은 지우지 않습니다(7.2절).

### 6.1 Python 선택

세 CLI(`agent-session`, `project-item`, `project-board`)의 `bin/` 진입점과 tmux helper `integrations/tmux/tmux_decide_status.sh`는 같은 규칙을 씁니다. 규칙의 원본은 공용 launcher [`tools/python-launcher.sh`](../../tools/python-launcher.sh) 하나입니다. 진입점은 이 파일을 `source`하며, 도구 디렉터리(`tools/<도구>/`)의 부모에 있어야 합니다. release는 이 상대 배치를 유지합니다.

설치본은 아래 세 값을 환경 변수나 `python.env`로 정합니다. 설치기는 release에 `python.env`를 씁니다(shim은 `current`를 거치는 symlink라 값을 정하지 않습니다). tmux가 shim 없이 부르는 helper(`tmux_project_board.sh`, `tmux_decide_status.sh`)는 `python.env`로 같은 값을 얻습니다.

| 변수 | 뜻 | 없을 때 |
| --- | --- | --- |
| `PROJECT_AGENT_PYTHON` | 설치 때 고른 interpreter의 절대 경로. 값이 있으면 후보는 이것 하나입니다. 다른 interpreter로 되돌아가지 않습니다. | 개발 checkout 규칙: macOS는 `python3`, WSL은 `~/python/.venv/bin/python`만, 그 밖에는 `/primehome/tools/Inhouse/Python3/latest/bin/python3`, `~/python/.venv/bin/python`, `python3` 순서 |
| `PROJECT_AGENT_PYTHONPATH` | release 안 외부 package 디렉터리. `:`로 여럿을 이을 수 있습니다. `project-board`만 `PYTHONPATH`에 더합니다. 설치기는 외부 package를 넣지 않으므로 빈 값을 적습니다. | 더하지 않음 |
| `PROJECT_AGENT_LD_LIBRARY_PATH` | 설치 interpreter가 설치 때와 같은 interpreter(같은 `sys.prefix`)로 뜨는 데 필요한 library 디렉터리. `PROJECT_AGENT_PYTHON`을 쓸 때 launcher가 `LD_LIBRARY_PATH` 앞에 붙이고 export합니다. 필요 없으면 빈 값입니다. | 붙이지 않음. 개발 checkout 규칙의 `LD_LIBRARY_PATH`는 바뀌지 않습니다. |

`python.env`: 위치는 launcher와 같은 디렉터리, 곧 release의 `tools/python.env`입니다. 설치기가 release를 만들 때 씁니다. `PROJECT_AGENT_PYTHON`에는 설치기를 실행한 interpreter의 절대 경로를, `PROJECT_AGENT_PYTHONPATH`에는 빈 값을 적습니다(외부 package를 넣지 않습니다). `PROJECT_AGENT_LD_LIBRARY_PATH`와 `PROJECT_AGENT_PYTHON_PREFIX`는 아래 "설치 때의 interpreter 시험"이 정합니다. 개발 checkout에는 없고 root `.gitignore`가 commit을 막습니다.

- 형식: 한 줄에 `NAME=값` 하나. launcher가 읽는 이름은 `PROJECT_AGENT_PYTHON`, `PROJECT_AGENT_PYTHONPATH`, `PROJECT_AGENT_LD_LIBRARY_PATH` 셋뿐이며(`PROJECT_AGENT_PYTHON_PREFIX`는 `check`만 읽고 launcher는 무시합니다), 값은 따옴표 없이 줄 끝까지입니다(공백을 포함할 수 있습니다). 같은 이름이 여러 번 나오면 마지막 줄이 이깁니다.
- launcher는 파일을 shell로 `source`하지 않고 두 이름의 줄만 읽습니다. 다른 이름이나 shell 문법(`$(…)`, 백틱)을 가진 줄은 무시하고 실행하지 않으며, 값 안의 `$`·백틱도 그대로의 글자입니다.
- 우선순위: 환경 변수에 값이 있으면 환경 변수가 이깁니다(변수마다 따로 판단합니다. 빈 값은 없는 것으로 봅니다). 값이 없는 변수만 파일에서 읽습니다. 파일이 없으면 위 표의 "없을 때" 규칙입니다.
- `python.env`의 `PROJECT_AGENT_PYTHON`이 가리키는 interpreter가 없거나 실행할 수 없으면 아래 `python_unavailable`과 같이 끝납니다. 다른 interpreter로 되돌아가지 않습니다.

설치 때의 interpreter 시험: 설치기는 `PROJECT_AGENT_PYTHON`에 적을 interpreter(설치기를 실행한 interpreter)의 `sys.prefix`를 `PROJECT_AGENT_PYTHON_PREFIX`에 적습니다. 사내 Python은 자기 `lib`이 `LD_LIBRARY_PATH`에 없으면 시스템 libpython으로 떠서 다른 `sys.prefix`(`/usr`)가 되고 사내 site-packages가 보이지 않으므로, 설치기는 빈 환경(`PATH`만 있음)에서 그 interpreter를 실행해 `sys.prefix`를 시험합니다. 같으면 `PROJECT_AGENT_LD_LIBRARY_PATH`는 빈 값입니다. 다르면 `<sys.prefix>/lib`, 그다음 `sysconfig`의 `LIBDIR`을 `LD_LIBRARY_PATH`로 주어 시험하고 처음으로 같아지는 디렉터리를 적습니다. 어느 것으로도 같아지지 않으면 오류 `python_environment`로 아무것도 바꾸기 전에 설치를 거절합니다(종료 코드 3). 같은 interpreter라도 library 경로가 다르면 `PROJECT_AGENT_LD_LIBRARY_PATH`가 달라지므로 `upgrade`는 "다른 interpreter"로 판정합니다.

- `project-board`와 `project-item`은 `PYTHONNOUSERSITE=1`로 실행하므로, 사용자 site의 package는 보이지 않습니다. release의 package는 `PROJECT_AGENT_PYTHONPATH`로만 보입니다.
- 시동 비용(PERF-002): 표준 library만 쓰는 `agent-session`, `project-item`, `tmux_decide_status.sh`의 interpreter는 `-S`로 시작해 site 처리(site-packages, `.pth`, `sitecustomize`)를 하지 않습니다. `project-board`도 `sync`·`click`·`toggle`(tmux hook과 key. textual을 import하지 않음)은 `-S`로, TUI 명령은 site를 처리합니다(textual이 interpreter의 site-packages에 있습니다). `-E`·`-I`는 쓰지 않으므로 `PYTHON*` 환경 변수의 효과와 `PROJECT_AGENT_PYTHONPATH`는 그대로입니다. 진입 script는 `#!/bin/bash`로 시작하고(`/usr/bin/env bash`는 PATH의 모든 NFS 디렉터리를 찾습니다), 자기 위치를 `dirname`·두 번째 `readlink` 없이 구합니다. symlink로 부른 경우에만 `readlink -f`를 한 번 실행합니다.
- 시동 번들(PERF-003): 명령 하나가 하는 일은 수십 ms인데, 시동 시간의 대부분은 모듈 파일을 하나씩 여는 비용입니다. NFS에서는 파일 하나를 열고 닫는 데 수 ms가 들고(host load가 높으면 더 듭니다) CLI는 모듈을 100개 안팎 import합니다. 설치기는 release를 만들 때 세 도구의 모든 모듈과, 각 도구가 시동할 때 import하는 표준 library 모듈의 compile한 code를 한 파일 `tools/__pycache__/bundle.<cache tag>.pyc`에 씁니다([`bundle.py`](../../install/project_agent_install/bundle.py)). 이름이 bytecode 파일이라서 release 지문(원칙 B)은 이 파일을 `__pycache__`의 `.pyc`처럼 뺍니다. 세 CLI의 진입점(`project-board`는 `sync`·`click`·`toggle`만)은 launcher의 `project_agent_read_boot`로 [`tools/bundle_boot.py`](../../tools/bundle_boot.py)를 `-c` 프로그램 앞에 읽고, 첫 import 전에 `_project_agent_bundle`을 부릅니다. 이 reader는 파일을 한 번 열어 header(모듈 색인)만 읽고, 모듈을 import할 때 그 code를 읽습니다. 파일 형식은 `bundle_boot.py`의 머리말과 `bundle.write`가 함께 소유합니다.
    - 모듈의 `__file__`과 code의 파일 이름은 원래 source 파일입니다(release 안의 최종 경로, 표준 library는 interpreter의 경로). 번들에 없는 모듈은 원래 경로에서 찾습니다. 번들이 없거나(개발 checkout), 헤더의 magic·`sys.version`이 지금 interpreter와 다르거나(다른 build가 쓴 것), `-O`로 시작했거나, header가 깨졌으면 reader는 아무것도 하지 않고 일반 import가 맡습니다. 따라서 interpreter가 바뀐 release도 느릴 뿐 틀리지 않습니다.
    - release는 불변이라 번들이 source와 어긋나지 않습니다. 번들이 있으면 `PYTHONPATH`에 있는 사용자 module이 번들에 있는 표준 library module을 가리지 못합니다.
- 생성 명령의 시동(PERF-004): run을 시작할 때 생성하는 Python 명령(Claude의 등록 hook, `launch.sh`의 `mark_process`, `controller.sh`의 controller)은 `python -S -c "...from agent_session.internal import ..."`로 시작합니다. 표준 library만 쓰는 경로라 site 처리를 하지 않습니다. 이 명령에는 번들 reader를 앞에 읽는 진입 script가 없으므로, 번들은 [`agent_session/__init__.py`](../../tools/agent-session/agent_session/__init__.py)가 연결합니다. 패키지를 처음 import할 때 다른 모듈을 import하기 전에 `tools/bundle_boot.py`를 읽어 `_project_agent_bundle`을 부릅니다. 그래서 명령의 `-c` 프로그램과 인자(entry 이름, 인자 순서)는 그대로이고 hook마다 모듈 파일을 하나씩 여는 비용만 사라집니다. reader가 이미 설치되어 있으면(세 CLI의 진입점) 다시 설치하지 않고, `bundle_boot.py`가 없거나(원격 runtime의 복사본) 번들이 맞지 않으면(개발 checkout, 다른 interpreter) 일반 import로 동작합니다. 바뀐 명령은 새 run에만 적용되며, 떠 있는 run의 명령은 자기 release에 고정되어 그대로입니다.
- `PROJECT_AGENT_PYTHON`이 없거나 실행할 수 없는 파일이면 `agent-session`은 JSON 오류 `python_unavailable`(종료 코드 5)을, 버전이 3.10 미만이면 `python_version`을 출력합니다. `project-item`, `project-board`와 `tmux_decide_status.sh`는 stderr에 한 줄을 쓰고 종료 코드 5로 끝납니다.

## 7. 명령의 동작

설치기는 `install/project-agent-install <명령>`입니다(개발 checkout과 `current/install/` 양쪽). 표준 library만 씁니다. `install`·`upgrade`는 release로 만들 Git checkout을 `--source PATH`로 받고(기본: 설치기가 있는 checkout), `install`은 `--adopt-dev-links CHECKOUT`도 받으며(2절 규칙 8), 모든 명령은 `--json`으로 결과를 JSON 하나로 출력합니다. 종료 코드는 0 완료(할 일이 없는 경우 포함), 1 `check` 실패, 2 옵션 오류, 3 아무것도 바꾸기 전의 거절(충돌, 떠 있는 run, 없는 VERSION, 어긋난 설치 기록 등), 4 바꾸는 중 실패·중단입니다(`install`·`upgrade`·`rollback`은 되돌린 뒤, `uninstall`은 되돌리지 않고 다음 `uninstall`을 기다립니다. 규칙 5).

release 이름 `<version>-<hash>`: `<version>`은 원본 root의 `VERSION` 첫 줄(공백 제거, `[0-9A-Za-z][0-9A-Za-z._+~-]*`)이고 파일이 없거나 형식이 틀리면 거절합니다. `<hash>`는 원본 HEAD commit의 앞 12자입니다. release에 들어가는 파일이 commit과 다르면(수정됐거나 추적되지 않은 파일이 있으면) 거절합니다. 내용 해시로 이름을 짓지 않습니다. release에 넣지 않는 경로(test, `__pycache__`, `docs/cr`)의 변경은 거절 사유가 아닙니다. 같은 이름의 release가 이미 있으면 다시 만들지 않고 씁니다.

모든 명령은 `--dry-run`을 받습니다. `--dry-run`은 아무것도 만들지 않고 바뀔 경로를 모두 출력합니다. 출력과 실제 실행의 변경 목록이 같아야 합니다.

| 명령 | 만들거나 바꾸는 것 | 바꾸지 않는 것 |
| --- | --- | --- |
| `install` | 2절의 모든 경로, 3절의 tmux 블록, 설치 기록. `--adopt-dev-links`가 있으면 옛 개발 checkout의 link를 새로 만들지 않고 교체합니다. 이미 설치되어 있고 같은 release면 아무것도 바꾸지 않습니다. | 4절 |
| `upgrade` | 새 `releases/<version>-<hash>/`, `current` 교체, 설치 기록의 `previous`·`current` | shim, skill link, `tmux.conf`, tmux 블록, 등록 파일, 이전 release |
| `rollback` | `current`를 설치 기록의 `previous` release로 원자적으로 교체. 교체 전의 release를 새 `previous`로 적습니다 | 위와 같음. release를 지우지 않습니다. |
| `prune` | `current`·`previous`·떠 있는 run이 쓰는 release가 아닌 release 디렉터리와 그 설치 기록 항목(7.1.2절) | `current`, 그 밖의 모든 경로 |
| `uninstall` | 설치 기록에 있는 소유만 지웁니다(release 전체, `current`, `tmux.conf`, 설치 기록, `backup/`, shim, skill link). tmux 블록은 3절대로 지웁니다. 넘겨받은 개발 checkout link는 지우지 않고 이전 대상으로 되돌립니다(2절 규칙 8). 설치기가 만든 빈 디렉터리를 지웁니다. | 등록 파일, `<base>/agent/`, `~/.cache`의 잠금·cache, 5.1의 신뢰 기록. 지우지 않은 것은 경로를 출력합니다. |
| `check` | 읽기만 합니다. | 모든 것 |

`check`는 다음을 확인하고 실패하면 0이 아닌 코드로 끝납니다.

- 설치 기록의 모든 소유 경로가 있고, 종류와 link 대상이 기록과 같습니다.
- `current`가 존재하는 release를 가리키고, release 안의 진입점이 실행됩니다.
- tmux 블록이 기록된 파일에 있습니다. symlink 때문에 건너뛴 경우는 실패가 아니라 안내입니다.
- `~/.local/bin`이 PATH에 있습니다. 없으면 안내입니다(실패가 아닙니다).
- PATH에서 처음 찾은 `tmux`가 최소 버전(3.2절) 이상입니다. 낮으면 실패이고, 그 tmux의 버전과 경로, 최소 버전, 해소 방법(사내 tmux 경로를 PATH 앞에 둠)을 알립니다. PATH에 `tmux`가 없으면 안내입니다(실패가 아닙니다).
- 건너뛴 tmux binding이 있으면 "binding 건너뜀"으로 알립니다(3.1절). 실패가 아닙니다.
- release의 launcher로 설치 interpreter를 빈 환경(`PATH`만 있음. 사용자의 `LD_LIBRARY_PATH`가 library 경로의 누락을 가리지 않습니다)에서 실행해 `sys.prefix`가 `PROJECT_AGENT_PYTHON_PREFIX`(설치 때의 값)와 같은지 확인합니다. 다르거나 뜨지 않으면 실패이고, 실제 `sys.prefix`와 설치 때의 값을 알립니다.
- `project-board`가 쓰는 `textual`이 같은 방식으로 실행한 설치 interpreter에 `tools/project-board/requirements.txt`의 버전으로 있는지 안내합니다. 없거나 버전이 다르면 안내만 합니다(실패가 아닙니다).
- 사용자가 소유 경로를 다른 것으로 바꿨으면 그 경로를 알리고 `check`는 실패로 끝납니다(위 첫 항목). `upgrade`와 `uninstall`은 그런 경로를 바꾸거나 지우지 않고 알립니다. 원격 runtime의 skill link가 같은 규칙을 씁니다([remote_runtime.py:74-90](../../tools/agent-session/agent_session/remote_runtime.py)) .

### 7.1 떠 있는 run

release는 run의 hook·script가 쓰는 코드입니다. run을 시작할 때 `launch.sh`, `controller.sh`, Claude의 `settings.json`에 release의 **해석된 절대 경로**(symlink를 푼 경로)와 python 경로가 들어갑니다([launch_artifacts.py:23, 35, 123, 146](../../tools/agent-session/agent_session/launch_artifacts.py), [lifecycle.py:107](../../tools/agent-session/agent_session/lifecycle.py)).

1. `upgrade`와 `rollback`은 떠 있는 run에 영향을 주지 않습니다. 그 run은 시작된 release를 계속 씁니다. 새 run부터 `current`가 가리키는 release를 씁니다.
2. 설치기는 사용 중인 release를 지우지 않습니다. 사용 중이란, 등록된 project의 `<base>/agent/runs/*/`의 script에 그 release 경로가 있고 그 run이 끝나지 않았다는 뜻입니다.
3. `upgrade`는 이전 release를 지우지 않습니다. 오래된 release는 `prune`이 지웁니다(7.1.2절). 떠 있는 run이 쓰는 release를 찾는 함수는 설치기의 `runs.releases_in_use`이고, 그 기준은 7.1.1절과 같습니다.
4. Board pane은 release에 고정되지 않습니다. 이미 실행 중인 Board process는 시작한 release의 파일을 계속 씁니다. 확인한 사실: Board가 결정 답변을 보낼 때마다 그 release 안의 `tools/agent-session/bin/agent-session`을 실행합니다([answer.py:13, 39-42](../../tools/project-board/project_board/answer.py), 경로는 [model.py:13](../../tools/project-board/project_board/model.py)의 `TOOLS`). 지워진 release에서 시작한 Board는 답변을 보내지 못하고 `send_unavailable`을 냅니다. 읽기 전용 목록은 시작할 때 import한 module로 그리므로 영향이 없는지는 **(미확인)**입니다. 그래서 `upgrade`·`prune` 출력은 Board를 다시 열도록 안내하고, `prune`은 Board가 켜져 있으면(`@project_board_enabled`가 `1`) 그 사실을 알립니다.

### 7.1.1 떠 있는 run과 형식 버전

배포와 갱신은 run이 동작하는 중에 하므로, 옛 release와 새 release가 같은 state·tmux option·CR 파일을 함께 씁니다. 형식 버전([버전 규칙 3절](release.md#3-형식-버전과-호환-범위))이 다른 release를 한 run과 함께 두지 않기 위해 다음 규칙을 씁니다.

1. 판정 대상: `upgrade`와 `rollback`입니다(`--dry-run` 포함). 대상 release는 `upgrade`에서 `--source`의 `tools/formats.json`, `rollback`에서 `previous` release의 `tools/formats.json`입니다. 같은 release로의 `upgrade`(할 일 없음)는 판정하지 않습니다. `install`은 run이 없는 첫 설치라서 판정하지 않습니다.
2. 떠 있는 run: 등록된 모든 project의 slot 중 `agent_session.api.liveness`가 `alive`·`unknown`인 것입니다(7.2절과 같은 기준, `suspended` 기록만 있는 slot은 run이 없으므로 제외). 등록 파일이 있는데 읽을 수 없으면 판정할 수 없으므로 거절합니다(7.2절과 같음). run이 쓰는 코드는 `<base>/agent/runs/<run_id>/`의 `launch.sh`·`controller.sh`·`settings.json`에 적힌 경로로 알아냅니다.
3. run의 형식 버전:
   - release 경로(`~/.local/lib/project-agent/releases/<이름>/…`)에서 시작한 run은 그 release의 `tools/formats.json`입니다.
   - **release가 아닌 경로에서 시작한 run**(agent 저장소의 동결 사본 `…/codex/tools/agent-session`을 포함해 script가 `/tools/agent-session`만 가리키는 run)은 세 형식 모두 버전 1입니다([버전 규칙 3절](release.md#3-형식-버전과-호환-범위)의 동결 사본 규칙). 첫 release는 세 값이 1이므로 동결 사본에서 시작한 run은 첫 release로의 `upgrade`를 막지 않습니다.
   - tmux에 run이 없는 `unknown` slot처럼 run의 script를 찾을 수 없으면, 그 project의 모든 run 디렉터리가 가리키는 코드를 그 slot이 쓴다고 봅니다. 구분할 수 없으면 쓰는 것으로 봅니다.
4. 거절: 대상 release와 떠 있는 run 중 하나라도 세 값(`agent_session`, `tmux_options`, `item_files`)이 하나라도 다르면 `upgrade`·`rollback`은 아무것도 바꾸지 않고 거절합니다(코드 `formats_differ`, 종료 코드 3). 출력은 그 run의 project·slot·상태와, 어느 release(또는 release가 아닌 사본)에서 어느 값이 다른지, 그리고 아래 안내입니다. 대상 또는 run의 release에 `tools/formats.json`이 없거나 세 정수가 아니면 판정할 수 없으므로 거절합니다(`formats_unreadable`). 떠 있는 run이 없으면 판정하지 않습니다.
5. 안내: 목록의 run을 `agent-session restart --job leader`(Worker는 `--job <CR ID>`)로 다시 시작하면 run이 `current`의 release를 쓰므로, `current`와 대상의 형식이 같을 때 거절이 풀립니다. 이미 `current`의 release를 쓰는 run은 restart해도 그대로이므로 `agent-session stop`으로 끝낸 뒤 다시 실행합니다. 갱신한 뒤에 run을 다시 시작해 새 release를 씁니다.

### 7.1.2 `prune`

`prune`은 쓰지 않는 release를 지웁니다. 설치 기록에 적힌 release 중 다음이 아닌 것을 지웁니다.

- 설치 기록의 `current`, `previous`
- 떠 있는 run이 쓰는 release (7.1.1절의 2·3항과 같은 기준: 7.1절 2항의 "사용 중")

규칙:

1. 지우는 것은 release 디렉터리와 그 설치 기록 항목(`releases`와 소유 목록)입니다. 설치 기록에 없는 디렉터리와 다른 경로는 건드리지 않습니다.
2. release는 설치 기록의 목록 지문(`digest`)이 지금 디렉터리와 같을 때만 지웁니다(원칙 B). 다르면(사용자가 파일을 넣거나 고침) 남기고 알립니다. 지문이 없으면 지우지 않습니다. 디렉터리가 이미 없으면 설치 기록에서만 뺍니다.
3. `--dry-run`은 지울 release 목록과 남기는 release와 그 이유를 출력하며 아무것도 바꾸지 않습니다. 출력한 변경 목록은 실제 실행의 목록과 같습니다.
4. release마다 "디렉터리 삭제 → 그 release를 설치 기록에서 삭제" 순서로 하나씩 합니다. journal은 삭제(redo)로 기록하고(규칙 5), 설치 기록에서 빼는 일은 release 식별자만 담습니다(원칙 A). 중단되면 같은 `prune`이 이어서 끝내고, 그 전에 다른 명령은 `prune_interrupted`로 거절됩니다. 삭제는 release를 `releases/.tmp-<이름>`으로 먼저 옮긴 뒤 지우므로(`uninstall`과 같음) 중단된 삭제가 지문과 어긋난 release를 남기지 않습니다.
5. 지울 release가 없으면 "No release to remove"를 알리고 아무것도 바꾸지 않습니다. 강제 옵션은 없습니다.
6. Board가 켜져 있으면 7.1절 4항의 사실을 알립니다.

### 7.2 `uninstall`의 거절

관리 run이 살아 있으면 `uninstall`을 거절합니다. 거절하면 아무것도 바꾸지 않고, 살아 있는 run의 project와 slot을 출력합니다.

- 판정 대상은 등록 파일의 모든 project입니다. 등록 파일이 있는데 읽을 수 없으면 판정할 수 없으므로 거절합니다. 등록 파일이 어디에도 없으면 project가 없으므로 거절하지 않습니다. `<base>/agent/state.json`이 없는 project는 run이 없는 것으로 봅니다. 관리 run은 `AGENT_SESSION_SOCKET`의 tmux server(없으면 기본 server)에서 판정합니다.
- 각 slot은 [`agent_session.api.liveness`](../../tools/agent-session/agent_session/api.py)로 분류합니다. `alive`와 `unknown`을 거절 근거로 봅니다. `stopped`만 통과합니다.
- shutdown 기록(`<base>/agent/suspend.json`)에 남은 slot이 있으면 거절하고 그 slot을 출력합니다. 다시 재개할 대화가 남아 있는 채로 제품을 지우지 않기 위해서입니다([suspend.py:65-66](../../tools/agent-session/agent_session/suspend.py)). `liveness`가 `stopped`여도 같습니다.
- 강제 옵션(`--force`)은 두지 않습니다. 이유: 강제로 지우면 살아 있는 run의 hook과 controller가 지워진 코드를 부릅니다. 그러면 그 run에 `send`·`stop`·`restart`를 보낼 수 없습니다. 해소 방법은 run을 먼저 끝내는 것입니다(`agent-session stop`, `shutdown`).
- `liveness`의 `unknown`은 server 재시작 뒤 남은 state에도 나옵니다([api.py:73-80](../../tools/agent-session/agent_session/api.py)). 이 경우도 거절합니다. 해소 방법은 `agent-session stop`으로 slot을 끝내거나 `resume`으로 재개한 뒤 끝내는 것입니다.

사용자 등록 파일(6절)은 `uninstall`이 지우지 않습니다. 설치기가 만든 초안도 같습니다. 지우려면 사용자가 직접 지웁니다. 이 때문에 제거 뒤에는 등록 파일과 그 부모 디렉터리가 남습니다.

## 8. 인수 test 명세

[install/tests](../../install/tests)가 구현합니다(`python -m pytest -q install/tests`). 모든 경우에서 기대 변경 목록은 이 문서의 2·3·3.1·7절에서 얻습니다. 설치기의 설치 기록에서 얻지 않습니다.

### 8.1 공통 하네스

1. 격리 HOME을 만듭니다. `HOME`을 그 디렉터리로 바꾸고, `XDG_*`, `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `TMPDIR`은 격리 HOME 안으로 지정하거나 지웁니다. 실제 HOME을 읽지 않습니다.
2. 전후 snapshot을 찍습니다. HOME과 `TMPDIR` 아래의 모든 항목을 symlink를 따라가지 않고 걷습니다. 항목마다 경로, 종류, 권한, 내용 해시, symlink 대상, 일반 파일의 `mtime_ns`를 기록합니다.
3. 판정: 추가·삭제·변경된 경로의 집합이 그 경우의 기대 목록과 **정확히 같아야** 합니다. 기대 밖의 변경은 실패입니다. 기대 목록의 경로가 바뀌지 않은 것도 실패입니다.
4. 기대 밖의 일반 파일은 내용, 권한, `mtime_ns`가 모두 같아야 합니다.
5. 모든 경우에서 실제 `~/.claude`, `~/.codex`를 흉내 내는 기존 파일(`settings.json`, `config.toml`, `.claude.json`, `CLAUDE.md`, `AGENTS.md`, 다른 이름의 skill, `.bashrc`)을 격리 HOME에 미리 둡니다. 이 파일들은 어떤 경우에도 바뀌지 않아야 합니다.
6. tmux 확인이 필요한 경우는 격리 tmux server(private `-S` socket)를 씁니다. 실제 provider 없이, state와 run 파일과 tmux window로 run 증거를 만듭니다.

### 8.2 경우

| ID | 준비 | 동작 | 기대 변경 목록(정확히) | 추가 판정 |
| --- | --- | --- | --- | --- |
| T1 | 깨끗한 HOME. tmux 설정 없음. 등록 파일 없음 | `install` | 2절의 모든 경로, `~/.tmux.conf`(블록만), 등록 파일 초안과 `~/.config/project-agent/`, 필요한 부모 디렉터리 | `~/.tmux.conf`의 내용이 3절의 블록과 같음. `check`가 통과함. 설치 기록의 소유가 위 목록과 같음 |
| T2 | `~/.tmux.conf`가 있음(끝 줄바꿈 있음, 없음, 빈 파일 세 경우) | `install` | 2절의 경로(등록 초안 제외), `~/.tmux.conf`, `backup/<…>-.tmux.conf` | 블록 밖의 내용이 같음. `backup/`의 파일이 설치 전 원본과 byte 단위로 같음 |
| T3 | `~/.tmux.conf` 없음, `~/.config/tmux/tmux.conf`가 있음 | `install` | 2절의 경로, `~/.config/tmux/tmux.conf`, `backup/<…>` | `~/.tmux.conf`가 새로 생기지 않음. 둘 다 있는 경우는 `~/.tmux.conf`만 바뀜 |
| T4 | tmux 설정이 symlink(a: `~/.tmux.conf`가 다른 저장소 파일로 가는 link, b: `~/.config/tmux/tmux.conf`가 link) | `install` | 2절의 경로. tmux 파일과 link 대상은 변경 없음 | 종료 코드 0. 출력에 사실과 넣을 줄이 있음. `check`가 "수동 연결 필요"를 알림. 사용자가 link 대상에 그 줄을 넣은 뒤(주석 처리한 줄은 넣은 것이 아님)에는 알리지 않음 |
| T5 | 블록이 이미 있음(설치기 소유가 아님) | `install` | 2절의 경로. tmux 파일은 변경 없음 | `uninstall`이 그 블록을 지우지 않음(T9b) |
| T6 | 설치된 상태 | `upgrade` | 새 release 디렉터리, `current`, 설치 기록 | shim, skill link, `tmux.conf`, tmux 설정 파일, 등록 파일의 내용과 `mtime_ns`가 같음. 이전 release의 모든 파일이 byte 단위로 같음 |
| T7 | 설치된 상태. 옛 release를 쓰는 떠 있는 run(`launch.sh`가 옛 release 경로를 가짐) | `upgrade` | T6과 같음 | 옛 release가 남아 있음. 갱신 뒤에도 그 run의 `launch.sh`·controller 명령이 실행됨. 새로 시작한 run의 `launch.sh`는 새 release 경로를 가짐 |
| T8 | 설치·갱신을 한 상태 | `rollback` | `current`, 설치 기록 | `current`를 계속 읽는 관찰자가 교체 중에 `current`가 없거나 끊어진 상태를 한 번도 보지 못함. 이전 release가 없으면 거절하고 변경 없음 |
| T9 | 설치된 상태(T1, T2의 세 변형, T3) | `uninstall` | 2절에서 만든 경로의 삭제, 설치기가 만든 빈 디렉터리의 삭제. 등록 파일 초안과 그 디렉터리는 남음 | 설치 뒤 블록 밖을 고치지 않았다면 tmux 파일이 설치 전과 byte 단위로 같음. T1은 `~/.tmux.conf`가 없어짐. T9b: 블록 밖을 설치 뒤에 고쳤다면 블록만 지워지고 고친 내용은 남음. 설치기 소유가 아닌 블록은 남음 |
| T10 | 설치된 상태. 거절 사유 셋을 각각: 관리 run이 `alive`, `unknown`, `stopped`이지만 `suspend.json`에 slot이 남음 | `uninstall` | 없음 | snapshot 전체가 같음. 출력이 project와 slot을 알림. release가 지워지지 않음. `--force`는 인식되지 않는 옵션으로 거절됨 |
| T11 | 2절의 경로 하나마다 미리 만든 충돌(일반 파일, 디렉터리, 다른 곳을 가리키는 link, 같은 대상을 가리키지만 기록에 없는 link). 경로: shim 3, skill link 4, 비어 있지 않은 `~/.local/lib/project-agent/` | `install` | 없음 | snapshot 전체가 같음(부분 생성 없음). 출력이 충돌 경로를 모두 나열함. 종료 코드가 0이 아님 |
| T12 | 설치된 상태에서 사용자가 소유 경로 하나(skill link)를 자기 link로 바꿈 | `check`, `upgrade`, `uninstall` | `check`: 없음. `upgrade`·`uninstall`: 그 경로를 뺀 나머지 | 사용자가 바꾼 link가 그대로임. 출력이 그 경로를 알림 |
| T13 | 등록 파일 위치: (a) 어디에도 없음 (b) `~/.codex/project.json`만 (c) `~/.claude/project.json`만 (d) 제품 위치만 | `install` | (a)만 등록 초안을 더함 | (b)(c)(d)의 기존 등록 파일은 byte 단위로 같고 초안이 생기지 않음 |
| T14 | 위의 모든 상태 | 각 명령 + `--dry-run` | 없음 | snapshot 전체가 같음. 출력한 변경 목록이 같은 상태에서 실제로 실행한 변경 목록과 같음 |
| T15 | 설치를 중간에 실패시킴(예: `~/.local/bin`을 쓰기 금지) | `install` | 없음 | snapshot 전체가 같음 |
| T16 | 설치된 상태 | `install`을 한 번 더 | 없음(같은 release) | snapshot 전체가 같음 |
| T17 | 깨끗한 HOME | `install` → `uninstall` → `install` | 첫 `install`과 같음 | 첫 설치와 두 번째 설치의 snapshot이 같음 |
| T18 | 4절의 파일 | 모든 명령 | 4절의 파일은 변경 없음 | 4절의 파일의 내용, 권한, `mtime_ns`가 같음. 내용을 읽기만 했는지는 확인하지 않습니다 |
| T19 | 설치된 상태. 등록 project 하나. provider 대신 fake CLI | `agent-session start`, `stop`, `project-item new cr`, `project-board` 한 번 | 5절 표의 위치 안에서만 변경 | 5절 표 밖의 경로가 바뀌면 실패. 표를 고치면 이 test의 기대도 함께 고침 |

| T20 | 격리 tmux server. 사용자 설정이 `prefix B`(다른 명령)와 root `MouseDown1Pane`(다른 명령)을 미리 binding함 | 설치 뒤 `tmux.conf`를 읽음 | 파일 변경은 T1과 같음. server의 binding은 두 키 모두 사용자 값 그대로 | `check`가 두 키를 "binding 건너뜀"으로 알림. 사용자 binding이 없을 때는 둘 다 제품 binding으로 들어감 |
| T21 | 격리 tmux server. 읽기 전에 `@project_agent_board_key`를 `X`로 설정 | 설치 뒤 `tmux.conf`를 읽음 | 파일 변경은 T1과 같음 | `prefix X`가 Board toggle이고 `prefix B`는 binding되지 않음 |
| T22 | `~/.codex/skills/project-team`이 runtime이 만든 link(`skills.json`에 대상이 일치하게 기록됨). 같은 이름이지만 `skills.json`에 없는 link도 따로 준비 | `install` | 앞의 경우: 2절의 경로, 그 link의 대상 교체, 설치 기록. 뒤의 경우: 없음(거절) | `skills.json`의 내용과 `mtime_ns`가 같음. 설치 기록에 넘겨받음이 적힘 |
| T23 | `CLAUDE_CONFIG_DIR`·`CODEX_HOME`을 격리 HOME 안의 다른 디렉터리로 설정 | `install`, 그 뒤 두 변수를 지우고 `uninstall` | skill link는 변수가 가리키는 디렉터리의 `skills/`에만 생김. 기본 경로(`~/.claude`, `~/.codex`)에는 아무것도 없음 | 설치 기록에 실제 경로가 있음. `uninstall`이 기록한 경로의 link를 지움 |
| T24 | 이 workstation의 모양: 세 shim과 Codex skill link 둘은 옛 개발 checkout을 가리키는 절대 link, `~/.claude/skills`는 그 checkout의 `claude/skills`로 가는 symlink이고 안의 skill link 둘은 상대 link | 옵션 없이 `install` | 없음 | snapshot 전체(HOME과 checkout)가 같음. 출력이 일곱 경로를 모두 나열함. 종료 코드 3 |
| T25 | T24의 상태 | `install --adopt-dev-links <checkout>`, 이어서 `uninstall` | 2절의 경로(넘겨받은 일곱 link는 새로 만들지 않고 교체). Claude link는 checkout 안의 파일이 바뀜 | 설치 기록의 `adopted_from`이 이전 글자(상대 글자 포함)와 byte 단위로 같음. `check` 통과. `uninstall` 뒤 snapshot이 설치 전과 같음. 사용자가 그 사이에 바꾼 link는 `uninstall`이 건드리지 않음. 알려진 모양이 아닌 `adopted_from`이 든 기록은 거절됨. `--dry-run`의 목록이 실제 실행과 같음 |
| T26 | T24의 상태에서 하나만 어긋나게 함: 모양이 다른 대상, 다른 checkout을 가리킴, 파일·디렉터리가 있음, 다른 사용자 소유, 옵션이 가리키는 checkout이 다름 | `install --adopt-dev-links <checkout>` | 없음 | snapshot 전체가 같음(나머지 link도 교체되지 않음). 어긋난 경로를 모두 나열함. 종료 코드 3 |
| T27 | T24의 상태. 부모 `~/.claude/skills`가 symlink | T25와 같음 | T25와 같음 | `~/.claude/skills`가 그대로 symlink이고 checkout의 다른 skill은 같음. 되돌린 뒤 상대 글자가 그대로임 |
| T28 | T24의 상태 | `install --adopt-dev-links`와 `uninstall` 동안 일곱 진입점을 계속 `stat`하는 관찰자 | T25와 같음 | 관찰자가 없거나 끊어진 진입점을 한 번도 보지 못함(되돌림이 release 삭제보다 먼저임) |
| T29 | 설치된 상태. 떠 있는 run(`alive` 또는 tmux에 run이 없는 `unknown`)이 release에서 시작됨. 형식 값 하나(`agent_session`, `tmux_options`, `item_files` 각각)가 다른 release를 준비 | `upgrade`(`--dry-run` 포함) | 없음 | snapshot 전체가 같음. 종료 코드 3(`formats_differ`). 출력에 project·slot·상태·다른 값·restart 안내가 있음. 떠 있는 run이 없거나 형식이 같으면 T6과 같이 진행함. 대상에 `tools/formats.json`이 없으면 `formats_unreadable`로 거절함 |
| T29b | 형식 값이 다른 release로 갱신하고, 그 release에서 run이 시작됨 | `rollback` | 없음 | 위와 같이 거절함. run을 끝낸 뒤에는 T8과 같이 진행함. 형식이 같으면 run이 떠 있어도 진행함 |
| T30 | release가 아닌 경로(이 저장소의 checkout, 동결 사본 대용)에서 시작한 run이 떠 있음 | 첫 release의 `install`, 형식이 같은 release로 `upgrade`, 형식이 다른 release로 `upgrade` | 앞의 둘은 T1·T6과 같음. 셋째는 없음 | 셋째만 거절하고 출력에 "a copy that is not a release"와 다른 값이 있음 |
| T31 | 설치·갱신을 두 번 한 상태(release 셋). 떠 있는 run이 첫 release에서 시작됨 / 없음 / `unknown` / 첫 release 디렉터리에 사용자의 파일 | `prune`(`--dry-run` 포함) | run이 떠 있거나 `unknown`이거나 사용자의 파일이 있으면 없음(이유를 알림). 아니면 첫 release의 삭제와 설치 기록 | `current`·`previous`는 남음(`rollback` 뒤에는 새 `previous`도 남음). dry-run 목록과 실제 삭제 목록이 같음. `check`가 통과함. Board가 켜져 있으면 알림 |
| T32 | 위의 `prune`을 SIGKILL로 끊음(첫 step의 앞·뒤) | `check`, `upgrade`, `prune --dry-run`, `prune` | `prune`이 마침 | `check`는 실패, `upgrade`는 `prune_interrupted`, `--dry-run`은 거절. 마친 뒤 journal·임시 디렉터리가 없음 |
| T33 | 설치 interpreter가 빈 환경에서 다른 `sys.prefix`로 뜸(INSTALL-006) | `install`, 빈 환경에서 진입점과 `check`, `python.env`의 `PROJECT_AGENT_PYTHON_PREFIX`·library 경로 변경 후 `check` | 2절의 경로 | `python.env`에 library 경로가 적히고, 빈 환경의 진입점이 설치 때와 같은 `sys.prefix`로 실행됨. 어느 경로로도 같아지지 않으면 `python_environment`로 거절함(종료 코드 3). 값을 틀리게 하거나 library 경로를 지우면 `check`가 실패함 |

기대 변경 목록의 "정확히"는 T1~T18과 T20~T32에 적용합니다. T19는 "5절 안"입니다. T20·T21은 binding을 읽는 server의 상태도 판정합니다. T20·T21의 binding은 TMUX-001이 구현했습니다([test](../../integrations/tmux/test_project_agent_conf.py)).

## 9. 이 계약과 어긋나는 현재 동작

코드는 이 CR에서 바꾸지 않았습니다. 아래는 해당 단계에서 다룹니다.

| 항목 | 현재 | 계약 | 처리 단계 |
| --- | --- | --- | --- |
| 등록 파일 위치 | 해결됨(DIST-003): 6절의 세 후보를 찾음 | 6절의 세 후보 | 2단계 |
| CLI python 선택 | 해결됨(DIST-003): 6.1절의 공용 launcher가 `PROJECT_AGENT_PYTHON`·`PROJECT_AGENT_PYTHONPATH`를 받음 | 설치 때 고른 interpreter. `project-board`는 `PYTHONNOUSERSITE=1`이므로 release 안의 package를 `PYTHONPATH`로 넣어야 함 | 2단계 |
| tmux helper의 Python 선택 | 해결됨(INSTALL-002): `tools/python.env`를 launcher가 읽고, 결정 표시는 `tmux_decide_status.sh`가 같은 launcher로 실행함 | 설치 때 고른 interpreter(6.1절) | 4단계(설치기가 `python.env`를 씀) |
| 원격 runtime의 skill link | runtime의 건너뛰기는 해결됨(DIST-003): `install.json`이 있으면 `_install_skills`가 link를 만들지 않고 고치지 않음. 설치의 넘겨받기는 남음 | 설치본이 있으면 만들지 않고 고치지 않음(2절 규칙 6) | 4단계(설치의 넘겨받기) |
| tmux 통합 파일의 경로 | 해결됨(TMUX-001): 통합 파일이 읽힌 디렉터리(`@project_agent_tmux_dir`)의 helper를 부름 | `current` 아래 경로 | 5단계 |
| tmux 통합 파일의 binding | 해결됨(TMUX-001): 3.1절대로 binding하고 건너뜀 | 3.1절 | 5단계 |
| `tmux_decide_status.py`의 project-item 찾기 | 해결됨(TMUX-001): 스크립트가 있는 release 안의 `tools/project-item`을 찾음([README의 실행 경로 계약 6항](README.md)). `current` link 경로로 불러도 같은 release를 찾음 | 설치본에서도 찾음 | 5단계 |

### 9.1 7단계 안내문이 다룰 항목

설치는 project 저장소를 고치지 않습니다(4절). 아래 항목은 설치가 아니라 직원용 설치 안내문(DIST-001 7단계)이 다룹니다.

1. 제품은 등록 base의 `agent/` 아래에 파일을 씁니다(5.2절). 이 파일은 project 저장소에서 untracked로 보입니다. 대상: `state.json`, `state.lock`, `suspend.json`, `suspend.lock`, `allocation.lock`, `control/`, `runs/`, `diagnostics/`, `handoff/`, `decide/decide.html`.
2. 안내문은 사용자가 이 경로를 자기 저장소의 ignore 설정(`.gitignore` 또는 `.git/info/exclude`)에 넣도록 안내합니다. 어느 파일에 넣을지는 사용자가 정합니다.
3. 안내문은 `agent/cr/`, `agent/decide/`의 item 파일은 추적 대상이라는 점도 적습니다(`path_cr`, `path_decide`의 기본 예시는 [project-registry.example.json](project-registry.example.json)).
