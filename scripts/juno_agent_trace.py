#!/usr/bin/env python3
"""Agent Trace — port of cursor/agent-trace reference (MIT/CC BY 4.0 spec)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HQ = Path(__file__).resolve().parent.parent
TRACE_DIR = HQ / ".agent-trace"
TRACE_FILE = TRACE_DIR / "traces.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_model_id(model: str | None) -> str | None:
    if not model:
        return None
    if "/" in model:
        return model
    prefixes = {
        "claude-": "anthropic",
        "gpt-": "openai",
        "o1": "openai",
        "o3": "openai",
        "gemini-": "google",
        "deepseek-": "deepseek",
    }
    for prefix, provider in prefixes.items():
        if model.startswith(prefix):
            return f"{provider}/{model}"
    return model


def compute_range_positions(old_string: str, new_string: str, file_content: str | None = None) -> list[dict]:
    """Map str_replace edit to line ranges (agent-trace §6.3)."""
    if not new_string:
        return []
    lines = new_string.splitlines()
    line_count = max(len(lines), 1)
    if file_content and new_string in file_content:
        idx = file_content.index(new_string)
        start = file_content[:idx].count("\n") + 1
        return [{"start_line": start, "end_line": start + line_count - 1}]
    if file_content and old_string and old_string in file_content:
        idx = file_content.index(old_string)
        start = file_content[:idx].count("\n") + 1
        return [{"start_line": start, "end_line": start + line_count - 1}]
    return [{"start_line": 1, "end_line": line_count}]


def create_trace(
    file_path: str | Path,
    *,
    session_id: str | None = None,
    model: str | None = None,
    range_positions: list[dict] | None = None,
    contributor_type: str = "ai",
) -> dict:
    rel = str(file_path).replace("\\", "/")
    ranges = range_positions or [{"start_line": 1, "end_line": 1}]
    conversation: dict[str, Any] = {
        "contributor": {"type": contributor_type, "model_id": normalize_model_id(model)},
        "ranges": ranges,
    }
    if session_id:
        conversation["url"] = f"juno://session/{session_id}"
        conversation["related"] = [{"type": "session", "url": f"juno://session/{session_id}"}]
    return {
        "version": "0.1.0",
        "id": str(uuid.uuid4()),
        "timestamp": _now_iso(),
        "tool": {"name": "juno", "version": "0.4.0"},
        "files": [{"path": rel, "conversations": [conversation]}],
        "metadata": {"dev.juno": {"session_id": session_id}} if session_id else {},
    }


def append_trace(trace: dict) -> None:
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    with TRACE_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(trace, ensure_ascii=False) + "\n")


def list_traces(*, session_id: str | None = None, limit: int = 100) -> list[dict]:
    if not TRACE_FILE.exists():
        return []
    out: list[dict] = []
    for line in TRACE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if session_id:
            meta = (rec.get("metadata") or {}).get("dev.juno") or {}
            if meta.get("session_id") != session_id:
                continue
        out.append(rec)
    return out[-limit:]
