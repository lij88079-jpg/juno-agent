#!/usr/bin/env python3
"""IDE / workspace context injection (open files, cursor selection)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

HQ = Path(__file__).resolve().parent.parent
CTX_FILE = HQ / "memory" / "ide-context.json"


def save_context(payload: dict) -> dict:
    CTX_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "open_files": payload.get("open_files") or [],
        "active_file": payload.get("active_file") or "",
        "selection": payload.get("selection") or "",
        "workspace": payload.get("workspace") or "",
    }
    CTX_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, **data}


def load_context() -> dict:
    if not CTX_FILE.exists():
        return {}
    try:
        return json.loads(CTX_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def format_for_prompt(*, max_files: int = 4, max_chars: int = 6000) -> str:
    ctx = load_context()
    files = ctx.get("open_files") or []
    if not files and not ctx.get("active_file"):
        return ""

    lines = ["## IDE 上下文（用户当前打开的文件 · 优先参考）"]
    if ctx.get("workspace"):
        lines.append(f"工作区：`{ctx['workspace']}`")
    if ctx.get("active_file"):
        lines.append(f"当前文件：`{ctx['active_file']}`")
    if ctx.get("selection"):
        lines.append(f"选区：\n```\n{str(ctx['selection'])[:1200]}\n```")

    used = 0
    for i, f in enumerate(files[:max_files], 1):
        path = f.get("path") or f.get("name") or "?"
        content = (f.get("content") or "")[:2000]
        if not content:
            continue
        block = f"\n### [{i}] `{path}`\n```\n{content}\n```"
        if used + len(block) > max_chars:
            break
        lines.append(block)
        used += len(block)
    return "\n".join(lines)
