# project-agent 작업 지침

이 저장소는 Project Team, Project Item, Project Board, Agent Session을 독립적으로
개발·설치하기 위한 프로젝트입니다. 공통 지침은 사용자의 전역 AGENTS.md를 따릅니다.

현재 실행 원본은 `agent.desk`에 있습니다. 이전이 완료되기 전에는 이 저장소의
설명이나 등록만으로 실행 원본이 바뀌었다고 판단하지 않습니다. 구현 시에는
각 구성요소의 원본과 설치 경로를 하나씩 정하고, 중복 원본을 만들지 않습니다.

변경 요청은 등록된 `agent/cr`, 사용자 결정은 `agent/decide`에서 관리합니다.
SSH seat의 `host`와 원격 `path`는 프로젝트 등록이 소유합니다.
