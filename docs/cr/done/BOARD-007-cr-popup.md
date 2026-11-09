# BOARD-007: 결정·CR popup의 항목 목록과 선택한 항목 표시가 이상합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S3
- Base: b2038ee30d386a2a7b0730df7abb7fd96a6410c5 2026-11-10T00:19:24+09:00
- Outcome: fixed

## Symptom
사용자 보고: "Decision / CR을 위한 popup 창에서 item의 list, selected item에 대한 표시가 너무 이상함." 구체적인 화면은 아직 받지 않았습니다.
출처: 사용자 개선 요청 2026-11-09(대화, 11개 항목 중 8번).

## Evidence
- popup TUI는 `tools/project-board/project_board/tui.py`의 `PopupApp`·`CRPopupApp`입니다.

## Contract
- 목록에서 각 항목을 알아볼 수 있고, 지금 선택한 항목이 분명히 구별되어야 합니다([TUI 계획](../../project-board-tui-plan.md)).

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). 사용자가 표시 결함을 보고했고 위임 범위입니다. 구체 화면이 없으므로 Worker가 지금 화면을 capture해 문제를 목록으로 만들고, 고친 화면과 함께 Result에 둡니다. BOARD-002 뒤에 시작합니다. 사용자 지시(2026-11-09 대화): "위와 같이 11개의 개선 요청 사항이 있어."
- 2026-11-10 Leader: 선행 BOARD-002가 61e881e로 통합되었습니다(BOARD-003·004 병합). 그 구조를 따르십시오: Board pane은 본 window에 남고(최대 8개, 최근 본 순서), 보이지 않는 pane은 갱신하지 않으며(`project_board_visibility.sh`의 SIGUSR1), 파일은 바뀐 것만 다시 읽습니다(TUI 계획 2·5절). Board CR 다섯 개가 같은 `tui.py`·`tmux_control.py`를 고칠 수 있으므로 제출 전에 `origin/main`을 merge하십시오.
- 2026-11-10 Leader: 제출 1d85bbf551541ad9b92152bf09b94336d7fb7d17를 인수합니다. Leader review: TUI 계획의 'Popup 목록 행과 선택 표시' 규칙과 80·120열 고치기 전·뒤 capture, 문제 7개의 해결(선택 ▶·파란 배경, 한 줄 행과 … 줄임, 결정 상태 색, 목록 폭 40%, 초점과 선택 구분, 제목 markup 차단, review_wait 표시)을 확인했습니다. 가정(CR 행 상태는 목록 머리줄이 표시하므로 행에는 review_wait만)은 받아들입니다. merge 없음(origin/main 진행 없음).
- 2026-11-10 Leader: in-progress -> done, Outcome fixed. 통합 c5f8e3e(Merge cr/BOARD-007, 제출 1d85bbf). origin/main 반영 확인. CHANGELOG Unreleased에 더했습니다.

