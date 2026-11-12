# TEST-018: project-board test가 xdist worker마다 stale Rust binary를 따로 build해 경쟁

- Opened: 2026-11-12
- Scope: project-agent
- Severity: S3

## Symptom
2026-11-12에 BOARD-028 Worker가 Rust 소스를 고친 뒤 `python -m pytest -q -n 8 tools/project-board/tests`를 실행했습니다. 이때 `test_rust_equivalence.py`에서 test 실패가 아닌 error가 98건 났습니다. Worker는 binary를 먼저 build한 뒤 같은 명령을 다시 실행했고, 539 passed였습니다(BOARD-028 Result "수정 제출").

## Evidence
- `tools/project-board/tests/rust_binary.py` `sidebar_binary()`는 binary가 없거나 소스보다 오래됐으면 `cargo build --release --offline --locked`를 실행합니다. 이 판단과 build를 process마다 따로 합니다. 그래서 xdist worker 8개가 같은 stale binary를 보고 각자 build합니다. process 사이의 잠금이나 "한 번만 build"는 없습니다.
- cargo는 자기 build 디렉터리를 잠그므로 build 자체는 차례로 돕니다. 그러나 다음 경우는 막지 못합니다(가설, 확인하지 않음):
  - 다른 worker가 아직 쓰고 있거나 바꾸고 있는 `target/release/project-board-sidebar`를 한 worker가 "새것"으로 보고 실행하는 경우.
  - 실행 중인 binary를 cargo가 바꾸는 경우.
- README 검증의 project-board 명령은 `-n` 없이 돌지만, seat들은 `-n 8`로 자주 돌립니다. README는 "binary가 없거나 소스보다 오래됐으면 build로 만든다"고 약속하고, 실행 방식에 따른 예외를 두지 않습니다.

## Contract
1. 같은 checkout에서 test process 여럿(xdist worker, 같은 checkout의 동시 run)이 stale binary를 만나도, binary는 한 번만 build합니다. 모든 test는 완전히 쓰인 같은 binary를 실행합니다. Build 경쟁으로 생기는 error·실패는 없습니다.
2. Build가 실패하면 지금처럼 skip이 아니라 error이고, 그 출력을 보입니다.
3. `PROJECT_BOARD_SIDEBAR_BIN`·`CARGO_TARGET_DIR`·`PROJECT_AGENT_CARGO`의 의미는 그대로입니다. 각 도구 test의 독립 실행도 유지합니다.

## Disposition
- 2026-11-12 Leader 판정: 고칩니다. 실제로 관찰한 test infra 결함입니다. README가 약속한 "없거나 오래되면 build"가 동시 실행에서 깨집니다.
  - 근본 원인: "build가 필요한가"의 판단과 build 자체가 process마다 따로 이루어지고, 둘 사이를 잇는 단일 소유자(잠금이나 한 번만 build)가 없습니다.
  - 해결 방향은 둘 중 하나입니다. 하나는 판단과 build를 process 사이 잠금 하나 아래로 묶는 것이고, 다른 하나는 xdist controller에서 run마다 한 번만 build한 뒤 worker는 결과 경로만 받는 것입니다. 어느 쪽을 택할지는 Worker가 Contract를 기준으로 정합니다.
  - 다음 release를 설치한 뒤 시작합니다(release 검증의 부하를 늘리지 않기 위함).
- 2026-11-12 Leader: open -> todo.

## Implementation
읽을 문서:
- [README 검증](../../../README.md#검증): project-board test의 Rust binary 문장.
- 코드:
  - `tools/project-board/tests/rust_binary.py`.
  - 이 helper를 부르는 test와 fixture(`test_rust_equivalence.py`, `test_sidebar_binary.py`, `test_sidebar_release.py` 등).
- 절차: [project-team Worker 절](../../../skills/project-team/SKILL.md#worker).

1. 먼저 재현합니다. 소스 mtime을 갱신해 binary를 stale로 만든 뒤 `python -m pytest -q -n 8 tools/project-board/tests`를 실행해 error를 얻고, error의 실제 원인을 Result에 적습니다(Evidence의 가설을 확인하거나 고칩니다).
2. Contract 1~3을 만족하게 고칩니다. 이 helper를 쓰는 모든 경로가 같은 하나의 방법을 거칩니다.
3. README의 문장을 실제 보장에 맞게 고칩니다.
4. Test (관측 동작):
   - stale binary와 여러 process가 동시에 binary를 요청할 때 build가 한 번만 일어나고, 모두 같은 완전한 binary를 받는지 확인합니다.
   - build가 실패하면 error와 출력이 나오는지 확인합니다.

위험 등급: 낮음(test helper만 바뀜).

## Verification
- README 검증 표:
  - `tools/project-board/**`: `python -m pytest -q tools/project-board/tests`, `python -m pytest -q tools/agent-session/tests/test_api_boundary.py`.
  - 문서: 고친 문서의 상대 link 검사, `python -m pytest -q tools/test_distribution_boundary.py`.
- 재현 확인: stale binary 상태에서 `python -m pytest -q -n 8 tools/project-board/tests`를 실행합니다. 고치기 전 commit에서는 error가 나고 제출 commit에서는 통과하는 것을 Result에 적습니다.
