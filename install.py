#!/usr/bin/env python3
"""Install or restore a copied project-agent distribution."""

import sys


def main():
    if sys.version_info < (3, 11):
        print('project-agent: Python 3.11 or later is required.', file=sys.stderr)
        return 2

    import argparse
    import json
    from pathlib import Path

    from project_agent_install import InstallError, check, install, rollback

    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='check files and destinations without writing')
    mode.add_argument('--rollback', action='store_true', help='restore the previous installer-owned links')
    args = parser.parse_args()
    try:
        if args.rollback:
            result = rollback(Path.home())
        else:
            action = check if args.check else install
            result = action(Path(__file__).resolve().parent, Path.home())
    except (InstallError, OSError) as exc:
        print(json.dumps({'ok': False, 'error': getattr(exc, 'code', 'filesystem_error'),
                          'message': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({'ok': True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
