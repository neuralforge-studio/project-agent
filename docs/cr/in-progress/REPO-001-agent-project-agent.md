# REPO-001: agent 저장소에서 추출한 배치를 project-agent 제품 배치로 정리하고, 저장소 진입 문서를 둡니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Requester: agent, /primehome/swain/Utils/agent/agent.base, 2026-11-09
- Base: ae2f4129292a75244f12c56394c131bb5c5637d7 2026-11-09T14:00:56+09:00

## Symptom
이 저장소는 agent 저장소에서 제품 경로만 이력과 함께 추출해 만들었습니다(agent DIST-004, 2026-11-09, `main` 5b63953). 그래서 배치가 agent 저장소의 것 그대로입니다(`codex/tools/`, `codex/skills/`, `docs/`, `tmux/scripts/`). 저장소 자체를 설명하는 진입 문서(`AGENTS.md`, `README.md`)와 test 설정도 없습니다. 배포 설치기(설치 계약)가 기대하는 release 배치가 아직 정해지지 않았습니다.

## Evidence
- 현재 tree: `codex/tools/{agent-session,project-item,project-board,python-launcher.sh,conftest.py,...}`, `codex/skills/{project-team,project-item}`, `docs/{project-team/,project-board-*.md,html}`, `tmux/scripts/{tmux_project_board.sh,project_board.conf,tmux_decide_status.py,test_tmux_decide_status.py}`
- 저장소 상대 경로를 아는 곳
  - `codex/tools/agent-session/agent_session/remote.py`의 `GUIDANCE_FILES`, `source_archive()`
  - `remote_runtime.py`의 `guidance/codex/skills`
  - `codex/tools/test_distribution_boundary.py`
  - skill·명세 문서의 상대 link
  - `tmux/scripts/tmux_project_board.sh:6`
  - `tmux_decide_status.py:46`
- 추출본 단독 test(agent DIST-004 Result): 네 suite 모두 실행됩니다. 실패 2건은 load에 민감한 timing test입니다(`test_lifecycle.py::test_codex_trust_dialog_returns_its_window_and_reuses_the_run`, `project-board test_tui.py::test_popup_renders_markdown_and_csv_and_closes_editor_after_acceptance`).
- 계획: agent `docs/cr/todo/DIST-001-project-agent.md` 3단계("`tools/{agent-session,project-item,project-board}`, `skills/{project-team,project-item}`, `docs/`, `integrations/tmux/`, `install/`, test"), 설치 계약 `docs/project-team/install-contract.md`

## Contract
- 사용자 결정(agent D-20261109-08 C, -10 A): project-agent는 다른 직원에게 배포하는 독립 저장소입니다.
- 관측 동작(CLI·JSON·파일 형식·생성 script 내용)은 바꾸지 않습니다. 도구 디렉터리 이름(`agent-session`, `project-item`)과 형제 배치, `agent_session.internal`의 entry, `python -m agent_session.remote_runtime`·`remote_bridge`는 유지합니다. 원격 실행본의 guidance 배치를 바꾸면 보내는 쪽과 받는 쪽을 같은 release 안에서 함께 바꿉니다.
- 저장소 진입 문서는 구조 지도, 실행·검증 진입점, 관련 문서를 안내합니다. 각 사실의 원본은 한 곳에 둡니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 이 CR은 agent의 승인한 계획 DIST-001 3단계의 남은 부분입니다. DIST-001은 사용자 결정 D-20261109-08 C·-09 C·-10 A로 범위를 정하고 agent `docs/cr/todo/`에 있습니다(승인). 목표 배치는 그 계획 3단계가 정했습니다. 관측 동작을 바꾸지 않는 경로·문서 정리이므로 위임 범위(승인한 작업의 하위 작업, 선례가 있는 경로·문서 정리)입니다. 진행 순서 REPO-001 → TMUX-001·INSTALL-001 → RELEASE-001은 사용자가 2026-11-09 대화에서 지시했습니다. 사용자 원문: "제안 진행 순서대로 진행". 이 저장소의 경로는 이 workstation의 떠 있는 run에 영향을 주지 않습니다. 지금 모든 관리 run과 `~/.local/bin`·skill link는 agent 저장소의 동결 사본을 씁니다(2026-11-09 `readlink ~/.local/bin/agent-session` 확인).
- 2026-11-09 Leader: 제출 77a4f2d0e95a762c6a6346193eed7326e2f4c9a4를 인수합니다. Leader review: 경로 계산만 바뀐 코드 diff, README·AGENTS, Result의 suite·link·이력 근거를 확인했습니다. 제출 commit snapshot에서 test_remote·test_remote_skills·경계 test·tmux·launcher·doc_contract·tmux_control 132개를 다시 실행해 통과했습니다. Worker 확인 요청(install-contract.md:168의 project_board_home_status.conf): TMUX-001 Contract가 사용자 status layout을 제품 밖으로 정했으므로 이 저장소로 가져오지 않습니다. 문구 정정과 제품 지도 tmux 행의 같은 파일 이름 제거는 TMUX-001 Implementation에 넣습니다.

