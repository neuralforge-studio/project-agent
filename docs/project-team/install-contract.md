# project-agent 설치 계약

이 계약은 확정 기준(사용자 결정 D-20261109-08·09)입니다. 설치기는 DIST-001 4단계에서 구현합니다.
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
| `~/.local/lib/project-agent/releases/<version>-<hash>/` | 디렉터리 | 불변 release. 도구, skill, 문서, tmux 통합 파일, release 안의 외부 package를 담습니다. |
| `~/.local/lib/project-agent/current` | symlink | 활성 release를 가리킵니다. 원자적으로 바꿉니다. |
| `~/.local/lib/project-agent/tmux.conf` | 파일 | tmux include의 고정 대상입니다. `source-file -q ~/.local/lib/project-agent/current/integrations/tmux/project-agent.conf` 한 줄을 담습니다. 설치 때 한 번 쓰고 갱신하지 않습니다. |
| `~/.local/lib/project-agent/install.json` | 파일 | 설치 기록 |
| `~/.local/lib/project-agent/backup/` | 디렉터리 | 설치가 고친 기존 파일의 원본(3절). 고친 파일이 없으면 만들지 않습니다. |
| `~/.local/bin/agent-session`, `project-item`, `project-board` | shim | `current` 아래 각 도구의 진입점으로 가는 symlink 또는 script. 반드시 `current`를 거칩니다. 형태는 4단계가 정합니다. |
| `~/.claude/skills/project-team`, `~/.claude/skills/project-item` | symlink | `current` 아래 skill 디렉터리로 가는 link |
| `~/.codex/skills/project-team`, `~/.codex/skills/project-item` | symlink | 같은 skill 디렉터리로 가는 link |
| `~/.config/project-agent/project.json` | 파일 | 등록 파일 초안. 6절의 조건에서만 만듭니다. 내용은 빈 등록(`{}`)입니다. `load_registry`가 빈 object를 project 0개로 읽습니다([config.py:152-153](../../codex/tools/agent-session/agent_session/config.py)). |

경로 규칙은 다음과 같습니다.

1. 이미 같은 이름이 있고 설치기 소유가 아니면, 아무것도 바꾸지 않고 전체를 거절합니다.
   - 같은 이름은 파일, 디렉터리, 다른 곳을 가리키는 link입니다.
   - 같은 대상을 가리키지만 설치 기록에 없는 link도 소유가 아니므로 거절합니다.
   - 거절은 충돌 경로를 한 번에 모두 출력합니다.
   - 예외: 원격 runtime이 만든 skill link는 충돌이 아닙니다. 아래 규칙 6이 정합니다.
2. 부모 디렉터리가 없으면 설치가 만들고 설치 기록에 `created_dirs`로 남깁니다. 제거는 그 디렉터리가 비어 있을 때만 지웁니다.
3. provider 홈이 없으면 그 provider의 skill link를 만들지 않고 안내만 출력합니다. 설치가 쓰지 않는 provider의 홈을 만들지 않기 위해서입니다. provider 홈의 경로는 아래 규칙 7이 정합니다.
4. 부모 디렉터리가 symlink이면 link를 따라가서 만듭니다. link는 가리키는 디렉터리 안에 놓입니다. 설치 기록과 출력에는 `~` 기준 경로를 적고, 실제 위치를 함께 출력합니다. 이 workstation의 `~/.claude/skills`가 그 경우입니다(DIST-001 6단계가 `.gitignore`로 다룹니다).
5. 설치가 중간에 실패하면, 이미 만든 것을 지워 설치 전 상태로 돌립니다. 설치 기록은 마지막에 확정합니다.

6. **원격 runtime의 skill link를 넘겨받습니다.** 원격 runtime은 `~/.codex/skills/project-team`·`project-item` link를 만들고 소유를 `~/.cache/agent-session/skills.json`에 적습니다([remote_runtime.py:46-94](../../codex/tools/agent-session/agent_session/remote_runtime.py)). 같은 제품이 만든 link이므로 설치는 이를 충돌로 보지 않습니다.
   - 넘겨받는 조건은 runtime이 소유를 판단하는 조건과 같습니다. 이름이 `skills.json`에 있고, link의 소유자가 현재 사용자이고, link의 대상이 기록한 대상과 같습니다([remote_runtime.py:72-76](../../codex/tools/agent-session/agent_session/remote_runtime.py)). 하나라도 다르면 충돌입니다.
   - 설치는 그 link를 설치본의 skill 디렉터리를 가리키도록 바꾸고, 설치 기록에 설치기 소유로 적습니다. 설치 기록에는 넘겨받았음을 함께 적습니다.
   - 설치는 `skills.json`을 고치지 않습니다. runtime이 소유하는 기록이기 때문입니다.
   - 설치본이 있으면(`~/.local/lib/project-agent/install.json`이 있으면) runtime은 skill link를 만들지 않고 고치지 않습니다. 이 동작은 코드 변경입니다. 처리 단계는 9절에 적습니다.
