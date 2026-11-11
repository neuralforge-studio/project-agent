# INSTALL-008: uninstall 뒤 crontab에 project-agent의 check 작업이 남아 조용히 실패합니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S3
- Base: 4de34cfacd698187b031fcc938bac7077d0a8a49 2026-11-12T00:11:50+09:00
- Outcome: fixed

## Symptom
SESSION-015 뒤 Leader를 시작하면 사용자 crontab에 project 구역(`check` 작업)이 생깁니다. 이 작업의 명령은 Leader를 시작한 release의 `bin/agent-session`을 가리킵니다. 설치기 `uninstall`은 crontab을 고치지 않으므로, 제거한 release를 가리키는 작업이 30분마다 남아 실패합니다. 출력은 버려지므로 실패가 보이지 않습니다.

## Evidence
- SESSION-015 Result: "`uninstall`은 crontab을 고치지 않으므로(설치 계약 5.4절에 적음) 제거한 release를 가리키는 `check` 작업이 남습니다. 출력이 버려져 조용히 실패합니다. `agent-session cron rm`으로 지웁니다. 설치기가 지우게 할지는 별도 판단이 필요합니다."
- 설치 계약 3.1절 4·5항: 통합 파일이 넣은 tmux binding·hook은 `uninstall`이 되돌리는 명령을 출력하고 실행하지는 않습니다. 실행 중인 server를 바꾸지 않는 원칙입니다.
- crontab 구역 형식과 `agent-session cron`의 원본은 [동작 명세](../../project-team/spec.md) 7절 cron입니다(SESSION-015).

## Contract
- `uninstall`(그리고 `uninstall --dry-run`)은 사용자 crontab에 남은 project-agent 구역을 찾아 알리고, 지우는 명령(project마다 `agent-session cron rm …`, 또는 같은 효과의 명령)을 출력합니다. tmux binding을 되돌리는 명령을 출력하는 방식과 같습니다. 구역 밖의 사용자 줄은 건드리지 않습니다.
- 지우기를 직접 실행할지, 출력만 할지는 설치 계약 3.1절의 원칙(실행 중 상태를 바꾸지 않음)과 맞춰 정하고 그 근거를 계약에 적습니다.
- `check`(설치 점검)는 구역의 명령이 가리키는 release가 없으면 그 사실을 알립니다.

## Disposition
- 2026-11-11 Leader: 고친다(Leader 판정). 승인한 작업(SESSION-015)에서 나온 하위 결함입니다. 제거한 설치본의 작업이 crontab에 남아 조용히 실패합니다.
- 2026-11-11 Leader: open -> todo. Leader 판정: SESSION-015 하위 결함
- 2026-11-12 Leader: 제출 b40702e를 검토했습니다. 수정 요청은 하나입니다. uninstall이 출력하는 crontab 구역 삭제 명령이 sh 문법(`text=$(crontab -l)`)이라 이 host의 login shell·tmux default-shell인 csh에서 실행되지 않습니다. csh·sh 어디서나 같은 결과를 내고 읽기 실패 시 쓰지 않는 명령으로 바꾸고, T34에서 csh로도 실행해 확인합니다. 그 밖의 구현(cron.sections·api.crontab_sections, check 알림, 7.3절 근거, 하네스, 문서)은 문제없습니다. 재제출 전 origin/main(0.10.0, ITEM-001) merge와 해당 행 재검증을 요청했습니다.
- 2026-11-12 Leader: 제출 5bd1e3e55e921fef543a6b5bd64b539aa73566ae를 인수합니다. 검토 5bd1e3e(b40702e 위에 origin/main merge 508dfc8과 수정 하나). 출력 명령을 'crontab -l > ~/.project-agent-crontab.$$ && sed ... | crontab - ; rm -f ...' 한 줄로 바꿔 csh·sh에서 같은 뜻(작은따옴표 안 $·\ 그대로, | 가 && 보다 먼저 묶임, 읽기 실패 시 쓰지 않음). 이름에 ' 또는 ! 가 있는 구역은 손으로 고치라는 안내(계약 7.3절에 근거). T34가 sh -c, csh -f -c, noclobber, 읽기 실패에서 확인. install/tests 295 passed 2 skipped, 네 번째 명령 136 passed, project-item 141 passed, api_boundary·remote·cron 124 passed. b40702e의 나머지는 앞 검토를 재사용합니다.
- 2026-11-12 Leader: in-progress -> done, Outcome fixed. 통합 b875a98 (origin/main)

