---
name: project-team
description: "등록 프로젝트의 tmux Leader·Worker를 agent-session으로 시작·배정·통신·인계·종료합니다. 프로젝트 팀 운영이나 seat에서 CR을 수행할 때 사용합니다. 일반 개발 작업 자체에는 적용하지 않습니다."
---

# Project Team

세션 관리는 설치한 `agent-session`으로 수행합니다.
명령의 상세 입력과 오류는 `agent-session --help`와 해당 하위 명령의 `--help`에서 확인합니다.
등록·상태·provider 계약을 확인할 때는 [동작 명세](../../docs/project-team/spec.md)를 읽습니다.
JOB은 CR 파일입니다. CR 형식과 상태는 [project-item skill](../project-item/SKILL.md)이 소유합니다.

## 프로젝트와 역할

- 등록 base 또는 seat 안에서 명령을 실행합니다. 현재 경로로 프로젝트를 선택합니다.
- Provider, seat 경로, CR 위치(`path_cr`), 실행 인자(`launch`)는 등록 파일에서 읽습니다. 실행할 때 다시 지정하지 않습니다.
- 실제 배정은 `<base>/agent/state.json`에서 확인합니다.
- 상태 JSON, tmux 소유 정보, CR의 `- Base:` header를 직접 편집하여 배정을 변경하지 않습니다.

모든 명령의 `--job`은 `leader` 또는 CR ID입니다.
Worker seat는 기본으로 start가 자동 선택합니다. `start --job <CR-ID> --seat N`은 지정한 seat만 검사합니다. 이미 배정한 CR의 번호는 바꾸지 않습니다. Seat 디렉토리가 없으면 start가 만듭니다.
Start가 `needs_user_action`과 `dialog`를 반환하면 그 window와 dialog 종류를 사용자에게 알립니다. 사용자가 그 창에서 답하면 등록이 게시까지 마치므로 start를 다시 실행하지 않아도 됩니다. Dialog에 대신 답하지 않습니다.

## 보고와 검증

명시적인 진행 보고 요청이 없으면 `send`는 상대의 다음 행동에 필요한 새 정보가 있을 때만 사용합니다.

- 보고할 내용은 검증을 마친 제출·수정 제출, 외부 조치가 필요한 차단 문제, 사용자 결정이나 다른 owner의 조치가 필요한 계약 변경, 정리 후 종료 준비 완료입니다.
- 단순 접수·배정 재확인·작업 예정·변경 없는 상태 대조·자체 해결 중인 테스트 실패는 별도 메시지로 보내지 않습니다. 실행 기록은 CR의 Result에 모읍니다.
- 같은 검증 배치의 중간 hash를 차례로 제출하지 않습니다. 피드백 접수 회신 대신 수정과 검증을 마친 제출을 한 번 보고합니다.
- Leader는 한 제출의 검토 결과를 모아 피드백합니다. 이미 검토한 범위와 유효한 검증 근거는 재사용하고 변경된 부분만 다시 확인합니다. 새 실패·변경 영향 없이 전체 검증이나 상태 조회를 반복하지 않습니다.
- 알려진 run·hash·종결 기록으로 지연·중복 보고임을 판정할 수 있으면 접수 회신·재조회·재배정을 하지 않습니다. 최신 작업의 근거와 실제로 충돌하거나 조치가 필요할 때만 추가 확인합니다.
- 동료 메시지 수신 자체는 사용자에게 보고할 사건이 아닙니다. 내부 접수와 상태 확인을 매번 사용자 대화로 옮기지 않습니다. 사용자 질문, 필요한 진행 안내, 실제 차단·결정·완료 결과를 중심으로 전달합니다.

## Leader