## Implementation
읽을 문서: [제품 지도](../../project-team/README.md), [설치 계약](../../project-team/install-contract.md) 2절·6.1절, [동작 명세](../../project-team/spec.md). 이 CR의 Contract가 범위의 원본입니다.

1. `git mv`로 아래 배치로 옮깁니다. 이력이 rename으로 이어져야 합니다. 파일 이름은 바꾸지 않습니다.

   | 지금 | 새 위치 |
   | --- | --- |
   | `codex/tools/{agent-session,project-item,project-board}/` | `tools/{agent-session,project-item,project-board}/` |
   | `codex/tools/{python-launcher.sh,conftest.py,test_distribution_boundary.py,test_private_root.py,test_python_launcher.py}` | `tools/` 바로 아래 |
   | `codex/skills/{project-team,project-item}/` | `skills/{project-team,project-item}/` |
   | `tmux/scripts/` 아래 파일 4개 | `integrations/tmux/` |
   | `docs/` | 그대로 |

   빈 `codex/`와 `tmux/`는 남기지 않습니다. `install/`은 INSTALL-001이 만듭니다.
2. 저장소 상대 경로를 아는 코드를 새 배치에 맞춥니다. 경로 계산 말고 동작은 바꾸지 않습니다.
   - `tools/agent-session/agent_session/remote.py`: `GUIDANCE_FILES`를 새 경로로 바꿉니다. `source_archive()`의 저장소 root 계산(`root.parents[1]`)을 고칩니다. 실행본의 guidance 이름도 새 배치를 따릅니다(`guidance/skills/…`, `guidance/docs/project-team/…`). 그래야 skill 문서의 상대 link가 실행본 안에서 열립니다.
   - `tools/agent-session/agent_session/remote_runtime.py`: 받는 쪽의 `guidance/codex/skills`를 `guidance/skills`로 바꿉니다. `_legacy_skill`은 원격 host에 이미 있는 옛 모양(`<hash>/guidance/codex/skills/<이름>`)의 link를 계속 인식해야 합니다. 이 함수의 옛 모양 판정은 바꾸지 않습니다.
   - `integrations/tmux/tmux_project_board.sh`의 `project-board` 상대 경로와 `integrations/tmux/tmux_decide_status.py:46`의 `project-item` 경로를 고칩니다. `project_board.conf`의 `~/.tmux/scripts/…` 경로·binding·hook 이름은 TMUX-001 범위이므로 고치지 않습니다.
   - `tools/project-item/project_item/cli.py:109`가 새 배치에서 `skills/project-item/references/cr.md`를 찾는지 확인합니다.
   - 경로를 아는 test를 새 배치에 맞춥니다: `test_api_boundary.py`(agent-session·project-item), `test_remote.py`, `test_remote_skills.py`, `project-board/tests/test_tmux_control.py`, `tools/test_distribution_boundary.py`, `tools/test_python_launcher.py`.
