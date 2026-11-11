# BOARD-025: CR·결정 창이 열리고 내용이 보이기까지 느립니다

- Opened: 2026-11-11
- Scope: project-agent
- Severity: S2
- Base: 75e2891a6deb1fa620822778073cfbf2f76ab490 2026-11-11T14:21:39+09:00
- Outcome: fixed

## Symptom
사용자 보고(2026-11-11, 0.8.0): "decision cr 내용 load하는 것도 엄청 느리네."

## Evidence
- `tools/project-board/bin/project-board`는 `sync`·`click`·`toggle`만 시동 번들(`python -S`, bundle)로 실행합니다. CR 창(`cr`)과 결정 창(`popup`)은 `python -m project_board`로 실행해서 site 단계와 Textual import를 NFS에서 읽습니다. BOARD-016 측정에서 popup을 여는 데 16×16에서 1.2초가 걸렸고, Textual을 번들에 넣은 시제품(A7)은 0.81초였습니다.
- BOARD-020: 창이 떠 있을 때 sidebar에서 다른 항목을 누르면 `respawn-pane -k`로 창 process를 새로 시작합니다. 누를 때마다 Python과 Textual 시동을 다시 합니다. BOARD-020 Worker는 test server에서 CR 창이 시작하는 데 약 10초 걸렸다고 적었습니다(host 부하).
- BOARD-021:
  - CR 창은 `popup_snapshot(project_id, done=True)`로 연 project의 CR과 done 목록을 읽습니다.
  - 결정 창은 다른 project의 결정 여부를 background에서 전체 snapshot으로 읽습니다. 실제 등록 10개에서 cold 약 5초 걸리고, 그동안 ◀▶가 꺼져 있습니다.
- 본문은 Textual `Markdown` widget으로 그립니다. 긴 CR(표와 Result가 긴 것)을 그리는 비용은 재지 않았습니다.
- host load는 최근 87~111이었습니다(BOARD-022).

## Contract
1. 창이 이미 떠 있을 때 sidebar에서 다른 CR·결정을 누르거나 창 안에서 항목·project를 바꾸면, 새 내용이 0.5초 안에 보입니다. 측정 조건은 실제 등록과 같은 규모이고, host load를 함께 적습니다.
2. 창을 처음 열 때 목록과 첫 본문이 보이기까지의 시간을 줄입니다. 남는 시간에는 근거가 있어야 하고, 기다리는 동안 무엇을 읽는 중인지 창에 보입니다.
3. 화면 모양과 동작은 0.8.0 이후 통합된 것과 같습니다. 대상은 BOARD-020(떠 있는 창, 위치·크기 유지), BOARD-021(네 묶음, ◀▶), BOARD-024(Ctrl+J)입니다.

## Disposition
- 2026-11-11 Leader: 고친다(Leader 판정). 사용자가 보고한 느림입니다. 먼저 단계를 나눠 원인을 확인하고, 줄일 수 있는 비용을 줄입니다.
- 2026-11-11 Leader 판정(방향): 창이 이미 떠 있으면 process를 새로 띄우지 않고 떠 있는 창에 내용을 바꾸라고 알립니다(Contract 1). 처음 여는 비용은 시동 번들처럼 이미 있는 방식을 먼저 씁니다. 측정 결과가 다른 원인을 가리키면 Result에 근거를 적고 그에 맞게 고칩니다.
- 2026-11-11 Leader: open -> todo. Leader 판정: 사용자 보고 느림
- 2026-11-11 Leader: 떠 있는 창에 새 내용을 알리는 경로는 Python 밖의 client(BOARD-018 Rust sidebar)도 쓰는 규약으로 만듭니다. socket 위치는 pane option에 두고, 한 줄 JSON 메시지로 보냅니다. Board TUI 계획 문서에 적고 test로 지킵니다.
- 2026-11-11 Leader: 제출 50787757bcc6c9e3d8ff87132b17a178584472b9를 인수합니다. 검토 5078775(구현 ddbadbb·ec52698·e6697ff + main merge들, 마지막 merge는 TEAM-002·문서). 원인 분해(NFS 모듈 읽기, 창마다 respawn, 쓰지 않는 파일 읽기, 긴 Markdown과 접힌 Done 행), cr·popup 시동 번들(Textual과 의존 package, dist-info guard, 못 찾으면 python -m으로 재실행), window_link 규약(계획 5절, raw client test), _popup 재사용·busy·죽은 process·종류 변경, 읽는 범위 only, 긴 CR 첫 절 먼저, 접힌 묶음 지연 mount와 Done 제목 지연을 읽었습니다. 검증: project-board 228 + api_boundary 4(e6697ff), 네 번째 명령 136, install/tests 283(번들 변경 포함 이전 tree)과 merge 뒤 test_install 97·test_bundle 16·관련 23. merge가 입력을 바꾸지 않은 명령의 재사용 판정을 인정합니다. A/B(load 49~64): 처음 열기 6.05→1.97초, 떠 있는 창 전환 CR 6.16→0.93초·결정 5.10→0.89초. Contract 1의 0.5초는 미달(0.66~0.98초)이며, 남은 click 경로의 tmux 호출은 BOARD-018(Rust sidebar)이 규약 socket을 직접 쓰는 것으로 다룹니다.
- 2026-11-11 Leader: in-progress -> done, Outcome fixed. 통합 75285ec (origin/main). 0.8.2 release gate에서 부하로 실패한 test_cr_window_scrolls_to_the_pressed_group_first의 scroll 대기도 이 CR이 고쳤습니다.

