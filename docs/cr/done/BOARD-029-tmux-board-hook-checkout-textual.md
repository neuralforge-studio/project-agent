# BOARD-029: 이전 tmux Board hook이 남아 개발 checkout을 실행하고 textual 누락으로 종료

- Opened: 2026-11-13
- Scope: project-agent
- Severity: S1
- Outcome: fixed

## Symptom
2026-11-13 Mac의 project-agent Board pane %83이 `ModuleNotFoundError: No module named 'textual'`로 종료했습니다. 사용자 요청은 원인 조사입니다.

## Evidence
- `/opt/homebrew/bin/tmux -S /private/tmp/tmux-501/default display-message -p -t %83 '#{pane_start_command}'`: `/Users/swkim/Agent/agent.desk/codex/tools/project-board/bin/project-board sidebar`.
- pane traceback은 위 checkout의 `project_board/tui.py`에서 `from textual.app import App, ComposeResult` 실패를 보입니다.
- `show-hooks -g`에서 client-attached, client-detached, client-session-changed, session-window-changed의 `[board]` hook과 `[project-agent]` hook이 함께 존재합니다. 이전 hook은 `/Users/swkim/.tmux/scripts/tmux_project_board.sh sync`를 부릅니다.
- `/Users/swkim/.tmux/scripts`는 `/Users/swkim/Agent/agent.desk/tmux/scripts`의 symlink입니다. `tmux_project_board.sh:6`은 `../../codex/tools/project-board/bin/project-board`를 실행합니다.
- 이전 checkout의 `tools/python-launcher.sh:20`은 macOS에서 PATH의 python3을 고릅니다. 확인 결과 `/opt/homebrew/bin/python3`이고 `importlib.util.find_spec("textual")`은 None입니다.
- 현재 설치본의 Python `/Users/swkim/.local/share/project-agent/venv/bin/python`은 textual import에 성공했습니다. 설치본 python.env도 이 interpreter를 지정합니다.

## Contract
사용자는 현재 오류의 원인과 Linux·Claude 환경 관련 여부를 확인하도록 요청했습니다. 현재 설치본과 과거 checkout의 실행 경로를 구분합니다. 제품 코드와 사용자 tmux 설정 수정은 이번 조사에서 수행하지 않습니다.

## Disposition
- 2026-11-13 Leader 판정: 관찰된 실패의 직접 원인은 이전 Board 실행 경로가 선택한 Python에 textual이 없는 것입니다. 남은 `[board]` hook이 과거 checkout을 실행하는 경로를 확인했습니다. Linux 또는 Claude 자체의 비호환이라는 근거는 없습니다. 이번 요청은 원인 조사이므로 runtime 설정과 제품 코드는 변경하지 않습니다. 어떤 hook 호출이 pane %83을 만들었는지는 실행 시점 trace가 없어 확정하지 않습니다.

- 2026-11-13 Leader 판정: 사용자 원문 "너가 모든 작업을 완료해"에 따라 운영 복구를 수행합니다. 재현 근거가 있는 실행 경로 충돌을 해소하는 범위입니다.
- 2026-11-13 Leader: open -> todo. 사용자 복구 지시. 과거 runtime hook 제거와 설치본 Board 재시작만 수행
- 2026-11-13 Leader: todo -> done, Outcome fixed. 운영 복구 완료. 과거 hook 다섯 개 제거, 현재 release Rust Board 정상 화면과 Leader 보존 확인. 제품 코드 변경 없음

## Implementation
- 운영 복구 범위입니다. 현재 tmux server에서 과거 `[board]` hook 다섯 개만 제거합니다. 현재 `[project-agent]` hook과 실행 중인 대화는 유지합니다.
- 현재 설치본 CLI로 Board를 켭니다. 사용자 HOME의 tmux 설정은 이미 현재 설치본을 참조하므로 수정하지 않습니다.
- 위험 등급: 낮음. 제품 코드·배포·Git branch를 변경하지 않습니다.

## Verification
- 과거 hook이 없고 현재 hook이 남아 있는지 확인합니다.
- Board pane이 현재 release의 Rust sidebar를 실행하며 종료되지 않았는지 확인합니다.
- Board 화면의 프로젝트 목록과 실행 중인 Leader pane 보존을 확인합니다.

## Result
- tmux pane 출력, 시작 명령, 전역 hook, 기존 wrapper, 설치본 python.env를 읽어 대조했습니다.
- 과거 launcher의 Python에는 textual이 없고 설치본 Python에는 있다는 점을 각각 import 조회로 확인했습니다.
- 후속 조치 후보: 과거 `[board]` hook을 정리하고 현재 설치본으로 Board를 다시 만듭니다. 사용자 실행 환경의 정리 범위와 제품의 migration 지원 여부는 후속 작업에서 확인합니다.

- 2026-11-13 운영 복구 완료: tmux socket `/private/tmp/tmux-501/default`의 client-attached, client-detached, client-session-changed, session-window-changed, after-resize-pane에서 `[board]` hook만 제거했습니다.
- `show-hooks -g`로 과거 hook 제거와 `[project-agent]` hook 보존을 확인했습니다.
- Board가 꺼져 있어 설치본 `project-board toggle --socket /private/tmp/tmux-501/default`을 한 번 실행했습니다. `@project_board_enabled=1`입니다.
- 새 pane `%91`의 시작 명령은 `/Users/swkim/.local/lib/project-agent/releases/0.11.0-cfa0856113ed/tools/project-board/bin/project-board-sidebar`이고 `pane_dead=0`입니다.
- 화면 capture에서 haroo, agent, project-agent 목록이 표시됐습니다. traceback은 없습니다. 기존 Leader `%82`도 `pane_dead=0`, `codex`로 유지됐습니다.
- HOME의 `.tmux.conf`는 이미 현재 설치본을 source하고 과거 hook 설정을 source하지 않습니다. 따라서 파일 변경은 필요하지 않았습니다. 제품 소스 변경과 제출 commit은 없습니다.