7. **provider 홈은 환경 변수를 따릅니다.** 제품 코드가 따르는 규칙과 같습니다([claude.py:104](../../codex/tools/agent-session/agent_session/providers/claude.py), [codex.py:68](../../codex/tools/agent-session/agent_session/providers/codex.py)).
   - Claude: `CLAUDE_CONFIG_DIR`가 설정돼 있으면 그 디렉터리, 없으면 `~/.claude`. skill link는 그 아래 `skills/`에 만듭니다.
   - Codex: `CODEX_HOME`이 설정돼 있으면 그 디렉터리, 없으면 `~/.codex`. skill link는 그 아래 `skills/`에 만듭니다.
   - 설치는 쓴 실제 경로를 설치 기록에 남깁니다. `uninstall`과 `check`는 기록한 경로를 씁니다. 설치 뒤 환경 변수가 바뀌어도 기록한 경로를 씁니다.
   - 위 2절 표의 `~/.claude/skills/…`, `~/.codex/skills/…`는 변수가 없을 때의 기본 경로입니다.

## 3. 설치가 고치는 기존 파일은 하나뿐입니다

고치는 파일은 사용자 tmux 설정입니다. 넣는 내용은 시작·끝 표시가 있는 블록 하나입니다.

```
<이전 내용 바로 뒤에 줄바꿈 하나>
# >>> project-agent (managed block, do not edit) >>>
source-file -q ~/.local/lib/project-agent/tmux.conf
# <<< project-agent <<<
```

표시 줄의 정확한 글자는 4단계가 정하고 이 문서에 옮깁니다. 블록은 첫 줄의 줄바꿈 하나를 포함합니다. 그래야 원본이 줄바꿈으로 끝나지 않아도 제거가 byte 단위로 되돌립니다.

| 상황 | 동작 |
| --- | --- |
| 대상 선택 | `~/.tmux.conf`가 있으면 그 파일입니다. 없고 `~/.config/tmux/tmux.conf`가 있으면 그 파일입니다. 둘 다 있으면 `~/.tmux.conf`입니다(tmux가 읽는 순서와 같습니다). |
| 둘 다 없음 | 블록만 담은 `~/.tmux.conf`를 만듭니다. 설치 기록에 `created: true`로 남깁니다. `~/.config/tmux/`는 만들지 않습니다. |
| 블록이 이미 있음 | 파일을 바꾸지 않습니다. 그 블록을 설치기가 넣지 않았다면, 제거도 그 블록을 지우지 않습니다. |
| 블록을 넣음 | 고치기 전에 원본을 `backup/`에 둡니다. 파일 이름은 `<UTC 시각>-<원본 파일 이름>`입니다. |
| 대상이 symlink | 파일도 link 대상도 고치지 않습니다. 그 사실과 사용자가 넣을 줄을 출력합니다. 나머지 설치는 계속합니다. 종료 코드는 0입니다. `check`는 이 상태를 "수동 연결 필요"로 알립니다(실패가 아닙니다) . |
| 실행 중인 tmux server | 다시 읽히지 않습니다. 설치는 다시 읽는 명령 `tmux source-file ~/.local/lib/project-agent/tmux.conf`만 출력합니다. 사용자의 전체 설정을 다시 읽는 명령은 권하지 않습니다. |
| `upgrade`·`rollback` | 블록을 다시 고치지 않습니다. `current`만 바뀌기 때문입니다. |
| `uninstall` | 설치기가 넣은 표시된 블록(앞의 줄바꿈 포함)만 지웁니다. `created: true`이고 지운 뒤 내용이 없으면 파일도 지웁니다. |

보장: 설치 뒤 사용자가 블록 밖을 고치지 않았다면, 제거 뒤 파일은 설치 전과 byte 단위로 같습니다. 설치 전에 파일이 없었다면 제거 뒤에도 없습니다.

### 3.1 통합 파일이 server에 넣는 binding