## Implementation
읽을 문서:
- `tools/project-board/bin/project-board`, `tools/python-launcher.sh`, `tools/bundle_boot.py`, `install/project_agent_install/`의 번들 생성
- `tools/project-board/project_board/tmux_control.py`(`_popup`, `_window_command`, `open_popup`, `open_cr_popup`)
- `tui.py`(`CRPopupApp`, `PopupApp`, `run_cr_popup`, `run_popup`), `model.py`(`popup_snapshot`, `snapshot`, `done_items`, `read_cr_markdown`)
- BOARD-016 Result 2절(A7 번들, popup process 재사용 추정), BOARD-020·021 Result
- [설치 계약](../../project-team/install-contract.md), [Board TUI 계획](../../project-board-tui-plan.md), [project-team Worker 절](../../../skills/project-team/SKILL.md)

1. 단계 분해: 실제 등록(읽기만 함)과 test tmux server(`tools/tests/tmux_test_server.py`의 claim·release)에서 다음을 잽니다. 반복 3회이고 load를 함께 적습니다.
   - 경우: 처음 열기(CR, 결정), 창이 떠 있을 때 sidebar에서 다른 항목, 창 안 항목 바꾸기, ◀▶
   - 단계: 클릭에서 pane 생성, Python과 Textual 시동, 목록 읽기, 첫 그림, 본문 읽기, Markdown 그림
2. 원인을 Result에 적고 고칩니다. 후보:
   - 떠 있는 창 process에 새 내용을 알리는 경로(click socket과 같은 방식). `respawn-pane`은 창이 죽었을 때만 씁니다.
   - `cr`·`popup`의 시동 번들. 설치 계약과 release 검증에 미치는 영향을 적습니다.
   - 본문 읽기와 그리기 줄이기
   - 결정 창 ◀▶용 전체 snapshot 비용 줄이기
3. 기다리는 동안 창에 "읽는 중" 상태를 보입니다(Contract 2).
4. Test: Contract 1의 경로(떠 있는 창 재사용, 창이 죽었을 때 새로 띄우기)와 Contract 3의 동작 유지를 확인합니다.

의존: 없음.
- BOARD-022가 `tmux_control.py`를 고치고 있고 곧 통합됩니다. BOARD-018이 sidebar를 Rust로 옮기는 중입니다(popup은 Python으로 남음).
- 제출 전에 `origin/main`을 merge합니다.

위험 등급: 중간.

## Verification
1. README 검증 표에서 바꾼 경로의 행 명령 전부를 실행합니다. `tools/project-board/**`, `install/**`(번들을 바꾸면), `tools/python-launcher.sh`·`tools/bundle_boot.py`(바꾸면) 행입니다.
2. A/B: 0.8.0과 이 CR로 Contract 1의 대표 경우(창이 떠 있을 때 다른 항목)와 처음 열기(CR 창)를 번갈아 3회 잽니다. wall과 95% 구간을 적습니다. test는 측정과 동시에 돌립니다.

## Result
- 제출 commit: 50787757bcc6c9e3d8ff87132b17a178584472b9

`origin/cr/BOARD-025`에 push했습니다. `origin/main`(BOARD-022, 0.8.1, BOARD-026, TEAM-002)을 merge한 상태입니다.

