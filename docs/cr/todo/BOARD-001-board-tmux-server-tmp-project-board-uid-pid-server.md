# BOARD-001: Board가 tmux server마다 만드는 /tmp/project-board-<uid>-<pid> 디렉터리를 server가 끝나도 지우지 않아 쌓입니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3

## Symptom
Board는 tmux server마다 잠금 파일과 클릭 socket을 둘 private 디렉터리 `/tmp/project-board-<uid>-<server pid>`를 만듭니다. server가 끝나도 이 디렉터리를 지우는 곳이 없습니다. 사용자 환경에서는 tmux server를 새로 띄울 때마다 하나씩 남고, test에서는 server 수만큼 수백 개가 남았습니다(TEST-004 실측: project-board suite 1회에 6개 증가).

## Evidence
- `tools/project-board/project_board/tmux_control.py:56-68` `_private_dir`: `display-message -p '#{pid}'`로 server pid를 얻어 `/tmp/project-board-{uid}-{pid}`를 `mkdir(0o700)`. 지우는 코드 없음.
- 설치 계약 5.4절 표(`docs/project-team/install-contract.md:202`): "Board pane이 끝나면 socket을 지웁니다. 디렉터리는 지우지 않습니다."
- TEST-004 Result(2026-11-09, `docs/cr/done/TEST-004-*.md`): test helper가 test server의 것을 대신 지우게 했고, 제품 결함은 범위 밖으로 남김.

## Contract
- 사용자 계정의 자원은 그것을 쓰는 대상이 끝나면 남지 않아야 합니다(운영자 항의 2026-11-09, TEST-004 Contract와 같은 원칙).

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 재현 근거가 있는 제품 결함이므로 위임 범위입니다. 근본 원인은 디렉터리의 수명이 server에 묶여 있는데 server가 끝날 때 정리할 주체가 없다는 점입니다. `kill-server`·crash에는 server 쪽에서 code를 실행할 기회가 없으므로, 디렉터리를 만드는 쪽이 server가 끝난 디렉터리를 정리하는 규칙으로 고칩니다.

## Implementation
읽을 문서: [설치 계약](../../project-team/install-contract.md) 5.4절, [project-board README](../../../tools/project-board/README.md), [README 검증 표](../../../README.md#검증).

1. 수명 규칙: `/tmp/project-board-<uid>-<pid>`는 그 pid의 tmux server가 살아 있는 동안만 둡니다. `_private_dir`가 자기 디렉터리를 만들거나 쓰기 전에, 같은 uid의 `project-board-<uid>-<pid>` 중 그 pid가 없거나 tmux server가 아닌 것을 지웁니다. 지우는 대상은 이름 형식이 맞고, 디렉터리이며(symlink 아님), 소유자가 현재 사용자이고 mode가 0700인 것뿐입니다. 안에 있는 것은 Board가 만드는 `control.lock`·`<16자>.sock`뿐이어야 하며, 다른 것이 있으면 지우지 않고 남깁니다.
2. pid 재사용: pid가 살아 있어도 tmux server가 아니면 끝난 것으로 봅니다. 판정 방법(예: `/proc/<pid>/exe`·cmdline이 tmux인지, server의 시작 시각과 디렉터리 시각 비교)을 정하고 근거를 주석에 적습니다.
3. 동시 실행: 두 Board가 같은 디렉터리를 동시에 정리해도 오류로 끝나지 않게 합니다(이미 없으면 넘어감). 살아 있는 server의 디렉터리는 지우지 않습니다.
4. 계약 5.4절 행을 새 규칙으로 고칩니다. TEST-004의 test helper가 test server 디렉터리를 대신 지우는 부분은 이 규칙과 겹치지 않는지 확인하고, 필요 없어지면 helper 쪽을 정리합니다(helper의 대조 test `test_ending_a_test_server_removes_the_runtime_directory_the_board_made_for_it` 포함).

의존: 선행 TEST-004(done). 병렬 TMUX-002(파일 겹침 없음).

위험 등급: 낮음. 사용자 `/tmp` 아래 Board 전용 이름만 다룹니다.

## Verification
README 검증 표의 `tools/project-board/**` 행(project-board suite)과, 계약 문서를 바꾸므로 link 검사·`tools/test_distribution_boundary.py`.
1. 재현(수정 전): 격리 tmux server를 띄워 Board 디렉터리를 만들게 한 뒤 server를 `kill-server`하면 디렉터리가 남고, 다음 Board 시작 뒤에도 남음.
2. 수정 뒤: 같은 절차에서 다음 Board 시작 때 끝난 server의 디렉터리가 지워짐. 살아 있는 다른 server의 디렉터리, 이름 형식이 다른 것, 다른 소유자·mode의 것, 안에 다른 파일이 있는 것, symlink는 남음. pid가 살아 있지만 tmux가 아닌 경우는 지워짐.
