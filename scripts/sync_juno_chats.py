#!/usr/bin/env python3
"""Sync Juno web chat sessions (memory/chat-sessions) → knowledge/conversations/auto/."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

HQ = Path(__file__).resolve().parent.parent
SESSIONS_DIR = HQ / "memory" / "chat-sessions"
OUT_DIR = HQ / "knowledge" / "conversations" / "auto"
STATE_FILE = HQ / "config" / "sync-state.json"


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"synced": {}, "synced_juno": {}}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def session_to_markdown(session: dict) -> str | None:
    msgs = session.get("messages") or []
    if not msgs:
        return None
    sid = session.get("id") or "unknown"
    title = session.get("title") or "新对话"
    created = session.get("created") or ""
    updated = session.get("updated") or ""

    lines = [
        f"# Juno Web Chat · {title}",
        "",
        f"- **Session**: `{sid}`",
        f"- **Source**: `memory/chat-sessions/{sid}.json`",
        f"- **Created**: {created}",
        f"- **Updated**: {updated}",
        f"- **Synced**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
    ]
    for m in msgs:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if not content or role not in ("user", "assistant"):
            continue
        label = "User" if role == "user" else "Juno"
        t = m.get("time") or ""
        lines.append(f"## {label}" + (f" · {t}" if t else ""))
        lines.append("")
        lines.append(content)
        lines.append("")
    return "\n".join(lines)


def sync_session(session_id: str, *, force: bool = False) -> dict:
    """Sync one Juno web session by id. Returns {ok, new, path, skipped}."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fp = SESSIONS_DIR / f"{session_id}.json"
    if not fp.exists():
        return {"ok": False, "error": "session not found", "session_id": session_id}

    state = load_state()
    juno_map: dict = state.setdefault("synced_juno", {})
    key = str(fp)
    mtime = str(fp.stat().st_mtime)

    if not force and juno_map.get(key) == mtime:
        return {"ok": True, "new": 0, "skipped": 1, "session_id": session_id}

    try:
        session = json.loads(fp.read_text(encoding="utf-8"))
        md = session_to_markdown(session)
        if md is None:
            juno_map[key] = mtime
            save_state(state)
            return {"ok": True, "new": 0, "skipped": 1, "session_id": session_id}

        out_path = OUT_DIR / f"juno-{session_id}.md"
        out_path.write_text(md, encoding="utf-8")
        juno_map[key] = mtime
        state["last_juno_sync"] = datetime.now().isoformat(timespec="seconds")
        save_state(state)
        return {
            "ok": True,
            "new": 1,
            "skipped": 0,
            "session_id": session_id,
            "path": str(out_path.relative_to(HQ)).replace("\\", "/"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "session_id": session_id}


def sync_all(*, force: bool = False) -> dict:
    """Sync all Juno web chat sessions."""
    if not SESSIONS_DIR.exists():
        return {"new": 0, "skipped": 0, "errors": [], "sessions": 0}

    new_count = 0
    skip_count = 0
    errors: list[str] = []
    for fp in sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        r = sync_session(fp.stem, force=force)
        if not r.get("ok"):
            errors.append(f"{fp.stem}: {r.get('error', 'unknown')}")
        elif r.get("new"):
            new_count += 1
        else:
            skip_count += 1

    return {
        "new": new_count,
        "skipped": skip_count,
        "errors": errors,
        "sessions": new_count + skip_count,
        "out_dir": str(OUT_DIR),
    }


if __name__ == "__main__":
    import sys

    force = "--force" in sys.argv
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        print(json.dumps(sync_session(sys.argv[1], force=force), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(sync_all(force=force), ensure_ascii=False, indent=2))
