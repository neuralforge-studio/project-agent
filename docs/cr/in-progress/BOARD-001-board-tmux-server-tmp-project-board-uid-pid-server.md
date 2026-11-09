# BOARD-001: Board가 tmux server마다 만드는 /tmp/project-board-<uid>-<pid> 디렉터리를 server가 끝나도 지우지 않아 쌓입니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3
- Base: 5b5816d7ca39e37cb36b5ff45292ac8e81f2f863 2026-11-09T19:26:13+09:00

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
- 2026-11-09 Leader: 제출 5be5f6d5b317b46a954bebe765171dbbb15021b8를 인수합니다. Leader review: reap_runtime_directories의 대상 한정(이름 형식·디렉터리·내 소유·0700·내용이 control.lock과 16자 .sock뿐, 하나라도 다르면 전체 남김)과 끝난 server 판정(ESRCH·EPERM, tmux 아님, 디렉터리 mtime+2초보다 늦게 시작=pid 재사용; 애매하면 남김)을 확인했습니다. 수정 전 재현과 새 test 4개(남길 것 10종, 동시 정리 포함), project-board suite 119 passed·경계 test 9 passed. README 표대로 해당 suite만 실행.

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

## Result
- 제출 commit: 5be5f6d5b317b46a954bebe765171dbbb15021b8

변경 (`origin/cr/BOARD-001`, Base 5b5816d 위 commit 1개. 시작 뒤 `origin/main`은 진행하지 않았습니다):
- `tools/project-board/project_board/tmux_control.py`: `_private_dir`가 자기 디렉터리를 만들기 전에 `reap_runtime_directories()`를 부릅니다. 지우는 대상은 이름이 `project-board-<내 uid>-<pid>` 형식, lstat이 디렉터리(symlink 아님)·내 소유·mode 0700이고, 안에 `control.lock`(일반 파일)·`<16자 hex>.sock`(socket)만 있는 것입니다. 다른 이름·종류가 하나라도 있으면 디렉터리 전체를 남깁니다. 어떤 OSError도 호출자에게 올리지 않고 그 디렉터리를 넘깁니다(동시 정리로 이미 없어진 경우 포함).
- 끝난 server 판정(`_is_tmux_server_of`): ① `kill(pid, 0)`이 ESRCH·EPERM이면 끝남(다른 사용자의 process는 내 server가 아님). ② 살아 있으면 `ps -o etime=,comm=`로 command 이름이 `tmux*`가 아니면 끝남. ③ tmux여도 시작 시각(now − etime)이 디렉터리 mtime + 2초보다 늦으면 pid를 물려받은 다른 process이므로 끝남. 근거는 코드 주석: 디렉터리는 server가 뜬 뒤에 만들고 server가 끝난 뒤에는 아무도 쓰지 않으므로, 마지막 변경보다 늦게 시작한 process는 만든 server일 수 없습니다. etime이 초 단위로 내림되므로 2초 여유를 둡니다. 판정이 어긋날 때는 살아 있는 쪽(남김)으로 기웁니다. `ps`는 Linux·macOS 공통이라 `/proc`에 기대지 않습니다.
- 계약 5.4절 행(`docs/project-team/install-contract.md`)을 새 규칙으로 고치고 줄 번호 link를 갱신했습니다.
- test helper(`tools/tests/tmux_test_server.py`)의 정리와 대조 test `test_ending_a_test_server_removes_the_runtime_directory_the_board_made_for_it`는 그대로 둡니다. 제품은 끝난 server의 디렉터리를 **다음 Board 명령에서** 지우므로, test가 끝난 직후 남지 않게 하려면 helper의 즉시 삭제가 여전히 필요합니다(둘은 같은 디렉터리를 지울 뿐 충돌하지 않고, 이미 없으면 `rm -rf`·FileNotFoundError로 넘어갑니다). 주석만 "제품이 지우지 않는다"에서 현재 사실로 고쳤습니다.

검증:
1. 수정 전 재현(HEAD 사본 `project_board`로, test server A·B를 띄워 각자 `_private_dir` 호출 → A `kill-server` → B에서 `_private_dir`): A의 디렉터리가 **남음**(`exists() == True`). 수정 뒤 같은 절차: **지워짐**(`False`). B의 것은 남음.
2. 새 test 4개 (`tools/project-board/tests/test_tmux_control.py`, 격리 root로 실제 `/tmp`에 영향 없음):
   - `test_next_board_start_removes_the_directory_of_a_server_that_was_killed`: kill-server 직후에는 남고, 살아 있는 다른 server의 다음 Board 호출에서 지워지며 그 server 것은 남음.
   - `test_sweep_removes_directories_of_ended_servers_and_of_pids_tmux_no_longer_holds`: 죽은 pid(내용 있음·없음), 살아 있지만 tmux가 아닌 pid, 살아 있는 tmux지만 디렉터리보다 늦게 시작한 pid(mtime을 1시간 전으로)는 지워지고, 살아 있는 tmux server의 것(lock·sock 포함)은 남음.
   - `test_sweep_leaves_everything_that_is_not_an_ended_boards_own_directory`: 다른 파일이 든 것, 일반 파일인 `.sock`, 하위 디렉터리가 든 것, mode 0755, 다른 uid 이름, symlink(대상 포함), 형식이 다른 이름 5종은 남고 반환 목록이 비어 있음.
   - `test_concurrent_sweeps_of_the_same_directory_both_finish`: 4 thread가 같은 디렉터리를 20회 동시에 정리해도 예외 없이 끝남.
3. `python -m pytest -q tools/project-board/tests` → 119 passed. `python -m pytest -q tools/test_distribution_boundary.py` → 9 passed. `install-contract.md`의 상대 link 전부 존재. README 표상 `tools/project-board/**` 행과 문서 행만 해당합니다. 공유 test helper는 주석만 바꿨고 동작이 같아 다섯 명령 전체는 돌리지 않았습니다.
4. 기존 test `test_ending_a_test_server_removes_...`는 실제 `/tmp`를 쓰므로 실행 중 이 계정의 끝난 server 디렉터리 318개(이전 test가 남긴 것)를 새 규칙대로 지웠습니다. 살아 있는 server 것 1~2개는 남았습니다.
5. 정리: 내가 만든 임시 socket(`probe-*`)·scratchpad 외 남긴 process·파일 없음.