3. 문서의 경로와 상대 link를 고칩니다. 대상은 `docs/project-team/{README,spec,install-contract}.md`, 도구 README 세 개, skill 문서(`SKILL.md`, `cr.md`, `decide.md`), `docs/project-board-*.md`입니다. 2단계에서 고친 파일을 가리키는 줄 번호 link는 다시 확인합니다. 설치 계약의 `current/integrations/tmux/project-agent.conf`는 TMUX-001이 만들 이름이므로 그대로 둡니다.
4. 저장소 진입 문서를 만듭니다.
   - `README.md`: 저장소가 무엇인지 한 단락, 디렉터리 지도(디렉터리 → 소유 문서 link), 검증 명령, 관련 문서. 구성 요소와 계약의 사실은 `docs/project-team/README.md`가 원본입니다. Root README는 그 문서를 link하고 내용을 복사하지 않습니다.
   - `AGENTS.md`: 이 저장소에서 작업하는 agent의 규칙만 씁니다. CR 위치와 도구, Contract의 호환 규칙(도구 디렉터리 이름, entry, 원격 guidance의 보내는 쪽·받는 쪽 동시 변경), 이 workstation의 떠 있는 run은 agent 저장소의 동결 사본을 쓴다는 사실(agent DIST-001 6단계까지). 검증 명령은 README 한 곳에 두고 AGENTS.md는 link합니다. 전역 지침을 다시 쓰지 않습니다.
5. 검증 진입점을 정합니다. 저장소 root에서 네 suite를 실행하는 방법을 README 한 곳에 씁니다. pytest 설정 파일을 더하면, 한 번의 실행이 suite별 실행과 같은 test를 collect해야 합니다. 같은 이름의 test module(예: 두 suite의 `test_api_boundary.py`)이 충돌하지 않게 합니다. `pytest-xdist`를 필수로 만들지 않습니다.

검토한 대안: 실행본의 guidance 이름을 옛 모양(`guidance/codex/skills`)으로 유지하는 방법은 쓰지 않습니다. 옮긴 skill 문서의 상대 link(`../../docs/…`)가 실행본 안에서 열리지 않기 때문입니다.

범위 밖: tmux 통합 파일의 내용·binding·hook 이름(TMUX-001), 설치기와 `install/`(INSTALL-001), 버전·변경 기록(RELEASE-001), agent 저장소의 동결 사본.

의존: 선행 없음. 후행은 TMUX-001, INSTALL-001, RELEASE-001입니다.

위험 등급: 중간. 바뀌는 파일이 많고 원격 실행본의 배치가 바뀝니다. 떠 있는 run은 이 저장소를 쓰지 않으며 merge revert로 되돌릴 수 있습니다. 독립 검토는 두지 않고 Leader review로 인수합니다.

## Verification
1. 기준선: Base `5b63953`의 suite 결과는 agent DIST-004 Result를 재사용합니다. 같은 tree입니다. agent-session 704개(703 통과, timing 1 실패), project-item 120 통과, project-board 114개(113 통과, timing 1 실패), 나머지 36 통과입니다.
2. 이동 뒤 같은 네 suite를 새 경로에서 실행합니다. 합격 기준은 다음과 같습니다.
   - suite마다 collect한 test 수가 기준선과 같습니다. 새로 더한 test는 수를 따로 적습니다.
   - 위 timing test 2개 말고는 모두 통과합니다. 그 2개가 실패하면 단독 실행으로 통과를 확인하고 기록합니다.
   - 4단계 README에 적은 명령 그대로 실행해 같은 결과를 냅니다.
3. 이력: 옮긴 파일 중 3개 이상에서 `git log --follow --oneline <새 경로>`의 commit 수가 이동 전과 같습니다.
4. 남은 옛 경로: `git grep -n -E "codex/(tools|skills)|tmux/scripts" -- . ':!docs/cr'`의 결과가 없거나, 남긴 줄마다 이유를 Result에 적습니다. 예를 들어 옛 원격 link 모양처럼 의도한 줄입니다.
5. 상대 link: 저장소의 모든 Markdown 상대 link가 실제 파일을 가리킵니다. 검사 명령과 결과를 Result에 적습니다.
6. 원격 실행본: `source_archive()`가 `GUIDANCE_FILES`의 파일을 빠짐없이 싣고(`is_file()`로 건너뛴 파일 0개), 이름이 `guidance/skills/…`·`guidance/docs/project-team/…`입니다. 실행본 안 skill 문서의 상대 link가 실행본 안의 파일을 가리킵니다. 옛 모양 link의 넘겨받기 test(`test_remote.py`의 legacy 경우)가 통과합니다.
7. CLI smoke: `tools/{agent-session,project-item,project-board}/bin/<도구> --help`가 종료 0입니다. 이 base에서 `tools/project-item/bin/project-item ls`의 출력이 설치된 `project-item ls`와 같습니다.

