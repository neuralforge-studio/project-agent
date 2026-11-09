# SESSION-002: 원격 seat(Codex SSH)의 등록 게시도 시작 controller 생존에 묶여 있습니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3

## Symptom
SESSION-001에서 확정한 결함(게시 책임이 호출자에 묶인 시작 controller에 있음)이 원격 seat 경로에도 있습니다. 원격 Codex의 등록은 원격 host에서 일어나고, Leader host의 window에 `registered`를 쓰고 state를 게시하는 것은 시작 controller의 poll뿐입니다. controller가 원격 시작 dialog(`needs_user_action`)나 signal로 먼저 끝나면, 원격 등록이 끝나도 Leader host에 게시할 주체가 없습니다.

## Evidence
- `tools/agent-session/agent_session/remote_lifecycle.py:20-32` `poll`: 원격 결과를 받아 `registered`를 쓰고, 원격 dialog면 `needs_user_action`을 냅니다. `lifecycle.py`의 `_wait_ready`가 이 poll을 부르고 게시합니다.
- 명세 3절 원격 seat: "시작 dialog에서 대기한 뒤 native 등록이 늦게 끝나면 poll이 같은 run의 cache 게시를 마칩니다. 이 비동기 cache 게시만으로 Leader 호스트의 배정이나 시작 성공을 확정하지 않습니다."
- `remote_bridge.py`: Leader host와 원격 run 사이의 reverse-SSH uplink(Result와 CLI 보고용)가 이미 있습니다.
- 2026-11-09 등록 파일(`~/.claude/project.json`)의 모든 project에 원격 seat가 없습니다. 지금 운영에는 드러나지 않습니다.

## Contract
- SESSION-001이 고친 명세 5절: 게시는 등록의 일부입니다. 등록됐지만 게시되지 않은 상태는 없어야 합니다.

## Disposition
- 2026-11-09 Leader: 판정 보류(open 유지). 같은 결함이지만 등록이 Leader host 밖에서 일어나므로 고치는 경로(원격 등록을 uplink로 Leader host의 등록 함수에 올리는 방법 등)를 SESSION-001의 새 계약이 통합된 뒤 그 계약에 맞춰 설계합니다. 지금 원격 seat를 쓰는 project가 없어 SESSION-001과 따로 진행합니다.
