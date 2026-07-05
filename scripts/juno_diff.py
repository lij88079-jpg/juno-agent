#!/usr/bin/env python3
"""Line-level diff hunks for Cursor-style Accept/Reject."""
from __future__ import annotations

import difflib
from pathlib import Path


def build_hunks(old_text: str, new_text: str, *, context: int = 2) -> list[dict]:
    """Build hunk list from before/after snippet (str_replace)."""
    old_lines = (old_text or "").splitlines()
    new_lines = (new_text or "").splitlines()
    hunks: list[dict] = []
    for i, grp in enumerate(difflib.SequenceMatcher(None, old_lines, new_lines).get_opcodes()):
        tag, i1, i2, j1, j2 = grp
        if tag == "equal":
            continue
        lo = max(0, i1 - context)
        hi = min(len(old_lines), i2 + context)
        ln = max(0, j1 - context)
        hn = min(len(new_lines), j2 + context)
        hunks.append(
            {
                "id": f"h{i}",
                "tag": tag,
                "old_start": i1 + 1,
                "old_end": i2,
                "new_start": j1 + 1,
                "new_end": j2,
                "old_string": "\n".join(old_lines[i1:i2]),
                "new_string": "\n".join(new_lines[j1:j2]),
                "context_before": "\n".join(old_lines[lo:i1]),
                "context_after": "\n".join(old_lines[i2:hi]),
                "preview_old": "\n".join(f"- {l}" for l in old_lines[lo:hi]),
                "preview_new": "\n".join(f"+ {l}" for l in new_lines[ln:hn]),
                "status": "pending",
            }
        )
    if not hunks and old_text != new_text:
        hunks.append(
            {
                "id": "h0",
                "tag": "replace",
                "old_string": old_text,
                "new_string": new_text,
                "preview_old": "\n".join(f"- {l}" for l in old_lines[:12]),
                "preview_new": "\n".join(f"+ {l}" for l in new_lines[:12]),
                "status": "pending",
            }
        )
    return hunks


def apply_hunk_action(file_path: str, hunk: dict, action: str) -> dict:
    """accept = keep new; reject = revert old_string back."""
    action = (action or "").strip().lower()
    fp = Path(file_path)
    if not fp.is_file():
        return {"ok": False, "error": "文件不存在"}
    try:
        text = fp.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"ok": False, "error": str(e)}
    old_s = hunk.get("old_string") or ""
    new_s = hunk.get("new_string") or ""
    if action == "accept":
        hunk["status"] = "accepted"
        return {"ok": True, "path": str(fp), "action": "accept", "hunk_id": hunk.get("id")}
    if action == "reject":
        if new_s and new_s in text:
            text = text.replace(new_s, old_s, 1)
        elif old_s and old_s not in text:
            return {"ok": False, "error": "无法定位 hunk，请用文件级 Reject"}
        try:
            fp.write_text(text, encoding="utf-8")
        except OSError as e:
            return {"ok": False, "error": str(e)}
        hunk["status"] = "rejected"
        return {"ok": True, "path": str(fp), "action": "reject", "hunk_id": hunk.get("id")}
    return {"ok": False, "error": f"未知 action: {action}"}
