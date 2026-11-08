# project-agent

Project Team·Project Item·Project Board·Agent Session의 개발 원본입니다.
세 CLI, 두 스킬, SSH 실행 묶음과 Board 전용 tmux 자산을 함께 설치합니다.
기능 위치와 공개 API는 [아키텍처](docs/architecture.md)를 참조하십시오.
Team 운영은 [스킬](skills/project-team/SKILL.md), 등록·실행 계약은
[명세](docs/project-team/spec.md)가 소유합니다.

## 다운로드와 설치

Python 3.11 이상으로 저장소를 clone하거나 압축 다운로드를 풉니다.
그 디렉터리에서 다음 명령을 실행하십시오.

```sh
python3 install.py --check
python3 install.py
```

`--check`는 제품 파일·쓰기 권한·기존 항목 충돌을 읽기 전용으로 확인합니다.
설치기는 제품 파일만 `~/.local/lib/project-agent-installs/<내용 해시>/`에 복사합니다.
`.git`, 등록, 인증, state, CR, Decision, seat는 배포에 넣지 않습니다.
설치 후 다운로드 디렉터리를 제거할 수 있습니다.
설치된 파일은 개발 원본으로 수정하지 마십시오.

| 경로 | 설치 연결 |
| --- | --- |
| `~/.local/lib/project-agent` | 내용을 검사한 복사 설치본 |
| `~/.local/bin/{agent-session,project-item,project-board}` | 안정된 제품 root의 각 `tools/<이름>/bin/<이름>` |
| `~/.local/lib/agent-session` | 안정된 제품 root의 `tools/agent-session` |
| `~/.codex/skills/{project-team,project-item}` | 안정된 제품 root의 `skills/<이름>` |
| `~/.claude/skills/{project-team,project-item}` | 같은 제품 스킬 |

`~/.local/bin`을 PATH에 넣으십시오. 설치기는 다른 원본의 링크나 일반 파일을 덮어쓰지 않습니다.
전체 skills 폴더가 외부 저장소의 symlink이면 그 저장소를 따라가 수정하지 않습니다.
해당 owner가 제품 스킬 두 항목을 위 안정 root로 연결한 뒤 설치기를 실행하십시오.
다른 스킬은 보존됩니다.
기존 CLI·API 링크의 최초 전환도 해당 환경 owner가 기존 코드를 보존한 채 준비합니다.
agent Git 원본에는 머신별 절대 링크나 clone 깊이에 고정된 외부 상대 링크를 넣지 않습니다.
agent 소유 전환 절차가 실제 제품 root를 확인하여 runtime 호환 링크를 만들고 복구합니다.
준비된 각 스킬 링크는 같은 이름의 제품 스킬을 가리켜야 합니다.
두 스킬의 대상을 서로 바꾼 링크는 준비된 연결로 인정하지 않습니다.

설치기는 실행 준비 상태를 파일 설치 가능 여부와 별도로 표시합니다.
Git·tmux·provider CLI·Board의 Textual은 사용할 기능의 실행 조건입니다.
Textual 버전은 [requirements.txt](tools/project-board/requirements.txt)가 소유합니다.
Provider 로그인·SSH 접속·원격 origin 접근은 실제 실행에서 확인합니다.
설치기는 provider를 실행하거나 인증 파일을 읽지 않습니다.

세 launcher의 기존 Python 선택 정책은 각 도구 README를 따릅니다.
Agent Session은 macOS `python3`, WSL `~/python/.venv/bin/python`,
Workstation `/primehome/tools/Inhouse/Python3/latest/bin/python3`를 사용합니다.
Item·Board는 Workstation 전역 Python, `~/python/.venv/bin/python`, `python3` 순으로 선택합니다.
Workstation에 package가 없으면 설치를 요청하십시오. 설치기는 package나 가상환경을 만들지 않습니다.
SSH seat의 host·절대 path·선택 Python은 기존 프로젝트 등록이 소유합니다.

## 갱신과 복구

새 다운로드에서 같은 설치 명령을 실행하십시오.
내용이 바뀌면 새 설치본을 준비한 뒤 안정 root를 원자적으로 전환합니다.
같은 내용의 재설치는 같은 링크를 재사용합니다.
설치 기록은 `~/.local/state/project-agent/install.json`에 보관합니다.
중간 실패에서는 이번 실행이 바꾼 제품 링크를 복원합니다.

```sh
python3 ~/.local/lib/project-agent/install.py --rollback
```

명시적 복구는 설치기가 소유한 연결만 직전 대상으로 되돌립니다.
현재 링크가 사용자가 바꾼 항목이거나 이전 대상이 사라졌으면 성공으로 보고하지 않습니다.
이전 설치본은 자동 삭제하지 않습니다.
실행 중 run·hook·controller가 기록한 절대 library 경로는 종료 전까지 필요합니다.
등록·state·CR·Decision의 소유 위치는 설치나 복구로 바뀌지 않습니다.

agent.desk 환경의 최초 전환·동결 실행본 보존·정상 인계는 별도 owner 작업입니다.
공통 AGENTS·references·provider 설정·일반 tmux 환경은 agent.desk가 소유합니다.
이 저장소의 제품 제출만으로 운영 전환이 완료되지는 않습니다.

## tmux 연결

사용자 `~/.tmux.conf`에 필요한 include만 추가하십시오.

```tmux
source-file ~/.local/lib/project-agent/integrations/tmux/project_board.conf
# 선택: 기존 status-right 뒤에 결정 알림을 추가합니다.
source-file ~/.local/lib/project-agent/integrations/tmux/project_decide_status.conf
```

Board include는 prefix `B`, pane click과 lifecycle hook을 제공합니다.
`~/.tmux/scripts`는 필요하지 않습니다. 전체 status layout과 session navigation은 사용자 설정이 소유합니다.
결정 helper는 표준 Python과 제품 API를 사용합니다.
선택 fragment는 `python3`를 호출하므로 그 Python을 실행 가능한 PATH에 두십시오.

## 개발과 검증

[Agent Session](tools/agent-session/README.md), [Project Item](tools/project-item/README.md),
[Project Board](tools/project-board/README.md)에 기능별 진입점이 있습니다.
준비된 Python을 `PY`로 선택하고 저장소 root에서 실행하십시오.

```sh
"$PY" -m pytest -q -n 8 tools/agent-session/tests tools/project-item/tests tools/project-board/tests integrations/tmux/test_tmux_decide_status.py tests/test_install.py
bash -n tools/agent-session/bin/agent-session tools/project-item/bin/project-item tools/project-board/bin/project-board integrations/tmux/tmux_project_board.sh
git diff --check
```

검증은 임시 home·등록·Git 저장소와 격리 tmux socket을 사용합니다.
부하가 높으면 [Session 검증 안내](tools/agent-session/README.md#검증)의 기존 timeout 환경변수를 사용하십시오.
설치 검증은 임의 깊이와 공백을 포함한 source·home에서 수행합니다.
다운로드 삭제 뒤 CLI·API·스킬·관리 명령, 갱신·복구와 실패 transaction을 확인합니다.
실제 provider 로그인·원격 SSH 접속과 운영 인계는 격리 검증의 PASS 범위에 포함하지 않습니다.