## Implementation
읽을 문서: [설치 계약](../../project-team/install-contract.md) 3.1·5.4·7·8절, `install/project_agent_install/commands.py`(`uninstall`, `check`, `binding_undo`), [동작 명세](../../project-team/spec.md) 7절 cron, `tools/agent-session/agent_session/cron.py`(구역 읽기), `tools/tests/fake_crontab.py`, [project-team Worker 절](../../../skills/project-team/SKILL.md).

1. Contract를 구현합니다. 구역 해석은 `cron.py`의 형식을 따릅니다. 형식을 다시 정의하지 않습니다.
2. 설치 계약에 uninstall·check의 crontab 처리와 인수 test 번호를 더합니다.
3. Test: 구역 없음·하나·여럿, 사용자 줄 보존, dry-run, check의 없는 release 알림. 실제 crontab은 쓰지 않습니다(`fake_crontab`).

의존: SESSION-015가 통합된 뒤 시작합니다.

위험 등급: 낮음.

## Verification
1. README 검증 표의 `install/**` 행(`install/tests`)과 바꾼 문서 행.

## Result
- 제출 commit: b40702eeee572079db824b5c21c7f4080badecdc

`cr/INSTALL-008`에 push했습니다(base 4de34cf 위의 commit 하나).

**구현**
- `uninstall`(`--dry-run` 포함): 사용자 crontab의 project 구역마다 project와 작업 ID를 알리고, 그 구역만 지우는 명령을 출력합니다. 구역이 없거나 crontab이 없으면 crontab에 대해 아무것도 출력하지 않습니다. 읽지 못하면 그 사실과 `# >>> project-agent:` 줄을 찾으라는 안내를 출력하고 종료 코드는 0입니다. 끝 줄이 없거나 중복된 깨진 구역은 범위 삭제가 crontab 끝까지 지울 수 있어 명령 없이 `crontab -e`로 고치라고 알립니다.
- `check`: 구역 작업의 명령 첫 단어(절대 경로)가 없으면 project·작업 ID·경로와 `agent-session cron rm --project X --id Y`를 알립니다. 실패가 아니라 안내입니다(종료 코드 0). crontab을 읽지 못하면 그 사실을 알립니다. `crontab` 명령이 없으면 알리지 않습니다.
- 구역 해석은 `cron.py`가 소유합니다. `cron.sections`/`crontab_sections`를 더하고(시작·끝 marker 상수를 `_begin`/`_end`와 공유), 공개 이름 `agent_session.api.crontab_sections`로 냈습니다. 설치기는 `api`만 import할 수 있기 때문입니다(경계 test). api가 구역의 시작·끝 줄을 그대로 돌려주므로 설치기는 형식을 적지 않습니다. api의 import는 함수 안이라 다른 consumer의 import 비용은 같습니다.
- 새 파일 `install/project_agent_install/crontab.py`(읽기·없는 경로 판정·지우는 명령), `commands.py`의 `_crontab_notes`·`_crontab_notices`, `cli.py`가 `run_check`에 checkout root를 넘깁니다. `runs._api`는 `api_of`로 이름을 공개했습니다(설치기 모듈이 함께 씀).

**판정: 실행하지 않고 출력만 합니다**(계약 7.3절에 근거를 적음). (1) crontab은 사용자 파일이고 설치 기록의 소유가 아닙니다. 설치기가 고치는 기존 파일은 tmux include 한 줄로 한정합니다(D-20261109-09). (2) crontab은 cron이 지금도 읽는 실행 중 상태이고, 3.1절 5항(실행 중 상태를 바꾸지 않음)과 같습니다.
- 출력 명령은 `agent-session cron rm`이 아니라 `crontab -l`(실패하면 쓰지 않음) → `sed` 범위 삭제 → `crontab -`입니다. `uninstall`이 shim과 release를 지우므로 지운 뒤에는 `agent-session`을 부를 수 없기 때문입니다. 한계: 구역 앞의 빈 줄 하나는 남습니다(`agent-session cron rm`은 지웁니다). 계약에 적었습니다.

