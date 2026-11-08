# 제품 아키텍처

project-agent는 등록 프로젝트의 협업 실행과 항목 관리를 제공합니다.
제품의 세 CLI와 Team·Item 스킬은 하나의 복사 설치본을 사용합니다.
공개 사용자 계약은 [Session 명세](project-team/spec.md),
[Item 스킬](../skills/project-item/SKILL.md), [Board 명세](project-board-tui-plan.md)가 소유합니다.
설치와 검증의 실행 명령은 [README](../README.md)가 안내합니다.

## 기능 소유와 공개 경계

| 소유 기능 | 구현·검증 | 공개 입출력과 소비자 |
| --- | --- | --- |
| Session 등록 | `tools/agent-session/agent_session/config.py`, `registry.py`; `tests/test_config.py` | `agent_session.registry`의 project/seat 모델·load/resolve/find/select. Item·Board가 같은 parser를 사용합니다. |
| Session 실행 | `api.py`, `lifecycle.py`, `state.py`, `providers/`, `tmux.py`; `tests/test_caller.py`, `test_lifecycle.py`, `test_start_seat.py`, `test_state.py` | 기존 `agent_session.api`의 caller·binding·state·liveness. CLI와 Board가 사용합니다. |
| Item 도메인 | `tools/project-item/project_item/{cr,decide,store,assign,render,kinds,errors}.py`; 해당 도구 `tests/` | `project_item.api`의 항목 읽기·답변 저장·CR 배정·Result 동기화. Session·Board·tmux가 사용합니다. |
| Item 환경 통합 | `registry.py`, `guard.py`, `cli.py`; `tests/test_team_guard.py`, `test_cli.py` | 등록 선택·caller 권한·명령 오류 변환. 도메인의 상태 전이와 잠금을 재사용합니다. |
| Board | `tools/project-board/project_board/{model,answer,tui,tmux_control,cli}.py`; 해당 도구 `tests/` | snapshot·popup·답변 입력·tmux click/toggle. TUI는 도메인 저장 규칙을 만들지 않습니다. |
| SSH 통합 | `tools/agent-session/agent_session/remote*.py`; `tests/test_remote*.py`, `test_distribution.py` | helper·guidance 전송, 원격 실행 관찰, 권한을 확인한 보고의 Result 반영. 배정 원본은 Leader 측입니다. |
| tmux 알림 | `integrations/tmux/`; `test_tmux_decide_status.py`와 Board `test_tmux_control.py` | 공개 CLI와 항목 관찰 API. cache는 최근 관찰이며 항목 상태의 원본이 아닙니다. |
| 설치 통합 | root `project_agent_install.py`, `install.py`; `tests/test_install.py` | 파일 목록·내용 해시·계획·복사·링크 transaction·복구. CLI는 인자와 결과 표현을 맡습니다. |
| 운영 스킬 | `skills/project-team`, `skills/project-item`; SSH 배포 검증 | Team의 역할 절차와 Item의 CR·Decision 형식. 일반 엔지니어링 정책은 환경 소유입니다. |

표의 `tests/`는 해당 도구 디렉터리를 기준으로 합니다.
각 기능의 문서는 같은 도구의 README에 있습니다.
세부 모델·형식·오류를 상위 문서에서 다시 정의하지 않습니다.

## 허용 의존과 실패 처리

Item의 형식·저장·배정·오류와 `project_item.api`는 provider나 세션 제어를 import하지 않습니다.
`ItemError`의 원본은 `project_item.errors`입니다.
기존 `project_item.registry.ItemError` 경로는 같은 클래스를 재노출합니다.
등록·호출자 확인이 필요한 Item CLI 통합만 Session 공개 경계를 사용합니다.

`agent_session.registry`는 `config.py`의 parser와 모델을 재노출합니다.
프로젝트 이름 선택도 같은 parser의 결과에서 수행합니다.
등록·state loader·caller 판정을 다른 도구에 복제하지 않습니다.
기존 `agent_session.api`의 실행 확인은 provider에 의존합니다.
등록만 읽는 소비자는 그 실행 API를 import할 필요가 없습니다.

Session `jobs.py`는 Item 공개 API로 CR을 조회·claim·unclaim하고 Base를 기록합니다.
Item 잠금과 전이 검사는 Item이 소유합니다.
Session은 Item 오류를 기존 Session 오류와 exit code로 변환합니다.
Board `model.py`는 공개 등록·state 읽기와 Item 조회 결과를 화면 모델로 조합합니다.
Board `answer.py`는 operator 권한을 먼저 확인하고 Item 답변 접수 후 Leader에게 알립니다.
페이지 갱신·알림 실패가 이미 접수한 답변을 지우지 않습니다.