### 1. 원인 (측정)
창을 여는 시간의 대부분은 CPU가 아니라 NFS의 모듈 파일 하나하나를 여는 대기입니다(load 100~190, 이 host 64 core).

| 단계 | 측정 |
| --- | --- |
| `python -c pass` | 0.4~1.1초 |
| `import textual.app, textual.widgets` | wall 12~22초, **user+sys 0.8초**. 모듈 366개(textual·rich·markdown_it 등 182개) |
| `import project_board.tui` | 18~22초 |
| `import project_board.model` | 3.7~6.2초 |
| 같은 import를 시동 번들(Textual 포함)에서 | **1.5~1.9초**(wall), user 0.5초 (load 120). 3회 |
| `popup_snapshot`(fc2_cpu 44 CR + 결정) 전부 / CR만 / 결정만 | 1.66 / 0.56 / 1.38초 (agent: 0.6 / 0.10 / 0.83초) |
| 결정 전체 snapshot(등록 10개, 창의 ◀▶용) | cold 약 16~22초. decide 파일 parse가 11.6초, CR 3.8초, state 0.5초 |
| Markdown widget 그리기(CR 179줄) | CPU 1.8초(반복해도 같음). 블록 약 200개의 layout이 지배(cProfile) |
| 목록 mount(Done 1476개, 접혀 있어도) | 2.5초 + Done 제목 읽기 CPU 1.3초(19초 wall) |

즉 (1) 창을 새로 띄울 때마다 Python+Textual 시동에 수십 초가 들었고(BOARD-020의 `respawn-pane -k`가 클릭마다 반복), (2) 창이 뜬 뒤에도 쓰지 않는 파일(CR 창이 결정·state, 결정 창이 CR·state)을 읽었고, (3) 긴 CR의 Markdown과 접힌 Done 행의 layout이 CPU를 썼습니다.

### 2. 변경
1. **`cr`·`popup`을 시동 번들로 시작**: 설치기 `bundle.py`가 Textual과 의존 package(rich, markdown_it, pygments, mdurl, linkify_it, platformdirs, typing_extensions) 모듈 약 290개(번들 8 MB)를 같은 번들에 씁니다. 각 항목은 소유 package의 `*.dist-info` 경로를 5번째 값으로 가지고, reader(`bundle_boot.py`)는 그 디렉터리가 있을 때만 서빙합니다(package를 올리거나 지우면 설치된 package에서 import). `bin/project-board`의 `cr`·`popup`(`--config X` 앞에 와도)은 `python -S`로 시작해 `<sys.prefix>/lib/pythonX.Y/site-packages`를 경로 끝에 더하고, textual을 못 찾으면 같은 인자로 `python -m project_board`로 다시 실행합니다(venv `--system-site-packages`로 확인). 설치 계약 6.1절 갱신. 번들 header 형식은 항목에 선택 값 하나를 더했을 뿐이라 기존 3-tuple header·reader는 그대로입니다.
2. **떠 있는 창에 알리기**(Contract 1): `window_link.py`(한 줄 JSON 규약)와 `tmux_control._popup/_reuse`. 같은 종류(cr|decision)이고 창 process가 듣고 있으면 새 process 없이 알립니다. 시작 중이면 20초까지 기다리고, 종류가 다르거나 연결이 안 되면(죽은 process) `respawn-pane -k`로 같은 pane을 다시 시작합니다. 답변을 보내는 중이면 `busy`로 거절하고 창을 바꾸지 않습니다(보내는 답변 보호). 규약(pane option `@project_board_window_kind`·`@project_board_window_link`, 요청·응답·실패 처리·시작 명령)은 **Board TUI 계획 5절 "열려 있는 창에 새 내용 알리기"**가 소유합니다(Leader 추가 요구: Rust sidebar도 같은 규약). test: 창 쪽 `test_window_protocol.py`(`window_link`를 import하지 않는 raw socket client), client 쪽 `test_tmux_control.py::test_a_client_that_follows_the_plan_with_raw_tmux_and_a_socket_reaches_the_window`(raw tmux 명령과 socket).
3. **읽는 중 표시**(Contract 2): 창 pane은 시작하자마자(Python이 뜨기 전) `Board 창을 시작하는 중…`을 출력합니다. 화면에는 `읽는 중…`(제목·본문), 새 항목을 받으면 같은 문구, 결정 창의 ◀▶ 준비 중에는 `◀▶로 이동할 다른 project의 결정 항목을 읽는 중…`을 보입니다.
4. **읽는 범위 줄이기**: `model.project_view/snapshot/popup_snapshot(only=...)`. CR 창은 CR만(`ONLY_CRS`), 결정 창은 결정만(`ONLY_DECISIONS`)을 읽고, ◀▶용 `decision_snapshot`은 결정만 읽습니다(state·CR·seat 안 읽음). CR 창은 뜬 뒤 다른 project의 CR을 한 project씩 미리 읽어(`_warm`, cache 재사용) 다음 클릭이 읽힌 파일을 찾습니다.
5. **긴 CR은 첫 화면부터**: 30줄을 넘어 첫 `## ` 절 경계까지를 먼저 그리고(`cr_head`), 그린 뒤 전체 문서로 바꿉니다(최종 DOM은 같음. Textual `Markdown.append`는 블록 하나를 잃어 쓰지 않았습니다, 실험으로 확인).
6. **접힌 그룹의 행은 펼 때까지 mount하지 않고, Done 제목 읽기도 Done을 펼 때 시작합니다**(Leader가 BOARD-026 Worker의 지적으로 물은 항목: 측정으로 판단). balvian(Done 1476): 목록 apply+render 2.5초+제목 읽기 CPU 1.3초(10초 동안 CPU 5.4~5.8초) → 1.2초(10초 동안 1.15초). fc2_cpu(231): 2.1초 → 0.77초. 제목 읽기만 미루는 안은 CPU 1.3초 절감에 그쳐 행 mount까지 미루었습니다.