**문서**: 설치 계약 5.4절 crontab 행, 7절 `uninstall`·`check`, 새 7.3절, 8.2절 T34·T35와 "정확히" 범위(T20~T35), 동작 명세 5절 API 표(`crontab_sections`), `docs/install.md`의 uninstall 안내, README의 test 번호(T1~T35).

**Test**
- `install/tests/test_crontab.py` T34(구역 둘+사용자 줄 보존, 출력 명령 실행 뒤 구역만 사라짐, dry-run 동일·변경 없음, 정규식 문자 이름 `a.b`가 `aXb`를 지우지 않음, 구역 없음·crontab 없음, 깨진 구역, 읽을 수 없는 crontab)과 T35(없는 release 알림, 있는 진입점은 알리지 않음, 구역 없음, 읽기 실패, crontab 변경 없음). 기대 crontab 문구는 명세의 형식에서 손으로 썼습니다.
- `tools/agent-session/tests/test_cron.py`: `crontab_sections`의 구역·marker·작업, 깨진 구역(error만 담고 다른 구역은 읽음), 읽기 실패는 빈 목록이 아니라 오류.
- 하네스(`install/tests/harness.py`): `Home`이 모든 설치기 test에 `fake_crontab`을 둡니다(`check`·`uninstall`이 이제 crontab을 읽으므로 실제 crontab을 읽지 않게). `Runs`는 그 crontab을 같이 씁니다. 실제 crontab은 쓰거나 읽지 않았습니다.

**검증**(코드는 제출 commit과 같은 트리. 마지막으로 바꾼 것은 `spec.md`의 링크 한 곳이며 그 뒤 해당 test를 다시 실행했습니다)
- `python -m pytest -q -n 8 install/tests`: 289 passed, 2 skipped(새 test 6개 포함, 57분). 이 실행은 `spec.md` 링크 수정 전입니다. 그 수정은 install test의 입력(`docs`는 release에 들어가지만 test는 문서 내용을 읽지 않음)과 무관하다고 판단해 다시 하지 않았습니다.
- `python -m pytest -q -n 8 tools/agent-session/tests`: 923 passed, 1 failed(`test_git_ops.py::test_timed_out_git_releases_its_lock_and_reports_the_interruption`). host 부하로 인한 시간 의존 실패로 보입니다. 단독 재실행에서 통과(이 변경 없는 base 4de34cf에서도 통과)했고 `test_git_ops.py` 파일 전체도 37 passed였습니다.
- `tools/project-item/tests`: 125 passed. `tools/project-board/tests`: 229 passed(`api.py`를 바꿨으므로 README 표대로. 두 묶음은 같은 basename `test_cli.py` 때문에 따로 실행).
- `tools/test_distribution_boundary.py`, `tools/agent-session/tests/test_remote.py`, `test_api_boundary.py`: 74 passed. 처음 실행에서 `spec.md`의 새 행에 건 `install-contract.md` 링크가 원격 guidance 목록에 없어 `test_remote` 2개가 실패했습니다. 링크를 문구로 바꿔 통과했습니다.
- 문서 상대 link: 바꾼 문서의 새 link는 `docs/install.md`→계약 7.3절 anchor 하나이며 제목과 맞습니다.
- 위험 등급 낮음(Contract에 적힌 동작은 `uninstall`·`check`의 출력만이고 crontab 쓰기는 없음).

