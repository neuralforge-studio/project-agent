# Common·Haroo 실행 인수

이 문서는 2026-11-03의 실행 근거입니다.
현재 배정은 프로젝트의 `agent/state.json`이 소유합니다.
JOB 결과는 Haroo의 `.haroo-ops/jobs/J-20261103-01.md`와 업무 원본이 소유합니다.

## 환경과 범위

| 항목 | 실제 값 |
| --- | --- |
| Host | 현재 WSL Ubuntu |
| Python | `/home/swain/python/.venv/bin/python`, 3.12.3 |
| Tmux | 3.4, 사용자 기본 server |
| Codex | 대화형 CLI 0.166.0, 기존 공용 app-server daemon |
| 모델 | 기존 사용자 설정의 GPT-6.1-Sol max |
| Node | v22.18.0 |
| Base | `/home/swain/work/haroo/haroo.main` |
| Legacy | Base와 seat 기준 `../../haroo.old`, 읽기 전용 |
| Registry | `~/.codex/project.json`, `~/.claude/project.json`은 같은 파일로 연결 |
| 실행 위치 | `haroo` tmux session의 `haroo-leader` window |

Common CLI와 중립 library를 현재 머신에 설치했습니다.
공유 `project-team` skill을 두 도구의 skill 경로에 연결했습니다.
Haroo adapter와 운영 consumer를 공통 API로 전환했습니다.
기존 `haroo_tmux.py`와 native Leader rotation 경로를 제거했습니다.
Falcon2 이전과 다른 머신의 실제 인수는 이번 실행에 포함하지 않았습니다.

## 검사 결과

| 검사 | 근거와 결과 |
| --- | --- |
| 공통 tool 회귀 | 175 PASS. 격리 tmux와 임시 Git을 사용했습니다. Provider 응답 fixture를 포함합니다. |
| 마지막 종료 입력 변경 | 외부 TTY 계약의 수정 전 실패와 수정 후 PASS. 직접 영향 tmux 15개 PASS. |
| Haroo 운영 회귀 | 184 PASS·94 subtests PASS. 이후 취소·반납 변경은 직접 영향 8개 PASS. |
| 신규 seat 인증 설정 | 설정 누락의 수정 전 FAIL. 신규 두 사례와 직접 영향 두 사례 PASS. |
| Skill·설정 | Skill metadata 16개와 repository setup 검사 PASS. |
| Haroo 문서 | 공식 build/check PASS. 42 features·145 relations. |
| 실제 시작 | 실제 native UUID·cwd·현재 run을 결합하고 ready=true를 확인했습니다. |
| 실제 환경 | 도구 문맥에서 AGENT_SESSION_CONFIG·AGENT_SESSION_SOCKET·AGENT_SESSION_BASE·CODEX_THREAD_ID를 확인했습니다. |
| 과거 외부 창 연결 | 2026-11-03 인수 시험에서 같은 server의 `agent-8`에 당시 Leader window를 연결했습니다. 이 기능은 2026-11-04 사용자 요청으로 삭제했습니다. |
| 실제 인계 | 새 UUID와 새 run으로 self-restart했습니다. 이전 대화와 checkpoint를 보존했습니다. |
| Unloaded 대화 | 이전 Leader의 notLoaded 상태에서 같은 run·session·최신 turn 근거로 terminal을 확인했습니다. |
| 반납 뒤 전송 거절 | 종결 JOB의 send는 job_not_assigned·exit 3입니다. 전송하지 않았습니다. |

공통 전체 175 PASS는 마지막 250ms 종료 입력 보강 전의 실행입니다.
그 보강 뒤에는 직접 영향 tmux 15개와 아래 실제 Leader restart로 확인했습니다.
Actual provider 실행과 fixture 회귀를 같은 근거로 합산하지 않았습니다.

## 실제 서버 JOB

| 항목 | 기록 |
| --- | --- |
| JOB | `J-20261103-01` |
| Seat·branch | seat0, `job/J-20261103-01` |
| 최초 Git hash | `d4c10c4871d3ddf8a4d99ebc8e5f8f7a2579582c` |
| 최초 commit 시각 | `2026-11-03T19:42:19+09:00` |
| 동기화 시각 | `2026-11-03T10:49:44.727898+00:00` |
| Worker run | `2d2e3f1516bd4e2e967a3cb7188ff891` |
| 제출·검토·통합 hash | `e1da3f127bfa2ec5763602f2cfeb47af5405b981` |
| 최종 업무 상태 | integrated, released=true, worker_stopped=true |
| 반납 | seat0의 job_id·git_hash·session이 모두 null |

Worker는 legacy catalog 검증기를 `server/catalog/`로 이전했습니다.
Worker는 오류 계약과 strict JSON parser를 별도 모듈로 분리했습니다.
기존 public export 13개와 함수 본문을 보존했습니다.
기존 153행 테스트는 import 경로 한 곳만 바꿨습니다.