### 3. 화면·동작이 달라진 점(Contract 3)
- 창이 떠 있으면 process가 같으므로 **보내지 않은 답변(draft)이 결정 창에 남습니다**(옛 동작은 `respawn`으로 사라짐). `◀▶`로 옮길 때와 같은 규칙입니다.
- 접힘 상태는 창 단위로 유지됩니다(BOARD-026 규칙 그대로, 새 내용을 받아도 `collapsed`를 바꾸지 않음).
- 접힌 그룹의 행이 DOM에 없으므로(이전: 숨김) 펼 때 mount합니다. 보이는 모양은 같습니다.
- 다른 종류 창(CR↔결정)으로 바꿀 때는 그 pane의 process를 다시 시작합니다(종류별 process). 시동은 번들로 줄었습니다.
- 결정 창 ◀▶는 첫 읽기 뒤 background에서 준비됩니다(이전과 같음). 준비 중 문구가 새로 보입니다.
- 새 pane option 2개는 이전 release가 무시하는 추가이므로 `tmux_options` 형식 버전은 올리지 않습니다(MINOR 대상, release 판단은 Leader). `VERSION`·`CHANGELOG`는 건드리지 않았습니다.

### 4. A/B (실제 등록 10개, 읽기만. test tmux server에 pty client, 같은 `tmux_control.open_*popup` 호출. 0.8.0 = `~/.local/lib/project-agent/current`, 이 CR = 같은 commit에서 만든 release 사본. 번갈아 3회. wall = 클릭부터 capture-pane에 내용이 보일 때까지, 평균 ± 95% 구간(t 분포))
다른 seat의 test(`pytest -n 8` 등)가 같은 host에서 도는 상태(검증 2의 "동시에 돌린다")입니다. 구간이 큰 것은 host load 때문입니다.

최종 코드(commit 5078775 직전의 e6697ff 트리, 이후 merge는 문서·agent-session만 바뀜), load 49~64:

| 경우 | 0.8.0 | 이 CR |
| --- | --- | --- |
| CR 창 처음 열기(agent) | 6.05 ± 3.15초 | **1.97 ± 0.91초** |
| 창이 떠 있을 때 CR 전환(agent→fc2_cpu todo), 바로 클릭 | 6.16 ± 1.73초 | **0.93 ± 0.14초** |
| 같은 경우, 창이 뜬 뒤 45초 기다렸다 클릭 | 10.87 ± 8.90초 | **0.98 ± 0.50초** |
| 창이 떠 있을 때 결정 전환, 바로 클릭 | 5.10 ± 2.91초 | **0.89 ± 0.30초** |
| 같은 경우, 45초 뒤 클릭 | 12.22 ± 10.2초 | **0.66 ± 0.28초** |