**알려 둘 점**
- 이 Worker 시작 prompt는 `self-check.md`의 Worker 절대로 `CronCreate`로 자기 점검을 등록하라고 했으나, 그 문서(SESSION-015 이후)는 "Worker는 점검을 스스로 등록하지 않으며 session cron(`CronCreate`)을 쓰지 않는다"고 정합니다. 문서를 따라 등록하지 않았습니다. prompt 템플릿이 옛 방식으로 남은 것으로 보입니다(project-team의 시작 prompt 갱신은 이 CR의 범위 밖이라 건드리지 않았습니다).
- 검증 중 `git stash`를 한 번 써서 작업 트리를 12초쯤 되돌렸다가 복구했습니다(커밋 내용에는 영향이 없고, 그 사이 돈 agent-session 전체 실행은 버리고 다시 했습니다). 또 base와 비교하려 임시 worktree를 만들었다가 바로 지웠습니다(`git worktree list`는 seat 하나뿐).

### 수정 제출: csh에서 실행되는 삭제 명령
- 제출 commit: 5bd1e3e55e921fef543a6b5bd64b539aa73566ae

Leader 검토(b40702e)의 요청 하나를 반영하고 `origin/main`(0.10.0, ITEM-001, CR 문서)을 merge했습니다(충돌 없음, merge 508dfc8 + 수정 5bd1e3e를 `cr/INSTALL-008`에 push).

**수정**: `uninstall`이 출력하는 구역 삭제 명령을 csh·tcsh와 sh·bash·zsh에서 같게 동작하는 한 줄로 바꿨습니다.
```
crontab -l > ~/.project-agent-crontab.$$ && sed '<구역 범위 삭제>' ~/.project-agent-crontab.$$ | crontab - ; rm -f ~/.project-agent-crontab.$$
```
- 읽기가 실패하면 `&&` 때문에 쓰지 않습니다. 저장 파일은 HOME 안에 shell의 PID(`$$`, 두 shell 모두 PID)로 이름을 지어 csh `noclobber`와 부딪치지 않고(요청이 말한 "기존 파일에서 멈춤" 대신 충돌 자체를 피함), 끝에 `;` 뒤의 `rm -f`로 항상 지웁니다. 임시 파일을 world-writable `/tmp`에 두지 않은 것은 미리 정할 수 있는 이름의 symlink 공격을 피하려는 것입니다.
- script에는 `!`를 두지 않습니다. 이름에 `'` 또는 `!`가 있는 project의 구역은 두 shell이 다르게 읽어 한 명령이 같은 뜻이 될 수 없으므로 명령 없이 `crontab -e`로 손으로 고치라고 알립니다(깨진 구역과 같은 처리, `crontab.by_hand`). 이 점은 요청에 없던 판단이라 알립니다.
- 계약 7.3절의 명령 설명과 8.2절 T34 행을 맞췄습니다.

**Test**(`install/tests/test_crontab.py`): T34가 출력 명령을 `sh -c`, `csh -f -c`, `csh -f -c 'set noclobber; …'`로 각각 실행해 구역만 사라지고 사용자 줄이 보존됨을 확인합니다(csh가 없으면 csh 경우만 skip. 이 host에는 있어 실제로 실행됨). 정규식 문자 이름(`a.b`)은 csh로도 확인합니다. crontab을 읽지 못하는 상태에서 세 shell 모두 쓰지 않고 저장 파일도 남기지 않는 것, `'`·`!` 이름은 명령이 없는 것도 확인합니다. 실행 뒤 HOME에 저장 파일이 남지 않았는지도 매번 봅니다.

**검증**(제출 commit과 같은 트리, README 표와 Leader의 안내 기준)
- `python -m pytest -q -n 8 install/tests`: 295 passed, 2 skipped(40분).
- 네 번째 명령(`integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py`): 136 passed.
- `tools/project-item/tests`: 141 passed(ITEM-001 포함). `tools/agent-session/tests/test_api_boundary.py`·`test_remote.py`·`test_cron.py`: 124 passed(`spec.md`는 이번에 고치지 않았고, 고친 문서는 설치 계약뿐이며 새 link는 없습니다).
- 그 밖의 agent-session·project-board 결과는 입력이 바뀌지 않아 앞선 제출의 것을 재사용합니다(agent-session 923 passed, 1 failed는 `test_git_ops` 시간 의존 test로 단독·base·파일 전체 통과. project-board 229 passed).
