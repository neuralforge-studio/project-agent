"""No test reaches the user's real crontab (TEST-015).

The product starts the `crontab` command found on PATH, so a test replaces it with a shim
(`fake_crontab.py`). A test that sets PATH to something like `<directory>:/usr/bin:/bin` hides that shim and the
product then runs `/usr/bin/crontab` on the user's real spool, with the operating `check` jobs in it
(SESSION-016 found a test section written there). PATH cannot be the safeguard, since a test may set it to
anything.

On Linux `block()` sets `PR_SET_NO_NEW_PRIVS` on the pytest process. The flag is inherited by every child (xdist
workers, the tools a test starts, tmux panes) and cannot be cleared, and an exec under it ignores the set-uid bit.
`crontab` is set-uid root (its spool is `root`-only), so whichever `crontab` a test reaches by whatever PATH, it
runs without that privilege and fails with `Permission denied` for a read as well as a write. The failure is
the product's `crontab_unreadable` or `crontab_unwritable`. A shim is an ordinary script and is not affected.

The cost is that no command of a test can gain privilege (`sudo`, `su`); none of them needs it. Elsewhere there is
no equivalent, so `block()` says so and the run goes on without the safeguard.
"""

import ctypes
import sys
import warnings

PR_SET_NO_NEW_PRIVS = 38


def block():
    """Make the real `crontab` unusable for this process and its descendants; False (with a warning) when this
    platform cannot."""
    reason = "this platform has no PR_SET_NO_NEW_PRIVS"
    if sys.platform.startswith("linux"):
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) == 0:
                return True
            reason = f"prctl failed (errno {ctypes.get_errno()})"
        except (OSError, AttributeError) as error:
            reason = f"prctl is unavailable ({error})"
    warnings.warn(f"The real crontab is not blocked for this run: {reason}. A test must never reach it; check "
                  "`crontab -l` of the user before and after the run.", RuntimeWarning, stacklevel=2)
    return False
