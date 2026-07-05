#!/usr/bin/env python3
"""Sync Cursor agent-transcripts (.jsonl) into Juno knowledge/conversations/auto/."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

HQ = Path(__file__).resolve().parent.parent
OUT_DIR = HQ / "knowledge" / "conversations" / "auto"
STATE_FILE = HQ / "config" / "sync-state.json"
CURSOR_PROJECTS = Path.home() / ".cursor" / "projects"


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"synced": {}}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def extract_user_text(raw: str) -> str:
    m = re.search(r"<user_query>\s*(.*?)\s*</user_query>", raw, re.DOTALL)
    if m:
        return m.group(1).strip()
    return raw.strip()


def extract_assistant_text(parts: list) -> str:
    texts = []
    for p in parts:
        if not isinstance(p, dict):
            continue
        if p.get("type") == "text":
            t = p.get("text", "")
            if t and t != "[REDACTED]" and not t.startswith("[REDACTED]"):
                t = re.sub(r"\n?\[REDACTED\]", "", t).strip()
                if t:
                    texts.append(t)
    return "\n\n".join(texts)


def jsonl_to_markdown(jsonl_path: Path) -> str | None:
    lines_out: list[str] = []
    session_id = jsonl_path.stem
    project = jsonl_path.parts[-4] if len(jsonl_path.parts) >= 4 else "unknown"

    lines_out.append(f"# Cursor Chat · {session_id[:8]}…")
    lines_out.append("")
    lines_out.append(f"- **Source**: `{jsonl_path}`")
    lines_out.append(f"- **Project**: `{project}`")
    lines_out.append(f"- **Synced**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines_out.append("")
    lines_out.append("---")
    lines_out.append("")

    has_content = False
    for line in jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        role = obj.get("role")
        msg = obj.get("message") or {}
        content = msg.get("content") or []
        if role == "user":
            for p in content:
                if isinstance(p, dict) and p.get("type") == "text":
                    text = extract_user_text(p.get("text", ""))
                    if text:
                        lines_out.append("## User")
                        lines_out.append("")
                        lines_out.append(text)
                        lines_out.append("")
                        has_content = True
        elif role == "assistant":
            text = extract_assistant_text(content)
            if text:
                lines_out.append("## Assistant")
                lines_out.append("")
                lines_out.append(text)
                lines_out.append("")
                has_content = True

    if not has_content:
        return None
    return "\n".join(lines_out)


def find_transcripts() -> list[Path]:
    if not CURSOR_PROJECTS.exists():
        return []
    files: list[Path] = []
    for jsonl in CURSOR_PROJECTS.rglob("*.jsonl"):
        if "subagents" in jsonl.parts:
            continue
        if jsonl.parent.name != jsonl.stem:
            continue
        files.append(jsonl)
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def sync_all(*, force: bool = False) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    synced_map: dict = state.setdefault("synced", {})

    new_count = 0
    skip_count = 0
    errors: list[str] = []

    for jsonl in find_transcripts():
        key = str(jsonl)
        mtime = str(jsonl.stat().st_mtime)
        if not force and synced_map.get(key) == mtime:
            skip_count += 1
            continue
        try:
            md = jsonl_to_markdown(jsonl)
            if md is None:
                synced_map[key] = mtime
                skip_count += 1
                continue
            ts = datetime.fromtimestamp(jsonl.stat().st_mtime).strftime("%Y-%m-%d_%H%M%S")
            out_name = f"{ts}_{jsonl.stem[:8]}.md"
            out_path = OUT_DIR / out_name
            out_path.write_text(md, encoding="utf-8")
            synced_map[key] = mtime
            new_count += 1
        except Exception as e:
            errors.append(f"{jsonl.name}: {e}")

    state["last_sync"] = datetime.now().isoformat(timespec="seconds")
    save_state(state)
    return {
        "new": new_count,
        "skipped": skip_count,
        "total_tracked": len(synced_map),
        "errors": errors,
        "out_dir": str(OUT_DIR),
    }


def main() -> int:
    force = "--force" in sys.argv
    result = sync_all(force=force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