## Result
- 제출 commit: 77a4f2d0e95a762c6a6346193eed7326e2f4c9a4

`cr/REPO-001`(Base ae2f412 위 commit 1개)을 `origin/cr/REPO-001`에 push했습니다. `origin/main`은 진행하지 않아 merge는 없습니다.

변경:
- `git mv`로 `codex/tools/*`→`tools/`, `codex/skills/*`→`skills/`, `tmux/scripts/*`(4개)→`integrations/tmux/`. 빈 `codex/`·`tmux/`는 남기지 않았습니다. `docs/`는 그대로입니다.
- 코드: `remote.py`의 `GUIDANCE_FILES`(`skills/…`)와 `source_archive()`의 repo root(`root.parents[1]`→`root.parent`), `remote_runtime.py`의 받는 쪽 `guidance/skills`, `tmux_project_board.sh`·`tmux_decide_status.py`의 도구 경로. `_legacy_skill`의 옛 모양 판정은 바꾸지 않았습니다. `project_item/cli.py:109`의 `parents[3]/"skills/…"`는 새 배치에서도 그대로 맞아 바꾸지 않았습니다. 코드 주석·help 문구의 옛 경로(`Rules: skills/project-item/SKILL.md` 등)도 새 경로로 고쳤습니다.
- test: `test_api_boundary.py`(agent-session·project-item), `test_remote.py`, `test_remote_skills.py`, `test_tmux_control.py`, `test_distribution_boundary.py`의 경로·`parents[N]`. `test_remote.py`의 legacy test는 옛 모양(`guidance/codex/skills`)의 link를 직접 만들어 새 모양 bundle로 넘겨받는지 확인합니다. 새 test는 없습니다.
- 문서: Markdown 상대 link는 이동 전 위치로 해석해 새 위치 기준으로 다시 계산했습니다(스크립트). 본문의 경로 표기를 고쳤고, `docs/project-team/README.md`의 "도구별 검증 명령"은 루트 README(검증)가 원본이 되도록 link로 바꿨습니다. 그 명령 중 `codex/scripts/*` 3개(`gen_skill_metadata.py`, `check_agent_setup.py`, `test_check_agent_setup.py`)는 이 저장소에 없는 agent 저장소 소관이라 이 저장소의 검증에서 뺐습니다.
- `README.md`(저장소 설명 한 단락, 디렉터리 지도, 검증 명령 4개, 관련 문서)와 `AGENTS.md`(CR, 호환 규칙, 동결 사본 사실)를 만들었습니다. pytest 설정 파일은 더하지 않았습니다(suite별 명령 4개).

검증(Python `/primehome/tools/Inhouse/Python3/latest/bin/python3` 3.12, 저장소 root에서 README 명령 그대로):
1. 기준선: agent DIST-004 Result 재사용(같은 tree).
2. suite 결과와 collect 수:
   - agent-session `-n 8`: 704 collect, 704 통과.
   - project-item: 120 collect, 120 통과.
   - project-board: 114 collect, 113 통과, 1 실패. 실패는 기준선의 timing test `test_popup_renders_markdown_and_csv_and_closes_editor_after_acceptance`입니다. 단독 실행은 통과했습니다. agent-session의 timing test는 이번에는 통과했습니다.
   - 나머지(`integrations/tmux/test_tmux_decide_status.py` 15 + `tools/test_python_launcher.py`·`test_distribution_boundary.py` 21 + `tools/test_private_root.py` 1): 37 collect, 37 통과. 기준선의 "나머지 36"은 `test_private_root.py`를 뺀 수입니다. 이 test는 이전 README 명령에 없었으므로, 실행되지 않는 test가 없도록 4번째 명령에 넣었습니다(+1은 기존 test이고 새로 더한 test가 아닙니다).
