# TMUX-002: tmux 최소 버전이 정해지지 않아, 시스템 tmux 2.7에서 통합 파일이 오류로 읽히고 check도 알리지 않습니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Base: 742d60b97631c837788b218a138ed6b21b70b832 2026-11-09T19:09:15+09:00

## Symptom
통합 파일 `integrations/tmux/project-agent.conf`는 tmux 3.x 문법(`{ }` 명령 블록, 이름 붙은 hook index, `#{d:current_file}`, `run-shell -C` 등)을 씁니다. 이 workstation의 `/usr/bin/tmux`는 2.7이고, 사내 tmux 3.8(`/primehome/tools/Inhouse/tmux/latest/bin/tmux`)은 PATH에 사내 경로가 먼저 올 때만 쓰입니다. 개인 설정이 없는 새 직원은 2.7을 쓸 수 있습니다. 그러면 설치는 성공하지만 tmux 설정을 읽을 때 통합 파일이 오류를 내고, Board binding·hook이 들어가지 않습니다. 설치 계약에 tmux 최소 버전이 없고 설치기 `check`도 이를 알리지 않습니다.

## Evidence
- RELEASE-002 Worker 확인(2026-11-09, `docs/cr/done/RELEASE-002-tmux.md` Result): tmux 2.7은 통합 파일의 `{ }` 문법을 읽지 못함. 안내문 `docs/install.md` 1절은 "3.8에서 검증, 2.7 불가, 그 사이 미검증"으로만 적음.
- `/usr/bin/tmux -V` → `tmux 2.7`, `which -a tmux` → 사내 3.8이 먼저, 그 다음 `/usr/bin/tmux`.
- 설치 계약 3절·3.1절·5.3절: 통합 파일의 동작은 적었지만 필요한 tmux 버전은 없음. 7절 `check` 항목에도 없음.

## Contract
- 사용자 결정(agent D-20261109-08 C): 다른 직원에게 배포합니다. 설치본만으로 동작하거나, 동작할 수 없으면 그 사실과 해소 방법을 분명히 알려야 합니다.
- 설치 계약 7절: `check`는 설치가 동작하는지 확인하고 실패를 알립니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). RELEASE-002 Worker가 결정을 요청했으나, 지원하는 tmux에서 동작하지 않는데 알리지도 않는 것은 결함이므로 위임 범위입니다(사용자 지시 2026-11-09: 동작 결함은 Leader가 최적의 방법을 정함). RELEASE-003(빈 HOME 시범 설치)은 시스템 PATH의 tmux 2.7을 만나므로 이 CR 뒤에 합니다.

## Implementation
읽을 문서: [설치 계약](../../project-team/install-contract.md) 3절·3.1절·5.3절·7절, `integrations/tmux/project-agent.conf`, [안내문](../../install.md) 1절, tmux의 `CHANGES`(사내 tmux 설치본 또는 tmux 저장소).

1. 최소 버전을 근거로 정합니다. 통합 파일과 `project_agent_bind.sh`·`tmux_decide_status.sh`가 쓰는 tmux 기능을 모두 나열하고, 각 기능이 들어온 tmux 버전을 `CHANGES`로 확인해 표로 Result에 적습니다. 그중 가장 높은 버전이 최소 버전입니다. 이 host에서 실행해 볼 수 있는 버전(2.7, 3.8)은 실제로 확인합니다.
2. 계약 3절에 최소 버전을 원본으로 한 곳에 적습니다. 안내문 1절의 tmux 행은 그 절을 link하고 값을 다시 쓰지 않습니다(지금 "3.8 검증, 2.7 불가" 문장을 바꿈). 사내 tmux 경로 안내는 유지합니다.
3. 오래된 tmux에서의 동작을 정합니다. 최소 버전보다 낮은 tmux가 설치된 `tmux.conf`를 읽으면 parse 오류 대신 한 줄 안내(최소 버전과 사내 tmux 경로)를 보이고 아무것도 binding하지 않습니다. 2.7이 통합 파일 전체를 parse하기 전에 갈라야 하므로, 버전 판정은 2.7도 읽을 수 있는 문법으로 하십시오. 갈래를 두는 위치가 계약 2절의 고정 파일(`~/.local/lib/project-agent/tmux.conf`, "설치 때 한 번 쓰고 갱신하지 않음")이면 그 계약을 먼저 고치고, 이미 설치된 사람에게 미치는 영향(그 파일은 갱신되지 않음)을 적으십시오. 고정 파일을 바꾸지 않고 release 안의 파일에서 가를 수 있으면 그쪽을 택합니다.
4. 설치기 `check`가 PATH에서 처음 찾은 `tmux`의 버전을 확인합니다. 최소 버전보다 낮으면 실패(종료 코드 1)이고, 해소 방법(사내 tmux 경로를 PATH 앞에 둠)을 알립니다. `install`도 같은 사실을 안내합니다(설치는 진행). 계약 7절의 `check` 항목에 더합니다.

범위 밖: tmux 2.x용으로 통합 파일을 다시 쓰는 일(최소 버전 아래는 지원하지 않음을 알리는 것까지가 범위).

의존: 선행 없음. 후행 RELEASE-003.

위험 등급: 중간. 모든 사용자가 읽는 tmux 설정 경로를 바꿉니다.

## Verification
1. 재현(수정 전): 격리 tmux server를 `/usr/bin/tmux`(2.7)로 띄워 설치본 `tmux.conf`를 읽으면 parse 오류가 납니다. 같은 격리 HOME에서 `check`는 통과합니다(알리지 않음).
2. 수정 뒤: 2.7로 읽으면 오류 없이 한 줄 안내만 보이고 binding·hook·`@project_agent_*` option이 없습니다. 3.8로 읽으면 지금과 같이 binding·hook이 들어갑니다(기존 `integrations/tmux` test 통과). PATH 첫 `tmux`가 2.7인 격리 HOME에서 `check`가 실패와 해소 방법을 보이고, 3.8이면 통과합니다.
3. 최소 버전 근거 표(기능 → 도입 버전 → 출처)가 Result에 있습니다.
4. 영향 회귀: `install/tests`와 README 네 번째 명령(`integrations/tmux` 포함)이 통과합니다.
