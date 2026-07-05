#!/usr/bin/env python3
"""Lightweight autonomous learning from synced Juno / Cursor conversations."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

HQ = Path(__file__).resolve().parent.parent
SESSIONS_DIR = HQ / "memory" / "chat-sessions"
DAILY_DIR = HQ / "memory" / "daily"
MEMORY = HQ / "MEMORY.md"
TRAINING = HQ / "training" / "examples.jsonl"
STATE_FILE = HQ / "config" / "sync-state.json"

REMEMBER_RE = re.compile(
    r"(记住|记得|别忘了|帮我记|请记住|remember\s+this|don'?t\s+forget)",
    re.I,
)
CASUAL_RE = re.compile(
    r"^(hi|hello|hey|你好|嗨|在吗|在不在|哈喽|yo|谢谢|好的|ok|嗯|哦)[\s!！。~～]*$",
    re.I,
)


def _today_file() -> Path:
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    return DAILY_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.md"


def _clip(text: str, n: int = 120) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    return t if len(t) <= n else t[: n - 1] + "…"


def append_daily(line: str) -> None:
    fp = _today_file()
    stamp = datetime.now().strftime("%H:%M")
    block = f"- **{stamp}** {line}\n"
    if fp.exists():
        fp.write_text(fp.read_text(encoding="utf-8") + block, encoding="utf-8")
    else:
        fp.write_text(f"# {datetime.now().strftime('%Y-%m-%d')} · Juno 对话日志\n\n{block}", encoding="utf-8")


def append_memory_auto(fact: str) -> None:
    section = "## 自动沉淀（Juno 对话 · 实时）"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"- **{stamp}** {fact.strip()}\n"
    text = MEMORY.read_text(encoding="utf-8") if MEMORY.exists() else ""
    if section in text:
        parts = text.split(section, 1)
        head, tail = parts[0], parts[1]
        lines = [ln for ln in tail.splitlines() if ln.strip().startswith("- ")]
        lines.append(entry.strip())
        # keep last 40 auto entries
        lines = lines[-40:]
        body = "\n".join(lines) + "\n"
        MEMORY.write_text(head + section + "\n\n" + body, encoding="utf-8")
    else:
        MEMORY.write_text(
            text.rstrip() + f"\n\n{section}\n\n{entry}",
            encoding="utf-8",
        )


def maybe_add_training_example(question: str, answer: str) -> bool:
    if len(question) < 12 or CASUAL_RE.match(question):
        return False
    if len(answer) < 20:
        return False
    rows = []
    if TRAINING.exists():
        for line in TRAINING.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    for row in rows[:50]:
        if row.get("question", "").strip() == question.strip():
            return False
    TRAINING.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "question": question.strip(),
        "answer": answer.strip(),
        "tags": ["auto-learn", "juno-web"],
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    with TRAINING.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True


def learn_from_session(session_id: str) -> dict:
    fp = SESSIONS_DIR / f"{session_id}.json"
    if not fp.exists():
        return {"ok": False, "error": "session not found"}

    session = json.loads(fp.read_text(encoding="utf-8"))
    msgs = session.get("messages") or []
    if len(msgs) < 2:
        return {"ok": True, "learned": 0}

    last_user = next((m for m in reversed(msgs) if m.get("role") == "user"), None)
    last_asst = next((m for m in reversed(msgs) if m.get("role") == "assistant"), None)
    if not last_user or not last_asst:
        return {"ok": True, "learned": 0}

    u = (last_user.get("content") or "").strip()
    a = (last_asst.get("content") or "").strip()
    title = session.get("title") or session_id[:8]

    result = {"ok": True, "session_id": session_id, "daily": False, "memory": False, "training": False}

    append_daily(f"[{title}] 俊呈：{_clip(u)} → Juno：{_clip(a)}")
    result["daily"] = True

    if REMEMBER_RE.search(u):
        fact = u
        for prefix in ("记住", "记得", "别忘了", "帮我记", "请记住"):
            fact = re.sub(rf"^{prefix}[：:,\s]*", "", fact, flags=re.I)
        if len(fact) < 4:
            fact = u
        append_memory_auto(fact)
        result["memory"] = True

    if maybe_add_training_example(u, a):
        result["training"] = True

    state = {}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    state["last_auto_learn"] = datetime.now().isoformat(timespec="seconds")
    state["last_auto_learn_session"] = session_id
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    result["learned"] = int(result["daily"]) + int(result["memory"]) + int(result["training"])
    return result


if __name__ == "__main__":
    import sys

    sid = sys.argv[1] if len(sys.argv) > 1 else ""
    if not sid:
        print(json.dumps({"ok": False, "error": "session_id required"}, ensure_ascii=False))
    else:
        print(json.dumps(learn_from_session(sid), ensure_ascii=False, indent=2))
