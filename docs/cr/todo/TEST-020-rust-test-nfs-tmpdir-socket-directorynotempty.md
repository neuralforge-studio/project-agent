# TEST-020: Rust test가 NFS TMPDIR에서 socket 디렉터리를 지우다 DirectoryNotEmpty로 실패

- Opened: 2026-11-13
- Scope: project-agent
- Severity: S1

## Symptom
2026-11-13에 0.12.0 release를 검증했습니다(clone, release commit 4e9044f, TMPDIR=`/primehome/swain/tmp`, NFS). `(cd tools/project-board/rust && cargo test --offline --locked)`가 96 passed, 1 failed였습니다.
- 실패한 test: `window::tests::a_request_is_one_json_line_and_the_reply_one_json_line`
- 패닉 위치: `src/window.rs:184:39`. `called Result::unwrap() on an Err value: Os { code: 39, kind: DirectoryNotEmpty }`
실패 뒤에 `/primehome/swain/tmp/pbw-3089372`가 빈 디렉터리로 남았습니다. 0.11.0 검증에서는 같은 test가 통과했습니다.

## Evidence
- 이 test는 `std::env::temp_dir()`(TMPDIR, 이 host에서는 NFS) 아래 `pbw-<pid>`에 Unix socket을 만들고, 끝에 `remove_dir_all(...).unwrap()`을 부릅니다(`src/window.rs:167-185`).
- 가설(확인하지 않음): NFS는 열린 파일을 지우면 그 파일을 `.nfsXXXX`로 이름을 바꿔 둡니다(silly rename). 그래서 지우는 순간 디렉터리가 비어 있지 않았습니다. 같은 process의 다른 test thread가 fork한 자식이 exec 전에 fd를 잠깐 들고 있었을 수 있습니다. 실패 뒤 디렉터리가 비어 있었던 것은 이 가설과 맞습니다.
- 다른 Rust test도 같은 모양입니다.
  - `pbw2-<pid>`(`window.rs:189`), `pbr-<label>-<pid>`(`release.rs:203`, Drop에서 오류 무시)도 TMPDIR 아래 pid 이름 디렉터리를 씁니다.
  - pytest 쪽에는 test 임시 디렉터리 규칙(`tools/tests/private_root.py`, README 검증 "임시 디렉터리")이 있지만, `cargo test`는 pytest 밖이라 그 규칙의 대상이 아닙니다.

## Contract
1. Rust test는 TMPDIR이 NFS여도, 다른 test thread나 process와 동시에 돌아도 정리 단계 때문에 실패하지 않습니다.
2. Rust test의 임시 파일과 socket은 test마다 고유한 위치에 만들고, 통과한 test는 남기지 않습니다. 이 위치를 만들고 지우는 방법은 Rust test helper 한 곳이 소유합니다.
3. README 검증의 임시 디렉터리 규칙에 `cargo test`가 어떻게 따르는지(또는 왜 다른지)를 적습니다.

## Disposition
- 2026-11-13 Leader 판정: 고칩니다. 0.12.0 release 검증을 막은 test 결함입니다.
  - 근본 원인 후보: Rust test가 임시 위치를 각자 TMPDIR 아래 pid 이름으로 만들고, NFS에서 즉시 지워진다고 가정합니다. 정확한 원인은 Worker가 확인합니다.
  - release를 막는 항목이므로 바로 시작합니다.
- 2026-11-13 Leader: open -> todo.

## Implementation
읽을 문서:
- [README 검증](../../../README.md#검증): 임시 디렉터리, Rust test.
- [설치 계약 2.1절](../../project-team/install-contract.md#21-rust-sidebar의-build).
- 코드: `tools/project-board/rust/src/`(`window.rs`, `release.rs`, 그리고 임시 파일이나 socket을 쓰는 모든 test), `tools/tests/private_root.py`(pytest 쪽 규칙, 참고).
- 절차: [project-team Worker 절](../../../skills/project-team/SKILL.md#worker).

1. 먼저 재현하고 원인을 확인합니다. NFS TMPDIR에서 `cargo test`를 반복 실행하고, 실패 시점에 디렉터리 안에 무엇이 있는지 확인합니다. 결과를 Result에 적습니다.
2. Rust test의 임시 위치를 만들고 지우는 helper 하나를 둡니다(test마다 고유한 위치). 모든 Rust test가 그것을 씁니다.
3. 정리가 NFS의 동작(열린 파일의 silly rename 등)에도 test를 실패시키지 않게 하고, 통과한 test가 흔적을 남기지 않게 합니다. 방법은 확인한 원인에 맞춰 Worker가 정합니다.
4. README의 임시 디렉터리 규칙에 `cargo test`를 적습니다.

위험 등급: 낮음(test만 바뀜).

## Verification
- README 검증 표 `tools/project-board/rust/**`:
  - `(cd tools/project-board/rust && cargo test --offline --locked)`
  - `python -m pytest -q tools/project-board/tests`
  - 네 번째 명령
- 문서: 고친 문서의 상대 link 검사, `python -m pytest -q tools/test_distribution_boundary.py`.
- 반복 확인: NFS TMPDIR(이 host의 기본)에서 `cargo test`를 여러 번 반복해 모두 통과하는 것을 Result에 적습니다.
