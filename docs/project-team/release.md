# project-agent 버전 규칙

이 문서는 project-agent의 버전 값, 형식 버전과 호환 범위, git tag 이름, 변경 기록의 작성 규칙을 소유합니다. 설치 경로와 설치기의 동작은 [설치 계약](install-contract.md)이 소유합니다.

## 1. 버전 값

- 원본은 저장소 root의 `VERSION` 파일입니다. 첫 줄 하나가 `MAJOR.MINOR.PATCH`([SemVer](https://semver.org/lang/ko/))이고 다른 내용은 없습니다. 첫 값은 `0.1.0`입니다.
- 설치기는 이 값으로 release 이름 `<version>-<hash>`를 만듭니다([설치 계약 1절](install-contract.md#1-용어)). 이름 형식은 설치기와 맞춘 interface이므로 바꾸지 않습니다.
- `VERSION`은 마지막으로 낸 release의 버전입니다. 첫 release 전에는 첫 release가 될 `0.1.0`입니다. 값은 release를 내는 commit(5절)에서만 올립니다.

## 2. MAJOR·MINOR·PATCH

| 올리는 값 | 조건 |
| --- | --- |
| MAJOR | 직원이 조치해야 하는 호환 파괴: 3절의 형식 버전을 올리는 변경, 공개 진입점(CLI 명령·옵션·JSON 출력, [제품 지도](README.md#공개-진입점))의 제거나 의미 변경, [설치 계약 2절](install-contract.md#2-설치가-만드는-것)의 설치 경로 변경 |
| MINOR | 호환되는 기능 추가: 새 명령·옵션·JSON 필드, 이전 release가 무시하는 tmux option 추가 |
| PATCH | 공개 계약을 바꾸지 않는 결함 수정과 문서 수정 |

MAJOR가 0인 동안(1.0.0 전)은 호환 파괴도 MINOR로 올립니다(SemVer 4항). 그 외 규칙은 같습니다. 한 release에 여러 변경이 있으면 가장 큰 값을 올립니다.

## 3. 형식 버전과 호환 범위

release가 함께 쓰는 형식은 셋이며, 각 버전은 [`tools/formats.json`](../../tools/formats.json)에 선언합니다. 이 파일이 형식 버전의 유일한 원본입니다. 첫 값은 모두 1입니다.

| 키 | 형식 | 형식의 원본 |
| --- | --- | --- |
| `agent_session` | agent-session의 `<base>/agent/state.json`과 관리 window option `@agent_session_*` | [동작 명세 3절](spec.md#3-statejson) |
| `tmux_options` | tmux 통합이 읽고 쓰는 `@project_board_*`, `@project_agent_*` option | [제품 지도](README.md#공개-진입점), [설치 계약 3.1절](install-contract.md#31-통합-파일이-server에-넣는-binding) |
| `item_files` | CR·결정 파일의 header·절·상태 이름 | [cr.md](../../skills/project-item/references/cr.md), [decide.md](../../skills/project-item/references/decide.md) |

- **올리는 때**: 이전 release가 쓴 것을 새 release가 올바르게 읽지 못하거나, 새 release가 쓴 것을 이전 release가 잘못 읽는 변경입니다. 예: 필드·option·header의 제거나 이름 변경, 값의 의미 변경, 필수 항목 추가. 형식 버전을 올리면 2절에 따라 MAJOR를 올립니다.
- **올리지 않는 때**: 이전 release가 무시하는 추가(선택 필드·새 option)입니다. MINOR를 올립니다.
- **호환 범위**: 세 값이 모두 같은 release끼리만 호환합니다. 하나라도 다르면 호환하지 않습니다. 배포와 갱신은 run이 동작하는 중에 하므로(조용한 시점이 없습니다), 떠 있는 run의 release와 형식 버전이 다른 release로 `upgrade`·`rollback`하는 요청을 설치기가 거절합니다. 판정 규칙(떠 있는 run의 찾기, 동결 사본의 판정, 거절 출력)은 [설치 계약 7.1.1절](install-contract.md#711-떠-있는-run과-형식-버전)이 소유하고, 이 문서는 값의 뜻만 정합니다.
- agent 저장소의 동결 사본(첫 release 전에 쓰던 `agent-session` 등)은 세 형식 모두 버전 1로 봅니다.

## 4. git tag

- 이름은 `v<VERSION>`입니다. 예: `v0.1.0`. `VERSION`의 값과 항상 같습니다.
- tag는 release를 내는 commit(5절)에 만듭니다. 이미 만든 tag는 옮기거나 지우지 않습니다. 틀린 release는 다음 PATCH로 고칩니다.
- tag를 만들고 push하는 사람은 Leader입니다. 첫 `v0.1.0`은 새 계정 시범 설치가 통과한 뒤 만듭니다.

## 5. 변경 기록과 release 절차

변경 기록은 root의 [`CHANGELOG.md`](../../CHANGELOG.md)입니다. 어느 version에 어느 CR이 들어갔는지는 이 파일이 CR ID 목록으로 답합니다. CR 파일에는 version을 적지 않습니다([CR 계약 "release와 CR"](../../skills/project-item/references/cr.md#release와-cr)).

- 구조: 맨 위에 `## Unreleased`, 그 아래에 최신 순으로 `## <version> - <YYYY-MM-DD>` 절을 둡니다.
- 절의 내용:
  - CR ID 목록: 한 줄에 CR ID 하나(`- REPO-001`). 제목과 내용은 `docs/cr/`의 CR 파일이 원본이므로 적지 않습니다.
  - `형식:` 줄: 3절의 형식 버전이 바뀌었으면 키와 값(예: `agent_session 1 → 2`), 바뀌지 않았으면 `변경 없음`.
- 쌓는 때: Leader가 CR을 통합하고 done(`fixed`)으로 옮길 때 그 CR의 ID를 `Unreleased`에 더합니다. 같은 commit에서 형식 버전을 올렸으면 `Unreleased`의 `형식:` 줄도 고칩니다. 통합하지 않은 CR(waived·merged)은 적지 않습니다.
- release 전 검증: Leader는 release를 내는 commit에서 [README의 검증](../../README.md#검증)의 명령을 모두 실행합니다. 거기에 Rust sidebar의 두 확인을 더합니다. cargo와 vendored crate는 [설치 계약 2.1절](install-contract.md#21-rust-sidebar의-build)이 정합니다.
  - Rust 단위 test: `tools/project-board/rust`에서 `CARGO_TARGET_DIR=<저장소 밖 디렉터리> cargo test --offline --locked`.
  - build 성공: 같은 위치의 `cargo build --release --offline --locked`와 같은 설치기의 build를 진짜 cargo로 실행하는 `install/tests`의 T40(`slow`)입니다. T40은 진짜 cargo가 없는 host에서는 건너뛰므로, 그런 host에서 낸 release는 이 확인을 하지 않은 것입니다.
- release를 내는 commit: Leader가 한 commit에서 (1) `Unreleased`의 항목을 `## <version> - <날짜>` 절로 옮기고 빈 `Unreleased`를 남기며, (2) 2절로 정한 새 값을 `VERSION`에 쓰고, (3) 그 commit에 4절의 tag를 만듭니다.
