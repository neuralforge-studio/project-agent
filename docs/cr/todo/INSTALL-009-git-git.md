# INSTALL-009: 설치기가 느린 git을 'git을 실행할 수 없음'으로 판정해 부하에서 설치를 거절

- Opened: 2026-11-13
- Scope: project-agent
- Severity: S1

## Symptom
2026-11-13에 0.12.0 release를 검증했습니다(clone, release commit 4e9044f, host load 약 65, TMPDIR는 NFS). `python -m pytest -q -n 8 install/tests`가 1 failed, 317 passed, 2 skipped였습니다.
- 실패한 test: `install/tests/test_principles.py::test_a_tmux_file_with_a_second_hard_link_is_not_rewritten`
- 설치기 출력: `git_unavailable: Cannot run git: Command '['git', '-C', '<source>', 'status', '--porcelain=v1', '-z', '--untracked-files=all']' timed out after 60 seconds`
git은 정상으로 있었고, 명령이 60초 안에 끝나지 않았을 뿐입니다. 그런데 설치기는 "git을 실행할 수 없다"고 판정하고 설치를 거절했습니다.

## Evidence
- `install/project_agent_install/release.py:52-60` `_git`은 `subprocess.run(..., timeout=60)`를 씁니다. `TimeoutExpired`는 `SubprocessError`이므로 `OSError`와 같은 갈래로 잡혀 `git_unavailable`("Cannot run git")이 됩니다.
- 설치기 제품 코드에는 이 밖에도 숫자로 고정한 한도가 흩어져 있습니다.
  - `commands.py:641`·`:654`: 60초.
  - `commands.py:677`: 30초.
  - `bundle.py:98`: 120초.
  - `release.py:124`: 30초.
  - `tmuxrecord.py:45`: 10초, `:58`: 30초.
  - `rustbuild.py:128`: `TIMEOUT`.
  이 한도들의 원본, 근거, 그리고 넘겼을 때의 판정이 한곳에 정해져 있지 않습니다.
- 사용자는 이 workstation(NFS, 평소 load 50~150)에서 `upgrade`를 실행합니다. 같은 일이 실제 upgrade에서 생기면 설치가 잘못된 이유로 거절됩니다.
- 같은 모양(제품 코드의 숫자 한도)이 다른 도구에도 있습니다. 예: `tools/project-item/project_item/branch.py`의 `GIT_TIMEOUT = 120`. 이번 CR의 범위는 설치기이고, 다른 도구의 것은 Result에 목록으로 남깁니다.

## Contract
1. 설치기가 부르는 외부 명령(git, python, tmux, ldd, cargo, 설치한 도구의 `--help`·`--version`)의 한도는 "끝나지 않는 것"을 막는 용도로만 씁니다. host가 느리다는 이유로 정상 명령이 실패하지 않게 합니다. 한도가 필요한 곳과 필요 없는 곳은 근거를 두고 정합니다.
2. 한도의 값과 근거는 설치기 안의 원본 하나에서 나옵니다. 호출하는 곳마다 숫자를 따로 두지 않습니다.
3. 한도를 넘기면 "실행할 수 없음"과 구별되는 오류로 보고합니다. 오류에는 어느 명령이 몇 초를 넘겼는지가 나옵니다.
4. 설치 계약의 오류 표(오류 code와 뜻)를 새 판정에 맞게 고칩니다. 새 오류 code가 생기면 계약과 test에 함께 넣습니다.

## Disposition
- 2026-11-13 Leader 판정: 고칩니다. 0.12.0 release 검증을 막은 제품 결함이고, 사용자의 실제 upgrade에서도 같은 거절이 날 수 있습니다.
  - 근본 원인: 설치기의 외부 명령 한도가 근거 없는 숫자로 흩어져 있습니다. 또 한도 초과를 "실행할 수 없음"으로 잘못 판정합니다.
  - release를 막는 항목이므로 바로 시작합니다.
- 2026-11-13 Leader: open -> todo.

## Implementation
읽을 문서:
- [설치 계약](../../project-team/install-contract.md): 오류 표, 검사(`check`), 8절 test 목록.
- [README 검증](../../../README.md#검증).
- 코드: `install/project_agent_install/`(`release.py`, `commands.py`, `bundle.py`, `tmuxrecord.py`, `rustbuild.py`), `install/tests/`.
- 절차: [project-team Worker 절](../../../skills/project-team/SKILL.md#worker).

1. 설치기의 외부 명령 호출을 모두 찾아 목록으로 만듭니다. 각 호출에 대해 한도가 왜 필요한지(멈출 수 있는 이유), 그리고 넘기면 어떻게 판정할지를 정합니다.
2. 한도의 원본을 하나로 모읍니다. 근거는 그 원본의 주석에 적습니다.
3. 한도를 넘기면 별도 오류로 보고합니다(어느 명령이 몇 초를 넘겼는지). "git을 실행할 수 없음" 같은 판정은 실제로 실행할 수 없을 때만 냅니다.
4. 설치 계약의 오류 표와 test를 맞춥니다.
5. Test (관측 동작):
   - 느린 명령(fake git 등)이 한도 안에 끝나면 설치가 성공하는지 확인합니다.
   - 끝나지 않는 명령은 한도에서 "한도 초과" 오류와 명령 이름·초를 내는지 확인합니다.
   - 실행할 수 없는 명령은 지금처럼 "실행할 수 없음"인지 확인합니다.
   - test의 기다림은 `tools/tests/wait_limit.py`를 따릅니다(TEST-016). `tools/test_wait_limits.py`가 통과해야 합니다.
6. 다른 도구 제품 코드의 같은 모양(숫자 한도, 한도 초과의 판정)을 목록으로 Result에 적습니다. 고치지는 않습니다.

위험 등급: 중간(설치기 오류 판정과 계약 변경).

## Verification
- README 검증 표 `install/**`: `python -m pytest -q -n 8 install/tests`.
- 문서를 고치면: 고친 문서의 상대 link 검사, `python -m pytest -q tools/test_distribution_boundary.py`.
- 네 번째 명령의 `python -m pytest -q tools/test_wait_limits.py`.
- 재현: 끝나지 않는 fake git으로 수정 전 commit이 `git_unavailable`을 내는 것과, 제출 commit의 판정을 Result에 적습니다.