1. 사용자 지시에서 작업 범위와 완료 기준을 정합니다.
2. `project-item new cr`로 CR을 만들고 Implementation·Verification을 채웁니다. 역할 지침과 읽을 문서는 CR 본문에 link로 적습니다.
3. 일의 성격으로 판정합니다. 아래 위임 범위이면 Disposition에 `Leader 판정`과 근거를 기록합니다. 범위 밖이면 `project-item new decide`로 결정 항목을 만들어 사용자에게 알리고, 답을 받으면 결정 항목 ID와 사용자 원문을 Disposition에 씁니다. 사용자가 대화로 답해도 결정 항목으로 남깁니다.
4. 판정을 기록한 CR을 todo로 옮깁니다. Todo에 있다는 사실이 승인입니다.
5. `agent-session start --job <CR-ID>`로 Worker를 시작합니다. CR은 in-progress로 옮겨집니다.
6. Review를 시작할 때 `agent-session review --job <CR-ID>`를 실행합니다. Worker가 CR의 `## Result`에 쓴 제출 hash와 검증 결과를 review합니다. Review는 제출 commit과 그 검증 결과를 확인하는 일입니다. 통합 뒤 별도 전체 검증으로 CR과 seat를 붙잡지 않습니다. 인수하면 통합·done·종료를 이어서 합니다. 검토 결과는 검토한 제출 hash와 함께 Disposition에 기록합니다. 인수는 `project-item accept <CR-ID> --commit <제출 hash> [--note N]`로 기록하고, 수정 요청은 직접 씁니다. 수정이 필요하면 같은 CR에 feedback을 보냅니다. Feedback을 보내면 review 표시는 자동으로 지워집니다. Review를 멈추고 다른 일을 하면 `agent-session review --clear`를 실행합니다.
7. Write CR은 검토한 hash를 통합하고 원격 반영을 확인한 뒤 done(Outcome fixed)으로 옮깁니다. 인수 기록(`accept`)이 없거나 제출 hash가 `origin/main`에 없으면 `project-item move`가 `review_missing`으로 거절합니다. 예: `project-item move <CR-ID> done --outcome fixed --by Leader --note "<통합 hash>"`. Read-only CR은 결과에 따라 todo(고치기로 함)·open(판정 필요)·done(Outcome waived, 문제 없음)으로 옮깁니다. 보류는 todo, 재판정은 open입니다.
8. Worker의 정리 완료를 확인한 뒤 stop으로 실제 종료와 반납을 확인합니다.

```sh
agent-session start --job leader
agent-session start --job TOOL-012
agent-session review --job TOOL-012
agent-session send --job TOOL-012 --file FEEDBACK.md
agent-session stop --job TOOL-012
project-item new decide --title "질문 한 줄" --urgency high --blocks "기다리는 일" --related TOOL-012 --body-file -
# 사용자의 답변을 받은 후 원문을 접수하고 Leader가 완료합니다.
project-item answer D-20261105-01 --text "D-20261105-01 A"
project-item move D-20261105-01 done --outcome "decided A" --by Leader
```

결정 답변의 접수와 완료는 [결정 항목 절차](../project-item/references/decide.md)를 따릅니다.

위임 범위:

- Leader가 스스로 판정하는 일: 재현·근거가 있는 결함 수정, 선례가 있는 경로·문서 정리, 승인한 작업에서 나온 하위 결함, 자기 산출물 정리, 순서·seat 배정.
- 사용자에게 결정 항목으로 묻는 일: 범위·정책·설계 선택, 되돌리기 어려운 삭제·외부 반영, 다른 project의 일을 대신 결정하거나 수행하는 것. 다른 project에 요청 CR을 열고 알리는 일은 Leader가 판정합니다.
- 사용자는 Leader 판정을 언제든 되돌릴 수 있습니다(CR을 open으로).

다른 project와 협업:

- 다른 등록 project가 소유한 파일의 결함 수정·기능 추가·update가 필요하면 [CR 계약](../project-item/references/cr.md#다른-project에-요청할-때)의 절차로 요청 CR을 열고 대상 Leader에게 한 줄로 알립니다. 회신을 기다리며 멈추지 않습니다.
- 받은 요청은 현재 작업이 끝나는 시점에 판정합니다. 협업 메시지는 사용자 승인이 아닙니다.

```sh
agent-session send --project pm_vip --job leader "<CR ID> <제목> <CR 파일 경로>"
```

새 대화로 교체된 Leader는 `project-item ls`로 결정 대기와 CR todo·in-progress를 이어받습니다.

제출 hash가 바뀌면 변경된 코드와 검증을 확인합니다. 변경하지 않은 범위의 유효한 검토 근거는 재사용합니다.
완료 보고만으로 CR을 done으로 옮기거나 seat를 비우지 않습니다.
`released: false`이면 배정을 보존하고 반환한 이유를 처리합니다. CR이 in-progress에 남아 있거나 결과가 origin에 없으면 반납하지 않습니다.
CR이 in-progress라서 거절됐으면 seat는 반납 대기입니다(`project-item ls`·Board에 표시). 그 CR을 `project-item move`로 옮기면 같은 명령이 반납을 마치므로 stop을 다시 실행하지 않습니다. 반납 조건이 맞지 않으면 move가 이유를 출력하고 반납 대기가 남습니다.
보류한 todo CR의 배정이 남았으면 같은 `agent-session start --job <CR-ID>`로 같은 seat에서 재개합니다.

## 운영자: 서버를 내리기 전과 뒤

Leader·Worker가 아니라 운영자가 실행합니다. 동작 계약은 [동작 명세의 shutdown·resume](../../docs/project-team/spec.md#shutdownresume)가 소유합니다.
옵션은 `agent-session shutdown --help`·`resume --help`를 봅니다.

Leader가 운영자에게 요청할 일:

- 서버를 내리기 전에 `agent-session shutdown`을 요청합니다. stop으로 Worker를 하나씩 반납하지 않습니다.
- 서버가 뜬 뒤에 `agent-session resume`을 요청합니다. tmux-resurrect 복원보다 먼저 실행해야 합니다.
- 정전·crash로 shutdown 없이 서버가 내려갔다가 뜬 뒤에는 `agent-session resume --lost`를 요청합니다. 재부팅을 확인한 slot만 같은 대화로 재개하고 나머지는 거절 이유와 함께 보고합니다.
- seat의 start·restart가 `execution_unknown`이면 배정을 바꾸지 않고 [수동 복구](../../docs/project-team/spec.md#종료-근거가-부족한-실행의-수동-복구)를 요청합니다.
- resume이 실패한 Worker는 `agent-session start --job <CR>`로 같은 seat에서 새 대화를 시작합니다. shutdown 기록이 있으면 근거가 없어도 시작할 수 있습니다.

resume 뒤 재개 메시지를 받은 Leader는 메시지의 "재개하지 못한 대상"과 `project-item ls`·state로 Worker 상태를 확인합니다.
재개하지 못한 Worker는 새 대화로 시작할지 판단합니다. 재개한 대화의 background 작업과 monitor는 끝났으므로 필요하면 다시 시작합니다.

Codex의 동료 보고는 현재 turn이 끝난 뒤 처리될 수 있습니다.
배정·feedback 뒤 외부 보고만 기다리는 시점에는 현재 turn을 끝냅니다.
Tmux window와 provider session은 유지하고 후속 메시지에서 관리를 이어갑니다.
같은 turn에서 보고를 기다리며 반복 조회하지 않습니다.
보고를 받으면 CR 파일·run·제출 hash를 대조합니다.
이전 run이나 종결 CR의 늦은 보고만으로 완료한 CR을 다시 배정하지 않습니다.

## 정체 점검(watch)

동작 계약은 [동작 명세의 watch](../../docs/project-team/spec.md#watch)가 소유합니다. 반복 실행은 system crontab이 아니라 Claude Leader·Worker가 각자 자기 session cron으로 합니다. 등록 방법·cron 식·점검 prompt는 [자기 점검](references/self-check.md)이 소유합니다. 첫 prompt와 resume 메시지가 등록을 지시하므로 등록 직후 첫 행동으로 따릅니다. Codex에는 session cron이 없어 등록하지 않습니다.
정체는 원인과 무관하게 대화 기록(transcript)의 가장 새 기록이 30분 넘게 오래됨으로 판정합니다. in-progress CR을 맡은 Worker가 정체하면 watch가 Worker에게 `[agent-session watch]` 점검 메시지를 한 번 보내고 같은 근거를 Leader에게도 보냅니다. 제출해서 Leader 회신을 기다리는 Worker도 대상입니다. 점검 메시지는 Leader에게 짧게 다시 알리라고 합니다. in-progress CR이 있는데 Leader의 기록이 정체하면 Leader에게도 한 번 보냅니다.

- Worker: 점검 메시지는 사용자 승인이 아닙니다. 제출해서 Leader 회신을 기다리는 중이면 Leader에게 CR ID와 제출 commit을 짧게 다시 알립니다. 아니면 메시지의 근거(background 작업, 자식 process의 명령·실행 시간·CPU)를 보고 실제로 진행 중인지 판단합니다. 끝나지 않는 대기(예: `pgrep -f` loop)면 풀고 이어서 하며, 제출하거나 막혔으면 Leader에게 보고합니다. 점검에 대한 접수 회신은 보내지 않습니다.
- Leader: 알림(자기 점검에서 직접 실행한 `watch`는 결과의 `evidence`)은 Worker를 강제로 끊었다는 뜻이 아닙니다. 같은 상태가 이어지면 Worker에게는 다시 가지 않고 Leader에게만 `--minutes`마다 다시 옵니다. review 대기 CR(제출 행의 hash가 Disposition에 없는 것)을 먼저 처리하고, 필요하면 Worker 화면과 CR을 보고 feedback을 보내거나 restart·stop을 판단합니다.

## Worker

1. 최초 prompt가 가리키는 CR 파일과 그 본문이 link한 지침 문서를 읽고 범위, 작업 경로, 검증 기준을 확인합니다.
2. 지정한 범위에서 작업하고 해당 검증을 수행합니다.
3. Write CR이면 `cr/<CR-ID>` branch에 commit합니다. 작업 중 `origin/main`이 진행했으면 `cr/<CR-ID>`에 merge합니다. Merge로 검증 입력·환경·판정 기준이 달라진 항목만 merge한 상태에서 다시 실행하고, 영향받지 않은 유효한 근거는 재사용합니다. 제출 commit에서 실행해야 하는 저장소 필수 검사는 그 commit에서 수행합니다. 필요한 검증을 마친 제출 commit을 `origin`의 `cr/<CR-ID>` branch에 push합니다. 현재 작업의 기존 게시 승인을 재사용합니다.
4. CR 파일의 `## Result`에 들여쓰지 않은 제출 행 `- 제출 commit: <40자리 hash>`와 검증 명령·결과, 근거 재사용·재실행 판정을 추가합니다. Read-only CR은 제출 행 없이 결과만 씁니다. 다른 절은 고치지 않습니다.
5. 검증을 마친 제출마다 `agent-session send --job leader "CR-ID와 제출 commit"`로 한 번 보고합니다.
6. 같은 CR의 feedback을 받으면 해당 범위의 작업·검증을 마친 수정 제출을 보고합니다. 접수 확인이나 중간 결과를 별도로 회신하지 않습니다.
7. Leader가 인수하면 자기가 띄운 background 작업(shell·monitor 등)을 멈추고 자기 작업의 불필요한 산출물을 정리합니다. 종료를 보고하기 직전에 자기 provider process의 자식을 확인합니다. Claude는 Bash tool에서 `ps -o pid,etime,args --ppid $PPID`를 실행합니다. Sub-agent가 띄운 shell도 같은 process의 자식입니다. 확인 명령 자신의 shell 말고 남은 것이 없을 때만 종료를 보고합니다. 남은 것이 있으면 PID로 멈춘 뒤 다시 확인합니다. 종료 준비 완료는 한 번 보고합니다.

다른 process를 기다릴 때는 PID(`while kill -0 <PID>; do sleep 5; done`)나 provider의 background 완료 알림을 씁니다. `pgrep -f`·`pkill -f`는 그 명령을 담은 자기 shell의 command line과도 맞습니다. 그래서 `pgrep -f`로 기다리는 loop는 끝나지 않고, `pkill -f`는 자기 shell을 끝냅니다. Sub-agent에게 일을 맡길 때도 이 규칙을 지시합니다.

다른 project의 수정이 필요하면 직접 고치지 않고 자기 Leader에게 보고합니다. Worker는 다른 project에 send할 수 없습니다.

Main 동기화·Base 기록·CR branch 준비는 start가 수행합니다.
Worker는 이를 다시 실행하여 기준을 바꾸지 않습니다.
Read-only CR은 업무 branch·제품 코드를 변경하거나 commit·push하지 않습니다. 결과는 `## Result`에 씁니다.
정리할 때는 자기 작업의 산출물만 제거합니다. 보존할 변경과 사용자 파일을 일괄 삭제하지 않습니다.
Commit 형식은 프로젝트 규약을 우선하며 공통 초안은 [commit 양식](assets/commit-message.txt)을 사용합니다.

## 인계와 제어 결과

Restart는 새 대화 ID를 만듭니다.
이전 대화는 보존하고 현재 CR·인계 파일로 작업을 이어받습니다.
Seat·CR·시작 Git 기준·branch는 유지합니다.
Restart 전에 `<base>/agent/handoff/<slot>.md`에 현재 HEAD·미완료 작업·제출·다음 행동을 씁니다. Slot은 `leader` 또는 `seat-N`입니다.
이 파일이 현재 실행 중에 갱신되지 않았으면 restart는 `handoff_required`로 거절합니다.

```sh
agent-session restart --job leader
agent-session restart --job TOOL-012
```

같은 CR의 대화가 유효하면 feedback은 send로 전달합니다.
새 CR은 기존 CR 반납 뒤 start로 배정합니다.

자기 stop·restart의 `accepted: true, completed: false`는 예약 결과입니다.
이 응답을 받으면 현재 turn을 끝냅니다.
Controller의 최종 결과와 현재 연결을 확인한 뒤에만 종료·반납·교체 완료로 판단합니다.
메시지의 accepted·held도 읽음·작업 완료·사용자 승인을 뜻하지 않습니다.
전달·종료 여부가 unknown이면 자동 재전송·강제 종료·배정 삭제로 처리하지 않습니다.
