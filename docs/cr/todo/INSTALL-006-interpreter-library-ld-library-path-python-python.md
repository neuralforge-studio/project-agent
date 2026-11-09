# INSTALL-006: 설치기가 interpreter에 필요한 library 경로를 기록하지 않아, LD_LIBRARY_PATH가 없는 환경에서 사내 Python이 다른 Python처럼 동작합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2

## Symptom
설치본은 `tools/python.env`에 설치 interpreter의 경로만 기록합니다. 사내 Python(`/primehome/tools/Inhouse/Python3/latest/bin/python3`)은 자기 `lib`이 `LD_LIBRARY_PATH`에 없으면 시스템 libpython으로 떠서 `sys.prefix=/usr`가 되고, 사내 site-packages(`textual` 등)가 보이지 않습니다. 사내 환경 설정이 없는 계정, cron, 그런 환경에서 시작한 tmux server에서는 Board가 시작하지 않습니다. 안내문 1절의 "사내 Python에는 있습니다"도 이 조건에서는 사실이 아닙니다.

## Evidence
- RELEASE-003 시범 설치 F1(2026-11-09, `docs/cr/in-progress/RELEASE-003-release.md` Result): 변형 A(`env -i`)에서 `$PY -c 'import textual'`이 ModuleNotFoundError, `check`가 Note로만 안내.
- Leader 재현: `env -i PATH=/usr/bin:/bin /primehome/tools/Inhouse/Python3/latest/bin/python3 -c 'import sys; print(sys.prefix)'` → `/usr`. `LD_LIBRARY_PATH=/primehome/tools/Inhouse/Python3/latest/lib`를 주면 `/primehome/tools/Inhouse/Python3/latest`.
- `tools/python-launcher.sh:48`: `LD_LIBRARY_PATH`는 개발 checkout의 Workstation 규칙에서만 설정. `PROJECT_AGENT_PYTHON`(설치본, `python.env`) 경로에서는 설정하지 않음.
- 설치 계약 6.1절: 설치본은 설치 때 고른 interpreter만 쓰고 다른 interpreter로 되돌아가지 않음.

## Contract
- 설치 계약 6.1절: 설치본의 진입점은 설치 때 고른 interpreter로 실행됩니다. 그 interpreter가 설치 때와 같은 interpreter(같은 `sys.prefix`)로 떠야 이 계약이 지켜집니다.

## Disposition
- 2026-11-09 Leader: 고친다(Leader 판정). RELEASE-003 시범 설치에서 재현된 동작 결함이므로 위임 범위입니다. 근본 원인은 설치기가 interpreter의 경로만 기록하고, 그 interpreter가 자기 자신으로 뜨는 데 필요한 환경(library 경로)은 기록하지 않는다는 점입니다. 첫 release(v0.1.0)는 이 CR과 RELEASE-003의 F1 재확인 뒤에 냅니다.

## Implementation
읽을 문서: [설치 계약](../../project-team/install-contract.md) 6.1절·7절, [안내문](../../install.md) 1절, `tools/python-launcher.sh`, [README 검증 표](../../../README.md#검증).

1. 설치 때 interpreter의 실행 조건을 확정합니다. 설치기를 실행한 interpreter의 `sys.prefix`와 실제 libpython 위치를 확인하고, 빈 환경(`env -i`)에서 그 interpreter가 같은 `sys.prefix`로 뜨는지 시험합니다. 다르면 같은 interpreter로 뜨게 하는 library 경로(예: `<prefix>/lib`)를 정합니다. 그 경로로도 같아지지 않으면 설치를 거절하고 이유를 출력합니다.
2. 정한 library 경로를 `python.env`에 새 이름(예: `PROJECT_AGENT_LD_LIBRARY_PATH`)으로 기록하고, launcher가 설치 interpreter를 실행할 때 그 값을 `LD_LIBRARY_PATH` 앞에 붙입니다. 개발 checkout 규칙은 바꾸지 않습니다. 계약 6.1절의 `python.env` 형식(허용 이름 목록)을 먼저 고칩니다.
3. `check`가 launcher를 거쳐 설치 interpreter를 빈 환경에서 실행해 `sys.prefix`가 설치 때와 같은지 확인하고, 다르면 실패로 알립니다. Board package 확인(`textual`)도 같은 방식으로 합니다.
4. 안내문 1절의 Python·`textual` 문장을 사실에 맞게 고칩니다(설치기가 interpreter의 library 경로를 기록하므로 로그인 환경과 무관함, 또는 그 조건).
5. 사내 tmux도 library 경로(libevent 등)가 필요합니다(TMUX-002·RELEASE-003 Result). tmux는 설치기가 고르는 실행 파일이 아니므로 이 CR은 안내문에 필요한 조건을 적는 것까지 합니다.

의존: 선행 없음. 후행 RELEASE-003 F1 재확인, 첫 release.

위험 등급: 중간. 모든 진입점의 interpreter 실행 환경을 바꿉니다.

## Verification
README 검증 표의 `install/**`·`tools/python-launcher.sh` 행(네 번째 명령, `install/tests`)과 문서 행.
1. 재현(수정 전): 격리 HOME에 사내 Python으로 설치한 뒤 `env -i`(LD_LIBRARY_PATH 없음)에서 release의 `bin/project-board --help`가 사내 package를 보지 못함(또는 `python -c 'import sys; print(sys.prefix)'`가 `/usr`).
2. 수정 뒤 같은 환경에서 release 진입점이 설치 때와 같은 `sys.prefix`로 실행되고 `textual`을 import함. `check`가 빈 환경에서도 통과하고, 기록한 library 경로를 지우면 실패를 알림.
3. 개발 checkout 진입점은 기존 `tools/test_python_launcher.py`대로 동작.