tmux 통합 파일은 읽힐 때 tmux server에 binding과 hook을 넣습니다([5.3](#53-tmux-server)). 사용자가 정한 binding은 덮어쓰지 않습니다. 구현은 DIST-001 5단계가 합니다.

1. `prefix B`와 root table의 `MouseDown1Pane`은 비어 있거나 tmux 기본값일 때만 binding합니다. 그 밖의 binding이 있으면 건너뜁니다. tmux 3.8 기준으로 `prefix B`는 기본 binding이 없고, `MouseDown1Pane`의 기본값은 `select-pane -t = \; send-keys -M`입니다.
2. Board 키는 사용자가 바꿀 수 있습니다. 통합 파일을 읽기 전에 tmux option `@project_agent_board_key`를 설정하면 그 키를 씁니다. 없으면 `B`입니다.
3. 건너뛴 binding은 `check`가 "binding 건너뜀"으로 알립니다. 어느 키를 건너뛰었는지 함께 알립니다. 실패가 아닙니다.
4. 통합 파일이 넣은 binding과 hook은 `uninstall` 뒤에도 server가 끝날 때까지 남습니다. `uninstall`은 이를 되돌리는 명령을 출력합니다. 출력하는 명령은 `unbind-key`, 기본값이 있는 `MouseDown1Pane`의 기본값 복원, `set-hook -gu`입니다. 사용자의 binding은 되돌림 대상이 아닙니다.
5. 설치기는 이 명령을 실행하지 않습니다. 실행 중인 server를 바꾸지 않는 원칙은 3절의 "실행 중인 tmux server" 행과 같습니다.

## 4. 설치가 절대 건드리지 않는 것

- Claude·Codex 설정 파일: `settings.json`, `config.toml`, `.claude.json`. 실행 중의 신뢰 기록은 5절이 따로 다룹니다.
- `CLAUDE.md`, `AGENTS.md`, 이 계약의 2절에 없는 다른 skill
- shell rc와 PATH. `~/.local/bin`이 PATH에 없으면 안내만 출력합니다.
- 전역 Python package. Board의 외부 package는 release 안에 넣습니다.
- 등록 project의 저장소: `.gitignore`, `.git/info/exclude`, git 설정, project 안의 어떤 파일도 고치지 않습니다. base의 `agent/` 아래 untracked 파일에 대한 안내는 9.1절이 정합니다.
- 위 3절의 한 파일을 뺀 모든 기존 파일. 읽기만 해도 되는 파일은 예외 없이 내용·권한·mtime이 같아야 합니다.

## 5. 실행 중 쓰기 목록

설치가 아니라 제품이 실행 중에 쓰는 위치입니다. 2026-11-09에 코드에서 확인한 사실만 적습니다. 확인하지 못한 것은 **(미확인)**으로 남깁니다.

찾은 방법(재현용): 쓰기 호출 검색과 경로 검색을 `codex/tools/{agent-session,project-item,project-board}`와 `tmux/scripts`에서 했습니다.

```sh
grep -rnE 'write_text|write_bytes|\.open\(|\bopen\(|os\.replace|os\.rename|\.rename\(|shutil\.|mkdir|makedirs|symlink|unlink|rmtree|os\.remove|\.touch\(|chmod|mkstemp|NamedTemporary|TemporaryDirectory|tempfile|fcntl|os\.link|copy2|copyfile|copytree|os\.write|O_CREAT' \
    codex/tools/agent-session codex/tools/project-item codex/tools/project-board --include='*.py' | grep -v /tests/
grep -rnE 'Path\.home|expanduser|XDG|"HOME"|~/|\.cache|/tmp' codex/tools tmux/scripts --include='*.py' --include='*.sh' | grep -v /tests/
grep -rnE '"(new-session|new-window|set-option|set-hook|bind-key|rename-window|kill-window|respawn-pane|send-keys|run-shell|display-message|split-window)"' \
    codex/tools --include='*.py' | grep -v /tests/
```

**범위** 열: "등록"은 등록 파일이 가리키는 경로(base, seat, `path_cr`, `path_decide`)에 한정된다는 뜻입니다. "HOME"은 등록과 무관하게 사용자 HOME 안의 고정 위치입니다. "tmux"는 tmux server의 상태입니다. "tmp"는 HOME 밖의 `/tmp`입니다.

### 5.1 사용자 HOME의 고정 위치

| 위치 | 언제 | 무엇을 쓰는가 | 범위 | 근거 |
| --- | --- | --- | --- | --- |
| `~/.claude.json` (`CLAUDE_CONFIG_DIR`가 있으면 그 디렉터리의 `.claude.json`) | Claude project에서 `start`가 새 seat를 clone했을 때만 | `projects.<seat 절대 경로>.hasTrustDialogAccepted = true` 한 항목. 파일이 없으면 쓰지 않습니다. 이미 true면 쓰지 않습니다. 잠금 디렉터리 `.claude.json.lock`과 임시 파일 `.claude.json.agent-session-<pid>`를 만들고 끝나면 지웁니다. 파일이 symlink면 가리키는 파일을 고칩니다(`resolve()`). | 등록(seat 경로). 새로 clone한 로컬 seat만. Claude Leader의 base에는 쓰지 않습니다. | [claude.py:143-190](../../codex/tools/agent-session/agent_session/providers/claude.py), 호출 [lifecycle.py:535-536](../../codex/tools/agent-session/agent_session/lifecycle.py) → [claude.py:244-246](../../codex/tools/agent-session/agent_session/providers/claude.py) |
| `~/.codex/config.toml` (`CODEX_HOME`가 있으면 그 디렉터리) | Codex project에서 (a) Leader를 시작할 때마다, (b) `start`가 새 로컬 seat를 clone했을 때, (c) 원격 host에서 seat를 clone했을 때 | `[projects."<절대 경로>"]`에 `trust_level = "trusted"`. 이미 trusted면 쓰지 않습니다. **디렉터리 `~/.codex/`와 `config.toml`이 없으면 만듭니다.** 잠금 디렉터리 `config.toml.agent-session.lock`과 임시 파일을 만들고 끝나면 지웁니다. symlink면 가리키는 파일을 고칩니다. | 등록(base 또는 seat 경로) | [codex.py:35-113](../../codex/tools/agent-session/agent_session/providers/codex.py), 호출 [launch_artifacts.py:101-102](../../codex/tools/agent-session/agent_session/launch_artifacts.py), [lifecycle.py:535-536](../../codex/tools/agent-session/agent_session/lifecycle.py), [remote_runtime.py:299-300](../../codex/tools/agent-session/agent_session/remote_runtime.py) |
| `~/.cache/project-item/locks/<hash>.lock` | `project-item`의 `new`·`move`·`record`·`render` 등 item root를 쓰는 모든 명령 | 잠금 파일(내용 없음). 만든 뒤에 지우지 않습니다. `<hash>`는 item root 경로의 해시입니다. | 등록(`path_cr`, `path_decide`)에서 계산한 이름 | [store.py:19-31](../../codex/tools/project-item/project_item/store.py) |
| `~/.cache/tmux-decide-status.json`, `.lock`, `.<pid>.tmp` (`XDG_CACHE_HOME`가 있으면 그 아래) | tmux status가 `tmux_decide_status.py`를 부를 때. 사용자가 status 설정에 이 script를 넣은 경우만 | 열린 결정 ID 목록과 잠금. 새 결정이 생기면 모든 tmux client에 `display-message`와, Leader window의 pane tty에 BEL(0x07)을 씁니다. | 등록(project마다 `path_decide`를 읽음) | [tmux_decide_status.py:49-51, 69-74, 168-170](../../tmux/scripts/tmux_decide_status.py), 알림 [같은 파일 136-146](../../tmux/scripts/tmux_decide_status.py) |
| (원격 host의 HOME) `~/.cache/agent-session/runs/<run>/`, `~/.cache/agent-session/runtime/<hash>/`와 `.lock`, `~/.cache/agent-session/skills.json`·`skills.lock` | Codex SSH Worker seat를 쓰는 원격 host에서만 | run 기록, 받은 실행본 압축 해제, skill 소유 기록. 이 host에서는 일어나지 않습니다. | 원격 host의 HOME | [remote_runtime.py:17-20, 46-94, 171-214](../../codex/tools/agent-session/agent_session/remote_runtime.py), [remote.py:15-29](../../codex/tools/agent-session/agent_session/remote.py) |
| (원격 host의 HOME) `~/.codex/skills/project-team`, `~/.codex/skills/project-item` | 같은 원격 host에서 run을 시작할 때 | 위 실행본의 `guidance/codex/skills/<이름>`을 가리키는 symlink. 이름이 이미 있고 이 runtime이 만든 것이 아니면 건드리지 않습니다. `~/.codex/skills/`가 없으면 만듭니다. | 원격 host의 HOME. **2절의 설치 대상과 같은 이름입니다(2절 규칙 6).** | [remote_runtime.py:46-94](../../codex/tools/agent-session/agent_session/remote_runtime.py) |

읽기만 하는 HOME 위치(쓰지 않음): `~/.claude/projects/`([claude.py:104](../../codex/tools/agent-session/agent_session/providers/claude.py)), `~/.claude/settings.json`([claude.py:279](../../codex/tools/agent-session/agent_session/providers/claude.py)), `~/.claude/sessions/`([registry.py:79-97](../../codex/tools/project-item/project_item/registry.py)), `~/.codex/<profile>.config.toml`([codex.py:327-328](../../codex/tools/agent-session/agent_session/providers/codex.py)), 등록 파일.

### 5.2 등록 project 안

`<base>`는 등록된 base 경로입니다. 아래는 모두 등록 경로 아래입니다.

| 위치 | 언제 | 무엇을 쓰는가 | 범위 | 근거 |
| --- | --- | --- | --- | --- |
| `<base>/agent/state.json`, `state.lock` | 모든 배정·제어 명령 | slot별 배정 state(원자적 교체) | 등록(base) | [state.py:176-231](../../codex/tools/agent-session/agent_session/state.py) |
| `<base>/agent/suspend.json`, `suspend.lock` | `shutdown`·`resume` | shutdown 기록 | 등록(base) | [suspend.py:65-66, 92-95](../../codex/tools/agent-session/agent_session/suspend.py) |
| `<base>/agent/allocation.lock`, `agent/control/<slot>.lock` | `start`·`stop`·`restart`·`send` | 잠금 파일 | 등록(base) | [lifecycle.py:73, 345, 494, 524](../../codex/tools/agent-session/agent_session/lifecycle.py) |
| `<base>/agent/runs/<run_id>/` | run을 시작할 때, stop·restart를 예약할 때 | `prompt.md`, Claude의 `settings.json`(hook 선언), `launch.sh`, `controller.sh`, `control-request.json`, `control-result.json`. 원격 seat는 `bridge.json`도 씁니다. 모든 명령에 **release의 절대 경로**와 python 경로가 들어갑니다. | 등록(base) | [launch_artifacts.py:80-89, 104, 137-152](../../codex/tools/agent-session/agent_session/launch_artifacts.py), [lifecycle.py:864-866](../../codex/tools/agent-session/agent_session/lifecycle.py), [internal.py:234-265](../../codex/tools/agent-session/agent_session/internal.py), [remote_bridge.py:53-74](../../codex/tools/agent-session/agent_session/remote_bridge.py) |
| `<base>/agent/diagnostics/<시각>-<명령>-<pid>.log` | 명령이 내부 오류로 끝났을 때 | traceback | 등록(base) | [cli.py:126-137](../../codex/tools/agent-session/agent_session/cli.py) |
| `<base>/agent/handoff/<slot>.md` | 원격 seat의 restart 검증 때 중앙 사본을 씁니다. 로컬 slot의 파일은 대화가 씁니다(제품 코드가 아닙니다). | 인계 문서 | 등록(base) | [handoff.py:15-28](../../codex/tools/agent-session/agent_session/handoff.py) |
| `path_decide/decide.html` (`render --out`이 있으면 그 경로) | `project-item`이 결정을 바꿀 때마다 | 결정 목록 page(원자적 교체) | 등록(`path_decide`) | [render.py:246-258](../../codex/tools/project-item/project_item/render.py), [cli.py:46-47](../../codex/tools/project-item/project_item/cli.py) |
| `path_cr`·`path_decide`의 item 파일 | `new`·`move`·`record`·`accept`·`answer`, `start`의 배정(`todo`→`in-progress`), Base header 기록, 원격 Worker의 Result 보고 | item 파일 생성(`O_EXCL`), 본문 수정, 상태 디렉터리 사이 이동(git이 추적하면 `git mv`) | 등록(`path_cr`, `path_decide`) | [store.py:131-134, 196, 291-303](../../codex/tools/project-item/project_item/store.py), [assign.py:48-67](../../codex/tools/project-item/project_item/assign.py), [remote_bridge.py:46](../../codex/tools/agent-session/agent_session/remote_bridge.py), 답변 [answer.py:108](../../codex/tools/project-board/project_board/answer.py) |
| base·seat의 git 작업 트리 | `start`가 Worker를 배정할 때 | `git switch main`, `fetch origin`, `merge --ff-only`, `switch -c cr/<ID>`, `submodule update --init --recursive`. 작업 트리와 ref를 바꿉니다. | 등록(base, seat) | [git_ops.py:98-100, 118, 142-172](../../codex/tools/agent-session/agent_session/git_ops.py) |
| 새 seat 디렉터리 | seat 경로가 없을 때 `start`가 | 새 디렉터리 하나를 만들고 base의 origin을 clone합니다. clone이 실패하면 그 디렉터리만 지웁니다. | 등록(seat 경로) | [workspace.py:15-49](../../codex/tools/agent-session/agent_session/workspace.py) |

### 5.3 tmux server

두 도구가 tmux server(사용자의 기본 server 또는 `--socket`)의 상태를 바꿉니다. 이 상태는 server가 끝나면 사라집니다.

| 대상 | 언제 | 무엇을 하는가 | 근거 |
| --- | --- | --- | --- |
| session | project의 첫 run을 만들 때 | `new-session -d -s <project>`와 session option `@agent_session_owner`. 이미 있는 session은 owner가 같을 때만 씁니다. | [tmux.py:200-220](../../codex/tools/agent-session/agent_session/tmux.py) |
| window·pane | run마다 | `new-window`, `rename-window`, `select-window`, `respawn-pane`, `kill-window`, `send-keys`(`/exit`, `Enter`) | [tmux.py:209, 266, 447, 525, 542, 563-569](../../codex/tools/agent-session/agent_session/tmux.py), [windows.py:37, 64](../../codex/tools/agent-session/agent_session/windows.py) |
| window option | run마다 | `remain-on-exit on`과 `@agent_session_*`(run 식별, 현재 run 포인터) | [tmux.py:220, 274-277, 345, 361, 412](../../codex/tools/agent-session/agent_session/tmux.py) |
| 알림 | shutdown 등 | 모든 client에 `display-message`, pane tty에 BEL | [tmux.py:458, 470-474](../../codex/tools/agent-session/agent_session/tmux.py) |
| `run-shell -b` | stop·restart 예약, Board popup | controller script 실행, `display-popup` | [tmux.py:619](../../codex/tools/agent-session/agent_session/tmux.py), [tmux_control.py:366](../../codex/tools/project-board/project_board/tmux_control.py) |
| Board option | Board를 켜고 끌 때, 크기를 바꿀 때 | server option `@project_board_enabled`, `@project_board_config`, `@project_board_width`, `@project_board_expanded`, window option `@project_board_pane`, `@project_board_restore`, pane option `@project_board_managed`, `@project_board_click_socket` | [tmux_control.py:146, 182-208, 233-237, 289-352](../../codex/tools/project-board/project_board/tmux_control.py) |
| Board pane | Board가 켜져 있을 때, client가 보는 window마다 | `split-window`로 사이드바 pane을 추가합니다. | [tmux_control.py:218-250](../../codex/tools/project-board/project_board/tmux_control.py) |
| 통합 파일이 넣는 binding·hook (`source-file`로 읽힐 때. 규칙은 3.1절) | tmux 설정을 읽을 때 | `bind-key B`, root table의 `MouseDown1Pane`, `[board]` 이름의 hook 9개(`client-attached`, `client-detached`, `client-session-changed`, `session-window-changed`, `window-created`, `window-closed`, `after-resize-pane`, `pane-died`) | [project_board.conf:3-32](../../tmux/scripts/project_board.conf) |

사용자 status 배치(`status-left`, `status-format[0]`, `MouseDown1Status`)는 통합 파일에 넣지 않습니다. 각자의 tmux 설정이 소유합니다(DIST-001 5단계). 그 내용은 [project_board_home_status.conf](../../tmux/scripts/project_board_home_status.conf)에 있고 `tmux/tmux.conf`가 같은 줄을 씁니다.

### 5.4 HOME 밖

| 위치 | 언제 | 무엇을 하는가 | 근거 |
| --- | --- | --- | --- |
| `/tmp/project-board-<uid>-<tmux pid>/` (mode 0700), `control.lock`, `<16자>.sock` | Board를 켤 때 | 잠금 파일과 클릭 전달용 unix socket. Board pane이 끝나면 socket을 지웁니다. 디렉터리는 지우지 않습니다. | [tmux_control.py:56-83, 223](../../codex/tools/project-board/project_board/tmux_control.py), [tui.py:196-223](../../codex/tools/project-board/project_board/tui.py) |
| `/tmp/as-u-<uid>-<run>.sock` | 원격 seat의 SSH 연결 | bridge socket | [remote_bridge.py:63-64](../../codex/tools/agent-session/agent_session/remote_bridge.py) |
| `/tmp/as-<uid>-<run>.sock` (원격 host) | 원격 seat run | 원격 tmux socket | [remote_runtime.py:212](../../codex/tools/agent-session/agent_session/remote_runtime.py) |
| 시스템 임시 디렉터리 `project-board-*` | Board에서 결정 답변을 보낼 때 | 답변 본문 파일. 끝나면 지웁니다. | [answer.py:36-38](../../codex/tools/project-board/project_board/answer.py) |

### 5.5 provider 쪽 부수 효과

- `start`가 Codex Leader·Worker를 시작할 때 Codex daemon이 꺼져 있으면 `codex app-server daemon start`를 실행합니다([codex.py:281-283](../../codex/tools/agent-session/agent_session/providers/codex.py), [lifecycle.py:108](../../codex/tools/agent-session/agent_session/lifecycle.py)). daemon이 Codex 쪽에 무엇을 쓰는지는 **(미확인)**입니다.
- 관리 대화가 `~/.claude`·`~/.codex` 아래에 쓰는 transcript와 설정은 provider가 소유합니다. 제품 코드의 쓰기가 아니므로 이 목록에 넣지 않습니다.

### 5.6 이 목록의 한계

- 위 검색은 `.py`와 tmux script만 봅니다. `bin/` 아래 shell launcher는 쓰기 호출이 없음을 읽어서 확인했습니다.
- 사용자가 `launch.args`로 provider에 넘기는 인자와 그 결과는 이 목록 밖입니다.
- Worker 대화가 seat 안에서 하는 작업(commit, push)은 제품 코드의 쓰기가 아닙니다.
- 인수 test가 이 표를 직접 검증하는지는 8절의 T19가 정합니다 .

## 6. 등록 파일

등록 파일의 형식은 [명세 2절](spec.md#2-등록과-프로젝트-선택)이 소유합니다. 이 절은 위치만 정합니다.

현재 코드의 선택 규칙([config.py:62-85](../../codex/tools/agent-session/agent_session/config.py)):

1. `--config`가 있으면 그 파일만 씁니다. `AGENT_SESSION_CONFIG`는 `current_project`가 같은 방식으로 씁니다.
2. 없으면 `~/.codex/project.json`과 `~/.claude/project.json` 중 있는 파일을 씁니다. 둘 다 있고 서로 다른 파일이면 `registry_ambiguous`로 거절합니다. 병합하지 않습니다.

계약: 후보에 제품 전용 위치를 더합니다.

1. `--config`, 환경 변수 `AGENT_SESSION_CONFIG`
2. 후보 셋: `~/.config/project-agent/project.json`, `~/.codex/project.json`, `~/.claude/project.json`. 있는 파일이 하나(또는 같은 파일의 여러 경로)면 그 파일을 씁니다. 서로 다른 파일이 둘 이상이면 지금처럼 `registry_ambiguous`로 거절합니다.
3. 셋 다 없으면 `registry_not_found`입니다. 오류 문구에 세 위치를 모두 적습니다.

설치의 등록 파일 초안은 후보 셋 중 어느 위치에도 파일이 없을 때만 만듭니다. 이 workstation은 기존 파일이 있으므로 초안을 만들지 않습니다. 이 규칙을 코드에 넣는 일은 코드 변경이므로 DIST-003이 합니다. 오류 문구와 `--help`의 위치 안내도 함께 바꿉니다([config.py:74](../../codex/tools/agent-session/agent_session/config.py), [project-item cli.py:19](../../codex/tools/project-item/project_item/cli.py), [registry.py:3](../../codex/tools/project-item/project_item/registry.py)).

초안은 설치 뒤 사용자의 파일입니다. `upgrade`·`rollback`은 읽거나 고치지 않습니다. `uninstall`은 지우지 않습니다(7.2절).

## 7. 명령의 동작

모든 명령은 `--dry-run`을 받습니다. `--dry-run`은 아무것도 만들지 않고 바뀔 경로를 모두 출력합니다. 출력과 실제 실행의 변경 목록이 같아야 합니다.

| 명령 | 만들거나 바꾸는 것 | 바꾸지 않는 것 |
| --- | --- | --- |
| `install` | 2절의 모든 경로, 3절의 tmux 블록, 설치 기록. 이미 설치되어 있고 같은 release면 아무것도 바꾸지 않습니다. | 4절 |
| `upgrade` | 새 `releases/<version>-<hash>/`, `current` 교체, 설치 기록의 `previous`·`current` | shim, skill link, `tmux.conf`, tmux 블록, 등록 파일, 이전 release |
| `rollback` | `current`를 설치 기록의 `previous` release로 원자적으로 교체. 교체 전의 release를 새 `previous`로 적습니다 | 위와 같음. release를 지우지 않습니다. |
| `uninstall` | 설치 기록에 있는 소유만 지웁니다(release 전체, `current`, `tmux.conf`, 설치 기록, `backup/`, shim, skill link). tmux 블록은 3절대로 지웁니다. 설치기가 만든 빈 디렉터리를 지웁니다. | 등록 파일, `<base>/agent/`, `~/.cache`의 잠금·cache, 5.1의 신뢰 기록. 지우지 않은 것은 경로를 출력합니다. |
| `check` | 읽기만 합니다. | 모든 것 |

`check`는 다음을 확인하고 실패하면 0이 아닌 코드로 끝납니다.

- 설치 기록의 모든 소유 경로가 있고, 종류와 link 대상이 기록과 같습니다.
- `current`가 존재하는 release를 가리키고, release 안의 진입점이 실행됩니다.
- tmux 블록이 기록된 파일에 있습니다. symlink 때문에 건너뛴 경우는 실패가 아니라 안내입니다.
- `~/.local/bin`이 PATH에 있습니다. 없으면 안내입니다(실패가 아닙니다).
- 건너뛴 tmux binding이 있으면 "binding 건너뜀"으로 알립니다(3.1절). 실패가 아닙니다.
- 사용자가 소유 경로를 다른 것으로 바꿨으면 그 경로를 알립니다. `upgrade`와 `uninstall`은 그런 경로를 바꾸거나 지우지 않고 알립니다. 원격 runtime의 skill link가 같은 규칙을 씁니다([remote_runtime.py:74-90](../../codex/tools/agent-session/agent_session/remote_runtime.py)) .

### 7.1 떠 있는 run

release는 run의 hook·script가 쓰는 코드입니다. run을 시작할 때 `launch.sh`, `controller.sh`, Claude의 `settings.json`에 release의 **해석된 절대 경로**(symlink를 푼 경로)와 python 경로가 들어갑니다([launch_artifacts.py:23, 35, 123, 146](../../codex/tools/agent-session/agent_session/launch_artifacts.py), [lifecycle.py:107](../../codex/tools/agent-session/agent_session/lifecycle.py)).

1. `upgrade`와 `rollback`은 떠 있는 run에 영향을 주지 않습니다. 그 run은 시작된 release를 계속 씁니다. 새 run부터 `current`가 가리키는 release를 씁니다.
2. 설치기는 사용 중인 release를 지우지 않습니다. 사용 중이란, 등록된 project의 `<base>/agent/runs/*/`의 script에 그 release 경로가 있고 그 run이 끝나지 않았다는 뜻입니다.
3. `upgrade`는 이전 release를 지우지 않습니다. 오래된 release를 정리하는 명령의 이름과 시점은 4단계가 정합니다(DIST-001 4단계는 "정리 명령은 참조를 확인한 뒤 지웁니다"라고만 적었습니다).
4. Board pane은 release에 고정되지 않습니다. 이미 실행 중인 Board process가 지워진 release의 파일을 나중에 읽는지는 **(미확인)**입니다. `upgrade` 출력은 Board를 다시 열도록 안내합니다.

### 7.2 `uninstall`의 거절

관리 run이 살아 있으면 `uninstall`을 거절합니다. 거절하면 아무것도 바꾸지 않고, 살아 있는 run의 project와 slot을 출력합니다.

- 판정 대상은 등록 파일의 모든 project입니다. 등록 파일을 읽을 수 없으면 판정할 수 없으므로 거절합니다.
- 각 slot은 [`agent_session.api.liveness`](../../codex/tools/agent-session/agent_session/api.py)로 분류합니다. `alive`와 `unknown`을 거절 근거로 봅니다. `stopped`만 통과합니다.
- shutdown 기록(`<base>/agent/suspend.json`)에 남은 slot이 있으면 거절하고 그 slot을 출력합니다. 다시 재개할 대화가 남아 있는 채로 제품을 지우지 않기 위해서입니다([suspend.py:65-66](../../codex/tools/agent-session/agent_session/suspend.py)). `liveness`가 `stopped`여도 같습니다.
- 강제 옵션(`--force`)은 두지 않습니다. 이유: 강제로 지우면 살아 있는 run의 hook과 controller가 지워진 코드를 부릅니다. 그러면 그 run에 `send`·`stop`·`restart`를 보낼 수 없습니다. 해소 방법은 run을 먼저 끝내는 것입니다(`agent-session stop`, `shutdown`).
- `liveness`의 `unknown`은 server 재시작 뒤 남은 state에도 나옵니다([api.py:73-80](../../codex/tools/agent-session/agent_session/api.py)). 이 경우도 거절합니다. 해소 방법은 `agent-session stop`으로 slot을 끝내거나 `resume`으로 재개한 뒤 끝내는 것입니다.

사용자 등록 파일(6절)은 `uninstall`이 지우지 않습니다. 설치기가 만든 초안도 같습니다. 지우려면 사용자가 직접 지웁니다. 이 때문에 제거 뒤에는 등록 파일과 그 부모 디렉터리가 남습니다.

## 8. 인수 test 명세

4단계가 구현합니다. 모든 경우에서 기대 변경 목록은 이 문서의 2·3·3.1·7절에서 얻습니다. 설치기의 설치 기록에서 얻지 않습니다.

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
| T4 | tmux 설정이 symlink(a: `~/.tmux.conf`가 다른 저장소 파일로 가는 link, b: `~/.config/tmux/tmux.conf`가 link) | `install` | 2절의 경로. tmux 파일과 link 대상은 변경 없음 | 종료 코드 0. 출력에 사실과 넣을 줄이 있음. `check`가 "수동 연결 필요"를 알림 |
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

기대 변경 목록의 "정확히"는 T1~T18과 T20~T23에 적용합니다. T19는 "5절 안"입니다. T20·T21은 binding을 읽는 server의 상태도 판정합니다. T20·T21의 binding 구현은 DIST-001 5단계에서 갖춥니다.

## 9. 이 계약과 어긋나는 현재 동작

코드는 이 CR에서 바꾸지 않았습니다. 아래는 해당 단계에서 다룹니다.

| 항목 | 현재 | 계약 | 처리 단계 |
| --- | --- | --- | --- |
| 등록 파일 위치 | `~/.codex`·`~/.claude`만 찾음([config.py:71](../../codex/tools/agent-session/agent_session/config.py)) | 6절의 세 후보 | 2단계 |
| CLI python 선택 | 개인 경로 고정([agent-session:6-10](../../codex/tools/agent-session/bin/agent-session), [project-board:5-13](../../codex/tools/project-board/bin/project-board)) | 설치 때 고른 interpreter. `project-board`는 `PYTHONNOUSERSITE=1`이므로 release 안의 package를 `PYTHONPATH`로 넣어야 함 | 2단계 |
| 원격 runtime의 skill link | 설치본이 있어도 link를 만들고 고침([remote_runtime.py:46-94](../../codex/tools/agent-session/agent_session/remote_runtime.py)) | 설치본이 있으면 만들지 않고 고치지 않음(2절 규칙 6) | 2단계(runtime의 건너뛰기), 4단계(설치의 넘겨받기) |
| tmux 통합 파일의 경로 | `~/.tmux/scripts/tmux_project_board.sh`를 고정 경로로 부름([project_board.conf:3-32](../../tmux/scripts/project_board.conf)) | `current` 아래 경로 | 5단계 |
| tmux 통합 파일의 binding | `prefix B`와 root `MouseDown1Pane`을 무조건 binding함 | 3.1절 | 5단계 |
| `tmux_decide_status.py`의 project-item 찾기 | 저장소 상대 경로([README의 실행 경로 계약 6항](README.md)) | 설치본에서도 찾음 | 5단계 |

### 9.1 7단계 안내문이 다룰 항목

설치는 project 저장소를 고치지 않습니다(4절). 아래 항목은 설치가 아니라 직원용 설치 안내문(DIST-001 7단계)이 다룹니다.

1. 제품은 등록 base의 `agent/` 아래에 파일을 씁니다(5.2절). 이 파일은 project 저장소에서 untracked로 보입니다. 대상: `state.json`, `state.lock`, `suspend.json`, `suspend.lock`, `allocation.lock`, `control/`, `runs/`, `diagnostics/`, `handoff/`, `decide/decide.html`.
2. 안내문은 사용자가 이 경로를 자기 저장소의 ignore 설정(`.gitignore` 또는 `.git/info/exclude`)에 넣도록 안내합니다. 어느 파일에 넣을지는 사용자가 정합니다.
3. 안내문은 `agent/cr/`, `agent/decide/`의 item 파일은 추적 대상이라는 점도 적습니다(`path_cr`, `path_decide`의 기본 예시는 [project-registry.example.json](project-registry.example.json)).
