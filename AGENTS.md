이 문서는 이 저장소에서 작업하는 agent의 규칙만 씁니다. 전역 지침은 다시 쓰지 않습니다. 저장소 구조는 [README](README.md)가, 구성 요소와 계약은 [제품 지도](docs/project-team/README.md)가 원본입니다. 검증 명령은 [README의 검증](README.md#검증)에 있습니다.

# CR

- CR은 `docs/cr/`에 있습니다. 생성·판정·이동은 `project-item` 도구와 [CR 계약](skills/project-item/references/cr.md)을 따릅니다. 파일을 직접 옮기지 않습니다.
- 역할별 절차(Leader·Worker·운영자)는 [project-team skill](skills/project-team/SKILL.md)이 소유합니다.

# 호환 규칙

관측 동작(CLI·JSON·파일 형식·생성 script 내용)을 바꾸지 않는 변경이 기본입니다. 아래는 [실행 경로 계약](docs/project-team/README.md#실행-경로-계약)이 소유합니다.

- 도구 디렉터리 이름(`tools/agent-session`, `tools/project-item`, `tools/project-board`)과 그 형제 배치를 유지합니다.
- `agent_session.internal`의 entry와 `python -m agent_session.remote_runtime`·`remote_bridge`를 유지합니다.
- 원격 실행본의 guidance 배치는 보내는 쪽(`remote.py`)과 받는 쪽(`remote_runtime.py`)을 같은 release 안에서 함께 바꿉니다. 옛 모양 link를 인식하는 `_legacy_skill`의 판정은 바꾸지 않습니다.

# 이 workstation의 run

2026-11-09 현재 이 workstation의 관리 run, `~/.local/bin`, skill link는 agent 저장소의 동결 사본을 씁니다. 이 저장소의 변경은 떠 있는 run에 영향을 주지 않습니다. 이 사실은 agent 저장소 DIST-001 6단계까지 유효합니다.
