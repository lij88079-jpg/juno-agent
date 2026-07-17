#!/usr/bin/env python3
"""Kill process on port 8765 and restart Juno server."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

PORT = 8765
SCRIPTS = Path(__file__).resolve().parent
SERVER = SCRIPTS / "juno_training_server.py"


def kill_port(port: int) -> list[int]:
    killed: list[int] = []
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(["netstat", "-ano"], text=True, errors="replace")
        except subprocess.CalledProcessError:
            return killed
        for line in out.splitlines():
            if f":{port}" not in line or "LISTENING" not in line.upper():
                continue
            parts = line.split()
            if not parts:
                continue
            try:
                pid = int(parts[-1])
            except ValueError:
                continue
            if pid <= 0 or pid in killed:
                continue
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            killed.append(pid)
    return killed


def main() -> int:
    killed = kill_port(PORT)
    if killed:
        print(f"killed pids: {killed}")
        time.sleep(1)
    subprocess.Popen(
        [sys.executable, str(SERVER)],
        cwd=str(SCRIPTS),
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    print("started juno_training_server.py")
    time.sleep(4)
    try:
        import urllib.request
        import json

        d = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/chat/status", timeout=8).read())
        print("build:", d.get("build"))
        print("mode:", d.get("mode"), "chat_backend:", d.get("chat_backend"))
        if d.get("build") != "2026-07-07-hybrid-cursor":
            print("WARN: old code still running?")
            return 2
    except Exception as e:
        print("status check failed:", e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
