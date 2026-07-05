#!/usr/bin/env python3
"""Cursor stop hook: sync Cursor + Juno web chats (fail-open)."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def main() -> int:
    try:
        _ = sys.stdin.read()
    except Exception:
        pass
    for script in ("sync_cursor_chats.py", "sync_juno_chats.py"):
        try:
            subprocess.run(
                [sys.executable, str(SCRIPTS / script)],
                capture_output=True,
                timeout=120,
                check=False,
            )
        except Exception:
            pass
    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
