# INSTALL-006: 설치기가 interpreter에 필요한 library 경로를 기록하지 않아, LD_LIBRARY_PATH가 없는 환경에서 사내 Python이 다른 Python처럼 동작합니다

- Opened: 2026-11-09
- Scope: project-agent
- Severity: S2
- Base: a50c23a3e251def5c0aeca54f641f0ed69f5eeb6 2026-11-09T19:57:07+09:00

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
- 2026-11-09 Leader: 제출 4be6c8cd9b500f7e7ed63756a72593f961b77f90를 인수합니다. Leader review: 설치기가 빈 환경에서 interpreter의 sys.prefix를 시험해 같은 interpreter로 뜨게 하는 library 경로를 python.env(PROJECT_AGENT_LD_LIBRARY_PATH)에 기록하고, 없으면 python_environment로 거절, launcher가 그 경로를 앞에 붙이며, check가 빈 환경에서 sys.prefix를 대조함을 확인했습니다. 수정 전 재현(env -i에서 sys.prefix=/usr, textual 없음)과 수정 뒤(사내 prefix, textual 8.2.8 import), README 표대로 네 번째 명령 91·install/tests 260 passed. 알려진 한계: 설치기를 사내 환경 없이 실행하면 그때의 interpreter(/usr prefix)를 기록함(안내문에 사내 환경에서 실행하라고 적음). Worker의 git stash 사용은 전역 규칙 위반(영향 없음).

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

## Result
- 제출 commit: 4be6c8cd9b500f7e7ed63756a72593f961b77f90

`origin/cr/INSTALL-006`에 push했습니다. 기능 commit은 `bd858ae`이고, `4be6c8c`는 `origin/main`(`e20caee`, CR 문서 두 개만 바뀜)을 merge한 것입니다.

변경:
- 설치기(`release.py`·`commands.py`): 설치 interpreter를 빈 환경(`PATH`만)에서 실행해 `sys.prefix`를 시험합니다. 설치기 자신의 `sys.prefix`와 같으면 library 경로는 빈 값, 다르면 `<prefix>/lib`, 그다음 `sysconfig`의 `LIBDIR`을 시험해 처음 같아지는 경로를 `python.env`의 `PROJECT_AGENT_LD_LIBRARY_PATH`에 적습니다. 어느 것도 같아지지 않으면 `python_environment`로 거절합니다(종료 코드 3, 변경 전). `check`가 비교할 설치 때의 `sys.prefix`를 `PROJECT_AGENT_PYTHON_PREFIX`로 함께 적습니다(launcher는 이 이름을 무시합니다).
- launcher(`tools/python-launcher.sh`): `PROJECT_AGENT_PYTHON`을 쓸 때 `PROJECT_AGENT_LD_LIBRARY_PATH`를 `LD_LIBRARY_PATH` 앞에 붙이고 export합니다. 환경 변수가 파일보다 우선합니다. 개발 checkout 규칙은 그대로입니다.
- `check`: launcher를 거쳐 설치 interpreter를 빈 환경에서 실행해 `sys.prefix`가 설치 때와 다르면 실패로 알립니다. `textual` 확인도 같은 방식이며 안내(notice)로 남습니다. 이전에는 사용자의 `LD_LIBRARY_PATH`가 누락을 가렸습니다.
- 문서: 설치 계약 6.1절(변수 표·`python.env` 형식·설치 때의 interpreter 시험)·2절·7절 `check` 항목·8.2절 T33, 안내문 1절(library 경로 기록, `textual`, 사내 tmux의 library 조건)·8절 문제 표.
- Implementation 5(사내 tmux): 설치기는 tmux를 고르지 않으므로 안내문 1절에 필요한 `LD_LIBRARY_PATH` 조건을 적는 데까지 했습니다.

검증:
1. 수정 전 재현(격리 HOME, 사내 Python으로 설치): `python.env`는 interpreter 경로뿐이었고, `env -i`에서 `sys.prefix=/usr`, `import textual`이 ModuleNotFoundError, `project-board`(인자 없음)도 `ModuleNotFoundError: textual`이었습니다.
2. 수정 후 같은 시나리오(격리 HOME, commit된 checkout에서 설치): `python.env`에 `PROJECT_AGENT_LD_LIBRARY_PATH=/primehome/tools/Inhouse/Python3/latest/lib`, `PROJECT_AGENT_PYTHON_PREFIX=/primehome/tools/Inhouse/Python3/latest`가 적혔고, `env -i`로 launcher를 거친 interpreter가 `sys.prefix=/primehome/tools/Inhouse/Python3/latest`, `textual 8.2.8`을 import했습니다. `project-board --help`가 실행됩니다. 빈 환경의 `check`는 interpreter 항목에서 실패·안내가 없고, 남은 FAIL은 PATH를 `/usr/bin:/bin`으로 줄인 탓의 시스템 tmux 2.7뿐입니다(이 CR 범위 밖).
3. 새 test: `install/tests/test_interpreter_environment.py` 7개(흉내 interpreter로 library 경로 기록·불필요·거절, 실제 interpreter의 `python.env` 내용을 독립 시험으로 확인, 빈 환경의 진입점·launcher·`check`, 설치 때 값을 틀리게 하거나 library 경로를 지우면 `check` 실패). `tools/test_python_launcher.py`에 4개(앞에 붙임·사용자 값이 없을 때·환경 변수 우선·개발 checkout 규칙 불변)를 더했습니다. `test_install.py`의 `python.env` 확인은 새 줄을 허용하도록 `startswith`로 바꿨습니다.
4. README 검증 표 `install/**`·`tools/python-launcher.sh` 행 명령(수정 commit `bd858ae`의 트리에서):
   - `python -m pytest -q integrations/tmux tools/test_python_launcher.py tools/test_distribution_boundary.py tools/test_private_root.py tools/test_release_files.py tools/test_tmux_test_server.py` → 91 passed
   - `python -m pytest -q -n 8 install/tests` → 260 passed, 2 skipped(기존 skip). 새 파일은 따로 다시 실행해 7 passed, skip 없음.
   - 문서 행은 별도 명령이 없어 위 시나리오 2로 갈음했고, 계약·안내문은 코드와 대조했습니다.
5. 근거 재사용: 마지막 merge(`4be6c8c`)는 CR 문서 두 개만 바꿨으므로 검증 입력이 같아 테스트를 다시 실행하지 않았습니다.

참고:
- 설치기가 이미 `LD_LIBRARY_PATH` 없이 떠서 `sys.prefix=/usr`인 상태로 실행되면 "같은 interpreter"가 `/usr`이므로 library 경로는 빈 값으로 기록되고 거절하지 않습니다(CR의 "설치기를 실행한 interpreter와 같은 `sys.prefix`" 기준). 사내 Python으로 설치할 때는 사내 환경이 있는 셸에서 실행해야 합니다.
- 작업 중 실수로 `git stash`를 한 번 실행했습니다(내용이 작업 트리와 같음을 확인하고 즉시 `drop`, stash 목록은 비어 있고 변경은 그대로입니다). 이 일 때문에 저장소 상태가 바뀐 것은 없습니다.
- 이 workstation의 실제 `~/.local`은 건드리지 않았습니다(시범은 scratchpad 아래 격리 HOME).