3. 이력: 이동 전 → 이동 뒤 `git log --follow --oneline` 수는 `remote.py` 2→3, `project_item/cli.py` 8→9, `skills/project-team/SKILL.md` 21→22, `tmux_decide_status.py` 2→3, `tools/project-item/README.md` 6→7입니다. 늘어난 1은 이 제출 commit이며, 이전 이력은 rename으로 이어집니다.
4. 남은 옛 경로: `git grep -n -E "codex/(tools|skills)|tmux/scripts" -- . ':!docs/cr'` 결과는 아래 줄뿐이고 모두 의도한 줄입니다(`codex/(tools|skills)` 모양은 `~/.codex/skills`와 옛 link 모양에서만 나옵니다).
   - `~/.codex/skills/…`: provider의 사용자 skill 디렉터리(`install-contract.md`, `agent-session/README.md`, `remote_runtime.py:69`, test). 저장소 경로가 아닙니다.
   - `guidance/codex/skills/project-team`(`test_remote.py:540`): 옛 원격 link 모양의 넘겨받기 test.
   - `~/.tmux/scripts/…`(`project_board.conf`, `install-contract.md:320`, `project-board/README.md:24`): 사용자 tmux 설치 경로이며 TMUX-001 범위입니다.
5. 상대 link: scratchpad의 `checklinks.py`(`git ls-files -co`의 모든 `*.md`, 코드 블록 제외, `docs/cr` 포함)로 link 185개를 검사해 파일 누락·`.md` anchor 불일치 0개입니다. 줄 번호 link가 가리키는 파일 중 이번에 고친 파일(`remote.py`, `remote_runtime.py`, `cli.py`)은 줄 수가 바뀌지 않는 제자리 수정이라 줄 번호가 그대로입니다. 검사에서 `install-contract.md:168`의 `integrations/tmux/project_board_home_status.conf` link 1개가 누락이었습니다. 이 파일은 추출 때 옮겨지지 않았고 Base에서도 이미 끊어진 link였습니다. 내용을 지어내지 않고 link를 풀어 "agent 저장소의 파일이며 이 저장소에는 아직 없습니다. TMUX-001이 정합니다"로 바꿨습니다(Leader 확인 필요: TMUX-001에서 이 파일을 가져올지 정해 주십시오).
6. 원격 실행본: `source_archive()`가 `GUIDANCE_FILES` 8개를 모두 싣고(목록 8, 실행본 8, `guidance/skills/…` 5개·`guidance/docs/project-team/…` 3개), `test_source_archive_ships_exactly_the_listed_guidance_files`가 `is_file()` 단언으로 건너뛴 파일 0개를 확인합니다. 실행본 안 `.md` 문서의 상대 link 중 `skills/`·`docs/project-team/`을 가리키는 것은 모두 실행본 안에 있습니다. 도구 README·소스를 가리키는 link 6개(`tools/…`)는 이전과 같이 실행본에 싣지 않습니다(`remote.py` 주석: "Tool READMEs stay in the source tree"). 이 link는 guidance 범위 밖이며 test도 `skills/`·`docs/project-team/`만 확인합니다. Legacy 넘겨받기 test(`test_legacy_runtime_skill_links_can_refresh_without_claiming_other_links`)는 통과합니다.
7. CLI smoke: 세 `bin/<도구> --help` 종료 0. seat에서 `tools/project-item/bin/project-item ls`와 설치된 `project-item ls`의 출력이 같습니다(`diff` 무차이).

근거 재사용·재실행: Base `origin/main`이 진행하지 않아 merge 영향은 없습니다. suite 실행 뒤 `install-contract.md`의 link 한 줄과 README·AGENTS를 고쳤고, 영향받는 `test_distribution_boundary` 등 4번째 명령과 link 검사는 제출 commit에서 다시 실행해 통과했습니다(agent-session·project-item·project-board suite는 이 문서 수정의 영향을 받지 않아 재사용).