같은 측정을 load 80~140에서 한 앞선 batch(Done 지연 mount·긴 CR 첫 화면 이전 코드): 0.8.0은 first_cr 19.5, switch_cr 25.8, switch_decision 23.8초, 이 CR은 4.1, 3.5, 2.5초. 결정 창 첫 열기는 0.8.0 18.8 ± 13.5 → 4.0 ± 2.1초(load 84).

**Contract 1의 0.5초는 이 측정에서 닿지 못했습니다**(load 50~60에서 0.66~0.98초). 남은 시간: click 호출(`tmux_control` 한 번, 0.15~0.58초: tmux 명령 여러 개를 process로 부름), 새 목록과 본문 mount·layout(긴 CR의 첫 절 Markdown과 목록 행), 그리고 측정의 capture-pane 폴링 오차(30 ms 간격으로 tmux process를 부름)입니다. 가설: tmux 호출 수를 줄이면(Rust sidebar가 한 번에 요청) click 호출이 줄 것입니다. 이 CR에서는 측정 근거가 있는 위 변경까지만 했습니다. 옛 0.8.0은 같은 load에서 6~12초이고 load 100 이상에서는 20초를 넘습니다.

### 5. 검증 (commit은 위 merge 전후 명시)
- `python -m pytest -q tools/project-board/tests tools/agent-session/tests/test_api_boundary.py`: 최종 tui 코드(e6697ff)에서 228 passed + 4 passed. 이후 merge(TEAM-002)는 `agent_session`·문서만 바꿔서 `test_api_boundary.py`·`test_cli.py`와 `install/tests/test_bundle.py`를 merge 후 다시 실행: 23 passed.
- 네 번째 명령(`integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py`): 0.8.1 merge 뒤 tree에서 136 passed(BOARD-026·TEAM-002 merge 이전). 이후 변경은 `tui.py`·tests·`agent-session`·문서뿐이라 이 명령의 입력(launcher·번들 reader·`integrations/`)은 바뀌지 않았고, 문서 link는 `test_distribution_boundary`가 같은 tree에서 통과했습니다.
- `install/tests`: 전체 `-n 8` 283 passed, 2 skipped(0.8.0 merge 이전 tree). `VERSION`을 읽는 `test_install.py`는 0.8.1 merge 뒤 다시: 97 passed, 1 skipped. 번들을 바꾼 `test_bundle.py`는 16 passed(새 test 3개: Textual 모듈과 guard, TUI가 번들에서 import, guard가 없는 디렉터리면 설치된 package에서 import) + merge 뒤 위 23 passed에 포함.
- 새 test: `test_window_protocol.py`(창 쪽 규약), `test_tmux_control.py`(떠 있는 창 재사용, 시작 중 기다림, `busy`, 죽은 process, 종류 변경, 시작 문구, raw client), `test_tui.py`(열린 CR·결정 창이 알림을 받음, 읽는 중, 거절, draft 보존, 전송 중 busy, 다른 project 미리 읽기 1회, `cr_head`, 긴 CR 첫 화면, 접힌 Done 행·제목), `test_model.py`(`only` 범위), `test_python_launcher.py`(cr/popup `-S`, `--config` 앞).
- 기존 test 변경: `test_cli.py`(`mark_link` 인자), 접힌 Done 행이 DOM에 없다는 점을 반영한 3개(`four_groups`, `moves_between_every_project`, 내 새 test), `test_cr_window_scrolls_to_the_pressed_group_first`의 scroll 대기(부하에서 간헐 실패하던 timing), `test_bundle`의 번들에 없는 stdlib 모듈 예(`colorsys`→`wave`: Textual이 이제 colorsys를 import).
- 근거 재사용: merge로 입력이 바뀌지 않은 test는 다시 돌리지 않았습니다(위 각 항목에 명시).

### 6. 남은 일·참고
- Contract 1의 0.5초는 위처럼 미달이고, 가설은 위 4절에 있습니다(미검증).
- BOARD-018(Rust sidebar): 5절 규약대로 pane option과 socket에 한 줄 JSON을 쓰면 됩니다. 규약 문서와 raw client test가 기준입니다.
- 번들에 Textual을 넣은 것은 설치 계약 6.1절을 바꿉니다(문서 반영함). 같은 버전을 다시 설치하는 경우는 구별하지 않습니다(code가 같기 때문).
- 이 workstation의 관리 run·`~/.local/bin`은 동결 사본이라 이 변경이 떠 있는 Board에는 아직 적용되지 않습니다(AGENTS.md).
