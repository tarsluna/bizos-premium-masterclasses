#!/usr/bin/env python3
"""Short-lived credential helper; never saves credentials in Git config or remotes."""
import os
from pathlib import Path
import sys

if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] == 'get':
    fields = dict(line.rstrip('\n').split('=', 1) for line in sys.stdin if '=' in line)
    if fields.get('protocol') == 'https' and fields.get('host') == 'github.com':
        print('username=x-access-token')
        print('password=' + Path(os.environ['BIZOS_GITHUB_TOKEN_FILE']).read_text().strip())