## Implementation
읽을 문서: [project-board README](../../../tools/project-board/README.md), [TUI 계획](../../project-board-tui-plan.md), [설치 계약 5.3·5.4절](../../project-team/install-contract.md), [README 검증 표](../../../README.md#검증).

1. 지금 화면: 결정 popup과 CR popup을 실제 크기의 격리 tmux에서 열어 목록·선택 표시를 text capture로 남기고, 읽기 어려운 점(정렬, 잘림, 선택 강조, 상태 구분, 긴 제목)을 목록으로 적습니다.
2. 고침: 각 항목을 한 줄에 알아볼 수 있게(ID·상태·제목, 긴 제목은 정해진 방식으로 줄임), 선택한 항목을 색과 표시로 분명히 구별하게 합니다. 규칙을 [TUI 계획](../../project-board-tui-plan.md)에 먼저 적습니다.

의존: 선행 BOARD-002.

## Verification
1. 고치기 전·뒤 화면 capture(80열·120열 두 크기)와 1단계 목록의 항목마다 해결 여부.
2. README 검증 표의 `tools/project-board/**` 행.

## Result

- 제출 commit: 1d85bbf551541ad9b92152bf09b94336d7fb7d17

`origin/main`은 Base(b2038ee)에서 진행하지 않아 merge가 없습니다. 규칙은 [TUI 계획](../../project-board-tui-plan.md)의 "Popup 목록 행과 선택 표시"에 먼저 적었습니다.

### 1단계: 고치기 전 문제 목록과 해결 여부

실제 크기(80·120열 x 28행) 격리 tmux(`tmux_test_server.claim`)에서 `project-board cr`·`popup`을 실행해 `capture-pane -p`(text)와 `-e`(색)로 얻었습니다. 항목은 CR 5개(긴 영문·긴 한글 제목 포함), 결정 4개(대기 2·접수·반영)입니다.

| # | 고치기 전 문제 | 해결 |
| --- | --- | --- |
| 1 | 선택 항목과 아닌 항목의 스타일이 같습니다(모두 같은 회색 배경·굵은 글자, ANSI 확인). 선택을 알 방법이 본문 제목뿐입니다 | 선택 행은 `▶`, 파란 배경(47;109;179), 굵은 흰 글자. 선택하지 않은 행은 공백 표식·어두운 배경 |
| 2 | 항목이 2줄 이상입니다. ID와 제목이 다른 줄이고 긴 제목은 4~7줄로 줄바꿈해 다음 항목과 구별이 안 됩니다 | 항목마다 한 줄. 끝을 `…`로 줄임(ID·상태는 항상 보임) |
| 3 | 결정 목록에서 `· 결정 대기`가 80열에서 ID 아래 줄로 밀립니다 | 한 줄 `▶ ID 대기 제목`. 상태를 짧게 하고 색으로 구분(대기 노랑·접수 하늘·반영 초록) |
| 4 | 목록 칸이 28%(80열에서 22칸)라 ID(13칸)와 상태가 들어가지 않습니다 | 40%, 30~46칸(80열 32칸, 120열 46칸) |
| 5 | Tab 초점도 선택과 구별되지 않습니다(Button 기본 reverse) | 초점(비선택)은 밝은 회청색 배경, 선택은 파란 배경으로 서로 다름 |
| 6 | 제목의 `[...]`가 Button markup으로 해석될 수 있습니다 | 라벨을 `Content.assemble`로 만들어 제목을 markup으로 해석하지 않음(테스트) |
| 7 | CR 목록에 상태 구분이 없습니다(`review_wait` 항목도 같음) | `review_wait`인 in-progress CR에 노란 `검토` 표시. 그 밖의 CR 상태는 목록 하나가 상태 하나라 머리줄이 표시하므로 행에 반복하지 않음(판단 근거는 계획에 기록) |

가정: CR 행의 "상태"를 목록 상태(open/todo/in-progress)가 아니라 항목별로 달라지는 `review_wait`로 해석했습니다. 행마다 같은 값을 반복하면 80열에서 제목이 더 줄기 때문입니다. 행마다 상태를 보이기를 원하시면 `tui._cr_status` 한 곳을 바꿉니다.

### 2단계: 고치기 전·뒤 화면(위 14줄 이내, 목록 부분)

**cr popup, 80열, 고치기 전**

```text
 Falcon2 · open 1/5 · CPU-001

  CPU-001            │
  Popup 목록 표시    │
  CPU-002            │                CPU-001: Popup 목록 표시
  A very long title  │
  that certainly     │   • Opened: 2026-11-05
  will not fit       │   • Scope: board test
  within a narrow    │   • Severity: S3
  popup list column  │   • Base: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
  at eighty columns  │     2026-11-05T09:00:00+09:00
  CPU-003            │
```

**cr popup, 80열, 고친 뒤**

```text
 Falcon2 · open 1/5 · CPU-001

 ▶ CPU-001 Popup 목록 표시     │
   CPU-002 A very long title … │
   CPU-003 아주 긴 한글 제목 … │           CPU-001: Popup 목록 표시
   CPU-004 Short               │
   CPU-005 short two           │   • Opened: 2026-11-05
                               │   • Scope: board test
                               │   • Severity: S3
                               │   • Base:
                               │     bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
                               │     bb 2026-11-05T09:00:00+09:00
```

**cr popup, 120열, 고치기 전**

```text
 Falcon2 · open 1/5 · CPU-001

  CPU-001                       │
  Popup 목록 표시               │
  CPU-002                       │                              CPU-001: Popup 목록 표시
  A very long title that        │
  certainly will not fit        │   • Opened: 2026-11-05
  within a narrow popup list    │   • Scope: board test
  column at eighty columns      │   • Severity: S3
  CPU-003                       │   • Base: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 2026-11-05T09:00:00+09:00
  아주 긴 한글 제목입니다 이    │
  제목은 좁은 목록 칸에         │
```

**cr popup, 120열, 고친 뒤**

```text
 Falcon2 · open 1/5 · CPU-001

 ▶ CPU-001 Popup 목록 표시                   │
   CPU-002 A very long title that certainly… │
   CPU-003 아주 긴 한글 제목입니다 이 제목 … │                        CPU-001: Popup 목록 표시
   CPU-004 Short                             │
   CPU-005 short two                         │   • Opened: 2026-11-05
                                             │   • Scope: board test
                                             │   • Severity: S3
                                             │   • Base: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
                                             │     2026-11-05T09:00:00+09:00
                                             │
```

**decision popup, 80열, 고치기 전**

```text
 Falcon2 · 결정 1/4 · D-20261107-01 · 결정 대기

  D-20261107-01    │ 기다리는 질문 하나
  · 결정 대기      │ 상태: 결정 대기
  기다리는 질문    │ 긴급도: high
  하나             │ 막는 일: TOOL-002
  D-20261107-02    │ Background
  · 결정 대기      │   배경 입니다.
  A very long      │
  decision         │ Options
  title that       │   ┌────────────────────────────┬─────────────────────┐
  certainly        │   │ 선택지                     │ 내용                │
```

**decision popup, 80열, 고친 뒤**

```text
 Falcon2 · 결정 1/4 · D-20261107-01 · 결정 대기

 ▶ D-20261107-01 대기 기다리 … │ 기다리는 질문 하나
   D-20261107-02 대기 A very … │ 상태: 결정 대기
   D-20261107-03 접수 접수된 … │ 긴급도: high
   D-20261107-04 반영 반영 중… │ 막는 일: TOOL-002
                               │ Background
                               │   배경 입니다.
                               │
                               │ Options
                               │   ┌─────────────────────┬────────────────┐
                               │   │ 선택지              │ 내용           │
```

**decision popup, 120열, 고치기 전**

```text
 Falcon2 · 결정 1/4 · D-20261107-01 · 결정 대기

  D-20261107-01 · 결정 대기   │ 기다리는 질문 하나
  기다리는 질문 하나          │ 상태: 결정 대기
  D-20261107-02 · 결정 대기   │ 긴급도: high
  A very long decision title  │ 막는 일: TOOL-002
  that certainly will not     │ Background
  fit within a narrow list    │   배경 입니다.
  column                      │
  D-20261107-03 · 답변 접수   │ Options
  접수된 질문                 │   ┌────────────────────────────────────────────┬──────────────────────────────────┐
  D-20261107-04 · 반영 중     │   │ 선택지                                     │ 내용                             │
```

**decision popup, 120열, 고친 뒤**

```text
 Falcon2 · 결정 1/4 · D-20261107-01 · 결정 대기

 ▶ D-20261107-01 대기 기다리는 질문 하나     │ 기다리는 질문 하나
   D-20261107-02 대기 A very long decision … │ 상태: 결정 대기
   D-20261107-03 접수 접수된 질문            │ 긴급도: high
   D-20261107-04 반영 반영 중인 질문         │ 막는 일: TOOL-002
                                             │ Background
                                             │   배경 입니다.
                                             │
                                             │ Options
                                             │   ┌────────────────────────────────────┬───────────────────────────┐
                                             │   │ 선택지                             │ 내용                      │
```

색은 ANSI capture로 확인했습니다. 고친 뒤 선택 행: `48;2;47;109;179`(배경)·`1`(굵게)·`38;2;255;255;255`(글자), 상태 글자 `대기`는 `38;2;255;207;112`, 비선택 행 배경은 `48;2;23;34;47`입니다.

### 검증

- `python -m pytest -q tools/project-board/tests`: 152 passed(제출 commit `1d85bbf`). README 검증 표의 `tools/project-board/**` 행입니다.
- 바뀐 label을 보는 기존 test 3건을 새 형식으로 고쳤고, 새 test 3건(4 case: 80·120열 한 줄 행과 선택 표식·클래스, 긴 제목에서도 ID·상태 유지와 `…`, 클릭 시 선택 이동, `review_wait` 표시, 제목 markup 비해석)을 추가했습니다.
- `docs/**` 변경(TUI 계획 한 절)은 상대 link를 바꾸지 않았습니다. 근거 재사용·재실행: `origin/main`이 Base와 같아 merge로 달라진 입력이 없습니다.