1. 같은 구조의 이전 상태에서 기존 테스트 5개가 통과했습니다.
2. 책임 분리 뒤 같은 테스트 5개가 통과했습니다.
3. 입력 계약의 별도 테스트 6개가 통과했습니다.
4. 기존 공개 안내 테스트 9개가 통과했습니다.
5. 서버 문서의 공식 build/check가 통과했습니다.
6. Worker는 JOB branch에 commit·push하고 공식 결과를 기록했습니다.
7. Worker는 common send로 실제 hash와 근거를 보고했습니다.
8. Leader는 실제 diff·원본 본문·쓰기 범위·검증 commit을 검토했습니다.
9. Leader는 같은 hash를 main에 fast-forward하고 원격 게시와 인수를 기록했습니다.
10. Worker는 자기 캐시와 process를 정리하고 common send로 보고했습니다.
11. Leader는 common stop의 실제 종료·반납 결과를 확인했습니다.

Leader는 늦게 도착한 인수 전 보고를 현재 integrated 기록과 대조했습니다.
Leader는 완료한 JOB을 다시 배정하지 않았습니다.
수정 요청이 필요한 제품 finding은 없었습니다.
이번 실작업에서 제품 feedback 반복은 수행하지 않았습니다.
해당 경로는 공통 fixture 회귀의 근거를 사용합니다.

## 실행에서 찾고 수정한 문제

| 문제 | 수정과 확인 |
| --- | --- |
| 원격 Codex thread가 daemon의 기존 cwd를 사용 | 공통 argv에 확정한 --cd를 추가했습니다. 두 경로 회귀와 실제 Haroo 등록을 확인했습니다. |
| 신규 clone이 base의 SSH 명령을 받지 않음 | Leader가 같은 JOB으로 재개했습니다. 이후 seat_prepare가 유효 core.sshCommand만 새 local 설정에 복사하도록 수정했습니다. 자격 파일은 읽거나 복사하지 않습니다. |
| 빠른 /exit·Enter가 입력란에 남음 | 최초 Worker 종료에는 정착한 Enter 한 번을 보조했습니다. 이후 literal과 단일 Enter 사이에 250ms를 두었습니다. |
| notLoaded에서 background 조회 거절 | 마지막 loaded terminal 근거와 최신 native turn을 대조합니다. 근거가 없으면 unknown을 보존합니다. |
| 닫힌 window가 다른 seat의 시작을 차단 | 해당 seat만 거절하고 다른 seat의 등록을 계속합니다. 원래 pointer는 보존합니다. |
| 시작 전 실패한 예약의 취소·반납 차단 | 미실행 대기 process를 정상 TERM하고 stop→취소→stop으로 반납합니다. |
| /proc 조회 중 다른 PID의 소멸 | ESRCH만 정상 소멸로 처리합니다. 권한·I/O 오류는 unknown입니다. |

Codex 0.166.0의 [공식 입력 상태 코드](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/tui/src/bottom_pane/paste_burst.rs)는 빠른 입력 뒤 120ms 동안 Enter를 줄바꿈으로 처리할 수 있습니다.
보강 뒤 실제 Leader는 추가 키 보조 없이 정상 종료하고 새 대화로 교체됐습니다.
최종 인계 제어 결과는 `agent/runs/448c9177f24943c99e46a7692fb2b065/control-result.json`의 completed=true입니다.
새 대화는 `01a1a11e-235a-7ac1-b4cd-f4f7f257585f`이며 새 run은 `37c1a6600a454d4080ea2645f2dfdca2`입니다.

## 보존과 후속 범위

Haroo main에는 운영 전환 `d4c10c4`, 서버 통합 `e1da3f1`, seat 설정 보강 `bee4329`를 게시했습니다.
Common source·skill·계획 변경은 현재 agent 저장소의 작업 트리와 로컬 설치에 반영했습니다.
이 회차에서는 agent 저장소의 commit·push를 수행하지 않았습니다.
기존의 다른 수정 파일은 보존했습니다.

Claude Code는 최종 코드와 실제 daemon·tmux·Git·업무 기록을 독립적으로 대조했습니다.
Claude Code 검토와 Codex 자체 검토는 모두 통과했습니다.
인수를 막는 추가 finding은 없습니다.

Claude의 새 대화형 Worker 시작은 Falcon2 이전 단계의 실제 인수 대상입니다.
이번에는 provider fixture와 실제 동료 MCP 메시지·독립 코드 검토를 확인했습니다.
Workstation의 Python library 환경과 controller 비정상 종료 뒤 자동 복구는 계획의 후속 항목입니다.
현재 종료 근거 부족 사례의 수동 절차는 [명세 7절](spec.md#7-stoprestart)이 소유합니다.
