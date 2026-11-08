# project-agent 작업 지침

Project Team·Project Item·Project Board·Agent Session의 개발 원본입니다.
공통 지침은 사용자의 전역 AGENTS.md를 따릅니다.
기능 소유·공개 경계·허용 의존은 [아키텍처](docs/architecture.md)가 안내합니다.
실행·설치·검증 진입점은 [README](README.md)를 따릅니다.

- Session 등록·배정·liveness·provider 제어는 `tools/agent-session`이 소유합니다.
- CR·Decision 형식·저장·상태 전이는 `tools/project-item`이 소유합니다.
- Board TUI·tmux 연결은 `tools/project-board`와 `integrations/tmux`가 소유합니다.
- 설치 파일 목록·해시·복사·연결·복구는 `project_agent_install.py`가 소유합니다.
- 스킬은 `skills/`에 있습니다. 명세와 형식 규칙의 원본을 복제하지 않습니다.

배포 설치본은 별도 개발 원본이 아닙니다.
agent.desk의 공통 지침·일반 tmux·설치 consumer는 해당 project owner가 변경합니다.
운영 전환과 기존 run의 종료 확인 전에는 옛 실제 코드를 제거하지 않습니다.
이 저장소의 설명이나 등록만으로 운영 원본이 바뀌었다고 판단하지 않습니다.

변경 요청은 등록된 `agent/cr`, 사용자 결정은 `agent/decide`에서 관리합니다.
SSH seat의 `host`·원격 `path`·선택 Python은 프로젝트 등록이 소유합니다.
등록·state·CR·Decision·seat는 제품 설치 payload에 넣지 않습니다.
직접 영향 테스트는 임시 home과 격리 tmux socket을 사용합니다.
