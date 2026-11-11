"""A stand-in `crontab` command for tests: `crontab -l` and `crontab -` over one file.

The product starts `crontab` by name, so a test puts `install(directory)` first on PATH and no test touches the
real user's crontab. `FAKE_CRONTAB` names the file that plays the crontab; a missing file is a user without a
crontab (`crontab -l` fails with the message of cron). `FAKE_CRONTAB_FAIL` makes the named action fail
(`read` or `write`) with that exit status. `FAKE_CRONTAB_LOG` appends one line per call, for tests that
count them.
"""

import os
from pathlib import Path
import stat

# A shell script, not Python: a test calls it several times and a Python start-up costs a second on a loaded host.
SCRIPT = '''#!/bin/sh
[ -n "$FAKE_CRONTAB_LOG" ] && echo "$*" >> "$FAKE_CRONTAB_LOG"
if [ "$1" = "-l" ]; then action=read; else action=write; fi
if [ "$FAKE_CRONTAB_FAIL" = "$action" ]; then echo "crontab: simulated failure" >&2; exit 1; fi
case "$1" in
    -l) if [ ! -e "$FAKE_CRONTAB" ]; then echo "no crontab for tester" >&2; exit 1; fi
        cat "$FAKE_CRONTAB" ;;
    -) cat > "$FAKE_CRONTAB" ;;
    *) exit 2 ;;
esac
'''


def install(directory, crontab_file):
    """Write the shim into `directory` and return the environment variables a process needs to use it."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    shim = directory / "crontab"
    shim.write_text(SCRIPT)
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return {"PATH": str(directory) + os.pathsep + os.environ.get("PATH", ""), "FAKE_CRONTAB": str(crontab_file)}
