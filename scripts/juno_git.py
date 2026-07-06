#!/usr/bin/env python3
"""Git workflow tool — status/diff/log/commit (user must explicitly request commit)."""
from __future__ import annotations

import subprocess
from pathlib import Path

HQ = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], *, cwd: Path) -> dict:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return {"ok": proc.returncode == 0, "code": proc.returncode, "output": out[:8000]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def git_workflow(action: str, *, message: str = "", paths: list[str] | None = None, cwd: str = "") -> dict:
    action = (action or "status").strip().lower()
    work = Path(cwd).resolve() if cwd else HQ
    if not (work / ".git").exists():
        work = HQ

    if action == "status":
        return _run(["git", "status", "--short"], cwd=work)
    if action == "diff":
        return _run(["git", "diff"], cwd=work)
    if action == "log":
        return _run(["git", "log", "-5", "--oneline"], cwd=work)
    if action == "commit":
        if not message.strip():
            return {"ok": False, "error": "commit 需要 message；仅用户明确要求时才能 commit"}
        add_args = ["git", "add"] + (paths or ["."])
        st = _run(add_args, cwd=work)
        if not st.get("ok"):
            return st
        return _run(["git", "commit", "-m", message.strip()], cwd=work)
    return {"ok": False, "error": f"未知 action: {action}（status/diff/log/commit）"}
