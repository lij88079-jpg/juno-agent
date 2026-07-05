#!/usr/bin/env python3
"""Real-time pipeline: sync Juno web chat + Cursor chats + auto-learn."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HQ = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent


def run_py(script: str, *args: str) -> dict:
    cmd = [sys.executable, str(SCRIPTS / script), *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=120)
        if proc.stdout.strip():
            return json.loads(proc.stdout.strip())
        return {"ok": False, "error": proc.stderr.strip() or "empty output"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def after_chat_turn(session_id: str) -> dict:
    """Called after each Juno web chat reply completes."""
    out = {"session_id": session_id, "juno_sync": None, "cursor_sync": None, "learn": None}
    out["juno_sync"] = run_py("sync_juno_chats.py", session_id)
    out["learn"] = run_py("juno_auto_learn.py", session_id)
    # Also refresh Cursor transcripts (fail-open, incremental)
    out["cursor_sync"] = run_py("sync_cursor_chats.py")
    return out


def sync_all() -> dict:
    return {
        "juno": run_py("sync_juno_chats.py"),
        "cursor": run_py("sync_cursor_chats.py"),
    }


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "--all":
        print(json.dumps(after_chat_turn(sys.argv[1]), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(sync_all(), ensure_ascii=False, indent=2))