SSH `remote_bridge.py`는 run·caller·수신 대상을 확인합니다.
`project_item.api.sync_cr_result`가 항목 잠금 안에서 Result만 갱신합니다.
Leader가 바꾼 다른 절은 보존합니다. 독립적으로 바뀐 Result는 충돌로 거절합니다.
도구의 오류 type identity와 사용자 exit code는 기존 계약을 유지합니다.

형제 도구의 Python 경로 조립은 각 통합 진입점에서 수행합니다.
별도 설치 package나 공통 모델을 만들지 않은 이유는 이 세 도구가 함께 배포되기 때문입니다.
각 기능 내부의 비공개 함수는 그 기능의 공개 API가 조합할 수 있습니다.
다른 기능의 소비자는 문서화한 공개 경계를 사용합니다.

## 실행 흐름과 공유 자원

1. CLI는 등록된 base·seat를 Session parser로 선택합니다.
2. Session은 caller·기존 run·state를 대조하고 Item의 CR을 배정합니다.
3. Provider 어댑터는 등록의 실행 인자를 사용해 tmux에서 실행합니다.
4. Worker는 CR에 지정한 범위의 작업과 검증 결과를 제출합니다.
5. Board는 원본 파일과 실행 관찰을 읽고 화면을 갱신합니다.
6. Leader가 제출을 검토·통합하고 기존 절차로 done과 반납을 수행합니다.

등록은 사용자의 `project.json`, 배정은 프로젝트의 `agent/state.json`이 소유합니다.
CR·Decision 상태는 등록된 항목 디렉터리와 본문이 소유합니다.
설치 기록은 제품 연결 복구만 소유하며 운영 상태를 복제하지 않습니다.
Textual 버전은 Board의 `requirements.txt` 하나가 소유합니다.

## 배포와 이전 경계

설치 manifest는 `project_agent_install.product_files()`가 소유합니다.
명시한 제품 자산과 `PRODUCT_MODULES`의 필수 Python 파일만 복사합니다.
새 module을 추가하면 같은 manifest를 갱신합니다. 빠진 필수 파일은 설치 전에 거절합니다.
내용 해시는 상대 경로·실행 속성·내용으로 계산합니다.
복사본을 검사한 뒤 안정 root 링크를 전환하며 기존 설치본은 남깁니다.
설치기는 등록·인증·운영 state나 provider 설정을 생성하지 않습니다.

SSH archive는 Session·Item helper와 `guidance/skills`, `guidance/docs`를 전송합니다.
Team·Item의 metadata·commit asset·CR·Decision 문서를 포함합니다.
원격 cache의 옛 `guidance/codex/skills`와 새 `guidance/skills`는 서로 구분합니다.
ready 근거와 소유권을 확인한 제품 링크만 새 cache로 갱신합니다.
사용자가 바꾼 링크는 그대로 보존합니다.

Board include와 호환 helper는 `~/.local/bin/project-board`를 호출합니다.
결정 status fragment는 안정 root의 제품 helper를 호출합니다.
일반 tmux 설정과 사용자 status layout은 이 제품의 설치 대상이 아닙니다.

agent.desk는 공통 지침·개인 환경·제품 consumer 연결을 소유합니다.
최초 운영 전환은 해당 owner와 조정합니다.
기존 run이 기록한 옛 library·hook·controller 경로는 정상 인계 전까지 보존해야 합니다.
제품 저장소의 구현 완료와 실제 운영 이전 완료를 구분합니다.

## 검증 경계

root `conftest.py`는 Unix socket 길이를 제한하기 위해 `/tmp`에 실행별 임시 디렉터리를 만듭니다.
`pytest.ini`는 동명 테스트 모듈을 별개로 수집하고 테스트 helper 경로를 제공합니다.
명시한 `--basetemp`는 그대로 사용합니다. Unix socket을 시험할 때는 짧은 경로를 지정하십시오.
Session의 기존 timeout 설정은 해당 README가 소유합니다.

직접 영향 검증은 세 도구, tmux 결정 알림, 복사형 설치를 함께 실행합니다.
공개 API 검증은 도메인 import에 provider가 로드되지 않는지 확인합니다.
SSH 검증은 guidance 완결성·상대 링크·소유 cache 전환을 확인합니다.
설치 검증은 임시 home에서 충돌·중간 실패·갱신·복구와 다운로드 삭제 뒤 동작을 확인합니다.
실제 provider 로그인과 SSH 접속은 준비 상태 출력이나 격리 test로 보증하지 않습니다.
